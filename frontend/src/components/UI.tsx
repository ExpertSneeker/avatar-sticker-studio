import { previewUrl } from '../lib/preview'
import { createContext, useContext, useEffect, useId, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { X, LoaderCircle, ImagePlus, Check, Minus, Plus, Search } from 'lucide-react'
import type { PrintSettings, TemplateSet } from '../lib/types'

export const NoticeContext=createContext<(message:string,kind?:'success'|'error')=>void>(()=>{})
export const useNotice=()=>useContext(NoticeContext)
export function Brand({compact=false}:{compact?:boolean}) {
  return <div className="brand"><svg width="34" height="34" viewBox="0 0 34 34" fill="none" aria-hidden="true"><rect width="34" height="34" rx="11" fill="currentColor"/><path d="M8 18c0-5 4-9 9-9 5 0 9 4 9 9v1a9 9 0 0 1-18 0v-1Z" fill="white"/><path d="m11 10 6-5 4 7-10-2Z" fill="white"/><circle cx="14" cy="18" r="1" fill="currentColor"/><circle cx="21" cy="18" r="1" fill="currentColor"/><path d="M15 22q2.5 2 5 0" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round"/></svg>{!compact&&<span>头像贴纸</span>}</div>
}
export function Spinner(){return <LoaderCircle size={16} className="spin" aria-label="正在处理"/>}
export function Empty({title,description,children}:{title:string;description?:string;children?:ReactNode}) {
  return <div className="empty"><span className="empty-icon"><ImagePlus size={28} strokeWidth={1.3}/></span><h3>{title}</h3>{description&&<p>{description}</p>}{children}</div>
}
export function Modal({title,children,onClose,wide=false}:{title:string;children:ReactNode;onClose:()=>void;wide?:boolean}) {
  const ref=useRef<HTMLDivElement>(null), id=useId(), closeRef=useRef(onClose)
  closeRef.current=onClose
  useEffect(()=>{
    const previous=document.activeElement as HTMLElement
    const controls=()=>Array.from(ref.current?.querySelectorAll<HTMLElement>('button:not(:disabled),input:not(:disabled),select,textarea,[tabindex="0"]')||[])
    controls()[0]?.focus()
    const key=(event:KeyboardEvent)=>{
      if(event.key==='Escape') closeRef.current()
      if(event.key==='Tab') {
        const elements=controls(),first=elements[0],last=elements.at(-1)
        if(event.shiftKey && document.activeElement===first){event.preventDefault();last?.focus()}
        if(!event.shiftKey && document.activeElement===last){event.preventDefault();first?.focus()}
      }
    }
    document.addEventListener('keydown',key);const old=document.body.style.overflow;document.body.style.overflow='hidden'
    return ()=>{document.removeEventListener('keydown',key);document.body.style.overflow=old;previous?.focus()}
  },[])
  return <div className="modal-backdrop" onMouseDown={e=>{if(e.target===e.currentTarget)onClose()}}><div className={'modal '+(wide?'modal-wide':'')} role="dialog" aria-modal="true" aria-labelledby={id} ref={ref}><div className="modal-head"><h2 id={id}>{title}</h2><button className="icon-button" onClick={onClose} aria-label="关闭"><X size={20}/></button></div>{children}</div></div>
}
export const statusNames:Record<string,string>={queued:'排队中',pending:'待处理',processing:'生成中',running:'生成中',generating:'生成中',completed:'已完成',complete:'已完成',ready:'已完成',failed:'需处理',partial:'部分完成',unknown:'结果待确认',paused:'已暂停',repacking:'正在排版',archived:'已归档'}
export function Status({value}:{value:string}) {return <span className={'status status-'+value}><i/>{statusNames[value]||value}</span>}
export function PrintFields({value,onChange}:{value:PrintSettings;onChange:(value:PrintSettings)=>void}) {
  const field=(key:keyof PrintSettings,label:string,min:number,max:number)=><label className="field">{label}<div className="unit-input"><input type="number" min={min} max={max} step="1" value={Number(value[key])} onChange={e=>onChange({...value,[key]:Number(e.target.value)})}/><span>mm</span></div></label>
  return <div className="print-fields"><div className="field"><span>纸张</span><div className="segmented"><button type="button" className={value.paper_width_mm===210&&value.paper_height_mm===297?'selected':''} onClick={()=>onChange({...value,paper_width_mm:210,paper_height_mm:297})}>A4</button><button type="button" className={value.paper_width_mm===297&&value.paper_height_mm===420?'selected':''} onClick={()=>onChange({...value,paper_width_mm:297,paper_height_mm:420})}>A3</button><span>也可自定义</span></div></div><div className="form-grid">{field('paper_width_mm','纸张宽度',50,600)}{field('paper_height_mm','纸张高度',50,600)}{field('long_edge_mm','单张内容长边',10,300)}{field('margin_mm','页边距',0,80)}{field('gap_mm','图片间距',0,80)}<label className="field">打印分辨率<select value={value.dpi} onChange={e=>onChange({...value,dpi:Number(e.target.value)})}><option value={300}>300 DPI</option><option value={150}>150 DPI</option><option value={600}>600 DPI</option></select></label></div><label className="check-line"><input type="checkbox" checked={value.brightness} onChange={e=>onChange({...value,brightness:e.target.checked})}/>亮度优化<span>用于偏暗图片</span></label><label className="check-line"><input type="checkbox" checked={value.color_balance} onChange={e=>onChange({...value,color_balance:e.target.checked})}/>打印色彩平衡<span>保留透明边缘</span></label><p className="hint">按有效内容等比排版。纸张装不下时会提示调整，不会缩小图片来凑数。</p></div>
}
export function TemplateChooser({templates,value,onChange}:{templates:TemplateSet[];value:string[];onChange:(value:string[])=>void}) {
  const [search,setSearch]=useState('')
  const available=templates.filter(t=>t.active)
  const query=search.trim().toLocaleLowerCase()
  const filtered=available.filter(set=>(set.name+' '+set.code).toLocaleLowerCase().includes(query))
  if(!available.length)return <Empty title="还没有可用模板" description="管理员上传一套 12 张模板并上架后，即可开始制作。"/>
  return <>
    <div className="template-search-bar">
      <label className="search-input"><Search size={16}/><input aria-label="搜索模板套装" placeholder="搜索模板名称或编号" value={search} onChange={e=>setSearch(e.target.value)}/></label>
      {search&&<button className="text-button" onClick={()=>setSearch('')}>清空搜索</button>}
      <span className="hint">找到 {filtered.length} 套</span>
    </div>
    {filtered.length?<div className="template-picker">{filtered.map(set=><button type="button" key={set.id} className={'template-option '+(value.includes(set.id)?'selected':'')} onClick={()=>onChange(value.includes(set.id)?value.filter(id=>id!==set.id):[...value,set.id])}><div className="set-mosaic">{set.images.slice(0,4).map(im=><img key={im.id} src={previewUrl(im.url)} alt=""/>)}</div><div><strong>{set.name}</strong><span>{set.code} · 12 张</span></div><span className="pick-check">{value.includes(set.id)?<Check size={16}/>:<Plus size={16}/>}</span></button>)}</div>:<Empty title="没有匹配的模板套装" description="试试其他名称或编号；已选套装会保留。"/>}
  </>
}
export function Progress({value,total}:{value:number;total:number}) {return <div className="progress-track"><span style={{transform:`scaleX(${total?Math.min(1,value/total):0})`}}/></div>}
export function Counter({value,onChange,min=1,max=100}:{value:number;onChange:(n:number)=>void;min?:number;max?:number}) {return <div className="counter"><button type="button" onClick={()=>onChange(Math.max(min,value-1))} aria-label="减少"><Minus size={14}/></button><input type="number" min={min} max={max} value={value} onChange={e=>onChange(Number(e.target.value))}/><button type="button" onClick={()=>onChange(Math.min(max,value+1))} aria-label="增加"><Plus size={14}/></button></div>}
