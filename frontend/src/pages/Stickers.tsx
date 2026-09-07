import {useCategories,categoryName} from '../lib/categories'
import {CategoryManager} from '../components/CategoryManager'
import {StickerBulkEditor} from '../components/StickerBulkEditor'
import { LibraryDeleteButton } from '../components/LibraryDeleteButton'
import { useEffect, useRef, useState } from 'react'
import { Plus, Pencil, Eye, Upload, Check, LayoutGrid, Grid3X3, List } from 'lucide-react'
import { api } from '../lib/api'
import { prepareUploadImage } from '../lib/image'
import { previewUrl } from '../lib/preview'
import { searchMatcher } from '../lib/search'
import type { Sticker } from '../lib/types'
import { Empty, Modal, Spinner, useNotice } from '../components/UI'
import { ImagePreview } from '../components/ImagePreview'

export function StickerChooser({stickers,value,onChange}:{stickers:Sticker[];value:string[];onChange:(ids:string[])=>void}) {
 const {categories}=useCategories()
 const [search,setSearch]=useState(''),[category,setCategory]=useState('all')
 useEffect(()=>{if(category!=='all'&&!categories.some(c=>c.id===category))setCategory('all')},[categories,category])
 const matches=searchMatcher(search)
 const filtered=stickers.filter(s=>(s.active||value.includes(s.id))&&(category==='all'||category===s.category)&&matches(s.code+' '+s.name))
 return <><div className="filter-bar"><label className="search-input"><input aria-label="搜索贴纸" value={search} placeholder="搜索贴纸编号或名称" onChange={e=>setSearch(e.target.value)}/></label><select aria-label="筛选贴纸分类" value={category} onChange={e=>setCategory(e.target.value)}><option value="all">全部分类</option>{categories.map(({id,name:label})=><option key={id} value={id}>{label}</option>)}</select></div><div className="template-picker">{filtered.map(s=><button type="button" key={s.id} className={'template-option '+(value.includes(s.id)?'selected':'')} disabled={!s.active&&!value.includes(s.id)} aria-pressed={value.includes(s.id)} onClick={()=>onChange(value.includes(s.id)?value.filter(id=>id!==s.id):[...value,s.id])}><img className="avatar" src={previewUrl(s.image.url)} alt=""/><div><strong>{s.name}</strong><span>{s.code}{!s.active?' · 不可用':''}</span></div>{value.includes(s.id)?<Check size={16}/>:<Plus size={16}/>}</button>)}</div>{!filtered.length&&<Empty title="没有匹配的贴纸" description="调整分类或搜索条件。"/>}</>
}
function StickerEditor({sticker,onClose,onSaved}:{sticker:Sticker|null;onClose:()=>void;onSaved:()=>void}) {
 const {categories}=useCategories()
 const [code,setCode]=useState(sticker?.code||''),[name,setName]=useState(sticker?.name||''),[category,setCategory]=useState(sticker?.category||'general'),[files,setFiles]=useState<File[]>([]),[busy,setBusy]=useState(false)
 const notice=useNotice(),controller=useRef<AbortController|null>(null)
 useEffect(()=>()=>controller.current?.abort(),[])
 async function save(){if(controller.current)return;const c=new AbortController();controller.current=c;setBusy(true);try{const form=new FormData();if(sticker){form.append('code',code);form.append('name',name);form.append('category',category)}else{form.append('category',category);form.append('codes',JSON.stringify(files.map(f=>f.name.replace(/\.[^.]+$/,''))))}
 for(const file of files)form.append(sticker?'file':'files',await prepareUploadImage(file,c.signal));await api(sticker?'/stickers/'+sticker.id:'/stickers',{method:sticker?'PUT':'POST',body:form,signal:c.signal});if(!c.signal.aborted){notice(sticker?'贴纸已更新，旧订单保留原版本':'贴纸已上传');onSaved();onClose()}}catch(e){if(!c.signal.aborted)notice((e as Error).message,'error')}finally{controller.current=null;setBusy(false)}}
 return <Modal title={sticker?'编辑贴纸':'批量上传贴纸'} onClose={onClose}><fieldset className="template-edit-fields" disabled={busy}>{sticker&&<><label className="field">贴纸编号<input value={code} onChange={e=>setCode(e.target.value)}/></label><label className="field">贴纸名称<input value={name} onChange={e=>setName(e.target.value)}/></label><ImagePreview src={sticker.image.url} alt={sticker.name}/></>}<label className="field">分类<select aria-label="分类" value={category} onChange={e=>setCategory(e.target.value)}>{categories.map(({id,name:label})=><option key={id} value={id}>{label}</option>)}</select></label><label className="upload-template button"><Upload size={16}/>{sticker?'替换图片（可选）':'选择贴纸图片'}<input type="file" multiple={!sticker} accept="image/png,image/jpeg,image/webp" onChange={e=>setFiles(Array.from(e.target.files||[]))}/></label>{!sticker&&<p className="hint">文件名去掉扩展名作为贴纸编号；编号必须唯一。所选分类应用于本次全部上传图片。</p>}<ul>{files.map((f,i)=><li key={i}>{f.name}{!sticker?' → '+f.name.replace(/\.[^.]+$/,''):''}</li>)}</ul></fieldset><div className="modal-footer"><button className="button primary" disabled={busy||(sticker?!code.trim()||!name.trim():!files.length)} onClick={()=>void save()}>{busy&&<Spinner/>}保存贴纸</button></div></Modal>
}
type LibraryView='grid'|'compact'|'list'
function storedView():LibraryView{try{const value=localStorage.getItem('sticker-library-view');return value==='compact'||value==='list'?value:'grid'}catch{return 'grid'}}
export function Stickers({stickers,canEdit,onRefresh}:{stickers:Sticker[];canEdit:boolean;onRefresh:()=>void}) {
 const {categories}=useCategories()
 const [editor,setEditor]=useState<Sticker|null|undefined>(),[preview,setPreview]=useState<Sticker|null>(null),[search,setSearch]=useState(''),[category,setCategory]=useState('all')
 const [view,setView]=useState<LibraryView>(storedView),[selected,setSelected]=useState<string[]>([]),[batch,setBatch]=useState<'update'|'delete'|null>(null)
 useEffect(()=>{if(category!=='all'&&!categories.some(c=>c.id===category))setCategory('all')},[categories,category])
 const matches=searchMatcher(search)
 const filtered=stickers.filter(s=>(category==='all'||s.category===category)&&matches(s.code+' '+s.name))
 const editable=filtered.filter(s=>s.editable),chosen=stickers.filter(s=>s.editable&&selected.includes(s.id))
 const allSelected=editable.length>0&&editable.every(s=>selected.includes(s.id))
 useEffect(()=>{if(!canEdit){setSelected([]);setBatch(null);setEditor(undefined)}},[canEdit])
 function changeView(next:LibraryView){setView(next);try{localStorage.setItem('sticker-library-view',next)}catch{/* View remains usable without storage. */}}
 function select(id:string){setSelected(prev=>prev.includes(id)?prev.filter(x=>x!==id):[...prev,id])}
 function selectAll(){setSelected(prev=>allSelected?prev.filter(id=>!editable.some(s=>s.id===id)):Array.from(new Set([...prev,...editable.map(s=>s.id)])))}

 return <><div className="page-heading"><div><h1>贴纸库</h1><p>公共贴纸统一维护，可单张选择，也可组合成模板套装。</p></div>{canEdit&&<div className="library-heading-actions"><CategoryManager/><button className="button primary" onClick={()=>setEditor(null)}><Plus size={16}/>批量上传</button></div>}</div>
 <div className="filter-bar sticker-filters"><label className="search-input"><input aria-label="搜索贴纸" value={search} onChange={e=>setSearch(e.target.value)} placeholder="搜索编号或名称"/></label><select aria-label="贴纸分类" value={category} onChange={e=>setCategory(e.target.value)}><option value="all">全部分类</option>{categories.map(c=><option key={c.id} value={c.id}>{c.name}</option>)}</select><span className="hint">{filtered.length} 张贴纸</span><div className="library-views" role="group" aria-label="贴纸库视图">{([{id:'grid',name:'大图视图',icon:LayoutGrid},{id:'compact',name:'紧凑网格',icon:Grid3X3},{id:'list',name:'列表视图',icon:List}] as const).map(v=><button key={v.id} className={'icon-button '+(view===v.id?'active':'')} aria-label={v.name} title={v.name} aria-pressed={view===v.id} onClick={()=>changeView(v.id)}><v.icon size={18}/></button>)}</div></div>
 {canEdit&&<div className="sticker-bulk-bar"><label className="check-line"><input type="checkbox" checked={allSelected} disabled={!editable.length} onChange={selectAll}/>全选筛选结果</label><span>已选 {chosen.length} 张{chosen.length>1000?'（每次最多 1000 张）':''}</span><button className="text-button" disabled={!chosen.length} onClick={()=>setSelected([])}>清空选择</button><div><button className="button" disabled={!chosen.length||chosen.length>1000} onClick={()=>setBatch('update')}>批量编辑</button><button className="button library-delete" disabled={!chosen.length||chosen.length>1000} onClick={()=>setBatch('delete')}>批量删除</button></div></div>}
 <div className={'template-library sticker-library sticker-'+view}>{filtered.map(s=><article className={'library-set '+(selected.includes(s.id)&&canEdit?'is-selected':'')} key={s.id}>{canEdit&&s.editable&&<label className="sticker-select"><input type="checkbox" aria-label={'选择贴纸 '+s.code} checked={selected.includes(s.id)} onChange={()=>select(s.id)}/></label>}<button className="library-mosaic sticker-cover" onClick={()=>setPreview(s)} aria-label={'预览 '+s.name}><img src={previewUrl(s.image.url)} alt={s.name} loading="lazy"/></button><div className="library-details"><div><h3>{s.name}</h3><p>{s.code} · v{s.revision}</p><span className="category-badge">{categoryName(categories,s.category)}</span></div></div><div className="library-actions"><button className="icon-button" title="预览贴纸" aria-label={"预览贴纸 "+s.code} onClick={()=>setPreview(s)}><Eye size={16}/></button>{canEdit&&s.editable&&<><button className="icon-button" title="编辑贴纸" aria-label={"编辑贴纸 "+s.code} onClick={()=>setEditor(s)}><Pencil size={16}/></button><LibraryDeleteButton iconOnly kind="stickers" id={s.id} code={s.code} onDeleted={onRefresh}/></>}</div></article>)}</div>
 {!filtered.length&&<Empty title="暂无匹配的贴纸" description="公共贴纸上传后会显示在这里。"/>}
 {canEdit&&editor!==undefined&&<StickerEditor sticker={editor} onClose={()=>setEditor(undefined)} onSaved={onRefresh}/>}
 {canEdit&&batch&&<StickerBulkEditor stickers={chosen} action={batch} onClose={()=>setBatch(null)} onSaved={()=>{setSelected([]);onRefresh()}}/>}
 {preview&&<Modal title={preview.code+' · '+preview.name} onClose={()=>setPreview(null)}><ImagePreview src={preview.image.url} alt={preview.name}/></Modal>}</>
}
