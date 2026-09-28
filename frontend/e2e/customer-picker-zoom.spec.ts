import {test,expect,type APIRequestContext} from '@playwright/test'
import {randomUUID} from 'node:crypto'
import {createCustomer,pixel,staffLogin} from './customer-fixtures'

async function stickersIn(request:APIRequestContext,category:string,codes:string[]){
  const form=new FormData()
  form.append('codes',JSON.stringify(codes));form.append('category',category)
  for(const code of codes)form.append('files',new Blob([new Uint8Array(pixel)],{type:'image/png'}),code+'.png')
  const response=await request.post('/api/stickers',{multipart:form});expect(response.ok(),await response.text()).toBeTruthy()
  return await response.json() as {id:string;code:string}[]
}

test('guest picker shows Chinese categories, dense cards and zoom for stickers and template contents',async({page})=>{
  await staffLogin(page.request)
  const suffix=randomUUID().slice(0,6).toUpperCase()
  const boys=await stickersIn(page.request,'boy',[1,2,3,4].map(i=>`ZB${suffix}-${i}`))
  const animals=await stickersIn(page.request,'animal',[1,2,3,4,5].map(i=>`ZA${suffix}-${i}`))
  const set=await page.request.post('/api/templates',{data:{code:`ZSET-${suffix}`,name:'放大测试套装',category:'animal',sticker_ids:animals.map(s=>s.id)}});expect(set.ok()).toBeTruthy()
  const order=await createCustomer(page.request,{generation_limit:20,final_count:2})
  // Screenshots wait for modal entrance animations to finish.
  const settle=()=>page.evaluate(()=>Promise.allSettled(document.getAnimations().filter(animation=>animation.effect?.getTiming().iterations!==Infinity).map(animation=>animation.finished)))
  const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message))
  await page.goto('/guest')
  await page.getByLabel('订单号',{exact:true}).fill(order.order_number);await page.getByRole('button',{name:'进入订单'}).click()
  await page.getByLabel('上传头像').setInputFiles({name:'avatar.png',mimeType:'image/png',buffer:pixel})
  await expect(page.locator('.customer-avatar-row')).toHaveCount(1)
  for(const [width,height] of [[390,844],[1280,900]]){
    await page.setViewportSize({width,height})
    await page.getByRole('button',{name:'选择模板和贴纸'}).first().click()
    const picker=page.getByRole('dialog',{name:'选择模板和贴纸'})
    await picker.getByRole('button',{name:'单张贴纸',exact:true}).click()
    // Category names come from the organization, never the raw ids.
    const categories=picker.getByLabel('贴纸分类')
    const labels=await categories.locator('option').allTextContents()
    expect(labels.some(label=>/^男孩（\d+）$/.test(label))&&labels.some(label=>/^动物（\d+）$/.test(label))&&labels.some(label=>/^通用（\d+）$/.test(label))).toBe(true)
    expect(labels.join()).not.toMatch(/boy|animal|general/)
    await categories.selectOption({label:labels.find(label=>label.startsWith('男孩'))!})
    await picker.getByLabel('搜索模板或贴纸').fill(suffix)
    await expect(picker.locator('.customer-catalog article')).toHaveCount(boys.length)
    const columns=await picker.locator('.customer-catalog').evaluate(el=>getComputedStyle(el).gridTemplateColumns.split(' ').length)
    expect(columns).toBe(width<720?3:6)
    await settle();await page.screenshot({path:`test-results/picker-zoom-${width}-stickers.png`})
    await picker.getByRole('button',{name:`放大查看 ${boys[0].code}`}).click()
    const zoom=page.getByRole('dialog',{name:boys[0].code})
    await expect(zoom.locator('.customer-zoom-image img')).toHaveAttribute('src',/size=1024$/)
    await expect(zoom.locator('.customer-zoom-image img')).toBeVisible()
    await settle();await page.screenshot({path:`test-results/picker-zoom-${width}-sticker-zoom.png`})
    await zoom.getByRole('button',{name:'关闭',exact:true}).first().click()
    await expect(zoom).toHaveCount(0)
    // Template zoom lists every contained sticker; each opens its own enlargement.
    await picker.getByRole('button',{name:'模板套装',exact:true}).click()
    await categories.selectOption('all')
    await picker.getByRole('button',{name:`放大查看 ZSET-${suffix}`}).click()
    const contents=page.getByRole('dialog',{name:'放大测试套装 · 共 5 张'})
    await expect(contents.locator('.customer-set-preview button')).toHaveCount(animals.length)
    await settle();await page.screenshot({path:`test-results/picker-zoom-${width}-template.png`})
    await contents.getByRole('button',{name:`放大查看 ${animals[2].code}`}).click()
    await expect(page.getByRole('dialog',{name:`放大测试套装 · ${animals[2].code}`}).locator('img')).toBeVisible()
    await page.keyboard.press('Escape');await page.keyboard.press('Escape')
    await expect(contents).toHaveCount(0)
    // Zooming never changes the selection.
    await expect(picker.getByText('本头像已选 0 张',{exact:false})).toBeVisible()
    await page.keyboard.press('Escape')
  }
  expect(errors).toEqual([])
})
