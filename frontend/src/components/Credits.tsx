import { useEffect, useRef, useState } from 'react'
import { RefreshCw } from 'lucide-react'
import { api, ApiError, post } from '../lib/api'
import { Empty, Modal, Spinner, useNotice } from './UI'
import '../pages/Accounts.css'

export interface CreditsWallet {available:number;frozen:number;spent:number;version:number;exempt:boolean}
interface Ledger {id:string;created_at:string;event:'reserve'|'charge'|'release'|'adjust';available_delta:number;frozen_delta:number;available_after:number;frozen_after:number;amount:number;reason:string;actor:string;order_id?:string;generation_id?:string}
interface Generation {id:string;order_id:string;item_id:string;created_at:string;request_id?:string;status:'review'}
interface CreditData {wallet:CreditsWallet;entries:Ledger[];total:number;period_spent:number;pending:Generation[]}
interface Adjustment {operation:'add'|'set';amount:number;reason:string;client_token:string;expected_version:number}
interface Settlement {outcome:'charge'|'release';reason:string;client_token:string}
const eventNames={reserve:'预占',charge:'扣除',release:'释放',adjust:'管理员调整'}
const format=(value:number)=>value.toLocaleString('zh-CN')
const signed=(value:number)=>(value>0?'+':'')+format(value)
const date=(value:string)=>new Date(value).toLocaleString('zh-CN',{hour12:false})
const uncertain=(error:unknown)=>!(error instanceof ApiError)||error.status>=500

