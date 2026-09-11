import { sha256 } from './api'
import { prepareUploadImage } from './image'
import { guestApi, guestPost } from './customer-orders'
export interface GuestUpload {id:string;filename?:string;size?:number;offset:number;complete:boolean;preview_url?:string}
export async function guestUpload(file:File,onProgress:(value:number)=>void,signal?:AbortSignal){
  const prepared=await prepareUploadImage(file,signal)
  const hash=await sha256(prepared)
  signal?.throwIfAborted()
  let state=await guestPost<GuestUpload>('/uploads/init',{filename:prepared.name,size:prepared.size,sha256:hash},signal)
  while(!state.complete&&state.offset<prepared.size){
    const offset=state.offset
    state=await guestApi<GuestUpload>('/uploads/'+encodeURIComponent(state.id),{method:'PUT',headers:{'Upload-Offset':String(offset),'Content-Type':'application/octet-stream'},body:prepared.slice(offset,offset+1024*1024),signal})
    if(state.offset<=offset)throw new Error('上传没有继续，请重试')
    onProgress(Math.round(state.offset/prepared.size*100))
  }
  return guestPost<GuestUpload>('/uploads/'+encodeURIComponent(state.id)+'/complete',undefined,signal)
}
