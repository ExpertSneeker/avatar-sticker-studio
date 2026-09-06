import { useCallback, useEffect, useRef, useState } from 'react'
import { House, LayoutGrid, ClipboardList, ScanSearch, UserRound, Settings2, FolderOpen, Plus, LogOut, X, CheckCircle2, AlertCircle, Menu } from 'lucide-react'
import { Auth } from './pages/Auth'
import { Workspace } from './pages/Workspace'
import { Templates } from './pages/Templates'
import { Orders } from './pages/Orders'
import type { DeviceState } from './pages/Orders'
import { Account, Admin } from './pages/Settings'
import { Brand, Modal, NoticeContext, Spinner } from './components/UI'
import { api, expectUser, post } from './lib/api'
import { bindDestination, directoryPermission, directorySupported, openOrderDirectory, orderDirectory, pickDirectory, savedRecord, storedDirectory, syncOrder } from './lib/device'
import type { Order, TemplateSet, User } from './lib/types'

type Page='workspace'|'templates'|'tasks'|'review'|'account'|'admin'
const navigation=[{id:'workspace',name:'工作台',icon:House},{id:'templates',name:'模板库',icon:LayoutGrid},{id:'tasks',name:'任务中心',icon:ClipboardList},{id:'review',name:'结果检查',icon:ScanSearch},{id:'account',name:'账号设置',icon:UserRound},{id:'admin',name:'管理设置',icon:Settings2}] as const
export default function App() {
  const [user,setUser]=useState<User|null>(null),[needsSetup,setNeedsSetup]=useState(false),[loading,setLoading]=useState(true),[error,setError]=useState('')
  const [page,setPage]=useState<Page>('workspace'),[templates,setTemplates]=useState<TemplateSet[]>([]),[orders,setOrders]=useState<Order[]>([])
  const [directory,setDirectory]=useState<FileSystemDirectoryHandle|null>(null),[device,setDevice]=useState<Record<string,DeviceState>>({})
  const [toast,setToast]=useState<{message:string;kind:string}|null>(null),[mobileNav,setMobileNav]=useState(false)
  const [repair,setRepair]=useState<string|null>(null)
  const addRef=useRef<(()=>void)|null>(null),attempted=useRef<Record<string,number>>({}),syncing=useRef(false),activeSaves=useRef(new Set<string>()),pickingDownload=useRef(false)
  const session=useRef(new AbortController()),identity=useRef<string|null>(null),authChannel=useRef<BroadcastChannel|null>(null)
  const updateUser=useCallback((next:User|null)=>{
    if(identity.current!==next?.id){session.current.abort();session.current=new AbortController();identity.current=next?.id||null;setOrders([]);setTemplates([]);setDevice({});setRepair(null)}
    expectUser(next?.id||null);setUser(next)
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
  useEffect(()=>{if(!toast)return;const t=setTimeout(()=>setToast(null),6500);return()=>clearTimeout(t)},[toast])
  const auth=()=>api<{needs_setup:boolean;user:User|null}>('/auth/status').then(s=>{updateUser(s.user);setNeedsSetup(s.needs_setup);setError('')}).catch(e=>setError(e.message)).finally(()=>setLoading(false))
  useEffect(()=>{void auth()},[])
  const refresh=useCallback(async()=>{
    if(!user)return
    const signal=session.current.signal
    try{const [sets,tasks]=await Promise.all([api<TemplateSet[]>('/templates',{signal}),api<Order[]>('/orders',{signal})]);if(signal.aborted||identity.current!==user.id)return;setTemplates(sets);setOrders(tasks);setError('')}catch(e){if(!signal.aborted)setError((e as Error).message)}
  },[user])
  useEffect(()=>{void refresh();if(!user)return;const timer=setInterval(refresh,4000);return()=>clearInterval(timer)},[refresh,user])
  useEffect(()=>{
    setDirectory(null);setDevice({});attempted.current={}
    if(!user)return
    let active=true
    storedDirectory(user.id).then(handle=>{if(active&&handle)setDirectory(handle)}).catch(()=>{})
    return()=>{active=false}
  },[user?.id])
  const chooseDirectory=useCallback(async()=>{
    if(!user)return
    if(!directorySupported()){notice('当前浏览器请使用订单中的 ZIP 下载','error');return}
    try{const handle=await pickDirectory(user.id);setDirectory(handle);attempted.current={};notice('保存目录已选择：'+handle.name)}catch(e){if((e as Error).name!=='AbortError')notice((e as Error).message,'error')}
  },[notice,user])
  const save=useCallback(async(id:string,repairModified=false,automatic=false,forceDownload=false,targetRoot?:FileSystemDirectoryHandle)=>{
    if(!user||activeSaves.current.has(id))return
    const order=orders.find(o=>o.id===id)
    if(!order)return
    const signal=session.current.signal
    activeSaves.current.add(id)
    try {
      let handle=targetRoot||(repairModified?(await savedRecord(user.id,id))?.root:null)||await orderDirectory(user.id,order,directory)
      signal.throwIfAborted()
      if(!handle){
        if(automatic)throw new Error('待选择此订单的保存目录')
        if(!directorySupported())throw new Error('请使用桌面 Chrome 或 Edge，或在详情中下载 ZIP')
        handle=await window.showDirectoryPicker({mode:'readwrite'})
        signal.throwIfAborted()
        handle=await bindDestination(user.id,order.client_token||id,handle)
      }
      if(!await directoryPermission(handle,!automatic))throw new Error('待授权此订单的保存目录，请点击重新下载授权')
      signal.throwIfAborted()
      setDevice(prev=>({...prev,[id]:{message:'正在核对本地文件',busy:true}}))
      const record=await syncOrder(user.id,id,handle,message=>{if(!signal.aborted)setDevice(prev=>({...prev,[id]:{message,busy:true}}))},{signal,repairModified,automatic,forceDownload})
      if(!signal.aborted)setDevice(prev=>({...prev,[id]:{message:record.complete?'已保存到本机':'已保存当前成品，等待其余图片',version:record.version,saved:!!(record.downloadedOnce||record.complete)}}))
    }catch(e){if(!signal.aborted&&(e as Error).name!=='AbortError')setDevice(prev=>({...prev,[id]:{message:(e as Error).message,error:true}}))}
    finally{activeSaves.current.delete(id)}
  },[directory,orders,user])
  async function redownload(ids:string[]) {
    if(!user||pickingDownload.current||!ids.length)return
    if(!directorySupported()){notice('请使用桌面 Chrome 或 Edge 选择下载目录，或在详情中下载 ZIP','error');return}
    const signal=session.current.signal
    pickingDownload.current=true
    try {
      const first=orders.find(order=>order.id===ids[0])
      if(!first)return
      const previous=await savedRecord(user.id,first.id)
      const startIn=previous?.root||await orderDirectory(user.id,first,directory)||directory||'downloads'
      signal.throwIfAborted()
      const target=await window.showDirectoryPicker({mode:'readwrite',startIn})
      signal.throwIfAborted()
      for(const id of ids){signal.throwIfAborted();await save(id,false,false,true,target)}
    }catch(error){if(!signal.aborted&&(error as Error).name!=='AbortError')notice((error as Error).message,'error')}
    finally{pickingDownload.current=false}
  }
  useEffect(()=>{
    if(!user||syncing.current)return
    const signal=session.current.signal
    const candidates=orders.filter(o=>!activeSaves.current.has(o.id)&&attempted.current[o.id]!==o.artifact_version)
    if(!candidates.length)return
    let cancelled=false
    syncing.current=true
    async function run(){
      try{
        for(const order of candidates){
          if(cancelled||signal.aborted)break
          const old=await savedRecord(user!.id,order.id)
          if(cancelled||signal.aborted)break
          attempted.current[order.id]=order.artifact_version
          if(old?.downloadedOnce||old?.complete){
            setDevice(prev=>({...prev,[order.id]:{message:old.version===order.artifact_version?'已保存到本机':'已下载过 · 有更新可重新下载',version:old.version,saved:true}}))
          }else if(order.download_ready){await save(order.id,false,true)}
          else setDevice(prev=>({...prev,[order.id]:{message:'等待全部成品后自动下载'}}))
        }
      }finally{syncing.current=false}
    }
    void run()
    return()=>{cancelled=true}
  },[orders,directory,user,save])
  const openDirectory=async(id:string)=>{
    try{await openOrderDirectory(user!.id,id)}catch(e){if((e as Error).name!=='AbortError')notice((e as Error).message,'error')}
  }
  function changePage(next:Page){setPage(next);setMobileNav(false)}
  if(loading)return <div className="startup"><Brand/><Spinner/></div>
  if(!user)return <NoticeContext.Provider value={notice}>{error?<div className="startup"><Brand/><div className="error-banner">{error}</div><button className="button" onClick={()=>void auth()}>重新连接</button></div>:<Auth needsSetup={needsSetup} onLogin={next=>{updateUser(next);authChannel.current?.postMessage({userId:next.id})}}/>}</NoticeContext.Provider>
  return <NoticeContext.Provider value={notice}><div className="app-shell"><aside className={'sidebar '+(mobileNav?'open':'')}><Brand/><nav aria-label="主导航">{navigation.filter(n=>n.id!=='admin'||user.role==='admin').map(item=><button key={item.id} className={(page===item.id?'active ':'')+(item.id==='account'?'nav-bottom':'')} onClick={()=>changePage(item.id)}><item.icon size={19} strokeWidth={1.65}/>{item.name}{item.id==='tasks'&&orders.some(o=>o.failed||o.unknown)&&<i className="notification-dot"/>}</button>)}</nav><div className="sidebar-profile"><span className="profile-initial">{user.display_name.slice(0,1)}</span><div><strong>{user.display_name}</strong><small>{user.role==='admin'?'管理员':'制作成员'}</small></div><button className="icon-button" title="退出登录" onClick={async()=>{try{await post('/auth/logout');updateUser(null);authChannel.current?.postMessage({userId:null});setPage('workspace')}catch(e){notice((e as Error).message,'error')}}}><LogOut size={16}/></button></div></aside>{mobileNav&&<button className="nav-shade" onClick={()=>setMobileNav(false)} aria-label="关闭导航"/>}<div className="main-shell"><header className="topbar"><div><button className="icon-button mobile-menu" onClick={()=>setMobileNav(!mobileNav)} aria-label="展开导航"><Menu size={22}/></button><h2>{navigation.find(n=>n.id===page)?.name}</h2></div><div><button className="button directory-button" onClick={chooseDirectory}><FolderOpen size={17}/><span>{directory?directory.name:'选择保存目录'}</span></button><button className="button primary" onClick={()=>{changePage('workspace');if(page==='workspace')addRef.current?.()}}><Plus size={17}/>新建订单</button></div></header><main className="content">{error&&<div className="error-banner">{error}<button className="text-button" onClick={()=>void refresh()}>重试</button></div>}{page==='workspace'&&<Workspace key={user.id} user={user} templates={templates} directory={directory} onCreated={()=>void refresh()} addRef={addRef}/>} {page==='templates'&&<Templates templates={templates} admin={user.role==='admin'} onRefresh={()=>void refresh()}/>} {(page==='tasks'||page==='review')&&<Orders key={page} orders={orders} review={page==='review'} onRefresh={()=>void refresh()} onSync={async(id,repairRequested)=>{if(repairRequested)setRepair(id);else await redownload([id])}} onRedownload={redownload} onOpenDirectory={openDirectory} device={device}/>} {page==='account'&&<Account user={user} onUpdate={updateUser}/>} {page==='admin'&&user.role==='admin'&&<Admin/>}</main><footer className="app-footer"><span>头像贴纸工作台</span><span>1K 生图 · 透明 PNG · 独立订单</span></footer></div></div>{repair&&<Modal title="修复已保存文件" onClose={()=>setRepair(null)}><p>将使用服务器成品覆盖此订单中被修改或损坏的已管理文件。你手动修改过的同一文件也会被替换。</p><p className="hint">未由此订单保存的同名文件仍会保留，请为这些冲突选择其他目录。</p><div className="modal-footer"><button className="button" onClick={()=>setRepair(null)}>取消</button><button className="button primary" onClick={()=>{const id=repair;setRepair(null);void save(id,true)}}>确认修复</button></div></Modal>}{toast&&<div className={'toast '+toast.kind} role={toast.kind==='error'?'alert':'status'}>{toast.kind==='error'?<AlertCircle size={18}/>:<CheckCircle2 size={18}/>}<span>{toast.message}</span><button onClick={()=>setToast(null)} aria-label="关闭提示"><X size={16}/></button></div>}</NoticeContext.Provider>
}
