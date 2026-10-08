import {test,expect,type Route} from '@playwright/test'
import {randomUUID} from 'node:crypto'
import {createCustomer,staffLogin} from './customer-fixtures'
// Rewritten responses need the full body: drop the page's If-None-Match so the server never answers 304.
const fresh=(route:Route)=>Object.fromEntries(Object.entries(route.request().headers()).filter(([name])=>name!=='if-none-match'))

test('seller remark is read-only, fetched from Pinduoduo per order or in bulk; buyer memo is gone',async({page})=>{
  await staffLogin(page.request)
  const tag=randomUUID().slice(0,6).toUpperCase()
  const linked=await createCustomer(page.request,{order_number:`RMK-${tag}-A`,final_count:2,generation_limit:4})
  const manual=await createCustomer(page.request,{order_number:`RMK-${tag}-B`})
  // The test backend has no Pinduoduo shop: present the first order as linked, as the API does for Agiso orders.
  let remark='开户时备注'
  const decorate=(order:any)=>order.id===linked.id?{...order,shop_id:'shop-1',shop_name:'草木造物',platform:'pdd',platform_editable:false,remark_supported:true,platform_remark:remark,buyer_memo:undefined}:order
  await page.route('**/api/customer-orders?summary=1*',async route=>{const response=await route.fetch({headers:fresh(route)});route.fulfill({response,json:(await response.json()).map(decorate)})})
  await page.route(`**/api/customer-orders/${linked.id}`,async route=>{const response=await route.fetch({headers:fresh(route)});route.fulfill({response,json:decorate(await response.json())})})
  const requested:string[][]=[]
  await page.route('**/api/customer-orders/remarks/sync',async route=>{
    const ids=route.request().postDataJSON().ids as string[];requested.push(ids);remark='客服后加的备注'
    await route.fulfill({json:{results:ids.map(id=>({id,order_number:linked.order_number,status:'updated',remark}))}})
  })
  await page.goto('/')
  await page.getByPlaceholder('搜索订单号').fill(`RMK-${tag}`)
  const rows=page.locator('.customer-order-row')
  await expect(rows).toHaveCount(2)
  const linkedRow=rows.filter({hasText:linked.order_number}),manualRow=rows.filter({hasText:manual.order_number})
  await expect(linkedRow).toContainText('卖家备注：开户时备注');await expect(linkedRow).toContainText('可提交印刷 2 张')
  await expect(page.getByText('买家备注')).toHaveCount(0)
  // Only Pinduoduo orders offer the fetch; bulk selection counts linked orders only.
  await expect(manualRow.getByRole('button',{name:'获取卖家备注'})).toHaveCount(0)
  await page.getByLabel('全选当前订单').check()
  const bulk=page.getByRole('button',{name:'获取卖家备注 (1)'})
  await bulk.click()
  await expect.poll(()=>requested).toEqual([[linked.id]])
  await expect(page.getByText('卖家备注：更新 1 个，无变化 0 个')).toBeVisible()
  await expect(linkedRow).toContainText('卖家备注：客服后加的备注')
  // Single-order fetch from the row; the detail shows the source and no edit entry.
  await linkedRow.getByRole('button',{name:'获取卖家备注'}).click()
  await expect.poll(()=>requested.length).toBe(2);expect(requested[1]).toEqual([linked.id])
  await linkedRow.getByRole('button',{name:'进入 / 代操作'}).click()
  const dialog=page.getByRole('dialog',{name:'订单 '+linked.order_number})
  await expect(dialog).toContainText('卖家备注：客服后加的备注');await expect(dialog).toContainText('来自拼多多，打印在每页订单号后')
  await expect(dialog.getByRole('button',{name:'修改',exact:true})).toHaveCount(0)
  await expect(dialog).toContainText('可提交印刷 2 张')
})
