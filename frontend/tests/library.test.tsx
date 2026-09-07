import { describe, expect, test } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { selectionSummary } from '../src/lib/templates'
import { Stickers } from '../src/pages/Stickers'
import type { Sticker, TemplateSet } from '../src/lib/types'
const a:Sticker={id:'a',code:'S1',name:'One',category:'boy',active:true,revision:2,image:{id:'im',url:'/a'},editable:false}
const b={...a,id:'b',code:'S2'}
const templates=[{id:'t1',images:[{...a.image,sticker_id:'a',code:'S1',revision:2,position:1}]},{id:'t2',images:[{...a.image,sticker_id:'a',code:'S1',revision:2,position:1}]}] as TemplateSet[]
describe('public sticker selection',()=>{
 test('overlap generates once but exports every occurrence',()=>{const result=selectionSummary(templates,['t1','t2'],[a,b],['a','b']);expect(result.generationCount).toBe(2);expect(result.exportCount).toBe(4);expect(result.entries.map(e=>e.code)).toEqual(['S1','S1','S1','S2'])})
 test('revision changes are distinct generation work',()=>{const result=selectionSummary([{...templates[0],images:[{...templates[0].images[0],revision:1}]}],['t1'],[a],['a']);expect(result.generationCount).toBe(2)})
 test('legacy draft sticker selection defaults empty',()=>{expect(selectionSummary(templates,['t1'],[a]).exportCount).toBe(1)})
 test('viewers cannot create or edit stickers',()=>{const html=renderToStaticMarkup(<Stickers stickers={[a]} canEdit={false} onRefresh={()=>{}}/>);expect(html).toContain('预览');expect(html).not.toContain('批量上传');expect(html).not.toContain('>编辑<')})
 test('permission enables creation but explicit noneditable assets remain protected',()=>{const html=renderToStaticMarkup(<Stickers stickers={[a]} canEdit onRefresh={()=>{}}/>);expect(html).toContain('批量上传');expect(html).not.toContain('>编辑<')})
})

test('editors can delete stickers while viewers cannot',()=>{
 const editor=renderToStaticMarkup(<Stickers stickers={[{...a,editable:true}]} canEdit onRefresh={()=>{}}/>)
 expect(editor).toContain('删除贴纸 S1')
 const viewer=renderToStaticMarkup(<Stickers stickers={[{...a,editable:true}]} canEdit={false} onRefresh={()=>{}}/>)
 expect(viewer).not.toContain('删除贴纸 S1')
})

test('sticker library exposes category labels, view choices and editor bulk selection',()=>{
 const html=renderToStaticMarkup(<Stickers stickers={[{...a,editable:true}]} canEdit onRefresh={()=>{}}/>)
 expect(html).toContain('管理分类')
 expect(html).toContain('列表视图')
 expect(html).toContain('选择贴纸 S1')
 const viewer=renderToStaticMarkup(<Stickers stickers={[a]} canEdit={false} onRefresh={()=>{}}/>)
 expect(viewer).not.toContain('管理分类')
 expect(viewer).not.toContain('全选筛选结果')
})

test('sticker cards use labelled icon actions without status controls',()=>{
 const html=renderToStaticMarkup(<Stickers stickers={[{...a,editable:true}]} canEdit onRefresh={()=>{}}/>)
 expect(html).toContain('aria-label="编辑贴纸 S1"')
 expect(html).not.toContain('>停用<')
 expect(html).not.toContain('已启用')
 expect(html).not.toContain('>编辑</button>')
})
