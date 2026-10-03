import {test,expect} from '@playwright/test'
import {randomUUID} from 'node:crypto'
import {uploadStickers} from './library-fixtures'
import {createCustomer,pixel,staffLogin} from './customer-fixtures'

test('pre-generation check shows each avatar with its chosen template and sticker previews and quantities',async({page})=>{
  await staffLogin(page.request)
  const suffix=randomUUID().slice(0,6).toUpperCase()
  const stickers=await uploadStickers(page.request,[0,1,2,3].map(i=>({name:`PF${suffix}-${i}.png`,mimeType:'image/png',buffer:pixel})))
  const set=await page.request.post('/api/templates',{data:{code:`PFSET-${suffix}`,name:'核对套装',category:'general',sticker_ids:stickers.slice(0,3).map(s=>s.id)}});expect(set.ok(),await set.text()).toBeTruthy()
  const order=await createCustomer(page.request,{generation_limit:10,final_count:2})
  const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message))
  await page.goto('/guest')
  await page.getByLabel('订单号',{exact:true}).fill(order.order_number);await page.getByRole('button',{name:'进入订单'}).click()
  await page.getByLabel('上传头像').setInputFiles([{name:'一号.png',mimeType:'image/png',buffer:pixel},{name:'二号.png',mimeType:'image/png',buffer:pixel}])
  await expect(page.locator('.customer-avatar-row')).toHaveCount(2)
  const picker=page.getByRole('dialog',{name:'选择模板和贴纸'})
  await page.getByRole('button',{name:'选择模板和贴纸'}).nth(0).click()
  await picker.getByRole('button',{name:'模板套装',exact:true}).click()
  await picker.getByLabel('搜索模板或贴纸').fill(suffix)
  await picker.getByLabel(`PFSET-${suffix} 份数`,{exact:true}).fill('1')
  await picker.getByRole('button',{name:'单张贴纸',exact:true}).click()
  await picker.getByLabel(stickers[3].code+' 份数',{exact:true}).fill('2')
  await picker.getByRole('button',{name:'应用选择'}).click()
  await page.getByRole('button',{name:'选择模板和贴纸'}).nth(1).click()
  await picker.getByLabel('搜索模板或贴纸').fill(suffix)
  await picker.getByLabel(stickers[0].code+' 份数',{exact:true}).fill('1')
  await picker.getByRole('button',{name:'应用选择'}).click()
  for(const [width,height] of [[1280,900],[390,844]]){
    await page.setViewportSize({width,height})
    await page.getByRole('button',{name:'核对并开始生成'}).click()
    const check=page.getByRole('dialog',{name:'生成前核对'})
    const first=check.getByRole('region',{name:'头像 1 的选择'}),second=check.getByRole('region',{name:'头像 2 的选择'})
    await expect(first).toContainText('共 5 张');await expect(second).toContainText('共 1 张')
    // Template first (mosaic of its stickers), then single stickers, each with its quantity.
    await expect(first.locator('li')).toHaveCount(2)
    await expect(first.locator('li').nth(0)).toContainText('核对套装');await expect(first.locator('li').nth(0)).toContainText('1 套 · 每套 3 张')
    await expect(first.locator('li').nth(0).locator('img')).toHaveCount(3)
    await expect(first.locator('li').nth(0).getByLabel('数量 1')).toBeVisible()
    await expect(first.locator('li').nth(1)).toContainText('2 张');await expect(first.locator('li').nth(1).getByLabel('数量 2')).toBeVisible()
    await expect(second.locator('li')).toHaveCount(1);await expect(second.locator('li')).toContainText(stickers[0].code)
    const images=check.locator('.customer-preflight-avatar img')
    await expect.poll(()=>images.evaluateAll(list=>(list as HTMLImageElement[]).every(image=>image.complete&&image.naturalWidth>0))).toBe(true)
    await page.evaluate(()=>Promise.allSettled(document.getAnimations().map(animation=>animation.finished)))
    await page.screenshot({path:`test-results/preflight-preview-${width}.png`})
    // The confirm button stays reachable at the bottom of a long check.
    await expect(check.getByRole('button',{name:'确认开始生成'})).toBeInViewport({ratio:1})
    expect(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth)).toBe(false)
    await check.getByRole('button',{name:'返回调整'}).click();await expect(check).toHaveCount(0)
  }
  expect(errors).toEqual([])
})
