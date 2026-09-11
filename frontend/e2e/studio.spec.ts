import {uploadStickers} from './library-fixtures'
import {test,expect} from '@playwright/test'
import {staffLogin,uploadAvatar,pixel} from './customer-fixtures'
const evidence=(name:string)=>'/tmp/avatar-studio-fal-qa/'+name

test('legacy orders remain readable with manual print-only delivery and global settings',async({page})=>{
 await staffLogin(page.request)
 const stickers=await uploadStickers(page.request,Array.from({length:12},(_,i)=>({name:`template-${i+1}.png`,mimeType:'image/png',buffer:pixel})))
 const template=await(await page.request.post('/api/templates',{data:{code:'B001',name:'春日出游',category:'general',sticker_ids:stickers.map(s=>s.id)}})).json()
 const response=await page.request.post('/api/orders',{data:{upload_id:await uploadAvatar(page.request),name:'历史样本',template_ids:[template.id],print_settings:{long_edge_mm:50},client_token:'legacy-browser-seed'}})
 expect(response.ok(),await response.text()).toBe(true);const order=await response.json()
 await expect.poll(async()=>(await(await page.request.get('/api/orders/'+order.id)).json()).download_ready,{timeout:60000}).toBe(true)
 const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message))
 await page.goto('/')
 await page.getByRole('navigation').getByRole('button',{name:'历史订单',exact:true}).click()
 await expect(page.getByRole('heading',{name:'历史订单',exact:true,level:1})).toBeVisible()
 await page.locator('.task-main').filter({hasText:'历史样本'}).click()
 const dialog=page.getByRole('dialog').first()
 await expect(dialog.getByRole('heading',{name:'历史样本',exact:true})).toBeVisible()
 await expect(dialog.getByRole('link',{name:'下载此图'})).toHaveCount(0)
 await expect(dialog.getByRole('link',{name:'下载打印图'})).not.toHaveCount(0)
 const manifest=await(await page.request.get('/api/orders/'+order.id+'/manifest')).json()
 expect(manifest.files.every((f:{kind:string})=>f.kind==='print')).toBe(true)
 await dialog.getByRole('button',{name:'单张结果'}).click();await dialog.locator('.result-card').first().click()
 await expect(page.getByRole('dialog').last().locator('.compare-grid figure')).toHaveCount(3)
 await expect(page.getByRole('link',{name:'下载单张'})).toHaveCount(0)
 await page.keyboard.press('Escape');await page.keyboard.press('Escape')
 await page.getByRole('navigation').getByRole('button',{name:'管理设置',exact:true}).click()
 await expect(page.getByLabel('FAL API Key')).toHaveAttribute('type','password')
 await expect(page.getByLabel('最大同时处理数量')).toHaveAttribute('max','40')
 await page.screenshot({path:evidence('legacy-and-global-settings.png'),fullPage:true})
 expect(errors).toEqual([])
})

