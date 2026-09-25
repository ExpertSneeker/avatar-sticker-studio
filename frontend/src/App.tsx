import { CategoryContext, DEFAULT_CATEGORIES, type LibraryCategory } from './lib/categories'
import { lazy, Suspense, useCallback, useEffect, useRef, useState } from 'react'
import { BarChart3, ChartNoAxesCombined, House, Sticker as StickerIcon, LayoutGrid, ClipboardList, UserRound, Settings2, Plus, LogOut, X, CheckCircle2, AlertCircle, Menu, Building2, BookOpen } from 'lucide-react'
import { Auth } from './pages/Auth'
import { Stickers } from './pages/Stickers'
import { Templates } from './pages/Templates'
import { CustomerOrders } from './pages/CustomerOrders'
import { Organizations } from './pages/Organizations'
import { Statistics } from './pages/Statistics'
import { Accounts } from './pages/Accounts'
import { Account, Admin } from './pages/Settings'
import { Brand, NoticeContext, Spinner } from './components/UI'
import { api, expectUser, post } from './lib/api'
import { visiblePolling } from './lib/polling'
import { isAdmin, roleLabel, staffLibrary } from './lib/customer-orders'
import type { Sticker, TemplateSet, User } from './lib/types'

const StaffGuide = lazy(() => import('./pages/StaffGuide'))
const Shops = lazy(() => import('./pages/Shops').then(module => ({ default: module.Shops })))

