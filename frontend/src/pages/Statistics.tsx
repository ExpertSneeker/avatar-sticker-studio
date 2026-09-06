import { useEffect, useState } from 'react'
import { RefreshCw, BarChart3, Users, ArrowUpRight } from 'lucide-react'
import { api } from '../lib/api'
import { Empty, Spinner } from '../components/UI'
import './Statistics.css'

interface Totals {orders:number;ready_orders:number;images:number;completed:number;failed:number;unknown:number;running:number;queued:number;attempts:number;extra_attempts:number}
interface TemplateRow {code:string;orders:number;images:number;completed:number;failed:number}
interface MemberRow {id:string;display_name:string;username:string;active:boolean;orders:number;images:number;completed:number;failed:number;attempts:number}
interface StatisticsData {
  scope:'personal'|'global'; days:number; generated_at:string; summary:Totals; order_statuses:Record<string,number>
  daily:{date:string;orders:number;images:number}[]; templates:TemplateRow[]; members?:MemberRow[]
  accounts?:{total:number;active:number;contributing:number}
}
const periods=[['1','最近 24 小时'],['3','最近 3 天'],['7','最近 7 天'],['30','最近 30 天'],['0','全部订单']]
const states=[['queued','排队中'],['processing','处理中'],['completed','已完成'],['failed','有失败'],['unknown','待确认'],['paused','已暂停'],['archived','已归档']]
const number=(value:number)=>value.toLocaleString('zh-CN')

