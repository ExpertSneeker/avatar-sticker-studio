import {useEffect, useRef, useState} from 'react'
import {Trash2} from 'lucide-react'
import {api, ApiError} from '../lib/api'
import {Modal, Spinner, useNotice} from './UI'

type TemplateReference={id:string;code:string;name:string;active:boolean}
export function LibraryDeleteButton({kind,id,code,onDeleted}:{kind:'stickers'|'templates';id:string;code:string;onDeleted:()=>void}) {
  const [busy,setBusy]=useState(false)
  const [references,setReferences]=useState<TemplateReference[]|null>(null)
  const request=useRef<AbortController|null>(null)
  const notice=useNotice(),label=kind==='stickers'?'贴纸':'模板'
  useEffect(()=>()=>request.current?.abort(),[])
  async function remove() {
    if(request.current)return
    const controller=new AbortController();request.current=controller;setBusy(true)
    try {
      await api('/'+kind+'/'+id,{method:'DELETE',signal:controller.signal})
      if(!controller.signal.aborted){notice(label+'已删除，历史订单保留原版本');onDeleted()}
    } catch(error) {
      if(controller.signal.aborted)return
      const detail=error instanceof ApiError?error.detail as {templates?:TemplateReference[]}|undefined:undefined
      if(error instanceof ApiError&&error.status===409&&Array.isArray(detail?.templates))setReferences(detail.templates)
      else notice((error as Error).message,'error')
    } finally {
      request.current=null
      if(!controller.signal.aborted)setBusy(false)
    }
  }
  return <><button type="button" className="text-button library-delete" disabled={busy} aria-label={'删除'+label+' '+code} title={kind==='templates'?'删除集合，保留贴纸和历史订单':'仅可删除未被任何模板使用的贴纸'} onClick={()=>void remove()}>{busy?<Spinner/>:<Trash2 size={15}/>}删除</button>
    {references&&<Modal title="贴纸仍被模板使用" onClose={()=>setReferences(null)}><p>贴纸「{code}」无法删除。请先从以下模板中移除它，或删除这些模板：</p><ul className="library-reference-list">{references.map(t=><li key={t.id}><strong>{t.name}</strong><span>{t.code} · {t.active?'已上架':'已下架'}</span></li>)}</ul><p className="hint">已下架模板仍保留成员引用，也需要先移除。</p><div className="modal-footer"><button className="button primary" onClick={()=>setReferences(null)}>知道了</button></div></Modal>}
  </>
}
