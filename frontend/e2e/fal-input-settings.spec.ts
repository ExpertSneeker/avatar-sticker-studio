import { expect, test } from '@playwright/test'
import { staffLogin } from './customer-fixtures'

test('未配置 OSS 时固定直接提交，仍可保存队列设置，支持手机', async ({ page }) => {
  await staffLogin(page.request)
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  await page.goto('/')
  await page.getByRole('button', { name: '管理设置', exact: true }).click()
  const mode = page.getByLabel('生图图片传输方式', { exact: true })
  await expect(mode).toBeVisible()
  await expect(mode).toBeDisabled()
  await expect(mode).toHaveValue('inline')
  await expect(page.getByText('服务器尚未配置 OSS，当前使用直接提交图片。', { exact: true })).toBeVisible()
  await page.getByLabel('同时提交数量', { exact: true }).fill('2')
  await page.getByRole('button', { name: '保存全站设置', exact: true }).click()
  await expect(page.getByText('全站设置已保存', { exact: true })).toBeVisible()
  const settings = await (await page.request.get('/api/admin/settings')).json()
  expect(settings.fal_input_mode).toBe('inline')
  expect(settings.fal_input_oss_available).toBe(false)
  expect(settings.max_uploads).toBe(2)
  await page.screenshot({ path: '/tmp/avatar-studio-fal-qa/input-mode-desktop.png', fullPage: true })
  await page.setViewportSize({ width: 390, height: 844 })
  await expect.poll(() => page.locator('.sidebar').evaluate(element => element.getBoundingClientRect().right)).toBeLessThanOrEqual(0)
  await mode.scrollIntoViewIfNeeded()
  await expect(mode).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await page.screenshot({ path: '/tmp/avatar-studio-fal-qa/input-mode-mobile.png' })
  expect(errors).toEqual([])
})

test('OSS 可用时传输方式可保存，服务端拒绝时保留修改并提示', async ({ page }) => {
  await staffLogin(page.request)
  // Render-only availability fixture: no cloud configuration or provider is touched.
  let currentMode: 'inline' | 'oss' = 'inline'
  let fail = false
  const patches: Record<string, unknown>[] = []
  await page.route('**/api/admin/settings', async route => {
    if (route.request().method() === 'PATCH') {
      const body = route.request().postDataJSON()
      patches.push(body)
      if (fail) return route.fulfill({ status: 422, json: { detail: '服务器尚未配置 OSS，无法使用 OSS 图片链接' } })
      currentMode = body.fal_input_mode
      return route.fulfill({ json: { ok: true } })
    }
    const response = await route.fetch()
    return route.fulfill({ response, json: { ...await response.json(), fal_input_mode: currentMode, fal_input_oss_available: true } })
  })
  await page.goto('/')
  await page.getByRole('button', { name: '管理设置', exact: true }).click()
  const mode = page.getByLabel('生图图片传输方式', { exact: true })
  await expect(mode).toBeEnabled()
  await mode.selectOption('oss')
  await page.getByRole('button', { name: '保存全站设置', exact: true }).click()
  await expect(page.getByText('全站设置已保存', { exact: true })).toBeVisible()
  expect(patches.at(-1)?.fal_input_mode).toBe('oss')
  expect(patches.at(-1)).not.toHaveProperty('fal_input_oss_available')
  await expect(mode).toHaveValue('oss')
  fail = true
  await mode.selectOption('inline')
  await page.getByRole('button', { name: '保存全站设置', exact: true }).click()
  await expect(page.getByText('服务器尚未配置 OSS，无法使用 OSS 图片链接', { exact: true })).toBeVisible()
  await expect(mode).toHaveValue('inline')
  await expect(page.getByRole('button', { name: '保存全站设置', exact: true })).toBeEnabled()
})
