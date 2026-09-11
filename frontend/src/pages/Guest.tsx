import { useEffect, useState } from 'react'
import { LogOut } from 'lucide-react'
import { Brand, Spinner } from '../components/UI'
import { CustomerWorkbench } from '../components/CustomerWorkbench'
import { guestApi, guestPost } from '../lib/customer-orders'
import type { CustomerLibrary, GuestOrder } from '../lib/customer-orders'
import './CustomerOrders.css'

// The guest entry never imports the staff shell, local database or delivery helpers.
export default function Guest(){
  const [order,setOrder]=useState<GuestOrder|null>(null),[library,setLibrary]=useState<CustomerLibrary>({stickers:[],templates:[]})
  const [number,setNumber]=useState(''),[loading,setLoading]=useState(true),[busy,setBusy]=useState(false),[error,setError]=useState('')
  async function load(){
    const current=await guestApi<GuestOrder>('/order')
    const catalog=current.state==='draft'||current.state==='review'?await guestApi<CustomerLibrary>('/library'):{stickers:[],templates:[]}
    setLibrary(catalog);setOrder(current)
  }
  useEffect(()=>{
    let active=true
    const expired=()=>{setOrder(null);setLibrary({stickers:[],templates:[]})}
    window.addEventListener('guest-session-expired',expired)
    void load().catch(()=>{}).finally(()=>{if(active)setLoading(false)})
    return()=>{active=false;window.removeEventListener('guest-session-expired',expired)}
  },[])
  useEffect(()=>{
    if(!order||!['draft','review'].includes(order.state)){setLibrary({stickers:[],templates:[]});return}
    const controller=new AbortController()
    void guestApi<CustomerLibrary>('/library',{signal:controller.signal}).then(next=>{if(!controller.signal.aborted){setLibrary(next);setError('')}}).catch(e=>{if(!controller.signal.aborted)setError(e.message)})
    return()=>controller.abort()
  },[order?.id,order?.version,order?.state])
  async function login(event:React.FormEvent){
    event.preventDefault();if(busy)return;setBusy(true);setError('')
    try{await guestPost('/login',{order_number:number.trim()});await load();setNumber('')}
    catch(e){setError((e as Error).message)}finally{setBusy(false)}
  }
  return <div className="guest-shell"><header className="guest-header"><Brand/><span>客户选图</span>{order&&<button className="button" disabled={busy} onClick={async()=>{setBusy(true);try{await guestPost('/logout');setOrder(null);setLibrary({stickers:[],templates:[]});setError('')}catch(e){setError((e as Error).message)}finally{setBusy(false)}}}><LogOut size={16}/>退出订单</button>}</header><main className="guest-content">{order&&error&&<div className="error-banner" role="alert">{error}</div>}{loading?<div className="startup"><Spinner/></div>:order?<CustomerWorkbench key={order.id} initial={order} mode="guest" library={library} onChange={setOrder}/>:<form className="guest-login settings-section" onSubmit={login}><h1>查看你的头像贴纸</h1><p>输入工作人员提供的订单号，上传头像、选择贴纸并确认成品。</p><label className="field">订单号<input required autoComplete="off" autoCapitalize="none" spellCheck={false} value={number} onChange={e=>setNumber(e.target.value)} maxLength={120}/></label>{error&&<div className="error-banner" role="alert">{error}</div>}<button className="button primary" disabled={busy||!number.trim()}>{busy&&<Spinner/>}进入订单</button></form>}</main><footer className="guest-footer">头像贴纸 · 客户预览</footer></div>
}
