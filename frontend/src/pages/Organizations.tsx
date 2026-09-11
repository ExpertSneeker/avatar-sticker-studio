import { useEffect, useRef, useState } from 'react'
import { Copy, Plus, RefreshCw } from 'lucide-react'
import { api, patch, post } from '../lib/api'
import { Empty, Modal, Spinner, useNotice } from '../components/UI'
import type { User } from '../lib/types'
import './Accounts.css'
import './CustomerOrders.css'
interface Organization {id:string;name:string;active:boolean}
export function Organizations(){
  const [organizations,setOrganizations]=useState<Organization[]>([]),[loading,setLoading]=useState(true),[error,setError]=useState(''),[busy,setBusy]=useState(false)
  const [create,setCreate]=useState(false),[editing,setEditing]=useState<Organization|null>(null),[toggle,setToggle]=useState<Organization|null>(null)
  const [name,setName]=useState(''),[username,setUsername]=useState(''),[displayName,setDisplayName]=useState('')
  const [secret,setSecret]=useState<{organization:Organization;admin:User;temporary_password:string}|null>(null),notice=useNotice(),lock=useRef(false)
  async function load(){try{setOrganizations(await api<Organization[]>('/admin/organizations'));setError('')}catch(e){setError((e as Error).message)}finally{setLoading(false)}}
  useEffect(()=>{void load()},[])
  async function save(e:React.FormEvent){
    e.preventDefault();if(lock.current)return;lock.current=true;setBusy(true);setError('')
    try{if(editing){await patch('/admin/organizations/'+encodeURIComponent(editing.id),{name:name.trim()});setEditing(null);notice('组织名称已更新')}else{setSecret(await post('/admin/organizations',{name:name.trim(),admin_username:username.trim(),admin_display_name:displayName.trim()}));setCreate(false)}await load()}
    catch(e){setError((e as Error).message)}finally{lock.current=false;setBusy(false)}
  }
  async function changeActive(){
    if(lock.current||!toggle)return;lock.current=true;setBusy(true);setError('')
    try{await patch('/admin/organizations/'+encodeURIComponent(toggle.id),{active:!toggle.active});setToggle(null);await load();notice('组织状态已更新')}
    catch(e){setError((e as Error).message)}finally{lock.current=false;setBusy(false)}
  }
  return <div className="accounts-page"><div className="page-heading"><div><h1>组织管理</h1><p>每个组织拥有独立成员、素材库和客户订单。</p></div><button className="button primary" onClick={()=>{setName('');setUsername('');setDisplayName('');setError('');setCreate(true)}}><Plus size={16}/>创建组织</button></div><div className="accounts-toolbar"><span className="hint">{organizations.length} 个组织</span><button className="button" disabled={busy} onClick={()=>void load()}><RefreshCw size={16}/>刷新</button></div>{error&&<div className="error-banner" role="alert">{error}</div>}{loading?<Spinner/>:organizations.length?<div className="accounts-table-wrap"><table className="accounts-table"><thead><tr><th>组织名称</th><th>状态</th><th>操作</th></tr></thead><tbody>{organizations.map(organization=><tr key={organization.id}><th scope="row">{organization.name}</th><td><span className={'account-state '+(organization.active?'active':'inactive')}>{organization.active?'启用中':'已停用'}</span></td><td><div className="accounts-actions"><button className="text-button" disabled={busy} onClick={()=>{setEditing(organization);setName(organization.name);setError('')}}>修改名称</button><button className="text-button" disabled={busy} onClick={()=>setToggle(organization)}>{organization.active?'停用组织':'启用组织'}</button></div></td></tr>)}</tbody></table></div>:<Empty title="还没有组织" description="创建组织时会同时生成该组织的管理员账号。"/>}
    {(create||editing)&&<Modal title={editing?'修改组织名称':'创建组织'} onClose={()=>{if(!busy){setCreate(false);setEditing(null)}}}><form onSubmit={e=>void save(e)}><label className="field">组织名称<input required maxLength={120} value={name} onChange={e=>setName(e.target.value)}/></label>{!editing&&<><label className="field">管理员账号<input required minLength={3} maxLength={40} pattern="[A-Za-z0-9_.\-]+" autoComplete="off" value={username} onChange={e=>setUsername(e.target.value)}/></label><label className="field">管理员显示名称<input required maxLength={80} value={displayName} onChange={e=>setDisplayName(e.target.value)}/></label><p className="hint">创建后将显示一次临时密码，请妥善交给组织管理员。</p></>}{error&&<div className="error-banner" role="alert">{error}</div>}<div className="modal-footer"><button className="button" type="button" disabled={busy} onClick={()=>{setCreate(false);setEditing(null)}}>取消</button><button className="button primary" disabled={busy}>{busy&&<Spinner/>}{editing?'保存名称':'创建组织和管理员'}</button></div></form></Modal>}
    {toggle&&<Modal title={toggle.active?'停用组织':'启用组织'} onClose={()=>{if(!busy)setToggle(null)}}><p>确认{toggle.active?'停用':'启用'}「{toggle.name}」？{toggle.active?'停用后该组织成员与客户将无法继续访问。':'启用后组织成员与客户可恢复访问。'}</p>{error&&<div className="error-banner" role="alert">{error}</div>}<div className="modal-footer"><button className="button" disabled={busy} onClick={()=>setToggle(null)}>返回</button><button className="button primary" disabled={busy} onClick={()=>void changeActive()}>{busy&&<Spinner/>}确认{toggle.active?'停用':'启用'}</button></div></Modal>}
    {secret&&<Modal title="组织已创建" onClose={()=>setSecret(null)}><p>组织：{secret.organization.name}</p><p>管理员账号：{secret.admin.username}</p><p className="hint">临时密码仅在此处展示，关闭后不会保留。</p><div className="account-secret"><code>{secret.temporary_password}</code><button className="icon-button" aria-label="复制管理员临时密码" onClick={()=>void navigator.clipboard.writeText(secret.temporary_password).then(()=>notice('已复制')).catch(()=>notice('请手动选中复制','error'))}><Copy size={18}/></button></div><div className="modal-footer"><button className="button primary" onClick={()=>setSecret(null)}>已保存，关闭</button></div></Modal>}
  </div>
}
