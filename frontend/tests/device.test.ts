import { beforeEach, describe, expect, it, vi } from 'vitest'
import { sha256 } from '../src/lib/api'
import { syncOrder } from '../src/lib/device'
import type { Manifest } from '../src/lib/types'

const localStore=vi.hoisted(()=>({values:new Map<string,any>(),writes:0,failAt:0}))
vi.mock('../src/lib/db',()=>({
  readLocal:async(key:string)=>localStore.values.get(key),
  writeLocal:async(key:string,value:any)=>{
    localStore.writes++
    if(localStore.writes===localStore.failAt)throw new Error('storage quota')
    localStore.values.set(key,{...value,hashes:{...value.hashes},intents:{...value.intents}})
  },
}))

class TestDirectory {
  name='test-output';kind='directory';permission='granted';files=new Map<string,Blob>();failFile='';writes:string[]=[];removed:string[]=[]
  async queryPermission(){return this.permission}
  async isSameEntry(other:unknown){return other===this}
  async getDirectoryHandle(){return this}
  async *entries(){for(const name of this.files.keys())yield [name,await this.getFileHandle(name)] as const}
  async getFileHandle(name:string,options?:{create?:boolean}){
    if(!this.files.has(name)&&!options?.create)throw new DOMException('missing','NotFoundError')
    if(!this.files.has(name)&&options?.create)this.files.set(name,new Blob())
    const root=this
    return {kind:'file',getFile:async()=>root.files.get(name)!,createWritable:async()=>{
      let pending:Blob
      return {write:async(blob:Blob)=>{pending=blob},close:async()=>{
        if(root.failFile===name)throw new DOMException('disk full','QuotaExceededError')
        root.files.set(name,pending);root.writes.push(name)
      },abort:async()=>{}}
    }}
  }
  async removeEntry(name:string){this.files.delete(name);this.removed.push(name)}
  handle(){return this as unknown as FileSystemDirectoryHandle}
}
let manifest:Manifest,blobs:Map<string,Blob>,root:TestDirectory,duringDownload:(path:string)=>void
async function artifact(path:string,content:string){const blob=new Blob([content]);blobs.set('/'+path,blob);return {id:path,path,url:'/'+path,sha256:await sha256(blob),size:blob.size,kind:'print'}}
async function owned(values:Record<string,string>){
  const hashes:Record<string,string>={}
  for(const [path,text]of Object.entries(values)){const blob=new Blob([text]);root.files.set(path,blob);hashes[path]=await sha256(blob)}
  localStore.values.set('saved:u:o',{version:1,complete:true,root:root.handle(),name:'小满',hashes})
}
beforeEach(async()=>{
  localStore.values.clear();localStore.writes=0;localStore.failAt=0
  root=new TestDirectory();blobs=new Map();duringDownload=()=>{}
  manifest={order_id:'o',name:'小满',version:2,complete:true,files:[await artifact('a.png','new-a'),await artifact('b.png','new-b')]}
  vi.stubGlobal('fetch',vi.fn(async(input:string)=>{
    if(input.endsWith('/manifest'))return Response.json(manifest)
    duringDownload(input)
    const blob=blobs.get(input)
    return blob?new Response(blob):new Response('',{status:404})
  }))
})