export function CreditsPanel({userId,days='30'}:{userId?:string;days?:string}) {
  // A keyed child prevents one account's in-flight UI state appearing in another account.
  return <CreditsContent key={userId||'personal'} userId={userId} days={days}/>
}
function CreditsContent({userId,days}:{userId?:string;days:string}) {
  const notice=useNotice()
  const [data,setData]=useState<CreditData|null>(null),[loading,setLoading]=useState(true),[error,setError]=useState('')
  const [offset,setOffset]=useState(0),[revision,setRevision]=useState(0),[loadedQuery,setLoadedQuery]=useState('')
  const [adjustOpen,setAdjustOpen]=useState(false),[operation,setOperation]=useState<'add'|'set'>('add'),[amount,setAmount]=useState(''),[reason,setReason]=useState('')
  const [settle,setSettle]=useState<{generation:Generation;outcome:'charge'|'release'}|null>(null),[settleReason,setSettleReason]=useState('')
  const [busy,setBusy]=useState(false),[mutationError,setMutationError]=useState(''),[retrying,setRetrying]=useState(false)
  const adjustment=useRef<Adjustment|null>(null),settlement=useRef<Settlement|null>(null),lock=useRef(false)
  const mounted=useRef(false)
  useEffect(()=>{mounted.current=true;return()=>{mounted.current=false}},[])
  const path=userId?`/admin/users/${encodeURIComponent(userId)}/credits`:'/credits'
  const queryKey=`${path}:${days}:${offset}:${revision}`
  useEffect(()=>{setOffset(0)},[days])
  useEffect(()=>{
    const controller=new AbortController()
    setLoading(true);setError('')
    api<CreditData>(`${path}?days=${encodeURIComponent(days)}&offset=${offset}&limit=50`,{signal:controller.signal})
      .then(value=>{if(!controller.signal.aborted){setData(value);setLoadedQuery(queryKey)}})
      .catch(e=>{if(!controller.signal.aborted)setError(e.message)})
      .finally(()=>{if(!controller.signal.aborted)setLoading(false)})
    return()=>controller.abort()
  },[path,days,offset,revision,queryKey])
  const refresh=()=>setRevision(v=>v+1)
  function closeAdjustment(){if(busy||retrying)return;setAdjustOpen(false);setAmount('');setReason('');setMutationError('');adjustment.current=null}
  function closeSettlement(){if(busy||retrying)return;setSettle(null);setSettleReason('');setMutationError('');settlement.current=null}
  async function adjustCredits() {
    if(lock.current||!data||!userId)return
    const numeric=Number(amount)
    if(!adjustment.current&&(!amount.trim()||!Number.isSafeInteger(numeric)||numeric<0||numeric>1_000_000_000||!reason.trim())){setMutationError('积分须为 0–1,000,000,000 的整数，并填写调整原因。');return}
    adjustment.current??={operation,amount:numeric,reason:reason.trim(),client_token:crypto.randomUUID(),expected_version:data.wallet.version}
    lock.current=true;setBusy(true);setMutationError('')
    try {
      const wallet=await post<CreditsWallet>(path,adjustment.current)
      if(!mounted.current)return
      setData(value=>value?{...value,wallet}:value);adjustment.current=null;setRetrying(false);setAdjustOpen(false);setAmount('');setReason('');refresh();notice('积分已调整')
    } catch(e) {
      if(!mounted.current)return
      if(e instanceof ApiError&&e.status===409){adjustment.current=null;setRetrying(false);setMutationError('余额已变化，正在刷新。请核对最新余额后重新提交。');refresh()}
      else {const unknown=uncertain(e);if(!unknown)adjustment.current=null;setRetrying(unknown);setMutationError(unknown?'本次调整结果尚未确认。请重试确认原操作，系统不会重复记账。':(e as Error).message)}
    } finally {lock.current=false;if(mounted.current)setBusy(false)}
  }
  async function settleGeneration() {
    if(lock.current||!settle||!settleReason.trim())return
    settlement.current??={outcome:settle.outcome,reason:settleReason.trim(),client_token:crypto.randomUUID()}
    lock.current=true;setBusy(true);setMutationError('')
    try {
      const wallet=await post<CreditsWallet>(`/admin/generations/${encodeURIComponent(settle.generation.id)}/settle`,settlement.current)
      if(!mounted.current)return
      setData(value=>value?{...value,wallet}:value);settlement.current=null;setRetrying(false);setSettle(null);setSettleReason('');refresh();notice('待确认记录已结算')
    } catch(e) {
      if(!mounted.current)return
      const unknown=uncertain(e);if(!unknown)settlement.current=null;setRetrying(unknown);setMutationError(unknown?'结算结果尚未确认。请重试确认原操作，系统不会重复结算。':(e as Error).message)
      if(e instanceof ApiError&&e.status===409)refresh()
    } finally {lock.current=false;if(mounted.current)setBusy(false)}
  }
  return <section className="credits-panel">
    <div className="accounts-section-heading"><div><h2>{userId?'积分与流水':'我的积分'}</h2><p className="hint">积分以生图结算为准，冻结积分正在等待生成结果。</p></div><div className="button-group"><button className="button" disabled={loading||busy} onClick={refresh}><RefreshCw size={15}/>刷新</button>{userId&&data&&!data.wallet.exempt&&<button className="button" disabled={loading||!!error||busy} onClick={()=>{setAdjustOpen(true);if(!adjustment.current)setMutationError('')}}>调整积分</button>}</div></div>
    {error&&<div className="error-banner" role="alert">{error}<button className="text-button" onClick={refresh}>重新加载</button></div>}
    {loading&&<p className="credits-loading" role="status"><Spinner/>正在读取积分记录</p>}
    {data&&loadedQuery===queryKey&&!loading&&!error&&<>
      <div className="credits-summary"><div><span>可用积分</span><strong>{data.wallet.exempt?'免计费':format(data.wallet.available)}</strong></div><div><span>冻结积分</span><strong>{format(data.wallet.frozen)}</strong></div><div><span>累计消耗</span><strong>{format(data.wallet.spent)}</strong></div><div><span>{days==='0'?'全部时间消耗':'所选期间消耗'}</span><strong>{format(data.period_spent)}</strong></div></div>
      {data.wallet.exempt&&<p className="notice-banner">管理员免计费，无需增加积分。</p>}
      {!!data.pending.length&&<div className="credits-pending"><h3>生成结果待确认 <span className="count">{data.pending.length}</span></h3><p className="hint">这些记录的积分保持冻结，待管理员核实供应商结果后结算。</p>{data.pending.map(generation=><div className="credits-pending-row" key={generation.id}><div><strong>生成记录 {generation.id}</strong><small>订单 {generation.order_id} · 图片 {generation.item_id}</small><small>{date(generation.created_at)}{generation.request_id&&` · 请求 ${generation.request_id}`}</small></div>{userId&&<div className="button-group"><button className="button" disabled={busy||retrying} onClick={()=>{setSettle({generation,outcome:'charge'});setSettleReason('');setMutationError('')}}>确认扣除</button><button className="button" disabled={busy||retrying} onClick={()=>{setSettle({generation,outcome:'release'});setSettleReason('');setMutationError('')}}>释放积分</button></div>}</div>)}</div>}
      <div className="accounts-section-heading"><h3>积分流水</h3><span className="hint">按记账时间筛选 · 共 {format(data.total)} 条</span></div>
      {data.entries.length?<div className="accounts-table-wrap"><table className="accounts-table credits-ledger"><thead><tr><th>时间 / 类型</th><th>可用变动</th><th>冻结变动</th><th>变动后可用 / 冻结</th><th>原因与关联记录</th></tr></thead><tbody>{data.entries.map(entry=><tr key={entry.id}><td><strong>{eventNames[entry.event]||entry.event}</strong><small><time dateTime={entry.created_at}>{date(entry.created_at)}</time></small></td><td>{signed(entry.available_delta)}</td><td>{signed(entry.frozen_delta)}</td><td>{format(entry.available_after)} / {format(entry.frozen_after)}</td><td className="ledger-reason">{entry.reason||'—'}<small>操作人：{entry.actor||'—'}</small>{entry.order_id&&<small>订单：{entry.order_id}</small>}{entry.generation_id&&<small>生成记录：{entry.generation_id}</small>}</td></tr>)}</tbody></table></div>:!loading&&<Empty title="所选期间暂无积分流水"/>}
      {data.total>50&&<div className="accounts-pagination"><button className="button" disabled={loading||offset===0} onClick={()=>setOffset(value=>Math.max(0,value-50))}>上一页</button><span>{Math.floor(offset/50)+1} / {Math.max(1,Math.ceil(data.total/50))}</span><button className="button" disabled={loading||offset+50>=data.total} onClick={()=>setOffset(value=>value+50)}>下一页</button></div>}
    </>}
    {adjustOpen&&data&&<Modal title="调整可用积分" onClose={closeAdjustment}><form onSubmit={e=>{e.preventDefault();void adjustCredits()}}><p className="hint">当前可用 {format(data.wallet.available)} · 冻结 {format(data.wallet.frozen)}。调整仅影响可用积分。</p><label className="field">调整方式<select value={operation} disabled={busy||retrying} onChange={e=>setOperation(e.target.value as 'add'|'set')}><option value="add">增加可用积分</option><option value="set">设置可用积分</option></select></label><label className="field">{operation==='add'?'增加积分':'调整后的可用积分'}<input type="number" min={0} max={1_000_000_000} step={1} required value={amount} disabled={busy||retrying} onChange={e=>setAmount(e.target.value)}/></label><label className="field">调整原因<textarea required maxLength={200} rows={3} value={reason} disabled={busy||retrying} onChange={e=>setReason(e.target.value)}/></label>{mutationError&&<div className="error-banner" role="alert">{mutationError}</div>}<div className="modal-footer"><button type="button" className="button" disabled={busy||retrying} onClick={closeAdjustment}>取消</button><button className="button primary" disabled={busy||loading||!!error}>{busy?<Spinner/>:null}{retrying?'重试确认原操作':'确认调整'}</button></div></form></Modal>}
    {settle&&<Modal title={settle.outcome==='charge'?'确认扣除冻结积分':'确认释放冻结积分'} onClose={closeSettlement}><form onSubmit={e=>{e.preventDefault();void settleGeneration()}}><p className="credits-confirm-copy">{settle.outcome==='charge'?'请在核实此次生图已产生应计费结果后扣除冻结积分。':'请在核实此次生图无需扣费后释放冻结积分，返还至可用积分。'}</p><p className="hint credits-id">生成记录：{settle.generation.id}<br/>订单：{settle.generation.order_id}</p><label className="field">结算依据<textarea required rows={3} maxLength={200} value={settleReason} disabled={busy||retrying} onChange={e=>setSettleReason(e.target.value)}/></label>{mutationError&&<div className="error-banner" role="alert">{mutationError}</div>}<div className="modal-footer"><button type="button" className="button" disabled={busy||retrying} onClick={closeSettlement}>取消</button><button className="button primary" disabled={busy||!settleReason.trim()}>{busy?<Spinner/>:null}{retrying?'重试确认原操作':settle.outcome==='charge'?'确认扣除':'确认释放'}</button></div></form></Modal>}
  </section>
}
