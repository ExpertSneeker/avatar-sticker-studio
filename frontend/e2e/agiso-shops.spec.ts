import { expect, test } from '@playwright/test'
import { staffLogin } from './customer-fixtures'

test('套餐必须填真实 ID，保存精确额度，消息结果不确定时没有重试入口', async ({ page }) => {
  await staffLogin(page.request)
  const shop = { id:'local-shop',shop_id:'10001',shop_name:'草木造物（本地模拟）',owner:'test-owner',owner_name:'测试账户',organization_id:'org',enabled:false,authorized:true,expires_at:1900000000,last_event_at:null,can_manage:true }
  let saved: unknown = null
  let configured = true
  await page.route('**/api/agiso/**', async route => {
    const path = new URL(route.request().url()).pathname
    if (path.endsWith('/status')) return route.fulfill({ json: { configured,missing:[],authorization_callback_url:null,webhook_url:null,aftersales_enabled:false } })
    if (path.endsWith('/shops')) return route.fulfill({ json: [shop] })
    if (path.endsWith('/rules')) {
      if (route.request().method() === 'PUT') saved = route.request().postDataJSON().rules
      return route.fulfill({ json: saved || [] })
    }
    if (path.endsWith('/events')) return route.fulfill({ json: [] })
    if (path.endsWith('/orders')) return route.fulfill({ json: [{ id:'local-order',order_number:'LOCAL-TEST',customer_order_id:'customer',open_status:'opened',message_status:'unknown',guest_url:'http://127.0.0.1/guest?order_number=LOCAL-TEST',error:'send_unknown',created_at:1800000000,entered_at:null,can_retry:false }] })
    return route.fulfill({ status:404,json:{detail:'Unexpected test request'} })
  })
  await page.goto('/')
  await page.getByRole('button', { name: '店铺接入', exact: true }).click()
  await page.getByRole('button', { name: '填入 10张 / 20张测试套餐' }).click()
  await expect(page.getByLabel('每件可生成 2', { exact:true })).toHaveValue('20')
  await expect(page.getByRole('button', { name: '开启自动开户' })).toBeDisabled()
  await page.getByRole('button', { name: '保存套餐' }).click()
  await expect(page.getByRole('alert')).toContainText('真实的商品 ID 和 SKU ID')
  for (const [index, sku] of [[1,'101'],[2,'102']] as const) {
    await page.getByLabel('商品 ID ' + index, { exact:true }).fill('100')
    await page.getByLabel('SKU ID ' + index, { exact:true }).fill(sku)
  }
  await page.getByRole('button', { name: '保存套餐' }).click()
  await expect(page.getByText('套餐已保存，仅影响之后的新订单。')).toBeVisible()
  expect(saved).toEqual([
    {goods_id:'100',sku_id:'101',goods_name:'补差价专用',sku_name:'10张',generation_limit:10,final_count:10,rerun_limit:2,enabled:false},
    {goods_id:'100',sku_id:'102',goods_name:'补差价专用',sku_name:'20张',generation_limit:20,final_count:20,rerun_limit:2,enabled:false},
  ])
  await expect(page.getByRole('button', { name: '开启自动开户' })).toBeDisabled()
  await page.getByLabel('启用此 SKU 自动开户').first().check()
  await page.getByRole('button', { name: '保存套餐' }).click()
  await expect(page.getByRole('button', { name: '开启自动开户' })).toBeEnabled()
  configured = false
  await page.getByRole('button', { name:'刷新',exact:true }).click()
  await expect(page.getByText('尚未完成阿奇索应用配置')).toBeVisible()
  await expect(page.getByRole('button', { name: '开启自动开户' })).toBeDisabled()
  await page.getByRole('button', { name:'接入订单',exact:true }).click()
  await expect(page.getByText('结果待核对', { exact:true })).toBeVisible()
  await expect(page.getByRole('button', { name:'重试发送' })).toHaveCount(0)
  await expect(page.getByRole('button', { name:'复制选图链接' })).toBeVisible()
  await expect(page.getByText('发送结果不确定，请先在拼多多核对消息。')).toBeVisible()
})

test('较旧刷新请求失败不会覆盖已经成功的新状态', async ({ page }) => {
  await staffLogin(page.request)
  let count = 0
  let holdNext = false
  let releaseOld: (() => Promise<void>) | undefined
  await page.route('**/api/agiso/**', async route => {
    const path = new URL(route.request().url()).pathname
    if (path.endsWith('/status')) return route.fulfill({ json: { configured:false,missing:[],authorization_callback_url:null,webhook_url:null,aftersales_enabled:false } })
    if (path.endsWith('/shops')) {
      count++
      if (holdNext) { holdNext = false; releaseOld = () => route.fulfill({ status:500,json:{detail:'较旧请求错误'} }); return }
      return route.fulfill({ json: [] })
    }
    return route.fulfill({ status:404 })
  })
  await page.goto('/')
  await page.getByRole('button', { name:'店铺接入',exact:true }).click()
  await expect(page.getByText('还没有连接店铺')).toBeVisible()
  const initialCount = count
  holdNext = true
  await page.getByRole('button', { name:'刷新',exact:true }).click()
  await expect.poll(() => !!releaseOld).toBe(true)
  await page.getByRole('button', { name:'刷新',exact:true }).click()
  await expect.poll(() => count).toBe(initialCount + 2)
  const completed = page.waitForResponse(response => response.status() === 500 && response.url().includes('/agiso/shops'))
  await releaseOld!()
  await completed
  await expect(page.getByText('较旧请求错误')).toHaveCount(0)
})

test('授权失败提示在店铺刷新完成后仍然保留', async ({ page }) => {
  await staffLogin(page.request)
  await page.goto('/?agiso=error')
  await expect(page.getByText('还没有连接店铺')).toBeVisible()
  await expect(page.getByRole('alert')).toContainText('店铺授权未完成')
  await expect(page).toHaveURL(/\/$/)
})
