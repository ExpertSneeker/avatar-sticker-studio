import {test,expect} from '@playwright/test'
import {readFileSync} from 'node:fs'
import {completedCustomer,staffLogin} from './customer-fixtures'
import {uploadStickers} from './library-fixtures'
const evidence=(name:string)=>'/tmp/avatar-studio-fal-qa/'+name

test('admin cleanup previews protected customer history and preserves orders and templates',async({page})=>{
  await staffLogin(page.request)
  const pixel=readFileSync(new URL('./fixtures/portrait.png',import.meta.url))
  const stickers=await uploadStickers(page.request,[{name:'清理测试贴纸.png',mimeType:'image/png',buffer:pixel}])
  const created=await page.request.post('/api/templates',{data:{code:'CLEAN-SET',name:'清理测试套装',category:'general',sticker_ids:stickers.map((sticker:{id:string})=>sticker.id)}})
  expect(created.ok(),await created.text()).toBeTruthy()
  const fixture=await completedCustomer(page.request,stickers[0].id,{notes:'清理保护测试'})
  const manifestBefore=await(await page.request.get('/api/customer-orders/'+fixture.id+'/manifest')).json()
  const templates=await(await page.request.get('/api/templates')).json()
  await page.goto('/')
  await page.getByRole('navigation').getByRole('button',{name:'管理设置'}).click()
  await expect(page.getByText('磁盘总容量',{exact:true})).toBeVisible()
  await page.getByLabel('清理此日期之前的订单').fill('2027-01-01')
  const previewResponse=page.waitForResponse(response=>response.url().endsWith('/api/admin/cleanup/preview'))
  await page.getByRole('button',{name:'预览清理范围'}).click()
  const preview=await(await previewResponse).json()
  expect(preview).toMatchObject({order_count:0,item_count:0,file_count:0})
  const dialog=page.getByRole('dialog').last()
  await expect(dialog.getByRole('heading',{name:'确认清理服务器订单'})).toBeVisible()
  await expect(dialog.getByRole('button',{name:'确认永久清理'})).toBeDisabled()
  await page.screenshot({path:evidence('admin-cleanup-confirm.png'),animations:'disabled'})
  await expect(dialog.getByLabel('我确认永久删除上述服务器订单及文件')).toBeDisabled()
  const cleanup=await page.request.post('/api/admin/cleanup',{data:{before:preview.before,preview_token:preview.preview_token,confirmed:true}})
  expect(cleanup.ok(),await cleanup.text()).toBeTruthy()
  expect(await cleanup.json()).toMatchObject({deleted_orders:0})
  expect(await(await page.request.get('/api/customer-orders/'+fixture.id)).json()).toEqual(fixture)
  expect(await(await page.request.get('/api/customer-orders/'+fixture.id+'/manifest')).json()).toEqual(manifestBefore)
  await dialog.getByRole('button',{name:'关闭',exact:true}).click()
  await expect(dialog).not.toBeVisible()
  expect(await(await page.request.get('/api/templates')).json()).toEqual(templates)
  await page.locator('.maintenance-panel').scrollIntoViewIfNeeded()
  await page.screenshot({path:evidence('admin-storage.png'),animations:'disabled'})
})
