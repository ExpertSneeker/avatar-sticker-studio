import { useEffect, useState } from 'react'
import { Download, Pencil, RefreshCw } from 'lucide-react'
import { api } from '../lib/api'
import { PLATFORM_KEYS, PLATFORM_LABELS, type PlatformKey } from '../lib/agiso'
import { stateLabels, type OrderState } from '../lib/customer-orders'
import { Empty, Modal, Spinner, useNotice } from '../components/UI'

type Category='packaging'|'shipping'|'material'|'generation'|'cutout'|'agiso'|'oss'|'esa'
interface Rates {from:string;packaging:number;shipping:number;sheet:number;per_sheet:number;cutout:number;agiso_base:number;agiso_high:number;agiso_increment:number}
interface CostRow {id:string;order_number:string;state:OrderState;created:string;platform:PlatformKey;shop_name:string;shipped_at:number|null;printed:number;sheets:number;fixed_basis:'actual'|'estimate'|null;cutouts:number;requests:number;allocated:number;costs:Record<Category,number>;total:number}
export interface CostReport {date_from:string|null;date_to:string|null;today:string;scope:'global'|'organization';rates:Rates;rate_versions:Rates[]
  fx:{usd_cny:number;source:string;day:string|null;published?:string|null}
  summary:{orders:number;printed:number;sheets:number;total:number;per_order:number;per_sticker:number;categories:Record<Category,number>}
  orders:CostRow[];unattributed?:{categories:Record<Category,number>;total:number}
  agiso_check?:{days:number;balance_drop:number;computed:number;ratio:number|null;balance:number|null;balance_day:string|null}}
export const categoryLabels:Record<Category,string>={packaging:'包装',shipping:'快递',material:'物料',generation:'生图',cutout:'抠图',agiso:'阿奇索',oss:'OSS',esa:'ESA 加速'}
const categories=Object.keys(categoryLabels) as Category[]
const fxSources:Record<string,string>={cfets:'中国外汇交易中心中间价','open.er-api.com':'open.er-api.com',fallback:'默认值（尚未取得当日汇率）'}
const yuan=(value:number,digits=2)=>'¥'+value.toFixed(digits)
const pad=(n:number)=>String(n).padStart(2,'0')
const iso=(d:Date)=>`${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}`
function period(name:string):[string,string]{
  const now=new Date()
  if(name==='this-month')return [iso(new Date(now.getFullYear(),now.getMonth(),1)),iso(now)]
  if(name==='last-month')return [iso(new Date(now.getFullYear(),now.getMonth()-1,1)),iso(new Date(now.getFullYear(),now.getMonth(),0))]
  if(name==='30')return [iso(new Date(now.getTime()-29*86400000)),iso(now)]
  return ['','']
}
const rateFields:[keyof Rates,string,number][]=[['packaging','包装费（元/单）',0.01],['shipping','快递费（元/单）',0.01],['sheet','物料（元/张）',0.01],['per_sheet','每张物料可裁贴纸数',1],['cutout','抠图（元/次，成功才计费）',0.001],['agiso_base','阿奇索基础档（元/次）',0.001],['agiso_high','阿奇索高级档（元/次）',0.001],['agiso_increment','阿奇索增值档（元/次）',0.001]]

function csv(report:CostReport){
  const head=['订单号','创建日期','平台','店铺','状态','印刷张数','物料张数','包装/快递/物料',...categories.map(c=>categoryLabels[c]),'合计']
  const rows=report.orders.map(r=>[r.order_number,r.created,PLATFORM_LABELS[r.platform],r.shop_name,stateLabels[r.state],r.printed,r.sheets,r.fixed_basis==='estimate'?'预计':r.fixed_basis==='actual'?'实际':'',...categories.map(c=>r.costs[c].toFixed(4)),r.total.toFixed(4)])
  return '﻿'+[head,...rows].map(line=>line.map(v=>`"${String(v).replace(/"/g,'""')}"`).join(',')).join('\r\n')
}

