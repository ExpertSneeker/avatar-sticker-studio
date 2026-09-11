import {test,expect} from '@playwright/test'
import {randomUUID} from 'node:crypto'
import {uploadStickers} from './library-fixtures'
import {createCustomer,pixel,staffLogin} from './customer-fixtures'

for(const mode of ['staff','guest'] as const){
  test(`${mode}: shared selection limit counts all avatars, repeated stickers and complete templates`,async({page,browser})=>{
    await staffLogin(page.request)
    const suffix=randomUUID().slice(0,8)
    const stickers=await uploadStickers(page.request,['A','B'].map(letter=>({name:`CAP-${suffix}-${letter}.png`,mimeType:'image/png',buffer:pixel})))
    const templateCode='CAP-SET-'+suffix
    expect((await page.request.post('/api/templates',{data:{code:templateCode,name:templateCode,category:'general',sticker_ids:stickers.map(s=>s.id)}})).ok()).toBe(true)
    const order=await createCustomer(page.request,{generation_limit:10,final_count:8})
    const context=await browser.newContext({baseURL:'http://127.0.0.1:5174',viewport:mode==='guest'?{width:390,height:844}:{width:1440,height:1000}})
    try{
      const screen=mode==='staff'?page:await context.newPage()
      const errors:string[]=[];screen.on('pageerror',e=>errors.push(e.message))
      if(mode==='guest'){
        await screen.goto('/guest');await screen.getByLabel('订单号',{exact:true}).fill(order.order_number);await screen.getByRole('button',{name:'进入订单'}).click()
      }else{
        await screen.goto('/');await screen.locator('.customer-order-row').filter({hasText:order.order_number}).getByRole('button',{name:'进入 / 代操作',exact:true}).click()
      }
      await screen.getByLabel('上传头像').setInputFiles(['one','two'].map(name=>({name:`${suffix}-${name}.png`,mimeType:'image/png',buffer:pixel})))
      await expect(screen.locator('.customer-avatar-row')).toHaveCount(2)
      await screen.getByRole('button',{name:'选择模板和贴纸'}).nth(0).click()
      let picker=screen.getByRole('dialog',{name:'选择模板和贴纸'})
      await picker.getByRole('button',{name:'单张贴纸',exact:true}).click()
      await picker.getByLabel('搜索模板或贴纸').fill(suffix)
      await picker.getByLabel(stickers[0].code+' 份数',{exact:true}).fill('5')
      await expect(picker.getByLabel('订单选图统计')).toContainText('订单已选 5 / 10 张')
      await picker.getByRole('button',{name:'应用选择'}).click()
      await screen.getByRole('button',{name:'选择模板和贴纸'}).nth(1).click()
      picker=screen.getByRole('dialog',{name:'选择模板和贴纸'})
      await picker.getByLabel('搜索模板或贴纸').fill(templateCode)
      await picker.getByLabel(templateCode+' 份数',{exact:true}).fill('3')
      await expect(picker.getByLabel(templateCode+' 份数',{exact:true})).toHaveValue('2')
      await expect(picker.getByLabel('订单选图统计')).toContainText('订单已选 9 / 10 张')
      await expect(picker.getByRole('button',{name:templateCode+' 增加份数',exact:true})).toBeDisabled()
      await picker.getByRole('button',{name:'单张贴纸',exact:true}).click();await picker.getByLabel('搜索模板或贴纸').fill(suffix)
      await picker.getByLabel(stickers[0].code+' 份数',{exact:true}).fill('999')
      await expect(picker.getByLabel(stickers[0].code+' 份数',{exact:true})).toHaveValue('1')
      await expect(picker.getByLabel('订单选图统计')).toContainText('订单已选 10 / 10 张')
      await expect(picker.getByRole('button',{name:stickers[0].code+' 增加份数',exact:true})).toBeDisabled()
      await expect(picker.getByRole('button',{name:stickers[1].code+' 增加份数',exact:true})).toBeDisabled()
      await expect(picker.getByLabel(stickers[1].code+' 份数',{exact:true})).toBeDisabled()
      await picker.getByRole('button',{name:stickers[0].code+' 减少份数',exact:true}).click()
      await expect(picker.getByRole('button',{name:stickers[1].code+' 增加份数',exact:true})).toBeEnabled()
      await picker.getByRole('button',{name:stickers[1].code+' 增加份数',exact:true}).click()
      await screen.screenshot({path:`/tmp/selection-limit-${mode}-picker.png`,fullPage:true})
      expect(await screen.evaluate(()=>document.documentElement.scrollWidth>innerWidth)).toBe(false)
      await picker.getByRole('button',{name:'应用选择'}).click()
      await expect(screen.getByLabel('订单选图统计')).toContainText('订单已选 10 / 10 张')
      await screen.getByRole('button',{name:'选择模板和贴纸'}).nth(0).click()
      picker=screen.getByRole('dialog',{name:'选择模板和贴纸'})
      await picker.getByRole('button',{name:'单张贴纸',exact:true}).click();await picker.getByLabel('搜索模板或贴纸').fill(suffix)
      await picker.getByLabel(stickers[0].code+' 份数',{exact:true}).fill('999')
      await expect(picker.getByLabel(stickers[0].code+' 份数',{exact:true})).toHaveValue('5')
      await picker.getByRole('button',{name:stickers[0].code+' 减少份数',exact:true}).click()
      await expect(picker.getByLabel('订单选图统计')).toContainText('订单已选 9 / 10 张')
      await picker.getByRole('button',{name:'应用选择'}).click()
      await screen.getByRole('button',{name:'移除头像 1',exact:true}).click()
      await expect(screen.getByLabel('订单选图统计')).toContainText('订单已选 5 / 10 张')
      expect(errors).toEqual([])
    }finally{await context.close()}
  })
}
