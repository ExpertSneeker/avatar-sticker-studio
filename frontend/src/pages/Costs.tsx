import { useEffect, useState } from 'react'
import { Download, Pencil, RefreshCw } from 'lucide-react'
import { api } from '../lib/api'
import { PLATFORM_KEYS, PLATFORM_LABELS, type PlatformKey } from '../lib/agiso'
import { stateLabels, type OrderState } from '../lib/customer-orders'
import { Empty, Modal, Spinner, useNotice } from '../components/UI'

type Category='packaging'|'shipping'|'material'|'generation'|'cutout'|'agiso'|'oss'|'esa'
interface Rates {from:string;packaging:number;shipping:number;sheet:number;per_sheet:number;cutout:number;agiso_base:number;agiso_high:number;agiso_increment:number
  oss_traffic:number;oss_traffic_idle:number;oss_storage:number;oss_requests:number;esa_traffic:number}
interface CostRow {id:string;order_number:string;state:OrderState;created:string;platform:PlatformKey;shop_id:string|null;shop_name:string;shipped_at:number|null;printed:number;sheets:number;fixed_basis:'actual'|'estimate'|null;cutouts:number;requests:number;allocated:number;costs:Record<Category,number>;physical:number;software:number;total:number}
export interface CostReport {date_from:string|null;date_to:string|null;today:string;scope:'global'|'organization';rates:Rates;rate_versions:Rates[]
  fx:{usd_cny:number;source:string;day:string|null;published?:string|null}
  shops:{id:string;name:string;platform:PlatformKey}[]
  summary:{orders:number;printed:number;sheets:number;total:number;physical:number;software:number;per_order:number;per_sticker:number;categories:Record<Category,number>}
  orders:CostRow[];unattributed?:{categories:Record<Category,number>;total:number}
  agiso_check?:{days:number;balance_drop:number;computed:number;ratio:number|null;balance:number|null;balance_day:string|null}}
export const categoryLabels:Record<Category,string>={packaging:'包装',shipping:'快递',material:'物料',generation:'生图',cutout:'抠图',agiso:'阿奇索',oss:'OSS',esa:'ESA 加速'}
// 现实成本: what ships and is cut; 软件成本: generation, Agiso and cloud services.
const groups:{key:'physical'|'software';label:string;categories:Category[]}[]=[
  {key:'physical',label:'现实成本',categories:['packaging','shipping','material','cutout']},
  {key:'software',label:'软件成本',categories:['generation','agiso','oss','esa']},
]
const categories=groups.flatMap(group=>group.categories)
const fxSources:Record<string,string>={cfets:'中国外汇交易中心中间价','open.er-api.com':'open.er-api.com',fallback:'默认值（尚未取得当日汇率）'}
const yuan=(value:number,digits=2)=>'¥'+value.toFixed(digits)
const pad=(n:number)=>String(n).padStart(2,'0')
const iso=(d:Date)=>`${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}`
const presets=[['this-month','本月'],['last-month','上月'],['30','最近 30 天'],['all','全部']] as const
function period(name:string):[string,string]{
  const now=new Date()
  if(name==='this-month')return [iso(new Date(now.getFullYear(),now.getMonth(),1)),iso(now)]
  if(name==='last-month')return [iso(new Date(now.getFullYear(),now.getMonth()-1,1)),iso(new Date(now.getFullYear(),now.getMonth(),0))]
  if(name==='30')return [iso(new Date(now.getTime()-29*86400000)),iso(now)]
  return ['','']
}
const rateFields:[keyof Rates,string,number][]=[['packaging','包装费（元/单）',0.01],['shipping','快递费（元/单）',0.01],['sheet','物料（元/张）',0.01],['per_sheet','每张物料可裁贴纸数',1],['cutout','抠图（元/次，成功才计费）',0.001],
  ['agiso_base','阿奇索基础档（元/次）',0.001],['agiso_high','阿奇索高级档（元/次）',0.001],['agiso_increment','阿奇索增值档（元/次）',0.001],
  ['oss_traffic','OSS 外网流出 8–24 点（元/GB）',0.01],['oss_traffic_idle','OSS 外网流出 0–8 点（元/GB）',0.01],['oss_storage','OSS 存储（元/GB·月）',0.01],['oss_requests','OSS 请求（元/万次）',0.001],['esa_traffic','ESA 流量（元/GB）',0.001]]

