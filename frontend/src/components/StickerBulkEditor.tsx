import {useEffect,useRef,useState} from 'react'
import type {Sticker} from '../lib/types'
import {api,ApiError} from '../lib/api'
import {useCategories} from '../lib/categories'
import {Modal,Spinner,useNotice} from './UI'

type Reference={sticker:{id:string;code:string};templates:{id:string;code:string;name:string;active:boolean}[]}
export function StickerBulkEditor({stickers,action,onClose,onSaved}:{stickers:Sticker[];action:'update'|'delete';onClose:()=>void;onSaved:()=>void}){
 const {categories}=useCategories(),notice=useNotice()
 const [category,setCategory]=useState(''),[status,setStatus]=useState(''),[busy,setBusy]=useState(false),[refs,setRefs]=useState<Reference[]|null>(null)
 const request=useRef<AbortController|null>(null)
 useEffect(()=>()=>request.current?.abort(),[])
 async function save(){
  if(request.current)return
  const c=new AbortController();request.current=c;setBusy(true);setRefs(null)
  try{await api('/stickers/batch',{method:'POST',signal:c.signal,headers:{'Content-Type':'application/json'},body:JSON.stringify({ids:stickers.map(s=>s.id),action,...(action==='update'?{...(category?{category}:{}),...(status?{active:status==='active'}:{})}:{})})});if(!c.signal.aborted){notice('已'+(action==='delete'?'删除':'更新')+' '+stickers.length+' 张贴纸');onSaved();onClose()}}
  catch(e){if(!c.signal.aborted){const detail=e instanceof ApiError?e.detail as {references?:Reference[]}:undefined;if(detail?.references)setRefs(detail.references);else notice((e as Error).message,'error')}}
  finally{request.current=null;if(!c.signal.aborted)setBusy(false)}
 }
 return <Modal title={action==='delete'?'确认批量删除':'批量编辑贴纸'} onClose={()=>{if(!busy)onClose()}}><p>已选择 {stickers.length} 张贴纸。{action==='delete'?'确认后从贴纸库移除，历史订单保留原版本。':'仅修改下方选定字段，图片、编号和历史订单保留原版本。'}</p><details className="batch-selection"><summary>查看所选贴纸</summary><ul>{stickers.map(s=><li key={s.id}>{s.code} · {s.name}</li>)}</ul></details>
 {action==='update'&&<fieldset className="template-edit-fields form-grid" disabled={busy}><label className="field">修改分类<select aria-label="修改分类" value={category} onChange={e=>setCategory(e.target.value)}><option value="">保持原分类</option>{categories.map(c=><option key={c.id} value={c.id}>{c.name}</option>)}</select></label><label className="field">修改状态<select aria-label="修改状态" value={status} onChange={e=>setStatus(e.target.value)}><option value="">保持原状态</option><option value="active">启用</option><option value="inactive">停用</option></select></label></fieldset>}
 {refs&&<div role="alert"><p>部分贴纸仍被模板使用，本次未删除任何贴纸。请先移除以下引用：</p><ul className="library-reference-list">{refs.map(r=><li key={r.sticker.id}><strong>{r.sticker.code}</strong>{r.templates.map(t=><span key={t.id}>{t.name} · {t.code} · {t.active?'已上架':'已下架'}</span>)}</li>)}</ul></div>}
 <div className="modal-footer"><button className="button" disabled={busy} onClick={onClose}>取消</button><button className={'button '+(action==='delete'?'danger':'primary')} disabled={busy||!stickers.length||stickers.length>1000||(action==='update'&&!category&&!status)} onClick={()=>void save()}>{busy&&<Spinner/>}{action==='delete'?'确认删除':'保存批量修改'}</button></div></Modal>
}
