import {test,expect} from '@playwright/test'
import {randomUUID} from 'node:crypto'
import {uploadStickers} from './library-fixtures'
import {createCustomer,pixel,staffLogin} from './customer-fixtures'

test('mobile picker opens on single stickers and keeps filters and apply pinned while scrolling',async({page})=>{
  await page.setViewportSize({width:390,height:700})
  await staffLogin(page.request)
  const suffix=randomUUID().slice(0,8)
  const stickers=await uploadStickers(page.request,Array.from({length:12},(_,i)=>({name:`SCROLL-${suffix}-${i}.png`,mimeType:'image/png',buffer:pixel})))
  const order=await createCustomer(page.request,{generation_limit:18,final_count:15})
  const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message))
  await page.goto('/guest')
  await page.getByLabel('订单号',{exact:true}).fill(order.order_number)
  await page.getByRole('button',{name:'进入订单'}).click()
  await page.getByLabel('上传头像').setInputFiles({name:'avatar.png',mimeType:'image/png',buffer:pixel})
  await page.getByRole('button',{name:'选择模板和贴纸'}).click()
  const picker=page.getByRole('dialog',{name:'选择模板和贴纸'})
  await expect(picker.getByRole('button',{name:'单张贴纸',exact:true})).toHaveClass(/active/)
  await picker.getByLabel('搜索模板或贴纸').fill(suffix)
  await expect(picker.locator('.customer-catalog article')).toHaveCount(12)
  // The whole dialog (pinned tabs on top, apply bar at the bottom) fits the visible screen.
  await page.evaluate(()=>Promise.allSettled(document.getAnimations().map(animation=>animation.finished)))
  const box=(await picker.boundingBox())!
  expect(box.y).toBeGreaterThanOrEqual(0);expect(box.y+box.height).toBeLessThanOrEqual(700)
  await picker.getByLabel(stickers[0].code+' 份数',{exact:true}).fill('18')
  expect(await picker.locator('.customer-catalog').evaluate(el=>getComputedStyle(el).overflowY)).toBe('visible')
  await picker.locator('.customer-catalog article').first().hover()
  // Mid-list: tabs, search, category and the apply bar all stay usable without scrolling back.
  await page.mouse.wheel(0,400)
  await expect.poll(()=>picker.evaluate(el=>el.scrollTop)).toBeGreaterThan(200)
  for(const control of [picker.getByLabel('搜索模板或贴纸'),picker.getByLabel('贴纸分类'),picker.getByRole('button',{name:'模板套装',exact:true}),picker.getByRole('button',{name:'应用选择'}),picker.getByText('订单共 18 / 18 张')])await expect(control).toBeInViewport({ratio:1})
  await page.screenshot({path:'test-results/customer-picker-sticky-mobile.png'})
  await page.mouse.wheel(0,10000)
  await expect(picker.getByRole('button',{name:'应用选择'})).toBeInViewport()
  await expect(picker.getByLabel('搜索模板或贴纸')).toBeInViewport({ratio:1})
  await page.screenshot({path:'/tmp/customer-picker-scroll-mobile.png'})
  await picker.getByRole('button',{name:'应用选择'}).click()
  await page.getByRole('button',{name:'核对并开始生成'}).click()
  const check=page.getByRole('dialog',{name:'生成前核对'})
  await expect(check.locator('.customer-counts>div').filter({hasText:'可提交印刷'})).toHaveText('可提交印刷15')
  await expect(check.getByText('实际生成',{exact:true})).toHaveCount(0)
  await page.screenshot({path:'/tmp/customer-preflight-mobile.png'})
  expect(errors).toEqual([])
})
