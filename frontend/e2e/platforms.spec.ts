import { test, expect } from '@playwright/test'
import { randomUUID } from 'node:crypto'
import { staffLogin } from './customer-fixtures'

test('manual orders need a platform, show it in the list and can move to another platform',async({page})=>{
  await staffLogin(page.request)
  await page.goto('/')
  await page.getByRole('button',{name:'开新订单'}).click()
  const create=page.getByRole('dialog',{name:'开新订单'})
  const number='PLAT-'+randomUUID().slice(0,8)
  await create.getByLabel('订单号',{exact:true}).fill(number)
  await create.getByRole('button',{name:'创建订单',exact:true}).click()
  // The platform select is required: the browser keeps the dialog open.
  await expect(create).toBeVisible()
  await expect(create.getByLabel('店铺',{exact:true})).toBeDisabled()
  await create.getByLabel('平台',{exact:true}).selectOption('douyin')
  await expect(create.getByText('未选择店铺时使用开单账号的水印')).toBeVisible()
  await create.getByRole('button',{name:'创建订单',exact:true}).click()
  await expect(page.getByRole('heading',{name:'订单 '+number,level:2})).toBeVisible()
  await expect(page.locator('.customer-order-meta')).toContainText('平台：抖店')
  await page.getByRole('button',{name:'修改平台和店铺'}).click()
  const editor=page.getByRole('dialog',{name:'修改平台和店铺 · '+number})
  await editor.getByLabel('平台',{exact:true}).selectOption('xhs')
  await editor.getByRole('button',{name:'保存'}).click()
  await expect(page.locator('.customer-order-meta')).toContainText('平台：小红书')
  await page.getByRole('button',{name:'返回订单'}).click()
  const row=page.locator('.customer-order-row',{hasText:number})
  await expect(row.locator('.platform-badge')).toHaveText('小红书')
  // The order row recolors its spans gray; the badge must keep its own readable color.
  expect(await row.locator('.platform-badge').evaluate(e=>getComputedStyle(e).color)).toBe('rgb(192, 18, 46)')
  await row.screenshot({path:'/tmp/avatar-studio-fal-qa/platform-badge-row.png'})
  await page.getByLabel('平台',{exact:true}).selectOption('pdd')
  await expect(row).toHaveCount(0)
  await page.getByLabel('平台',{exact:true}).selectOption('xhs')
  await expect(row).toHaveCount(1)
})

test('shops page offers each platform and edits a shop watermark',async({page})=>{
  await staffLogin(page.request)
  const shop={id:'shop-1',shop_id:'999',shop_name:'草木造物',owner:'u',owner_name:'联调管理员',organization_id:'o',enabled:false,authorized:true,expires_at:null,last_event_at:null,can_manage:true,platform:'pdd',platform_label:'拼多多',watermark:'草木造物'}
  let saved=''
  await page.route('**/api/agiso/shops',route=>route.fulfill({json:[{...shop,watermark:saved||shop.watermark}]}))
  await page.route('**/api/agiso/shops/shop-1/rules',route=>route.fulfill({json:[]}))
  await page.route('**/api/agiso/shops/shop-1/watermark',async route=>{saved=route.request().postDataJSON().watermark;await route.fulfill({json:{...shop,watermark:saved}})})
  await page.goto('/')
  await page.getByRole('navigation').getByRole('button',{name:'店铺接入',exact:true}).click()
  for(const label of ['连接拼多多店铺','连接抖店店铺（接入中）','连接小红书店铺（接入中）'])await expect(page.getByRole('button',{name:label})).toBeDisabled()
  await expect(page.locator('.shop-card .platform-badge')).toHaveText('拼多多')
  expect(await page.locator('.shop-card .platform-badge').evaluate(e=>getComputedStyle(e).color)).toBe('rgb(180, 35, 24)')
  await page.locator('.shop-card').screenshot({path:'/tmp/avatar-studio-fal-qa/platform-badge-shop.png'})
  const field=page.getByLabel('草木造物 店铺水印')
  await expect(field).toHaveValue('草木造物')
  await field.fill('草木造物·新')
  await page.getByRole('button',{name:'保存水印'}).click()
  await expect(page.getByText('之后开的订单使用新水印')).toBeVisible()
  expect(saved).toBe('草木造物·新')
  await expect(page.locator('.shop-card')).toContainText('水印：草木造物·新')
})
