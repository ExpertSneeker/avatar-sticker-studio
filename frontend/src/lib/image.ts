/** Prepare upload bytes entirely in the browser; never changes the source file on disk. */
export async function prepareUploadImage(file:File, signal?:AbortSignal):Promise<File> {
  signal?.throwIfAborted()
  const header=new Uint8Array(await file.slice(0,12).arrayBuffer())
  const type=header[0]===0xff&&header[1]===0xd8&&header[2]===0xff?'image/jpeg'
    :[137,80,78,71,13,10,26,10].every((byte,i)=>header[i]===byte)?'image/png'
    :String.fromCharCode(...header.slice(0,4))==='RIFF'&&String.fromCharCode(...header.slice(8,12))==='WEBP'?'image/webp':null
  if(!type)throw new Error(file.name+'：请使用有效的 JPG、PNG 或 WebP 图片')
  signal?.throwIfAborted()
  let bitmap:ImageBitmap
  try{bitmap=await createImageBitmap(file,{imageOrientation:'from-image'})}
  catch{signal?.throwIfAborted();throw new Error(file.name+'：无法读取图片，请重新选择')}
  let canvas:HTMLCanvasElement|undefined
  try {
    signal?.throwIfAborted()
    const shortEdge=Math.min(bitmap.width,bitmap.height)
    if(shortEdge<=1024)return file
    const scale=1024/shortEdge
    canvas=document.createElement('canvas')
    canvas.width=Math.round(bitmap.width*scale)
    canvas.height=Math.round(bitmap.height*scale)
    const context=canvas.getContext('2d')
    if(!context)throw new Error('浏览器无法创建图片画布')
    context.imageSmoothingEnabled=true
    context.imageSmoothingQuality='high'
    context.drawImage(bitmap,0,0,canvas.width,canvas.height)
    const blob=await new Promise<Blob>((resolve,reject)=>{
      canvas!.toBlob(value=>value?.size?resolve(value):reject(new Error('图片编码失败')),type,0.88)
    })
    signal?.throwIfAborted()
    const name=blob.type===type?file.name:file.name.replace(/\.[^.]+$/,'')+'.png'
    return new File([blob],name,{type:blob.type,lastModified:file.lastModified})
  } catch(error) {
    signal?.throwIfAborted()
    throw new Error(file.name+'：本地压缩失败，'+(error as Error).message)
  } finally {
    bitmap.close()
    if(canvas){canvas.width=0;canvas.height=0}
  }
}
