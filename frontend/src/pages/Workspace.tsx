import { selectionSummary } from '../lib/templates'
import { StickerChooser } from './Stickers'
import { previewUrl } from '../lib/preview'
import { useCallback, useEffect, useRef, useState } from 'react'
import type { SetStateAction } from 'react'
import { Upload, Plus, Layers, SlidersHorizontal, Trash2, ArrowRight, FolderOpen } from 'lucide-react'
import { Empty, Modal, PrintFields, TemplateChooser, Spinner, useNotice } from '../components/UI'
import { ApiError, post } from '../lib/api'
import { readLocal, writeLocal } from '../lib/db'
import { uploadFile } from '../lib/upload'
import { bindDestination, directoryPermission, directorySupported } from '../lib/device'
import { safeFilename } from '../lib/sync'
import { defaultPrint } from '../lib/types'
import type { Draft, Order, PrintSettings, Sticker, TemplateSet, User } from '../lib/types'

function FileAvatar({file}:{file:File}) {
  const [url,setUrl]=useState('')
  useEffect(()=>{const value=URL.createObjectURL(file);setUrl(value);return()=>URL.revokeObjectURL(value)},[file])
  return <img className="avatar" src={previewUrl(url||undefined)} alt="上传的头像"/>
}
export function Workspace({user,templates,stickers,onCreated,addRef,directory,onChooseGlobalDirectory}:{onChooseGlobalDirectory:()=>Promise<void>;directory:FileSystemDirectoryHandle|null;user:User;templates:TemplateSet[];stickers:Sticker[];onCreated:()=>void;addRef:React.RefObject<(()=>void)|null>}) {
  const [drafts,setDraftsState]=useState<Draft[]>([]),[loaded,setLoaded]=useState(false),[persisted,setPersisted]=useState(false),[selected,setSelected]=useState<string[]>([])
  const [picker,setPicker]=useState<string[]|null>(null),[pickValue,setPickValue]=useState<string[]>([]),[pickStickers,setPickStickers]=useState<string[]>([]),[pickerTab,setPickerTab]=useState<'templates'|'stickers'>('templates')
  const [printTargets,setPrintTargets]=useState<string[]|null>(null),[print,setPrint]=useState<PrintSettings>(defaultPrint)
  const [busy,setBusy]=useState(false),[states,setStates]=useState<Record<string,string>>({}),[drag,setDrag]=useState(false)
  const setDrafts=useCallback((action:SetStateAction<Draft[]>)=>{setPersisted(false);setDraftsState(action)},[])
  const outputRequest=useRef(0)
  const input=useRef<HTMLInputElement>(null), batch=useRef<AbortController|null>(null), notice=useNotice()
  useEffect(()=>()=>{outputRequest.current++;batch.current?.abort()},[user.id])
  useEffect(()=>{let active=true;readLocal<Draft[]>('drafts:'+user.id).then(value=>{if(active){setDrafts(prev=>[...(value||[]).map(d=>({...d,sticker_ids:d.sticker_ids||[]})),...prev.filter(d=>!(value||[]).some(old=>old.id===d.id))]);setSelected(prev=>Array.from(new Set([...(value||[]).map(d=>d.id),...prev])));setLoaded(true)}}).catch(()=>setLoaded(true));return()=>{active=false}},[user.id])
  useEffect(()=>{if(!loaded)return;let active=true;writeLocal('drafts:'+user.id,drafts).then(()=>{if(active)setPersisted(true)}).catch(()=>notice('草稿保存失败，请检查浏览器存储空间','error'));return()=>{active=false}},[drafts,loaded,user.id,notice])
  useEffect(()=>{if(persisted||!drafts.length)return;const warn=(event:BeforeUnloadEvent)=>{event.preventDefault()};window.addEventListener('beforeunload',warn);return()=>window.removeEventListener('beforeunload',warn)},[persisted,drafts.length])
  useEffect(()=>{addRef.current=()=>input.current?.click();return()=>{addRef.current=null}},[addRef])
  function add(files:FileList|null) {
    if(!files)return
    const valid=Array.from(files).filter(f=>/\.(jpe?g|png|webp)$/i.test(f.name))
    if(valid.length!==files.length)notice('已跳过不支持的文件，请上传 JPG、PNG 或 WebP','error')
    const rows=valid.map(file=>({id:crypto.randomUUID(),file,name:file.name.replace(/\.[^.]+$/,''),template_ids:[],sticker_ids:[],print_settings:{...defaultPrint,...user.print_defaults},client_token:crypto.randomUUID()}))
    setDrafts(prev=>[...prev,...rows]);setSelected(prev=>[...prev,...rows.map(r=>r.id)])
  }
  const chosen=drafts.filter(d=>selected.includes(d.id))
  const count=chosen.reduce((sum,d)=>sum+selectionSummary(templates,d.template_ids,stickers,d.sticker_ids).generationCount,0)
  function choose(ids:string[]) {setPicker(ids);setPickValue(drafts.find(d=>d.id===ids[0])?.template_ids||[]);setPickStickers(drafts.find(d=>d.id===ids[0])?.sticker_ids||[])}
  function editPrint(ids:string[]) {setPrintTargets(ids);setPrint(drafts.find(d=>d.id===ids[0])?.print_settings||defaultPrint)}
  async function chooseOutput(draft:Draft) {
    if(!directory){await onChooseGlobalDirectory();return}
    const request=++outputRequest.current
    if(!directorySupported()){notice('请使用桌面 Chrome 或 Edge 选择保存目录','error');return}
    try {
      const handle=await window.showDirectoryPicker({mode:'readwrite',startIn:draft.output_directory||directory||'downloads'})
      if(request!==outputRequest.current)return
      setDrafts(prev=>prev.map(row=>row.id===draft.id?{...row,output_directory:handle}:row))
    } catch(error){if((error as Error).name!=='AbortError')notice((error as Error).message,'error')}
  }
  const missingDirectory=chosen.some(d=>!d.output_directory&&!directory)
  async function submit() {
    if(busy||!chosen.length)return
    if(missingDirectory){notice('请先为所选订单选择保存目录','error');return}
    const controller=new AbortController();batch.current=controller
    const signal=controller.signal
    setBusy(true);let successful=0
    for(const draft of chosen) {
      let creationStarted=false
      try {
        signal.throwIfAborted()
        if(!safeFilename(draft.name))throw new Error('请填写有效的订单名称')
        if(!draft.template_ids.length&&!draft.sticker_ids?.length)throw new Error('请先选择模板或贴纸')
        if(selectionSummary(templates,draft.template_ids,stickers,draft.sticker_ids).exportCount>360)throw new Error('每个订单最多导出 360 张图片，请拆分订单')
        if(draft.template_ids.some(id=>!templates.find(t=>t.id===id&&t.active&&t.available!==false))||(draft.sticker_ids||[]).some(id=>!stickers.find(s=>s.id===id&&s.active)))throw new Error('所选模板或贴纸已不可用，请重新选择')
        const root=draft.output_directory||directory!
        if(!await directoryPermission(root,true))throw new Error('保存目录尚未授权，请重新选择或授权')
        signal.throwIfAborted()
        setStates(p=>({...p,[draft.id]:'正在本地压缩'}))
        const upload=await uploadFile(draft.file,percentage=>setStates(p=>({...p,[draft.id]:'上传 '+percentage+'%'})),signal)
        signal.throwIfAborted()
        const bound=await bindDestination(user.id,draft.client_token,root)
        signal.throwIfAborted()
        setDrafts(prev=>prev.map(row=>row.id===draft.id?{...row,output_directory:bound,destination_locked:true}:row))
        if(!await directoryPermission(bound))throw new Error('此草稿原先绑定的目录需要重新授权')
        signal.throwIfAborted()
        creationStarted=true
        await post<Order>('/orders',{upload_id:upload.id,name:draft.name,template_ids:draft.template_ids,sticker_ids:draft.sticker_ids||[],print_settings:draft.print_settings,client_token:draft.client_token},signal)
        signal.throwIfAborted()
        setDrafts(prev=>prev.filter(d=>d.id!==draft.id));setSelected(prev=>prev.filter(id=>id!==draft.id));successful++
      } catch(e){
        if(signal.aborted)break
        if(!draft.destination_locked&&(!creationStarted||e instanceof ApiError&&e.status>=400&&e.status<500&&e.status!==408)){
          setDrafts(prev=>prev.map(row=>row.id===draft.id?{...row,destination_locked:false,...(creationStarted?{client_token:crypto.randomUUID()}: {})}:row))
        }
        setStates(p=>({...p,[draft.id]:(e as Error).message}))
      }
    }
    if(signal.aborted)return
    setBusy(false)
    if(successful){notice('已提交 '+successful+' 个订单，可在任务中心查看进度');onCreated()}
  }
  return <><div className="page-heading"><div><h1>批量制作</h1><p>上传头像，选择模板和单张贴纸，自动生成可打印的贴纸。</p></div></div><p className="hint">{user.role==='admin'?'管理员生图免扣积分':`可用积分 ${user.credits?.available??0} · 冻结积分 ${user.credits?.frozen??0} · 本次预计冻结 ${count} 积分（成功生成每张扣 1 积分）`}</p><div className="steps"><div><span>1</span>上传头像</div><i/><div><span>2</span>选择模板</div><i/><div><span>3</span>生成与保存</div></div><input ref={input} type="file" hidden multiple accept="image/jpeg,image/png,image/webp" onChange={e=>{add(e.target.files);e.target.value=''}}/><button className={'drop-zone '+(drag?'dragging':'')} disabled={busy} onClick={()=>input.current?.click()} onDragOver={e=>{e.preventDefault();setDrag(true)}} onDragLeave={()=>setDrag(false)} onDrop={e=>{e.preventDefault();setDrag(false);if(!busy)add(e.dataTransfer.files)}}><Upload size={36} strokeWidth={1.5}/><strong>拖入头像照片</strong><span>支持 JPG、PNG、WebP，上传前在本地按短边 1024 px 缩小</span></button><section className="workspace-orders"><div className="section-heading"><h2>待提交订单 <span className="count">{drafts.length}</span></h2><span className="hint" role="status">{persisted?'草稿已保存':'正在保存草稿…'}</span><button className="text-button" onClick={()=>input.current?.click()} disabled={busy}><Plus size={16}/> 添加头像</button></div><div className="toolbar"><label className="check-line"><input type="checkbox" checked={drafts.length>0&&selected.length===drafts.length} onChange={e=>setSelected(e.target.checked?drafts.map(d=>d.id):[])} disabled={busy}/>全选</label><button className="button" disabled={!selected.length||busy} onClick={()=>choose(selected)}><Layers size={16}/>批量选择模板</button><button className="button" disabled={!selected.length||busy} onClick={()=>editPrint(selected)}><SlidersHorizontal size={16}/>打印参数</button></div><div className="orders-table"><div className="order-table-head"><span/><span>图片名称与保存位置</span><span>模板套装</span><span>打印规格</span><span>状态</span><span/></div>{drafts.length?drafts.map(d=><div className="order-row" key={d.id}><input aria-label={'选择 '+d.name} type="checkbox" checked={selected.includes(d.id)} disabled={busy} onChange={e=>setSelected(prev=>e.target.checked?[...prev,d.id]:prev.filter(id=>id!==d.id))}/><div className="avatar-name"><FileAvatar file={d.file}/><div className="draft-identity"><label className="draft-name-field"><span>图片名称／保存文件夹名</span><input aria-label="订单名称" value={d.name} disabled={busy||d.destination_locked} onChange={e=>setDrafts(prev=>prev.map(row=>row.id===d.id?{...row,name:e.target.value}:row))}/></label><button className="draft-directory" type="button" disabled={busy||d.destination_locked} title="单独选择此订单的保存位置" onClick={()=>void chooseOutput(d)}><FolderOpen size={14}/><span>{d.output_directory?d.output_directory.name:directory?'默认：'+directory.name:'选择保存位置'}</span></button>{d.output_directory&&!d.destination_locked&&<button className="text-button use-global" disabled={busy} onClick={()=>setDrafts(prev=>prev.map(row=>row.id===d.id?{...row,output_directory:undefined}:row))}>使用全局目录</button>}</div></div><button className="row-templates" onClick={()=>choose([d.id])} disabled={busy}>{d.template_ids.length||d.sticker_ids?.length?<><div className="tiny-sets">{d.template_ids.slice(0,3).map(id=>{const set=templates.find(s=>s.id===id);return <div key={id} className="tiny-set">{set?.images.slice(0,4).map(im=><img key={im.id} src={previewUrl(im.url)} alt=""/>)}<span>{set?.code||'已下架'}</span></div>})}</div>{(d.sticker_ids?.length||0)>0&&<span>单张贴纸 {d.sticker_ids!.length} 张</span>}{d.template_ids.length>3&&<span>+{d.template_ids.length-3}</span>}</>:<span className="add-template"><Plus size={18}/>选择模板</span>}</button><button className="print-summary" onClick={()=>editPrint([d.id])} disabled={busy}>{d.print_settings.paper_width_mm===210&&d.print_settings.paper_height_mm===297?'A4':d.print_settings.paper_width_mm+'×'+d.print_settings.paper_height_mm+' mm'}<span>{d.print_settings.long_edge_mm/10} cm · {d.print_settings.dpi} DPI</span></button><span className={'draft-status '+(states[d.id]?'has-message':'')}>{states[d.id]||'待提交'}</span><button className="icon-button" disabled={busy} title="移除此头像" onClick={()=>{setDrafts(prev=>prev.filter(row=>row.id!==d.id));setSelected(prev=>prev.filter(id=>id!==d.id))}}><Trash2 size={16}/></button></div>):<Empty title="还没有待提交的订单" description="从上传第一张头像开始，工作台会为你保留未提交的草稿。"/>}</div></section><div className="submit-bar"><div>{missingDirectory&&<p className="directory-required">请先选择保存目录，再提交订单。</p>}<p>已选 <strong>{chosen.length}</strong> 个订单 <span>/</span> 预计生成 <strong>{count}</strong> 张 · 导出 <strong>{chosen.reduce((sum,d)=>sum+selectionSummary(templates,d.template_ids,stickers,d.sticker_ids).exportCount,0)}</strong> 张</p></div><button className="button primary" onClick={submit} disabled={busy||!chosen.length||missingDirectory}>{busy?<Spinner/>:<ArrowRight size={17}/>}提交生成</button></div>{picker&&<Modal title="选择模板和贴纸" onClose={()=>setPicker(null)} wide><div className="unavailable-selections">{pickValue.filter(id=>!templates.some(t=>t.id===id&&t.active&&t.available!==false)).map(id=><button className="button" key={id} onClick={()=>setPickValue(pickValue.filter(value=>value!==id))}>移除不可用模板 {templates.find(t=>t.id===id)?.code||id}</button>)}{pickStickers.filter(id=>!stickers.some(s=>s.id===id&&s.active)).map(id=><button className="button" key={id} onClick={()=>setPickStickers(pickStickers.filter(value=>value!==id))}>移除不可用贴纸 {stickers.find(s=>s.id===id)?.code||id}</button>)}</div><div className="tabs"><button className={pickerTab==='templates'?'active':''} onClick={()=>setPickerTab('templates')}>模板套装</button><button className={pickerTab==='stickers'?'active':''} onClick={()=>setPickerTab('stickers')}>单张贴纸</button></div>{pickerTab==='templates'?<TemplateChooser templates={templates} value={pickValue} onChange={setPickValue}/>:<StickerChooser stickers={stickers} value={pickStickers} onChange={setPickStickers}/>}<details><summary>合并导出清单 · {selectionSummary(templates,pickValue,stickers,pickStickers).exportCount} 张</summary><div className="preview-template-grid">{selectionSummary(templates,pickValue,stickers,pickStickers).entries.map((e,i)=><figure key={i}><img src={previewUrl(e.url)} alt={e.code}/><figcaption>{i+1}. {e.code} · {e.source}</figcaption></figure>)}</div></details><div className="modal-footer"><span>已选 {pickValue.length} 套 · 实际生成 {selectionSummary(templates,pickValue,stickers,pickStickers).generationCount} 张 · 导出 {selectionSummary(templates,pickValue,stickers,pickStickers).exportCount} 张（最多 360 张）</span><button className="button primary" disabled={selectionSummary(templates,pickValue,stickers,pickStickers).exportCount>360} onClick={()=>{setDrafts(prev=>prev.map(d=>picker.includes(d.id)?{...d,template_ids:[...pickValue],sticker_ids:[...pickStickers]}:d));setPicker(null)}}>应用到 {picker.length} 个订单</button></div></Modal>}{printTargets&&<Modal title="打印参数" onClose={()=>setPrintTargets(null)}><PrintFields value={print} onChange={setPrint}/><div className="modal-footer"><span>应用到 {printTargets.length} 个订单</span><button className="button primary" onClick={()=>{setDrafts(prev=>prev.map(d=>printTargets.includes(d.id)?{...d,print_settings:{...print}}:d));setPrintTargets(null)}}>保存参数</button></div></Modal>}</>
}
