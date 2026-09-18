import { useCallback, useEffect, useRef, useState } from 'react'
import { Copy, Download, Plus, RefreshCw } from 'lucide-react'
import { api, ApiError, post } from '../lib/api'
import { CustomerWorkbench, PendingMutation } from '../components/CustomerWorkbench'
import { Empty, Modal, PrintFields, Spinner, useNotice } from '../components/UI'
import { OrderMutations, stateLabels } from '../lib/customer-orders'
import type { CustomerLibrary, CustomerOrder } from '../lib/customer-orders'
import { directorySupported, syncOrder } from '../lib/device'
import { customerManifestPath, customerZipUrl } from '../lib/delivery'
import type { PrintSettings, User } from '../lib/types'
import { submissionDate } from '../lib/orders'
import './CustomerOrders.css'

type WatermarkPreview={orders:{id:string;order_number:string;watermark:string}[];preview_token:string}
type StaffAction={order:CustomerOrder;path:'cancel'|'restore'|'unlock'|'repack'}
export function CustomerOrders({user,library,createRequest=0,onCreateHandled,scope='active'}:{user:User;library:CustomerLibrary;createRequest?:number;onCreateHandled?:()=>void;scope?:'active'|'history'}){
  const notice=useNotice(),[orders,setOrders]=useState<CustomerOrder[]>([]),[selected,setSelected]=useState<string|null>(null)
  const [error,setError]=useState(''),[loading,setLoading]=useState(true),[busy,setBusy]=useState(false)
  const [search,setSearch]=useState(''),[state,setState]=useState('all'),[owner,setOwner]=useState('all'),[start,setStart]=useState(''),[end,setEnd]=useState('')
  const [checked,setChecked]=useState<string[]>([]),[createOpen,setCreateOpen]=useState(false),[action,setAction]=useState<StaffAction|null>(null),[print,setPrint]=useState<PrintSettings|null>(null)
  const [watermarks,setWatermarks]=useState<WatermarkPreview|null>(null),[zipIds,setZipIds]=useState<string[]>([]),[downloads,setDownloads]=useState<Record<string,string>>({})
  const session=useRef(new AbortController()),lock=useRef(false),mutations=useRef(new OrderMutations()),bulkToken=useRef('')
  const history=scope==='history'
  const visibleOrders=history?orders:orders.filter(order=>order.state==='draft'||order.state==='review')
  const refresh=useCallback(async()=>{const controller=session.current;try{const next=await api<CustomerOrder[]>('/customer-orders',{signal:controller.signal});if(!controller.signal.aborted){setOrders(prev=>next.map(order=>{const existing=prev.find(o=>o.id===order.id);return existing&&existing.version>order.version?existing:order}));setError('')}}catch(e){if(!controller.signal.aborted)setError((e as Error).message)}finally{if(!controller.signal.aborted)setLoading(false)}},[])
  useEffect(()=>{const controller=new AbortController();session.current=controller;void refresh();const timer=setInterval(()=>{if(!lock.current)void refresh()},4000);return()=>{controller.abort();clearInterval(timer)}},[refresh])
  useEffect(()=>{if(createRequest){setCreateOpen(true);onCreateHandled?.()}},[createRequest])
  const dateError=!!(start&&end&&start>end)
  const filtered=visibleOrders.filter(order=>(state==='all'||order.state===state)&&(owner==='all'||order.owner===owner)&&order.order_number.toLocaleLowerCase().includes(search.trim().toLocaleLowerCase())&&(!start||new Date(order.created_at||'').getTime()>=new Date(start+'T00:00:00').getTime())&&(!end||new Date(order.created_at||'').getTime()<=new Date(end+'T23:59:59.999').getTime())&&!dateError)
  const active=orders.find(order=>order.id===selected),selectedOrders=orders.filter(order=>checked.includes(order.id)),ready=selectedOrders.filter(order=>order.state==='submitted'&&order.delivery_ready)
  function accept(next:CustomerOrder){setOrders(prev=>prev.map(order=>order.id===next.id&&next.version>=order.version?next:order))}
  async function runAction(){
    if(lock.current||!action)return
    lock.current=true;setBusy(true);setError('')
    try{const next=await mutations.current.run<CustomerOrder>('staff','/customer-orders/'+encodeURIComponent(action.order.id),'/'+action.path,action.order.version,action.path==='repack'&&print?{print_settings:print}:{});accept(next);setAction(null);notice('订单已更新')}
    catch(e){setError((e as Error).message);if(e instanceof ApiError&&e.status===409){try{const latest=await api<CustomerOrder>('/customer-orders/'+encodeURIComponent(action.order.id));accept(latest);setAction({...action,order:latest})}catch{}}else await refresh()}
    finally{lock.current=false;setBusy(false)}
  }
  async function retryAction(){
    if(lock.current)return
    lock.current=true;setBusy(true);setError('')
    try{const next=await mutations.current.retry<CustomerOrder>();accept(next);setAction(null);notice('操作结果已确认')}catch(e){setError((e as Error).message)}finally{lock.current=false;setBusy(false)}
  }
  async function previewWatermarks(){
    if(lock.current)return
    lock.current=true;setBusy(true);setError('')
    try{setWatermarks(await post<WatermarkPreview>('/customer-orders/watermarks/preview',{ids:selectedOrders.map(order=>order.id)}));bulkToken.current=crypto.randomUUID()}
    catch(e){setError((e as Error).message)}finally{lock.current=false;setBusy(false)}
  }
  async function applyWatermarks(){
    if(lock.current||!watermarks)return
    lock.current=true;setBusy(true);setError('')
    try{const result=await post<{updated:number}>('/customer-orders/watermarks',{ids:watermarks.orders.map(order=>order.id),preview_token:watermarks.preview_token,client_token:bulkToken.current});setWatermarks(null);await refresh();notice(`已更新 ${result.updated} 个订单的水印`)}
    catch(e){setError((e as Error).message);if(e instanceof ApiError&&e.status>=400&&e.status<500)setWatermarks(null)}finally{lock.current=false;setBusy(false)}
  }
  async function download(ids:string[]){
    if(lock.current||!ids.length)return
    if(!directorySupported()){setZipIds(ids);return}
    lock.current=true;setBusy(true)
    try{
      const root=await window.showDirectoryPicker({mode:'readwrite',id:'customer-order-download'})
      for(const id of ids){
        session.current.signal.throwIfAborted()
        const order=orders.find(order=>order.id===id);if(!order)continue
        try{await syncOrder(user.id,id,root,message=>setDownloads(prev=>({...prev,[id]:message})),{signal:session.current.signal,manifestPath:customerManifestPath(id)});setDownloads(prev=>({...prev,[id]:'打印文件已保存'}))}
        catch(e){if(session.current.signal.aborted)throw e;setDownloads(prev=>({...prev,[id]:(e as Error).message}));notice(order.order_number+'：'+(e as Error).message,'error')}
      }
    }catch(e){if((e as Error).name!=='AbortError'){setError((e as Error).message);setZipIds(ids)}}finally{lock.current=false;setBusy(false)}
  }
  async function copyOrderNumber(number:string){
    try{await navigator.clipboard.writeText(number);notice('订单号已复制')}
    catch{notice('复制失败，请手动选中订单号复制','error')}
  }
  function controls(order:CustomerOrder){return <><button type="button" className="button" onClick={()=>void copyOrderNumber(order.order_number)}><Copy size={15}/>复制订单号</button>{order.state==='cancelled'?<button className="button" disabled={busy} onClick={()=>setAction({order,path:'restore'})}>恢复订单</button>:<>{order.state==='submitted'?<><button className="button" disabled={busy||!order.delivery_ready} onClick={()=>void download([order.id])}><Download size={15}/>下载打印文件</button><button className="button" disabled={busy} onClick={()=>setAction({order,path:'unlock'})}>解锁选图</button><button className="button" disabled={busy} onClick={()=>{setPrint(order.print_settings);setAction({order,path:'repack'})}}>重新排版</button></>:null}<button className="text-button" disabled={busy} onClick={()=>setAction({order,path:'cancel'})}>取消订单</button></>}</>}
  return <div className="customer-orders">{active?<><div className="customer-staff-actions">{controls(active)}</div><div className="customer-order-meta">开单人：{active.owner_name} · 备注：{active.notes||'无'}<br/>当前水印：{active.watermark||active.owner_name}{active.delivery_ready?' · 打印文件就绪':''}{downloads[active.id]&&<p role="status">{downloads[active.id]}</p>}</div><CustomerWorkbench key={active.id} initial={active} mode="staff" library={library} onBack={()=>setSelected(null)} onChange={next=>accept({...active,...next,version:next.version??active.version})}/></>:<><div className="page-heading"><div><h1>{history?'历史订单':'客户订单'}</h1><p>{history?'查看全部订单，包含待制作、选图中、已提交和已取消的记录。':'开单后将订单号交给客户，也可进入订单代客户制作和选图。'}</p></div>{!history&&<div className="button-group"><a className="button" href="/guest" target="_blank" rel="noreferrer">客户入口</a><button className="button primary" onClick={()=>setCreateOpen(true)}><Plus size={16}/>开新订单</button></div>}</div>
    <div className="customer-order-filters"><label className="field">订单号<input value={search} onChange={e=>setSearch(e.target.value)} placeholder="搜索订单号"/></label><label className="field">开单人<select value={owner} onChange={e=>setOwner(e.target.value)}><option value="all">全部开单人</option>{Array.from(new Map(visibleOrders.map(order=>[order.owner,order.owner_name])).entries()).map(([id,name])=><option key={id} value={id}>{name}</option>)}</select></label><label className="field">订单状态<select value={state} onChange={e=>{setState(e.target.value);setChecked([])}}><option value="all">{history?'全部订单':'全部在制订单'}</option>{(history?Object.entries(stateLabels):Object.entries(stateLabels).filter(([value])=>value==='draft'||value==='review')).map(([value,label])=><option key={value} value={value}>{label}</option>)}</select></label><label className="field">开始日期<input type="date" value={start} onChange={e=>setStart(e.target.value)}/></label><label className="field">结束日期<input type="date" value={end} min={start} onChange={e=>setEnd(e.target.value)}/></label><button className="button" onClick={()=>void refresh()} disabled={busy}><RefreshCw size={16}/>刷新</button></div>{dateError&&<p className="error-banner">结束日期不能早于开始日期</p>}
    <div className="customer-bulk-toolbar"><label className="check-line"><input type="checkbox" aria-label="全选当前订单" checked={!!filtered.length&&filtered.every(order=>checked.includes(order.id))} onChange={e=>setChecked(prev=>e.target.checked?Array.from(new Set([...prev,...filtered.map(order=>order.id)])):prev.filter(id=>!filtered.some(order=>order.id===id)))}/>全选当前订单</label><span className="hint">已选 {selectedOrders.length} 个</span><button className="button" disabled={busy||!ready.length} onClick={()=>void download(ready.map(order=>order.id))}><Download size={16}/>批量下载打印文件 ({ready.length})</button><button className="button" disabled={busy||!selectedOrders.length} onClick={()=>void previewWatermarks()}>批量更新水印</button>{!!checked.length&&<button className="text-button" onClick={()=>setChecked([])}>清空选择</button>}</div>
    {loading?<Spinner/>:filtered.length?<div className="customer-order-list">{filtered.map(order=><article key={order.id} className="customer-order-row"><input type="checkbox" aria-label={'选择订单 '+order.order_number} checked={checked.includes(order.id)} onChange={e=>setChecked(prev=>e.target.checked?[...prev,order.id]:prev.filter(id=>id!==order.id))}/><button className="customer-order-open" onClick={()=>setSelected(order.id)}><strong>{order.order_number}</strong><span>{order.owner_name} · 最终 {order.final_count} 张 · 上限 {order.generation_limit} 张</span>{order.notes&&<span>备注：{order.notes}</span>}<small>{submissionDate(order.created_at||'')}</small>{downloads[order.id]&&<small role="status">{downloads[order.id]}</small>}</button><span className="customer-order-status">{stateLabels[order.state]}{order.state==='submitted'&&!order.delivery_ready?' · 排版中':''}</span><div className="customer-order-actions"><button className="button" onClick={()=>setSelected(order.id)}>{order.state==='draft'||order.state==='review'?'进入 / 代操作':'查看订单'}</button>{controls(order)}</div></article>)}</div>:<Empty title="没有匹配的订单" description={history?'调整筛选条件即可查看其他订单。':'调整筛选条件，或开一个新订单。'}/>}</>}
    {error&&<div className="error-banner" role="alert">{error}</div>}{mutations.current.pendingPath&&!busy&&<PendingMutation busy={busy} onRetry={()=>void retryAction()}/>}
    {createOpen&&<CreateOrder onClose={()=>setCreateOpen(false)} onCreated={order=>{setOrders(prev=>[order,...prev.filter(value=>value.id!==order.id)]);setCreateOpen(false);setSelected(order.id);notice('订单已创建')}}/>}
    {action&&<Modal title={{cancel:'取消订单',restore:'恢复订单',unlock:'解锁订单',repack:'重新排版'}[action.path]} onClose={()=>{if(!busy)setAction(null)}}><p>订单：{action.order.order_number}</p>{mutations.current.pendingPath&&!busy&&<PendingMutation busy={busy} onRetry={()=>void retryAction()}/>}{action.path==='repack'&&print?<PrintFields value={print} onChange={setPrint}/>:<p>{{cancel:'订单移入回收站，客户将无法查看预览或继续操作。已有的处理请求会继续核对结果。',restore:'订单将恢复到取消前状态，客户可重新进入订单。',unlock:'保留现有图片和重跑次数，重新开放选图。再次提交前无法下载打印文件。',repack:''}[action.path]}</p>}{error&&<div className="error-banner" role="alert">{error}</div>}<div className="modal-footer"><button className="button" disabled={busy} onClick={()=>setAction(null)}>返回</button><button className="button primary" disabled={busy} onClick={()=>void runAction()}>{busy&&<Spinner/>}确认{action.path==='cancel'?'取消':action.path==='restore'?'恢复':action.path==='unlock'?'解锁':'排版'}</button></div></Modal>}
    {watermarks&&<Modal title="核对批量水印更新" onClose={()=>{if(!busy)setWatermarks(null)}}><p>将使用各订单开单人当前的水印设置更新预览。空白水印使用开单人的显示名称。</p><ul className="customer-watermark-list">{watermarks.orders.map(order=><li key={order.id}><strong>{order.order_number}</strong> → {order.watermark}</li>)}</ul><p className="hint">只更新水印预览，已生成图片和打印文件保持原样。原预览链接将失效。</p><div className="modal-footer"><button className="button" disabled={busy} onClick={()=>setWatermarks(null)}>返回</button><button className="button primary" disabled={busy} onClick={()=>void applyWatermarks()}>{busy&&<Spinner/>}确认更新 {watermarks.orders.length} 个订单</button></div></Modal>}
    {!!zipIds.length&&<Modal title="下载打印文件 ZIP" onClose={()=>setZipIds([])}><p>当前浏览器无法选择本地文件夹，请逐个下载订单打印包。</p><div className="zip-fallback-list">{zipIds.map(id=><a key={id} className="button" href={customerZipUrl(id)} download><Download size={16}/>{orders.find(order=>order.id===id)?.order_number} · ZIP</a>)}</div></Modal>}
  </div>
}
function CreateOrder({onClose,onCreated}:{onClose:()=>void;onCreated:(order:CustomerOrder)=>void}){
  const [number,setNumber]=useState(''),[limit,setLimit]=useState(20),[finalCount,setFinalCount]=useState(10),[reruns,setReruns]=useState(2),[notes,setNotes]=useState(''),[error,setError]=useState(''),[busy,setBusy]=useState(false)
  const pending=useRef<{key:string;body:Record<string,unknown>}|null>(null),lock=useRef(false)
  async function create(e:React.FormEvent){
    e.preventDefault();if(lock.current)return
    const payload={order_number:number.trim(),generation_limit:limit,final_count:finalCount,rerun_limit:reruns,notes:notes.trim()},key=JSON.stringify(payload)
    if(pending.current&&pending.current.key!==key){setError('上次开单结果尚未确认，请恢复原内容后重试');return}
    const request=pending.current||{key,body:{...payload,client_token:crypto.randomUUID()}};pending.current=request;lock.current=true;setBusy(true);setError('')
    try{const order=await post<CustomerOrder>('/customer-orders',request.body);pending.current=null;onCreated(order)}catch(e){if(e instanceof ApiError&&e.status>=400&&e.status<500)pending.current=null;setError((e as Error).message)}finally{lock.current=false;setBusy(false)}
  }
  return <Modal title="开新订单" onClose={()=>{if(!busy)onClose()}}><form onSubmit={e=>void create(e)}><label className="field">订单号<input aria-label="订单号" required maxLength={120} autoComplete="off" value={number} onChange={e=>setNumber(e.target.value)}/><span className="hint">客户凭此号码进入订单；订单号不可重复使用。</span></label><div className="form-grid"><label className="field">可选图片上限<input required type="number" min={1} max={360} value={limit} onChange={e=>setLimit(Number(e.target.value))}/></label><label className="field">最终成品数量<input required type="number" min={1} max={limit} value={finalCount} onChange={e=>setFinalCount(Number(e.target.value))}/></label><label className="field">每张可重跑次数<input required type="number" min={0} value={reruns} onChange={e=>setReruns(Number(e.target.value))}/></label></div><label className="field">内部备注<textarea maxLength={200} value={notes} onChange={e=>setNotes(e.target.value)} rows={3}/><span className="hint">仅工作人员可见，用于本地打印文件夹命名。</span></label>{error&&<div className="error-banner" role="alert">{error}</div>}<div className="modal-footer"><button type="button" className="button" disabled={busy} onClick={onClose}>取消</button><button className="button primary" disabled={busy||finalCount>limit}>{busy&&<Spinner/>}创建订单</button></div></form></Modal>
}
