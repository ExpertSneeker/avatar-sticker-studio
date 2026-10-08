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

it('specification defaults take the largest complete quantity and preserve unmatched quotas', async () => {
  const { withSpecDefaults, newSkuRule } = await import('../src/lib/agiso')
  expect(newSkuRule().enabled).toBe(true)
  for (const [name, quotas] of [
    ['1张',[3,1,1]],['6个',[8,6,3]],['12张',[16,12,6]],
    ['18个',[24,18,7]],['18张赠6个',[24,18,7]],['24个',[30,24,9]],['30张',[35,30,12]],['36个',[42,36,15]],
    ['42张',[50,42,18]],['42个+赠送6张',[50,42,18]],
  ] as const) {
    const next=withSpecDefaults({...rule,sku_name:name})
    expect([next.generation_limit,next.final_count,next.rerun_limit]).toEqual(quotas)
    expect(next.enabled).toBe(false)
  }
  for (const sku_name of ['16张','61个','1.6张','10张','6套','']) {
    expect(withSpecDefaults({...rule,sku_name})).toEqual({...rule,sku_name})
  }
})

it('rule ids follow each platform: digits for Pinduoduo/Douyin, hex for Xiaohongshu (SKU unique)',()=>{
  const base={goods_name:'',sku_name:'',generation_limit:16,final_count:12,rerun_limit:6,enabled:true}
  const xhs={...base,goods_id:'6ac795ef7dbca2000160f981',sku_id:'6ac795ef7dbca2000160f99d'}
  expect(ruleError([xhs],'xhs')).toBe('')
  expect(ruleError([xhs],'pdd')).toContain('真实的商品 ID')
  expect(ruleError([xhs,{...xhs,goods_id:'other0'}],'xhs')).toContain('SKU 重复')
  expect(ruleError([{...xhs,sku_id:'bad id'}],'xhs')).toContain('真实的商品 ID')
  expect(ruleError([{...base,goods_id:'1721288561899563',sku_id:'1721288561899566'}],'douyin')).toBe('')
})
