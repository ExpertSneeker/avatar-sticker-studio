import {useRef,useState,useEffect} from 'react'
import {Tags,Plus} from 'lucide-react'
import {api,ApiError} from '../lib/api'
import {useCategories} from '../lib/categories'
import {Modal,Spinner,useNotice} from './UI'

type Reference={id:string;kind:string;code:string;name:string}
export function CategoryManager(){
 const [open,setOpen]=useState(false)
 return <><button className="button" onClick={()=>setOpen(true)}><Tags size={16}/>管理分类</button>{open&&<Editor onClose={()=>setOpen(false)}/>}</>
}
function Editor({onClose}:{onClose:()=>void}){
 const {categories,refresh}=useCategories(),notice=useNotice()
 const [names,setNames]=useState<Record<string,string>>({}),[name,setName]=useState(''),[busy,setBusy]=useState(false),[deleting,setDeleting]=useState<string|null>(null),[refs,setRefs]=useState<Reference[]|null>(null)
 const request=useRef<AbortController|null>(null)
 useEffect(()=>()=>request.current?.abort(),[])
 async function save(method:string,id?:string){
  if(request.current)return
  const c=new AbortController();request.current=c;setBusy(true)
  try{await api('/library/categories'+(id?'/'+id:''),{method,signal:c.signal,...(method==='DELETE'?{}:{headers:{'Content-Type':'application/json'},body:JSON.stringify({name:id?names[id]??categories.find(x=>x.id===id)?.name:name})})});if(!c.signal.aborted){refresh();setName('');setNames(previous=>{const next={...previous};if(id)delete next[id];return next});setDeleting(null);setRefs(null);notice('分类已更新')}}
  catch(e){if(!c.signal.aborted){const detail=e instanceof ApiError?e.detail as {resources?:Reference[]}:undefined;if(detail?.resources){setDeleting(null);setRefs(detail.resources)}else notice((e as Error).message,'error')}}
  finally{request.current=null;if(!c.signal.aborted)setBusy(false)}
 }
 return <Modal title="管理公共分类" onClose={onClose}><p className="hint">贴纸库和模板库共用这些分类。已被使用的分类须先移出资源再删除，默认分类可改名。</p><fieldset disabled={busy} className="template-edit-fields"><div className="category-create"><label className="field">新分类名称<input value={name} onChange={e=>setName(e.target.value)} maxLength={100}/></label><button className="button" disabled={!name.trim()} onClick={()=>void save('POST')}><Plus size={15}/>新增分类</button></div><div className="category-rows">{categories.map(c=><div key={c.id} className="category-row"><input aria-label={'分类名称 '+c.name} value={names[c.id]??c.name} maxLength={100} onChange={e=>setNames({...names,[c.id]:e.target.value})}/><button className="text-button" aria-label={'保存分类 '+c.name} disabled={!(names[c.id]??c.name).trim()||names[c.id]===undefined||names[c.id]===c.name} onClick={()=>void save('PATCH',c.id)}>保存</button><button className="text-button library-delete" disabled={c.id==='general'} aria-label={'删除分类 '+c.name} onClick={()=>setDeleting(c.id)}>{c.id==='general'?'默认':'删除'}</button></div>)}</div></fieldset>{busy&&<Spinner/>}
 {deleting&&<Modal title="确认删除分类" onClose={()=>setDeleting(null)}><p>确定删除分类「{categories.find(c=>c.id===deleting)?.name}」吗？</p><div className="modal-footer"><button className="button" disabled={busy} onClick={()=>setDeleting(null)}>取消</button><button className="button danger" disabled={busy} onClick={()=>void save('DELETE',deleting)}>确认删除</button></div></Modal>}
 {refs&&<Modal title="分类仍被使用" onClose={()=>setRefs(null)}><p>请先修改以下资源的分类，再删除此分类：</p><ul className="library-reference-list">{refs.map(r=><li key={r.kind+r.id}><strong>{r.name}</strong><span>{r.kind==='stickers'?'贴纸':'模板'} · {r.code}</span></li>)}</ul></Modal>}
 </Modal>
}
