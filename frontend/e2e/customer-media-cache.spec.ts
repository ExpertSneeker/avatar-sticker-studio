import { chromium, expect, test, type BrowserContext } from '@playwright/test'
import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { completedCustomer, pixel, staffLogin } from './customer-fixtures'
import { uploadStickers } from './library-fixtures'

for (const width of [1440, 390]) {
  test(`watermarked media persists across browser restart and revalidates at ${width}px`, async ({ page, baseURL }, testInfo) => {
    await staffLogin(page.request)
    const [sticker] = await uploadStickers(page.request, [{ name: `CACHE-${width}.png`, mimeType: 'image/png', buffer: pixel }])
    const order = await completedCustomer(page.request, sticker.id)
    const profile = mkdtempSync(join(tmpdir(), 'sticker-private-cache-'))
    let context: BrowserContext | undefined
    const launch = () => chromium.launchPersistentContext(profile, { channel: testInfo.project.use.channel as string, headless: true, baseURL, viewport: { width, height: 900 } })
    try {
      context = await launch()
      expect((await context.request.post('/api/guest/login', { data: { order_number: order.order_number } })).ok()).toBe(true)
      const guest = await (await context.request.get('/api/guest/order')).json()
      const link = baseURL + guest.preview_url
      let viewer = await context.newPage()
      const first = await viewer.goto(link)
      expect(first?.status()).toBe(200)
      expect((await first?.allHeaders())?.['cache-control']).toBe('private, no-cache')
      await expect.poll(() => viewer.locator('img').evaluate((image: HTMLImageElement) => image.naturalWidth)).toBeGreaterThan(0)
      await context.close()
      context = await launch()
      viewer = await context.newPage()
      const cdp = await context.newCDPSession(viewer)
      await cdp.send('Network.enable')
      const wireStatuses: number[] = []
      const validators: string[] = []
      cdp.on('Network.responseReceivedExtraInfo', event => wireStatuses.push(event.statusCode))
      cdp.on('Network.requestWillBeSentExtraInfo', event => {
        for (const [name, value] of Object.entries(event.headers)) if (name.toLowerCase() === 'if-none-match') validators.push(String(value))
      })
      expect((await viewer.goto(link))?.status()).toBe(200)
      await expect.poll(() => wireStatuses.includes(304)).toBe(true)
      expect(validators).toContain((await first?.allHeaders())?.etag)
      await expect.poll(() => viewer.locator('img').evaluate((image: HTMLImageElement) => image.naturalWidth)).toBeGreaterThan(0)
      expect((await context.request.post('/api/guest/logout')).ok()).toBe(true)
      expect((await viewer.goto(link))?.status()).toBe(401)
    } finally {
      await context?.close()
      rmSync(profile, { recursive: true, force: true })
    }
  })
}
