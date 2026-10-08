export interface AgisoStatus {
  configured: boolean
  missing: string[]
  authorization_callback_url: string | null
  webhook_url: string | null
  aftersales_enabled: boolean
  aftersales_platforms: PlatformKey[]
  platforms: PlatformInfo[]
}
export type PlatformKey = 'pdd' | 'douyin' | 'xhs'
export interface PlatformInfo { key: PlatformKey; label: string; connectable: boolean; remark_sync: boolean; apps?: { key: string; label: string }[] }
// Labels for orders and filters; the authorization switch per platform comes from /agiso/status.
export const PLATFORM_LABELS: Record<PlatformKey, string> = { pdd: '拼多多', douyin: '抖店', xhs: '小红书' }
export const PLATFORM_KEYS = Object.keys(PLATFORM_LABELS) as PlatformKey[]
// Hosts the authorization redirect may point to (docs/agiso-reference/README.md).
// Douyin has two Agiso apps: 自动发货 (aldsDoudian) and 虚拟自动发货 (aldsdd).
const AUTHORIZE_HOSTS: Record<PlatformKey, string[]> = { pdd: ['aldspdd.agiso.com'], douyin: ['aldsdoudian.agiso.com', 'aldsdd.agiso.com'], xhs: ['aldsxhs.agiso.com'] }
export function validAuthorizeUrl(platform: PlatformKey, value: string) {
  const url = new URL(value)
  return url.protocol === 'https:' && AUTHORIZE_HOSTS[platform].includes(url.hostname)
}
export interface Shop {
  id: string; shop_id: string; shop_name: string; owner: string; owner_name: string
  organization_id: string; enabled: boolean; authorized: boolean; expires_at: number | null
  last_event_at: number | null; can_manage: boolean
  platform: PlatformKey; platform_label: string; watermark: string
}
export interface SkuRule {
  goods_id: string; sku_id: string; goods_name: string; sku_name: string
  generation_limit: number; final_count: number; rerun_limit: number; enabled: boolean
}
// Kept in sync with backend/app/sku_defaults.py; both sides have contract tests.
const specQuotas: Partial<Record<number, readonly [number, number, number]>> = {
  42: [50, 42, 18], 36: [42, 36, 15], 30: [35, 30, 12],
  24: [30, 24, 9], 18: [24, 18, 7], 12: [16, 12, 6], 6: [8, 6, 3], 1: [3, 1, 1],
}
export function withSpecDefaults(rule: SkuRule): SkuRule {
  for (const quantity of [42, 36, 30, 24, 18, 12, 6, 1]) {
    if (new RegExp(`(?<![\\d.])${quantity}[个张]`).test(rule.sku_name)) {
      const quotas = specQuotas[quantity]
      if (!quotas) return rule
      const [generation_limit, final_count, rerun_limit] = quotas
      return { ...rule, generation_limit, final_count, rerun_limit }
    }
  }
  return rule
}
export function newSkuRule(): SkuRule {
  return { goods_id: '', sku_id: '', goods_name: '', sku_name: '', generation_limit: 10, final_count: 10, rerun_limit: 2, enabled: true }
}
export interface ShopOrder {
  id: string; order_number: string; customer_order_id: string | null; open_status: string
  message_status: string; guest_url: string | null; error: string | null
  created_at: number; entered_at: number | null; can_retry: boolean
}
export interface ShopEvent {
  id: string; topic: string | number; status: string; error: string | null
  received_at: number; order_number: string | null; can_replay: boolean
}
export interface GoodsPage {
  available: boolean; goods: { goods_id: string; goods_name: string; skus: { sku_id: string; sku_name: string }[] }[]
  total?: number; page?: number; message: string
}
export function ruleError(rules: SkuRule[]): string {
  const keys = new Set<string>()
  for (const [index, rule] of rules.entries()) {
    const label = `第 ${index + 1} 条规则：`
    if (!/^\d+$/.test(rule.goods_id) || !/^\d+$/.test(rule.sku_id)) return label + '请填写真实的商品 ID 和 SKU ID'
    const key = rule.goods_id + ':' + rule.sku_id
    if (keys.has(key)) return label + '商品和 SKU 重复'
    keys.add(key)
    if (![rule.generation_limit, rule.final_count, rule.rerun_limit].every(Number.isSafeInteger)) return label + '数量必须是整数'
    if (rule.generation_limit < 1 || rule.generation_limit > 360 || rule.final_count < 1 || rule.final_count > 360) return label + '生成和提交数量须为 1 至 360'
    if (rule.final_count > rule.generation_limit) return label + '可提交印刷数量不能超过生成数量'
    if (rule.rerun_limit < 0) return label + '整单重试次数不能小于 0'
  }
  return ''
}
export function guestLink(origin: string, number: string): string {
  const url = new URL('/guest', origin)
  url.searchParams.set('order_number', number)
  return url.toString()
}
export function integrationLabel(value: string): string {
  return ({ held: '售后处理中', received: '已接收', pending: '待处理', queued: '待发送', processing: '处理中', opened: '已开户', sent: '发送成功', failed: '处理失败', unknown: '结果待核对', manual: '待人工处理', ignored: '已忽略', completed: '已处理', processed: '已处理', cancelled: '已取消', paused: '已暂停', blocked: '已暂停', not_sent: '未发送', retry: '等待重试', retrying: '等待重试', ready: '待发送', skipped: '已跳过', none: '无', disabled: '已停用', fetch: '读取订单中', unmatched: '匹配店铺中' } as Record<string, string>)[value] || '待核对'
}

export function integrationError(value: string): string {
  return ({
    unmapped_sku: '该 SKU 尚未配置，请核对商品套餐后重新处理。',
    conflicting_rules: '套餐规则冲突，请人工核对。', quota_exceeded: '订单额度超过 360 张，请人工处理。',
    order_number_conflict: '订单号与已有订单冲突，请人工确认归属。',
    shop_disabled: '店铺自动开户已关闭。', authorization_expired: '店铺授权已失效，重新授权后会继续处理。',
    account_disabled: '负责账户已停用，请联系管理员。', aftersales_pending: '售后申请处理中，订单已暂停。',
    aftersales_review: '售后情况需要人工核对。', aftersales_disabled: '自动售后尚未启用，通知已保留。',
    refunded: '整单退款已成功，客户访问已取消。', send_unknown: '发送结果不确定，请先在平台聊天记录核对消息。',
    send_failed: '消息发送失败，请检查发送助手和店铺授权。',
    unsupported_topic: '该类型通知暂未参与自动处理，已记录在通知记录中。',
    order_unpaid: '平台订单尚未付款，不开户。', order_cancelled: '平台订单已取消或关闭，不开户。',
    order_lookup_failed: '多次读取平台订单详情失败，请核对店铺授权和订单号后重新处理。',
    unknown_shop: '通知中的店铺未匹配到已授权店铺，请确认该店铺已在本站授权。',
  } as Record<string, string>)[value] || '需要人工核对，请查看通知记录或联系管理员。'
}
