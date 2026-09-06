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
test('first task destination establishes global default; later selections only override one task',async({page})=>{
 await login(page)
 await page.addInitScript(()=>{
  const state=window as any;state.folderCalls=[];state.folderName='global-default';state.cancelFolder=true
  window.showDirectoryPicker=async options=>{state.folderCalls.push(options);if(state.cancelFolder)throw new DOMException('Cancelled','AbortError');return(await navigator.storage.getDirectory()).getDirectoryHandle(state.folderName,{create:true})}
 })
 await page.goto('/')
 await page.locator('input[type=file]').setInputFiles(['一号','二号'].map(name=>({name:name+'.png',mimeType:'image/png',buffer:pixel})))
 const buttons=page.getByTitle('单独选择此订单的保存位置')
 await buttons.first().click()
 await expect(page.locator('.directory-button')).toHaveText('选择保存目录')
 await expect(buttons.nth(1)).toHaveText('选择保存位置')
 await page.evaluate(()=>{(window as any).cancelFolder=false})
 await buttons.first().click()
 await expect(page.locator('.directory-button')).toHaveText('global-default')
 await expect(buttons.first()).toHaveText('默认：global-default')
 await expect(buttons.nth(1)).toHaveText('默认：global-default')
 await page.evaluate(()=>{(window as any).folderName='single-task'})
 await buttons.first().click()
 await expect(buttons.first()).toHaveText('single-task')
 await expect(buttons.nth(1)).toHaveText('默认：global-default')
 await expect(page.locator('.directory-button')).toHaveText('global-default')
 await page.reload()
 await expect(buttons.first()).toHaveText('single-task')
 await expect(buttons.nth(1)).toHaveText('默认：global-default')
 await page.screenshot({path:join(tmpdir(),'avatar-studio-fal-qa','directory-default-flow.png'),animations:'disabled'})
})
test('task name and details open the same dialog and retain list filters',async({page})=>{
 await login(page)
 const order={id:'dialog-fixture',name:'弹窗任务',created_at:new Date().toISOString(),status:'queued',total:12,completed:0,failed:0,unknown:0,paused:false,avatar_url:'data:image/png;base64,'+pixel.toString('base64'),template_codes:['B001'],print_settings:{paper_width_mm:210,paper_height_mm:297,long_edge_mm:85,margin_mm:10,gap_mm:10,dpi:300,brightness:false,color_balance:false},artifact_version:0,artifacts:[],items:[],download_ready:false}
 await page.route('**/api/orders',r=>r.fulfill({json:[order]}))
 await page.route('**/api/orders/dialog-fixture',r=>r.fulfill({json:order}))
 await page.goto('/')
 await page.getByRole('navigation').getByRole('button',{name:'任务中心',exact:true}).click()
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
