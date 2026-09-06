import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, test } from 'vitest'
import { Templates } from '../src/pages/Templates'
import { TemplateChooser } from '../src/components/UI'
import type { TemplateSet } from '../src/lib/types'

const base={code:'B001',category:'boy',active:true,revision:1,images:[]}
const publicSet={...base,id:'public',name:'公共男孩',scope:'public' as const,owner:null,editable:false}
const personalSet={...base,id:'personal',name:'个人动物',category:'animal',scope:'personal' as const,owner:'me',editable:true}
const inactiveSet={...personalSet,id:'inactive',name:'未上架通用',category:'general',active:false}
const noop=()=>{}

describe('template permissions and availability',()=>{
  test('members can create sets and manage their personal active and inactive sets',()=>{
    const html=renderToStaticMarkup(<Templates templates={[publicSet,personalSet,inactiveSet]} admin={false} onRefresh={noop}/> )
    expect(html).toContain('新建套装')
    expect(html.match(/编辑<\/button>/g)).toHaveLength(2)
    expect(html).toContain('未上架通用')
    expect(html).toContain('aria-label="模板归属"')
    expect(html).toContain('动物')
    expect(html).toContain('通用')
  })

  test('explicit editable false overrides the admin fallback',()=>{
    const html=renderToStaticMarkup(<Templates templates={[publicSet]} admin={true} onRefresh={noop}/> )
    expect(html).not.toContain('编辑</button>')
    expect(html).not.toContain('下架</button>')
  })

  test('legacy records only show management actions for admins',()=>{
    const legacy={...base,id:'legacy',name:'旧模板'} as TemplateSet
    const member=renderToStaticMarkup(<Templates templates={[legacy]} admin={false} onRefresh={noop}/> )
    const admin=renderToStaticMarkup(<Templates templates={[legacy]} admin={true} onRefresh={noop}/> )
    expect(member).not.toContain('编辑</button>')
    expect(admin).toContain('编辑</button>')
  })

  test('picker includes active public and personal templates, excluding inactive sets',()=>{
    const html=renderToStaticMarkup(<TemplateChooser templates={[publicSet,personalSet,inactiveSet]} value={['public','personal']} onChange={noop}/> )
    expect(html).toContain('公共男孩')
    expect(html).toContain('个人动物')
    expect(html).not.toContain('未上架通用')
    expect(html.match(/template-option selected/g)).toHaveLength(2)
    expect(html).toContain('value="animal"')
    expect(html).toContain('value="general"')
    expect(html).toContain('aria-label="筛选模板归属"')
  })
})
