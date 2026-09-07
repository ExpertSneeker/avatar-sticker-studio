export function withinPeriod(createdAt:string,days:number,now=Date.now()) {
  if(!days)return true
  const created=Date.parse(createdAt)
  return Number.isFinite(created)&&created>=now-days*86400000&&created<=now
}
export const submissionDate=(createdAt:string)=>new Date(createdAt).toLocaleString('zh-CN',{year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false})

export interface OrderDateFilter {mode:string;date:string;start:string;end:string}
export interface DateBounds {start:number;end:number;error?:string}
export function localDateInput(time=Date.now()) {
  const date=new Date(time)
  return `${String(date.getFullYear()).padStart(4,'0')}-${String(date.getMonth()+1).padStart(2,'0')}-${String(date.getDate()).padStart(2,'0')}`
}
function localMidnight(value:string) {
  if(!/^\d{4}-\d{2}-\d{2}$/.test(value))return NaN
  const date=new Date(value+'T00:00:00')
  return Number.isFinite(date.getTime())&&localDateInput(date.getTime())===value?date.getTime():NaN
}
export function dateFilterBounds(filter:OrderDateFilter,now=Date.now()):DateBounds {
  if(filter.mode==='0')return {start:-Infinity,end:Infinity}
  if(['1','3','7','30'].includes(filter.mode))return {start:now-Number(filter.mode)*86400000,end:now+1}
  const first=filter.mode==='today'?localDateInput(now):filter.mode==='date'?filter.date:filter.start
  const last=filter.mode==='range'?filter.end:first
  const start=localMidnight(first),end=localMidnight(last)
  if(!Number.isFinite(start)||!Number.isFinite(end))return {start:0,end:0,error:filter.mode==='range'?'请选择有效的开始和结束日期':'请选择有效日期'}
  if(start>end)return {start:0,end:0,error:'开始日期不能晚于结束日期'}
  // Calendar increment, not 24 hours: local days can vary with daylight saving time.
  const nextDay=new Date(end);nextDay.setDate(nextDay.getDate()+1);nextDay.setHours(0,0,0,0)
  return {start,end:nextDay.getTime()}
}
export function withinDateBounds(createdAt:string,bounds:DateBounds) {
  const created=Date.parse(createdAt)
  return !bounds.error&&Number.isFinite(created)&&created>=bounds.start&&created<bounds.end
}
