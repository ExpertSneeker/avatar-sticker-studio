import {useEffect,useRef,useState} from 'react'
import {ApiError,api,patch} from '../lib/api'
import type {User} from '../lib/types'
import {Modal,Spinner} from './UI'

type Limit={generation_concurrency:number}
export function AccountConcurrencyDialog({account,onClose,onSaved}:{account:User;onClose:()=>void;onSaved:()=>void}) {
  const [current,setCurrent]=useState<number|null>(null),[value,setValue]=useState(''),[loading,setLoading]=useState(true),[busy,setBusy]=useState(false),[error,setError]=useState(''),[revision,setRevision]=useState(0)
  const mounted=useRef(false),lock=useRef(false)
  const path=`/admin/users/${encodeURIComponent(account.id)}/concurrency`
  useEffect(()=>{mounted.current=true;return()=>{mounted.current=false}},[])
  useEffect(()=>{
    const controller=new AbortController()
    setLoading(true);setCurrent(null)
    api<Limit>(path,{signal:controller.signal}).then(result=>{
      if(controller.signal.aborted)return
      setCurrent(result.generation_concurrency);setValue(String(result.generation_concurrency))
    }).catch(e=>{if(!controller.signal.aborted)setError(e.message)}).finally(()=>{if(!controller.signal.aborted)setLoading(false)})
    return()=>controller.abort()
  },[path,revision])
  async function save() {
    const limit=Number(value)
    if(lock.current||current===null||!Number.isInteger(limit)||limit<1||limit>40)return
    lock.current=true;setBusy(true);setError('')
    try {
      await patch<Limit>(path,{generation_concurrency:limit,expected_limit:current})
      if(mounted.current)onSaved()
    } catch(e){
      if(!mounted.current)return
      setError((e as Error).message)
      if(e instanceof ApiError&&e.status===409)setRevision(v=>v+1)
    } finally {lock.current=false;if(mounted.current)setBusy(false)}
  }
  const close=()=>{if(!lock.current)onClose()}
  return <Modal title="设置账号生图并行上限" onClose={close}><form onSubmit={e=>{e.preventDefault();void save()}}>
    <p className="account-confirm-copy">{account.display_name}（{account.username}）的所有订单共用此上限，包括单张重跑。</p>
    {loading?<div className="account-loading" role="status"><Spinner/>正在读取当前上限</div>:current!==null&&<label className="field">最多同时生图数量<input type="number" min={1} max={40} step={1} required disabled={busy} value={value} onChange={e=>setValue(e.target.value)}/><span className="hint">可设置为 1–40，默认 2。用户可查看，只有管理员可以修改。</span></label>}
    <p className="account-confirm-copy">实际同时生图数量还受全站上限约束。FAL 排队中和仍占并发的待确认请求会计入；降低上限不会中断已发出的请求，后续生图会等待空位。已有请求的查询及图片后处理继续执行。</p>
    {error&&<div className="error-banner" role="alert">{error}</div>}
    <div className="modal-footer"><button type="button" className="button" disabled={busy} onClick={close}>取消</button>{!loading&&current===null&&<button type="button" className="button" onClick={()=>{setError('');setRevision(v=>v+1)}}>重新加载</button>}<button className="button primary" disabled={busy||loading||current===null||!Number.isInteger(Number(value))||Number(value)<1||Number(value)>40}>{busy&&<Spinner/>}保存上限</button></div>
  </form></Modal>
}
