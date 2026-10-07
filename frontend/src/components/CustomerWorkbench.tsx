import { useEffect, useRef, useState } from 'react'
import { ArrowLeft, Check, ImagePlus, Minus, Plus, RefreshCw, Trash2, ZoomIn } from 'lucide-react'
import { api, ApiError } from '../lib/api'
import { searchMatcher } from '../lib/search'
import { uploadFile } from '../lib/upload'
import { guestUpload } from '../lib/guest-upload'
import { guestApi, canApplySelection, draftChoices, pruneChoices, categoryOptions, mediaSrcSet, pickerImageSizes, zoomUrl, OrderMutations, quantityIds, selectionCounts, selectionQuantityLimit, selectionError, slotBusy, stateLabels, submissionError } from '../lib/customer-orders'
import type { AvatarChoice, CustomerLibrary, CustomerSlot, GuestOrder, LibrarySticker, LibraryTemplate, OrderDraft, Preflight } from '../lib/customer-orders'
import { Empty, Modal, Spinner, Status } from './UI'
import { visiblePolling } from '../lib/polling'
import { guideHidden } from '../lib/guide'
import { GuideTour, PhotoRules, PhotoRulesDialog, PHOTO_DIALOG, type GuideStep } from './GuestGuide'
import '../pages/CustomerOrders.css'

