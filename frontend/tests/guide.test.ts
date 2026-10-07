import {afterEach,beforeEach,expect,test,vi} from 'vitest'

function fakeStorage(){const data=new Map<string,string>();return {getItem:(k:string)=>data.get(k)??null,setItem:(k:string,v:string)=>void data.set(k,v),removeItem:(k:string)=>void data.delete(k),get length(){return data.size},key:(i:number)=>[...data.keys()][i]??null,data}}
// Object.keys(localStorage) lists stored keys in browsers; the proxy below mimics that for replayGuides.
let storage:ReturnType<typeof fakeStorage>
beforeEach(()=>{
  vi.resetModules();storage=fakeStorage()
  const proxy=new Proxy(storage,{ownKeys:()=>[...storage.data.keys()],getOwnPropertyDescriptor:(_t,k)=>storage.data.has(String(k))?{enumerable:true,configurable:true,value:storage.data.get(String(k))}:undefined})
  vi.stubGlobal('window',{});vi.stubGlobal('navigator',{webdriver:false});vi.stubGlobal('localStorage',proxy)
})
afterEach(()=>vi.unstubAllGlobals())

test('我知道了 hides a tip for this visit only; 不再提示 hides it on this device',async()=>{
  const guide=await import('../src/lib/guide')
  expect(guide.guideHidden('a')).toBe(false)
  guide.acknowledgeGuide('a');expect(guide.guideHidden('a')).toBe(true)
  expect(storage.data.size).toBe(0)
  guide.muteGuide('b');expect(storage.data.get('guest-guide:b')).toBe('off')
  vi.resetModules()
  const reloaded=await import('../src/lib/guide')
  expect(reloaded.guideHidden('a')).toBe(false)
  expect(reloaded.guideHidden('b')).toBe(true)
})

test('操作指引 replays every tip and keeps only the test switch',async()=>{
  const guide=await import('../src/lib/guide')
  storage.setItem('guest-guide:force','1')
  guide.muteGuide('b');guide.acknowledgeGuide('a')
  const heard=vi.fn();const stop=guide.subscribeGuide(heard)
  guide.replayGuides()
  expect(guide.guideHidden('a')).toBe(false);expect(guide.guideHidden('b')).toBe(false)
  expect([...storage.data.keys()]).toEqual(['guest-guide:force']);expect(heard).toHaveBeenCalled();stop()
})

test('automated browsers skip the walkthrough unless a test forces it',async()=>{
  vi.stubGlobal('navigator',{webdriver:true})
  const guide=await import('../src/lib/guide')
  expect(guide.guideHidden('a')).toBe(true)
  storage.setItem('guest-guide:force','1')
  expect(guide.guideHidden('a')).toBe(false)
})
