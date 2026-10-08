import { expect, type Page, type APIRequestContext } from '@playwright/test'
import { createHash, randomUUID } from 'node:crypto'
import { mkdirSync, readFileSync } from 'node:fs'
export const pixel=readFileSync(new URL('./fixtures/portrait.png',import.meta.url))
export async function staffLogin(request:APIRequestContext){
  const status=await(await request.get('/api/auth/status')).json()
  const response=await request.post(status.needs_setup?'/api/auth/setup':'/api/auth/login',{data:{username:'testadmin',password:'local-test-password',...(status.needs_setup?{display_name:'联调管理员'}:{})}})
  expect(response.ok(),await response.text()).toBeTruthy()
  mkdirSync('/tmp/avatar-studio-fal-qa',{recursive:true})
  return response.json()
}
export async function uploadAvatar(request:APIRequestContext,name='头像.png'){
  const init=await request.post('/api/uploads/init',{data:{filename:name,size:pixel.length,sha256:createHash('sha256').update(pixel).digest('hex')}})
  expect(init.ok(),await init.text()).toBeTruthy();const upload=await init.json()
  if(!upload.complete){expect((await request.put('/api/uploads/'+upload.id,{data:pixel,headers:{'Upload-Offset':String(upload.offset)}})).ok()).toBeTruthy()}
  expect((await request.post('/api/uploads/'+upload.id+'/complete')).ok()).toBeTruthy()
  return upload.id
}
export async function createCustomer(request:APIRequestContext,options:Record<string,unknown>={}){
  const response=await request.post('/api/customer-orders',{data:{platform:'pdd',order_number:'QA-'+randomUUID().slice(0,10),generation_limit:2,final_count:1,rerun_limit:1,notes:'打印验收',client_token:randomUUID(),...options}})
  expect(response.ok(),await response.text()).toBeTruthy();return response.json()
}
export async function mutate(request:APIRequestContext,order:any,path:string,data:Record<string,unknown>={}){
  const response=await request.post(`/api/customer-orders/${order.id}/${path}`,{data:{client_token:randomUUID(),expected_version:order.version,...data}})
  expect(response.ok(),await response.text()).toBeTruthy();return response.json()
}
async function currentCustomer(request:APIRequestContext,id:string){
  const response=await request.get('/api/customer-orders/'+id)
  expect(response.ok(),await response.text()).toBeTruthy()
  return response.json()
}
export async function generateCustomer(request:APIRequestContext,order:{id:string},avatars:{upload_id:string;template_ids:string[];sticker_ids:string[]}[]){
  let current=await mutate(request,await currentCustomer(request,order.id),'generate',{avatars})
  await expect.poll(async()=>{
    current=await currentCustomer(request,order.id)
    return current.slots.length>0&&current.slots.every((slot:any)=>!!slot.selected_version_id)
  },{timeout:60000}).toBe(true)
  return current
}
export async function submitCustomer(request:APIRequestContext,order:{id:string},slotIds?:string[]){
  let current=await currentCustomer(request,order.id)
  current=await mutate(request,current,'submit',{slot_ids:slotIds||current.slots.map((slot:any)=>slot.id)})
  await expect.poll(async()=>{current=await currentCustomer(request,order.id);return current.delivery_ready},{timeout:60000}).toBe(true)
  return current
}
export async function completedCustomer(request:APIRequestContext,stickerId:string,options:Record<string,unknown>={}){
  const order=await createCustomer(request,options)
  const generated=await generateCustomer(request,order,[{upload_id:await uploadAvatar(request),template_ids:[],sticker_ids:[stickerId]}])
  return submitCustomer(request,generated)
}
export async function installDirectoryPicker(page:Page,name='manual-print-output'){
  await page.addInitScript(name=>{
    const state=window as any;state.pickerCalls=0;state.pickerCancel=false;state.pickerName=name
    window.showDirectoryPicker=async()=>{state.pickerCalls++;if(state.pickerCancel)throw new DOMException('Cancelled','AbortError');return(await navigator.storage.getDirectory()).getDirectoryHandle(state.pickerName,{create:true})}
  },name)
}
