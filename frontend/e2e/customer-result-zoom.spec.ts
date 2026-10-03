import {test,expect} from '@playwright/test'
import {randomUUID} from 'node:crypto'
import {uploadStickers} from './library-fixtures'
import {createCustomer,mutate,pixel,staffLogin,uploadAvatar} from './customer-fixtures'

test('result cards zoom the generated sticker without toggling the final selection',async({page})=>{
  await staffLogin(page.request)
  const [sticker]=await uploadStickers(page.request,[{name:`ZOOMR-${randomUUID().slice(0,8)}.png`,mimeType:'image/png',buffer:pixel}])
  let order=await createCustomer(page.request,{generation_limit:2,final_count:1})
  order=await mutate(page.request,order,'generate',{avatars:[{upload_id:await uploadAvatar(page.request),template_ids:[],sticker_ids:[sticker.id,sticker.id]}]})
  await expect.poll(async()=>{order=await(await page.request.get('/api/customer-orders/'+order.id)).json();return order.slots.every((slot:any)=>!!slot.selected_version_id)},{timeout:60000}).toBe(true)
  const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message))
  await page.goto('/guest')
  await page.getByLabel('订单号',{exact:true}).fill(order.order_number);await page.getByRole('button',{name:'进入订单'}).click()
  for(const [width,height] of [[1280,900],[390,844]]){
    await page.setViewportSize({width,height})
    const card=page.locator('.customer-result').first()
    await expect(card.locator('.customer-result-image img')).toBeVisible()
    await card.getByRole('button',{name:'放大查看第 1 张'}).click()
    const zoom=page.getByRole('dialog',{name:`${sticker.code} · 第 1 张`})
    const image=zoom.locator('.media-frame img')
    await expect(image).toHaveAttribute('src',/size=1024/)
    await expect.poll(()=>image.evaluate((el:HTMLImageElement)=>el.complete&&el.naturalWidth)).toBeGreaterThan(0)
    // The viewer fits the screen without scrolling.
    expect(await zoom.evaluate(el=>el.scrollHeight-el.clientHeight)).toBeLessThanOrEqual(1)
    await page.evaluate(()=>Promise.allSettled(document.getAnimations().map(animation=>animation.finished)))
    await page.screenshot({path:`test-results/result-zoom-${width}.png`})
    await page.keyboard.press('Escape');await expect(zoom).toHaveCount(0)
    // Zooming never selects the card as a final result.
    await expect(page.getByLabel('选择成品 1')).not.toBeChecked()
    await expect(page.locator('.customer-selection-badge')).toHaveText('已选 0/1')
  }
  // Selecting by clicking the card still works.
  await page.locator('.customer-result').first().click()
  await expect(page.getByLabel('选择成品 1')).toBeChecked()
  expect(errors).toEqual([])
})
