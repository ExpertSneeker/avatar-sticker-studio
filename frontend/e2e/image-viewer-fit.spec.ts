import {test,expect,type Locator,type Page} from '@playwright/test'
import {randomUUID} from 'node:crypto'
import {createCustomer,pixel,staffLogin} from './customer-fixtures'

// A large portrait sticker that used to overflow the 550px preview dialog.
async function tallPng(page:Page){
  const data=await page.evaluate(()=>{const canvas=document.createElement('canvas');canvas.width=1200;canvas.height=1600;const ctx=canvas.getContext('2d')!;ctx.fillStyle='#d9a066';ctx.fillRect(0,0,1200,1600);ctx.fillStyle='#2a4d7a';ctx.fillRect(100,100,1000,1400);return canvas.toDataURL('image/png').split(',')[1]})
  return Buffer.from(data,'base64')
}

// The whole image is visible inside the viewport without any scrolling in the dialog.
async function expectFits(page:Page,dialog:Locator){
  const img=dialog.locator('.media-frame img')
  await expect(img).toBeVisible()
  await expect.poll(()=>img.evaluate((el:HTMLImageElement)=>el.complete&&el.naturalWidth)).toBeGreaterThan(0)
  await page.evaluate(()=>Promise.allSettled(document.getAnimations().map(animation=>animation.finished)))
  const box=await dialog.evaluate(el=>{const image=el.querySelector<HTMLImageElement>('.media-frame img')!,rect=image.getBoundingClientRect(),modal=el.getBoundingClientRect()
    return {scrollY:el.scrollHeight-el.clientHeight,scrollX:el.scrollWidth-el.clientWidth,top:rect.top,bottom:rect.bottom,left:rect.left,right:rect.right,modalBottom:modal.bottom,width:rect.width,height:rect.height,ratio:image.naturalWidth/image.naturalHeight}})
  const viewport=page.viewportSize()!
  expect(box.scrollY).toBeLessThanOrEqual(1);expect(box.scrollX).toBeLessThanOrEqual(1)
  expect(box.top).toBeGreaterThanOrEqual(0);expect(box.left).toBeGreaterThanOrEqual(0)
  expect(box.right).toBeLessThanOrEqual(viewport.width);expect(box.modalBottom).toBeLessThanOrEqual(viewport.height)
  expect(Math.abs(box.width/box.height-box.ratio)).toBeLessThan(.02)
  // Scaled down to fit, but still uses most of the available height or width.
  expect(Math.max(box.height/viewport.height,box.width/viewport.width)).toBeGreaterThan(.55)
}

test('single-image viewers scale large stickers to fit the screen',async({page})=>{
  await staffLogin(page.request)
  const code=`FIT-${randomUUID().slice(0,6).toUpperCase()}`
  await page.goto('/')
  const form=new FormData();form.append('codes',JSON.stringify([code]));form.append('category','general')
  form.append('files',new Blob([new Uint8Array(await tallPng(page))],{type:'image/png'}),code+'.png')
  const upload=await page.request.post('/api/stickers',{multipart:form});expect(upload.ok(),await upload.text()).toBeTruthy()
  const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message))
  for(const [width,height] of [[1280,800],[390,844]]){
    await page.setViewportSize({width,height})
    await page.goto('/')
    if(width<720)await page.getByRole('button',{name:/菜单|导航/}).first().click()
    await page.getByRole('navigation').getByRole('button',{name:'贴纸库',exact:true}).click()
    await page.getByRole('button',{name:'预览贴纸 '+code,exact:true}).click()
    const preview=page.getByRole('dialog',{name:new RegExp(code)})
    await expectFits(page,preview)
    await page.screenshot({path:`test-results/image-fit-${width}-library.png`})
    // The original file is larger still and must fit the same way.
    await preview.getByRole('button',{name:'查看原图'}).click()
    await expect(preview.getByText('正在显示原始文件')).toBeVisible()
    await expectFits(page,preview)
    await page.keyboard.press('Escape');await expect(preview).toHaveCount(0)
  }
  const order=await createCustomer(page.request,{generation_limit:5,final_count:1})
  await page.goto('/guest')
  await page.getByLabel('订单号',{exact:true}).fill(order.order_number);await page.getByRole('button',{name:'进入订单'}).click()
  await page.getByLabel('上传头像').setInputFiles({name:'avatar.png',mimeType:'image/png',buffer:pixel})
  await expect(page.locator('.customer-avatar-row')).toHaveCount(1)
  for(const [width,height] of [[1280,800],[390,844]]){
    await page.setViewportSize({width,height})
    await page.getByRole('button',{name:'选择模板和贴纸'}).first().click()
    const picker=page.getByRole('dialog',{name:'选择模板和贴纸'})
    await picker.getByRole('button',{name:'单张贴纸',exact:true}).click()
    await picker.getByLabel('搜索模板或贴纸').fill(code)
    await picker.getByRole('button',{name:`放大查看 ${code}`}).click()
    const zoom=page.getByRole('dialog',{name:code})
    await expectFits(page,zoom)
    await page.screenshot({path:`test-results/image-fit-${width}-guest.png`})
    await page.keyboard.press('Escape');await expect(zoom).toHaveCount(0)
    await page.keyboard.press('Escape');await expect(picker).toHaveCount(0)
  }
  expect(errors).toEqual([])
})
