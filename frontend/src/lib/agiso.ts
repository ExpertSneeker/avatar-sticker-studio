export interface AgisoStatus {
  configured: boolean
  missing: string[]
  authorization_callback_url: string | null
  webhook_url: string | null
  aftersales_enabled: boolean
}
export interface Shop {
  id: string; shop_id: string; shop_name: string; owner: string; owner_name: string
  organization_id: string; enabled: boolean; authorized: boolean; expires_at: number | null
  last_event_at: number | null; can_manage: boolean
}
export interface SkuRule {
  goods_id: string; sku_id: string; goods_name: string; sku_name: string
  generation_limit: number; final_count: number; rerun_limit: number; enabled: boolean
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
    if (rule.final_count > rule.generation_limit) return label + '最终提交数量不能超过生成数量'
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
  return ({ held: '售后处理中', received: '已接收', pending: '待处理', queued: '待发送', processing: '处理中', opened: '已开户', sent: '发送成功', failed: '处理失败', unknown: '结果待核对', manual: '待人工处理', ignored: '已忽略', completed: '已处理', processed: '已处理', cancelled: '已取消', paused: '已暂停', blocked: '已暂停', not_sent: '未发送', retry: '等待重试', retrying: '等待重试', ready: '待发送', skipped: '已跳过', none: '无', disabled: '已停用' } as Record<string, string>)[value] || '待核对'
}

export function integrationError(value: string): string {
  return ({
    unmapped_sku: '该 SKU 尚未配置，请核对商品套餐后重新处理。',
    conflicting_rules: '套餐规则冲突，请人工核对。', quota_exceeded: '订单额度超过 360 张，请人工处理。',
    order_number_conflict: '订单号与已有订单冲突，请人工确认归属。',
    shop_disabled: '店铺自动开户已关闭。', authorization_expired: '店铺授权已失效，重新授权后会继续处理。',
    account_disabled: '负责账户已停用，请联系管理员。', aftersales_pending: '售后申请处理中，订单已暂停。',
    aftersales_review: '售后情况需要人工核对。', aftersales_disabled: '自动售后尚未启用，通知已保留。',
    refunded: '整单退款已成功，客户访问已取消。', send_unknown: '发送结果不确定，请先在拼多多核对消息。',
    send_failed: '消息发送失败，请检查发送助手和店铺授权。',
    unsupported_topic: '该类型通知暂未参与自动处理，已记录在通知记录中。',
  } as Record<string, string>)[value] || '需要人工核对，请查看通知记录或联系管理员。'
}
