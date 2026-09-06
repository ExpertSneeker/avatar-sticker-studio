import { expect,it } from 'vitest'
import { withinPeriod } from '../src/lib/orders'

it('uses rolling inclusive time windows and rejects invalid or future dates',()=>{
  const now=Date.parse('2026-09-06T12:00:00Z')
  expect(withinPeriod('2026-09-05T12:00:00Z',1,now)).toBe(true)
  expect(withinPeriod('2026-09-05T11:59:59Z',1,now)).toBe(false)
  for(const days of [3,7,30])expect(withinPeriod(new Date(now-days*86400000).toISOString(),days,now)).toBe(true)
  expect(withinPeriod('invalid',3,now)).toBe(false)
  expect(withinPeriod('2026-09-07T12:00:00Z',1,now)).toBe(false)
})
