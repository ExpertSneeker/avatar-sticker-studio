import {test,expect} from '@playwright/test'
import {readFileSync} from 'node:fs'
import {uploadStickers} from './library-fixtures'

test('deletion lists template references then removes only unreferenced stickers',async({page})=>{
 const status=await(await page.request.get('/api/auth/status')).json()
 await page.request.post(status.needs_setup?'/api/auth/setup':'/api/auth/login',{data:{username:'testadmin',password:'local-test-password',...(status.needs_setup?{display_name:'测试管理员'}:{})}})
 const pixel=readFileSync(new URL('./fixtures/portrait.png',import.meta.url))
 const [sticker]=await uploadStickers(page.request,[{name:'DELETE-ONE.png',mimeType:'image/png',buffer:pixel}])
 const templates=[]
 for(const code of ['DELETE-A','DELETE-B']){
  const response=await page.request.post('/api/templates',{data:{code,name:'引用模板 '+code,category:'general',sticker_ids:[sticker.id]}})
  expect(response.ok()).toBeTruthy();templates.push(await response.json())
 }
 expect((await page.request.patch('/api/templates/'+templates[1].id,{data:{active:false}})).status()).toBe(410)
 const deletes:string[]=[]
 page.on('request',r=>{if(r.method()==='DELETE')deletes.push(r.url())})
 await page.goto('/')
 await page.getByRole('navigation').getByRole('button',{name:'贴纸库',exact:true}).click()
 await page.getByLabel('搜索贴纸',{exact:true}).fill('DELETE-ONE')
 await page.getByRole('button',{name:'删除贴纸 DELETE-ONE',exact:true}).click()
 const dialog=page.getByRole('dialog')
 await expect(dialog).toContainText('确认删除贴纸')
 await dialog.getByRole('button',{name:'取消',exact:true}).click()
 await expect(page.getByRole('dialog')).toHaveCount(0)
 expect(deletes).toHaveLength(0)
 await page.getByRole('button',{name:'删除贴纸 DELETE-ONE',exact:true}).click()
 await dialog.getByRole('button',{name:'确认删除',exact:true}).click()
 await expect(dialog).toContainText('贴纸仍被模板使用')
 await expect(dialog).toContainText('引用模板 DELETE-A')
 await expect(dialog).toContainText('引用模板 DELETE-B')
 await expect(dialog).not.toContainText('已下架')
 await dialog.screenshot({path:'/tmp/library-delete-references.png'})
 await dialog.getByRole('button',{name:'知道了'}).click()
 await expect(page.locator('.library-set')).toHaveCount(1)
 await page.getByRole('navigation').getByRole('button',{name:'模板库',exact:true}).click()
 await page.getByLabel('搜索模板',{exact:true}).fill('DELETE-')
 for(const code of ['DELETE-A','DELETE-B']){
  const count=deletes.length
  await page.getByRole('button',{name:'删除模板 '+code,exact:true}).click()
  await expect(dialog).toContainText('确认删除模板')
  await expect(dialog).toContainText(code)
  await dialog.getByRole('button',{name:'取消',exact:true}).click()
  expect(deletes).toHaveLength(count)
  await expect(page.getByRole('button',{name:'删除模板 '+code,exact:true})).toBeVisible()
  await page.getByRole('button',{name:'删除模板 '+code,exact:true}).click()
  await dialog.getByRole('button',{name:'确认删除',exact:true}).click()
  await expect(dialog).toHaveCount(0)
 }
 await expect(page.locator('.library-set')).toHaveCount(0)
 expect((await(await page.request.get('/api/stickers')).json()).some((s:{id:string})=>s.id===sticker.id)).toBe(true)
 await page.getByRole('navigation').getByRole('button',{name:'贴纸库',exact:true}).click()
 await page.getByLabel('搜索贴纸',{exact:true}).fill('DELETE-ONE')
 await page.getByRole('button',{name:'删除贴纸 DELETE-ONE',exact:true}).click()
 await expect(dialog).toContainText('确认删除贴纸')
 await dialog.getByRole('button',{name:'确认删除',exact:true}).click()
 await expect(page.locator('.library-set')).toHaveCount(0)
 expect((await(await page.request.get('/api/stickers')).json()).some((s:{id:string})=>s.id===sticker.id)).toBe(false)
 expect((await page.request.get(sticker.image.url)).ok()).toBe(true)
})
