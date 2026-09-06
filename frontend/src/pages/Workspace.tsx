import { useCallback, useEffect, useRef, useState } from 'react'
import type { SetStateAction } from 'react'
import { Upload, Plus, Layers, SlidersHorizontal, Trash2, ArrowRight } from 'lucide-react'
import { Empty, Modal, PrintFields, TemplateChooser, Spinner, useNotice } from '../components/UI'
import { post } from '../lib/api'
import { readLocal, writeLocal } from '../lib/db'
import { uploadFile } from '../lib/upload'
import { safeFilename } from '../lib/sync'
import { defaultPrint } from '../lib/types'
import type { Draft, Order, PrintSettings, TemplateSet, User } from '../lib/types'

function FileAvatar({file}:{file:File}) {
  const [url,setUrl]=useState('')
  useEffect(()=>{const value=URL.createObjectURL(file);setUrl(value);return()=>URL.revokeObjectURL(value)},[file])
  return <img className="avatar" src={url||undefined} alt="上传的头像"/>
}
export function Workspace({user,templates,onCreated,addRef}:{user:User;templates:TemplateSet[];onCreated:()=>void;addRef:React.RefObject<(()=>void)|null>}) {
  const [drafts,setDraftsState]=useState<Draft[]>([]),[loaded,setLoaded]=useState(false),[persisted,setPersisted]=useState(false),[selected,setSelected]=useState<string[]>([])
  const [picker,setPicker]=useState<string[]|null>(null),[pickValue,setPickValue]=useState<string[]>([])
  const [printTargets,setPrintTargets]=useState<string[]|null>(null),[print,setPrint]=useState<PrintSettings>(defaultPrint)
  const [busy,setBusy]=useState(false),[states,setStates]=useState<Record<string,string>>({}),[drag,setDrag]=useState(false)
  const setDrafts=useCallback((action:SetStateAction<Draft[]>)=>{setPersisted(false);setDraftsState(action)},[])
  const input=useRef<HTMLInputElement>(null), batch=useRef<AbortController|null>(null), notice=useNotice()
  useEffect(()=>()=>batch.current?.abort(),[user.id])
  useEffect(()=>{let active=true;readLocal<Draft[]>('drafts:'+user.id).then(value=>{if(active){setDrafts(prev=>[...(value||[]),...prev.filter(d=>!(value||[]).some(old=>old.id===d.id))]);setSelected(prev=>Array.from(new Set([...(value||[]).map(d=>d.id),...prev])));setLoaded(true)}}).catch(()=>setLoaded(true));return()=>{active=false}},[user.id])
  useEffect(()=>{if(!loaded)return;let active=true;writeLocal('drafts:'+user.id,drafts).then(()=>{if(active)setPersisted(true)}).catch(()=>notice('草稿保存失败，请检查浏览器存储空间','error'));return()=>{active=false}},[drafts,loaded,user.id,notice])
  useEffect(()=>{if(persisted||!drafts.length)return;const warn=(event:BeforeUnloadEvent)=>{event.preventDefault()};window.addEventListener('beforeunload',warn);return()=>window.removeEventListener('beforeunload',warn)},[persisted,drafts.length])
  useEffect(()=>{addRef.current=()=>input.current?.click();return()=>{addRef.current=null}},[addRef])
  function add(files:FileList|null) {
    if(!files)return
    const valid=Array.from(files).filter(f=>/\.(jpe?g|png|webp)$/i.test(f.name))
    if(valid.length!==files.length)notice('已跳过不支持的文件，请上传 JPG、PNG 或 WebP','error')
    const rows=valid.map(file=>({id:crypto.randomUUID(),file,name:file.name.replace(/\.[^.]+$/,''),template_ids:[],print_settings:{...defaultPrint,...user.print_defaults},client_token:crypto.randomUUID()}))
    setDrafts(prev=>[...prev,...rows]);setSelected(prev=>[...prev,...rows.map(r=>r.id)])
  }
  const chosen=drafts.filter(d=>selected.includes(d.id))
  const count=chosen.reduce((sum,d)=>sum+d.template_ids.length*12,0)
  function choose(ids:string[]) {setPicker(ids);setPickValue(drafts.find(d=>d.id===ids[0])?.template_ids||[])}
  function editPrint(ids:string[]) {setPrintTargets(ids);setPrint(drafts.find(d=>d.id===ids[0])?.print_settings||defaultPrint)}
  async function submit() {
    const controller=new AbortController();batch.current=controller
    const signal=controller.signal
    setBusy(true);let successful=0
    for(const draft of chosen) {
      try {
        signal.throwIfAborted()
        if(!safeFilename(draft.name))throw new Error('请填写有效的订单名称')
        if(drafts.filter(d=>d.name.normalize('NFC').toLowerCase()===draft.name.normalize('NFC').toLowerCase()).length>1)throw new Error('名称重复，请修改后提交')
        if(!draft.template_ids.length)throw new Error('请先选择模板套装')
        setStates(p=>({...p,[draft.id]:'正在上传'}))
        const upload=await uploadFile(draft.file,percentage=>setStates(p=>({...p,[draft.id]:'上传 '+percentage+'%'})),signal)
        signal.throwIfAborted()
        await post<Order>('/orders',{upload_id:upload.id,name:draft.name,template_ids:draft.template_ids,print_settings:draft.print_settings,client_token:draft.client_token},signal)
        signal.throwIfAborted()
        setDrafts(prev=>prev.filter(d=>d.id!==draft.id));setSelected(prev=>prev.filter(id=>id!==draft.id));successful++
      } catch(e){if(signal.aborted)break;setStates(p=>({...p,[draft.id]:(e as Error).message}))}
    }
    if(signal.aborted)return
    setBusy(false)
    if(successful){notice('已提交 '+successful+' 个订单，可在任务中心查看进度');onCreated()}
  }
  return <><div className="page-heading"><div><h1>批量制作</h1><p>上传头像，选择套装，自动生成可打印的贴纸。</p></div></div><div className="steps"><div><span>1</span>上传头像</div><i/><div><span>2</span>选择模板</div><i/><div><span>3</span>生成与保存</div></div><input ref={input} type="file" hidden multiple accept="image/jpeg,image/png,image/webp" onChange={e=>{add(e.target.files);e.target.value=''}}/><button className={'drop-zone '+(drag?'dragging':'')} disabled={busy} onClick={()=>input.current?.click()} onDragOver={e=>{e.preventDefault();setDrag(true)}} onDragLeave={()=>setDrag(false)} onDrop={e=>{e.preventDefault();setDrag(false);if(!busy)add(e.dataTransfer.files)}}><Upload size={36} strokeWidth={1.5}/><strong>拖入头像照片</strong><span>支持 JPG、PNG、WebP，可一次上传多张</span></button><section className="workspace-orders"><div className="section-heading"><h2>待提交订单 <span className="count">{drafts.length}</span></h2><span className="hint" role="status">{persisted?'草稿已保存':'正在保存草稿…'}</span><button className="text-button" onClick={()=>input.current?.click()} disabled={busy}><Plus size={16}/> 添加头像</button></div><div className="toolbar"><label className="check-line"><input type="checkbox" checked={drafts.length>0&&selected.length===drafts.length} onChange={e=>setSelected(e.target.checked?drafts.map(d=>d.id):[])} disabled={busy}/>全选</label><button className="button" disabled={!selected.length||busy} onClick={()=>choose(selected)}><Layers size={16}/>批量选择模板</button><button className="button" disabled={!selected.length||busy} onClick={()=>editPrint(selected)}><SlidersHorizontal size={16}/>打印参数</button></div><div className="orders-table"><div className="order-table-head"><span/><span>头像与名称</span><span>模板套装</span><span>打印规格</span><span>状态</span><span/></div>{drafts.length?drafts.map(d=><div className="order-row" key={d.id}><input aria-label={'选择 '+d.name} type="checkbox" checked={selected.includes(d.id)} disabled={busy} onChange={e=>setSelected(prev=>e.target.checked?[...prev,d.id]:prev.filter(id=>id!==d.id))}/><div className="avatar-name"><FileAvatar file={d.file}/><input aria-label="订单名称" value={d.name} disabled={busy} onChange={e=>setDrafts(prev=>prev.map(row=>row.id===d.id?{...row,name:e.target.value}:row))}/></div><button className="row-templates" onClick={()=>choose([d.id])} disabled={busy}>{d.template_ids.length?<><div className="tiny-sets">{d.template_ids.slice(0,3).map(id=>{const set=templates.find(s=>s.id===id);return <div key={id} className="tiny-set">{set?.images.slice(0,4).map(im=><img key={im.id} src={im.url} alt=""/>)}<span>{set?.code||'已下架'}</span></div>})}</div>{d.template_ids.length>3&&<span>+{d.template_ids.length-3}</span>}</>:<span className="add-template"><Plus size={18}/>选择模板</span>}</button><button className="print-summary" onClick={()=>editPrint([d.id])} disabled={busy}>{d.print_settings.paper_width_mm===210&&d.print_settings.paper_height_mm===297?'A4':d.print_settings.paper_width_mm+'×'+d.print_settings.paper_height_mm+' mm'}<span>{d.print_settings.long_edge_mm/10} cm · {d.print_settings.dpi} DPI</span></button><span className={'draft-status '+(states[d.id]?'has-message':'')}>{states[d.id]||'待提交'}</span><button className="icon-button" disabled={busy} title="移除此头像" onClick={()=>{setDrafts(prev=>prev.filter(row=>row.id!==d.id));setSelected(prev=>prev.filter(id=>id!==d.id))}}><Trash2 size={16}/></button></div>):<Empty title="还没有待提交的订单" description="从上传第一张头像开始，工作台会为你保留未提交的草稿。"/>}</div></section><div className="submit-bar"><p>已选 <strong>{chosen.length}</strong> 个订单 <span>/</span> 预计生成 <strong>{count}</strong> 张</p><button className="button primary" onClick={submit} disabled={busy||!chosen.length}>{busy?<Spinner/>:<ArrowRight size={17}/>}提交生成</button></div>{picker&&<Modal title="选择模板套装" onClose={()=>setPicker(null)} wide><TemplateChooser templates={templates} value={pickValue} onChange={setPickValue}/><div className="modal-footer"><span>已选 {pickValue.length} 套 · {pickValue.length*12} 张</span><button className="button primary" onClick={()=>{setDrafts(prev=>prev.map(d=>picker.includes(d.id)?{...d,template_ids:[...pickValue]}:d));setPicker(null)}}>应用到 {picker.length} 个订单</button></div></Modal>}{printTargets&&<Modal title="打印参数" onClose={()=>setPrintTargets(null)}><PrintFields value={print} onChange={setPrint}/><div className="modal-footer"><span>应用到 {printTargets.length} 个订单</span><button className="button primary" onClick={()=>{setDrafts(prev=>prev.map(d=>printTargets.includes(d.id)?{...d,print_settings:{...print}}:d));setPrintTargets(null)}}>保存参数</button></div></Modal>}</>
}
