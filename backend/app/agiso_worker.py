"""Durable inbox/outbox worker, with leases and no automatic ambiguous resend."""
import asyncio
import logging
from . import agiso_protocol as protocol
from .agiso_service import apply_trade, apply_refund, executable, order_allowed, integration_id
from .db import uid

log=logging.getLogger(__name__)


class AgisoWorker:
    def __init__(self,db,clock,transport=None):
        self.db,self.clock,self.transport=db,clock,transport
        self.id=uid();self.task=None

    def recover(self):
        now=self.clock()
        with self.db.transaction() as tx:
            for row in tx.all('agiso_events'):
                if row['status']=='processing' and row.get('lease_until',0)<=now:
                    row.update(status='pending',lease_until=0);tx.put('agiso_events',row)
            for row in tx.all('agiso_outbox'):
                if row['status'] in {'sending','claimed'} and row.get('lease_until',0)<=now:
                    row.update(status='unknown' if row['status']=='sending' else 'pending',lease_until=0)
                    tx.put('agiso_outbox',row)
                    linked=tx.get('agiso_orders',row['integration_id'])
                    if linked:
                        linked.update(message_status=row['status'],error='send_unknown' if row['status']=='unknown' else linked.get('error'))
                        tx.put('agiso_orders',linked)

    def process_event(self):
        config=protocol.settings()
        if not config['configured']: return False
        with self.db.transaction() as tx:
            def eligible(event):
                # Signed refund facts do not require an active outbound authorization
                # or an enabled auto-opening switch. Recover earlier switch-blocked facts.
                if event['topic']!='1' and config['aftersales_enabled'] and tx.get('agiso_shops',event['shop_id']):
                    if event['status']=='blocked' or event['status']=='disabled' and event.get('error')=='shop_disabled':return True
                if event['status']=='pending':return True
                if event['status']!='blocked' or not executable(tx,tx.get('agiso_shops',event['shop_id']),self.clock()):return False
                if event.get('error')=='aftersales_pending':
                    link=tx.get('agiso_orders',integration_id(event['shop_id'],event['payload']['Tid']))
                    return bool(link and not link.get('holds') and link['open_status'] not in {'cancelled','manual'})
                return True
            rows=[r for r in tx.all('agiso_events') if eligible(r)]
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
            elif config['aftersales_enabled']:
                apply_refund(tx,shop,row['payload'],self.clock())
                row.update(status='processed',error=None)
            else:row.update(status='disabled',error='aftersales_disabled')
            tx.put('agiso_events',row)
            return True

    def claim_message(self):
        config=protocol.settings();now=self.clock()
        if not config['configured']:return None
        with self.db.transaction() as tx:
            if any(e['status']=='pending' for e in tx.all('agiso_events')): return None
            if any(j['status'] in {'claimed','sending'} and j.get('lease_until',0)>now for j in tx.all('agiso_outbox')):return None
            rate=tx.get('agiso_rate','send') or {'id':'send','next_at':0}
            if rate['next_at']>now:return None
            for job in tx.all('agiso_outbox'):
                if job['status']!='pending' or job['next_at']>now:continue
                link=tx.get('agiso_orders',job['integration_id']);shop=tx.get('agiso_shops',job['shop_id'])
                order=tx.get('orders',link.get('customer_order_id') or '')
                if not executable(tx,shop,now) or not order_allowed(tx,order) or link.get('holds') or link['send_attempts']>=5:continue
                job.update(status='claimed',worker_id=self.id,run_id=uid(),lease_until=now+60)
                tx.put('agiso_outbox',job)
                rate['next_at']=now+0.1;tx.put('agiso_rate',rate)
                return job
        return None

    async def execute_message(self,job):
        if not job:return
        config=protocol.settings();now=self.clock()
        with self.db.transaction() as tx:
            current=tx.get('agiso_outbox',job['id'])
            if not current or current['status']!='claimed' or current.get('run_id')!=job['run_id'] or current.get('worker_id')!=self.id:return
            link=tx.get('agiso_orders',current['integration_id']);shop=tx.get('agiso_shops',current['shop_id'])
            order=tx.get('orders',link.get('customer_order_id') or '')
            pending_refund=any(e['status']=='pending' and e['topic']!='1' and e['shop_id']==shop['id'] for e in tx.all('agiso_events'))
            if not config['configured'] or not executable(tx,shop,now) or not order_allowed(tx,order) or link.get('holds') or pending_refund or link['send_attempts']>=5:
                current.update(status='pending',lease_until=0);tx.put('agiso_outbox',current);return
            current.update(status='sending',attempts=current['attempts']+1,lease_until=now+60)
            link.update(send_attempts=link['send_attempts']+1,message_status='sending')
            tx.put('agiso_outbox',current);tx.put('agiso_orders',link)
        # Mark uncertainty durably before network I/O; never hold a SQLite transaction here.
        try:
            response=await protocol.api('ImMsg/SendMsg',{'tid':link['tid'],'msg':'您的头像贴纸订单已开通，请打开链接并使用订单号登录：'+link['guest_url']+' 订单号：'+link['order_number']},shop,config,self.transport,now)
            status='sent' if response['IsSuccess'] is True else 'retry' if response.get('AllowRetry') is True else 'failed'
        except asyncio.CancelledError:
            self.finish_message(job,'unknown');raise
        except Exception:
            status='unknown'
        self.finish_message(job,status)

    def finish_message(self,job,status):
        with self.db.transaction() as tx:
            current=tx.get('agiso_outbox',job['id'])
            if not current or current.get('run_id')!=job['run_id'] or current['status']!='sending':return
            link=tx.get('agiso_orders',current['integration_id'])
            retry=status=='retry' and current['attempts']<3 and link['send_attempts']<5
            current.update(status='pending' if retry else 'failed' if status=='retry' else status,
                           retry_safe=status=='retry',next_at=self.clock()+30,lease_until=0)
            link.update(message_status=current['status'],error=None if status=='sent' else 'send_unknown' if status=='unknown' else 'send_failed')
            tx.put('agiso_outbox',current);tx.put('agiso_orders',link)

    async def process_once(self):
        self.recover()
        if self.process_event():return True
        job=self.claim_message()
        if job:await self.execute_message(job);return True
        return False

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
