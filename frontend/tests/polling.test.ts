import {afterEach,expect,test,vi} from 'vitest'
import {visiblePolling} from '../src/lib/polling'

function fakeDocument(state:'visible'|'hidden'){
  const listeners=new Set<()=>void>()
  const doc={visibilityState:state,addEventListener:(_:string,fn:()=>void)=>listeners.add(fn),removeEventListener:(_:string,fn:()=>void)=>listeners.delete(fn)}
  vi.stubGlobal('document',doc)
  return {set(next:'visible'|'hidden'){doc.visibilityState=next;listeners.forEach(fn=>fn())},listeners}
}
afterEach(()=>{vi.useRealTimers();vi.unstubAllGlobals()})

test('polls while visible, pauses while hidden and refreshes once on return',()=>{
  vi.useFakeTimers()
  const page=fakeDocument('visible'),tick=vi.fn()
  const stop=visiblePolling(tick,1000)
  vi.advanceTimersByTime(3000);expect(tick).toHaveBeenCalledTimes(3)
  page.set('hidden');vi.advanceTimersByTime(10000);expect(tick).toHaveBeenCalledTimes(3)
  page.set('visible');expect(tick).toHaveBeenCalledTimes(4)
  page.set('visible');expect(tick).toHaveBeenCalledTimes(4)
  vi.advanceTimersByTime(1000);expect(tick).toHaveBeenCalledTimes(5)
  stop();vi.advanceTimersByTime(5000);expect(tick).toHaveBeenCalledTimes(5);expect(page.listeners.size).toBe(0)
})

test('a tab opened in the background starts polling when first shown',()=>{
  vi.useFakeTimers()
  const page=fakeDocument('hidden'),tick=vi.fn()
  const stop=visiblePolling(tick,1000)
  vi.advanceTimersByTime(5000);expect(tick).not.toHaveBeenCalled()
  page.set('visible');expect(tick).toHaveBeenCalledTimes(1)
  vi.advanceTimersByTime(2000);expect(tick).toHaveBeenCalledTimes(3)
  stop()
})
