import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { Save } from 'lucide-react'
import { api, patch } from '../lib/api'
import { Spinner, useNotice } from './UI'

type OrganizationSettings={media_cache_days:number;default_media_cache_days:number}

// Organization admins choose how long cached watermarked customer images (avatars, results, overviews) are kept on the server.
export function OrganizationMediaSettings(){
  const [settings,setSettings]=useState<OrganizationSettings|null>(null),[days,setDays]=useState(''),[busy,setBusy]=useState(false),[error,setError]=useState(''),notice=useNotice()
  useEffect(()=>{api<OrganizationSettings>('/organization/settings').then(value=>{setSettings(value);setDays(String(value.media_cache_days))}).catch(e=>setError((e as Error).message))},[])
  async function save(event:FormEvent){
    event.preventDefault();setBusy(true)
    try{const next=await patch<OrganizationSettings>('/organization/settings',{media_cache_days:Number(days)});setSettings(next);setDays(String(next.media_cache_days));notice('客户图片缓存保留天数已保存')}catch(e){notice((e as Error).message,'error')}finally{setBusy(false)}
  }
  return <form onSubmit={save} className="settings-section" aria-label="客户图片缓存">
    <h2>客户图片缓存</h2>
    {error?<p className="error-banner" role="alert">{error}</p>:!settings?<Spinner/>:<>
      <label className="field">保留天数<input aria-label="客户图片缓存保留天数" type="number" required min={1} max={365} step={1} value={days} onChange={e=>setDays(e.target.value)}/></label>
      <p className="hint">本组织客户头像、生成结果和总览的水印预览会缓存在服务器上，最后一次查看满 {settings.media_cache_days} 天后自动清理（默认 {settings.default_media_cache_days} 天，可设 1–365 天）。只清理缓存，不影响原图、订单和打印文件；清理后客户再次打开会重新生成。</p>
      <button className="button" disabled={busy||!days||Number(days)===settings.media_cache_days}>{busy?<Spinner/>:<Save size={16}/>}保存</button>
    </>}
  </form>
}
