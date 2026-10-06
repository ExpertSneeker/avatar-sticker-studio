let expectedUser:string|null=null
// Polled GET JSON: remember the last body and its ETag in page memory only, send If-None-Match, and
// reuse the body when the server answers 304. Responses stay no-store, so nothing reaches disk.
const remembered=new Map<string,{etag:string;body:string}>(),REMEMBER_LIMIT=50
export async function fetchRevalidated(url:string,init:RequestInit={}):Promise<Response>{
  if((init.method||'GET').toUpperCase()!=='GET')return fetch(url,init)
  const headers=new Headers(init.headers),key=url+'\n'+(headers.get('X-Studio-User')||''),known=remembered.get(key)
  if(known)headers.set('If-None-Match',known.etag)
  const response=await fetch(url,{...init,headers,cache:'no-store'})
  if(response.status===304&&known)return new Response(known.body,{status:200,headers:{'Content-Type':'application/json'}})
  const etag=response.headers.get('ETag')
  if(response.ok&&etag&&response.headers.get('Content-Type')?.startsWith('application/json')){
    remembered.delete(key);remembered.set(key,{etag,body:await response.clone().text()})
    if(remembered.size>REMEMBER_LIMIT)remembered.delete(remembered.keys().next().value as string)
  }else remembered.delete(key)
  return response
}
export class ApiError extends Error {status:number;detail?:unknown;constructor(message:string,status:number,detail?:unknown){super(message);this.status=status;this.detail=detail}}
export function expectUser(id:string|null){if(id!==expectedUser)remembered.clear();expectedUser=id}
export async function api<T>(path:string, options:RequestInit={}):Promise<T> {
  const headers = new Headers(options.headers)
  const requiresUser=(!path.startsWith('/auth/')&&path!=='/health')||path==='/auth/logout'||path==='/auth/me'
  if(requiresUser&&expectedUser)headers.set('X-Studio-User',expectedUser)
  if (options.body && !(options.body instanceof FormData) && typeof options.body === 'string') headers.set('Content-Type','application/json')
  const response = await fetchRevalidated('/api'+path,{...options,headers,credentials:'same-origin'})
  if (!response.ok) {
    let message = '请求失败，请稍后重试'
    let detail:unknown
    try { const error = await response.json(); detail=error.detail; message = typeof error.detail === 'string' ? error.detail : typeof error.detail?.message === 'string' ? error.detail.message : JSON.stringify(error.detail) } catch { message = '服务暂时不可用（'+response.status+'）' }
    if(response.status===401&&requiresUser&&typeof window!=='undefined')window.dispatchEvent(new Event('studio-session-expired'))
    throw new ApiError(message,response.status,detail)
  }
  if (response.status===204) return undefined as T
  return response.json()
}
export const post = <T>(path:string,body?:unknown,signal?:AbortSignal)=>api<T>(path,{method:'POST',body:body===undefined?undefined:JSON.stringify(body),signal})
export const patch = <T>(path:string,body:unknown)=>api<T>(path,{method:'PATCH',body:JSON.stringify(body)})
export async function sha256(blob:Blob):Promise<string> {
  const buffer = await blob.arrayBuffer()
  const digest = await crypto.subtle.digest('SHA-256',buffer)
  return Array.from(new Uint8Array(digest),b=>b.toString(16).padStart(2,'0')).join('')
}
