import { expect, it } from 'vitest'
import { ruleError, guestLink, integrationError, type SkuRule } from '../src/lib/agiso'
const rule: SkuRule = { goods_id:'123',sku_id:'456',goods_name:'补差价专用',sku_name:'10张',generation_limit:10,final_count:10,rerun_limit:2,enabled:false }
it('requires real unique identifiers and valid quotas before saving', () => {
  expect(ruleError([rule])).toBe('')
  expect(ruleError([{...rule,sku_id:''}])).toContain('SKU ID')
  expect(ruleError([rule,{...rule}])).toContain('重复')
  expect(ruleError([{...rule,generation_limit:361}])).toContain('360')
  expect(ruleError([{...rule,final_count:11}])).toContain('超过')
  expect(ruleError([{...rule,rerun_limit:1.5}])).toContain('整数')
})
it('guest links encode order numbers as one query parameter', () => {
  expect(guestLink('https://studio.example','A&B')).toBe('https://studio.example/guest?order_number=A%26B')
})

it('integration failures use safe Chinese recovery guidance', () => {
  expect(integrationError('unmapped_sku')).toContain('SKU')
  expect(integrationError('send_unknown')).toContain('核对')
  expect(integrationError('provider response with token')).toBe('需要人工核对，请查看通知记录或联系管理员。')
})
