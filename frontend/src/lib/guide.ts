// Guest walkthrough state. "我知道了" hides a tip for this page visit only; "不再提示" hides that one
// tip on this device. Only these flags are stored (keys start with guest-guide:), never order data.
const PREFIX='guest-guide:'
const acknowledged=new Set<string>()
const listeners=new Set<()=>void>()
const notify=()=>listeners.forEach(listener=>listener())

function stored(key:string):string|null{try{return localStorage.getItem(PREFIX+key)}catch{return null}}

// Automated browsers skip the walkthrough unless a test opts in, so existing flows are not covered by it.
export function guideEnabled():boolean{
  if(typeof window==='undefined')return false
  return !navigator.webdriver||stored('force')==='1'
}
export function guideHidden(id:string):boolean{return !guideEnabled()||acknowledged.has(id)||stored(id)==='off'}
export function acknowledgeGuide(id:string){acknowledged.add(id);notify()}
export function muteGuide(id:string){
  acknowledged.add(id)
  try{localStorage.setItem(PREFIX+id,'off')}catch{/* private mode: still hidden for this visit */}
  notify()
}
export function replayGuides(){
  acknowledged.clear()
  try{for(const key of Object.keys(localStorage))if(key.startsWith(PREFIX)&&key!==PREFIX+'force')localStorage.removeItem(key)}catch{/* nothing stored */}
  notify()
}
export function subscribeGuide(listener:()=>void):()=>void{listeners.add(listener);return()=>{listeners.delete(listener)}}
