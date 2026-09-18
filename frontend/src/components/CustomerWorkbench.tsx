import { useEffect, useRef, useState } from 'react'
import { ArrowLeft, Check, ImagePlus, Minus, Plus, RefreshCw, Trash2 } from 'lucide-react'
import { api } from '../lib/api'
import { searchMatcher } from '../lib/search'
import { uploadFile } from '../lib/upload'
import { guestUpload } from '../lib/guest-upload'
import { guestApi, canApplySelection, OrderMutations, quantityIds, selectionCounts, selectionQuantityLimit, selectionError, slotBusy, stateLabels, submissionError } from '../lib/customer-orders'
import type { AvatarChoice, CustomerLibrary, CustomerSlot, GuestOrder, Preflight } from '../lib/customer-orders'
import { Empty, Modal, Spinner, Status } from './UI'
import '../pages/CustomerOrders.css'

type DraftAvatar=AvatarChoice&{name:string;preview_url:string}
export function CustomerWorkbench({initial,mode,library,onChange,onBack}:{initial:GuestOrder;mode:'guest'|'staff';library:CustomerLibrary;onChange?:(order:GuestOrder)=>void;onBack?:()=>void}){
  const [order,setOrder]=useState(initial),[avatars,setAvatars]=useState<DraftAvatar[]>([])
  const [busy,setBusy]=useState(''),[error,setError]=useState(''),[uploadProgress,setUploadProgress]=useState(0)
  const [picker,setPicker]=useState<string|null>(null),[preflight,setPreflight]=useState<Preflight|null>(null)
  const [comparison,setComparison]=useState<string|null>(null),[selection,setSelection]=useState<string[]>([]),[submitOpen,setSubmitOpen]=useState(false)
  const requestVersion=useRef(0),lock=useRef(false),mutations=useRef(new OrderMutations()),session=useRef(new AbortController())
  const base=mode==='guest'?'/order':'/customer-orders/'+encodeURIComponent(initial.id)
  const avatarsRef=useRef(avatars);avatarsRef.current=avatars
  const changeRef=useRef(onChange);changeRef.current=onChange
  function accept(next:GuestOrder){setOrder(previous=>next.state==='cancelled'||(next.version??0)>=(previous.version??0)?next:previous);if(next.state==='cancelled'||next.state==='submitted'){setAvatars([]);setSelection([]);setComparison(null);setPicker(null);setPreflight(null);setSubmitOpen(false)}if(next.paused){setComparison(null);setPicker(null);setPreflight(null);setSubmitOpen(false)}changeRef.current?.(next)}
  async function refresh(){const signal=session.current.signal,revision=++requestVersion.current;const next=mode==='guest'?await guestApi<GuestOrder>(base,{signal}):await api<GuestOrder>(base,{signal});if(!signal.aborted&&revision===requestVersion.current){accept(next)}}
  useEffect(()=>{
    const controller=new AbortController();session.current=controller
    let fetching=false
    const poll=async()=>{if(fetching||lock.current)return;fetching=true;try{await refresh()}catch(e){if(!controller.signal.aborted)setError((e as Error).message)}finally{fetching=false}}
    const timer=setInterval(()=>void poll(),2500)
    return()=>{clearInterval(timer);controller.abort()}
  },[base,mode])
  useEffect(()=>{if(initial.state==='cancelled'&&order.state!=='cancelled'||(initial.version??0)>(order.version??0))accept(initial)},[initial,order.version])
  useEffect(()=>{
    if(mode!=='guest'||order.state!=='draft'||!avatarsRef.current.length)return
    const controller=new AbortController(),ids=avatarsRef.current.map(avatar=>avatar.upload_id)
    setAvatars(previous=>previous.map(avatar=>({...avatar,preview_url:''})))
    void Promise.all(ids.map(async id=>({id,...await guestApi<{preview_url?:string}>('/uploads/'+encodeURIComponent(id),{signal:controller.signal})}))).then(results=>{
      if(!controller.signal.aborted)setAvatars(previous=>previous.map(avatar=>({...avatar,preview_url:results.find(result=>result.id===avatar.upload_id)?.preview_url||avatar.preview_url})))
    }).catch(e=>{if(!controller.signal.aborted)setError(e.message)})
    return()=>controller.abort()
  },[mode,order.version,order.state])
  const counts=selectionCounts(avatars,library),draftError=selectionError(order,counts)
  const finalError=submissionError(order,selection)
  const compared=order.slots?.find(slot=>slot.id===comparison)
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
        setAvatars(previous=>previous.some(a=>a.upload_id===result.id)?previous:[...previous,{upload_id:result.id,name:file.name,preview_url:url||'',template_ids:[],sticker_ids:[]}])
      }
      setPreflight(null)
    }catch(e){if(!session.current.signal.aborted)setError((e as Error).message)}finally{lock.current=false;if(!session.current.signal.aborted)setBusy('')}
  }
  async function check(){
    if(lock.current||order.paused)return
    lock.current=true;setBusy('preflight');setError('')
    try{const result=await mutations.current.run<Preflight>(mode,base,'/preflight',order.version??0,{avatars:avatars.map(({upload_id,template_ids,sticker_ids})=>({upload_id,template_ids,sticker_ids}))});if(!session.current.signal.aborted)setPreflight(result)}
    catch(e){if(!session.current.signal.aborted)setError((e as Error).message)}finally{lock.current=false;if(!session.current.signal.aborted)setBusy('')}
  }
  function toggleSlot(id:string){setSelection(prev=>prev.includes(id)?prev.filter(value=>value!==id):prev.length<order.final_count?[...prev,id]:prev)}
  return <div className={'customer-workbench '+mode+'-workbench'}>
    <div className="page-heading"><div>{onBack&&<button className="text-button" onClick={onBack}><ArrowLeft size={16}/>返回订单</button>}<h1>订单 {order.order_number}</h1><p>{stateLabels[order.state]}{order.state!=='cancelled'&&` · 最终选择 ${order.final_count} 张 · 最多选择 ${order.generation_limit} 张 · 每张可重跑 ${order.rerun_limit} 次`}</p></div><button className="button" disabled={!!busy} onClick={()=>void refresh().catch(e=>setError(e.message))}><RefreshCw size={16}/>刷新</button></div>
    {error&&<div className="error-banner" role="alert">{error}</div>}
    {!order.paused&&mutations.current.pendingPath&&!busy&&<PendingMutation busy={!!busy} onRetry={()=>void retryPending()}/>}
    {order.state==='cancelled'?<Empty title="订单已取消" description="如需继续制作，请联系为你开单的工作人员。"/>:order.paused?<section className="settings-section" role="status"><h2>订单暂时暂停</h2><p>{order.hold_reason||'当前订单暂不能生成或提交，请联系店铺客服。'}</p>{order.preview_url&&<img className="customer-overview" src={order.preview_url} alt="已确认贴纸水印总览"/>}<div className="customer-results">{order.slots?.map(slot=>{const result=slot.versions.find(v=>v.id===slot.selected_version_id);return result?<img className="customer-paused-preview" key={slot.id} src={result.preview_url} alt={slot.sticker_code+' 水印预览'} loading="lazy"/>:null})}</div></section>:order.state==='submitted'?<section className="customer-submitted"><span className="submitted-check"><Check size={28}/></span><h2>已提交印刷</h2><p>已选 {order.final_count} 张贴纸。已提交印刷，不可修改。</p>{order.preview_url?<img className="customer-overview" src={order.preview_url} alt="已确认贴纸水印总览"/>:<p className="hint"><Spinner/>总览正在整理中，请稍候。</p>}</section>:order.state==='draft'?<>
      <SelectionSummary count={counts.selection_count} max={order.generation_limit} finalCount={order.final_count}/><section className="settings-section"><div className="customer-section-head"><div><h2>1. 上传头像</h2><p className="hint">每个头像分别选择模板或贴纸，最多 {order.final_count} 个头像。</p></div><label className={'button '+(busy?'disabled':'')}><ImagePlus size={16}/>添加头像<input aria-label="上传头像" type="file" accept="image/*" multiple disabled={!!busy||avatars.length>=order.final_count} onChange={e=>{void upload(e.target.files);e.target.value=''}} hidden/></label></div>{busy==='upload'&&<p role="status"><Spinner/>头像上传中 {uploadProgress}%</p>}
      {!avatars.length?<Empty title="从一张清晰的头像开始" description="上传后即可选择喜欢的贴纸。"/>:<div className="customer-avatar-list">{avatars.map((avatar,index)=>{const count=selectionCounts([avatar],library);return <article className="customer-avatar-row" key={avatar.upload_id}>{avatar.preview_url?<img className="avatar large" src={avatar.preview_url} alt={`头像 ${index+1}`}/>:<ImagePlus size={32}/>}<div className="customer-avatar-name"><strong>头像 {index+1}</strong><small>{avatar.name}</small><span>{count.selection_count} 张已选 · {count.generation_count} 张实际生成</span></div><button className="button" disabled={!!busy} onClick={()=>setPicker(avatar.upload_id)}>选择模板和贴纸</button><button className="icon-button" aria-label={`移除头像 ${index+1}`} disabled={!!busy} onClick={()=>{setAvatars(prev=>prev.filter(a=>a.upload_id!==avatar.upload_id));setPreflight(null)}}><Trash2 size={16}/></button></article>})}</div>}</section>
      <div className="customer-submit-bar"><div><strong>已选 {counts.selection_count} 张</strong><p className="hint">{counts.avatar_count} 个头像 · 实际生成 {counts.generation_count} 张{draftError?' · '+draftError:''}</p></div><button className="button primary" disabled={!!busy||!!draftError||avatars.some(a=>!a.template_ids.length&&!a.sticker_ids.length)} onClick={()=>void check()}>{busy==='preflight'&&<Spinner/>}核对并开始生成</button></div>
    </>:<>
      <div className="notice-banner">生成后头像与贴纸组合已固定。勾选 {order.final_count} 张成品；重跑后请确认保留哪个版本。</div>
      <div className="customer-results">{order.slots?.map((slot,index)=>{const result=slot.versions.find(v=>v.id===slot.selected_version_id),selected=selection.includes(slot.id),canSelect=!busy&&!!result&&!slot.pending_version_id&&!slotBusy(slot)&&(selected||selection.length<order.final_count);return <article key={slot.id} className={'customer-result '+(selected?'selected ':'')+(canSelect?'selectable':'')} onClick={()=>{if(canSelect)toggleSlot(slot.id)}}><div className="customer-result-image checker">{result?<img src={result.preview_url} alt={`${slot.sticker_code} 第 ${index+1} 张`} loading="lazy"/>:<div className="result-pending"><Status value={slot.status}/></div>}</div><div className="customer-result-body"><div><strong>{slot.sticker_code}</strong><span className="hint">头像 {(order.avatars||[]).findIndex(a=>a.id===slot.avatar_id)+1} · 第 {index+1} 张</span></div><Status value={slot.status}/>{slot.error&&<p className="error-text">{slot.error}</p>}<label className="check-line" onClick={e=>e.stopPropagation()}><input type="checkbox" aria-label={`选择成品 ${index+1}`} checked={selected} disabled={!canSelect} onChange={()=>toggleSlot(slot.id)}/>{selected?'已选为成品':'选为成品'}</label><button className={'button '+(slot.pending_version_id?'primary':'')} onClick={e=>{e.stopPropagation();setComparison(slot.id)}}>{slot.pending_version_id?'对比并确认版本':'查看 / 重跑'}</button><small>重跑已用 {slot.reruns_used} / {order.rerun_limit}{slot.reruns_reserved?` · 处理中 ${slot.reruns_reserved} 次`:''}</small></div></article>})}</div>
      <div className="customer-submit-bar"><div><strong>已选 {selection.length} / {order.final_count} 张</strong><p className="hint">{finalError||'提交后将提交印刷，不可修改。'}</p></div><button className="button primary" disabled={!!busy||!!finalError} onClick={()=>setSubmitOpen(true)}>确认成品并提交</button></div>
    </>}
    {!order.paused&&picker&&<SelectionPicker library={library} avatar={avatars.find(a=>a.upload_id===picker)!} others={avatars.filter(a=>a.upload_id!==picker)} max={order.generation_limit} finalCount={order.final_count} onClose={()=>setPicker(null)} onSave={next=>{const updated=avatarsRef.current.map(a=>a.upload_id===picker?{...a,...next}:a);if(!canApplySelection(selectionCounts(avatarsRef.current,library).selection_count,selectionCounts(updated,library).selection_count,order.generation_limit)){setError('已超过订单选择上限，请减少份数');return}setAvatars(updated);setPicker(null);setPreflight(null)}}/>}
    {!order.paused&&preflight&&<Modal title="生成前核对" onClose={()=>{if(!busy)setPreflight(null)}}>{error&&<div className="error-banner" role="alert">{error}</div>}{!order.paused&&mutations.current.pendingPath&&!busy&&<PendingMutation busy={!!busy} onRetry={()=>void retryPending()}/>}<div className="customer-counts"><div><span>头像</span><strong>{preflight.avatar_count}</strong></div><div><span>可选结果</span><strong>{preflight.selection_count}</strong></div><div><span>实际生成</span><strong>{preflight.generation_count}</strong></div></div><p>重复选择会保留对应份数，同一头像的相同贴纸共用首次生成结果。开始后，头像和贴纸选择将固定。</p><p className="hint">完成后需选择 {order.final_count} 张成品。</p><div className="modal-footer"><button className="button" disabled={!!busy} onClick={()=>setPreflight(null)}>返回调整</button><button className="button primary" disabled={!!busy} onClick={()=>void mutate('/generate',{avatars:avatars.map(({upload_id,template_ids,sticker_ids})=>({upload_id,template_ids,sticker_ids}))})}>{busy&&<Spinner/>}确认开始生成</button></div></Modal>}
    {!order.paused&&compared&&<VersionComparison error={error} slot={compared} limit={order.rerun_limit} busy={!!busy} onClose={()=>setComparison(null)} pending={!!mutations.current.pendingPath&&!busy} onRetry={()=>void retryPending()} mode={mode} onRecovery={(action)=>void mutate('/slots/'+encodeURIComponent(compared.id)+'/'+action,action==='resolve'?{confirmed_ended:true}:{})} onRerun={()=>void mutate('/slots/'+encodeURIComponent(compared.id)+'/rerun')} onSelect={version_id=>void mutate('/slots/'+encodeURIComponent(compared.id)+'/select',{version_id})}/>}
    {!order.paused&&submitOpen&&<Modal title="确认最终成品" onClose={()=>{if(!busy)setSubmitOpen(false)}}>{error&&<div className="error-banner" role="alert">{error}</div>}{!order.paused&&mutations.current.pendingPath&&!busy&&<PendingMutation busy={!!busy} onRetry={()=>void retryPending()}/>}<p>将提交 {selection.length} 张成品。提交后将提交印刷，不可修改。</p><div className="modal-footer"><button className="button" disabled={!!busy} onClick={()=>setSubmitOpen(false)}>继续检查</button><button className="button primary" disabled={!!busy||!!finalError} onClick={()=>void mutate('/submit',{slot_ids:(order.slots||[]).filter(slot=>selection.includes(slot.id)).map(slot=>slot.id)})}>{busy&&<Spinner/>}确认提交</button></div></Modal>}
  </div>
}
function SelectionSummary({count,max,finalCount}:{count:number;max:number;finalCount:number}){
  const remaining=Math.max(0,max-count)
  return <div className="customer-selection-summary" role="status" aria-label="订单选图统计"><div><strong>订单已选 {count} / {max} 张</strong><span>{count>max?`超出 ${count-max} 张，请减少选择`:`还可选 ${remaining} 张`} · 最终需提交 {finalCount} 张</span></div><progress aria-label="订单选择进度" max={max} value={Math.min(count,max)}/>{count>=max&&<small>已达订单上限，请先减少选择再增加。</small>}</div>
}
function SelectionPicker({library,avatar,others,max,finalCount,onClose,onSave}:{library:CustomerLibrary;avatar:DraftAvatar;others:AvatarChoice[];max:number;finalCount:number;onClose:()=>void;onSave:(value:AvatarChoice)=>void}){
  const [choice,setChoice]=useState<AvatarChoice>({upload_id:avatar.upload_id,template_ids:avatar.template_ids,sticker_ids:avatar.sticker_ids})
  const [tab,setTab]=useState('templates'),[search,setSearch]=useState(''),[category,setCategory]=useState('all')
  const source=tab==='templates'?library.templates:library.stickers
  const kind=tab==='templates'?'template_ids':'sticker_ids'
  const matches=searchMatcher(search)
  const filtered=source.filter(s=>s.active!==false&&(!('available' in s)||s.available!==false)&&(category==='all'||s.category===category)&&matches(`${s.name} ${s.code}`))
  const counts=selectionCounts([choice],library),otherCount=selectionCounts(others,library).selection_count,total=otherCount+counts.selection_count
  function changeQuantity(id:string,value:number){
    setChoice(previous=>{
      const amount=previous[kind].filter(value=>value===id).length
      const limit=selectionQuantityLimit([...others,previous],library,previous.upload_id,kind,id,max)
      // Existing over-limit drafts can still be reduced; new additions never exceed the shared budget.
      return {...previous,[kind]:quantityIds(previous[kind],id,value,Math.max(amount,limit))}
    })
  }
  return <Modal title="选择模板和贴纸" onClose={onClose} wide>
    <SelectionSummary count={total} max={max} finalCount={finalCount}/>
    <p className="hint">本头像已选 {counts.selection_count} 张 · 其他头像已选 {otherCount} 张。模板按包含的贴纸张数计算，重复选择同样占用份数。</p>
    <div className="tabs"><button className={tab==='templates'?'active':''} onClick={()=>setTab('templates')}>模板套装</button><button className={tab==='stickers'?'active':''} onClick={()=>setTab('stickers')}>单张贴纸</button></div>
    <div className="customer-picker-filters"><input aria-label="搜索模板或贴纸" placeholder="搜索名称或编号" value={search} onChange={e=>setSearch(e.target.value)}/><select aria-label="贴纸分类" value={category} onChange={e=>setCategory(e.target.value)}><option value="all">全部分类</option>{Array.from(new Set(source.map(s=>s.category))).map(value=><option key={value}>{value}</option>)}</select></div>
    {filtered.length?<div className="customer-catalog">{filtered.map(entry=>{
      const amount=choice[kind].filter(id=>id===entry.id).length
      const limit=selectionQuantityLimit([...others,choice],library,choice.upload_id,kind,entry.id,max,total)
      return <article key={entry.id} className={amount?'selected':''}><div className="customer-catalog-image">{'images' in entry?entry.images.slice(0,4).map((image,index)=><img key={index} src={image.preview_url} alt="" loading="lazy"/>):<img src={entry.preview_url} alt="" loading="lazy"/>}</div><strong>{entry.name}</strong><span>{entry.code}{'sticker_ids' in entry?` · ${entry.sticker_ids.length} 张 / 套`:''}</span><div className="customer-quantity-control"><span>份数</span><div><button type="button" className="icon-button" aria-label={`${entry.code} 减少份数`} disabled={amount===0} onClick={()=>changeQuantity(entry.id,amount-1)}><Minus size={14}/></button><input aria-label={`${entry.code} 份数`} type="number" min={0} max={limit} disabled={amount===0&&limit===0} value={amount} onChange={e=>changeQuantity(entry.id,Number(e.target.value))}/><button type="button" className="icon-button" aria-label={`${entry.code} 增加份数`} disabled={amount>=limit} onClick={()=>changeQuantity(entry.id,amount+1)}><Plus size={14}/></button></div></div></article>
    })}</div>:<Empty title="没有匹配的模板或贴纸"/>}
    <div className="modal-footer"><span>本头像 {counts.selection_count} 张 · 订单共 {total} / {max} 张</span><button className="button primary" disabled={!canApplySelection(otherCount+selectionCounts([avatar],library).selection_count,total,max)} onClick={()=>onSave(choice)}>应用选择</button></div>
  </Modal>
}
function VersionComparison({slot,limit,busy,onClose,onRerun,onSelect,mode,onRecovery,pending,onRetry,error}:{error:string;pending:boolean;onRetry:()=>void;mode:'staff'|'guest';onRecovery:(action:string)=>void;slot:CustomerSlot;limit:number;busy:boolean;onClose:()=>void;onRerun:()=>void;onSelect:(id:string)=>void}){
  const [confirmRerun,setConfirmRerun]=useState(false),[confirmedEnded,setConfirmedEnded]=useState(false)
  return <Modal title={slot.sticker_code+' · 版本对比'} onClose={onClose} wide>{error&&<div className="error-banner" role="alert">{error}</div>}{pending&&<PendingMutation busy={busy} onRetry={onRetry}/>}<p className="hint">重跑成功后请明确保留旧版或新版。未保留的重跑仍计入已用次数。</p><div className="customer-versions">{slot.versions.map((version,index)=><figure key={version.id}><figcaption>版本 {index+1}{version.id===slot.pending_version_id?' · 新生成':version.id===slot.selected_version_id?' · 当前保留':''}</figcaption><div className="checker"><img src={version.preview_url} alt={'版本 '+(index+1)}/></div><button className={'button '+(version.id===slot.selected_version_id?'primary':'')} disabled={busy||slotBusy(slot)||(!slot.pending_version_id&&version.id===slot.selected_version_id)} onClick={()=>onSelect(version.id)}>{version.id===slot.selected_version_id&&slot.pending_version_id?'保留旧版本':version.id===slot.selected_version_id?'已保留':'保留此版本'}</button></figure>)}</div>{!slot.versions.length&&<Empty title="图片尚未生成完成"/>}{slot.error&&<div className="error-banner">{slot.error}</div>}<p>重跑已用 {slot.reruns_used} / {limit} 次{slot.reruns_reserved?`，${slot.reruns_reserved} 次处理中`:''}</p>{slot.pending_version_id&&<p className="notice-banner">请在上方选择要保留的版本后继续。</p>}{mode==='staff'&&<div className="customer-staff-actions">{slot.needs_resolution?<div><label className="check-line"><input type="checkbox" checked={confirmedEnded} onChange={e=>setConfirmedEnded(e.target.checked)}/>我已核对供应商，确认原请求已结束或不存在</label><button className="button" disabled={busy||!confirmedEnded} onClick={()=>{setConfirmedEnded(false);onRecovery('resolve')}}>确认结束并释放占用</button></div>:slot.status==='failed'?<>{!slot.versions.length&&<button className="button" disabled={busy} onClick={()=>onRecovery('retry')}>重试首次生成</button>}{slot.raw_available&&<button className="button" disabled={busy} onClick={()=>onRecovery('reprocess')}>仅重试后处理</button>}</>:null}</div>}{confirmRerun&&<p className="notice-banner">将为这一份贴纸生成新版本，成功后占用一次重跑机会。</p>}<div className="modal-footer"><button className="button" onClick={onClose}>关闭</button><button className="button primary" disabled={busy||slotBusy(slot)||!!slot.pending_version_id||slot.reruns_used+slot.reruns_reserved>=limit} onClick={()=>{if(confirmRerun){setConfirmRerun(false);onRerun()}else setConfirmRerun(true)}}><RefreshCw size={15}/>{confirmRerun?'确认重跑这一张':'重新生成这一张'}</button></div></Modal>
}

export function PendingMutation({busy,onRetry}:{busy:boolean;onRetry:()=>void}){
  return <div className="notice-banner customer-pending-mutation" role="status">上一操作的响应尚未确认。请重新核对结果，系统会沿用原操作，不会重复生成。<button className="button" disabled={busy} onClick={onRetry}>{busy&&<Spinner/>}重试确认上一操作</button></div>
}
