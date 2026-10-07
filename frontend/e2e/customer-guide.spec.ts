import { test, expect, type Page } from '@playwright/test'
import { uploadStickers } from './library-fixtures'
import { createCustomer, pixel, staffLogin } from './customer-fixtures'

// Walks the whole guest flow with the walkthrough forced on (automated browsers skip it by default).
for(const viewport of [{name:'mobile',width:390,height:844},{name:'desktop',width:1440,height:1000}]){
  test(`guest walkthrough guides every step on ${viewport.name}`,async({page,browser})=>{
    await staffLogin(page.request)
    await uploadStickers(page.request,[{name:`GUIDE-${viewport.name}.png`,mimeType:'image/png',buffer:pixel}])
    const order=await createCustomer(page.request,{generation_limit:2,final_count:1,rerun_limit:1})
    const context=await browser.newContext({baseURL:'http://127.0.0.1:5174',viewport})
    await context.addInitScript(()=>localStorage.setItem('guest-guide:force','1'))
    const guest=await context.newPage(),errors:string[]=[]
    guest.on('pageerror',e=>errors.push(e.message))
    const shot=(name:string)=>guest.screenshot({path:`/tmp/avatar-studio-fal-qa/guide-${viewport.name}-${name}.png`})
    const tip=guest.getByRole('dialog',{name:'操作提示'})
    const fits=async(page:Page)=>expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true)
    try{
      await guest.goto('/guest')
      await expect(tip).toContainText('在这里输入订单号');await shot('1-order-number');await fits(guest)
      await guest.getByLabel('订单号',{exact:true}).click()
      await guest.getByLabel('订单号',{exact:true}).fill(order.order_number)
      await expect(tip).toContainText('输好后点这里进入')
      await guest.getByRole('button',{name:'进入订单'}).click()

      await expect(guest.getByText('请上传头部清晰完整、无遮挡的照片')).toBeVisible()
      for(const alt of ['正确示范','错误示范 1','错误示范 2','错误示范 3'])await expect(guest.getByAltText(new RegExp(alt)).first()).toBeVisible()
      await expect(tip).toContainText('点这里上传头像照片');await expect(tip).toContainText('最多上传 1 个');await shot('2-upload');await fits(guest)
      await guest.locator('[data-guide="add-avatar"]').click()
      const rules=guest.getByRole('dialog',{name:'上传前请对照示范'})
      await expect(rules).toContainText('没有手、口罩、墨镜挡住脸');await guest.waitForTimeout(500);await shot('3-photo-dialog')
      const chooser=guest.waitForEvent('filechooser')
      await rules.getByRole('button',{name:'我知道了，去选照片'}).click()
      await (await chooser).setFiles({name:'头像.png',mimeType:'image/png',buffer:pixel})
      await expect(guest.locator('.customer-avatar-row')).toHaveCount(1)
      await expect(guest.locator('summary',{hasText:'查看拍照要求'})).toBeVisible()

      await expect(tip).toContainText('给这个头像挑贴纸');await shot('4-pick')
      await guest.getByRole('button',{name:'选择模板和贴纸'}).click()
      const picker=guest.getByRole('dialog',{name:'选择模板和贴纸'})
      await expect(tip).toContainText('一张一张挑');await shot('5-picker-tabs');await tip.getByRole('button',{name:'我知道了'}).click()
      await expect(tip).toContainText('点 + 选这张');await shot('6-picker-plus')
      // The tip points at the first available + button; anything outside the highlight is blocked.
      await picker.locator('[data-guide="picker-plus"]:not(:disabled)').first().click()
      await expect(tip).toContainText('还能选几张');await tip.getByRole('button',{name:'不再提示'}).click()
      await expect(tip).toContainText('应用选择');await shot('7-picker-apply')
      await picker.getByRole('button',{name:'应用选择'}).click()

      await expect(tip).toContainText('点这里开始制作');await shot('8-start')
      await guest.getByRole('button',{name:'核对并开始生成'}).click()
      const check=guest.getByRole('dialog',{name:'生成前核对'})
      await expect(check.locator('.guide-warning')).toContainText('不能再改');await guest.waitForTimeout(500);await shot('9-preflight')
      await check.getByRole('button',{name:'确认开始生成'}).click()

      await expect(tip).toContainText('挑出要印刷的',{timeout:60000});await shot('10-select');await tip.getByRole('button',{name:'我知道了'}).click()
      await expect(tip).toContainText('要正好选满 1 张');await tip.getByRole('button',{name:'我知道了'}).click()
      await expect(tip).toContainText('看大图');await tip.getByRole('button',{name:'我知道了'}).click()
      await expect(tip).toContainText('整单一共能重试 1 次');await tip.getByRole('button',{name:'我知道了'}).click()
      await guest.getByLabel('选择成品 1').check()
      await expect(tip).toContainText('点这里提交印刷');await shot('11-submit');await fits(guest)
      await guest.getByRole('button',{name:'确认成品并提交'}).click()
      const submit=guest.getByRole('dialog',{name:'确认最终成品'})
      await expect(submit.locator('.guide-warning')).toContainText('不能再改，也不能再重试')
      await submit.getByRole('button',{name:'确认提交',exact:true}).click()
      await expect(guest.getByRole('heading',{name:'已提交印刷'})).toBeVisible()
      await expect(tip).toHaveCount(0)

      // Only walkthrough flags are stored, never order data; 不再提示 survives, 我知道了 does not.
      const stored=await guest.evaluate(()=>Object.fromEntries(Object.keys(localStorage).map(key=>[key,localStorage.getItem(key)])))
      expect(stored).toEqual({'guest-guide:force':'1','guest-guide:picker-remaining':'off'})
      await guest.getByRole('button',{name:'操作指引'}).click()
      expect(await guest.evaluate(()=>Object.keys(localStorage))).toEqual(['guest-guide:force'])
      expect(errors).toEqual([])
    }finally{await context.close()}
  })
}
