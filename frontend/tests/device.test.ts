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
  vi.stubGlobal('location',{href:'https://studio.example/customer-orders',origin:'https://studio.example'})
  manifest={order_id:'o',name:'小满',version:2,complete:true,files:[await artifact('a.png','new-a'),await artifact('b.png','new-b')]}
  vi.stubGlobal('fetch',vi.fn(async(input:string)=>{
    if(input.endsWith('/manifest'))return Response.json(manifest)
    duringDownload(input)
    const blob=blobs.get(input)
    return blob?new Response(blob):new Response('',{status:404})
  }))
})

describe('real directory synchronization flow',()=>{
  it('uses the customer manifest by default and encodes the order ID',async()=>{
    const saved=await syncOrder('u','order /客户',root.handle(),()=>{})
    expect(saved.complete).toBe(true)
    expect(fetch).toHaveBeenCalledWith('/api/customer-orders/order%20%2F%E5%AE%A2%E6%88%B7/manifest',expect.anything())
  })
  it('can re-download to another directory and then back to its previously managed directory',async()=>{
    await syncOrder('u','o',root.handle(),()=>{})
    const alternate=new TestDirectory();alternate.name='alternate-output'
    await syncOrder('u','o',alternate.handle(),()=>{},{forceDownload:true})
    root.writes=[]
    await syncOrder('u','o',root.handle(),()=>{},{forceDownload:true})
    expect(root.writes).toEqual(['a.png','b.png'])
    expect(await alternate.files.get('a.png')!.text()).toBe('new-a')
  })
  it('only writes print files, never overview or originals',async()=>{
    manifest.files.push({...await artifact('overview.png','preview'),kind:'overview'},{...await artifact('original.png','source'),kind:'original'})
    const saved=await syncOrder('u','o',root.handle(),()=>{})
    expect(root.writes).toEqual(['a.png','b.png'])
    expect(Object.keys(saved.hashes)).toEqual(['a.png','b.png'])
  })
  it('explicit re-download fetches and writes all files even when already current',async()=>{
    await syncOrder('u','o',root.handle(),()=>{})
    root.writes=[]
    await syncOrder('u','o',root.handle(),()=>{},{forceDownload:true})
    expect(root.writes).toEqual(['a.png','b.png'])
  })
  it('rejects partial print manifests',async()=>{
    manifest.complete=false
    await expect(syncOrder('u','o',root.handle(),()=>{},{})).rejects.toThrow('全部打印文件')
    expect(root.writes).toEqual([])
  })
  it('supports authoritative customer manifests with a sanitized folder name',async()=>{
    const saved=await syncOrder('u','o',root.handle(),()=>{},{manifestPath:'/customer-orders/o/manifest',folderName:'ORDER_备注'})
    expect(saved.name).toBe('ORDER_备注')
    expect(saved.complete).toBe(true)
    expect(fetch).toHaveBeenCalledWith('/api/customer-orders/o/manifest',expect.anything())
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


describe('OSS print delivery',()=>{
  const remote='https://print.example/a.png?signature=initial'
  async function remoteFile(){
    manifest.files=[{...manifest.files[0],url:remote,local_url:'/a.png'}]
    return manifest.files[0]
  }
  function route(handler:(url:string,options:RequestInit)=>Promise<Response>|Response){
    vi.stubGlobal('fetch',vi.fn(async(url:string,options:RequestInit)=>{
      if(url.endsWith('/manifest'))return Response.json(manifest)
      return handler(url,options)
    }))
  }
  it('omits credentials on cross-origin downloads and retains them for same-origin files',async()=>{
    await remoteFile()
    manifest.files.push({...await artifact('b.png','new-b'),url:'https://studio.example/b.png'})
    route((url,options)=>{
      if(url===remote){
        expect(options.credentials).toBe('omit')
        return new Response(blobs.get('/a.png'))
      }
      expect(options.credentials).toBe('same-origin')
      return new Response(blobs.get('/b.png'))
    })
    const progress:string[]=[]
    await syncOrder('u','o',root.handle(),message=>progress.push(message))
    expect(root.writes).toEqual(['a.png','b.png'])
    expect(progress.some(message=>message.includes('从 OSS 下载'))).toBe(true)
  })
  it('uses the last refreshed signature for the next file',async()=>{
    const first='https://print.example/a.png?signature=initial'
    const stale='https://print.example/b.png?signature=stale'
    const fresh='https://print.example/b.png?signature=fresh'
    manifest.files=manifest.files.map((file,index)=>({...file,url:index?stale:first,local_url:'/'+file.path}))
    const requested:string[]=[]
    route(url=>{
      requested.push(url)
      if(url===first){manifest={...manifest,files:manifest.files.map(file=>file.path==='b.png'?{...file,url:fresh}:file)};return new Response(blobs.get('/a.png'))}
      return url===fresh?new Response(blobs.get('/b.png')):new Response('',{status:403})
    })
    await syncOrder('u','o',root.handle(),()=>{})
    expect(requested).toEqual([first,fresh])
    expect(root.writes).toEqual(['a.png','b.png'])
  })
  it('refreshes a rejected signature once and saves from the renewed remote URL',async()=>{
    await remoteFile()
    const fresh='https://print.example/a.png?signature=fresh'
    const requested:string[]=[]
    route(url=>{
      requested.push(url)
      if(url===remote){manifest={...manifest,files:manifest.files.map(file=>({...file,url:fresh}))};return new Response('',{status:403})}
      return new Response(blobs.get('/a.png'))
    })
    await syncOrder('u','o',root.handle(),()=>{})
    expect(requested).toEqual([remote,fresh])
    expect(await root.files.get('a.png')!.text()).toBe('new-a')
  })
  it('falls back to the local URL after exactly one remote retry and reports slower transfer',async()=>{
    await remoteFile()
    const fresh='https://print.example/a.png?signature=fresh'
    const requested:string[]=[],progress:string[]=[]
    route(url=>{
      requested.push(url)
      if(url===remote){manifest={...manifest,files:manifest.files.map(file=>({...file,url:fresh}))};throw new TypeError('network disconnected')}
      if(url===fresh)return new Response('',{status:403})
      return new Response(blobs.get('/a.png'))
    })
    await syncOrder('u','o',root.handle(),message=>progress.push(message))
    expect(requested).toEqual([remote,fresh,'/a.png'])
    expect(progress.some(message=>message.includes('服务器下载')&&message.includes('较慢'))).toBe(true)
    expect(await root.files.get('a.png')!.text()).toBe('new-a')
  })
  it('retries a remote body network failure before falling back',async()=>{
    await remoteFile()
    const requested:string[]=[]
    route(url=>{
      requested.push(url)
      if(url===remote){const response=new Response();vi.spyOn(response,'blob').mockRejectedValue(new TypeError('body disconnected'));return response}
      return new Response(blobs.get('/a.png'))
    })
    await syncOrder('u','o',root.handle(),()=>{})
    expect(requested).toEqual([remote,remote,'/a.png'])
    expect(root.writes).toEqual(['a.png'])
  })
  it.each(['version','sha256'] as const)('stops before retry when the refreshed %s changes',async(field)=>{
    await remoteFile()
    const requested:string[]=[]
    route(url=>{
      requested.push(url)
      manifest=field==='version'?{...manifest,version:3}:{...manifest,files:manifest.files.map(file=>({...file,sha256:'changed'}))}
      return new Response('',{status:403})
    })
    await expect(syncOrder('u','o',root.handle(),()=>{})).rejects.toThrow('结果已更新')
    expect(requested).toEqual([remote])
    expect(root.writes).toEqual([])
  })
  it('stops before writing if the refreshed hash changes after download',async()=>{
    await remoteFile()
    route(()=>{
      manifest={...manifest,files:manifest.files.map(file=>({...file,sha256:'changed'}))}
      return new Response(blobs.get('/a.png'))
    })
    await expect(syncOrder('u','o',root.handle(),()=>{})).rejects.toThrow('结果已更新')
    expect(root.writes).toEqual([])
  })
  it('does not retry or fall back after an abort',async()=>{
    await remoteFile()
    const controller=new AbortController(),requested:string[]=[]
    route(url=>{requested.push(url);controller.abort();throw new DOMException('cancelled','AbortError')})
    await expect(syncOrder('u','o',root.handle(),()=>{},{signal:controller.signal})).rejects.toThrow('cancelled')
    expect(requested).toEqual([remote])
    expect(root.writes).toEqual([])
  })
  it('does not retry same-origin failures as OSS failures',async()=>{
    const requested:string[]=[]
    route(url=>{requested.push(url);return new Response('',{status:503})})
    await expect(syncOrder('u','o',root.handle(),()=>{})).rejects.toThrow('下载失败')
    expect(requested).toEqual(['/a.png'])
    expect(root.writes).toEqual([])
  })
  it('does not retry or fall back for remote content integrity failure',async()=>{
    await remoteFile()
    const requested:string[]=[]
    route(url=>{requested.push(url);return new Response('wrong')})
    await expect(syncOrder('u','o',root.handle(),()=>{})).rejects.toThrow('文件校验失败')
    expect(requested).toEqual([remote])
    expect(root.writes).toEqual([])
  })
  it('stops on non-network response read failures without renewing or falling back',async()=>{
    await remoteFile()
    const requested:string[]=[]
    route(url=>{
      requested.push(url)
      const response=new Response()
      vi.spyOn(response,'blob').mockRejectedValue(new DOMException('cannot allocate buffer','QuotaExceededError'))
      return response
    })
    await expect(syncOrder('u','o',root.handle(),()=>{})).rejects.toThrow('cannot allocate buffer')
    expect(requested).toEqual([remote])
    expect(root.writes).toEqual([])
  })
  it('stops on refreshed manifest authorization denial without using the old local URL',async()=>{
    await remoteFile()
    let authorized=true
    const requested:string[]=[]
    vi.stubGlobal('fetch',vi.fn(async(url:string)=>{
      requested.push(url)
      if(url.endsWith('/manifest'))return authorized?Response.json(manifest):Response.json({detail:'后台账号已失效'},{status:403})
      authorized=false
      return new Response('',{status:403})
    }))
    await expect(syncOrder('u','o',root.handle(),()=>{})).rejects.toThrow('后台账号已失效')
    expect(requested).toEqual(['/api/customer-orders/o/manifest',remote,'/api/customer-orders/o/manifest'])
    expect(root.writes).toEqual([])
  })
  it('does not retry a failed local fallback',async()=>{
    await remoteFile()
    const requested:string[]=[]
    route(url=>{requested.push(url);return new Response('',{status:503})})
    await expect(syncOrder('u','o',root.handle(),()=>{})).rejects.toThrow('下载失败')
    expect(requested).toEqual([remote,remote,'/a.png'])
    expect(root.writes).toEqual([])
  })
  it('uses the refreshed local URL for fallback',async()=>{
    await remoteFile()
    const requested:string[]=[]
    route(url=>{
      requested.push(url)
      if(url===remote){manifest={...manifest,files:manifest.files.map(file=>({...file,local_url:'/latest-local.png'}))};return new Response('',{status:403})}
      return url==='/latest-local.png'?new Response(blobs.get('/a.png')):new Response('',{status:404})
    })
    await syncOrder('u','o',root.handle(),()=>{})
    expect(requested).toEqual([remote,remote,'/latest-local.png'])
    expect(root.writes).toEqual(['a.png'])
  })
  it('downloads the local manifest URL only once if OSS is disabled after refresh',async()=>{
    await remoteFile()
    const requested:string[]=[]
    route(url=>{
      requested.push(url)
      if(url===remote){manifest={...manifest,files:manifest.files.map(file=>({...file,url:'/a.png'}))};return new Response('',{status:403})}
      return new Response(blobs.get('/a.png'))
    })
    await syncOrder('u','o',root.handle(),()=>{})
    expect(requested).toEqual([remote,'/a.png'])
    expect(root.writes).toEqual(['a.png'])
  })
  it('rejects incorrect remote content length without retry or fallback',async()=>{
    await remoteFile()
    const requested:string[]=[]
    route(url=>{requested.push(url);return new Response('too long')})
    await expect(syncOrder('u','o',root.handle(),()=>{})).rejects.toThrow('文件校验失败')
    expect(requested).toEqual([remote])
    expect(root.writes).toEqual([])
  })

})
