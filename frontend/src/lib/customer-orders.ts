import { ApiError, post } from './api'
import type { PrintSettings, Sticker, TemplateSet } from './types'

export type OrderState = 'draft' | 'review' | 'submitted' | 'cancelled'
export interface CustomerVersion { id:string; preview_url:string }
export interface CustomerSlot {
  id:string; avatar_id:string; sticker_code:string; status:string
  reruns_used:number; reruns_reserved:number; selected_version_id:string|null
  pending_version_id:string|null; versions:CustomerVersion[]; error?:string|null; raw_available?:boolean; needs_resolution?:boolean
}
export interface CustomerAvatar {id:string; name:string; preview_url:string}
// This is the only order shape the guest workbench receives. Submitted/cancelled DTOs
// deliberately omit avatars and slots; do not fill them from an older response.
export interface GuestOrder {
  id:string; order_number:string; state:OrderState; version?:number
  generation_limit:number; final_count:number; rerun_limit:number
  avatars?:CustomerAvatar[]; slots?:CustomerSlot[]; preview_url?:string|null
  delivery_ready?:boolean; created_at?:string; paused?:boolean; hold_reason?:string|null
}
export interface CustomerOrder extends GuestOrder {
  version:number;
  shop_id?:string|null; shop_name?:string; owner:string; owner_name:string; organization_id:string; notes:string
  watermark:string; print_settings:PrintSettings; delivery_version:number
  buyer_memo?:string; platform_remark?:string
}
export interface LibrarySticker {id:string;code:string;name:string;category:string;revision:number;preview_url:string;active?:boolean}
export interface LibraryTemplate {id:string;code:string;name:string;category:string;sticker_ids:string[];images:{preview_url:string}[];active?:boolean;available?:boolean}
export interface CustomerLibrary {stickers:LibrarySticker[];templates:LibraryTemplate[]}
export interface AvatarChoice {upload_id:string;template_ids:string[];sticker_ids:string[]}
export interface Preflight {avatar_count:number;selection_count:number;generation_count:number}
export const stateLabels:Record<OrderState,string> = {draft:'待制作',review:'选图中',submitted:'已提交',cancelled:'已取消'}
export const roleLabel=(role:string)=>({superadmin:'超级管理员',org_admin:'组织管理员',staff:'成员'}[role]||role)
export const isAdmin=(role:string)=>role==='superadmin'||role==='org_admin'