test('FAL queue recovery preserves original request and requires confirmation before releasing unknown work', async ({page})=>{
  await page.request.post('/api/auth/login',{data:{username:'testadmin',password:'local-test-password'}})
  const orders=await (await page.request.get('/api/orders')).json()
  const detail=await (await page.request.get(`/api/orders/${orders[0].id}`)).json()
  const endpoint=`/api/orders/${detail.id}`
  Object.assign(detail,{unknown:2,completed:10,status:'unknown'})
  Object.assign(detail.items[0],{status:'unknown',processing_stage:'generate',fal_request_id:'fal-original-request',fal_status:'IN_PROGRESS',remote_reserved:true,recoverable:true,can_resolve:true,error:'FAL连接需要恢复'})
  Object.assign(detail.items[1],{status:'unknown',processing_stage:'generate',fal_request_id:null,fal_status:null,remote_reserved:true,recoverable:false,can_resolve:true,error:'FAL提交响应丢失'})
  const first=detail.items[0], second=detail.items[1]
  const mutations:string[]=[]
  await page.route(`**${endpoint}`,route=>route.fulfill({json:detail}))
  await page.route(`**${endpoint}/items/**`,async route=>{
    const request=route.request(),path=new URL(request.url()).pathname
    expect(request.method()).toBe('POST')
    mutations.push(path)
    if(path.endsWith('/recover'))Object.assign(first,{status:'running',fal_status:'IN_QUEUE',queue_position:2,recoverable:false,can_resolve:false,error:null})
    else if(path.endsWith('/resolve')){
      expect(request.postDataJSON()).toEqual({confirmed_ended:true})
      Object.assign(second,{status:'failed',remote_reserved:false,can_resolve:false,error:'已确认原请求结束'})
    }else throw new Error('Recovery must not submit a new generation')
    await route.fulfill({json:detail})
  })
  await page.goto('/')
  await page.getByRole('navigation').getByRole('button',{name:'历史订单'}).click()
  await page.getByRole('button',{name:new RegExp(detail.name+'.*B001')}).click()
  await page.getByRole('button',{name:'单张结果'}).click()
  await page.locator('.result-card').first().click()
  const dialog=page.getByRole('dialog').last()
  await expect(dialog.getByText('fal-original-request',{exact:true})).toBeVisible()
  expect(await dialog.locator('.compare-grid figure').first().locator('img').evaluate(image=>image.getBoundingClientRect().bottom<=image.closest('figure')!.getBoundingClientRect().bottom+1)).toBe(true)
  for(const image of await dialog.locator('.compare-grid img').all()){
    await image.evaluate(async (img:HTMLImageElement)=>{await img.decode();await new Promise(requestAnimationFrame)})
    expect((await image.boundingBox())!.height).toBeGreaterThan(64)
  }
  for(const button of await dialog.locator('.compare-grid').getByRole('button',{name:'查看原图',exact:true}).all())await expect(button).toBeInViewport()
  await page.screenshot({path:evidence('fal-request-unknown.png'),animations:'disabled'})

  await expect(dialog.getByRole('button',{name:/重新生成/})).toBeDisabled()
  await dialog.getByRole('button',{name:'恢复原请求',exact:true}).click()
  await expect(dialog.getByText('FAL 排队中 · 前方 2 个请求',{exact:true})).toBeVisible()
  await expect(dialog.getByText('fal-original-request',{exact:true})).toBeVisible()
  await dialog.getByRole('button',{name:'关闭',exact:true}).click()
  await page.locator('.result-card').nth(1).click()
  await expect(dialog.getByRole('button',{name:'恢复原请求',exact:true})).toHaveCount(0)
  const release=dialog.getByRole('button',{name:'释放并发占用',exact:true})
  await expect(release).toBeDisabled()
  await dialog.getByLabel('我已在 FAL 控制台确认原请求已结束或不存在').check()
  await release.click()
  await expect(dialog.getByRole('button',{name:'重新生成这一张',exact:true})).toBeEnabled()
  expect(mutations).toEqual([`${endpoint}/items/${first.id}/recover`,`${endpoint}/items/${second.id}/resolve`])
  await page.screenshot({path:evidence('fal-recovery.png'),animations:'disabled'})
})


test('submission date periods intersect search results',async({page})=>{
  await page.request.post('/api/auth/login',{data:{username:'testadmin',password:'local-test-password'}})
  const base=(await(await page.request.get('/api/orders')).json())[0]
  const rows=[0.5,2,5,15,40].map(days=>({...base,id:'date-'+days,name:'日期测试 '+days,created_at:new Date(Date.now()-days*86400000).toISOString(),download_ready:false,artifact_version:0,preview_url:null}))
  await page.route('**/api/orders',route=>route.fulfill({json:rows}))
  await page.goto('/')
  await page.getByRole('navigation').getByRole('button',{name:'历史订单'}).click()
  await expect(page.locator('.task-row time')).toHaveCount(5)
  for(const [days,count]of [['1',1],['3',2],['7',3],['30',4],['0',5]] as const){
    await page.getByLabel('提交时间范围').selectOption(days)
    await expect(page.locator('.task-row')).toHaveCount(count)
  }
  await page.getByLabel('搜索订单',{exact:true}).fill('日期测试 5')
  await page.getByLabel('提交时间范围').selectOption('3')
  // Multi-term substring search also matches the 5 in 0.5 and 15.
  await expect(page.locator('.task-row')).toHaveCount(1)
  await expect(page.locator('.task-row')).toContainText('日期测试 0.5')
  await page.getByLabel('提交时间范围').selectOption('7')
  await expect(page.locator('.task-row')).toHaveCount(2)
  await page.screenshot({path:evidence('order-date-search.png'),animations:'disabled'})
})


test('admin cleanup previews scope then removes isolated orders while preserving templates',async({page})=>{
  await page.request.post('/api/auth/login',{data:{username:'testadmin',password:'local-test-password'}})
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
