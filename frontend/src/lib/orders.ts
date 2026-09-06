export function withinPeriod(createdAt:string,days:number,now=Date.now()) {
  if(!days)return true
  const created=Date.parse(createdAt)
  return Number.isFinite(created)&&created>=now-days*86400000&&created<=now
}
export const submissionDate=(createdAt:string)=>new Date(createdAt).toLocaleString('zh-CN',{year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false})
