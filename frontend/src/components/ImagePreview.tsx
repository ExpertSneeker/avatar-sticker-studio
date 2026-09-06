import { useState } from 'react'
import { previewUrl } from '../lib/preview'

/** List thumbnails stay compressed; selected viewers can default to original pixels. */
export function ImagePreview({src,alt,className,defaultOriginal=false}:{src:string;alt:string;className?:string;defaultOriginal?:boolean}) {
  const [originalSource,setOriginalSource]=useState<{src:string;original:boolean}|null>(null)
  const original=originalSource?.src===src?originalSource.original:defaultOriginal
  return <><div className={className}><img src={original?src:previewUrl(src,1280)} alt={alt} decoding="async"/></div><p className="hint"><button className="text-button" onClick={()=>setOriginalSource({src,original:!original})}>{original?'返回压缩预览':'查看原图'}</button><span> · {original?'正在显示原始文件':'压缩预览'}</span></p></>
}
