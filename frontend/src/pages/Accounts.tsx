import { searchMatcher } from '../lib/search'
import { useEffect, useRef, useState } from 'react'
import { Copy, Plus, RefreshCw, Search, Users } from 'lucide-react'
import { api, patch, post } from '../lib/api'
import type { User } from '../lib/types'
import { Empty, Modal, Spinner, useNotice } from '../components/UI'
import { AccountConcurrencyDialog } from '../components/AccountConcurrencyDialog'
import { DeleteAccountDialog } from '../components/DeleteAccountDialog'
import { isAdmin, roleLabel } from '../lib/customer-orders'
import './Accounts.css'

type Account=User
export function Accounts({currentUser}:{currentUser:User}) {
  const notice=useNotice()
  const [users,setUsers]=useState<Account[]>([]),[loading,setLoading]=useState(true),[error,setError]=useState(''),[revision,setRevision]=useState(0)
  const [query,setQuery]=useState(''),[status,setStatus]=useState('all')
  const [createOpen,setCreateOpen]=useState(false),[username,setUsername]=useState(''),[displayName,setDisplayName]=useState('')
  const [confirm,setConfirm]=useState<{user:Account;action:'password'|'toggle'}|null>(null)
  const [concurrency,setConcurrency]=useState<Account|null>(null)
  const [deleting,setDeleting]=useState<Account|null>(null)
  const [secret,setSecret]=useState<{title:string;value:string;username?:string}|null>(null)
  const [busy,setBusy]=useState(false),[formError,setFormError]=useState('')
  const lock=useRef(false),mounted=useRef(false)
  useEffect(()=>{mounted.current=true;return()=>{mounted.current=false}},[])
  useEffect(()=>{
    const controller=new AbortController()
    setLoading(true);setError('')
    api<Account[]>('/admin/users',{signal:controller.signal}).then(value=>{if(!controller.signal.aborted)setUsers(value)})
      .catch(e=>{if(!controller.signal.aborted)setError(e.message)})
      .finally(()=>{if(!controller.signal.aborted)setLoading(false)})
    return()=>controller.abort()
  },[revision])
  const refresh=()=>setRevision(value=>value+1)
  const matchesSearch=searchMatcher(query)
  const matches=users.filter(user=>matchesSearch(user.display_name+' '+user.username)&&(status==='all'||(status==='active'?user.active!==false:user.active===false)))
  function closeCreate(){if(busy)return;setCreateOpen(false);setUsername('');setDisplayName('');setFormError('')}
  function closeConfirm(){if(busy)return;setConfirm(null);setFormError('')}
  async function createAccount() {
    if(lock.current)return
    lock.current=true;setBusy(true);setFormError('')
    try {
      const result=await post<{user:Account;temporary_password:string}>('/admin/users',{username:username.trim(),display_name:displayName.trim()})
      if(!mounted.current)return
      setCreateOpen(false);setUsername('');setDisplayName('');setSecret({title:'账号已创建',value:result.temporary_password,username:result.user.username});refresh()
    } catch(e){if(mounted.current)setFormError((e as Error).message)} finally {lock.current=false;if(mounted.current)setBusy(false)}
  }
  async function invite() {
    if(lock.current)return
    lock.current=true;setBusy(true)
    try {const result=await post<{code:string}>('/admin/invites');if(!mounted.current)return;setSecret({title:'成员邀请码',value:result.code})}
    catch(e){if(mounted.current)notice((e as Error).message,'error')} finally {lock.current=false;if(mounted.current)setBusy(false)}
  }
  async function applyConfirmed() {
    if(lock.current||!confirm)return
    lock.current=true;setBusy(true);setFormError('')
    try {
      if(confirm.action==='password') {
        const result=await post<{temporary_password:string}>(`/admin/users/${encodeURIComponent(confirm.user.id)}/password`)
        if(!mounted.current)return
        setSecret({title:'密码已重置',value:result.temporary_password,username:confirm.user.username})
      } else {
        await patch(`/admin/users/${encodeURIComponent(confirm.user.id)}`,{active:confirm.user.active===false})
        if(!mounted.current)return
        notice(confirm.user.active===false?'账号已启用':'账号已停用')
      }
      setConfirm(null);refresh()
    } catch(e){if(mounted.current)setFormError((e as Error).message)} finally {lock.current=false;if(mounted.current)setBusy(false)}
  }
  const copySecret=()=>{if(secret)void navigator.clipboard.writeText(secret.value).then(()=>notice('已复制')).catch(()=>notice('复制失败，请手动选中复制','error'))}
  return <div className="accounts-page">
    <div className="page-heading"><div><h1>账号管理</h1><p>管理所属组织的成员、登录权限和生图并行上限。</p></div><div className="button-group"><button className="button" disabled={busy||!currentUser.organization_id} onClick={()=>void invite()}>生成邀请码</button><button className="button primary" disabled={busy||!currentUser.organization_id} onClick={()=>{setCreateOpen(true);setFormError('')}}><Plus size={16}/>创建成员</button></div></div>
    <div className="accounts-toolbar"><label className="accounts-search"><Search size={16}/><input aria-label="搜索账号" placeholder="搜索用户名或姓名" value={query} onChange={e=>setQuery(e.target.value)}/></label><select aria-label="账号状态" value={status} onChange={e=>setStatus(e.target.value)}><option value="all">全部状态</option><option value="active">启用中</option><option value="inactive">已停用</option></select><button className="button" disabled={loading||busy} onClick={refresh}><RefreshCw size={15}/>刷新</button><span className="hint">{matches.length} 个账号</span></div>
    <p className="notice-banner"><Users size={16}/>{currentUser.organization_name||'所有组织'} · 组织内共享贴纸、模板和订单。</p>
    {error&&<div className="error-banner" role="alert">{error}<button className="text-button" onClick={refresh}>重新加载</button></div>}
    {loading&&!users.length?<div className="account-loading" role="status"><Spinner/>正在加载账号</div>:!error&&matches.length?<div className="accounts-table-wrap"><table className="accounts-table"><thead><tr><th>成员</th><th>状态</th><th>组织</th><th>生图并行上限</th><th>公共库编辑</th><th>操作</th></tr></thead><tbody>{matches.map(user=><tr key={user.id}><th scope="row"><strong>{user.display_name}</strong><small>{user.username} · {roleLabel(user.role)}</small></th><td><span className={'account-state '+(user.active===false?'inactive':'active')}>{user.active===false?'已停用':'启用中'}</span></td><td>{user.organization_name||'—'}</td><td><button className="text-button" aria-label="并行上限" title="设置账号生图并行上限" disabled={busy} onClick={()=>setConcurrency(user)}>{user.generation_concurrency??2} 张</button></td><td>{isAdmin(user.role)?'始终允许':<label className="check-line"><input type="checkbox" aria-label={user.display_name+' 公共库编辑权限'} checked={!!user.can_edit_library} disabled={busy} onChange={async e=>{const allowed=e.target.checked;if(lock.current)return;lock.current=true;setBusy(true);setUsers(prev=>prev.map(account=>account.id===user.id?{...account,can_edit_library:allowed}:account));try{await patch(`/admin/users/${encodeURIComponent(user.id)}/library-permission`,{can_edit_library:allowed});refresh();notice(allowed?'已允许编辑公共库':'已撤销公共库编辑权限')}catch(error){setUsers(prev=>prev.map(account=>account.id===user.id?{...account,can_edit_library:!allowed}:account));notice((error as Error).message,'error')}finally{lock.current=false;if(mounted.current)setBusy(false)}}}/>允许编辑</label>}</td><td><div className="accounts-actions">{user.id!==currentUser.id&&user.role!=='superadmin'&&<><button className="text-button" disabled={busy} onClick={()=>{setConfirm({user,action:'password'});setFormError('')}}>重置密码</button><button className="text-button" disabled={busy} onClick={()=>{setConfirm({user,action:'toggle'});setFormError('')}}>{user.active===false?'启用':'停用'}</button><button className="text-button account-delete-button" disabled={busy} onClick={()=>setDeleting(user)}>删除账号</button></>}</div></td></tr>)}</tbody></table></div>:!error&&<Empty title="没有匹配的账号" description="试试其他姓名、用户名或账号状态。"/>}
    {concurrency&&<AccountConcurrencyDialog account={concurrency} onClose={()=>setConcurrency(null)} onSaved={()=>{setConcurrency(null);refresh();notice('账号生图并行上限已保存')}}/>}
    {deleting&&<DeleteAccountDialog account={deleting} onClose={()=>setDeleting(null)} onDeleted={pending=>{setDeleting(null);refresh();notice(pending?'账号已删除，部分文件待清理，请在管理设置中重试清理':'账号及其订单已删除，公共库保留')}}/>}
    {createOpen&&<Modal title="创建成员账号" onClose={closeCreate}><form onSubmit={e=>{e.preventDefault();void createAccount()}}><p className="hint">创建后显示临时密码，成员登录后可修改。</p><label className="field">用户名<input required minLength={3} maxLength={40} pattern="[A-Za-z0-9_.\-]+" title="3 至 40 位英文字母、数字、下划线、点或连字符" autoComplete="off" value={username} onChange={e=>setUsername(e.target.value)} disabled={busy}/></label><label className="field">显示名称<input required maxLength={80} autoComplete="off" value={displayName} onChange={e=>setDisplayName(e.target.value)} disabled={busy}/></label>{formError&&<div className="error-banner" role="alert">{formError}</div>}<div className="modal-footer"><button className="button" type="button" disabled={busy} onClick={closeCreate}>取消</button><button className="button primary" disabled={busy||!username.trim()||!displayName.trim()}>{busy&&<Spinner/>}创建账号</button></div></form></Modal>}
    {confirm&&<Modal title={confirm.action==='password'?'重置成员密码':confirm.user.active===false?'启用成员账号':'停用成员账号'} onClose={closeConfirm}><p className="account-confirm-copy">{confirm.action==='password'?`确认重置「${confirm.user.display_name}」的密码？原密码将失效，成功后显示新的临时密码。`:`确认${confirm.user.active===false?'启用':'停用'}「${confirm.user.display_name}」？${confirm.user.active===false?'该成员可重新登录。':'该成员将无法继续登录使用。'}`}</p>{formError&&<div className="error-banner" role="alert">{formError}</div>}<div className="modal-footer"><button className="button" disabled={busy} onClick={closeConfirm}>取消</button><button className="button primary" disabled={busy} onClick={()=>void applyConfirmed()}>{busy&&<Spinner/>}确认{confirm.action==='password'?'重置':confirm.user.active===false?'启用':'停用'}</button></div></Modal>}
    {secret&&<Modal title={secret.title} onClose={()=>setSecret(null)}>{secret.username?<><p className="hint">用户名：{secret.username}</p><p className="account-confirm-copy">请妥善交给成员。临时密码仅在此处展示，关闭后不会保留。</p></>:<p className="account-confirm-copy">将邀请码交给成员，用于注册独立账号。</p>}<div className="account-secret"><code>{secret.value}</code><button className="icon-button" aria-label={secret.username?'复制临时密码':'复制邀请码'} onClick={copySecret}><Copy size={18}/></button></div><div className="modal-footer"><button className="button primary" onClick={()=>setSecret(null)}>已保存，关闭</button></div></Modal>}
  </div>
}