export function Costs({global=false,canEdit=false}:{global?:boolean;canEdit?:boolean}){
  const notice=useNotice()
  const [preset,setPreset]=useState('this-month'),[range,setRange]=useState<[string,string]>(()=>period('this-month')),[platform,setPlatform]=useState<'all'|PlatformKey>('all')
  const [data,setData]=useState<CostReport|null>(null),[loading,setLoading]=useState(true),[error,setError]=useState(''),[revision,setRevision]=useState(0)
  const [editing,setEditing]=useState<Rates|null>(null),[saving,setSaving]=useState(false)
  useEffect(()=>{
    const controller=new AbortController(),params=new URLSearchParams({scope:global?'global':'organization',offset:String(-new Date().getTimezoneOffset())})
    if(range[0])params.set('date_from',range[0]);if(range[1])params.set('date_to',range[1]);if(platform!=='all')params.set('platform',platform)
    setLoading(true);setError('')
    api<CostReport>('/costs?'+params,{signal:controller.signal}).then(value=>{if(!controller.signal.aborted)setData(value)}).catch(e=>{if(!controller.signal.aborted)setError(e.message)}).finally(()=>{if(!controller.signal.aborted)setLoading(false)})
    return()=>controller.abort()
  },[global,range,platform,revision])
  async function saveRates(){
    if(!editing)return
    setSaving(true)
    try{await api('/costs/rates',{method:'PUT',body:JSON.stringify(editing)});setEditing(null);setRevision(v=>v+1);notice('成本费率已保存')}catch(e){notice((e as Error).message,'error')}finally{setSaving(false)}
  }
  function exportCsv(){
    if(!data)return
    const link=document.createElement('a');link.href=URL.createObjectURL(new Blob([csv(data)],{type:'text/csv;charset=utf-8'}))
    link.download=`订单成本_${data.date_from||'全部'}_${data.date_to||data.today}.csv`;link.click();setTimeout(()=>URL.revokeObjectURL(link.href),1000)
  }
  const summary=data?.summary,max=Math.max(0.0001,...categories.map(c=>summary?.categories[c]||0))
  return <div className="costs-view">
    <div className="statistics-toolbar costs-toolbar"><label className="statistics-period">时间<select aria-label="成本时间范围" value={preset} onChange={e=>{setPreset(e.target.value);if(e.target.value!=='custom')setRange(period(e.target.value))}}><option value="this-month">本月</option><option value="last-month">上月</option><option value="30">最近 30 天</option><option value="all">全部订单</option><option value="custom">自定义</option></select></label>
      {preset==='custom'&&<><label className="statistics-period">开始<input type="date" aria-label="成本开始日期" value={range[0]} onChange={e=>setRange([e.target.value,range[1]])}/></label><label className="statistics-period">结束<input type="date" aria-label="成本结束日期" value={range[1]} min={range[0]} onChange={e=>setRange([range[0],e.target.value])}/></label></>}
      <label className="statistics-period">平台<select aria-label="成本平台" value={platform} onChange={e=>setPlatform(e.target.value as 'all'|PlatformKey)}><option value="all">全部平台</option>{PLATFORM_KEYS.map(key=><option key={key} value={key}>{PLATFORM_LABELS[key]}</option>)}</select></label>
      <span>按订单创建日期筛选，订单的全部成本都计入该订单</span>
      <div className="costs-toolbar-actions"><button className="button" disabled={loading} onClick={()=>setRevision(v=>v+1)}><RefreshCw size={16}/>刷新</button><button className="button" disabled={!data?.orders.length} onClick={exportCsv}><Download size={16}/>导出 CSV</button></div></div>
    {loading?<div className="statistics-loading" role="status"><Spinner/>正在计算成本</div>:error?<div className="error-banner" role="alert">{error}</div>:data&&summary&&<>
      <div className="statistics-cards">{[['总成本',yuan(summary.total),`${summary.orders} 个订单`],['单均成本',yuan(summary.per_order),'总成本 ÷ 订单数'],['每张贴纸成本',yuan(summary.per_sticker,3),`印刷 ${summary.printed} 张`],['物料用量',`${summary.sheets} 张`,`每张物料裁 ${data.rates.per_sheet} 张贴纸`]].map(([label,value,hint])=><article className="statistics-card" key={label}><span>{label}</span><strong>{value}</strong><small>{hint}</small></article>)}</div>
      <div className="statistics-panels"><section className="statistics-panel"><div className="statistics-section-heading"><div><h2>成本构成</h2><p>所选订单的各项合计</p></div></div>
        {categories.map(c=><div className="costs-category" key={c}><span>{categoryLabels[c]}</span><div className="costs-category-bar"><i style={{width:`${(summary.categories[c]/max)*100}%`}}/></div><strong>{yuan(summary.categories[c])}</strong><small>{summary.total?(100*summary.categories[c]/summary.total).toFixed(1):'0.0'}%</small></div>)}
      </section><section className="statistics-panel costs-rates"><div className="statistics-section-heading"><div><h2>费率</h2><p>{data.rates.from==='1970-01-01'?'默认费率':`自 ${data.rates.from} 起生效`}</p></div>{canEdit&&<button className="button" onClick={()=>setEditing({...data.rates,from:data.today})}><Pencil size={15}/>修改费率</button>}</div>
        <dl>{rateFields.map(([key,label])=><div key={key}><dt>{label}</dt><dd>{data.rates[key]}</dd></div>)}<div><dt>美元兑人民币</dt><dd>{data.fx.usd_cny.toFixed(4)}<small>{fxSources[data.fx.source]||data.fx.source}{data.fx.day?` · ${data.fx.day}`:''}</small></dd></div></dl>
      </section></div>
      {data.unattributed&&data.unattributed.total>0&&<section className="statistics-panel costs-unattributed"><div className="statistics-section-heading"><div><h2>无法归属到订单的费用</h2><p>同期发生但对不上具体订单的费用（测试调用、早期重试时没有保存编号的请求、未分摊的共用费用），不计入上面的订单合计</p></div><strong>{yuan(data.unattributed.total)}</strong></div><div className="costs-unattributed-list">{categories.filter(c=>data.unattributed!.categories[c]>0).map(c=><span key={c}>{categoryLabels[c]} <b>{yuan(data.unattributed!.categories[c])}</b></span>)}</div></section>}
      {data.agiso_check&&data.agiso_check.balance!==null&&<section className="statistics-panel costs-unattributed"><div className="statistics-section-heading"><div><h2>阿奇索余额校准</h2><p>每天记录一次开放平台余额，用余额实际下降额核对按单价计算的费用（有充值的时段不计）</p></div><strong>余额 {yuan(data.agiso_check.balance)}</strong></div><div className="costs-unattributed-list"><span>记录日期 <b>{data.agiso_check.balance_day}</b></span><span>可比天数 <b>{data.agiso_check.days}</b></span><span>余额下降 <b>{yuan(data.agiso_check.balance_drop,3)}</b></span><span>按单价计算 <b>{yuan(data.agiso_check.computed,3)}</b></span><span>实际 ÷ 计算 <b>{data.agiso_check.ratio===null?'数据不足':data.agiso_check.ratio.toFixed(2)}</b></span></div></section>}
      <section className="statistics-panel"><div className="statistics-section-heading"><div><h2>订单成本明细</h2><p>包装、快递、物料在发货时计入，已提交未发货的订单显示为“预计”；阿奇索、OSS、ESA 中对不上具体订单的共用费用按月平均分到当月订单（鼠标停在合计上可看平摊金额）</p></div></div>
        {data.orders.length?<div className="statistics-table-wrap costs-table"><table><thead><tr><th>订单</th><th>状态</th><th>印刷 / 物料</th>{categories.map(c=><th key={c}>{categoryLabels[c]}</th>)}<th>合计</th></tr></thead><tbody>{data.orders.map(row=><tr key={row.id}><th scope="row">{row.order_number}<small className="statistics-username">{PLATFORM_LABELS[row.platform]}{row.shop_name?` · ${row.shop_name}`:''} · {row.created}</small></th><td>{stateLabels[row.state]}{row.fixed_basis==='estimate'&&<small className="costs-estimate">预计</small>}</td><td>{row.printed} 张 / {row.sheets} 张</td>{categories.map(c=><td key={c} title={c==='generation'&&row.requests?`${row.requests} 次 FAL 请求`:c==='cutout'&&row.cutouts?`${row.cutouts} 次成功抠图`:undefined}>{row.costs[c]?row.costs[c].toFixed(c==='agiso'?3:2):'—'}</td>)}<td title={row.allocated?`含平摊的共用费用 ¥${row.allocated.toFixed(4)}`:undefined}><strong>{row.total.toFixed(2)}</strong></td></tr>)}</tbody></table></div>:<Empty title="所选范围内没有订单" description="调整时间或平台后再查看。"/>}
      </section>
    </>}
    {editing&&<Modal title="修改成本费率" onClose={()=>{if(!saving)setEditing(null)}}><p className="hint">保存为一个新的费率版本，从生效日期起计算；之前日期的订单仍按原费率。</p><div className="form-grid"><label className="field">生效日期<input type="date" aria-label="费率生效日期" value={editing.from} onChange={e=>setEditing({...editing,from:e.target.value})}/></label>{rateFields.map(([key,label,step])=><label className="field" key={key}>{label}<input type="number" aria-label={label} min={key==='per_sheet'?1:0} step={step} value={editing[key]} onChange={e=>setEditing({...editing,[key]:Number(e.target.value)})}/></label>)}</div><div className="modal-footer"><button className="button" disabled={saving} onClick={()=>setEditing(null)}>返回</button><button className="button primary" disabled={saving||!editing.from} onClick={()=>void saveRates()}>{saving&&<Spinner/>}保存费率</button></div></Modal>}
  </div>
}
