let expectedUser:string|null=null
export class ApiError extends Error {status:number;constructor(message:string,status:number){super(message);this.status=status}}
export function expectUser(id:string|null){expectedUser=id}
export async function api<T>(path:string, options:RequestInit={}):Promise<T> {
  const headers = new Headers(options.headers)
  const requiresUser=(!path.startsWith('/auth/')&&path!=='/health')||path==='/auth/logout'||path==='/auth/me'
  if(requiresUser&&expectedUser)headers.set('X-Studio-User',expectedUser)
  if (options.body && !(options.body instanceof FormData) && typeof options.body === 'string') headers.set('Content-Type','application/json')
  const response = await fetch('/api'+path,{...options,headers,credentials:'same-origin'})
  if (!response.ok) {
    let message = '请求失败，请稍后重试'
    try { const error = await response.json(); message = typeof error.detail === 'string' ? error.detail : JSON.stringify(error.detail) } catch { message = '服务暂时不可用（'+response.status+'）' }
    if(response.status===401&&requiresUser&&typeof window!=='undefined')window.dispatchEvent(new Event('studio-session-expired'))
    throw new ApiError(message,response.status)
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