export function Statistics({global=false}:{global?:boolean}) {
  const [days,setDays]=useState('30'),[revision,setRevision]=useState(0),[data,setData]=useState<StatisticsData|null>(null)
  const [loading,setLoading]=useState(true),[error,setError]=useState(''),[metric,setMetric]=useState<'orders'|'images'>('orders')
  const [templateSearch,setTemplateSearch]=useState(''),[memberSearch,setMemberSearch]=useState('')
  useEffect(()=>{
    const controller=new AbortController()
    setLoading(true);setError('');setData(null)
    api<StatisticsData>((global?'/admin/statistics':'/statistics')+`?days=${days}&offset=${-new Date().getTimezoneOffset()}`,{signal:controller.signal})
      .then(value=>{if(!controller.signal.aborted)setData(value)})
      .catch(e=>{if(!controller.signal.aborted)setError(e.message)})
      .finally(()=>{if(!controller.signal.aborted)setLoading(false)})
    return()=>controller.abort()
  },[days,global,revision])
  const summary=data?.summary
  const max=Math.max(1,...(data?.daily.map(day=>day[metric])||[]))
  const templates=data?.templates.filter(row=>row.code.toLocaleLowerCase().includes(templateSearch.trim().toLocaleLowerCase()))||[]
  const members=data?.members?.filter(row=>(row.display_name+' '+row.username).toLocaleLowerCase().includes(memberSearch.trim().toLocaleLowerCase()))||[]
  const cards=summary?[
    ['提交订单',summary.orders,'所选时间内提交'],['成品齐全',summary.ready_orders,'单张、拼图与总览已完成'],
    ['计划图片',summary.images,'包含尚未开始的单张'],['单张已完成',summary.completed,`完成率 ${summary.images?(100*summary.completed/summary.images).toFixed(1):'0.0'}%`],
    ['失败单张',summary.failed,`${summary.unknown} 张结果待确认`],['追加生图尝试',summary.extra_attempts,`累计启动尝试 ${number(summary.attempts)} 次`],
  ]:[]
  return <div className="statistics-page">
    <div className="page-heading"><div><h1>{global?'全站统计':'我的统计'}</h1><p>{global?'查看团队的制作量与任务分布。':'每一笔订单，都有清楚的制作记录。'}</p></div><button className="button" disabled={loading} onClick={()=>setRevision(v=>v+1)}><RefreshCw size={16}/>刷新统计</button></div>
    <div className="statistics-toolbar"><label className="statistics-period">统计范围<select aria-label="统计时间范围" value={days} onChange={e=>setDays(e.target.value)}>{periods.map(([value,label])=><option key={value} value={value}>{label}</option>)}</select></label><span>按订单提交时间筛选 · 当前结果快照</span></div>
    {loading?<div className="statistics-loading" role="status"><Spinner/>正在汇总统计</div>:error?<div className="error-banner" role="alert">{error}<button className="text-button" onClick={()=>setRevision(v=>v+1)}>重新加载</button></div>:data&&summary&&<>
      <div className="statistics-cards">{cards.map(([label,value,hint])=><article className="statistics-card" key={label}><span>{label}</span><strong>{number(Number(value))}</strong><small>{hint}</small></article>)}</div>
      {global&&data.accounts&&<div className="statistics-team"><Users size={18}/><span>全站账号 <b>{data.accounts.total}</b></span><span>启用中 <b>{data.accounts.active}</b></span><span>本期提交成员 <b>{data.accounts.contributing}</b></span><small>账号数量不受时间范围影响</small></div>}
      <div className="statistics-panels"><section className="statistics-panel statistics-trend"><div className="statistics-section-heading"><div><h2><BarChart3 size={18}/>提交趋势</h2><p>{days==='0'?'全部订单模式下，图表展示最近 30 个自然日。':'按当前设备时区分日汇总。'}</p></div><div className="tabs"><button className={metric==='orders'?'active':''} onClick={()=>setMetric('orders')}>订单</button><button className={metric==='images'?'active':''} onClick={()=>setMetric('images')}>图片</button></div></div>
        <div className="statistics-chart" role="img" aria-label={`${metric==='orders'?'订单':'计划图片'}提交趋势，总计 ${data.daily.reduce((sum,day)=>sum+day[metric],0)}`}>
          {data.daily.map((day,index)=><div className="statistics-column" key={day.date} title={`${day.date}：${day.orders} 单 / ${day.images} 张`}><div className="statistics-bar-space"><div className="statistics-bar" style={{height:`${day[metric]/max*100}%`,minHeight:day[metric]?3:0}}><span>{day[metric]||''}</span></div></div><small>{index===0||index===data.daily.length-1||index%Math.ceil(data.daily.length/6)===0?day.date.slice(5).replace('-','/'):''}</small></div>)}
        </div>
        <details className="statistics-chart-data"><summary>查看每日明细</summary><div className="statistics-table-wrap"><table><thead><tr><th>提交日期</th><th>订单</th><th>计划图片</th></tr></thead><tbody>{data.daily.map(day=><tr key={day.date}><td>{day.date}</td><td>{day.orders}</td><td>{day.images}</td></tr>)}</tbody></table></div></details>
      </section><section className="statistics-panel statistics-status"><div className="statistics-section-heading"><div><h2>订单状态</h2><p>每个订单只计入一种状态</p></div></div>{states.map(([key,label])=><div className="statistics-status-row" key={key}><span><i className={'statistics-dot '+key}/>{label}</span><strong>{number(data.order_statuses[key]||0)}</strong></div>)}<p className="statistics-status-note">单张排队 {number(summary.queued)} · 处理中 {number(summary.running)}</p></section></div>
      <section className="statistics-panel"><div className="statistics-section-heading"><div><h2><ArrowUpRight size={18}/>模板使用情况</h2><p>按套装编号统计，按使用订单数排序</p></div><input aria-label="搜索统计模板" placeholder="搜索套装编号" value={templateSearch} onChange={e=>setTemplateSearch(e.target.value)}/></div>{templates.length?<div className="statistics-table-wrap"><table><thead><tr><th>套装编号</th><th>使用订单</th><th>计划图片</th><th>单张完成</th><th>单张失败</th></tr></thead><tbody>{templates.map(row=><tr key={row.code}><th scope="row">{row.code}</th><td>{number(row.orders)}</td><td>{number(row.images)}</td><td>{number(row.completed)}</td><td>{number(row.failed)}</td></tr>)}</tbody></table></div>:<Empty title={templateSearch?'没有匹配的套装':'这个时间范围内还没有订单'} description="尝试调整时间范围或搜索条件。"/>}</section>
      {global&&<section className="statistics-panel"><div className="statistics-section-heading"><div><h2><Users size={18}/>成员制作情况</h2><p>仅管理员可见 · 展示本期有订单的成员</p></div><input aria-label="搜索统计成员" placeholder="搜索姓名或账号" value={memberSearch} onChange={e=>setMemberSearch(e.target.value)}/></div>{members.length?<div className="statistics-table-wrap"><table><thead><tr><th>成员</th><th>订单</th><th>计划图片</th><th>单张完成</th><th>单张失败</th><th>启动尝试</th></tr></thead><tbody>{members.map(row=><tr key={row.id}><th scope="row">{row.display_name}<small className="statistics-username">{row.username}{!row.active?' · 已停用':''}</small></th><td>{number(row.orders)}</td><td>{number(row.images)}</td><td>{number(row.completed)}</td><td>{number(row.failed)}</td><td>{number(row.attempts)}</td></tr>)}</tbody></table></div>:<Empty title="没有匹配的成员记录" description="尝试调整时间范围或搜索条件。"/>}</section>}
      <div className="statistics-footnote"><p>统计基于当前保留的订单，包含归档订单；清理后相应数据会移除。完成率＝当前完成单张 ÷ 计划图片。</p><p>追加生图尝试＝每张首次启动以外的尝试，包含重跑及提交重试；不是实际计费次数。历史耗时、费用及跨设备下载次数暂不统计。</p><span>更新于 {new Date(data.generated_at).toLocaleString('zh-CN',{hour12:false})}</span></div>
    </>}
  </div>
}
