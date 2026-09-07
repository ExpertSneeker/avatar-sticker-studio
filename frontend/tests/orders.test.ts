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

import {dateFilterBounds,withinDateBounds,localDateInput} from '../src/lib/orders'

it('uses local calendar days with inclusive start and exclusive next midnight',()=>{
  const now=new Date(2026,8,7,12).getTime()
  const today=dateFilterBounds({mode:'today',date:'',start:'',end:''},now)
  expect(localDateInput(now)).toBe('2026-09-07')
  for(const time of [new Date(2026,8,7),new Date(2026,8,7,23,59,59,999)])expect(withinDateBounds(time.toISOString(),today)).toBe(true)
  for(const time of [new Date(2026,8,6,23,59,59,999),new Date(2026,8,8)])expect(withinDateBounds(time.toISOString(),today)).toBe(false)
  expect(dateFilterBounds({mode:'date',date:'2026-09-07',start:'',end:''},now)).toEqual(today)
})
it('includes both range dates, handles calendar boundaries and rejects incomplete or inverted ranges',()=>{
  const bounds=dateFilterBounds({mode:'range',date:'',start:'2026-12-31',end:'2027-01-02'})
  expect(withinDateBounds(new Date(2027,0,2,23,59,59,999).toISOString(),bounds)).toBe(true)
  expect(withinDateBounds(new Date(2027,0,3).toISOString(),bounds)).toBe(false)
  for(const [start,end] of [['2026-09-08','2026-09-07'],['','2026-09-07'],['2026-09-07',''],['2026-02-30','2026-03-02']]){
    const invalid=dateFilterBounds({mode:'range',date:'',start,end})
    expect(invalid.error).toBeTruthy()
    expect(withinDateBounds(new Date().toISOString(),invalid)).toBe(false)
  }
  expect(dateFilterBounds({mode:'date',date:'',start:'',end:''}).error).toBeTruthy()
  const dst=dateFilterBounds({mode:'date',date:'2026-03-08',start:'',end:''})
  expect(dst.end-dst.start).toBe(new Date(2026,2,9).getTime()-new Date(2026,2,8).getTime())
  const midnightShift=dateFilterBounds({mode:'date',date:'2018-11-04',start:'',end:''})
  expect(midnightShift.end).toBe(new Date(2018,10,5).getTime())
})
it('keeps rolling presets distinct from today and leaves all-time unrestricted',()=>{
  const now=new Date(2026,8,7,12).getTime(), yesterday=new Date(2026,8,6,18).toISOString()
  const filter={mode:'1',date:'',start:'',end:''}
  expect(withinDateBounds(yesterday,dateFilterBounds(filter,now))).toBe(true)
  expect(withinDateBounds(yesterday,dateFilterBounds({...filter,mode:'today'},now))).toBe(false)
  expect(withinDateBounds('invalid',dateFilterBounds(filter,now))).toBe(false)
  expect(withinDateBounds(new Date(now+1).toISOString(),dateFilterBounds(filter,now))).toBe(false)
  expect(withinDateBounds('2000-01-01T00:00:00Z',dateFilterBounds({...filter,mode:'0'},now))).toBe(true)
})
