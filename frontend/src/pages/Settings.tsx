import { Maintenance } from '../components/Maintenance'
import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { KeyRound, Save, ShieldCheck } from 'lucide-react'
import { PrintFields, Spinner, useNotice } from '../components/UI'
import { api, patch, post } from '../lib/api'
import { defaultPrint } from '../lib/types'
import type { User, Settings, PrintSettings } from '../lib/types'

export function Account({user,onUpdate}:{user:User;onUpdate:(u:User)=>void}) {
  const [name,setName]=useState(user.display_name),[watermark,setWatermark]=useState(user.watermark||''),[print,setPrint]=useState<PrintSettings>({...defaultPrint,...user.print_defaults}),[busy,setBusy]=useState(false),notice=useNotice()
  async function save(event:FormEvent) {
    event.preventDefault();setBusy(true)
    try{const next=await patch<User>('/account',{display_name:name,watermark,print_defaults:print});onUpdate(next);notice('账号设置已保存')}catch(e){notice((e as Error).message,'error')}finally{setBusy(false)}
  }
  async function password(event:FormEvent<HTMLFormElement>) {
    event.preventDefault();const form=event.currentTarget;setBusy(true)
    try{await post('/account/password',Object.fromEntries(new FormData(form)));form.reset();notice('密码已更新')}catch(e){notice((e as Error).message,'error')}finally{setBusy(false)}
  }
  return <><div className="page-heading"><div><h1>账号设置</h1><p>让每一份预览，都带上你的名字。</p></div></div><div className="settings-layout"><form onSubmit={save}><section className="settings-section"><h2>个人信息</h2><div className="form-grid"><label className="field">账号<input value={user.username} disabled/></label><label className="field">显示名称<input value={name} onChange={e=>setName(e.target.value)} required/></label></div><label className="field">水印文字<input value={watermark} onChange={e=>setWatermark(e.target.value)} placeholder={user.display_name}/><span className="hint">斜向平铺在客户总览上，不影响打印文件。留空使用显示名称。</span></label><div className="watermark-preview" aria-label="水印样式预览">{Array.from({length:12},(_,i)=><span key={i}>{watermark||name||'头像贴纸'}</span>)}</div></section><section className="settings-section"><h2>默认打印参数</h2><PrintFields value={print} onChange={setPrint}/></section><button className="button primary" disabled={busy}>{busy?<Spinner/>:<Save size={16}/>}保存设置</button></form><aside><form onSubmit={password} className="settings-section"><h2><KeyRound size={18}/>修改密码</h2><label className="field">当前密码<input type="password" name="current_password" required autoComplete="current-password"/></label><label className="field">新密码<input type="password" name="new_password" required minLength={10} autoComplete="new-password"/></label><button className="button" disabled={busy}>更新密码</button></form><div className="aside-note"><ShieldCheck size={20}/><p>你的头像、订单和生成结果仅对你的账号及管理员可见。</p></div></aside></div></>
}
export function Admin() {
  const [settings,setSettings]=useState<Settings|null>(null),[key,setKey]=useState(''),[cutout,setCutout]=useState(''),[busy,setBusy]=useState(false),[error,setError]=useState(''),notice=useNotice()
  const load=()=>api<Settings>('/admin/settings').then(s=>{setSettings(s);setError('')}).catch(e=>setError(e.message))
  useEffect(()=>{void load()},[])
  async function save(event:FormEvent) {
    event.preventDefault();setBusy(true)
    try {await patch('/admin/settings',{max_inflight:settings!.max_inflight,prompt:settings!.prompt,...(key?{fal_api_key:key}:{}),...(cutout?{cutout_api_key:cutout}:{})});setKey('');setCutout('');await load();notice('全站设置已保存')}catch(e){notice((e as Error).message,'error')}finally{setBusy(false)}
  }
  return <><div className="page-heading"><div><h1>管理设置</h1><p>管理同时处理数量、服务接入和团队账号。</p></div></div>{error&&<div className="error-banner">{error}<button onClick={()=>void load()}>重试</button></div>}{settings?<div className="settings-layout"><form onSubmit={save}><section className="settings-section"><h2>生图服务</h2><div className="provider-heading"><strong>FAL.ai</strong><span className={'availability '+(settings.fal_configured?'on':'')}>{settings.fal_configured?'已配置密钥':'待配置'}</span></div><p className="provider-spec">gpt-image-2 <span>·</span> Low <span>·</span> 1K <span>·</span> 透明 PNG</p><label className="field">FAL API Key<input type="password" autoComplete="new-password" value={key} onChange={e=>setKey(e.target.value)} placeholder={settings.fal_configured?'输入新密钥以替换；留空保持原值':'填写此网站使用的 API Key'}/><span className="hint">填写 FAL 密钥，无需 OpenAI 密钥。密钥仅保存在服务端，保存后不会显示原文。</span></label><label className="field">椰子抠图 API Key（按需使用）<input type="password" autoComplete="new-password" value={cutout} onChange={e=>setCutout(e.target.value)} placeholder={settings.cutout_configured?'已配置；留空保持原值':'透明背景需要修复时使用'}/></label></section><section className="settings-section"><h2>全站并发</h2><div className="form-grid"><label className="field">最大同时处理数量<input type="number" required min={1} max={40} step={1} value={settings.max_inflight} onChange={e=>setSettings({...settings,max_inflight:Number(e.target.value)})}/></label></div><p className="hint">所有账号共用上限，包含已提交到 FAL 排队的任务。默认 2，不限制每分钟数量。FAL 账号达到实际并发上限时会继续排队；调低此值会等待已有任务结束。</p></section><section className="settings-section"><h2>固定提示词 <span className="count">v{settings.prompt_version}</span></h2><textarea rows={9} value={settings.prompt} onChange={e=>setSettings({...settings,prompt:e.target.value})}/><p className="hint">图 1 为模板，图 2 为头像。修改只影响新提交的任务。</p></section><button className="button primary" disabled={busy}>{busy?<Spinner/>:<Save size={16}/>}保存全站设置</button></form><aside><div className="aside-note"><ShieldCheck size={20}/><p>账号创建、邀请、密码重置和积分管理请前往左侧「账户管理」。</p></div></aside></div>:!error&&<Spinner/>}<Maintenance/></>
}
