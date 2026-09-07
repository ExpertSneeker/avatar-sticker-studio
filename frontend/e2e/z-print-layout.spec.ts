import {test,expect} from '@playwright/test'
import {readFileSync} from 'node:fs'
import {createHash} from 'node:crypto'

test('printed files include centered order title and retain original results when repacked',async({page})=>{
  await page.request.post('/api/auth/login',{data:{username:'testadmin',password:'local-test-password'}})
  const sets=await(await page.request.get('/api/templates')).json()
  const template=sets.find((t:{active:boolean;available:boolean})=>t.active&&t.available!==false)
  expect(template).toBeTruthy()
  const pixel=readFileSync(new URL('./fixtures/portrait.png',import.meta.url))
  const uploaded=await(await page.request.post('/api/uploads/init',{data:{filename:'标题居中验收.png',size:pixel.length,sha256:createHash('sha256').update(pixel).digest('hex')}})).json()
  await page.request.put('/api/uploads/'+uploaded.id,{data:pixel,headers:{'Upload-Offset':'0'}})
  await page.request.post('/api/uploads/'+uploaded.id+'/complete')
  const response=await page.request.post('/api/orders',{data:{upload_id:uploaded.id,name:'标题居中验收',template_ids:[template.id],print_settings:{},client_token:'print-layout-acceptance'}})
  expect(response.ok()).toBeTruthy();const order=await response.json()
  await expect.poll(async()=> (await(await page.request.get('/api/orders/'+order.id)).json()).status,{timeout:60000}).toBe('completed')
  const before=await(await page.request.get('/api/orders/'+order.id)).json()
  await page.goto('/')
  const file=before.artifacts.find((a:{kind:string})=>a.kind==='print')
  const measured=await page.evaluate(async(url)=>{
    const image=await createImageBitmap(await(await fetch(url)).blob())
    const canvas=document.createElement('canvas');canvas.width=image.width;canvas.height=image.height
    const ctx=canvas.getContext('2d')!;ctx.drawImage(image,0,0)
    const {data}=ctx.getImageData(0,0,canvas.width,canvas.height)
    let left=canvas.width,right=0,top=canvas.height,bottom=0,title=0
    for(let y=0;y<canvas.height;y++)for(let x=0;x<canvas.width;x++){
      const i=(y*canvas.width+x)*4;if(!data[i+3])continue
      if(y<120&&data[i]===0&&data[i+1]===0&&data[i+2]===0){title++;continue}
      if(data[i]>100){left=Math.min(left,x);right=Math.max(right,x+1);top=Math.min(top,y);bottom=Math.max(bottom,y+1)}
    }
    return {width:canvas.width,height:canvas.height,left,right,top,bottom,title,corner:data[3]}
  },file.url)
  expect(measured.width).toBe(2480);expect(measured.height).toBe(3508)
  expect(measured.title).toBeGreaterThan(100);expect(measured.corner).toBe(0)
  expect(Math.abs(measured.left-(measured.width-measured.right))).toBeLessThanOrEqual(2)
  expect(Math.abs((measured.top-142)-(3508-118-measured.bottom))).toBeLessThanOrEqual(2)
  await page.getByRole('navigation').getByRole('button',{name:'任务中心',exact:true}).click()
  await page.locator('.task-main').filter({hasText:'标题居中验收'}).click()
  const detail=page.getByRole('dialog').first()
  await detail.getByRole('button',{name:'重新排版',exact:true}).click()
  await expect(page.getByText('每页顶部标注订单名',{exact:false})).toBeVisible()
  const repack=page.getByRole('dialog').last()
  await repack.getByRole('button',{name:'开始排版',exact:true}).click()
  await expect.poll(async()=> (await(await page.request.get('/api/orders/'+order.id)).json()).artifact_version).toBeGreaterThan(before.artifact_version)
  const after=await(await page.request.get('/api/orders/'+order.id)).json()
  expect(after.items.map((i:{result_url:string;attempt:number})=>[i.result_url,i.attempt])).toEqual(before.items.map((i:{result_url:string;attempt:number})=>[i.result_url,i.attempt]))
})
