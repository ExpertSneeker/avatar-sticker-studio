import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, expectUser } from '../src/lib/api'
import { guestApi, isAdmin, moveSelection, OrderMutations, quantityIds, selectionCounts, selectionError, submissionError } from '../src/lib/customer-orders'
import type { CustomerLibrary, GuestOrder } from '../src/lib/customer-orders'
import { orderFolderName } from '../src/lib/delivery'
const library:CustomerLibrary={stickers:[{id:'a',code:'A',name:'A',category:'x',revision:1,preview_url:'/safe/a'},{id:'b',code:'B',name:'B',category:'x',revision:2,preview_url:'/safe/b'}],templates:[{id:'t',code:'T',name:'T',category:'x',sticker_ids:['a','b'],images:[]}]}
const order:GuestOrder={id:'o',order_number:'N',state:'review',version:2,generation_limit:6,final_count:2,rerun_limit:1,slots:[0,1].map(i=>({id:'s'+i,avatar_id:'u',sticker_code:'A',status:'completed',reruns_used:0,reruns_reserved:0,selected_version_id:'v'+i,pending_version_id:null,versions:[{id:'v'+i,preview_url:'/safe/'+i}]}))}
afterEach(()=>{vi.unstubAllGlobals();expectUser(null)})
describe('customer selection contract',()=>{
  it('retains repeated slots but deduplicates generation per avatar record and sticker revision',()=>{
    expect(selectionCounts([{upload_id:'u1',template_ids:['t','t'],sticker_ids:['a']},{upload_id:'u2',template_ids:[],sticker_ids:['a','a']}],library)).toEqual({avatar_count:2,selection_count:7,generation_count:3})
  })
  it('clamps repeated quantities, clears a selection and preserves other IDs',()=>{
    expect(quantityIds(['b','a','a'],'a',3)).toEqual(['b','a','a','a'])
    expect(quantityIds(['b','a'],'a',NaN)).toEqual(['b'])
    expect(quantityIds([],'a',900,3)).toHaveLength(3)
  })
  it('enforces avatar and repeated slot bounds before preflight',()=>{
    expect(selectionError(order,{avatar_count:3,selection_count:4,generation_count:4})).toContain('1 至 2')
    expect(selectionError(order,{avatar_count:1,selection_count:7,generation_count:1})).toContain('2 至 6')
    expect(selectionError(order,{avatar_count:1,selection_count:2,generation_count:1})).toBe('')
  })
  it('requires exact count, unique slots, completed versions and all pending choices resolved',()=>{
    expect(submissionError(order,['s1','s0'])).toBe('')
    expect(submissionError(order,['s0','s0'])).toContain('准确')
    expect(submissionError(order,['s0','missing'])).toContain('尚未生成')
    expect(submissionError({...order,slots:order.slots!.map((s,i)=>i?{...s,pending_version_id:'new'}:s)},['s0','s1'])).toContain('保留版本')
    expect(submissionError({...order,slots:order.slots!.map((s,i)=>i?{...s,status:'unknown'}:s)},['s0','s1'])).toContain('待确认')
    expect(submissionError({...order,state:'submitted'},['s0','s1'])).toContain('不能提交')
  })
  it('preserves explicit print order when moving without corrupting edges',()=>{
    expect(moveSelection(['a','b','c'],2,-1)).toEqual(['a','c','b'])
    expect(moveSelection(['a','b'],0,-1)).toEqual(['a','b'])
  })
  it('recognizes organization and platform administrators',()=>{
    expect(isAdmin('org_admin')).toBe(true);expect(isAdmin('superadmin')).toBe(true);expect(isAdmin('staff')).toBe(false)
  })
})
describe('isolated guest requests and uncertain mutation retries',()=>{
  it('does not send staff identity or store guest content',async()=>{
    expectUser('staff-user')
    const fetcher=vi.fn().mockImplementation(async()=>Response.json(order));vi.stubGlobal('fetch',fetcher)
    await guestApi('/order')
    const [url,options]=fetcher.mock.calls[0]
    expect(url).toBe('/api/guest/order');expect(options.cache).toBe('no-store');expect(options.headers.has('X-Studio-User')).toBe(false)
  })
  it('reuses exact token, expected version and payload after a lost response',async()=>{
    const fetcher=vi.fn().mockRejectedValueOnce(new TypeError('network')).mockImplementation(async()=>Response.json(order));vi.stubGlobal('fetch',fetcher)
    const client=new OrderMutations()
    await expect(client.run('staff','/customer-orders/o','/generate',2,{avatars:[]})).rejects.toThrow('network')
    await expect(client.run('staff','/customer-orders/o','/generate',3,{avatars:[{upload_id:'other'}]})).rejects.toThrow('上一操作')
    await expect(client.run('staff','/customer-orders/another','/cancel',3)).rejects.toThrow('上一操作')
    expect(client.pendingPath).toBe('/generate')
    await client.retry()
    expect(client.pendingPath).toBe(null)
    expect(fetcher.mock.calls[1][0]).toBe('/api/customer-orders/o/generate')
    expect(fetcher.mock.calls[0][1].body).toBe(fetcher.mock.calls[1][1].body)
    await client.run('staff','/customer-orders/o','/generate',4,{avatars:[]})
    expect(JSON.parse(fetcher.mock.calls[2][1].body).client_token).not.toBe(JSON.parse(fetcher.mock.calls[0][1].body).client_token)
  })
  it('allows a fresh retry after an authoritative conflict',async()=>{
    const fetcher=vi.fn().mockResolvedValueOnce(Response.json({detail:'changed'},{status:409})).mockImplementation(async()=>Response.json(order));vi.stubGlobal('fetch',fetcher)
    const client=new OrderMutations()
    await expect(client.run('staff','/customer-orders/o','/submit',2,{slot_ids:['s0','s1']})).rejects.toBeInstanceOf(ApiError)
    await client.run('staff','/customer-orders/o','/submit',3,{slot_ids:['s1','s0']})
    expect(JSON.parse(fetcher.mock.calls[1][1].body).expected_version).toBe(3)
  })
})
it('sanitizes folder names without changing raw notes and caps UTF-8 length',()=>{
  const input={order_number:'订单',notes:'../坏:名称 / '+('头像😀'.repeat(200))}
  const result=orderFolderName(input)
  expect(result).not.toMatch(/[\\/:*?"<>|]/)
  expect(new TextEncoder().encode(result).length).toBeLessThanOrEqual(220)
  expect(input.notes).toContain('../坏:名称')
  expect(orderFolderName({order_number:'N',notes:''})).toBe('N')
})
