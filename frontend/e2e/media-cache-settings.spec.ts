import { expect, test } from '@playwright/test'
import { completedCustomer, pixel, staffLogin } from './customer-fixtures'
import { uploadStickers } from './library-fixtures'

test('组织管理员设置客户图片缓存天数，超管查看水印图片缓存统计，支持手机', async ({ page }) => {
  await staffLogin(page.request)
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  // One viewed customer image so the statistics are non-empty.
  const [sticker] = await uploadStickers(page.request, [{ name: `CACHE-STATS-${Date.now()}.png`, mimeType: 'image/png', buffer: pixel }])
  const order = await completedCustomer(page.request, sticker.id)
  const detail = await (await page.request.get('/api/customer-orders/' + order.id)).json()
  expect((await page.request.get(detail.slots[0].versions[0].preview_url)).ok()).toBe(true)
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 900 })
    await page.goto('/')
    if (width < 720) await page.getByRole('button', { name: '展开导航' }).click()
    await page.getByRole('navigation').getByRole('button', { name: '账号设置', exact: true }).click()
    const form = page.getByRole('form', { name: '客户图片缓存' })
    const days = form.getByLabel('客户图片缓存保留天数')
    await expect(days).toHaveValue(/^\d+$/)
    await days.fill(width === 1440 ? '30' : '15')
    await form.getByRole('button', { name: '保存' }).click()
    await expect(page.getByText('客户图片缓存保留天数已保存')).toBeVisible()
    expect((await (await page.request.get('/api/organization/settings')).json()).media_cache_days).toBe(width === 1440 ? 30 : 15)
    await expect(form.getByText(`满 ${width === 1440 ? 30 : 15} 天后自动清理`, { exact: false })).toBeVisible()
    if (width < 720) await expect.poll(() => page.locator('.sidebar').evaluate(element => element.getBoundingClientRect().right)).toBeLessThanOrEqual(0)
    await page.screenshot({ path: `test-results/media-cache-settings-${width}.png`, fullPage: true })
    if (width < 720) await page.getByRole('button', { name: '展开导航' }).click()
    await page.getByRole('navigation').getByRole('button', { name: '管理设置', exact: true }).click()
    if (width < 720) await expect.poll(() => page.locator('.sidebar').evaluate(element => element.getBoundingClientRect().right)).toBeLessThanOrEqual(0)
    const stats = page.getByRole('region', { name: '水印图片缓存' })
    await expect(stats).toBeVisible()
    await expect(stats.getByText('图库水印图', { exact: true })).toBeVisible()
    await expect(stats.getByText('客户图片', { exact: true })).toBeVisible()
    await expect(stats.getByText(/不设容量上限/)).toBeVisible()
    const media = (await (await page.request.get('/api/admin/storage')).json()).media_cache
    expect(media.customer.files).toBeGreaterThan(0)
    await stats.scrollIntoViewIfNeeded()
    await page.screenshot({ path: `test-results/media-cache-stats-${width}.png` })
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  }
  expect(errors).toEqual([])
})
