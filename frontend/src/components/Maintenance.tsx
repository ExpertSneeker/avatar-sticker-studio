import { useEffect, useState } from 'react'
import { HardDrive, RefreshCw, Trash2 } from 'lucide-react'
import { api, post } from '../lib/api'
import { Modal, Progress, Spinner, useNotice } from './UI'
import { submissionDate } from '../lib/orders'

type CacheScope={files:number;bytes:number}
type MediaCache={library:CacheScope;customer:CacheScope;separate_from_data:boolean;pregeneration:{running:boolean;last_finished:number|null;generated:number;pending:number|null;removed:number;errors:number}|null}
type Storage={media_cache?:MediaCache;preview_cache_bytes:number;preview_cache_limit_bytes:number;total_bytes:number;used_bytes:number;free_bytes:number;app_bytes:number;pending_files:number}
type Plan={preview_cache_files:number;preview_cache_bytes:number;before:string;preview_token:string;order_count:number;item_count:number;file_count:number;file_bytes:number;blocked_count:number;legacy_unassigned_files:number;orders:{id:string;name:string;created_at:string}[]}
const bytes=(value:number)=>value>=1073741824?(value/1073741824).toFixed(1)+' GB':(value/1048576).toFixed(1)+' MB'
export function Maintenance(){
  const [storage,setStorage]=useState<Storage|null>(null),[error,setError]=useState(''),[date,setDate]=useState(''),[plan,setPlan]=useState<Plan|null>(null),[confirmed,setConfirmed]=useState(false),[busy,setBusy]=useState(false),notice=useNotice()
  async function refresh(){try{setStorage(await api<Storage>('/admin/storage'));setError('')}catch(error){setError((error as Error).message)}}
  useEffect(()=>{void refresh()},[])
  async function preview(){
    if(!date)return
    setBusy(true);setConfirmed(false)
    try{const before=new Date(date+'T00:00:00').toISOString();setPlan(await post<Plan>('/admin/cleanup/preview',{before}))}catch(error){notice((error as Error).message,'error')}finally{setBusy(false)}
  }
  async function cleanup(){
    if(!plan||!confirmed)return
    setBusy(true)
    try{
      const result=await post<{deleted_orders:number;pending_files:number;storage:Storage}>('/admin/cleanup',{before:plan.before,preview_token:plan.preview_token,confirmed:true})
      setStorage(result.storage);setPlan(null);setConfirmed(false)
      notice(result.pending_files?`已移除 ${result.deleted_orders} 个订单记录，${result.pending_files} 个文件待重试清理`:`已清理 ${result.deleted_orders} 个订单及关联文件`,result.pending_files?'error':'success')
    }catch(error){setPlan(null);setConfirmed(false);notice((error as Error).message,'error')}finally{setBusy(false)}
  }
  async function retry(){setBusy(true);try{const result=await post<{pending_files:number;storage:Storage}>('/admin/cleanup/retry');setStorage(result.storage);notice(result.pending_files?'仍有文件无法删除，请检查服务器文件权限':'剩余文件已清理',result.pending_files?'error':'success')}catch(error){notice((error as Error).message,'error')}finally{setBusy(false)}}
  return <section className="maintenance-panel"><div className="section-heading"><h2><HardDrive size={18}/>服务器存储与清理</h2><button className="text-button" onClick={()=>void refresh()}><RefreshCw size={15}/>刷新空间</button></div>
    {error&&<p className="error-banner">{error}</p>}
    {storage?<><div className="storage-metrics"><div><span>磁盘总容量</span><strong>{bytes(storage.total_bytes)}</strong></div><div><span>已使用</span><strong>{bytes(storage.used_bytes)}</strong></div><div><span>可用空间</span><strong>{bytes(storage.free_bytes)}</strong></div><div><span>网站数据占用</span><strong>{bytes(storage.app_bytes)}</strong></div></div><Progress value={storage.used_bytes} total={storage.total_bytes}/><p className="hint">缩略图缓存 {bytes(storage.preview_cache_bytes)} / {bytes(storage.preview_cache_limit_bytes)}，包含在网站占用中；达到上限会自动淘汰旧缓存。统计服务端数据所在磁盘；已使用空间包含其他应用。数据库删除后的空间可供后续订单复用。</p>{storage.media_cache&&<MediaCacheStats cache={storage.media_cache}/>}{storage.pending_files>0&&<div className="notice-banner">{storage.pending_files} 个已确认删除的文件尚未清理成功。<button className="button" disabled={busy} onClick={()=>void retry()}>重试文件清理</button></div>}</>:!error&&<Spinner/>}
    <div className="cleanup-controls"><label className="field">清理此日期之前的订单<input type="date" value={date} onChange={e=>{setDate(e.target.value);setPlan(null)}}/></label><button className="button" disabled={busy||!date} onClick={()=>void preview()}>{busy?<Spinner/>:<Trash2 size={16}/>}预览清理范围</button></div><p className="hint">以当前设备时区的所选日期 00:00 为界，覆盖所有账号。清理完整订单、任务与错误记录、单张成图及历史版本、拼图、预览、关联缩略图缓存和不再共用的头像；模板库及模板历史版本保留。本机已下载文件不会删除。</p>
    {plan&&<Modal title="确认清理服务器订单" onClose={()=>{if(!busy)setPlan(null)}}><p>将清理 <strong>{submissionDate(plan.before)}</strong> 之前的 <strong>{plan.order_count} 个订单</strong>、{plan.item_count} 个单张任务、{plan.file_count} 个文件，预计释放 {bytes(plan.file_bytes)}（含 {plan.preview_cache_files} 个缩略图缓存，{bytes(plan.preview_cache_bytes)}）。</p>{plan.blocked_count>0&&<p className="notice-banner">{plan.blocked_count} 个订单正在处理或结果待确认，本次跳过。请先结束或确认这些任务。</p>}{plan.legacy_unassigned_files>0&&<p className="hint">另有 {plan.legacy_unassigned_files} 个历史输出尚无可靠订单归属，本次保留。</p>}<ul className="cleanup-orders">{plan.orders.map(order=><li key={order.id}><span>{order.name}</span><time>{submissionDate(order.created_at)}</time></li>)}</ul>{plan.order_count>50&&<p className="hint">仅展示前 50 个，实际范围以总数为准。</p>}<label className="check-line"><input type="checkbox" checked={confirmed} disabled={busy||!plan.order_count} onChange={e=>setConfirmed(e.target.checked)}/>我确认永久删除上述服务器订单及文件</label><div className="modal-footer"><span className="hint">模板库和本机下载保持原样</span><button className="button danger" disabled={busy||!confirmed||!plan.order_count} onClick={()=>void cleanup()}>{busy&&<Spinner/>}确认永久清理</button></div></Modal>}
  </section>
}

