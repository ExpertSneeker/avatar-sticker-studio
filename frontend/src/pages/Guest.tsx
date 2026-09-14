import { useEffect, useRef, useState } from 'react'
import { LogOut } from 'lucide-react'
import { Brand, Spinner } from '../components/UI'
import { CustomerWorkbench } from '../components/CustomerWorkbench'
import { guestApi, guestPost } from '../lib/customer-orders'
import type { CustomerLibrary, GuestOrder } from '../lib/customer-orders'
import './CustomerOrders.css'

const emptyLibrary: CustomerLibrary = { stickers: [], templates: [] }
function linkedNumber() {
  const value = new URLSearchParams(window.location.search).get('order_number')?.trim() || ''
  return value.length <= 100 && !/[\u0000-\u001f\u007f]/.test(value) ? value : ''
}
function clearLink() {
  const url = new URL(window.location.href)
  url.searchParams.delete('order_number')
  window.history.replaceState(window.history.state, '', url.pathname + url.search + url.hash)
}

// The guest entry never imports the staff shell, local database or delivery helpers.
export default function Guest() {
  const [prefill] = useState(linkedNumber)
  const [number, setNumber] = useState(prefill)
  const [order, setOrder] = useState<GuestOrder | null>(null)
  const [otherOrder, setOtherOrder] = useState<GuestOrder | null>(null)
  const [library, setLibrary] = useState<CustomerLibrary>(emptyLibrary)
  const [loading, setLoading] = useState(true), [busy, setBusy] = useState(false), [error, setError] = useState('')
  const lifetime = useRef(new AbortController())

  useEffect(() => {
    const controller = new AbortController()
    lifetime.current = controller
    const expired = () => { setOrder(null); setOtherOrder(null); setLibrary(emptyLibrary) }
    window.addEventListener('guest-session-expired', expired)
    void guestApi<GuestOrder>('/order', { signal: controller.signal }).then(current => {
      if (controller.signal.aborted) return
      if (prefill && current.order_number !== prefill) setOtherOrder(current)
      else { setOrder(current); clearLink() }
    }).catch(() => {}).finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => { controller.abort(); window.removeEventListener('guest-session-expired', expired) }
  }, [prefill])

  useEffect(() => {
    setLibrary(emptyLibrary)
    if (!order || !['draft', 'review'].includes(order.state)) return
    const controller = new AbortController()
    void guestApi<CustomerLibrary>('/library', { signal: controller.signal }).then(next => {
      if (!controller.signal.aborted) setLibrary(next)
    }).catch(e => { if (!controller.signal.aborted) setError(e.message) })
    return () => controller.abort()
  }, [order?.id, order?.version, order?.state])

  async function login(event: React.FormEvent) {
    event.preventDefault()
    if (busy) return
    const signal = lifetime.current.signal
    setBusy(true); setError('')
    try {
      const current = await guestPost<GuestOrder>('/login', { order_number: number.trim() }, signal)
      if (signal.aborted) return
      setOtherOrder(null); setOrder(current); setNumber(''); clearLink()
    } catch (e) { if (!signal.aborted) setError((e as Error).message) }
    finally { if (!signal.aborted) setBusy(false) }
  }

  async function logout() {
    setBusy(true)
    try {
      await guestPost('/logout', undefined, lifetime.current.signal)
      if (lifetime.current.signal.aborted) return
      setOrder(null); setOtherOrder(null); setLibrary(emptyLibrary); setError(''); setNumber(''); clearLink()
    } catch (e) { if (!lifetime.current.signal.aborted) setError((e as Error).message) }
    finally { if (!lifetime.current.signal.aborted) setBusy(false) }
  }

  return <div className="guest-shell">
    <header className="guest-header"><Brand/><span>客户选图</span>{order && <button className="button" disabled={busy} onClick={() => void logout()}><LogOut size={16}/>退出订单</button>}</header>
    <main className="guest-content">
      {order && error && <div className="error-banner" role="alert">{error}</div>}
      {loading ? <div className="startup"><Spinner/></div> : order ?
        <CustomerWorkbench key={order.id} initial={order} mode="guest" library={library} onChange={setOrder}/> :
        <form className="guest-login settings-section" onSubmit={login}>
          <h1>查看你的头像贴纸</h1>
          {otherOrder ? <div role="status"><strong>当前已登录其他订单</strong><p>确认下方订单号后，可切换到本次购买的订单。</p></div> : <p>输入拼多多订单号，上传头像、选择贴纸并确认成品。</p>}
          <label className="field">订单号<input required autoComplete="off" autoCapitalize="none" spellCheck={false} value={number} onChange={e => setNumber(e.target.value)} maxLength={100}/></label>
          {error && <div className="error-banner" role="alert">{error}</div>}
          <button className="button primary" disabled={busy || !number.trim()}>{busy && <Spinner/>}{otherOrder ? '切换并进入订单' : '进入订单'}</button>
          {otherOrder && <button type="button" className="text-button" disabled={busy} onClick={() => { setOrder(otherOrder); setOtherOrder(null); setError(''); clearLink() }}>继续当前订单</button>}
        </form>}
    </main>
    <footer className="guest-footer">头像贴纸 · 客户预览</footer>
  </div>
}
