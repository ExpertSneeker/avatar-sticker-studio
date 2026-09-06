import { useState } from 'react'
import type { FormEvent } from 'react'
import { ArrowRight, ShieldCheck, Layers, Download } from 'lucide-react'
import { Brand, Spinner } from '../components/UI'
import { post } from '../lib/api'
import type { User } from '../lib/types'

export function Auth({needsSetup,onLogin}:{needsSetup:boolean;onLogin:(user:User)=>void}) {
  const [register,setRegister]=useState(false),[busy,setBusy]=useState(false),[error,setError]=useState('')
  async function submit(event:FormEvent<HTMLFormElement>) {
    event.preventDefault();setBusy(true);setError('')
    const data=Object.fromEntries(new FormData(event.currentTarget))
    try {onLogin(await post<User>(needsSetup?'/auth/setup':register?'/auth/register':'/auth/login',data))} catch(e){setError((e as Error).message)} finally{setBusy(false)}
  }
  return <div className="auth-page"><div className="auth-story"><Brand/><div><span className="auth-line"/><h1>一张头像。<br/>一整套好心情。</h1><p>从照片到贴纸，把重复的工作交给工作台。</p><div className="auth-points"><span><Layers size={20}/>固定套装，批量制作</span><span><ShieldCheck size={20}/>订单独立，进度可恢复</span><span><Download size={20}/>自动排版，直接打印</span></div></div><small>头像贴纸 · 生产工作台</small></div><main className="auth-form-area"><form className="auth-form" onSubmit={submit}><h2>{needsSetup?'创建管理员账号':register?'加入工作台':'欢迎回来'}</h2><p>{needsSetup?'首次使用，先设置你的管理员账号。':register?'使用管理员提供的邀请码注册。':'登录后继续你的贴纸制作。'}</p>{register&&!needsSetup&&<label className="field">邀请码<input name="invite" required autoComplete="off"/></label>}{(needsSetup||register)&&<label className="field">显示名称<input name="display_name" required maxLength={60} autoComplete="name"/></label>}<label className="field">账号<input name="username" required autoComplete="username" minLength={3}/></label><label className="field">密码<input name="password" type="password" required minLength={needsSetup||register?10:1} autoComplete={needsSetup||register?'new-password':'current-password'}/>{(needsSetup||register)&&<span className="hint">至少 10 个字符</span>}</label>{error&&<div className="error-banner" role="alert">{error}</div>}<button className="button primary full" disabled={busy}>{busy?<Spinner/>:<ArrowRight size={18}/>} {needsSetup?'创建并进入工作台':register?'注册账号':'登录'}</button>{!needsSetup&&<button type="button" className="text-button full" onClick={()=>{setRegister(!register);setError('')}}>{register?'已有账号，返回登录':'收到邀请码？注册账号'}</button>}</form></main></div>
}
