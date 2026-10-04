import {test,expect} from '@playwright/test'
import {readFileSync} from 'node:fs'
import {createCustomer,generateCustomer,mutate,staffLogin,submitCustomer,uploadAvatar} from './customer-fixtures'
import {uploadStickers} from './library-fixtures'
test('mixed public selections deduplicate generation and retain every exported copy',async({page})=>{
 await staffLogin(page.request)
 const pixel=readFileSync(new URL('./fixtures/portrait.png',import.meta.url))
 const stickers=await uploadStickers(page.request,[{name:'MIX-one.png',mimeType:'image/png',buffer:pixel},{name:'MIX-two.png',mimeType:'image/png',buffer:pixel}])
 const sets=[]
 for(const code of ['MIX-A','MIX-B']){const response=await page.request.post('/api/templates',{data:{code,name:code,category:'general',sticker_ids:[stickers[0].id]}});expect(response.ok()).toBeTruthy();sets.push(await response.json())}
 const customer=await createCustomer(page.request,{generation_limit:4,final_count:4})
 await page.goto('/')
 await page.getByRole('button').filter({hasText:customer.order_number}).first().click()
 await page.getByLabel('上传头像').setInputFiles({name:'混合验收.png',mimeType:'image/png',buffer:pixel})
 await page.getByRole('button',{name:'选择模板和贴纸'}).click()
 // The picker opens above the order-detail modal, so address it by name.
 const dialog=page.getByRole('dialog',{name:'选择模板和贴纸'})
 await dialog.getByRole('button',{name:'模板套装',exact:true}).click()
 await dialog.getByLabel('搜索模板或贴纸').fill('MIX-')
 for(const code of ['MIX-A','MIX-B'])await dialog.getByLabel(code+' 份数').fill('1')
 await dialog.getByRole('button',{name:'单张贴纸',exact:true}).click()
 for(const sticker of stickers)await dialog.getByLabel(sticker.code+' 份数').fill('1')
 await expect(dialog.getByText('本头像已选 4 张',{exact:false})).toBeVisible()
 await page.screenshot({path:'/tmp/avatar-studio-fal-qa/mixed-selection-desktop.png'})
 await page.setViewportSize({width:390,height:844});expect(await dialog.evaluate(e=>e.scrollWidth<=e.clientWidth)).toBe(true)
 await page.screenshot({path:'/tmp/avatar-studio-fal-qa/mixed-selection-mobile.png'})
 await dialog.getByRole('button',{name:'应用选择'}).click()
 // The avatar row reports deduplicated generation work after the picker closes.
 await expect(page.locator('.customer-avatar-name').getByText('4 张已选 · 2 张实际生成')).toBeVisible()
 await expect(page.locator('.customer-submit-bar')).toContainText('实际生成 2 张')
 const avatars=[{upload_id:await uploadAvatar(page.request,'混合验收.png'),template_ids:sets.map(s=>s.id),sticker_ids:stickers.map(s=>s.id)}]
 const latest=await(await page.request.get('/api/customer-orders/'+customer.id)).json()
 const preflight=await mutate(page.request,latest,'preflight',{avatars})
 expect(preflight).toMatchObject({generation_count:2,selection_count:4})
 const generated=await generateCustomer(page.request,customer,avatars)
 expect(generated.slots).toHaveLength(4)
 expect(new Set(generated.slots.map((slot:any)=>slot.selected_version_id)).size).toBe(2)
 const shared=generated.slots.filter((slot:any)=>slot.sticker_code===stickers[0].code)
 expect(shared).toHaveLength(3)
 expect(new Set(shared.map((slot:any)=>slot.selected_version_id)).size).toBe(1)
 const submitted=await submitCustomer(page.request,generated)
 expect(submitted.state).toBe('submitted')
 expect(submitted.slots).toHaveLength(4)
 const manifest=await(await page.request.get('/api/customer-orders/'+customer.id+'/manifest')).json()
 expect(manifest.files.every((file:{kind:string})=>file.kind==='print')).toBe(true)
})

test('retired browser drafts cannot create orders or bind download destinations',async({page})=>{
 await staffLogin(page.request)
 const user=await(await page.request.get('/api/auth/me')).json()
 // Seed before mounting the app so its initial empty-draft persistence cannot overwrite the fixture.
 await page.goto('/api/health')
 await page.evaluate(async(id)=>{
  const db=await new Promise<IDBDatabase>((resolve,reject)=>{const r=indexedDB.open('avatar-stickers-v1',1);r.onupgradeneeded=()=>r.result.createObjectStore('state');r.onsuccess=()=>resolve(r.result);r.onerror=()=>reject(r.error)})
  await new Promise<void>((resolve,reject)=>{const tx=db.transaction('state','readwrite');tx.objectStore('state').put([{id:'legacy-missing',name:'旧草稿',file:new File(['x'],'legacy.png',{type:'image/png'}),template_ids:['removed-template'],sticker_ids:['removed-sticker'],print_settings:{paper_width_mm:210,paper_height_mm:297,long_edge_mm:85,margin_mm:10,gap_mm:10,dpi:300,brightness:false,color_balance:false},client_token:'legacy-missing'}],'drafts:'+id);tx.oncomplete=()=>resolve();tx.onerror=()=>reject(tx.error)});db.close()
 },user.id)
 await page.goto('/')
 await expect(page.getByRole('heading',{name:'客户订单',exact:true})).toBeVisible()
 await expect(page.getByRole('button',{name:'提交生成',exact:true})).toHaveCount(0)
 await expect(page.getByText('旧草稿',{exact:true})).toHaveCount(0)
 await expect(page.getByRole('button',{name:'选择保存目录',exact:true})).toHaveCount(0)
})
