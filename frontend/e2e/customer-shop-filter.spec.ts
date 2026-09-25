import {test,expect} from '@playwright/test'
import {createCustomer,staffLogin} from './customer-fixtures'

test('workbench and history filter orders by associated shop',async({page})=>{
  await staffLogin(page.request)
  const orders=await Promise.all([createCustomer(page.request),createCustomer(page.request),createCustomer(page.request)])
  // Isolate the UI contract; backend association is covered by test_agiso.py.
  const rows=orders.map((o,i)=>({...o,shop_id:i<2?'shop-'+i:null,shop_name:i<2?'测试店铺'+i:''}))
  // The list polls summaries (?summary=1); order detail stays unmocked.
  await page.route(/\/api\/customer-orders(\?summary=1)?$/,route=>route.fulfill({json:rows}))
  await page.goto('/')
  for(const history of [false,true]){
    if(history)await page.getByRole('navigation').getByRole('button',{name:'历史订单',exact:true}).click()
    const filter=page.getByLabel('店铺',{exact:true})
    await filter.selectOption('shop-0')
    await expect(page.locator('.customer-order-row')).toHaveCount(1)
    await expect(page.locator('.customer-order-row')).toContainText(orders[0].order_number)
    await expect(page.locator('.customer-order-row')).toContainText('店铺：测试店铺0')
    await filter.selectOption('none')
    await expect(page.locator('.customer-order-row')).toHaveCount(1)
    await expect(page.locator('.customer-order-row')).toContainText(orders[2].order_number)
    await filter.selectOption('all')
    await expect(page.locator('.customer-order-row')).toHaveCount(3)
  }
})
