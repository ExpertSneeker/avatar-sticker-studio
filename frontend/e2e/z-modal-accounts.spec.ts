import {test,expect} from '@playwright/test'
import {staffLogin} from './customer-fixtures'
test('account concurrency dialog preserves search and restores focus at desktop and mobile',async({page})=>{
 await staffLogin(page.request)
 await page.request.post('/api/admin/users',{data:{username:'modalmember',display_name:'弹窗验收成员'}})
 await page.goto('/');await page.getByRole('navigation').getByRole('button',{name:'账户管理',exact:true}).click()
 await page.getByRole('textbox',{name:'搜索账号'}).fill('modalmember')
 await page.getByRole('button',{name:'并行上限',exact:true}).click()
 const dialog=page.getByRole('dialog')
 await expect(dialog.getByLabel('最多同时生图数量')).toBeVisible()
 await page.keyboard.press('Escape');await expect(dialog).toHaveCount(0)
 await expect(page.getByRole('button',{name:'并行上限',exact:true})).toBeFocused()
 await page.getByRole('button',{name:'并行上限',exact:true}).click()
 await page.setViewportSize({width:390,height:844});await expect(dialog).toBeInViewport()
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true)
 await page.screenshot({path:'/tmp/avatar-studio-fal-qa/account-dialog-mobile.png'})
 await page.keyboard.press('Escape');await expect(page.getByRole('textbox',{name:'搜索账号'})).toHaveValue('modalmember')
 expect(await page.evaluate(()=>document.body.style.overflow)).not.toBe('hidden')
})
