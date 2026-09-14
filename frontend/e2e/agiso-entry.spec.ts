import { expect, test } from '@playwright/test'
import { createCustomer, staffLogin } from './customer-fixtures'

test('预填订单号需要客户确认，登录后清理网址', async ({ page, request }) => {
  await staffLogin(request)
  const order = await createCustomer(request, { generation_limit: 10, final_count: 10, rerun_limit: 2 })
  await page.goto('/guest?order_number=' + encodeURIComponent(order.order_number))
  await expect(page.getByLabel('订单号', { exact: true })).toHaveValue(order.order_number)
  await expect(page.getByRole('button', { name: '进入订单', exact: true })).toBeVisible()
  await page.getByRole('button', { name: '进入订单', exact: true }).click()
  await expect(page.getByRole('button', { name: '退出订单', exact: true })).toBeVisible()
  await expect(page).toHaveURL(/\/guest$/)
  await expect(page.getByText(order.order_number, { exact: false })).toBeVisible()
})

test('已登录其他订单时先提示切换，不展示旧订单的工作台', async ({ page, request }) => {
  await staffLogin(request)
  const a = await createCustomer(request)
  const b = await createCustomer(request)
  await page.goto('/guest')
  await page.getByLabel('订单号', { exact: true }).fill(a.order_number)
  await page.getByRole('button', { name: '进入订单', exact: true }).click()
  await expect(page.getByRole('button', { name: '退出订单', exact: true })).toBeVisible()
  await page.goto('/guest?order_number=' + encodeURIComponent(b.order_number))
  await expect(page.getByText('当前已登录其他订单')).toBeVisible()
  await expect(page.getByLabel('订单号', { exact: true })).toHaveValue(b.order_number)
  await expect(page.getByRole('button', { name: '切换并进入订单' })).toBeVisible()
  await expect(page.getByText('上传头像', { exact: true })).toHaveCount(0)
  await page.getByRole('button', { name: '切换并进入订单' }).click()
  await expect(page).toHaveURL(/\/guest$/)
  await expect(page.getByText(b.order_number, { exact: false })).toBeVisible()
})

test('店铺接入在未配置时清晰提示并禁止连接', async ({ page }) => {
  await staffLogin(page.request)
  await page.goto('/')
  await page.getByRole('button', { name: '店铺接入', exact: true }).click()
  await expect(page.getByRole('heading', { name: '店铺接入', exact: true }).last()).toBeVisible()
  await expect(page.getByText('尚未完成阿奇索应用配置')).toBeVisible()
  await expect(page.getByRole('button', { name: '连接拼多多店铺' })).toBeDisabled()
})

test('售后暂停时隐藏生成和提交操作并给出原因', async ({ page, request }) => {
  await staffLogin(request)
  const order = await createCustomer(request)
  await page.request.post('/api/guest/login', { data: { order_number: order.order_number } })
  await page.route('**/api/guest/order', route => route.fulfill({ json: { ...order, version: 2, paused: true, hold_reason: '退款处理中，暂不能生成或提交' } }))
  await page.goto('/guest?order_number=' + encodeURIComponent(order.order_number))
  // The response simulates a previously authenticated order becoming paused.
  await expect(page.getByText('退款处理中，暂不能生成或提交')).toBeVisible()
  await expect(page.getByRole('button', { name: '核对并开始生成' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: '确认成品并提交' })).toHaveCount(0)
})
