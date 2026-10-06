import {afterEach,expect,test,vi} from 'vitest'
import {staffPolling,visiblePolling} from '../src/lib/polling'

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

test('staff pages check the account every 5 s but reload the large library only every minute',()=>{
  vi.useFakeTimers()
  const page=fakeDocument('visible'),account=vi.fn(),library=vi.fn()
  const stop=staffPolling(account,library)
  vi.advanceTimersByTime(55000);expect(account).toHaveBeenCalledTimes(11);expect(library).not.toHaveBeenCalled()
  vi.advanceTimersByTime(5000);expect(account).toHaveBeenCalledTimes(12);expect(library).toHaveBeenCalledTimes(1)
  page.set('hidden');vi.advanceTimersByTime(300000);expect(account).toHaveBeenCalledTimes(12);expect(library).toHaveBeenCalledTimes(1)
  // Returning to the tab shows fresh library data immediately, not after another minute.
  page.set('visible');expect(account).toHaveBeenCalledTimes(13);expect(library).toHaveBeenCalledTimes(2)
  stop();vi.advanceTimersByTime(120000);expect(library).toHaveBeenCalledTimes(2);expect(page.listeners.size).toBe(0)
})
