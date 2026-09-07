import { searchMatcher } from '../lib/search'
import { ImagePreview } from '../components/ImagePreview'
import { previewUrl } from '../lib/preview'
import { useEffect, useMemo, useRef, useState } from 'react'
import { Plus, Search, ArrowUp, ArrowDown, X, Upload, Pencil, Eye } from 'lucide-react'
import { Empty, Modal, Spinner, TEMPLATE_CATEGORIES, useNotice } from '../components/UI'
import { api, patch } from '../lib/api'
import { prepareUploadImage } from '../lib/image'
import type { TemplateImage, TemplateSet } from '../lib/types'

type EditImage={existing?:TemplateImage;file?:File;url:string;key:string}
function SetEditor({set,admin,onClose,onSaved}:{set:TemplateSet|null;admin:boolean;onClose:()=>void;onSaved:()=>void}) {
  const [images,setImages]=useState<EditImage[]>(set?.images.map(im=>({existing:im,url:im.url,key:im.id}))||[])
  const [name,setName]=useState(set?.name||''),[code,setCode]=useState(set?.code||''),[category,setCategory]=useState(set?.category||'boy')
  const [scope,setScope]=useState<'public'|'personal'>(set?(set.scope||'public'):'personal')
  const [busy,setBusy]=useState(false),[progress,setProgress]=useState(''),notice=useNotice()
  const submission=useRef<AbortController|null>(null)
  const imageUrls=useRef<string[]>([])
  useEffect(()=>()=>{submission.current?.abort();imageUrls.current.forEach(url=>URL.revokeObjectURL(url))},[])
  function add(files:FileList|null) {
    if(!files)return
    if(images.length+files.length>100){notice('每套最多 100 张，请分套上传','error');return}
    const next=Array.from(files).sort((a,b)=>a.name.localeCompare(b.name,undefined,{numeric:true})).map(file=>({file,url:URL.createObjectURL(file),key:crypto.randomUUID()}))
    imageUrls.current.push(...next.map(im=>im.url))
    setImages(prev=>[...prev,...next])
  }
  function move(index:number,offset:number) {
    setImages(prev=>{const next=[...prev];[next[index],next[index+offset]]=[next[index+offset],next[index]];return next})
  }
  async function save() {
    if(images.length<1||images.length>100){notice('每套需包含 1 至 100 张独立模板','error');return}
    if(!name.trim()||!code.trim()){notice('请填写套装名称和编号','error');return}
    if(submission.current)return
    const controller=new AbortController();submission.current=controller
    setBusy(true)
    try {
      const form=new FormData()
      form.append('name',name);form.append('code',code);form.append('category',category)
      if(!set)form.append('scope',admin?scope:'personal')
      // Full ordered multipart sequence: retained entries plus new upload indexes.
      form.append('existing_ids',JSON.stringify(images.filter(im=>im.existing).map(im=>im.existing!.id)))
      const newImages=images.filter(im=>im.file)
      form.append('image_order',JSON.stringify(images.map(im=>im.existing?{id:im.existing.id}:{file_index:newImages.findIndex(n=>n.key===im.key)})))
      for(const [index,image] of newImages.entries()) {
        setProgress(`正在本地压缩 ${index+1} / ${newImages.length}`)
        const prepared=await prepareUploadImage(image.file!,controller.signal)
        form.append('files',prepared)
      }
      controller.signal.throwIfAborted()
      setProgress('正在上传模板')
      await api(set?'/templates/'+set.id:'/templates',{method:set?'PUT':'POST',body:form,signal:controller.signal})
      controller.signal.throwIfAborted()
      notice(set?'模板新版本已保存，旧任务保持原版本':'模板套装已创建');onSaved();onClose()
    } catch(e){if(!controller.signal.aborted)notice((e as Error).message,'error')} finally{submission.current=null;setBusy(false);setProgress('')}
  }
  return <Modal title={set?'编辑模板套装':'新建模板套装'} onClose={onClose} wide><fieldset className="template-edit-fields" disabled={busy}><div className="form-grid template-meta"><label className="field">套装编号<input value={code} onChange={e=>setCode(e.target.value)} placeholder="例如 B001" disabled={!!set}/></label><label className="field">套装名称<input value={name} onChange={e=>setName(e.target.value)} placeholder="例如 春日出游"/></label><label className="field">分类<select value={category} onChange={e=>setCategory(e.target.value)}>{TEMPLATE_CATEGORIES.map(([id,label])=><option value={id} key={id}>{label}</option>)}</select></label></div>{admin&&!set?<label className="field">模板归属<select value={scope} onChange={e=>setScope(e.target.value as 'public'|'personal')}><option value="personal">个人模板 · 仅自己可见</option><option value="public">公共模板 · 上架后所有人可用</option></select></label>:<p className="hint">{(set?.scope||scope)==='personal'?'个人模板，仅自己可见和使用。':'公共模板，上架后所有人可用。'}</p>}<label className="upload-template button"><Upload size={16}/>添加模板图片<input type="file" multiple accept="image/png,image/jpeg,image/webp" onChange={e=>{add(e.target.files);e.target.value=''}}/></label><span className="muted">已选 {images.length} 张 · 每套 1–100 张 · 可调整排列顺序</span><div className="edit-template-grid">{images.map((image,index)=><div className="edit-template" key={image.key}><img src={previewUrl(image.url)} alt={'模板 '+(index+1)}/><div><span>{String(index+1).padStart(2,'0')}</span><button className="icon-button" disabled={index===0} onClick={()=>move(index,-1)} title="向前移动"><ArrowUp size={14}/></button><button className="icon-button" disabled={index===images.length-1} onClick={()=>move(index,1)} title="向后移动"><ArrowDown size={14}/></button><button className="icon-button" onClick={()=>setImages(prev=>prev.filter(im=>im.key!==image.key))} title="移除图片"><X size={14}/></button></div></div>)}</div></fieldset><div className="modal-footer"><p className="hint">上传前在本地按短边 1024 px 缩小并保留透明背景。替换会创建新版本。</p><button className="button primary" disabled={busy||images.length<1||images.length>100} onClick={save}>{busy&&<Spinner/>}{busy?progress:'保存套装'}</button></div></Modal>
}
export function Templates({templates,admin,onRefresh}:{templates:TemplateSet[];admin:boolean;onRefresh:()=>void}) {
  const [scope,setScope]=useState('all'),[category,setCategory]=useState('all'),[search,setSearch]=useState('')
  const [editor,setEditor]=useState<TemplateSet|null|undefined>(undefined),[preview,setPreview]=useState<TemplateSet|null>(null),notice=useNotice()
  const filtered=useMemo(()=>{
    const matchesSearch=searchMatcher(search)
    return templates.filter(t=>(scope==='all'||(t.scope||'public')===scope)&&(category==='all'||t.category===category)&&matchesSearch(t.name+' '+t.code))
  },[templates,scope,category,search])
  async function toggle(set:TemplateSet) {
    try {await patch('/templates/'+set.id,{active:!set.active});notice(set.active?'套装已下架':'套装已上架');onRefresh()}catch(e){notice((e as Error).message,'error')}
  }
  return <>
    <div className="page-heading"><div><h1>模板库</h1><p>套装张数自定义。公共模板共享使用，个人模板仅自己可见。</p></div><button className="button primary" onClick={()=>setEditor(null)}><Plus size={17}/>新建套装</button></div>
    <div className="filter-bar"><div className="tabs" role="group" aria-label="模板归属">{[['all','全部套装'],['public','公共模板'],['personal','个人模板']].map(([id,label])=><button className={scope===id?'active':''} aria-pressed={scope===id} onClick={()=>setScope(id)} key={id}>{label}</button>)}</div><label className="search-input"><Search size={16}/><input aria-label="搜索模板" placeholder="搜索名称或编号，支持空格多词" value={search} onChange={e=>setSearch(e.target.value)}/></label></div>
    <div className="filter-bar"><div className="tabs" role="group" aria-label="模板分类">{[['all','全部分类'],...TEMPLATE_CATEGORIES].map(([id,label])=><button className={category===id?'active':''} aria-pressed={category===id} onClick={()=>setCategory(id)} key={id}>{label}</button>)}</div></div>
    {filtered.length?<div className="template-library">{filtered.map(set=><article className="library-set" key={set.id}>
      <button className="library-mosaic" onClick={()=>setPreview(set)} aria-label={'预览 '+set.name}>{set.images.slice(0,12).map(im=><img key={im.id} src={previewUrl(im.url)} alt={set.name+' 模板 '+im.position} loading="lazy"/>)}</button>
      <div className="library-details"><div><h3>{set.name}</h3><p>{set.code} <span>·</span> {set.images.length} 张 <span>·</span> v{set.revision}</p><p>{set.scope==='personal'?'个人模板':'公共模板'} <span>·</span> {TEMPLATE_CATEGORIES.find(([id])=>id===set.category)?.[1]||set.category}</p></div><span className={'availability '+(set.active?'on':'')}>{set.active?'已上架':'未上架'}</span></div>
      <div className="library-actions"><button className="text-button" onClick={()=>setPreview(set)}><Eye size={15}/>预览</button>{(set.editable??admin)&&<><button className="text-button" onClick={()=>setEditor(set)}><Pencil size={15}/>编辑</button><button className="text-button" onClick={()=>toggle(set)}>{set.active?'下架':'上架'}</button></>}</div>
    </article>)}</div>:<Empty title={search||category!=='all'||scope!=='all'?'没有找到匹配的套装':'模板库等待你的第一套作品'} description="可调整筛选条件，或上传 1–100 张独立图片创建自己的模板套装。"><button className="button" onClick={()=>setEditor(null)}><Plus size={16}/>新建套装</button></Empty>}
    {editor!==undefined&&<SetEditor set={editor} admin={admin} onClose={()=>setEditor(undefined)} onSaved={onRefresh}/>}
    {preview&&<Modal title={preview.code+' · '+preview.name} onClose={()=>setPreview(null)} wide><div className="preview-template-grid">{preview.images.map((im,index)=><figure key={im.id}><ImagePreview src={im.url} alt={'模板 '+(index+1)}/><figcaption>{String(index+1).padStart(2,'0')}</figcaption></figure>)}</div></Modal>}
  </>
}
