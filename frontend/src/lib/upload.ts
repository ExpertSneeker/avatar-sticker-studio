import { api, post, sha256 } from './api'
import type { UploadResult } from './types'

export async function uploadFile(file:File,onProgress:(value:number)=>void,signal?:AbortSignal) {
  const hash=await sha256(file)
  signal?.throwIfAborted()
  let state=await post<UploadResult>('/uploads/init',{filename:file.name,size:file.size,sha256:hash},signal)
  const chunkSize=1024*1024
  while(!state.complete && state.offset<file.size) {
    const offset=state.offset
    signal?.throwIfAborted()
    state=await api<UploadResult>('/uploads/'+state.id,{method:'PUT',headers:{'Upload-Offset':String(offset),'Content-Type':'application/octet-stream'},body:file.slice(offset,offset+chunkSize),signal})
    if(state.offset<=offset) throw new Error('上传没有继续，请重试')
    onProgress(Math.round(state.offset/file.size*100))
  }
  signal?.throwIfAborted()
  return post<UploadResult>('/uploads/'+state.id+'/complete',undefined,signal)
}
