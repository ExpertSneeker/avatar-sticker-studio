import { expect, test } from '@playwright/test'
import { completedCustomer, createCustomer, pixel, staffLogin } from './customer-fixtures'
import { uploadStickers } from './library-fixtures'

test('白边处理宽度在账号设置保存，订单快照和重新排版使用原图像素，支持手机', async ({ page }) => {
  await staffLogin(page.request)
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  const originalDefaults = (await (await page.request.get('/api/auth/me')).json()).print_defaults
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 900 })
    await page.goto('/')
    if (width < 720) await page.getByRole('button', { name: '展开导航' }).click()
    await page.getByRole('navigation').getByRole('button', { name: '账号设置', exact: true }).click()
    const input = page.getByRole('spinbutton', { name: '白边处理宽度', exact: true })
    await expect(input).toHaveValue(width === 1440 ? '7' : '3')
    await input.fill(width === 1440 ? '3' : '0')
    const alpha = page.getByRole('spinbutton', { name: '白边边缘阈值', exact: true })
    await expect(alpha).toHaveValue(width === 1440 ? '128' : '96')
    if (width === 1440) await alpha.fill('96')
    await page.getByRole('button', { name: '保存设置', exact: true }).click()
    await expect(page.getByText('账号设置已保存')).toBeVisible()
    const defaults = (await (await page.request.get('/api/auth/me')).json()).print_defaults
    expect(defaults.white_border_px).toBe(width === 1440 ? 3 : 0)
    const fresh = await createCustomer(page.request)
    expect(fresh.print_settings.white_border_px).toBe(defaults.white_border_px)
    expect(defaults.white_border_alpha).toBe(96)
    expect(fresh.print_settings.white_border_alpha).toBe(96)
    await input.scrollIntoViewIfNeeded()
    await page.screenshot({ path: `/tmp/avatar-studio-fal-qa/white-border-settings-${width}.png`, fullPage: true })
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  }
  const [sticker] = await uploadStickers(page.request, [{ name: `WHITE-EDGE-${Date.now()}.png`, mimeType: 'image/png', buffer: pixel }])
  const submitted = await completedCustomer(page.request, sticker.id)
  if (page.viewportSize()!.width < 720) await page.getByRole('button', { name: '展开导航' }).click()
  await page.getByRole('navigation').getByRole('button', { name: '全部订单', exact: true }).click()
  await page.locator('.customer-order-row').filter({ hasText: submitted.order_number }).getByRole('button', { name: '查看订单' }).click()
  const orderDialog = page.getByRole('dialog', { name: '订单 ' + submitted.order_number, exact: true })
  await orderDialog.getByRole('button', { name: '重新排版', exact: true }).click()
  const repack = page.getByRole('dialog', { name: '重新排版', exact: true })
  await expect(repack.getByRole('spinbutton', { name: '白边处理宽度', exact: true })).toHaveValue('0')
  await repack.getByRole('spinbutton', { name: '白边处理宽度', exact: true }).fill('7')
  await repack.getByRole('button', { name: '确认排版', exact: true }).click()
  await expect.poll(async () => {
    const order = await (await page.request.get('/api/customer-orders/' + submitted.id)).json()
    return order.delivery_ready && order.print_settings.white_border_px === 7 && order.delivery_version > submitted.delivery_version
  }).toBe(true)
  expect((await (await page.request.get('/api/auth/me')).json()).print_defaults.white_border_px).toBe(0)
  expect(errors).toEqual([])
  expect((await page.request.patch('/api/account', { data: { print_defaults: originalDefaults } })).ok()).toBe(true)
})