type DraftAvatar=AvatarChoice&{name:string;preview_url:string}
export function CustomerWorkbench({initial,mode,library,onChange,onBack}:{initial:GuestOrder;mode:'guest'|'staff';library:CustomerLibrary;onChange?:(order:GuestOrder)=>void;onBack?:()=>void}){
  const [order,setOrder]=useState(initial),[avatars,setAvatars]=useState<DraftAvatar[]>(()=>initial.state==='draft'?draftChoices(initial.draft,library):[])
  const [busy,setBusy]=useState(''),[error,setError]=useState(''),[uploadProgress,setUploadProgress]=useState(0)
  const [picker,setPicker]=useState<string|null>(null),[preflight,setPreflight]=useState<Preflight|null>(null)
  const [resultZoom,setResultZoom]=useState<{title:string;url:string}|null>(null)
  const [comparison,setComparison]=useState<string|null>(null),[selection,setSelection]=useState<string[]>([]),[submitOpen,setSubmitOpen]=useState(false)
  const [photoDialog,setPhotoDialog]=useState(false),fileInput=useRef<HTMLInputElement>(null),guide=mode==='guest'
  const requestVersion=useRef(0),lock=useRef(false),mutations=useRef(new OrderMutations()),session=useRef(new AbortController())
  const base=mode==='guest'?'/order':'/customer-orders/'+encodeURIComponent(initial.id)
  const avatarsRef=useRef(avatars);avatarsRef.current=avatars
  const orderRef=useRef(order);orderRef.current=order
  const pickerRef=useRef(picker);pickerRef.current=picker
  const libraryRef=useRef(library);libraryRef.current=library
  // Avatars and choices are saved to the order on every change (last save wins), so a reload, another
  // device or staff see the same working list. Failed saves retry on the next poll.
  const [saveError,setSaveError]=useState('')
  const draftRevision=useRef(initial.draft?.revision??0),draftSaving=useRef(false),draftDirty=useRef(false),draftRetry=useRef(true)
  function adoptDraft(draft:OrderDraft){
    if(draft.revision>draftRevision.current&&!draftSaving.current&&!draftDirty.current&&!pickerRef.current){
      draftRevision.current=draft.revision;setAvatars(draftChoices(draft,libraryRef.current));setPreflight(null);return
    }
    // Same draft: refresh image links only (they change with the watermark).
    const links=new Map(draft.avatars.map(a=>[a.upload_id,a.preview_url||'']))
    setAvatars(previous=>previous.some(a=>links.get(a.upload_id)&&links.get(a.upload_id)!==a.preview_url)?previous.map(a=>({...a,preview_url:links.get(a.upload_id)||a.preview_url})):previous)
  }
  function changeAvatars(next:DraftAvatar[]){avatarsRef.current=next;setAvatars(next);setPreflight(null);draftDirty.current=true;draftRetry.current=true;void saveDraft()}
  async function saveDraft(){
    const current=orderRef.current
    if(draftSaving.current||!draftDirty.current||current.state!=='draft'||current.paused)return
    draftSaving.current=true;draftDirty.current=false
    let retryNow=false
    try{
      const body=JSON.stringify({avatars:avatarsRef.current.map(({upload_id,template_ids,sticker_ids})=>({upload_id,template_ids,sticker_ids}))})
      const next=mode==='guest'?await guestApi<GuestOrder>(base+'/draft',{method:'PUT',body}):await api<GuestOrder>(base+'/draft',{method:'PUT',body})
      if(session.current.signal.aborted)return
      setSaveError('')
      if(next.draft){
        draftRevision.current=next.draft.revision
        // Adopt the server's cleaned copy unless newer local changes are waiting to be saved.
        if(!draftDirty.current){const saved=draftChoices(next.draft,libraryRef.current);avatarsRef.current=saved;setAvatars(saved)}
      }
      accept(next);retryNow=draftDirty.current
    }catch(e){
      if(session.current.signal.aborted)return
      // Server errors and lost connections retry on the next poll; a rejected list waits for the next change.
      draftDirty.current=true;draftRetry.current=!(e instanceof ApiError&&e.status<500)
      setSaveError(`头像和选择暂未保存，${draftRetry.current?'正在自动重试':'请调整后重试'}：${(e as Error).message}`)
    }finally{draftSaving.current=false;if(retryNow)void saveDraft()}
  }
  const changeRef=useRef(onChange);changeRef.current=onChange
  function accept(next:GuestOrder){if(next.state==='draft'&&next.draft)adoptDraft(next.draft);setOrder(previous=>next.state==='cancelled'||(next.version??0)>=(previous.version??0)?next:previous);if(next.state==='cancelled'||next.state==='submitted'){setAvatars([]);setSelection([]);setComparison(null);setPicker(null);setPreflight(null);setSubmitOpen(false)}if(next.paused){setComparison(null);setPicker(null);setPreflight(null);setSubmitOpen(false)}changeRef.current?.(next)}
  async function refresh(){const signal=session.current.signal,revision=++requestVersion.current;const next=mode==='guest'?await guestApi<GuestOrder>(base,{signal}):await api<GuestOrder>(base,{signal});if(!signal.aborted&&revision===requestVersion.current){accept(next)}}
  useEffect(()=>{
    const controller=new AbortController();session.current=controller
    let fetching=false
    const poll=async()=>{if(draftDirty.current&&draftRetry.current)void saveDraft();if(fetching||lock.current)return;fetching=true;try{await refresh()}catch(e){if(!controller.signal.aborted)setError((e as Error).message)}finally{fetching=false}}
    const stop=visiblePolling(()=>void poll(),2500)
    return()=>{stop();controller.abort()}
  },[base,mode])
  useEffect(()=>{if(initial.state==='cancelled'&&order.state!=='cancelled'||(initial.version??0)>(order.version??0))accept(initial)},[initial,order.version])
  // Once the library arrives, drop saved choices it no longer offers and save the cleaned list.
  useEffect(()=>{
    const pruned=pruneChoices(avatarsRef.current,library)
    if(pruned.some((a,i)=>a.template_ids.length!==avatarsRef.current[i].template_ids.length||a.sticker_ids.length!==avatarsRef.current[i].sticker_ids.length))changeAvatars(pruned)
  },[library])
  const counts=selectionCounts(avatars,library),draftError=selectionError(order,counts)
  const finalError=submissionError(order,selection)
  const compared=order.slots?.find(slot=>slot.id===comparison)
  const rerunsUsed=(order.slots||[]).reduce((total,slot)=>total+(slot.reruns_used||0)+(slot.reruns_reserved||0),0)
  async function mutate(path:string,payload:Record<string,unknown>={}){
    if(lock.current||order.paused)return false
    lock.current=true;requestVersion.current++;setBusy(path);setError('')
    try{const next=await mutations.current.run<GuestOrder>(mode,base,path,order.version??0,payload);if(!session.current.signal.aborted){accept(next);setPreflight(null);setSubmitOpen(false)}return true}
    catch(e){if(!session.current.signal.aborted){setError((e as Error).message);try{await refresh()}catch{}}return false}
    finally{lock.current=false;if(!session.current.signal.aborted)setBusy('')}
  }
  async function retryPending(){
    if(lock.current||order.paused||!mutations.current.pendingPath)return
    const path=mutations.current.pendingPath
    lock.current=true;requestVersion.current++;setBusy('retry');setError('')
    try{const next=await mutations.current.retry<GuestOrder|Preflight>();if(!session.current.signal.aborted){if(path==='/preflight')setPreflight(next as Preflight);else{accept(next as GuestOrder);setPreflight(null);setSubmitOpen(false)}}}
    catch(e){if(!session.current.signal.aborted)setError((e as Error).message)}finally{lock.current=false;if(!session.current.signal.aborted)setBusy('')}
  }
  async function upload(files:FileList|null){
    if(!files?.length||lock.current||order.paused)return
    if(avatars.length+files.length>order.final_count){setError(`最多上传 ${order.final_count} 个头像`);return}
    lock.current=true;setBusy('upload');setError('')
    try{
      for(const file of Array.from(files)){
        setUploadProgress(0)
        const result=mode==='guest'?await guestUpload(file,setUploadProgress,session.current.signal):await uploadFile(file,setUploadProgress,session.current.signal)
        session.current.signal.throwIfAborted()
        const url='preview_url' in result?result.preview_url:'url' in result?result.url:''
        if(!avatarsRef.current.some(a=>a.upload_id===result.id))changeAvatars([...avatarsRef.current,{upload_id:result.id,name:file.name,preview_url:url||'',template_ids:[],sticker_ids:[]}])
      }
    }catch(e){if(!session.current.signal.aborted)setError((e as Error).message)}finally{lock.current=false;if(!session.current.signal.aborted)setBusy('')}
  }
  async function check(){
    if(lock.current||order.paused)return
    lock.current=true;setBusy('preflight');setError('')
    try{const result=await mutations.current.run<Preflight>(mode,base,'/preflight',order.version??0,{avatars:avatars.map(({upload_id,template_ids,sticker_ids})=>({upload_id,template_ids,sticker_ids}))});if(!session.current.signal.aborted)setPreflight(result)}
    catch(e){if(!session.current.signal.aborted)setError((e as Error).message)}finally{lock.current=false;if(!session.current.signal.aborted)setBusy('')}
  }
  const allChosen=avatars.length>0&&avatars.every(a=>a.template_ids.length||a.sticker_ids.length),anyResult=!!order.slots?.some(slot=>slot.versions.length)
  const tour:GuideStep[]=order.state==='draft'?[
    {id:'upload-add',target:'[data-guide="add-avatar"]',when:avatars.length<order.final_count,text:<><strong>点这里上传头像照片。</strong>每个头像会单独做成贴纸，本订单最多上传 {order.final_count} 个。</>},
    {id:'avatar-pick',target:'[data-guide="pick-stickers"]',when:avatars.length>0,text:<><strong>给这个头像挑贴纸。</strong>每个头像都要选。</>},
    {id:'start-generate',target:'[data-guide="start-generate"]',when:allChosen,text:'全部选好后，点这里开始制作。'},
  ]:order.state==='review'?[
    {id:'result-select',target:'[data-guide="select-final"]',text:<><strong>从做好的贴纸里挑出要印刷的</strong>，点「选为成品」，一共要选 {order.final_count} 张。</>},
    {id:'selected-badge',target:'[data-guide="selected-badge"]',when:anyResult,text:<>这里显示已经选了几张，<strong>要正好选满 {order.final_count} 张</strong>才能提交。</>},
    {id:'result-zoom',target:'[data-guide="result-zoom"]',text:'点这里看大图。'},
    {id:'result-rerun',target:'[data-guide="result-rerun"]',when:order.rerun_limit>0,text:`哪张不满意，可以点这里重新生成。整单一共能重试 ${order.rerun_limit} 次，用完就没有了。`},
    {id:'submit',target:'[data-guide="submit"]',when:selection.length===order.final_count,text:<strong>都选好了，点这里提交印刷。</strong>},
  ]:[]
  function toggleSlot(id:string){setSelection(prev=>prev.includes(id)?prev.filter(value=>value!==id):prev.length<order.final_count?[...prev,id]:prev)}
  return <div className={'customer-workbench '+mode+'-workbench'}>
    <div className="page-heading"><div>{onBack&&<button className="text-button" onClick={onBack}><ArrowLeft size={16}/>返回订单</button>}<h1>订单 {order.order_number}</h1><p>{stateLabels[order.state]}{order.state!=='cancelled'&&` · 可提交印刷 ${order.final_count} 张 · 重试次数 ${rerunsUsed} / ${order.rerun_limit} 次`}</p></div><button className="button" disabled={!!busy} onClick={()=>void refresh().catch(e=>setError(e.message))}><RefreshCw size={16}/>刷新</button></div>
    {error&&<div className="error-banner" role="alert">{error}</div>}
    {saveError&&order.state==='draft'&&<div className="notice-banner" role="status">{saveError}</div>}
    {!order.paused&&mutations.current.pendingPath&&!busy&&<PendingMutation busy={!!busy} onRetry={()=>void retryPending()}/>}
    {order.state==='cancelled'?<Empty title="订单已取消" description="如需继续制作，请联系为你开单的工作人员。"/>:order.paused?<section className="settings-section" role="status"><h2>订单暂时暂停</h2><p>{order.hold_reason||'当前订单暂不能生成或提交，请联系店铺客服。'}</p>{order.preview_url&&<img className="customer-overview" src={order.preview_url} alt="已确认贴纸水印总览"/>}<div className="customer-results">{order.slots?.map(slot=>{const result=slot.versions.find(v=>v.id===slot.selected_version_id);return result?<img className="customer-paused-preview" key={slot.id} src={result.preview_url} alt={slot.sticker_code+' 水印预览'} loading="lazy"/>:null})}</div></section>:order.state==='submitted'?<section className="customer-submitted"><span className="submitted-check"><Check size={28}/></span><h2>已提交印刷</h2><p>已选 {order.final_count} 张贴纸。已提交印刷，不可修改。</p>{order.preview_url?<img className="customer-overview" src={order.preview_url} alt="已确认贴纸水印总览"/>:<p className="hint"><Spinner/>总览正在整理中，请稍候。</p>}</section>:order.state==='draft'?<>
      <SelectionSummary count={counts.selection_count} max={order.generation_limit} finalCount={order.final_count}/><section className="settings-section"><div className="customer-section-head"><div><h2>1. 上传头像</h2><p className="hint">每个头像分别选择模板或贴纸，最多 {order.final_count} 个头像。</p></div><label data-guide="add-avatar" className={'button '+(busy?'disabled':'')} onClick={e=>{if(guide&&!(e.target instanceof HTMLInputElement)&&!busy&&avatars.length<order.final_count&&!guideHidden(PHOTO_DIALOG)){e.preventDefault();setPhotoDialog(true)}}}><ImagePlus size={16}/>添加头像<input ref={fileInput} className="guide-file-input" aria-label="上传头像" type="file" accept="image/*" multiple disabled={!!busy||avatars.length>=order.final_count} onChange={e=>{void upload(e.target.files);e.target.value=''}}/></label></div>{guide&&<PhotoRules compact={avatars.length>0}/>}{busy==='upload'&&<p role="status"><Spinner/>头像上传中 {uploadProgress}%</p>}
      {!avatars.length?<Empty title="从一张清晰的头像开始" description="上传后即可选择喜欢的贴纸。"/>:<div className="customer-avatar-list">{avatars.map((avatar,index)=>{const count=selectionCounts([avatar],library);return <article className="customer-avatar-row" key={avatar.upload_id}>{avatar.preview_url?<img className="avatar large" src={avatar.preview_url} alt={`头像 ${index+1}`}/>:<ImagePlus size={32}/>}<div className="customer-avatar-name"><strong>头像 {index+1}</strong><small>{avatar.name}</small><span>{count.selection_count} 张已选 · {count.generation_count} 张实际生成</span></div><button className="button" data-guide="pick-stickers" disabled={!!busy} onClick={()=>setPicker(avatar.upload_id)}>选择模板和贴纸</button><button className="icon-button" aria-label={`移除头像 ${index+1}`} disabled={!!busy} onClick={()=>changeAvatars(avatarsRef.current.filter(a=>a.upload_id!==avatar.upload_id))}><Trash2 size={16}/></button></article>})}</div>}</section>
      <div className="customer-submit-bar"><div><strong>已选 {counts.selection_count} 张</strong><p className="hint">{counts.avatar_count} 个头像 · 实际生成 {counts.generation_count} 张{draftError?' · '+draftError:''}</p></div><button className="button primary" data-guide="start-generate" disabled={!!busy||!!draftError||avatars.some(a=>!a.template_ids.length&&!a.sticker_ids.length)} onClick={()=>void check()}>{busy==='preflight'&&<Spinner/>}核对并开始生成</button></div>
    </>:<>
      <div className="customer-selection-badge-wrap"><span className="customer-selection-badge" data-guide="selected-badge" role="status" aria-live="polite">已选 {selection.length}/{order.final_count}</span></div>{guide&&order.slots?.some(slot=>!slot.versions.length&&slot.status!=='failed')&&<div className="guide-waiting" role="status">正在制作中，需要一些时间。可以先离开，之后用同一个订单号回来查看，结果会自动保存。</div>}<div className="notice-banner">生成后头像与贴纸组合已固定。勾选 {order.final_count} 张提交印刷；重试后请确认保留哪个版本。</div>
      <div className="customer-results">{order.slots?.map((slot,index)=>{const result=slot.versions.find(v=>v.id===slot.selected_version_id),selected=selection.includes(slot.id),canSelect=!busy&&!!result&&!slot.pending_version_id&&!slotBusy(slot)&&(selected||selection.length<order.final_count);return <article key={slot.id} className={'customer-result '+(selected?'selected ':'')+(canSelect?'selectable':'')} onClick={()=>{if(canSelect)toggleSlot(slot.id)}}><div className="customer-result-image checker">{result?<><img src={result.preview_url} alt={`${slot.sticker_code} 第 ${index+1} 张`} loading="lazy"/><button type="button" className="customer-zoom-button" data-guide="result-zoom" aria-label={`放大查看第 ${index+1} 张`} title="放大查看" onClick={e=>{e.stopPropagation();setResultZoom({title:`${slot.sticker_code} · 第 ${index+1} 张`,url:result.preview_url})}}><ZoomIn size={15}/></button></>:<div className="result-pending"><Status value={slot.status}/></div>}</div><div className="customer-result-body"><div><strong>{slot.sticker_code}</strong><span className="hint">头像 {(order.avatars||[]).findIndex(a=>a.id===slot.avatar_id)+1} · 第 {index+1} 张</span></div><Status value={slot.status}/>{slot.error&&<p className="error-text">{slot.error}</p>}{slot.can_retry&&<button className="button" disabled={!!busy} onClick={e=>{e.stopPropagation();void mutate('/slots/'+encodeURIComponent(slot.id)+'/retry')}}>{busy==='/slots/'+slot.id+'/retry'?<Spinner/>:<RefreshCw size={15}/>}重试生成</button>}<label className="check-line" data-guide={canSelect?'select-final':undefined} onClick={e=>e.stopPropagation()}><input type="checkbox" aria-label={`选择成品 ${index+1}`} checked={selected} disabled={!canSelect} onChange={()=>toggleSlot(slot.id)}/>{selected?'已选为成品':'选为成品'}</label><button className={'button '+(slot.pending_version_id?'primary':'')} data-guide={result?'result-rerun':undefined} onClick={e=>{e.stopPropagation();setComparison(slot.id)}}>{slot.pending_version_id?'对比并确认版本':'查看 / 重跑'}</button>{slot.reruns_reserved?<small>重试处理中 {slot.reruns_reserved} 次</small>:null}</div></article>})}</div>
      <div className="customer-submit-bar"><div><strong>提交印刷 {selection.length} / {order.final_count} 张</strong><p className="hint">{finalError||'提交后将提交印刷，不可修改。'}</p></div><button className="button primary" data-guide="submit" disabled={!!busy||!!finalError} onClick={()=>setSubmitOpen(true)}>确认成品并提交</button></div>
    </>}
    {resultZoom&&order.state==='review'&&<Modal title={resultZoom.title} onClose={()=>setResultZoom(null)} className="modal-media"><div className="media-frame customer-zoom-image"><img src={zoomUrl(resultZoom.url)} alt={resultZoom.title}/></div></Modal>}
    {!order.paused&&picker&&<SelectionPicker guide={guide} library={library} avatar={avatars.find(a=>a.upload_id===picker)!} others={avatars.filter(a=>a.upload_id!==picker)} max={order.generation_limit} finalCount={order.final_count} onClose={()=>setPicker(null)} onSave={next=>{const updated=avatarsRef.current.map(a=>a.upload_id===picker?{...a,...next}:a);if(!canApplySelection(selectionCounts(avatarsRef.current,library).selection_count,selectionCounts(updated,library).selection_count,order.generation_limit)){setError('已超过订单选择上限，请减少份数');return}setPicker(null);changeAvatars(updated)}}/>}
    {!order.paused&&preflight&&<Modal title="生成前核对" onClose={()=>{if(!busy)setPreflight(null)}} wide className="customer-picker-modal">{error&&<div className="error-banner" role="alert">{error}</div>}{!order.paused&&mutations.current.pendingPath&&!busy&&<PendingMutation busy={!!busy} onRetry={()=>void retryPending()}/>}<div className="customer-counts"><div><span>头像</span><strong>{preflight.avatar_count}</strong></div><div><span>可预览数量</span><strong>{preflight.selection_count}</strong></div><div><span>可提交印刷</span><strong>{order.final_count}</strong></div></div>{guide&&<p className="guide-warning">⚠️ 点了「确认开始生成」，头像和贴纸就<strong>不能再改</strong>了，请再检查一遍。</p>}<p>重复选择会保留对应份数，同一头像的相同贴纸共用首次生成结果。开始后，头像和贴纸选择将固定。</p><p className="hint">完成后需选择 {order.final_count} 张成品。</p><PreflightSelections avatars={avatars} library={library}/><div className="modal-footer customer-picker-footer"><button className="button" disabled={!!busy} onClick={()=>setPreflight(null)}>返回调整</button><button className="button primary" disabled={!!busy} onClick={()=>void mutate('/generate',{avatars:avatars.map(({upload_id,template_ids,sticker_ids})=>({upload_id,template_ids,sticker_ids}))})}>{busy&&<Spinner/>}确认开始生成</button></div></Modal>}
    {!order.paused&&compared&&<VersionComparison guide={guide} error={error} slot={compared} limit={order.rerun_limit} used={rerunsUsed} busy={!!busy} onClose={()=>setComparison(null)} pending={!!mutations.current.pendingPath&&!busy} onRetry={()=>void retryPending()} mode={mode} onRecovery={(action)=>void mutate('/slots/'+encodeURIComponent(compared.id)+'/'+action,action==='resolve'?{confirmed_ended:true}:{})} onRerun={()=>void mutate('/slots/'+encodeURIComponent(compared.id)+'/rerun')} onSelect={version_id=>void mutate('/slots/'+encodeURIComponent(compared.id)+'/select',{version_id})}/>}
    {guide&&<GuideTour steps={tour} paused={order.paused||!!picker||!!preflight||photoDialog||!!resultZoom||!!compared||submitOpen}/>}
    {guide&&photoDialog&&<PhotoRulesDialog onClose={()=>setPhotoDialog(false)} onPick={()=>{setPhotoDialog(false);fileInput.current?.click()}}/>}
    {!order.paused&&submitOpen&&<Modal title="确认最终成品" onClose={()=>{if(!busy)setSubmitOpen(false)}}>{error&&<div className="error-banner" role="alert">{error}</div>}{!order.paused&&mutations.current.pendingPath&&!busy&&<PendingMutation busy={!!busy} onRetry={()=>void retryPending()}/>}{guide&&<p className="guide-warning">⚠️ 提交后马上进入印刷，<strong>不能再改，也不能再重试</strong>。</p>}<p>将提交 {selection.length} 张成品。提交后将提交印刷，不可修改。</p><div className="modal-footer"><button className="button" disabled={!!busy} onClick={()=>setSubmitOpen(false)}>继续检查</button><button className="button primary" disabled={!!busy||!!finalError} onClick={()=>void mutate('/submit',{slot_ids:(order.slots||[]).filter(slot=>selection.includes(slot.id)).map(slot=>slot.id)})}>{busy&&<Spinner/>}确认提交</button></div></Modal>}
  </div>
}
// Each avatar with the templates and stickers chosen for it, in selection order, with quantities.
const tally=(ids:string[])=>Array.from(ids.reduce((counts,id)=>counts.set(id,(counts.get(id)||0)+1),new Map<string,number>()))
const preflightImageSizes={single:'(max-width:720px) calc((100vw - 110px) / 3), 132px',set:'(max-width:720px) calc((100vw - 110px) / 6), 66px'}
function PreflightSelections({avatars,library}:{avatars:DraftAvatar[];library:CustomerLibrary}){
  return <div className="customer-preflight-list">{avatars.map((avatar,index)=>{
    const entries=[
      ...tally(avatar.template_ids).flatMap(([id,amount])=>{const t=library.templates.find(value=>value.id===id);return t?[{key:'t'+id,name:t.name,code:t.code,images:t.images.slice(0,4).map(image=>image.preview_url),amount,detail:`${amount} 套 · 每套 ${t.sticker_ids.length} 张`}]:[]}),
      ...tally(avatar.sticker_ids).flatMap(([id,amount])=>{const s=library.stickers.find(value=>value.id===id);return s?[{key:'s'+id,name:s.name,code:s.code,images:[s.preview_url],amount,detail:`${amount} 张`}]:[]}),
    ]
    return <section key={avatar.upload_id} className="customer-preflight-avatar" aria-label={`头像 ${index+1} 的选择`}>
      <header>{avatar.preview_url?<img className="avatar large" src={avatar.preview_url} alt={`头像 ${index+1}`}/>:<ImagePlus size={32}/>}<div><strong>头像 {index+1}</strong><span>共 {selectionCounts([avatar],library).selection_count} 张</span></div></header>
      <ul>{entries.map(entry=><li key={entry.key}><div className="customer-catalog-image">{entry.images.map((url,i)=><img key={i} src={url} srcSet={mediaSrcSet(url)} sizes={preflightImageSizes[entry.images.length>1?'set':'single']} alt="" loading="lazy"/>)}<b aria-label={`数量 ${entry.amount}`}>×{entry.amount}</b></div><strong title={entry.code!==entry.name?`${entry.name}（${entry.code}）`:entry.name}>{entry.name}</strong><span>{entry.detail}</span></li>)}</ul>
    </section>
  })}</div>
}
function SelectionSummary({count,max,finalCount}:{count:number;max:number;finalCount:number}){
  const remaining=Math.max(0,max-count)
  return <div className="customer-selection-summary" role="status" aria-label="订单选图统计"><div><strong>订单已选 {count} / {max} 张</strong><span data-guide="remaining">{count>max?`超出 ${count-max} 张，请减少选择`:`还可选 ${remaining} 张`} · 可提交印刷 {finalCount} 张</span></div><progress aria-label="订单选择进度" max={max} value={Math.min(count,max)}/>{count>=max&&<small>已达订单上限，请先减少选择再增加。</small>}</div>
}
type PickerKind='template_ids'|'sticker_ids'
type PickerEntry={kind:PickerKind;item:LibraryTemplate|LibrarySticker}
function SelectionPicker({guide=false,library,avatar,others,max,finalCount,onClose,onSave}:{guide?:boolean;library:CustomerLibrary;avatar:DraftAvatar;others:AvatarChoice[];max:number;finalCount:number;onClose:()=>void;onSave:(value:AvatarChoice)=>void}){
  const [choice,setChoice]=useState<AvatarChoice>({upload_id:avatar.upload_id,template_ids:avatar.template_ids,sticker_ids:avatar.sticker_ids})
  const [tab,setTab]=useState<'stickers'|'templates'|'selected'>('stickers'),[search,setSearch]=useState(''),[category,setCategory]=useState('all')
  // "已选" shows the list captured on entry (templates, then stickers, in selection order): cards stay put while
  // quantities change, and one reduced to 0 can be added back until the tab is opened again.
  const [pinned,setPinned]=useState<{kind:PickerKind;id:string}[]>([])
  const [zoom,setZoom]=useState<{title:string;url:string}|null>(null),[setView,setSetView]=useState<LibraryTemplate|null>(null)
  const offered=(s:{active?:boolean;available?:boolean})=>s.active!==false&&s.available!==false
  const templates=library.templates.filter(offered),stickers=library.stickers.filter(offered)
  const pool:PickerEntry[]=tab==='selected'?pinned.flatMap(({kind,id})=>{const item=(kind==='template_ids'?templates:stickers).find(value=>value.id===id);return item?[{kind,item}]:[]})
    :tab==='templates'?templates.map(item=>({kind:'template_ids' as const,item})):stickers.map(item=>({kind:'sticker_ids' as const,item}))
  const matches=searchMatcher(search)
  const usable=pool.map(entry=>entry.item)
  const filtered=pool.filter(({item})=>(category==='all'||item.category===category)&&matches(`${item.name} ${item.code}`))
  const categories=categoryOptions(library.categories||[],usable)
  const counts=selectionCounts([choice],library),otherCount=selectionCounts(others,library).selection_count,total=otherCount+counts.selection_count
  function openSelected(){
    const unique=(ids:string[])=>Array.from(new Set(ids))
    setPinned([...unique(choice.template_ids).map(id=>({kind:'template_ids' as const,id})),...unique(choice.sticker_ids).map(id=>({kind:'sticker_ids' as const,id}))])
    setTab('selected')
  }
  function changeQuantity(kind:PickerKind,id:string,value:number){
    setChoice(previous=>{
      const amount=previous[kind].filter(value=>value===id).length
      const limit=selectionQuantityLimit([...others,previous],library,previous.upload_id,kind,id,max)
      // Existing over-limit drafts can still be reduced; new additions never exceed the shared budget.
      return {...previous,[kind]:quantityIds(previous[kind],id,value,Math.max(amount,limit))}
    })
  }
  function card({kind,item:entry}:PickerEntry){
    const amount=choice[kind].filter(id=>id===entry.id).length
    const limit=selectionQuantityLimit([...others,choice],library,choice.upload_id,kind,entry.id,max,total)
    const title=entry.name+(entry.code!==entry.name?' · '+entry.code:''),meta=[entry.code!==entry.name?entry.code:'','sticker_ids' in entry?`${entry.sticker_ids.length} 张/套`:''].filter(Boolean).join(' · ')
    return <article key={kind+entry.id} className={amount?'selected':''}><div className="customer-catalog-image">{'images' in entry?entry.images.slice(0,4).map((image,index)=><img key={index} src={image.preview_url} srcSet={mediaSrcSet(image.preview_url)} sizes={pickerImageSizes[entry.images.length>1?'setThumbnail':'sticker']} alt="" loading="lazy"/>):<img src={entry.preview_url} srcSet={mediaSrcSet(entry.preview_url)} sizes={pickerImageSizes.sticker} alt="" loading="lazy"/>}<button type="button" className="customer-zoom-button" aria-label={`放大查看 ${entry.code}`} title={'images' in entry?'查看模板包含的贴纸':'放大查看'} onClick={()=>'images' in entry?setSetView(entry):setZoom({title,url:entry.preview_url})}><ZoomIn size={15}/></button></div><strong>{entry.name}</strong>{meta&&<span>{meta}</span>}<div className="customer-quantity-control"><div><button type="button" className="icon-button" aria-label={`${entry.code} 减少份数`} disabled={amount===0} onClick={()=>changeQuantity(kind,entry.id,amount-1)}><Minus size={14}/></button><input aria-label={`${entry.code} 份数`} type="number" min={0} max={limit} disabled={amount===0&&limit===0} value={amount} onChange={e=>changeQuantity(kind,entry.id,Number(e.target.value))}/><button type="button" className="icon-button" data-guide="picker-plus" aria-label={`${entry.code} 增加份数`} disabled={amount>=limit} onClick={()=>changeQuantity(kind,entry.id,amount+1)}><Plus size={14}/></button></div></div></article>
  }
  return <Modal title="选择模板和贴纸" onClose={onClose} wide className="customer-picker-modal">
    <SelectionSummary count={total} max={max} finalCount={finalCount}/>
    <p className="hint">本头像已选 {counts.selection_count} 张 · 其他头像已选 {otherCount} 张。模板按包含的贴纸张数计算，重复选择同样占用份数。</p>
    {/* Tabs, search and category stay pinned while long catalogs scroll. */}
    <div className="customer-picker-toolbar"><div className="tabs" data-guide="picker-tabs"><button className={tab==='stickers'?'active':''} onClick={()=>setTab('stickers')}>单张贴纸</button><button className={tab==='templates'?'active':''} onClick={()=>setTab('templates')}>模板套装</button><button className={tab==='selected'?'active':''} onClick={openSelected}>已选 {counts.selection_count}</button></div>
    <div className="customer-picker-filters"><input aria-label="搜索模板或贴纸" placeholder="搜索名称或编号" value={search} onChange={e=>setSearch(e.target.value)}/><select aria-label="贴纸分类" value={category} onChange={e=>setCategory(e.target.value)}><option value="all">全部分类（{usable.length}）</option>{categories.map(option=><option key={option.id} value={option.id} disabled={!option.count&&option.id!==category}>{option.name}（{option.count}）</option>)}</select></div></div>
    {tab==='selected'&&!pool.length?<Empty title="还没有选择" description="去“单张贴纸”或“模板套装”挑选，选好的会显示在这里。"/>
      :!filtered.length?<Empty title="没有匹配的模板或贴纸"/>
      :tab==='selected'?(['template_ids','sticker_ids'] as const).map(kind=>{const group=filtered.filter(entry=>entry.kind===kind);return group.length?<section key={kind} className="customer-selected-group" aria-label={kind==='template_ids'?'已选模板套装':'已选单张贴纸'}><h3>{kind==='template_ids'?'模板套装':'单张贴纸'}</h3><div className="customer-catalog">{group.map(card)}</div></section>:null})
      :<div className="customer-catalog">{filtered.map(card)}</div>}
    {setView&&<Modal title={`${setView.name} · 共 ${setView.images.length} 张`} onClose={()=>setSetView(null)} wide><p className="hint">模板包含以下贴纸，点击可放大查看。</p><div className="customer-set-preview">{setView.images.map((image,index)=>{const label=image.code||`第 ${index+1} 张`;return <button type="button" key={index} aria-label={`放大查看 ${label}`} onClick={()=>setZoom({title:`${setView.name} · ${label}`,url:image.preview_url})}><img src={image.preview_url} srcSet={mediaSrcSet(image.preview_url)} sizes={pickerImageSizes.setContents} alt="" loading="lazy"/><span>{label}</span></button>})}</div></Modal>}
    {zoom&&<Modal title={zoom.title} onClose={()=>setZoom(null)} className="modal-media"><div className="media-frame customer-zoom-image"><img src={zoomUrl(zoom.url)} alt={zoom.title}/></div></Modal>}
    <div className="modal-footer customer-picker-footer"><span><button type="button" className="text-button customer-selected-link" title="查看已选" onClick={openSelected}>本头像 {counts.selection_count} 张</button> · 订单共 {total} / {max} 张</span><button className="button primary" data-guide="picker-apply" disabled={!canApplySelection(otherCount+selectionCounts([avatar],library).selection_count,total,max)} onClick={()=>onSave(choice)}>应用选择</button></div>
    {guide&&<GuideTour paused={!!zoom||!!setView} steps={[
      {id:'picker-tabs',target:'[data-guide="picker-tabs"]',text:'「单张贴纸」一张一张挑；「模板套装」一次选一整套。'},
      {id:'picker-plus',target:'.customer-picker-modal [data-guide="picker-plus"]:not(:disabled)',text:<>点 <strong>+</strong> 选这张，多点几次可以选多份；点 <strong>−</strong> 减少。</>},
      {id:'picker-remaining',target:'.customer-picker-modal [data-guide="remaining"]',text:'这里显示还能选几张，选满了就加不了。'},
      {id:'picker-apply',target:'[data-guide="picker-apply"]',text:<strong>选好后一定要点「应用选择」，不点就没选上！</strong>},
    ]}/>}
  </Modal>
}
function VersionComparison({guide=false,slot,limit,used,busy,onClose,onRerun,onSelect,mode,onRecovery,pending,onRetry,error}:{guide?:boolean;error:string;pending:boolean;onRetry:()=>void;mode:'staff'|'guest';onRecovery:(action:string)=>void;slot:CustomerSlot;limit:number;used:number;busy:boolean;onClose:()=>void;onRerun:()=>void;onSelect:(id:string)=>void}){
  const [confirmRerun,setConfirmRerun]=useState(false),[confirmedEnded,setConfirmedEnded]=useState(false)
  return <Modal title={slot.sticker_code+' · 版本对比'} onClose={onClose} wide>{error&&<div className="error-banner" role="alert">{error}</div>}{pending&&<PendingMutation busy={busy} onRetry={onRetry}/>}<p className="hint">重试成功后请明确保留旧版或新版。未保留的重试仍计入整单已用次数。</p><div className="customer-versions">{slot.versions.map((version,index)=><figure key={version.id}><figcaption>版本 {index+1}{version.id===slot.pending_version_id?' · 新生成':version.id===slot.selected_version_id?' · 当前保留':''}</figcaption><div className="checker"><img src={version.preview_url} alt={'版本 '+(index+1)}/></div><button className={'button '+(version.id===slot.selected_version_id?'primary':'')} data-guide={slot.pending_version_id?'keep-version':undefined} disabled={busy||slotBusy(slot)||(!slot.pending_version_id&&version.id===slot.selected_version_id)} onClick={()=>onSelect(version.id)}>{version.id===slot.selected_version_id&&slot.pending_version_id?'保留旧版本':version.id===slot.selected_version_id?'已保留':'保留此版本'}</button></figure>)}</div>{!slot.versions.length&&<Empty title="图片尚未生成完成"/>}{slot.error&&<div className="error-banner">{slot.error}</div>}<p>整单重试已用 {used} / {limit} 次{slot.reruns_used?`，本张 ${slot.reruns_used} 次`:''}{slot.reruns_reserved?`，本张处理中 ${slot.reruns_reserved} 次`:''}</p>{slot.pending_version_id&&<p className="notice-banner">请在上方选择要保留的版本后继续。</p>}{mode==='staff'&&<div className="customer-staff-actions">{slot.needs_resolution?<div><label className="check-line"><input type="checkbox" checked={confirmedEnded} onChange={e=>setConfirmedEnded(e.target.checked)}/>我已核对供应商，确认原请求已结束或不存在</label><button className="button" disabled={busy||!confirmedEnded} onClick={()=>{setConfirmedEnded(false);onRecovery('resolve')}}>确认结束并释放占用</button></div>:slot.status==='failed'?<>{!slot.versions.length&&<button className="button" disabled={busy} onClick={()=>onRecovery('retry')}>重试首次生成</button>}{slot.raw_available&&<button className="button" disabled={busy} onClick={()=>onRecovery('reprocess')}>仅重试后处理</button>}</>:null}</div>}{confirmRerun&&<p className="notice-banner">将为这一份贴纸生成新版本，成功后占用一次整单重试次数。</p>}<div className="modal-footer"><button className="button" onClick={onClose}>关闭</button><button className="button primary" disabled={busy||slotBusy(slot)||!!slot.pending_version_id||used>=limit} onClick={()=>{if(confirmRerun){setConfirmRerun(false);onRerun()}else setConfirmRerun(true)}}><RefreshCw size={15}/>{confirmRerun?'确认重跑这一张':'重新生成这一张'}</button></div>{guide&&<GuideTour steps={[{id:'version-keep',target:'[data-guide="keep-version"]:not(:disabled)',text:'重新生成后有新旧两个版本，请点选要留下的那个。'}]}/>}</Modal>
}

export function PendingMutation({busy,onRetry}:{busy:boolean;onRetry:()=>void}){
  return <div className="notice-banner customer-pending-mutation" role="status">上一操作的响应尚未确认。请重新核对结果，系统会沿用原操作，不会重复生成。<button className="button" disabled={busy} onClick={onRetry}>{busy&&<Spinner/>}重试确认上一操作</button></div>
}