describe('real directory synchronization flow',()=>{
  it('automatically saves a completed order only once even if files disappear or versions change',async()=>{
    await syncOrder('u','o',root.handle(),()=>{},{automatic:true})
    root.files.delete('a.png');root.writes=[]
    manifest={...manifest,version:3}
    await syncOrder('u','o',root.handle(),()=>{},{automatic:true})
    expect(root.files.has('a.png')).toBe(false)
    expect(root.writes).toEqual([])
  })
  it('explicit re-download fetches and writes all files even when already current',async()=>{
    await syncOrder('u','o',root.handle(),()=>{})
    root.writes=[]
    await syncOrder('u','o',root.handle(),()=>{},{forceDownload:true})
    expect(root.writes).toEqual(['a.png','b.png'])
  })
  it('does not automatically download partial results',async()=>{
    manifest.complete=false
    await expect(syncOrder('u','o',root.handle(),()=>{},{automatic:true})).rejects.toThrow('全部成品')
    expect(root.writes).toEqual([])
  })
  it('writes verified files and preserves incomplete manifest status',async()=>{
    manifest.complete=false
    const messages:string[]=[]
    const saved=await syncOrder('u','o',root.handle(),message=>messages.push(message))
    expect(saved.complete).toBe(false)
    expect(messages.at(-1)).toContain('等待其余图片')
    expect(await root.files.get('a.png')!.text()).toBe('new-a')
    expect(saved.hashes).toEqual(Object.fromEntries(manifest.files.map(f=>[f.path,f.sha256])))
  })
  it('does not delete obsolete pages until every current page is written',async()=>{
    await owned({'a.png':'old-a','obsolete.png':'old-page'})
    root.failFile='b.png'
    await expect(syncOrder('u','o',root.handle(),()=>{})).rejects.toThrow('disk full')
    expect(root.files.has('obsolete.png')).toBe(true)
    root.failFile=''
    await syncOrder('u','o',root.handle(),()=>{})
    expect(root.writes.filter(path=>path==='a.png')).toHaveLength(1)
    expect(root.removed).toEqual(['obsolete.png'])
  })
  it('recovers a committed file after manifest storage failed using durable intent',async()=>{
    localStore.failAt=2
    await expect(syncOrder('u','o',root.handle(),()=>{})).rejects.toThrow('storage quota')
    expect(root.files.has('a.png')).toBe(true)
    expect(localStore.values.get('saved:u:o').intents['a.png'].sha256).toBe(manifest.files[0].sha256)
    localStore.failAt=0
    await syncOrder('u','o',root.handle(),()=>{})
    expect(root.writes.filter(path=>path==='a.png')).toHaveLength(1)
  })
  it('preserves foreign files even when byte-identical',async()=>{
    root.files.set('a.png',blobs.get('/a.png')!)
    await expect(syncOrder('u','o',root.handle(),()=>{})).rejects.toThrow('同名')
    expect(root.writes).toEqual([])
  })
  it('resumes its own empty placeholder after the first write failed',async()=>{
    root.failFile='a.png'
    await expect(syncOrder('u','o',root.handle(),()=>{})).rejects.toThrow('disk full')
    expect(root.files.get('a.png')!.size).toBe(0)
    root.failFile=''
    await syncOrder('u','o',root.handle(),()=>{})
    expect(await root.files.get('a.png')!.text()).toBe('new-a')
  })
  it('refuses files changed during download',async()=>{
    await owned({'a.png':'old-a'})
    duringDownload=path=>{if(path==='/a.png')root.files.set('a.png',new Blob(['manual-change']))}
    await expect(syncOrder('u','o',root.handle(),()=>{})).rejects.toThrow('保存期间')
    expect(await root.files.get('a.png')!.text()).toBe('manual-change')
  })
  it('refuses obsolete manifests and keeps old pages',async()=>{
    await owned({'obsolete.png':'old'})
    duringDownload=()=>{manifest={...manifest,version:3}}
    await expect(syncOrder('u','o',root.handle(),()=>{})).rejects.toThrow('结果已更新')
    expect(root.writes).toEqual([])
    expect(root.files.has('obsolete.png')).toBe(true)
  })
  it('repairs damaged managed files only with explicit repair option',async()=>{
    await owned({'a.png':'old'})
    root.files.set('a.png',new Blob(['damaged']))
    await expect(syncOrder('u','o',root.handle(),()=>{})).rejects.toThrow('被修改')
    await syncOrder('u','o',root.handle(),()=>{},{repairModified:true})
    expect(await root.files.get('a.png')!.text()).toBe('new-a')
  })
  it('stops on permission loss and account cancellation without writes',async()=>{
    root.permission='prompt'
    await expect(syncOrder('u','o',root.handle(),()=>{})).rejects.toThrow('重新授权')
    root.permission='granted'
    const controller=new AbortController()
    duringDownload=()=>controller.abort()
    await expect(syncOrder('u','o',root.handle(),()=>{},{signal:controller.signal})).rejects.toThrow()
    expect(root.writes).toEqual([])
  })
})
