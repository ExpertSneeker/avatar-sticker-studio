import { test, expect } from '@playwright/test'
import { createHash } from 'node:crypto'
import { pixel } from './customer-fixtures'

test('OSS browser download omits cookies, renews once and falls back with a slower-server status',async({page,context})=>{
  const sha256=createHash('sha256').update(pixel).digest('hex')
  let signature='initial'
  const requests:{url:string;cookie:string|undefined}[]=[]
  await page.route('**/api/customer-orders/oss-browser/manifest',async route=>{
    await route.fulfill({json:{order_id:'oss-browser',name:'OSS浏览器测试',version:1,complete:true,files:[{
      id:'synthetic-print',path:'a.png',kind:'print',size:pixel.length,sha256,
      url:'http://127.0.0.1:9999/oss-print/a.png?signature='+signature,local_url:'/api/oss-browser-local.png',
    }]}})
  })
  await page.route('http://127.0.0.1:9999/oss-print/**',async route=>{
    const request=route.request()
    requests.push({url:request.url(),cookie:request.headers().cookie})
    signature='renewed'
    await route.fulfill({status:403,headers:{'Access-Control-Allow-Origin':new URL(page.url()).origin},body:'expired'})
  })
  await page.route('**/api/oss-browser-local.png',async route=>{
    const request=route.request()
    requests.push({url:request.url(),cookie:request.headers().cookie})
    await route.fulfill({contentType:'image/png',body:pixel})
  })
  await page.goto('/')
  await context.addCookies([{name:'synthetic-delivery-cookie',value:'present',url:page.url()}])
  const saved=await page.evaluate(async()=>{
    const devicePath='/src/lib/device.ts'
    const {syncOrder}=await import(/* @vite-ignore */ devicePath)
    const root=await(await navigator.storage.getDirectory()).getDirectoryHandle('oss-browser-output',{create:true})
    const progress:string[]=[]
    await syncOrder('synthetic-user','oss-browser',root,(message:string)=>progress.push(message),{manifestPath:'/customer-orders/oss-browser/manifest'})
    const directory=await root.getDirectoryHandle('OSS浏览器测试')
    const file=await(await directory.getFileHandle('a.png')).getFile()
    const digest=await crypto.subtle.digest('SHA-256',await file.arrayBuffer())
    return {progress,sha256:Array.from(new Uint8Array(digest),b=>b.toString(16).padStart(2,'0')).join('')}
  })
  expect(requests.map(request=>new URL(request.url).pathname+new URL(request.url).search)).toEqual([
    '/oss-print/a.png?signature=initial','/oss-print/a.png?signature=renewed','/api/oss-browser-local.png',
  ])
  expect(requests.slice(0,2).every(request=>!request.cookie)).toBe(true)
  expect(requests[2].cookie).toContain('synthetic-delivery-cookie=present')
  expect(saved.sha256).toBe(sha256)
  expect(saved.progress.some(message=>message.includes('从 OSS 下载'))).toBe(true)
  expect(saved.progress.some(message=>message.includes('服务器下载')&&message.includes('较慢'))).toBe(true)
})
