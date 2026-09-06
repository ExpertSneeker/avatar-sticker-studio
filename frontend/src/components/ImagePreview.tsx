import { useState } from 'react'
import { previewUrl } from '../lib/preview'

/** Original pixels are fetched only after an explicit inspection request. */
export function ImagePreview({src,alt,className}:{src:string;alt:string;className?:string}) {
  const [originalSource,setOriginalSource]=useState<string|null>(null)
  const original=originalSource===src
  return <><div className={className}><img src={original?src:previewUrl(src,1280)} alt={alt} decoding="async"/></div><p className="hint"><button className="text-button" onClick={()=>setOriginalSource(original?null:src)}>{original?'返回压缩预览':'查看原图'}</button><span> · {original?'正在显示原始文件':'压缩预览，下载保留原图'}</span></p></>
}
