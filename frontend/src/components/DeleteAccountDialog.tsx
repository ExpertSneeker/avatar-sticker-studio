import { useEffect, useRef, useState } from 'react'
import { ApiError, api } from '../lib/api'
import type { User } from '../lib/types'
import { Modal, Spinner } from './UI'

type DeletionPlan={preview_token:string;order_count:number;template_count:number;revision_count:number;asset_count:number;upload_count:number;blocked_count:number;can_delete:boolean;frozen_credits:number}

export function DeleteAccountDialog({account,onClose,onDeleted}:{account:User;onClose:()=>void;onDeleted:(pendingFiles:number)=>void}) {
  const [plan,setPlan]=useState<DeletionPlan|null>(null),[username,setUsername]=useState(''),[error,setError]=useState('')
  const [loading,setLoading]=useState(true),[busy,setBusy]=useState(false),[revision,setRevision]=useState(0)
  const lock=useRef(false),mounted=useRef(false),finished=useRef(onDeleted)
  finished.current=onDeleted
  useEffect(()=>{mounted.current=true;return()=>{mounted.current=false}},[])
  useEffect(()=>{
    const controller=new AbortController()
    setLoading(true);setPlan(null)
    api<DeletionPlan>(`/admin/users/${encodeURIComponent(account.id)}/deletion`,{signal:controller.signal})
      .then(value=>{if(!controller.signal.aborted)setPlan(value)})
      .catch(e=>{if(!controller.signal.aborted)setError(e.message)})
      .finally(()=>{if(!controller.signal.aborted)setLoading(false)})
    return()=>controller.abort()
  },[account.id,revision])
  function close(){if(!lock.current)onClose()}
  async function remove() {
    if(lock.current||!plan?.can_delete||username!==account.username)return
    lock.current=true;setBusy(true);setError('')
    try {
      const result=await api<{pending_files:number}>(`/admin/users/${encodeURIComponent(account.id)}`,{method:'DELETE',body:JSON.stringify({username,preview_token:plan.preview_token,confirmed:true})})
      if(mounted.current)finished.current(result.pending_files)
    } catch(e) {
      if(!mounted.current)return
      if(e instanceof ApiError&&e.status===404){finished.current(0);return}
      setError((e as Error).message);setUsername('');setPlan(null);setRevision(value=>value+1)
    } finally {lock.current=false;if(mounted.current)setBusy(false)}
  }
  return <Modal title="删除成员账号" onClose={close}>
    <p className="credits-confirm-copy">将永久删除「{account.display_name}」（{account.username}）及其全部订单、个人上传和相关图片，无法恢复。公共贴纸、公共模板和其他账号的数据不受影响。</p>
    {loading?<div className="credits-loading" role="status"><Spinner/>正在核对删除范围</div>:plan&&<>
      <ul className="account-delete-scope"><li>{plan.template_count} 套历史个人模板 <span>含 {plan.revision_count} 个历史版本</span></li><li>{plan.order_count} 个订单 <span>含订单信息、日志、原图、成品、拼图与预览缓存</span></li><li>{plan.asset_count} 张图片 <span>同时清理该账号的上传文件与未完成上传</span></li></ul>
      <p className="hint">未消耗的冻结积分（{plan.frozen_credits}）会释放，仅保留不含姓名、备注或图片内容的最小积分记账记录。</p>
      {!plan.can_delete&&<div className="error-banner" role="alert">仍有 {plan.blocked_count} 张图片正在处理或结果待核对。请处理完成后再删除账号。</div>}
    </>}
    {error&&<div className="error-banner" role="alert">{error}</div>}
    {plan?.can_delete&&<label className="field">输入用户名以确认<input autoComplete="off" spellCheck={false} value={username} placeholder={account.username} disabled={busy} onChange={e=>setUsername(e.target.value)}/></label>}
    <div className="modal-footer"><button className="button" disabled={busy} onClick={close}>取消</button>{!loading&&(!plan||!plan.can_delete)&&<button className="button" disabled={busy} onClick={()=>{setError('');setRevision(value=>value+1)}}>重新检查</button>}<button className="button danger" disabled={loading||busy||!plan?.can_delete||username!==account.username} onClick={()=>void remove()}>{busy&&<Spinner/>}确认删除账号</button></div>
  </Modal>
}
