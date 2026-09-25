import {test,expect} from '@playwright/test'
import {createCustomer,staffLogin} from './customer-fixtures'

test('history renders 50 rows at a time while filters and select-all cover every match',async({page})=>{
  await staffLogin(page.request)
  const base=await createCustomer(page.request)
  // Isolate the list UI: 60 synthetic summaries (newest first), with overview thumbnails.
  const rows=Array.from({length:60},(_,i)=>({...base,id:`paging-${i}`,order_number:`PAGE-${String(i).padStart(2,'0')}`,state:'submitted',delivery_ready:false,
    preview_url:`/api/customer-orders/paging-${i}/media/${'a'.repeat(32)}?v=1`}))
  await page.route(/\/api\/customer-orders\?summary=1$/,route=>route.fulfill({json:rows}))
  await page.route(/\/api\/customer-orders\/paging-\d+\/media\//,route=>route.fulfill({status:404}))
  await page.goto('/')
  await page.getByRole('navigation').getByRole('button',{name:'历史订单',exact:true}).click()
  const list=page.locator('.customer-order-row')
  await expect(list).toHaveCount(50)
  const thumb=page.locator('.customer-order-thumb img').first()
  await expect(thumb).toHaveAttribute('loading','lazy')
  expect(await thumb.getAttribute('src')).toMatch(/[?&]size=160$/)
  await page.getByLabel('全选当前订单').check()
  await expect(page.getByText('已选 60 个')).toBeVisible()
  await page.getByRole('button',{name:'显示更多（还有 10 个）'}).click()
  await expect(list).toHaveCount(60)
  await expect(page.getByRole('button',{name:/显示更多/})).toHaveCount(0)
  // Changing a filter starts again from the first page of matches.
  await page.getByLabel('订单号',{exact:true}).fill('PAGE-5')
  await expect(list).toHaveCount(10)
  await page.getByLabel('订单号',{exact:true}).fill('')
  await expect(list).toHaveCount(50)
})
