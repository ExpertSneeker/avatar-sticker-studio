import { test, expect } from '@playwright/test'
import { randomUUID } from 'node:crypto'
import { readFile } from 'node:fs/promises'
import { uploadStickers } from './library-fixtures'
import { completedCustomer, mutate, pixel, staffLogin } from './customer-fixtures'

test('administrators see per-order costs, edit dated rates and export CSV, on desktop and phone',async({page})=>{
  await staffLogin(page.request)
  const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message))
  const tag=randomUUID().slice(0,6).toUpperCase()
  const [sticker]=await uploadStickers(page.request,[{name:`CST-${tag}.png`,mimeType:'image/png',buffer:pixel}])
  const order=await completedCustomer(page.request,sticker.id,{order_number:`CST-${tag}`})
  await expect.poll(async()=>(await(await page.request.get('/api/customer-orders/'+order.id)).json()).delivery_ready,{timeout:60000}).toBe(true)
  await mutate(page.request,await(await page.request.get('/api/customer-orders/'+order.id)).json(),'ship')
  const before=(await(await page.request.get('/api/costs?scope=global')).json()).rates
  try{
    await page.setViewportSize({width:1440,height:1000})
    await page.goto('/');await page.getByRole('navigation').getByRole('button',{name:'统计',exact:true}).click()
    await page.getByRole('tab',{name:'成本'}).click()
    await expect(page.getByRole('heading',{name:'成本',exact:true,level:1})).toBeVisible()
    const row=page.locator('.costs-table tr').filter({hasText:`CST-${tag}`})
    await expect(row).toContainText('0.30');await expect(row).toContainText('2.30');await expect(row).toContainText('0.27')
    await expect(row).toContainText('1 张 / 1 张')
    await expect(page.locator('.costs-rates')).toContainText('6.7220')
    await expect(page.locator('.costs-rates')).toContainText('中国外汇交易中心中间价')
    // A rate effective today applies to orders shipped today.
    await page.getByRole('button',{name:'修改费率'}).click()
    const dialog=page.getByRole('dialog',{name:'修改成本费率'})
    await dialog.getByLabel('快递费（元/单）').fill('3')
    await dialog.getByRole('button',{name:'保存费率'}).click()
    await expect(page.getByText('成本费率已保存')).toBeVisible()
    await expect(row).toContainText('3.00')
    // Totals for the current filter, split into physical and software costs; shop and date filters.
    const total=page.getByRole('region',{name:'当前筛选的总计'})
    await expect(total).toContainText('现实成本');await expect(total).toContainText('软件成本');await expect(total).toContainText('全部店铺')
    await expect(page.locator('.costs-table thead')).toContainText('现实成本');await expect(page.locator('.costs-table tfoot')).toContainText('合计')
    await page.getByLabel('成本店铺').selectOption('none')
    await expect(total).toContainText('无关联店铺');await expect(row).toBeVisible()
    await page.screenshot({path:'test-results/costs-1440.png',fullPage:true})
    await page.getByLabel('成本开始日期').fill('2099-01-01')
    await expect(page.getByText('当前筛选下没有订单')).toBeVisible()
    await page.getByRole('button',{name:'本月',exact:true}).click()
    await expect(row).toBeVisible()
    const download=page.waitForEvent('download')
    await page.getByRole('button',{name:'导出 CSV'}).click()
    const file=await download
    expect(file.suggestedFilename()).toMatch(/^订单成本_.*\.csv$/)
    const text=await readFile(await file.path(),'utf8')
    expect(text).toContain(`CST-${tag}`);expect(text.split('\r\n')[0]).toContain('合计')
    await page.setViewportSize({width:390,height:844})
    await expect(row).toBeVisible()
    expect(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth)).toBe(false)
    await page.screenshot({path:'test-results/costs-390.png',fullPage:true})
    // The platform view lists every organization.
    await page.setViewportSize({width:1440,height:1000})
    await page.getByRole('navigation').getByRole('button',{name:'全站统计',exact:true}).click()
    await page.getByRole('tab',{name:'成本'}).click()
    await expect(page.getByRole('heading',{name:'全站成本',level:1})).toBeVisible()
    await expect(page.locator('.costs-table tr').filter({hasText:`CST-${tag}`})).toBeVisible()
    expect(errors).toEqual([])
  }finally{
    const today=(await(await page.request.get('/api/costs?scope=global')).json()).today
    await page.request.put('/api/costs/rates',{data:{...before,from:today}})
  }
})
