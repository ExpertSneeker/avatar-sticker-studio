import {test,expect,type Browser} from '@playwright/test'
import {randomUUID} from 'node:crypto'
import {createCustomer,pixel,staffLogin} from './customer-fixtures'
import {uploadStickers} from './library-fixtures'

// The picker downloads the smallest watermarked tier covering each image's rendered width at the screen density.
const tiers=[160,320,640]
const tierOf=(url:string)=>Number(new URL(url).searchParams.get('size'))
const expected=(width:number,dpr:number)=>tiers.find(tier=>tier>=width*dpr)??640

async function pickerImages(browser:Browser,baseURL:string,orderNumber:string,suffix:string,width:number,dpr:number){
  const context=await browser.newContext({baseURL,viewport:{width,height:900},deviceScaleFactor:dpr})
  const page=await context.newPage()
  const requested:number[]=[]
  page.on('request',request=>{if(request.url().includes('/api/guest/media/'))requested.push(tierOf(request.url()))})
  await page.goto('/guest')
  await page.getByLabel('订单号',{exact:true}).fill(orderNumber);await page.getByRole('button',{name:'进入订单'}).click()
  await page.getByLabel('上传头像').setInputFiles({name:'avatar.png',mimeType:'image/png',buffer:pixel})
  await page.getByRole('button',{name:'选择模板和贴纸'}).first().click()
  const picker=page.getByRole('dialog',{name:'选择模板和贴纸'})
  await picker.getByLabel('搜索模板或贴纸').fill(suffix)
  const loaded=async(locator:ReturnType<typeof picker.locator>)=>{
    await expect.poll(()=>locator.evaluate((image:HTMLImageElement)=>image.complete&&image.naturalWidth>0)).toBe(true)
    return locator.evaluate((image:HTMLImageElement)=>({width:image.getBoundingClientRect().width,src:image.currentSrc}))
  }
  // Smallest views first: browsers may reuse an already loaded larger candidate of the same image.
  const thumbnail=await loaded(picker.locator('.customer-catalog-image img').first())
  await picker.getByRole('button',{name:'单张贴纸',exact:true}).click()
  const sticker=await loaded(picker.locator('.customer-catalog-image img').first())
  await picker.getByRole('button',{name:'模板套装',exact:true}).click()
  await picker.getByRole('button',{name:`放大查看 RSET-${suffix}`}).click()
  const contents=await loaded(page.getByRole('dialog',{name:'响应式套装 · 共 4 张'}).locator('.customer-set-preview img').first())
  await context.close()
  return {thumbnail,contents,sticker,requested}
}

test('picker thumbnails load the smallest sufficient watermarked tier',async({page,browser,baseURL})=>{
  await staffLogin(page.request)
  const suffix=randomUUID().slice(0,6).toUpperCase()
  const stickers=await uploadStickers(page.request,[1,2,3,4].map(i=>({name:`R${suffix}-${i}.png`,mimeType:'image/png',buffer:pixel})))
  expect((await page.request.post('/api/templates',{data:{code:`RSET-${suffix}`,name:'响应式套装',category:'animal',sticker_ids:stickers.map(s=>s.id)}})).ok()).toBeTruthy()
  const order=await createCustomer(page.request,{generation_limit:20,final_count:2})
  for(const [width,dpr] of [[390,3],[375,2],[430,3],[720,2],[768,2],[1024,2],[1440,1],[1440,2]] as const){
    const {thumbnail,contents,sticker,requested}=await pickerImages(browser,baseURL!,order.order_number,suffix,width,dpr)
    for(const [name,image] of Object.entries({thumbnail,contents,sticker})){
      const label=`${name} at ${width}px@${dpr}x renders ${image.width.toFixed(1)}px`
      expect(tierOf(image.src),label).toBe(expected(image.width,dpr))
    }
    // Thumbnails never fall back to the old default 640 tier on phones, nor fetch zoom-sized media.
    if(width<=430)expect(requested.filter(size=>size>=640)).toEqual([])
    expect(requested).not.toContain(1024)
  }
})
