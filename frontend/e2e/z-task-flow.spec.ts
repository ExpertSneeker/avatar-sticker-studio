import {test,expect,type Page} from '@playwright/test'
import {readFileSync} from 'node:fs'
import {join} from 'node:path'
import {tmpdir} from 'node:os'
const pixel=readFileSync(new URL('./fixtures/portrait.png',import.meta.url))
async function login(page:Page){
 const setup=await page.request.post('/api/auth/setup',{data:{username:'flowadmin',password:'flow-test-password',display_name:'流程验收管理员'}})
 const response=await page.request.post('/api/auth/login',{data:setup.ok()?{username:'flowadmin',password:'flow-test-password'}:{username:'testadmin',password:'local-test-password'}})
 if(!response.ok())await page.request.post('/api/auth/login',{data:{username:'flowadmin',password:'flow-test-password'}})
}
test('opening an order requires no directory picker or persisted draft binding',async({page})=>{
 await login(page)
 await page.addInitScript(()=>{(window as any).folderCalls=0;window.showDirectoryPicker=async()=>{(window as any).folderCalls++;throw new DOMException('Cancelled','AbortError')}})
 await page.goto('/')
 await page.getByRole('button',{name:'开新订单'}).click()
 const dialog=page.getByRole('dialog',{name:'开新订单'})
 await dialog.getByLabel('订单号',{exact:true}).fill('NO-DIRECTORY-'+Date.now())
 await dialog.getByRole('button',{name:'创建订单',exact:true}).click()
 await expect(page.getByLabel('上传头像')).toHaveCount(1)
 await expect(page.getByRole('button',{name:'选择保存目录'})).toHaveCount(0)
 expect(await page.evaluate(()=>(window as any).folderCalls)).toBe(0)
})
test('task name and details open the same dialog and retain list filters',async({page})=>{
 await login(page)
 const order={id:'dialog-fixture',name:'弹窗任务',created_at:new Date().toISOString(),status:'queued',total:12,completed:0,failed:0,unknown:0,paused:false,avatar_url:'data:image/png;base64,'+pixel.toString('base64'),template_codes:['B001'],print_settings:{paper_width_mm:210,paper_height_mm:297,long_edge_mm:85,margin_mm:10,gap_mm:10,dpi:300,brightness:false,color_balance:false},artifact_version:0,artifacts:[],items:[],download_ready:false}
 await page.route('**/api/orders',r=>r.fulfill({json:[order]}))
 await page.route('**/api/orders/dialog-fixture',r=>r.fulfill({json:order}))
 await page.goto('/')
 await page.getByRole('navigation').getByRole('button',{name:'历史订单',exact:true}).click()
 await page.getByRole('textbox',{name:'搜索订单'}).fill('弹窗')
 await page.getByRole('button',{name:'查看详情',exact:true}).click()
 const detail=page.getByRole('dialog',{name:'弹窗任务 · 任务详情',exact:true})
 await expect(detail).toBeVisible()
 await detail.getByRole('button',{name:'重新排版',exact:true}).click()
 await expect(page.getByRole('dialog',{name:'重新排版',exact:true})).toBeVisible()
 await page.keyboard.press('Escape')
 await expect(detail).toBeVisible()
 await page.setViewportSize({width:390,height:844})
 await expect(detail).toBeInViewport()
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true)
 await page.screenshot({path:join(tmpdir(),'avatar-studio-fal-qa','task-detail-mobile.png'),animations:'disabled'})
 await detail.getByRole('button',{name:'关闭',exact:true}).click()
 await expect(page.getByRole('textbox',{name:'搜索订单'})).toHaveValue('弹窗')
 await page.locator('.task-main').click()
 await expect(detail).toBeVisible()
 await page.keyboard.press('Escape')
 await expect(detail).toHaveCount(0)
})