type Page='stickers'|'workspace'|'templates'|'tasks'|'account'|'admin'|'statistics'|'global-statistics'|'users'|'organizations'|'shops'|'guide'
const navigation=[{id:'workspace',name:'工作台',icon:House},{id:'stickers',name:'贴纸库',icon:StickerIcon},{id:'templates',name:'模板库',icon:LayoutGrid},{id:'tasks',name:'历史订单',icon:ClipboardList},{id:'shops',name:'店铺接入',icon:Building2},{id:'statistics',name:'统计',icon:BarChart3},{id:'guide',name:'使用说明',icon:BookOpen},{id:'account',name:'账号设置',icon:UserRound},{id:'users',name:'账户管理',icon:UserRound},{id:'organizations',name:'组织管理',icon:Building2},{id:'global-statistics',name:'全站统计',icon:ChartNoAxesCombined},{id:'admin',name:'管理设置',icon:Settings2}] as const
export default function App(){
  const [user,setUser]=useState<User|null>(null),[needsSetup,setNeedsSetup]=useState(false),[loading,setLoading]=useState(true),[error,setError]=useState('')
  const [page,setPage]=useState<Page>(()=>new URLSearchParams(window.location.search).has('agiso')?'shops':'workspace'),[templates,setTemplates]=useState<TemplateSet[]>([]),[stickers,setStickers]=useState<Sticker[]>([])
  const [categories,setCategories]=useState<LibraryCategory[]>(DEFAULT_CATEGORIES)
  const [toast,setToast]=useState<{message:string;kind:string}|null>(null),[mobileNav,setMobileNav]=useState(false),[createRequest,setCreateRequest]=useState(0)
  const session=useRef(new AbortController()),identity=useRef<string|null>(null),authChannel=useRef<BroadcastChannel|null>(null)
  const updateUser=useCallback((next:User|null)=>{
    if(identity.current!==next?.id){session.current.abort();session.current=new AbortController();identity.current=next?.id||null;setTemplates([]);setStickers([]);setCategories(DEFAULT_CATEGORIES)}
    expectUser(next?.id||null);setUser(next);if(next?.role==='superadmin'&&!next.organization_id)setPage('organizations')
  },[])
  useEffect(()=>{
    const expired=()=>{updateUser(null);setPage('workspace');setError('')}
    window.addEventListener('studio-session-expired',expired)
    const channel=typeof BroadcastChannel!=='undefined'?new BroadcastChannel('sticker-session'):null
    authChannel.current=channel
    if(channel)channel.onmessage=event=>{if(identity.current&&event.data.userId!==identity.current)expired()}
    return()=>{window.removeEventListener('studio-session-expired',expired);channel?.close()}
  },[updateUser])
  const notice=useCallback((message:string,kind='success')=>setToast({message,kind}),[])
  useEffect(()=>{if(!toast)return;const timer=setTimeout(()=>setToast(null),6500);return()=>clearTimeout(timer)},[toast])
  const auth=()=>api<{needs_setup:boolean;user:User|null}>('/auth/status').then(status=>{updateUser(status.user);setNeedsSetup(status.needs_setup);setError('')}).catch(e=>setError(e.message)).finally(()=>setLoading(false))
  useEffect(()=>{void auth()},[])
  const userId=user?.id,hasOrganization=!!user?.organization_id
  const refresh=useCallback(async()=>{
    if(!userId)return
    const signal=session.current.signal
    if(!hasOrganization){try{const current=await api<User>('/auth/me',{signal});if(!signal.aborted)setUser(current)}catch(e){if(!signal.aborted)setError((e as Error).message)}return}
    try{const [sets,currentUser,assets,cats]=await Promise.all([api<TemplateSet[]>('/templates',{signal}),api<User>('/auth/me',{signal}),api<Sticker[]>('/stickers',{signal}),api<LibraryCategory[]>('/library/categories',{signal})]);if(signal.aborted||identity.current!==userId)return;setTemplates(sets);setStickers(assets);setCategories(cats);setUser(previous=>JSON.stringify(previous)===JSON.stringify(currentUser)?previous:currentUser);setError('')}catch(e){if(!signal.aborted)setError((e as Error).message)}
  },[userId,hasOrganization])
  useEffect(()=>{void refresh();if(!userId)return;return visiblePolling(()=>void refresh(),5000)},[refresh,userId])
  function changePage(next:Page){setPage(next);setMobileNav(false)}
  if(loading)return <div className="startup"><Brand/><Spinner/></div>
  if(!user)return <NoticeContext.Provider value={notice}>{error?<div className="startup"><Brand/><div className="error-banner">{error}</div><button className="button" onClick={()=>void auth()}>重新连接</button></div>:<Auth needsSetup={needsSetup} onLogin={next=>{updateUser(next);authChannel.current?.postMessage({userId:next.id})}}/>}</NoticeContext.Provider>
  const admin=isAdmin(user.role),global=user.role==='superadmin'
  const visible=navigation.filter(item=>hasOrganization||!['workspace','stickers','templates','tasks','statistics','shops'].includes(item.id)).filter(item=>['admin','global-statistics','organizations'].includes(item.id)?global:item.id==='users'?admin:true)
  return <CategoryContext.Provider value={{categories,refresh:()=>void refresh()}}><NoticeContext.Provider value={notice}><div className="app-shell"><aside className={'sidebar '+(mobileNav?'open':'')}><Brand/><nav aria-label="主导航">{visible.map(item=><button key={item.id} className={(page===item.id?'active ':'')+(item.id==='account'?'nav-bottom':'')} onClick={()=>changePage(item.id)}><item.icon size={19} strokeWidth={1.65}/>{item.name}</button>)}</nav><div className="sidebar-profile"><span className="profile-initial">{user.display_name.slice(0,1)}</span><div><strong>{user.display_name}</strong><small>{user.organization_name?user.organization_name+' · ':''}{roleLabel(user.role)}</small></div><button className="icon-button" title="退出登录" onClick={async()=>{try{await post('/auth/logout');updateUser(null);authChannel.current?.postMessage({userId:null});setPage('workspace')}catch(e){notice((e as Error).message,'error')}}}><LogOut size={16}/></button></div></aside>{mobileNav&&<button className="nav-shade" onClick={()=>setMobileNav(false)} aria-label="关闭导航"/>}<div className="main-shell"><header className="topbar"><div><button className="icon-button mobile-menu" onClick={()=>setMobileNav(!mobileNav)} aria-label="展开导航"><Menu size={22}/></button><h2>{visible.find(item=>item.id===page)?.name}</h2></div><div>{hasOrganization&&<button className="button primary" onClick={()=>{changePage('workspace');setCreateRequest(value=>value+1)}}><Plus size={17}/>新建订单</button>}</div></header><main className="content">{error&&<div className="error-banner">{error}<button className="text-button" onClick={()=>void refresh()}>重试</button></div>}{page==='workspace'&&<CustomerOrders key={user.id} user={user} library={staffLibrary(stickers,templates)} createRequest={createRequest} onCreateHandled={()=>setCreateRequest(0)}/>} {page==='templates'&&<Templates templates={templates} stickers={stickers} canEdit={admin||!!user.can_edit_library} admin={admin} onRefresh={()=>void refresh()}/>} {page==='stickers'&&<Stickers stickers={stickers} canEdit={admin||!!user.can_edit_library} onRefresh={()=>void refresh()}/>} {page==='tasks'&&<CustomerOrders key={user.id} user={user} library={staffLibrary(stickers,templates)} scope="history"/>} {page==='shops'&&hasOrganization&&<Suspense fallback={<Spinner/>}><Shops key={user.id}/></Suspense>} {page==='guide'&&<Suspense fallback={<Spinner/>}><StaffGuide key={user.id}/></Suspense>} {page==='statistics'&&<Statistics/>} {page==='global-statistics'&&global&&<Statistics global/>} {page==='account'&&<Account user={user} onUpdate={updateUser}/>} {page==='admin'&&global&&<Admin/>}{page==='users'&&admin&&<Accounts currentUser={user}/>} {page==='organizations'&&global&&<Organizations/>}</main><footer className="app-footer"><span>头像贴纸工作台</span><span>客户选图 · 组织协作 · 打印交付</span></footer></div></div>{toast&&<div className={'toast '+toast.kind} role={toast.kind==='error'?'alert':'status'}>{toast.kind==='error'?<AlertCircle size={18}/>:<CheckCircle2 size={18}/>}<span>{toast.message}</span><button onClick={()=>setToast(null)} aria-label="关闭提示"><X size={16}/></button></div>}</NoticeContext.Provider></CategoryContext.Provider>
}
