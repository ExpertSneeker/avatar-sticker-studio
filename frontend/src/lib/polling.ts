// Polls only while the tab is visible. Returning to the tab refreshes immediately, so hidden
// tabs stop costing server work without ever showing staler data once the user looks again.
export function visiblePolling(tick:()=>void,ms:number):()=>void {
  if(typeof document==='undefined'){const timer=setInterval(tick,ms);return()=>clearInterval(timer)}
  let timer:ReturnType<typeof setInterval>|null=null
  const start=()=>{if(timer===null)timer=setInterval(tick,ms)}
  const stop=()=>{if(timer!==null){clearInterval(timer);timer=null}}
  const change=()=>{if(document.visibilityState==='hidden')stop();else if(timer===null){tick();start()}}
  if(document.visibilityState!=='hidden')start()
  document.addEventListener('visibilitychange',change)
  return()=>{stop();document.removeEventListener('visibilitychange',change)}
}

// Staff pages: the account check is tiny and must notice deactivation or permission changes
// quickly, while the library lists (all stickers, templates, categories) are large and change
// rarely. Editors' own changes still reload the library at once through onRefresh.
export const ACCOUNT_POLL_MS=5000,LIBRARY_POLL_MS=60000
export function staffPolling(account:()=>void,library:()=>void):()=>void {
  const stops=[visiblePolling(account,ACCOUNT_POLL_MS),visiblePolling(library,LIBRARY_POLL_MS)]
  return()=>stops.forEach(stop=>stop())
}