const timeText=(seconds:number|null)=>seconds?new Date(seconds*1000).toLocaleString('zh-CN',{hour12:false}):'尚未运行'
// Watermarked media disk cache: no size limit, so only usage is shown, split into library watermark images and customer images.
function MediaCacheStats({cache}:{cache:MediaCache}){
  const job=cache.pregeneration
  return <section className="media-cache-stats" aria-label="水印图片缓存">
    <h3>水印图片缓存</h3>
    <div className="storage-metrics"><div><span>图库水印图</span><strong>{bytes(cache.library.bytes)}</strong><small>{cache.library.files} 张</small></div><div><span>客户图片</span><strong>{bytes(cache.customer.bytes)}</strong><small>{cache.customer.files} 张</small></div><div><span>合计</span><strong>{bytes(cache.library.bytes+cache.customer.bytes)}</strong><small>{cache.library.files+cache.customer.files} 张</small></div><div><span>预生成</span><strong>{job?job.running?'进行中':job.pending?`待生成 ${job.pending}`:'已完成':'未启用'}</strong><small>{job?`上次完成 ${timeText(job.last_finished)}`:'仅在服务运行时启用'}</small></div></div>
    <p className="hint">不设容量上限，只做统计；{cache.separate_from_data?'缓存位于数据目录之外，不计入网站数据占用，也不进入发布备份。':'缓存位于数据目录内，已计入网站数据占用。'}图库水印图在贴纸删除或水印不再使用时清理；客户图片按各组织设置的天数清理。磁盘剩余不足 512 MB 时暂停写入缓存，图片仍会实时生成。{job&&job.errors>0?` 预生成累计失败 ${job.errors} 次，下轮会重试。`:''}</p>
  </section>
}
