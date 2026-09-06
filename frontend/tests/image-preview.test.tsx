import {renderToStaticMarkup} from 'react-dom/server'
import {expect,test} from 'vitest'
import {ImagePreview} from '../src/components/ImagePreview'
test('order previews can open original pixels directly',()=>{
 const src='/api/assets/'+'a'.repeat(32)
 const html=renderToStaticMarkup(<ImagePreview src={src} alt="任务预览" defaultOriginal/> )
 expect(html).toContain('src="'+src+'"')
 expect(html).not.toContain('/preview?')
})
