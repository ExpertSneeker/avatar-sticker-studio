import {test,expect} from '@playwright/test'
import {randomUUID} from 'node:crypto'
import {uploadStickers} from './library-fixtures'
import {completedCustomer,createCustomer,mutate,pixel,staffLogin} from './customer-fixtures'

test('order row buttons stack in right-aligned columns of two on wide screens',async({page})=>{
  await staffLogin(page.request)
  const tag=randomUUID().slice(0,6).toUpperCase()
  const [sticker]=await uploadStickers(page.request,[{name:`ACT-${tag}.png`,mimeType:'image/png',buffer:pixel}])
  const submitted=await completedCustomer(page.request,sticker.id,{order_number:`ACT-${tag}-1`})
  await createCustomer(page.request,{order_number:`ACT-${tag}-2`})
  const cancelled=await createCustomer(page.request,{order_number:`ACT-${tag}-3`});await mutate(page.request,cancelled,'cancel')
  // Present the submitted order as a Pinduoduo order so it shows every button (7).
  await page.route('**/api/customer-orders?summary=1',async route=>{const response=await route.fetch();route.fulfill({response,json:(await response.json()).map((o:any)=>o.id===submitted.id?{...o,shop_id:'shop-1',shop_name:'草木造物',platform_remark:'66666666aaaaa [pdd73050906494 10/04 23:52]'}:o)})})
  await page.setViewportSize({width:1440,height:1000})
  await page.goto('/')
  await page.getByRole('navigation').getByRole('button',{name:'历史订单',exact:true}).click()
  await page.getByPlaceholder('搜索订单号').fill(`ACT-${tag}`)
  const rows=page.locator('.customer-order-row');await expect(rows).toHaveCount(3)
  const layout=(n:number)=>rows.nth(n).evaluate(row=>{
    const actions=row.querySelector('.customer-order-actions')!,buttons=[...actions.children].map(b=>b.getBoundingClientRect())
    const lefts=new Set(buttons.map(b=>Math.round(b.left)))
    return {count:buttons.length,columns:lefts.size,maxPerColumn:Math.max(...[...lefts].map(l=>buttons.filter(b=>Math.round(b.left)===l).length)),
      rightGap:row.getBoundingClientRect().right-actions.getBoundingClientRect().right,infoWidth:row.querySelector('.customer-order-open')!.getBoundingClientRect().width}
  })
  const order=async(number:string)=>{for(let i=0;i<3;i++)if((await rows.nth(i).textContent())!.includes(number))return i;throw new Error(number)}
  const full=await layout(await order(`ACT-${tag}-1`))
  expect(full).toMatchObject({count:7,columns:4,maxPerColumn:2})
  expect(full.rightGap).toBeLessThan(30);expect(full.infoWidth).toBeGreaterThan(280)
  const draft=await layout(await order(`ACT-${tag}-2`))
  expect(draft.columns).toBe(2);expect(draft.maxPerColumn).toBe(2);expect(draft.rightGap).toBeLessThan(30)
  await page.screenshot({path:'test-results/order-actions-1440.png',fullPage:true})
  // Mid-width screens: when the details would get too narrow, the buttons move below them, still right aligned.
  await page.setViewportSize({width:1180,height:900})
  const mid=await layout(await order(`ACT-${tag}-1`))
  expect(mid.infoWidth).toBeGreaterThan(280);expect(mid.rightGap).toBeLessThan(30)
  expect(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth)).toBe(false)
  await page.screenshot({path:'test-results/order-actions-1180.png',fullPage:true})
  await page.setViewportSize({width:390,height:844})
  expect(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth)).toBe(false)
  await page.screenshot({path:'test-results/order-actions-390.png',fullPage:true})
})
