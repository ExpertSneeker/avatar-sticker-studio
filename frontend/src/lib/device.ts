import { api, sha256 } from './api'
import { readLocal, readOrCreateLocal, writeLocal } from './db'
import { planSync, safeFilename } from './sync'
import type { Manifest, Order } from './types'

type WriteIntent={sha256:string;baseline:string|null}
interface SavedLocation {root:FileSystemDirectoryHandle;name:string;hashes:Record<string,string>;intents?:Record<string,WriteIntent>}
export interface SavedRecord {locations?:SavedLocation[];version:number;complete:boolean;downloadedOnce?:boolean;hashes:Record<string,string>;root:FileSystemDirectoryHandle;name:string;intents?:Record<string,WriteIntent>}
const active=new Set<string>()
export const directorySupported=()=> 'showDirectoryPicker' in window
export async function pickDirectory(userId:string) {
  const handle=await window.showDirectoryPicker({mode:'readwrite',id:'avatar-stickers'})
  await writeLocal('directory:'+userId,handle)
  return handle
}
export const storedDirectory=(userId:string)=>readLocal<FileSystemDirectoryHandle>('directory:'+userId)
export const savedRecord=(userId:string,orderId:string)=>readLocal<SavedRecord>('saved:'+userId+':'+orderId)
export const bindDestination=(userId:string,token:string,root:FileSystemDirectoryHandle)=>readOrCreateLocal('destination:'+userId+':'+token,root)
export async function orderDirectory(userId:string,order:Order,fallback:FileSystemDirectoryHandle|null) {
  const bound=await readLocal<FileSystemDirectoryHandle>('destination:'+userId+':'+(order.client_token||order.id))
  if(bound)return bound
  const saved=await savedRecord(userId,order.id)
  // A submitted destination must never silently follow a new global directory.
  return saved?.root||(!order.client_token?fallback:null)
}
export async function openOrderDirectory(userId:string,orderId:string) {
  const saved=await savedRecord(userId,orderId)
  if(!saved)throw new Error('此订单尚未保存到本机')
  if(!directorySupported())throw new Error('请使用桌面 Chrome 或 Edge 打开本机目录')
  if(!await directoryPermission(saved.root,true))throw new Error('请先授权此订单的保存目录')
  const child=await saved.root.getDirectoryHandle(saved.name)
  // Browsers expose a native directory dialog, not a Finder/Explorer launch API.
  await window.showDirectoryPicker({mode:'read',startIn:child})
}
export async function directoryPermission(handle:FileSystemDirectoryHandle,request=false) {
  return (request?await handle.requestPermission({mode:'readwrite'}):await handle.queryPermission({mode:'readwrite'}))==='granted'
}
export async function syncOrder(userId:string,orderId:string,root:FileSystemDirectoryHandle,onProgress:(message:string)=>void,options:{signal?:AbortSignal;repairModified?:boolean;automatic?:boolean;forceDownload?:boolean}={}) {
  const key=userId+':'+orderId
  if(active.has(key)) throw new Error('此订单正在保存')
  active.add(key)
  const {signal,repairModified}=options
  try {
    signal?.throwIfAborted()
    if (!await directoryPermission(root)) throw new Error('保存目录需要重新授权，请点击“选择保存目录”')
    const manifest=await api<Manifest>('/orders/'+orderId+'/manifest',{signal})
    if(!safeFilename(manifest.name)) throw new Error('订单名称不能用作本地文件夹')
    if(!manifest.files.length) throw new Error('尚无可保存的成品')
    const run=async()=>{
    signal?.throwIfAborted()
    const previous=await savedRecord(userId,orderId)
    if(options.automatic&&(previous?.downloadedOnce||previous?.complete))return previous
    if(options.automatic&&!manifest.complete)throw new Error('等待全部成品完成后再自动下载')
    const downloadedOnce=!!(previous?.downloadedOnce||previous?.complete)
    // Keep ownership per output location so explicitly returning to an earlier folder stays safe.
    const locations:SavedLocation[]=[]
    let matching:SavedLocation|undefined
    const priorLocations=previous?[{root:previous.root,name:previous.name,hashes:previous.hashes,intents:previous.intents},...(previous.locations||[])]:[]
    for(const location of priorLocations){
      if(location.name===manifest.name&&await root.isSameEntry(location.root).catch(()=>false))matching??=location
      else locations.push(location)
    }
    const owned:Record<string,string>=Object.assign(Object.create(null),matching?.hashes)
    const intents:Record<string,WriteIntent>=Object.assign(Object.create(null),matching?.intents)
    const directory=await root.getDirectoryHandle(manifest.name,{create:true})
    const local:Record<string,string>=Object.create(null)
    for await(const [name,entry] of directory.entries()) {
      signal?.throwIfAborted()
      if(entry.kind==='file') local[name]=await sha256(await (entry as FileSystemFileHandle).getFile())
    }
    const emptyHash=await sha256(new Blob())
    for(const [path,intent] of Object.entries(intents)) {
      if(local[path]===intent.sha256 || intent.baseline===null&&local[path]===emptyHash) owned[path]=local[path]
    }
    const plan=planSync(manifest.files,local,owned,repairModified)
    if(plan.conflicts.length) throw new Error('发现同名或被修改的文件，请另选保存目录：'+plan.conflicts.join('、'))
    const downloads=options.forceDownload?manifest.files.map(file=>file.path):plan.download
    const persist=()=>writeLocal('saved:'+key,{version:-1,complete:false,downloadedOnce,locations,hashes:owned,intents,root,name:manifest.name})
    const actualHash=async(path:string)=>{
      try{return await sha256(await (await directory.getFileHandle(path)).getFile())}
      catch(error){if((error as Error).name==='NotFoundError')return undefined;throw error}
    }
    let progress=0
    for(const path of downloads) {
      signal?.throwIfAborted()
      const file=manifest.files.find(f=>f.path===path)!
      onProgress('正在保存 '+(++progress)+' / '+downloads.length)
      const response=await fetch(file.url,{credentials:'same-origin',signal})
      if(!response.ok) throw new Error('下载失败：'+path)
      const blob=await response.blob()
      if(blob.size!==file.size || await sha256(blob)!==file.sha256) throw new Error('文件校验失败：'+path)
      const current=await api<Manifest>('/orders/'+orderId+'/manifest',{signal})
      if(current.version!==manifest.version) throw new Error('结果已更新，请重新保存最新版本')
      signal?.throwIfAborted()
      // A download can take minutes; do not overwrite files changed since the initial scan.
      if(await actualHash(path)!==local[path]) throw new Error('保存期间本地文件发生变化，请重新核对：'+path)
      intents[path]={sha256:file.sha256,baseline:local[path]??null}
      await persist()
      signal?.throwIfAborted()
      if(await actualHash(path)!==local[path]) throw new Error('保存期间本地文件发生变化，请重新核对：'+path)
      const handle=await directory.getFileHandle(path,{create:true})
      const writable=await handle.createWritable()
      try {signal?.throwIfAborted();await writable.write(blob);signal?.throwIfAborted();await writable.close()} catch(error){await writable.abort().catch(()=>{});throw error}
      if(await sha256(await handle.getFile())!==file.sha256) throw new Error('写入后文件校验失败：'+path)
      owned[path]=file.sha256
      local[path]=file.sha256
      delete intents[path]
      // Persist every completed write so an interrupted sync can resume safely.
      await persist()
    }
    const latest=await api<Manifest>('/orders/'+orderId+'/manifest',{signal})
    if(latest.version!==manifest.version) throw new Error('结果已更新，请重新核对文件')
    for(const file of manifest.files) {
      signal?.throwIfAborted()
      if(await actualHash(file.path)!==file.sha256)throw new Error('本地文件校验不一致，请重新保存：'+file.path)
    }
    for(const path of plan.remove) {
      signal?.throwIfAborted()
      const handle=await directory.getFileHandle(path)
      if(await sha256(await handle.getFile())===owned[path]) await directory.removeEntry(path)
    }
    const record:SavedRecord={version:manifest.version,complete:manifest.complete,locations,downloadedOnce:downloadedOnce||manifest.complete,hashes:Object.fromEntries(manifest.files.map(f=>[f.path,f.sha256])),root,name:manifest.name}
    await writeLocal('saved:'+key,record)
    onProgress(manifest.complete?'已保存到本机':'已保存当前成品，等待其余图片')
    return record
    }
    // Web Locks serialize saves across tabs and accounts sharing an output folder.
    return typeof navigator!=='undefined'&&navigator.locks
      ? await navigator.locks.request('sticker-order:'+key,{signal},()=>navigator.locks.request('sticker-output:'+root.name+':'+manifest.name.normalize('NFC').toLowerCase(),{signal},run))
      : await run()
  } finally {active.delete(key)}
}
