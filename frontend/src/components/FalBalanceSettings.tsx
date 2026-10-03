import { useState } from 'react'
import type { FormEvent } from 'react'
import { RefreshCw, Save } from 'lucide-react'
import { api, patch } from '../lib/api'
import type { FalBalance, Settings } from '../lib/types'
import { Spinner } from './UI'

export function FalBalanceSettings({ settings, onSaved }: { settings: Settings; onSaved: (settings: Settings) => void }) {
  const [key, setKey] = useState('')
  const [busy, setBusy] = useState(false)
  const [balance, setBalance] = useState<FalBalance | null>(null)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const environment = settings.fal_balance_key_source === 'environment'

  async function saveKey(value: string) {
    setBusy(true); setError(''); setMessage(''); setBalance(null)
    try {
      const next = await patch<Settings>('/admin/settings', { fal_admin_key: value })
      onSaved(next); setKey(''); setMessage(value ? '余额查询密钥已保存，可以查询余额。' : '余额查询密钥已移除。')
    } catch (e) { setError((e as Error).message) }
    finally { setBusy(false) }
  }
  function save(event: FormEvent) { event.preventDefault(); void saveKey(key.trim()) }
  async function query() {
    setBusy(true); setError(''); setMessage(''); setBalance(null)
    try { setBalance(await api<FalBalance>('/admin/fal/balance', { cache: 'no-store' })) }
    catch (e) { setError((e as Error).message) }
    finally { setBusy(false) }
  }

  return <section className="settings-section" aria-label="FAL 账户余额">
    <h2>FAL 账户余额</h2>
    <div className="provider-heading"><strong>余额查询</strong><span className={'availability ' + (settings.fal_balance_configured ? 'on' : '')}>{settings.fal_balance_configured ? '已配置余额密钥' : '待配置 ADMIN Key'}</span></div>
    <p className="hint">仅网站超级管理员可配置和查询。余额属于此 ADMIN Key 对应的 FAL 账户，请与生图账号保持一致。</p>
    {environment ? <p className="hint">密钥由服务器环境变量 FAL_ADMIN_KEY 提供，替换或移除请联系服务器维护人员。</p> : <form onSubmit={save}>
      <label className="field">FAL ADMIN Key<input aria-label="FAL ADMIN Key" type="password" autoComplete="new-password" maxLength={500} value={key} onChange={e => setKey(e.target.value)} disabled={busy} placeholder={settings.fal_balance_configured ? '输入新密钥以替换；留空保持原值' : '粘贴 ADMIN scope 的完整密钥'} /><span className="hint">与生图 API Key 分开保存。密钥仅保存在服务端，保存后输入框清空，不回显原文。</span></label>
      <div className="fal-balance-actions"><button className="button" disabled={busy || !key.trim()}>{busy ? <Spinner /> : <Save size={16} />}保存余额查询密钥</button>{settings.fal_balance_configured && <button type="button" className="text-button" disabled={busy} onClick={() => void saveKey('')}>移除余额查询密钥</button>}</div>
    </form>}
    <div className="fal-balance-actions"><button type="button" className="button" disabled={busy || !settings.fal_balance_configured || !!key.trim()} onClick={() => void query()}>{busy ? <Spinner /> : <RefreshCw size={16} />}查询余额</button><span className="hint">{key.trim() ? '请先保存新密钥，再查询。' : '点击时查询，不自动刷新。'}</span></div>
    {error && <div className="error-banner" role="alert">{error}</div>}
    {message && <p className="hint" role="status">{message}</p>}
    {balance && <div className="fal-balance-result" role="status"><strong>{new Intl.NumberFormat('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 6 }).format(balance.current_balance)} {balance.currency}</strong><dl><dt>FAL 账号</dt><dd>{balance.account}</dd><dt>查询时间</dt><dd>{new Date(balance.queried_at * 1000).toLocaleString('zh-CN')}</dd></dl><p className="hint">这是查询时的账户余额，后续生图、充值或额度到期会改变余额。</p></div>}
  </section>
}