function csv(report:CostReport){
  const head=['订单号','创建日期','平台','店铺','状态','印刷张数','物料张数','包装/快递/物料',...groups.flatMap(g=>[...g.categories.map(c=>categoryLabels[c]),g.label+'小计']),'合计']
  const rows=report.orders.map(r=>[r.order_number,r.created,PLATFORM_LABELS[r.platform],r.shop_name,stateLabels[r.state],r.printed,r.sheets,r.fixed_basis==='estimate'?'预计':r.fixed_basis==='actual'?'实际':'',...groups.flatMap(g=>[...g.categories.map(c=>r.costs[c].toFixed(4)),r[g.key].toFixed(4)]),r.total.toFixed(4)])
  const s=report.summary
  const total=['合计','','','','',s.printed,s.sheets,'',...groups.flatMap(g=>[...g.categories.map(c=>s.categories[c].toFixed(4)),s[g.key].toFixed(4)]),s.total.toFixed(4)]
  return '﻿'+[head,...rows,total].map(line=>line.map(v=>`"${String(v).replace(/"/g,'""')}"`).join(',')).join('\r\n')
}

export function Costs({global=false,canEdit=false}:{global?:boolean;canEdit?:boolean}){
  const notice=useNotice()
  const [preset,setPreset]=useState('this-month'),[range,setRange]=useState<[string,string]>(()=>period('this-month'))
  const [platform,setPlatform]=useState<'all'|PlatformKey>('all'),[shop,setShop]=useState('all')
  const [data,setData]=useState<CostReport|null>(null),[loading,setLoading]=useState(true),[error,setError]=useState(''),[revision,setRevision]=useState(0)
  const [shops,setShops]=useState<CostReport['shops']>([])
  const [editing,setEditing]=useState<Rates|null>(null),[saving,setSaving]=useState(false)
  useEffect(()=>{
    const controller=new AbortController(),params=new URLSearchParams({scope:global?'global':'organization',offset:String(-new Date().getTimezoneOffset())})
    if(range[0])params.set('date_from',range[0]);if(range[1])params.set('date_to',range[1]);if(platform!=='all')params.set('platform',platform);if(shop!=='all')params.set('shop_id',shop)
    setLoading(true);setError('')
    api<CostReport>('/costs?'+params,{signal:controller.signal}).then(value=>{if(!controller.signal.aborted){setData(value);setShops(value.shops)}}).catch(e=>{if(!controller.signal.aborted)setError(e.message)}).finally(()=>{if(!controller.signal.aborted)setLoading(false)})
    return()=>controller.abort()
  },[global,range,platform,shop,revision])
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
  const choosePreset=(name:string)=>{setPreset(name);setRange(period(name))}
  const chooseDate=(next:[string,string])=>{setPreset('custom');setRange(next)}
  const shopOptions=shops.filter(s=>platform==='all'||s.platform===platform)
  const shopLabel=shop==='all'?'全部店铺':shop==='none'?'无关联店铺':shops.find(s=>s.id===shop)?.name||'所选店铺'
  const rangeLabel=range[0]||range[1]?`${range[0]||'最早'} 至 ${range[1]||'今天'}`:'全部日期'
  const summary=data?.summary,max=Math.max(0.0001,...categories.map(c=>summary?.categories[c]||0))
  return <div className="costs-view">
    <div className="statistics-toolbar costs-toolbar">
      <div className="tabs costs-presets" role="group" aria-label="快捷时间">{presets.map(([key,label])=><button key={key} type="button" className={preset===key?'active':''} onClick={()=>choosePreset(key)}>{label}</button>)}</div>
      <label className="statistics-period">开始<input type="date" aria-label="成本开始日期" value={range[0]} max={range[1]||undefined} onChange={e=>chooseDate([e.target.value,range[1]])}/></label>
      <label className="statistics-period">结束<input type="date" aria-label="成本结束日期" value={range[1]} min={range[0]||undefined} onChange={e=>chooseDate([range[0],e.target.value])}/></label>
      <label className="statistics-period">平台<select aria-label="成本平台" value={platform} onChange={e=>{setPlatform(e.target.value as 'all'|PlatformKey);setShop('all')}}><option value="all">全部平台</option>{PLATFORM_KEYS.map(key=><option key={key} value={key}>{PLATFORM_LABELS[key]}</option>)}</select></label>
      <label className="statistics-period">店铺<select aria-label="成本店铺" value={shop} onChange={e=>setShop(e.target.value)}><option value="all">全部店铺</option><option value="none">无关联店铺</option>{shopOptions.map(s=><option key={s.id} value={s.id}>{PLATFORM_LABELS[s.platform]} · {s.name||s.id}</option>)}</select></label>
      <div className="costs-toolbar-actions"><button className="button" disabled={loading} onClick={()=>setRevision(v=>v+1)}><RefreshCw size={16}/>刷新</button><button className="button" disabled={!data?.orders.length} onClick={exportCsv}><Download size={16}/>导出 CSV</button></div></div>
    {loading?<div className="statistics-loading" role="status"><Spinner/>正在计算成本</div>:error?<div className="error-banner" role="alert">{error}</div>:data&&summary&&<>
      <section className="statistics-panel costs-total" aria-label="当前筛选的总计"><p className="costs-filter-label">当前筛选：{rangeLabel} · {platform==='all'?'全部平台':PLATFORM_LABELS[platform]} · {shopLabel} · {summary.orders} 个订单（按订单创建日期，订单的全部成本都计入）</p>
        <div className="costs-total-grid"><div className="costs-total-main"><span>总计</span><strong>{yuan(summary.total)}</strong></div>
          {groups.map(g=><div key={g.key}><span>{g.label}</span><strong>{yuan(summary[g.key])}</strong><small>{g.categories.map(c=>categoryLabels[c]).join(' / ')}</small></div>)}
          <div><span>单均成本</span><strong>{yuan(summary.per_order)}</strong><small>总计 ÷ {summary.orders} 个订单</small></div>
          <div><span>每张贴纸成本</span><strong>{yuan(summary.per_sticker,3)}</strong><small>印刷 {summary.printed} 张 · 物料 {summary.sheets} 张</small></div></div></section>
      <div className="statistics-panels"><section className="statistics-panel"><div className="statistics-section-heading"><div><h2>成本构成</h2><p>当前筛选订单的各项合计</p></div></div>
        {groups.map(g=><div className="costs-group" key={g.key}><h3>{g.label}<span>{yuan(summary[g.key])}</span></h3>{g.categories.map(c=><div className="costs-category" key={c}><span>{categoryLabels[c]}</span><div className="costs-category-bar"><i style={{width:`${(summary.categories[c]/max)*100}%`}}/></div><strong>{yuan(summary.categories[c])}</strong><small>{summary.total?(100*summary.categories[c]/summary.total).toFixed(1):'0.0'}%</small></div>)}</div>)}
      </section><section className="statistics-panel costs-rates"><div className="statistics-section-heading"><div><h2>费率</h2><p>{data.rates.from==='1970-01-01'?'默认费率':`自 ${data.rates.from} 起生效`} · OSS、ESA 按量付费价格</p></div>{canEdit&&<button className="button" onClick={()=>setEditing({...data.rates,from:data.today})}><Pencil size={15}/>修改费率</button>}</div>
        <dl>{rateFields.map(([key,label])=><div key={key}><dt>{label}</dt><dd>{data.rates[key]}</dd></div>)}<div><dt>美元兑人民币</dt><dd>{data.fx.usd_cny.toFixed(4)}<small>{fxSources[data.fx.source]||data.fx.source}{data.fx.day?` · ${data.fx.day}`:''}</small></dd></div></dl>
      </section></div>
      {data.unattributed&&data.unattributed.total>0&&<section className="statistics-panel costs-unattributed"><div className="statistics-section-heading"><div><h2>无法归属到订单的费用</h2><p>同期发生但对不上具体订单的费用（测试调用、早期重试时没有保存编号的请求、当月没有订单的共用费用），不计入上面的总计</p></div><strong>{yuan(data.unattributed.total)}</strong></div><div className="costs-unattributed-list">{categories.filter(c=>data.unattributed!.categories[c]>0).map(c=><span key={c}>{categoryLabels[c]} <b>{yuan(data.unattributed!.categories[c])}</b></span>)}</div></section>}
      {data.agiso_check&&data.agiso_check.balance!==null&&<section className="statistics-panel costs-unattributed"><div className="statistics-section-heading"><div><h2>阿奇索余额校准</h2><p>每天记录一次开放平台余额，用余额实际下降额核对按单价计算的费用（有充值的时段不计）</p></div><strong>余额 {yuan(data.agiso_check.balance)}</strong></div><div className="costs-unattributed-list"><span>记录日期 <b>{data.agiso_check.balance_day}</b></span><span>可比天数 <b>{data.agiso_check.days}</b></span><span>余额下降 <b>{yuan(data.agiso_check.balance_drop,3)}</b></span><span>按单价计算 <b>{yuan(data.agiso_check.computed,3)}</b></span><span>实际 ÷ 计算 <b>{data.agiso_check.ratio===null?'数据不足':data.agiso_check.ratio.toFixed(2)}</b></span></div></section>}
      <section className="statistics-panel"><div className="statistics-section-heading"><div><h2>订单成本明细</h2><p>包装、快递、物料在发货时计入，已提交未发货的订单显示为“预计”；阿奇索、OSS、ESA 中对不上具体订单的共用费用按月平均分到当月订单（鼠标停在合计上可看平摊金额）</p></div></div>
        {data.orders.length?<div className="statistics-table-wrap costs-table"><table><thead><tr><th rowSpan={2}>订单</th><th rowSpan={2}>状态</th><th rowSpan={2}>印刷 / 物料</th>{groups.map(g=><th key={g.key} colSpan={g.categories.length+1} className="costs-group-head">{g.label}</th>)}<th rowSpan={2}>合计</th></tr>
          <tr>{groups.flatMap(g=>[...g.categories.map(c=><th key={c}>{categoryLabels[c]}</th>),<th key={g.key} className="costs-subtotal">小计</th>])}</tr></thead>
          <tbody>{data.orders.map(row=><tr key={row.id}><th scope="row">{row.order_number}<small className="statistics-username">{PLATFORM_LABELS[row.platform]}{row.shop_name?` · ${row.shop_name}`:''} · {row.created}</small></th><td>{stateLabels[row.state]}{row.fixed_basis==='estimate'&&<small className="costs-estimate">预计</small>}</td><td>{row.printed} 张 / {row.sheets} 张</td>
            {groups.flatMap(g=>[...g.categories.map(c=><td key={c} title={c==='generation'&&row.requests?`${row.requests} 次 FAL 请求`:c==='cutout'&&row.cutouts?`${row.cutouts} 次成功抠图`:undefined}>{row.costs[c]?row.costs[c].toFixed(c==='agiso'||c==='oss'||c==='esa'?3:2):'—'}</td>),<td key={g.key} className="costs-subtotal">{row[g.key].toFixed(2)}</td>])}
            <td title={row.allocated?`含平摊的共用费用 ¥${row.allocated.toFixed(4)}`:undefined}><strong>{row.total.toFixed(2)}</strong></td></tr>)}</tbody>
          <tfoot><tr><th scope="row">合计（{summary.orders} 单）</th><td/><td>{summary.printed} 张 / {summary.sheets} 张</td>{groups.flatMap(g=>[...g.categories.map(c=><td key={c}>{summary.categories[c].toFixed(2)}</td>),<td key={g.key} className="costs-subtotal">{summary[g.key].toFixed(2)}</td>])}<td><strong>{summary.total.toFixed(2)}</strong></td></tr></tfoot></table></div>:<Empty title="当前筛选下没有订单" description="调整时间、平台或店铺后再查看。"/>}
      </section>
    </>}
    {editing&&<Modal title="修改成本费率" onClose={()=>{if(!saving)setEditing(null)}}><p className="hint">保存为一个新的费率版本，从生效日期起计算；之前日期的成本仍按原费率。OSS、ESA 按用量 × 按量付费价格计算。</p><div className="form-grid"><label className="field">生效日期<input type="date" aria-label="费率生效日期" value={editing.from} onChange={e=>setEditing({...editing,from:e.target.value})}/></label>{rateFields.map(([key,label,step])=><label className="field" key={key}>{label}<input type="number" aria-label={label} min={key==='per_sheet'?1:0} step={step} value={editing[key]} onChange={e=>setEditing({...editing,[key]:Number(e.target.value)})}/></label>)}</div><div className="modal-footer"><button className="button" disabled={saving} onClick={()=>setEditing(null)}>返回</button><button className="button primary" disabled={saving||!editing.from} onClick={()=>void saveRates()}>{saving&&<Spinner/>}保存费率</button></div></Modal>}
  </div>
}
