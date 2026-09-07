import {useCategories,categoryName} from '../lib/categories'
import {CategoryManager} from '../components/CategoryManager'
import { LibraryDeleteButton } from '../components/LibraryDeleteButton'
import { searchMatcher } from '../lib/search'
import { ImagePreview } from '../components/ImagePreview'
import { previewUrl } from '../lib/preview'
import { useEffect, useMemo, useRef, useState } from 'react'
import { Plus, Search, ArrowUp, ArrowDown, X, Pencil, Eye } from 'lucide-react'
import { Empty, Modal, Spinner, useNotice } from '../components/UI'
import { api } from '../lib/api'
import { StickerChooser } from './Stickers'
import type { Sticker, TemplateSet } from '../lib/types'

function SetEditor({set,stickers,onClose,onSaved}:{set:TemplateSet|null;stickers:Sticker[];onClose:()=>void;onSaved:()=>void}) {
 const {categories}=useCategories()
 const [ids,setIds]=useState<string[]>(set?.sticker_ids||set?.images.map(im=>im.sticker_id||im.id)||[])
 const [name,setName]=useState(set?.name||''),[code,setCode]=useState(set?.code||''),[category,setCategory]=useState(set?.category||'general'),[busy,setBusy]=useState(false)
 const notice=useNotice(),submission=useRef<AbortController|null>(null)
 useEffect(()=>()=>submission.current?.abort(),[])
 function move(index:number,offset:number){setIds(prev=>{const next=[...prev];[next[index],next[index+offset]]=[next[index+offset],next[index]];return next})}
 async function save(){if(submission.current)return;const controller=new AbortController();submission.current=controller;setBusy(true);try{await api(set?'/templates/'+set.id:'/templates',{method:set?'PUT':'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({code,name,category,sticker_ids:ids}),signal:controller.signal});if(!controller.signal.aborted){notice('套装已保存，旧订单保留原版本');onSaved();onClose()}}catch(e){if(!controller.signal.aborted)notice((e as Error).message,'error')}finally{submission.current=null;setBusy(false)}}
 return <Modal title={set?'编辑模板套装':'新建模板套装'} onClose={onClose} wide><fieldset className="template-edit-fields" disabled={busy}><div className="form-grid template-meta"><label className="field">套装编号<input value={code} onChange={e=>setCode(e.target.value)}/></label><label className="field">套装名称<input value={name} onChange={e=>setName(e.target.value)}/></label><label className="field">分类<select aria-label="分类" value={category} onChange={e=>setCategory(e.target.value)}>{categories.map(({id,name:label})=><option key={id} value={id}>{label}</option>)}</select></label></div><p className="hint">从公共贴纸库选择 1–100 张贴纸。下方顺序决定套装导出顺序。</p><StickerChooser stickers={stickers} value={ids} onChange={next=>{if(next.length>100)notice('每套最多 100 张贴纸','error');else setIds(next)}}/><div className="edit-template-grid">{ids.map((id,index)=>{const image=stickers.find(s=>s.id===id);return <div className="edit-template" key={id}><img src={previewUrl(image?.image.url)} alt={image?.code||'不可用贴纸'}/><div><span>{index+1} · {image?.code}</span><button className="icon-button" disabled={index===0} onClick={()=>move(index,-1)} title="向前移动"><ArrowUp size={14}/></button><button className="icon-button" disabled={index===ids.length-1} onClick={()=>move(index,1)} title="向后移动"><ArrowDown size={14}/></button><button className="icon-button" onClick={()=>setIds(ids.filter(x=>x!==id))} title="移除贴纸"><X size={14}/></button></div></div>})}</div></fieldset><div className="modal-footer"><span>已选 {ids.length} 张</span><button className="button primary" disabled={busy||!code.trim()||!name.trim()||ids.length<1||ids.length>100||ids.some(id=>!stickers.find(s=>s.id===id)?.active)} onClick={()=>void save()}>{busy&&<Spinner/>}保存套装</button></div></Modal>
}
export function Templates({templates,stickers=[],admin,canEdit=admin,onRefresh}:{templates:TemplateSet[];stickers?:Sticker[];admin:boolean;canEdit?:boolean;onRefresh:()=>void}) {
  const {categories}=useCategories()
  const [category,setCategory]=useState('all'),[search,setSearch]=useState('')
  const [editor,setEditor]=useState<TemplateSet|null|undefined>(undefined),[preview,setPreview]=useState<TemplateSet|null>(null)
  useEffect(()=>{if(category!=='all'&&!categories.some(c=>c.id===category))setCategory('all')},[categories,category])
  const filtered=useMemo(()=>{
    const matchesSearch=searchMatcher(search)
    return templates.filter(t=>(category==='all'||t.category===category)&&matchesSearch(t.name+' '+t.code))
  },[templates,category,search])

  return <>
    <div className="page-heading"><div><h1>模板库</h1><p>从公共贴纸库组合有序套装，所有成员共享使用。</p></div>{canEdit&&<div className="library-heading-actions"><CategoryManager/><button className="button primary" onClick={()=>setEditor(null)}><Plus size={17}/>新建套装</button></div>}</div>
    <div className="filter-bar"><label className="search-input"><Search size={16}/><input aria-label="搜索模板" placeholder="搜索名称或编号，支持空格多词" value={search} onChange={e=>setSearch(e.target.value)}/></label></div>
    <div className="filter-bar"><div className="tabs" role="group" aria-label="模板分类">{[{id:'all',name:'全部分类'},...categories].map(({id,name:label})=><button className={category===id?'active':''} aria-pressed={category===id} onClick={()=>setCategory(id)} key={id}>{label}</button>)}</div></div>
    {filtered.length?<div className="template-library">{filtered.map(set=><article className="library-set" key={set.id}>
      <button className="library-mosaic" onClick={()=>setPreview(set)} aria-label={'预览 '+set.name}>{set.images.slice(0,12).map(im=><img key={im.id} src={previewUrl(im.url)} alt={set.name+' 模板 '+im.position} loading="lazy"/>)}</button>
      <div className="library-details"><div><h3>{set.name}</h3><p>{set.code} <span>·</span> {set.images.length} 张 <span>·</span> v{set.revision}</p><p>{'公共模板'} <span>·</span> {categoryName(categories,set.category)}</p></div>{set.available===false&&<span className="availability">包含不可用贴纸</span>}</div>
      <div className="library-actions"><button className="text-button" onClick={()=>setPreview(set)}><Eye size={15}/>预览</button>{canEdit&&(set.editable??admin)&&<><button className="text-button" onClick={()=>setEditor(set)}><Pencil size={15}/>编辑</button><LibraryDeleteButton kind="templates" id={set.id} code={set.code} onDeleted={onRefresh}/></>}</div>
    </article>)}</div>:<Empty title={search||category!=='all'?'没有找到匹配的套装':'模板库等待你的第一套作品'} description="可调整筛选条件，或从公共贴纸库选择 1–100 张创建套装。">{canEdit&&<button className="button" onClick={()=>setEditor(null)}><Plus size={16}/>新建套装</button>}</Empty>}
    {canEdit&&editor!==undefined&&<SetEditor set={editor} stickers={stickers} onClose={()=>setEditor(undefined)} onSaved={onRefresh}/>}
    {preview&&<Modal title={preview.code+' · '+preview.name} onClose={()=>setPreview(null)} wide><div className="preview-template-grid">{preview.images.map((im,index)=><figure key={im.id}><ImagePreview src={im.url} alt={'模板 '+(index+1)}/><figcaption>{String(index+1).padStart(2,'0')}</figcaption></figure>)}</div></Modal>}
  </>
}
