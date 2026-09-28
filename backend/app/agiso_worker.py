"""Durable order-event worker; website-originated messages are retired."""
import asyncio
import logging
from . import agiso_protocol as protocol
from .agiso_service import apply_trade, apply_refund, apply_memo, executable, integration_id
from .db import uid

log=logging.getLogger(__name__)


class AgisoWorker:
    def __init__(self,db,clock,transport=None):
        self.db,self.clock,self.transport=db,clock,transport
        self.id=uid();self.task=None

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
                if event['topic']!='1' and config['aftersales_enabled'] and tx.get('agiso_shops',event['shop_id']):
                    if event['status']=='blocked' or event['status']=='disabled' and event.get('error') in {'shop_disabled','aftersales_disabled'}:return True
                if event['status']=='pending':return True
                if event['status']!='blocked' or not executable(tx,tx.get('agiso_shops',event['shop_id']),self.clock()):return False
                if event.get('error')=='aftersales_pending':
                    link=tx.get('agiso_orders',integration_id(event['shop_id'],event['payload']['Tid']))
                    return bool(link and not link.get('holds') and link['open_status'] not in {'cancelled','manual'})
                return True
            # eligible() only accepts pending, blocked or disabled events.
            rows=[r for r in tx.where('agiso_events','status','pending','blocked','disabled') if eligible(r)]
            # Refund admission precedes trade opening and every outbound send.
            row=min(rows,key=lambda r:(r['topic']=='1',r['received_at']),default=None)
            if not row:return False
            shop=tx.get('agiso_shops',row['shop_id'])
            if not shop or row['topic']=='1' and not executable(tx,shop,self.clock()):
                reason='shop_disabled' if not shop or not shop.get('enabled') else 'authorization_expired' if shop.get('expires_at',0)<=self.clock() else 'account_disabled'
                row.update(status='blocked',error=reason);tx.put('agiso_events',row);return True
            if row['topic']=='1':
                link=apply_trade(tx,shop,row['payload'],config,self.clock())
                row.update(status='processed' if link['open_status']=='opened' else 'blocked' if link['open_status']=='held' else 'manual',error=link.get('error'))
            elif row['topic']=='64':
                apply_memo(tx,shop,row['payload'],self.clock())
                row.update(status='processed',error=None)
            elif config['aftersales_enabled']:
                apply_refund(tx,shop,row['payload'],self.clock())
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

    async def process_once(self):
        self.recover()
        return self.process_event()

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
