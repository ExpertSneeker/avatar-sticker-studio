import { useEffect, useRef, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { Check, X } from 'lucide-react'
import { Modal } from './UI'
import { acknowledgeGuide, guideHidden, muteGuide, subscribeGuide } from '../lib/guide'
import correct from '../assets/guide/correct.webp'
import blurry from '../assets/guide/blurry.webp'
import covered from '../assets/guide/covered.webp'
import blended from '../assets/guide/blended.webp'

export interface GuideStep {id:string;target:string;text:ReactNode;when?:boolean}

const PAD=6,GAP=12
function findTarget(selector:string):HTMLElement|null{
  for(const element of Array.from(document.querySelectorAll<HTMLElement>(selector))){
    const rect=element.getBoundingClientRect()
    if(rect.width>0&&rect.height>0)return element
  }
  return null
}
const sameRect=(a:DOMRect|null,b:DOMRect)=>!!a&&a.top===b.top&&a.left===b.left&&a.width===b.width&&a.height===b.height

// Spotlights one button at a time: everything else dims, the bubble explains it, and the highlighted
// button itself stays clickable (pressing it counts as "我知道了"). Steps show in order, each only
// once its target is on the page, so the tour follows the customer through the flow.
export function GuideTour({steps,paused=false}:{steps:GuideStep[];paused?:boolean}){
  const stepsRef=useRef(steps);stepsRef.current=steps
  const [tick,setTick]=useState(0)
  const [active,setActive]=useState<{step:GuideStep;element:HTMLElement}|null>(null)
  const [rect,setRect]=useState<DOMRect|null>(null)
  const activeRef=useRef(active);activeRef.current=active
  const okRef=useRef<HTMLButtonElement>(null)
  useEffect(()=>subscribeGuide(()=>setTick(value=>value+1)),[])
  useEffect(()=>{
    if(paused){setActive(null);return}
    const pick=()=>{
      let next:{step:GuideStep;element:HTMLElement}|null=null
      for(const step of stepsRef.current){
        if(step.when===false||guideHidden(step.id))continue
        const element=findTarget(step.target)
        if(element){next={step,element};break}
      }
      const current=activeRef.current
      if(!next){if(current)setActive(null);return}
      if(current?.step.id===next.step.id&&current.element===next.element){if(current.step!==next.step)setActive(next);return}
      if(current?.step.id!==next.step.id)next.element.scrollIntoView({block:'center',behavior:'smooth'})
      setActive(next)
    }
    pick()
    const timer=setInterval(pick,500)
    return()=>clearInterval(timer)
  },[paused,tick])
  useEffect(()=>{
    if(!active)return
    let frame=0
    const follow=()=>{const next=active.element.getBoundingClientRect();setRect(previous=>sameRect(previous,next)?previous:next);frame=requestAnimationFrame(follow)}
    follow()
    const clicked=(event:MouseEvent)=>{if(event.target instanceof Node&&active.element.contains(event.target))acknowledgeGuide(active.step.id)}
    document.addEventListener('click',clicked,true)
    okRef.current?.focus({preventScroll:true})
    return()=>{cancelAnimationFrame(frame);document.removeEventListener('click',clicked,true)}
  },[active])
  if(!active||!rect)return null
  const vw=window.innerWidth,vh=window.innerHeight
  const hole={top:rect.top-PAD,left:rect.left-PAD,width:rect.width+PAD*2,height:rect.height+PAD*2}
  const bottom=hole.top+hole.height,right=hole.left+hole.width,width=Math.min(360,vw-24)
  const left=Math.min(Math.max(hole.left+hole.width/2-width/2,12),vw-width-12)
  const below=vh-bottom>=210||hole.top<210
  const place=below?{top:Math.min(bottom+GAP,vh-210),left,width}:{bottom:vh-hole.top+GAP,left,width}
  const block=(style:React.CSSProperties)=><div className="guide-shade" style={style} onClick={event=>event.stopPropagation()}/>
  return createPortal(<div className="guide-layer">
    {block({top:0,left:0,width:vw,height:Math.max(hole.top,0)})}
    {block({top:bottom,left:0,width:vw,height:Math.max(vh-bottom,0)})}
    {block({top:hole.top,left:0,width:Math.max(hole.left,0),height:hole.height})}
    {block({top:hole.top,left:right,width:Math.max(vw-right,0),height:hole.height})}
    <div className="guide-ring" style={hole}/>
    <div className="guide-bubble" role="dialog" aria-label="操作提示" style={place}>
      <div className="guide-text">{active.step.text}</div>
      <div className="guide-actions">
        <button type="button" className="text-button" onClick={()=>muteGuide(active.step.id)}>不再提示</button>
        <button type="button" ref={okRef} className="button primary" onClick={()=>acknowledgeGuide(active.step.id)}>我知道了</button>
      </div>
    </div>
  </div>,document.body)
}

const examples=[
  {src:correct,good:true,label:'正确示范',note:'头部完整、清楚、无遮挡'},
  {src:blurry,good:false,label:'错误示范 1',note:'照片模糊'},
  {src:covered,good:false,label:'错误示范 2',note:'脸部被遮挡'},
  {src:blended,good:false,label:'错误示范 3',note:'黑头发配黑背景，头发和背景融在一起'},
]
export const PHOTO_RULE='请上传头部清晰完整、无遮挡的照片，头发边缘要清晰，不要与背景融为一体'

export function PhotoExamples({large=false}:{large?:boolean}){
  return <div className={'guide-examples'+(large?' large':'')}>{examples.map(example=><figure key={example.label} className={example.good?'good':'bad'}>
    <div className="guide-example-image"><img src={example.src} alt={`${example.label}：${example.note}`} loading="lazy"/><span className="guide-mark" aria-hidden="true">{example.good?<Check size={large?44:32} strokeWidth={3.5}/>:<X size={large?44:32} strokeWidth={3.5}/>}</span></div>
    <figcaption><strong>【{example.label}】</strong>{example.note}</figcaption>
  </figure>)}</div>
}

// Shown in the upload section; once a photo is uploaded it folds into a single line that still opens.
export function PhotoRules({compact}:{compact:boolean}){
  const body=<><p className="guide-rule">{PHOTO_RULE}</p><PhotoExamples/></>
  return compact?<details className="guide-rules compact"><summary>查看拍照要求</summary>{body}</details>:<div className="guide-rules" role="note">{body}</div>
}

export const PHOTO_DIALOG='photo-rules-dialog'
// Opens every time before the photo picker until the customer chooses 不再提示.
export function PhotoRulesDialog({onPick,onClose}:{onPick:()=>void;onClose:()=>void}){
  return <Modal title="上传前请对照示范" onClose={onClose} wide className="guide-photo-dialog">
    <p className="guide-rule">{PHOTO_RULE}</p>
    <PhotoExamples large/>
    <ol className="guide-checklist"><li>整个头和头发都在照片里</li><li>照片清楚、不模糊</li><li>没有手、口罩、墨镜挡住脸</li><li>头发和背景颜色区别明显</li></ol>
    <div className="modal-footer"><button type="button" className="button" onClick={()=>{muteGuide(PHOTO_DIALOG);onPick()}}>不再提示</button><button type="button" className="button primary" onClick={onPick}>我知道了，去选照片</button></div>
  </Modal>
}
