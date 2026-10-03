import {test,expect,type Page} from '@playwright/test'
import {randomUUID} from 'node:crypto'
import {uploadStickers} from './library-fixtures'
import {createCustomer,pixel,staffLogin} from './customer-fixtures'

const draftOf=async(page:Page,id:string)=>(await(await page.request.get('/api/customer-orders/'+id)).json()).draft

test('guest avatars and choices survive reloads, reach staff and sync both ways before generation',async({page,context})=>{
  await staffLogin(page.request)
  const suffix=randomUUID().slice(0,8)
  const stickers=await uploadStickers(page.request,[0,1,2].map(i=>({name:`DRAFT-${suffix}-${i}.png`,mimeType:'image/png',buffer:pixel})))
  const order=await createCustomer(page.request,{generation_limit:6,final_count:2})
  const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message))
  await page.goto('/guest')
  await page.getByLabel('订单号',{exact:true}).fill(order.order_number);await page.getByRole('button',{name:'进入订单'}).click()
  await page.getByLabel('上传头像').setInputFiles({name:'草稿头像.png',mimeType:'image/png',buffer:pixel})
  await expect(page.locator('.customer-avatar-row')).toHaveCount(1)
  await page.getByRole('button',{name:'选择模板和贴纸'}).click()
  const picker=page.getByRole('dialog',{name:'选择模板和贴纸'})
  await picker.getByLabel('搜索模板或贴纸').fill(suffix)
  await picker.getByLabel(stickers[0].code+' 份数',{exact:true}).fill('2')
  await picker.getByRole('button',{name:'应用选择'}).click()
  await expect.poll(async()=>(await draftOf(page,order.id))?.avatars?.[0]?.sticker_ids?.length).toBe(2)
  const summary=page.getByLabel('订单选图统计')
  await expect(summary).toContainText('订单已选 2 / 6 张')

  // A reload restores the avatar (with its image) and its choices.
  await page.reload()
  await expect(page.locator('.customer-avatar-row')).toHaveCount(1)
  await expect(summary).toContainText('订单已选 2 / 6 张')
  const avatarImage=page.locator('.customer-avatar-row img').first()
  await expect.poll(()=>avatarImage.evaluate((image:HTMLImageElement)=>image.complete&&image.naturalWidth)).toBeGreaterThan(0)
  await page.getByRole('button',{name:'选择模板和贴纸'}).click()
  await picker.getByLabel('搜索模板或贴纸').fill(suffix)
  await expect(picker.getByLabel(stickers[0].code+' 份数',{exact:true})).toHaveValue('2')
  await page.keyboard.press('Escape')

  // Staff opening the order see the customer's working list.
  const staff=await context.newPage()
  await staff.goto('/');await staff.getByLabel('订单号',{exact:true}).fill(order.order_number)
  await staff.getByRole('button',{name:'进入 / 代操作',exact:true}).click()
  const orderDialog=staff.getByRole('dialog',{name:'订单 '+order.order_number,exact:true})
  await expect(orderDialog.locator('.customer-avatar-row')).toHaveCount(1)
  await expect(orderDialog.getByLabel('订单选图统计')).toContainText('订单已选 2 / 6 张')
  // Staff help pick another sticker; the open customer page follows without a reload.
  await orderDialog.getByRole('button',{name:'选择模板和贴纸'}).click()
  const staffPicker=staff.getByRole('dialog',{name:'选择模板和贴纸'})
  await staffPicker.getByLabel('搜索模板或贴纸').fill(suffix)
  await staffPicker.getByLabel(stickers[1].code+' 份数',{exact:true}).fill('1')
  await staffPicker.getByRole('button',{name:'应用选择'}).click()
  await expect(summary).toContainText('订单已选 3 / 6 张')
  await staff.close()

  // Removing the avatar is saved too.
  await page.getByRole('button',{name:'移除头像 1'}).click()
  await expect.poll(async()=>(await draftOf(page,order.id))?.avatars?.length).toBe(0)
  await page.reload()
  await expect(page.getByText('从一张清晰的头像开始')).toBeVisible()
  expect(errors).toEqual([])
})
