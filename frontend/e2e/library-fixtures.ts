import {expect, type APIRequestContext, type Locator} from '@playwright/test'
export async function uploadStickers(request:APIRequestContext, files:{name:string;mimeType:string;buffer:Buffer}[]) {
 const form=new FormData()
 for(const file of files)form.append('files',new Blob([new Uint8Array(file.buffer)],{type:file.mimeType}),file.name)
 const response=await request.post('/api/stickers',{multipart:form});expect(response.ok(),await response.text()).toBeTruthy()
 return await response.json() as {id:string;code:string;image:{url:string}}[]
}
export async function chooseStickers(dialog:Locator,codes:string[]) {
 for(const code of codes){await dialog.getByLabel('搜索贴纸',{exact:true}).fill(code);await dialog.locator('.template-option').filter({hasText:code}).first().click()}
 await dialog.getByLabel('搜索贴纸',{exact:true}).fill('')
}
