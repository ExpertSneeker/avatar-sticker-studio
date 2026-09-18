import {test,expect} from '@playwright/test'
import {readFileSync} from 'node:fs'
import {createHash} from 'node:crypto'
import {staffLogin} from './customer-fixtures'
import {uploadStickers} from './library-fixtures'
const evidence=(name:string)=>'/tmp/avatar-studio-fal-qa/'+name

test('admin cleanup previews scope then removes isolated orders while preserving templates',async({page})=>{
  await staffLogin(page.request)
  const pixel=readFileSync(new URL('./fixtures/portrait.png',import.meta.url))
  const stickers=await uploadStickers(page.request,[{name:'清理测试贴纸.png',mimeType:'image/png',buffer:pixel}])
  const created=await page.request.post('/api/templates',{data:{code:'CLEAN-SET',name:'清理测试套装',category:'general',sticker_ids:stickers.map((sticker:{id:string})=>sticker.id)}})
  expect(created.ok(),await created.text()).toBeTruthy()
  const template=await created.json()
  const uploaded=await(await page.request.post('/api/uploads/init',{data:{filename:'清理测试订单.png',size:pixel.length,sha256:createHash('sha256').update(pixel).digest('hex')}})).json()
  await page.request.put('/api/uploads/'+uploaded.id,{data:pixel,headers:{'Upload-Offset':'0'}})
  await page.request.post('/api/uploads/'+uploaded.id+'/complete')
  const fixture=await(await page.request.post('/api/orders',{data:{upload_id:uploaded.id,name:'清理测试订单',template_ids:[template.id],print_settings:{},client_token:'admin-cleanup-fixture'}})).json()
  await expect.poll(async()=> (await(await page.request.get('/api/orders/'+fixture.id)).json()).status,{timeout:60000}).toBe('completed')
  await expect.poll(async()=>(await(await page.request.get('/api/orders')).json()).every((o:{download_ready:boolean})=>o.download_ready),{timeout:40000}).toBe(true)
  const templates=await(await page.request.get('/api/templates')).json()
  await page.goto('/')
  await page.getByRole('navigation').getByRole('button',{name:'管理设置'}).click()
  await expect(page.getByText('磁盘总容量',{exact:true})).toBeVisible()
  await page.getByLabel('清理此日期之前的订单').fill('2027-01-01')
  await page.getByRole('button',{name:'预览清理范围'}).click()
  const dialog=page.getByRole('dialog').last()
  await expect(dialog.getByRole('heading',{name:'确认清理服务器订单'})).toBeVisible()
  await expect(dialog.getByRole('button',{name:'确认永久清理'})).toBeDisabled()
  await page.screenshot({path:evidence('admin-cleanup-confirm.png'),animations:'disabled'})
  await dialog.getByLabel('我确认永久删除上述服务器订单及文件').check()
  await dialog.getByRole('button',{name:'确认永久清理'}).click()
  await expect(dialog).not.toBeVisible()
  expect(await(await page.request.get('/api/orders')).json()).toEqual([])
  expect(await(await page.request.get('/api/templates')).json()).toEqual(templates)
  await page.locator('.maintenance-panel').scrollIntoViewIfNeeded()
  await page.screenshot({path:evidence('admin-storage.png'),animations:'disabled'})
})
