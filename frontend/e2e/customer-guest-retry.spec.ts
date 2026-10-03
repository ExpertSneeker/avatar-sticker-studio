import {test,expect} from '@playwright/test'
import {randomUUID} from 'node:crypto'
import {readFileSync} from 'node:fs'
import {uploadStickers} from './library-fixtures'
import {createCustomer,mutate,staffLogin,uploadAvatar} from './customer-fixtures'

// The browser-test provider fails this template's first generation as an unsent upload.
const failOnce=readFileSync(new URL('./fixtures/fail-once.png',import.meta.url))

for(const [width,height] of [[1280,900],[390,844]]){
  test(`guest sees a definite failure and retries it (${width}px)`,async({page})=>{
    await staffLogin(page.request)
    const [sticker]=await uploadStickers(page.request,[{name:`RETRY-${randomUUID().slice(0,8)}.png`,mimeType:'image/png',buffer:failOnce}])
    let order=await createCustomer(page.request,{generation_limit:1,final_count:1,rerun_limit:0})
    order=await mutate(page.request,order,'generate',{avatars:[{upload_id:await uploadAvatar(page.request),template_ids:[],sticker_ids:[sticker.id]}]})
    await expect.poll(async()=>(await(await page.request.get('/api/customer-orders/'+order.id)).json()).slots[0].status,{timeout:60000}).toBe('failed')
    const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message))
    await page.setViewportSize({width,height})
    await page.goto('/guest')
    await page.getByLabel('订单号',{exact:true}).fill(order.order_number);await page.getByRole('button',{name:'进入订单'}).click()
    const card=page.locator('.customer-result').first()
    await expect(card.locator('.error-text')).toHaveText('连接生成服务失败，可点击“重试生成”（还可重试 3 次）')
    const retry=card.getByRole('button',{name:'重试生成'})
    await expect(retry).toBeVisible()
    const box=await retry.boundingBox();expect(box!.x+box!.width).toBeLessThanOrEqual(width)
    await page.screenshot({path:`test-results/guest-retry-${width}.png`,fullPage:true})
    await retry.click()
    await expect(card.locator('.customer-result-image img')).toBeVisible({timeout:60000})
    await expect(card.getByRole('button',{name:'重试生成'})).toHaveCount(0)
    await expect(card.locator('.error-text')).toHaveCount(0)
    await expect(page.locator('.page-heading p')).toContainText('重试次数 0 / 0 次')
    expect(errors).toEqual([])
  })
}