export function staffLibrary(stickers:Sticker[],templates:TemplateSet[]):CustomerLibrary {
  return {stickers:stickers.map(s=>({...s,preview_url:s.image.url})),templates:templates.map(t=>({...t,sticker_ids:t.sticker_ids||t.images.map(i=>i.sticker_id||'').filter(Boolean),images:t.images.map(i=>({preview_url:i.url}))}))}
}
export function quantityIds(ids:string[],id:string,quantity:number,max=360):string[] {
  const count=Math.max(0,Math.min(max,Number.isFinite(quantity)?Math.floor(quantity):0))
  return [...ids.filter(value=>value!==id),...Array.from({length:count},()=>id)]
}
export function selectionCounts(avatars:AvatarChoice[],library:CustomerLibrary):Preflight {
  let selection_count=0,generation_count=0
  for(const avatar of avatars){
    const ids=[...avatar.sticker_ids,...avatar.template_ids.flatMap(id=>library.templates.find(t=>t.id===id)?.sticker_ids||[])]
    selection_count+=ids.length
    generation_count+=new Set(ids.map(id=>{const sticker=library.stickers.find(s=>s.id===id);return `${id}:${sticker?.revision??0}`})).size
  }
  return {avatar_count:avatars.length,selection_count,generation_count}
}
export function selectionQuantityLimit(avatars:AvatarChoice[],library:CustomerLibrary,avatarId:string,kind:'template_ids'|'sticker_ids',id:string,max:number,selectionCount=selectionCounts(avatars,library).selection_count):number {
  const avatar=avatars.find(value=>value.upload_id===avatarId)
  const cost=kind==='template_ids'?(library.templates.find(value=>value.id===id)?.sticker_ids.length??0):1
  if(!avatar||cost<=0)return 0
  const current=avatar[kind].filter(value=>value===id).length
  const otherCopies=selectionCount-current*cost
  return Math.max(0,Math.floor((max-otherCopies)/cost))
}
export function canApplySelection(previousCount:number,nextCount:number,max:number):boolean {
  return nextCount<=max||nextCount<previousCount
}
export function selectionError(order:GuestOrder,counts:Preflight):string {
  if(counts.avatar_count<1||counts.avatar_count>order.final_count)return `请上传 1 至 ${order.final_count} 个头像`
  if(counts.selection_count<order.final_count||counts.selection_count>order.generation_limit)return `请选择 ${order.final_count} 至 ${order.generation_limit} 张贴纸（含重复份数）`
  return ''
}
export const slotBusy=(slot:CustomerSlot)=>slot.reruns_reserved>0||['queued','pending','running','processing','generating','unknown'].includes(slot.status)
export function submissionError(order:GuestOrder,ids:string[]):string {
  if(order.state!=='review')return '当前订单不能提交'
  const slots=order.slots||[]
  if(slots.some(slotBusy))return '仍有图片处理中或结果待确认，请稍后再提交'
  if(slots.some(s=>s.pending_version_id))return '请先为重跑图片选择保留版本'
  if(ids.length!==order.final_count||new Set(ids).size!==ids.length)return `请准确选择 ${order.final_count} 张成品`
  if(ids.some(id=>!slots.some(s=>s.id===id&&s.selected_version_id&&s.versions.some(v=>v.id===s.selected_version_id))))return '所选图片尚未生成完成'
  return ''
}
export function moveSelection(ids:string[],index:number,offset:number):string[] {
  const next=[...ids],target=index+offset
  if(index<0||target<0||index>=next.length||target>=next.length)return next
  ;[next[index],next[target]]=[next[target],next[index]]
  return next
}
export async function guestApi<T>(path:string,options:RequestInit={}):Promise<T> {
  const headers=new Headers(options.headers)
  if(typeof options.body==='string')headers.set('Content-Type','application/json')
  const response=await fetch('/api/guest'+path,{...options,headers,credentials:'same-origin',cache:'no-store'})
  if(!response.ok){
    let message='操作未完成，请稍后重试'
    try{const body=await response.json();if(typeof body.detail==='string')message=body.detail;else if(typeof body.detail?.message==='string')message=body.detail.message}catch{}
    if(response.status===401)window.dispatchEvent(new Event('guest-session-expired'))
    throw new ApiError(message,response.status)
  }
  return response.status===204?undefined as T:response.json()
}
export const guestPost=<T>(path:string,body?:unknown,signal?:AbortSignal)=>guestApi<T>(path,{method:'POST',body:body===undefined?undefined:JSON.stringify(body),signal})

// Retry an uncertain network response with exactly the same token and payload.
// Tokens live only in memory; guest choices and images never enter browser storage.
export class OrderMutations {
  private pending: {key:string;path:string;body:Record<string,unknown>;mode:'guest'|'staff';base:string}|null=null
  async run<T>(mode:'guest'|'staff',base:string,path:string,version:number,payload:Record<string,unknown>={}):Promise<T>{
    const key=JSON.stringify([mode,base,path,payload])
    if(this.pending&&this.pending.key!==key)throw new Error('上一操作结果尚未确认，请先重试上一操作')
    const request=this.pending||{key,path,mode,base,body:{...payload,client_token:crypto.randomUUID(),expected_version:version}}
    this.pending=request
    return this.retry<T>()
  }
  get pendingPath(){return this.pending?.path||null}
  async retry<T>():Promise<T>{
    const request=this.pending
    if(!request)throw new Error('没有待确认的操作')
    try{
      const result=request.mode==='guest'?await guestPost<T>(request.base+request.path,request.body):await post<T>(request.base+request.path,request.body)
      this.pending=null;return result
    }catch(error){if(error instanceof ApiError&&error.status>=400&&error.status<500)this.pending=null;throw error}
  }
}
