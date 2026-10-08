"""Durable order-event worker; website-originated messages are retired."""
import asyncio
import logging
from . import agiso_protocol as protocol
from .agiso_service import apply_trade, apply_refund, apply_memo, event_family, event_tid, executable, integration_id, open_trade
from .agiso_platforms import ADAPTERS
from .platforms import platform_of

FETCH_ATTEMPTS=5
from .db import uid

log=logging.getLogger(__name__)


class AgisoWorker:
    def __init__(self,db,clock,transport=None):
        self.db,self.clock,self.transport=db,clock,transport
        self.id=uid();self.task=None

    async def submitted_remark(self,order_id):
        from .remark_sync import sync_submitted
        try:await sync_submitted(self.db,order_id,self.transport,self.clock)
        except Exception:log.exception('Seller remark sync failed')

    def recover(self):
        now=self.clock()
        with self.db.transaction() as tx:
            for row in tx.where('agiso_events','status','processing'):
                if row['status']=='processing' and row.get('lease_until',0)<=now:
                    row.update(status='pending',lease_until=0);tx.put('agiso_events',row)

    def process_event(self):
        config=protocol.settings()
        if not config['configured']: return False
        with self.db.transaction() as tx:
            def eligible(event):
                # Signed refund facts do not require an active outbound authorization
                # or an enabled auto-opening switch. Recover earlier switch-blocked facts.
                if event_family(event)!='trade' and protocol.aftersales_for(config,tx.get('agiso_shops',event['shop_id'])):
                    if event['status']=='blocked' or event['status']=='disabled' and event.get('error') in {'shop_disabled','aftersales_disabled'}:return True
                if event['status']=='pending':return True
                if event['status']!='blocked' or not executable(tx,tx.get('agiso_shops',event['shop_id']),self.clock()):return False
                if event.get('error')=='aftersales_pending':
                    link=tx.get('agiso_orders',integration_id(event['shop_id'],event_tid(event)))
                    return bool(link and not link.get('holds') and link['open_status'] not in {'cancelled','manual'})
                return True
            # eligible() only accepts pending, blocked or disabled events.
            rows=[r for r in tx.where('agiso_events','status','pending','blocked','disabled') if eligible(r)]
            # Refund admission precedes trade opening and every outbound send.
            row=min(rows,key=lambda r:(event_family(r)=='trade',r['received_at']),default=None)
            if not row:return False
            shop=tx.get('agiso_shops',row['shop_id'])
            family=event_family(row)
            if not shop or family=='trade' and not executable(tx,shop,self.clock()):
                reason='shop_disabled' if not shop or not shop.get('enabled') else 'authorization_expired' if shop.get('expires_at',0)<=self.clock() else 'account_disabled'
                row.update(status='blocked',error=reason);tx.put('agiso_events',row);return True
            if family=='trade':
                # Douyin/Xiaohongshu trades carry the normalized order read by fetch_once.
                link=open_trade(tx,shop,row['trade'],config,self.clock()) if row.get('trade') else apply_trade(tx,shop,row['payload'],config,self.clock())
                row.update(status='processed' if link['open_status']=='opened' else 'blocked' if link['open_status']=='held' else 'manual',error=link.get('error'))
            elif family=='memo':
                apply_memo(tx,shop,row['payload'],self.clock())
                row.update(status='processed',error=None)
            elif protocol.aftersales_for(config,shop):
                apply_refund(tx,shop,row.get('refund') or row['payload'],self.clock())
                row.update(status='processed',error=None)
            else:row.update(status='disabled',error='aftersales_disabled')
            tx.put('agiso_events',row)
            return True

    def claim_message(self):
        # Legacy outbox records are retained for audit, never consumed again.
        return None

    async def execute_message(self,job):
        # Reject even a previously claimed job: only the merchant platform sends.
        return

    async def fetch_once(self):
        """Douyin/Xiaohongshu: read Order/Detail outside any transaction. A trade gets its SKUs; an event
        whose shop id matched no shop is assigned to the authorized shop of that platform able to read
        the order, and that id is remembered for later pushes. Failures back off, then go to manual."""
        config=protocol.settings()
        if not config['configured']:return False
        now=self.clock()
        with self.db.transaction() as tx:
            row=next((e for e in tx.where('agiso_events','status','fetch','unmatched') if e['status'] in {'fetch','unmatched'} and e.get('lease_until',0)<=now),None)
            if not row:return False
            if row['shop_id']:
                shop=tx.get('agiso_shops',row['shop_id'])
                if not shop or not shop.get('token') or shop.get('expires_at',0)<=now:
                    # Wait for reauthorization without spending attempts.
                    row.update(lease_until=now+300,error='authorization_expired');tx.put('agiso_events',row);return True
                candidates=[shop]
            else:
                candidates=[s for s in tx.all('agiso_shops') if platform_of(s)==row['platform'] and s.get('token') and s.get('expires_at',0)>now]
            row.update(lease_until=now+60,attempts=row.get('attempts',0)+1);tx.put('agiso_events',row)
        adapter=ADAPTERS[row['platform']];found=None;trade=None
        for shop in candidates:
            try:
                trade=await adapter.trade(shop,row['tid'],config,self.transport,now);found=shop;break
            except Exception as error:
                log.warning('Agiso %s order lookup failed: %s',row['platform'],type(error).__name__)
        with self.db.transaction() as tx:
            latest=tx.get('agiso_events',row['id'])
            if not latest or latest['status'] not in {'fetch','unmatched'}:return True
            if not found:
                if latest['attempts']>=FETCH_ATTEMPTS:
                    latest.update(status='manual',error='order_lookup_failed' if latest['shop_id'] else 'unknown_shop')
                else:latest.update(lease_until=now+30*latest['attempts'])
            else:
                shop=tx.get('agiso_shops',found['id'])
                if not latest['shop_id']:
                    keys=set(shop.get('push_keys',[]))|{latest['shop_key']}
                    shop['push_keys']=sorted(k for k in keys if k);tx.put('agiso_shops',shop)
                    latest['shop_id']=shop['id']
                if latest['family']=='trade':
                    latest['trade']=trade
                    latest.update(status='pending' if shop.get('enabled') else 'disabled',error=None if shop.get('enabled') else 'shop_disabled')
                else:latest.update(status='pending',error=None)
            tx.put('agiso_events',latest)
            return True

    async def process_once(self):
        self.recover()
        fetched=await self.fetch_once()
        return self.process_event() or fetched

    async def start(self):
        if self.task:return
        self.recover()
        async def run():
            while True:
                try:await self.process_once()
                except asyncio.CancelledError:raise
                except Exception:log.error('Agiso worker step failed; durable job retained')
                await asyncio.sleep(0.25)
        self.task=asyncio.create_task(run())

    async def stop(self):
        if self.task:
            self.task.cancel()
            try:await self.task
            except asyncio.CancelledError:pass
            self.task=None
