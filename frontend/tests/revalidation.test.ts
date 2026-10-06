import {afterEach,expect,test,vi} from 'vitest'
import {api, expectUser} from '../src/lib/api'

afterEach(()=>{vi.unstubAllGlobals();expectUser(null)})

test('an unchanged poll sends the remembered ETag and reuses the body from memory',async()=>{
  const sent:(string|null)[]=[],modes:(RequestCache|undefined)[]=[]
  const replies=[
    ()=>new Response(JSON.stringify([{id:'a'}]),{status:200,headers:{'Content-Type':'application/json','ETag':'W/"one"'}}),
    ()=>new Response(null,{status:304,headers:{'ETag':'W/"one"'}}),
    ()=>new Response(JSON.stringify([{id:'b'}]),{status:200,headers:{'Content-Type':'application/json','ETag':'W/"two"'}}),
  ]
  vi.stubGlobal('fetch',vi.fn(async(_url:string,init:RequestInit)=>{sent.push(new Headers(init.headers).get('If-None-Match'));modes.push(init.cache);return replies[sent.length-1]()}))
  expectUser('u1')
  expect(await api('/stickers')).toEqual([{id:'a'}])
  expect(await api('/stickers')).toEqual([{id:'a'}])
  expect(await api('/stickers')).toEqual([{id:'b'}])
  expect(sent).toEqual([null,'W/"one"','W/"one"'])
  expect(modes).toEqual(['no-store','no-store','no-store'])
})

test('switching account forgets remembered bodies',async()=>{
  const sent:(string|null)[]=[]
  vi.stubGlobal('fetch',vi.fn(async(_url:string,init:RequestInit)=>{sent.push(new Headers(init.headers).get('If-None-Match'));return new Response('[]',{status:200,headers:{'Content-Type':'application/json','ETag':'W/"x"'}})}))
  expectUser('u1');await api('/stickers')
  expectUser('u2');await api('/stickers')
  expect(sent).toEqual([null,null])
})
