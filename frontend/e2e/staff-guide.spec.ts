import { expect, test } from '@playwright/test'
import { createCustomer, staffLogin } from './customer-fixtures'

test('后台可阅读和搜索说明，退出登录后不再显示正文', async ({ page }) => {
  await staffLogin(page.request)
  await page.goto('/')
  await page.getByRole('button', { name: '使用说明', exact: true }).click()
  await expect(page.getByRole('heading', { name: '后台使用说明', exact: true })).toBeVisible()
  await expect(page.getByRole('heading', { name: '开户与额度', exact: true })).toBeVisible()
  await page.getByRole('searchbox', { name: '搜索使用说明' }).fill('20张')
  await expect(page.getByRole('heading', { name: '拼多多店铺接入', exact: true })).toBeVisible()
  await expect(page.getByRole('heading', { name: '图库与模板', exact: true })).toHaveCount(0)
  await page.getByRole('searchbox', { name: '搜索使用说明' }).fill('不存在的帮助词')
  await expect(page.getByText('没有找到相关说明')).toBeVisible()
  await page.getByRole('button', { name: '退出登录', exact: true }).click()
  await expect(page.getByRole('heading', { name: '后台使用说明', exact: true })).toHaveCount(0)
  expect((await page.request.get('/api/staff-guide')).status()).toBe(401)
})

test('只有访客会话时没有说明入口，直接请求正文也被拒绝', async ({ browser, baseURL, request }) => {
  await staffLogin(request)
  const order = await createCustomer(request)
  const context = await browser.newContext({ baseURL })
  try {
    const page = await context.newPage()
    await page.request.post('/api/guest/login', { data: { order_number: order.order_number } })
    await page.goto('/guest')
    await expect(page.getByRole('heading', { name: '订单 ' + order.order_number, exact: true })).toBeVisible()
    await expect(page.getByRole('button', { name: '使用说明', exact: true })).toHaveCount(0)
    expect((await page.request.get('/api/staff-guide')).status()).toBe(401)
  } finally { await context.close() }
})
