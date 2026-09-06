import { test, expect } from '@playwright/test'

test('local resize preserves portrait geometry, PNG alpha and filenames before upload', async ({page})=>{
  await page.goto('/')
  const result=await page.evaluate(async()=>{
    const modulePath='/src/lib/image.ts'
    const {prepareUploadImage}=await import(modulePath)
    const canvas=document.createElement('canvas');canvas.width=2048;canvas.height=3072
    const context=canvas.getContext('2d')!
    context.fillStyle='rgba(220,80,40,0.5)';context.fillRect(512,512,1024,1024)
    context.fillStyle='#238844';context.fillRect(512,2048,1024,512)
    const input=new File([await new Promise<Blob>(r=>canvas.toBlob(b=>r(b!),'image/png'))],'客户头像.png',{type:'image/png'})
    const output=await prepareUploadImage(input)
    const bitmap=await createImageBitmap(output)
    const check=document.createElement('canvas');check.width=bitmap.width;check.height=bitmap.height
    const ctx=check.getContext('2d')!;ctx.drawImage(bitmap,0,0)
    return {name:output.name,type:output.type,width:bitmap.width,height:bitmap.height,alpha:[ctx.getImageData(0,0,1,1).data[3],ctx.getImageData(300,300,1,1).data[3],ctx.getImageData(300,1100,1,1).data[3]]}
  })
  expect(result).toEqual({name:'客户头像.png',type:'image/png',width:1024,height:1536,alpha:[0,128,255]})
})

test('JPEG compression respects EXIF orientation and reduces bytes; small images stay unchanged',async({page})=>{
  await page.goto('/')
  const result=await page.evaluate(async()=>{
    const modulePath='/src/lib/image.ts'
    const {prepareUploadImage}=await import(modulePath)
    const canvas=document.createElement('canvas');canvas.width=2048;canvas.height=3072
    const ctx=canvas.getContext('2d')!,pixels=ctx.createImageData(canvas.width,canvas.height)
    let seed=42
    for(let i=0;i<pixels.data.length;i+=4){seed=(seed*1664525+1013904223)>>>0;pixels.data[i]=seed>>>24;pixels.data[i+1]=(seed>>>16)&255;pixels.data[i+2]=(seed>>>8)&255;pixels.data[i+3]=255}
    ctx.putImageData(pixels,0,0)
    const jpeg=await new Promise<Blob>(r=>canvas.toBlob(b=>r(b!),'image/jpeg',1))
    // Minimal EXIF orientation=6: encoded portrait is displayed rotated clockwise.
    const exif=new Uint8Array([255,225,0,34,69,120,105,102,0,0,73,73,42,0,8,0,0,0,1,0,18,1,3,0,1,0,0,0,6,0,0,0,0,0,0,0])
    const input=new File([jpeg.slice(0,2),exif,jpeg.slice(2)],'相机照片.jpg',{type:'image/jpeg'})
    const output=await prepareUploadImage(input),bitmap=await createImageBitmap(output)
    canvas.width=512;canvas.height=768
    const small=new File([await new Promise<Blob>(r=>canvas.toBlob(b=>r(b!),'image/webp'))],'小头像.webp',{type:'image/webp'})
    const preserved=await prepareUploadImage(small)
    const digest=async(file:File)=>Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',await file.arrayBuffer()))).join(',')
    return {width:bitmap.width,height:bitmap.height,name:output.name,type:output.type,ratio:output.size/input.size,smallUnchanged:await digest(small)===await digest(preserved)}
  })
  expect(result.width).toBe(1536);expect(result.height).toBe(1024)
  expect(result.name).toBe('相机照片.jpg');expect(result.type).toBe('image/jpeg')
  expect(result.ratio).toBeLessThan(0.5);expect(result.smallUnchanged).toBe(true)
})

test('cancelling local compression sends no upload request; invalid images fail locally',async({page})=>{
  await page.goto('/')
  const writes:string[]=[]
  page.on('request',request=>{if(request.method()!=='GET')writes.push(request.url())})
  const result=await page.evaluate(async()=>{
    const imagePath='/src/lib/image.ts',uploadPath='/src/lib/upload.ts'
    const {prepareUploadImage}=await import(imagePath),{uploadFile}=await import(uploadPath)
    const canvas=document.createElement('canvas');canvas.width=2048;canvas.height=2048
    const blob=await new Promise<Blob>(r=>canvas.toBlob(b=>r(b!),'image/png'))
    const controller=new AbortController(),native=HTMLCanvasElement.prototype.toBlob
    HTMLCanvasElement.prototype.toBlob=function(callback,type,quality){native.call(this,blob=>{controller.abort();callback(blob)},type,quality)}
    let aborted=false,invalid=false
    try{await uploadFile(new File([blob],'头像.png',{type:'image/png'}),()=>{},controller.signal)}catch(e){aborted=(e as Error).name==='AbortError'}
    finally{HTMLCanvasElement.prototype.toBlob=native}
    try{await prepareUploadImage(new File(['not an image'],'错误.png',{type:'image/png'}))}catch{invalid=true}
    return {aborted,invalid}
  })
  expect(result).toEqual({aborted:true,invalid:true});expect(writes).toEqual([])
})
