import { useCallback, useEffect, useRef, useState } from 'react'
import { Copy, Plus, RefreshCw, Store, Trash2 } from 'lucide-react'
import { api, patch, post } from '../lib/api'
import { integrationLabel, integrationError, ruleError } from '../lib/agiso'
import type { AgisoStatus, GoodsPage, Shop, ShopEvent, ShopOrder, SkuRule } from '../lib/agiso'
import { Modal, Spinner } from '../components/UI'
import './Shops.css'

function date(value: number | null) { return value ? new Date(value * 1000).toLocaleString('zh-CN') : '暂无' }
const blankRule = (): SkuRule => ({ goods_id: '', sku_id: '', goods_name: '', sku_name: '', generation_limit: 10, final_count: 10, rerun_limit: 2, enabled: false })

export function Shops() {
  const [status, setStatus] = useState<AgisoStatus | null>(null), [shops, setShops] = useState<Shop[]>([])
  const [selected, setSelected] = useState(''), [loading, setLoading] = useState(true), [connecting, setConnecting] = useState(false)
  const [error, setError] = useState(''), [notice, setNotice] = useState('')
  const [authorizationError, setAuthorizationError] = useState('')
  const lifetime = useRef(new AbortController())
  const reloadRevision = useRef(0)
  const reload = useCallback(async () => {
    const revision = ++reloadRevision.current
    const signal = lifetime.current.signal
    try {
      const [nextStatus, nextShops] = await Promise.all([api<AgisoStatus>('/agiso/status', { signal }), api<Shop[]>('/agiso/shops', { signal })])
      if (signal.aborted || revision !== reloadRevision.current) return
      setStatus(nextStatus); setShops(nextShops); setError('')
      setSelected(id => nextShops.some(shop => shop.id === id) ? id : nextShops[0]?.id || '')
    } catch (error) { if (!signal.aborted && revision === reloadRevision.current) throw error }
  }, [])
  useEffect(() => {
    const controller = new AbortController(); lifetime.current = controller
    const params = new URLSearchParams(window.location.search)
    if (params.has('agiso')) {
      if (params.get('agiso') === 'connected') setNotice('店铺授权已完成，请配置商品套餐后再启用自动开户。')
      else setAuthorizationError('店铺授权未完成，请重新连接或联系管理员核对。')
      params.delete('agiso')
      window.history.replaceState(window.history.state, '', window.location.pathname + (params.size ? '?' + params.toString() : '') + window.location.hash)
    }
    void reload().catch(e => { if (!controller.signal.aborted) setError(e.message) }).finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [reload])
  async function connect() {
    setConnecting(true); setError(''); setAuthorizationError('')
    try {
      const result = await post<{ url: string }>('/agiso/authorize', {}, lifetime.current.signal)
      const url = new URL(result.url)
      if (url.protocol !== 'https:' || url.hostname !== 'aldspdd.agiso.com') throw new Error('授权地址无效，请联系管理员')
      if (!lifetime.current.signal.aborted) window.location.assign(url.toString())
    } catch (e) { if (!lifetime.current.signal.aborted) setError((e as Error).message) }
    finally { if (!lifetime.current.signal.aborted) setConnecting(false) }
  }
  const selectedShop = shops.find(shop => shop.id === selected)
  return <>
    <div className="page-heading"><div><h1>店铺接入</h1><p>连接拼多多店铺，按购买规格自动开通客户选图。</p></div><div className="button-group"><button className="button" disabled={loading || connecting} onClick={() => { setError(''); void reload().catch(e => setError(e.message)) }}><RefreshCw size={16}/>刷新</button><button className="button primary" disabled={!status?.configured || connecting} onClick={() => void connect()}>{connecting ? <Spinner/> : <Plus size={16}/>}连接拼多多店铺</button></div></div>
    {(authorizationError || error) && <div className="error-banner" role="alert">{authorizationError || error}</div>}
    {notice && <p role="status">{notice}</p>}
    {status && <section className="settings-section shop-config">
      <h3>{status.configured ? '接入服务已配置' : '尚未完成阿奇索应用配置'}</h3>
      <p>{status.configured ? '每家店铺独立授权。完成套餐配置、发送助手登录和测试后，再打开自动开户。' : '请由网站管理员完成开放平台应用和服务器配置，之后即可连接店铺。'}</p>
      <p className="hint">实体贴纸仍在寄件时填写物流。这里只发送选图入口，不会提前标记已发货。{!status.aftersales_enabled && ' 自动售后尚未启用，须先核实真实退款通知。'}</p>
      <details><summary>接入配置详情</summary><dl>{status.missing.length > 0 && <><dt>待配置项目</dt><dd><code>{status.missing.join('、')}</code></dd></>}{status.authorization_callback_url && <><dt>店铺授权回调</dt><dd><code>{status.authorization_callback_url}</code></dd></>}{status.webhook_url && <><dt>订单通知地址</dt><dd><code>{status.webhook_url}</code></dd></>}</dl><a href="https://www.yuque.com/agiso/open/owplxcrlyxpzw1cq" target="_blank" rel="noreferrer">查看阿奇索授权说明</a></details>
    </section>}
    {loading ? <div className="shop-empty"><Spinner/>正在读取店铺</div> : !shops.length ? <div className="settings-section shop-empty"><Store size={28}/><h3>还没有连接店铺</h3><p>连接店铺后，按真实商品和规格配置生成、提交及重做额度。</p></div> :
      <div className="shops-layout"><aside className="shop-list" aria-label="已连接店铺">{shops.map(shop => <button className={'shop-card ' + (shop.id === selected ? 'active' : '')} key={shop.id} onClick={() => setSelected(shop.id)} aria-pressed={shop.id === selected}><strong>{shop.shop_name}</strong><small>负责账户：{shop.owner_name}</small><small>{shop.enabled ? '自动开户已开启' : '自动开户已关闭'} · {shop.authorized ? '已授权' : '需要重新授权'}</small></button>)}</aside>{selectedShop && <ShopDetail key={selectedShop.id} shop={selectedShop} configured={!!status?.configured} onUpdate={reload}/>}</div>}
  </>
}

function ShopDetail({ shop, configured, onUpdate }: { shop: Shop; configured: boolean; onUpdate: () => Promise<void> }) {
  const base = '/agiso/shops/' + encodeURIComponent(shop.id)
  const [tab, setTab] = useState<'rules' | 'orders' | 'events'>('rules')
  const [rules, setRules] = useState<SkuRule[]>([]), [orders, setOrders] = useState<ShopOrder[]>([]), [events, setEvents] = useState<ShopEvent[]>([])
  const [loading, setLoading] = useState(true), [busy, setBusy] = useState(false), [dirty, setDirty] = useState(false), [error, setError] = useState(''), [notice, setNotice] = useState('')
  const [sourceOpen, setSourceOpen] = useState(false), [source, setSource] = useState<GoodsPage | null>(null), [search, setSearch] = useState(''), [page, setPage] = useState(1)
  const [copiedLink, setCopiedLink] = useState<string | null>(null)
  const lifetime = useRef(new AbortController())
  useEffect(() => {
    const controller = new AbortController(); lifetime.current = controller
    void api<SkuRule[]>(base + '/rules', { signal: controller.signal }).then(next => { if (!controller.signal.aborted) setRules(next) }).catch(e => { if (!controller.signal.aborted) setError(e.message) }).finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [base])
  const activityRevision = useRef(0)
  const refreshActivity = useCallback(async () => {
    const revision = ++activityRevision.current
    const signal = lifetime.current.signal
    try {
      const [nextOrders, nextEvents] = await Promise.all([api<ShopOrder[]>(base + '/orders', { signal }), api<ShopEvent[]>(base + '/events', { signal })])
      if (!signal.aborted && revision === activityRevision.current) { setOrders(nextOrders); setEvents(nextEvents); setError('') }
    } catch (error) { if (!signal.aborted && revision === activityRevision.current) throw error }
  }, [base])
  useEffect(() => { if (tab !== 'rules') void refreshActivity().catch(e => { if (!lifetime.current.signal.aborted) setError(e.message) }) }, [tab, refreshActivity])
  async function action(work: () => Promise<unknown>, message: string) {
    if (busy) return
    const signal = lifetime.current.signal
    setBusy(true); setError(''); setNotice('')
    try { await work(); if (!signal.aborted) setNotice(message) }
    catch (e) { if (!signal.aborted) setError((e as Error).message) }
    finally { if (!signal.aborted) setBusy(false) }
  }
  function edit(index: number, change: Partial<SkuRule>) { setRules(previous => previous.map((rule, i) => i === index ? { ...rule, ...change } : rule)); setDirty(true); setNotice('') }
  async function save() {
    const validation = ruleError(rules)
    if (validation) { setError(validation); return }
    await action(async () => {
      const next = await api<SkuRule[]>(base + '/rules', { method: 'PUT', body: JSON.stringify({ rules }), signal: lifetime.current.signal })
      if (!lifetime.current.signal.aborted) { setRules(next); setDirty(false) }
      await onUpdate()
    }, '套餐已保存，仅影响之后的新订单。')
  }
  async function findGoods(nextPage = 1) {
    await action(async () => {
      const next = await api<GoodsPage>(base + '/goods?page=' + nextPage + '&goods_name=' + encodeURIComponent(search), { signal: lifetime.current.signal })
      if (!lifetime.current.signal.aborted) { setSource(next); setPage(nextPage) }
    }, '')
  }
  async function copyLink(value: string) {
    try { await navigator.clipboard.writeText(value); setNotice('选图链接已复制') }
    catch { setCopiedLink(value) }
  }
  return <section className="shop-detail">
    <div className="settings-section"><div className="shop-toolbar"><div><h2>{shop.shop_name}</h2><p className="hint">店铺 ID：{shop.shop_id} · 负责账户：{shop.owner_name}</p></div><span className={'shop-status ' + (shop.enabled ? '' : 'off')}>{shop.enabled ? '自动开户已开启' : '自动开户已关闭'}</span></div><p className="hint">授权到期：{date(shop.expires_at)}<br/>最近收到订单：{date(shop.last_event_at)}</p>{shop.can_manage && <button className="button" disabled={busy || loading || (!shop.enabled && (!configured || dirty || !shop.authorized || !rules.some(rule => rule.enabled)))} onClick={() => void action(async () => { await patch(base, { enabled: !shop.enabled }); await onUpdate() }, shop.enabled ? '已关闭自动开户，已有订单保留。' : '已开启自动开户，仅处理已启用的 SKU。')}>{shop.enabled ? '关闭自动开户' : '开启自动开户'}</button>}{dirty && <p className="hint">套餐有未保存的修改，保存后才能开启自动开户。</p>}</div>
    <div className="shop-tabs" role="group" aria-label="店铺信息"><button className={'button ' + (tab === 'rules' ? 'primary' : '')} onClick={() => setTab('rules')}>商品套餐</button><button className={'button ' + (tab === 'orders' ? 'primary' : '')} onClick={() => setTab('orders')}>接入订单</button><button className={'button ' + (tab === 'events' ? 'primary' : '')} onClick={() => setTab('events')}>通知记录</button></div>
    {error && <div className="error-banner" role="alert">{error}</div>}{notice && <p role="status">{notice}</p>}
    {tab === 'rules' && <>
      <p className="hint">生成和提交张数按购买件数累加；每张重做次数不变。最多 360 张，未配置的 SKU 转人工处理。</p>
      {shop.can_manage && <div className="button-group"><button className="button" disabled={busy || loading} onClick={() => { setSourceOpen(true); void findGoods() }}>从店铺选择规格</button><button className="button" disabled={busy || loading} onClick={() => { setRules(previous => [...previous, blankRule()]); setDirty(true) }}><Plus size={15}/>手动添加</button></div>}
      {loading ? <div className="shop-empty"><Spinner/></div> : !rules.length ? <p className="shop-empty">尚未配置商品套餐。添加规则后，需要分别启用 SKU 和店铺开关。</p> : <div className="shop-rules">{rules.map((rule, index) => <article className="shop-rule" key={index}>
        <div className="shop-rule-head"><strong>{rule.goods_name || '商品'} · {rule.sku_name || '规格 ' + (index + 1)}</strong>{shop.can_manage && <button className="icon-button" aria-label={'删除规则 ' + (index + 1)} disabled={busy} onClick={() => { setRules(previous => previous.filter((_, i) => i !== index)); setDirty(true) }}><Trash2 size={16}/></button>}</div>
        <div className="shop-rule-grid">{(['goods_name', 'sku_name', 'goods_id', 'sku_id'] as const).map((field, i) => <label className="field" key={field}>{['商品名称', '规格名称', '商品 ID', 'SKU ID'][i]}<input aria-label={`${['商品名称', '规格名称', '商品 ID', 'SKU ID'][i]} ${index + 1}`} value={rule[field]} disabled={!shop.can_manage || busy} maxLength={field.endsWith('id') ? 100 : 200} onChange={e => edit(index, { [field]: e.target.value.trim() })}/></label>)}</div>
        <div className="shop-rule-quotas">{(['generation_limit', 'final_count', 'rerun_limit'] as const).map((field, i) => <label className="field" key={field}>{['每件可生成', '每件最终提交', '单张重做次数'][i]}<input type="number" aria-label={`${['每件可生成', '每件最终提交', '单张重做次数'][i]} ${index + 1}`} min={i === 2 ? 0 : 1} max={i === 2 ? undefined : 360} step="1" value={rule[field]} disabled={!shop.can_manage || busy} onChange={e => edit(index, { [field]: e.target.valueAsNumber })}/></label>)}</div>
        <label className="check-line"><input type="checkbox" checked={rule.enabled} disabled={!shop.can_manage || busy} onChange={e => edit(index, { enabled: e.target.checked })}/>启用此 SKU 自动开户</label>
      </article>)}</div>}
      {shop.can_manage && <div className="shop-save"><span className="hint">{dirty ? '修改尚未保存' : '已保存的规则用于后续订单'}</span><button className="button primary" disabled={busy || loading || !dirty} onClick={() => void save()}>{busy && <Spinner/>}保存套餐</button></div>}
    </>}
    {tab === 'orders' && <><button className="button" disabled={busy} onClick={() => void action(refreshActivity, '订单状态已刷新')}><RefreshCw size={15}/>刷新订单</button><div className="shop-scroll"><table className="shop-table"><thead><tr><th>订单号</th><th>开户 / 消息</th><th>客户进入</th><th>操作</th></tr></thead><tbody>{orders.map(order => <tr key={order.id}><td>{order.order_number}<small>{date(order.created_at)}</small>{order.error && <small>{integrationError(order.error)}</small>}</td><td>{integrationLabel(order.open_status)}<small>{integrationLabel(order.message_status)}</small></td><td>{order.entered_at ? date(order.entered_at) : '尚未进入'}</td><td><div className="button-group">{order.guest_url && <button className="button" onClick={() => void copyLink(order.guest_url!)}><Copy size={14}/>复制选图链接</button>}{shop.can_manage && order.can_retry && <button className="button" disabled={busy} onClick={() => void action(async () => { await post(base + '/orders/' + encodeURIComponent(order.id) + '/retry-message', {}); await refreshActivity() }, '已安排补发，请稍后刷新状态。')}>重试发送</button>}</div>{order.message_status === 'unknown' && <small>请先在拼多多核对消息，避免重复发送。</small>}</td></tr>)}</tbody></table>{!orders.length && <p className="shop-empty">还没有接入订单</p>}</div></>}
    {tab === 'events' && <><button className="button" disabled={busy} onClick={() => void action(refreshActivity, '通知记录已刷新')}><RefreshCw size={15}/>刷新记录</button><div className="shop-scroll"><table className="shop-table"><thead><tr><th>接收时间</th><th>订单号</th><th>处理结果</th><th>操作</th></tr></thead><tbody>{events.map(event => <tr key={event.id}><td>{date(event.received_at)}</td><td>{event.order_number || '未识别'}</td><td>{integrationLabel(event.status)}{event.error && <small>{integrationError(event.error)}</small>}</td><td>{shop.can_manage && event.can_replay && <button className="button" disabled={busy} onClick={() => void action(async () => { await post(base + '/events/' + encodeURIComponent(event.id) + '/replay', {}); await refreshActivity() }, '通知已重新排队，不会重复开户。')}>重新处理</button>}</td></tr>)}</tbody></table>{!events.length && <p className="shop-empty">还没有收到通知</p>}</div></>}
    {sourceOpen && <Modal title="选择店铺商品规格" onClose={() => setSourceOpen(false)}><form className="shop-toolbar" onSubmit={e => { e.preventDefault(); void findGoods(1) }}><label className="field">商品名称<input value={search} onChange={e => setSearch(e.target.value)}/></label><button className="button" disabled={busy}>{busy ? <Spinner/> : '查询商品'}</button></form>{error && <div className="error-banner" role="alert">{error}</div>}{source && !source.available && <p>{source.message || '暂时无法读取商品，请核对店铺授权，或手动填写真实 ID。'}</p>}<div className="shop-source-list">{source?.goods.map(goods => <article className="shop-source" key={goods.goods_id}><strong>{goods.goods_name}</strong><p className="hint">商品 ID：{goods.goods_id}</p><div className="button-group">{goods.skus.map(sku => <button className="button" key={sku.sku_id} disabled={rules.some(rule => rule.goods_id === goods.goods_id && rule.sku_id === sku.sku_id)} onClick={() => {
      setRules(previous => { const index = previous.findIndex(rule => !rule.goods_id && !rule.sku_id && rule.sku_name === sku.sku_name); const next = { ...(index >= 0 ? previous[index] : blankRule()), goods_id: goods.goods_id, goods_name: goods.goods_name, sku_id: sku.sku_id, sku_name: sku.sku_name }; return index >= 0 ? previous.map((rule, i) => i === index ? next : rule) : [...previous, next] }); setDirty(true); setNotice('已添加规格，请核对额度并保存。')
    }}>{sku.sku_name} · {sku.sku_id}</button>)}</div></article>)}</div>{source?.available && !source.goods.length && <p className="shop-empty">未找到商品，请确认已审核上架或调整搜索词。</p>}<div className="modal-footer"><button className="button" disabled={busy || page <= 1} onClick={() => void findGoods(page - 1)}>上一页</button><span>第 {page} 页</span><button className="button" disabled={busy || !source?.available || page * 100 >= (source.total || 0)} onClick={() => void findGoods(page + 1)}>下一页</button><button className="button primary" onClick={() => setSourceOpen(false)}>完成选择</button></div></Modal>}
    {copiedLink && <Modal title="复制选图链接" onClose={() => setCopiedLink(null)}><p>浏览器未允许自动复制，请选中下方链接复制。</p><input aria-label="选图链接" className="full" readOnly value={copiedLink} onFocus={e => e.target.select()}/></Modal>}
  </section>
}
