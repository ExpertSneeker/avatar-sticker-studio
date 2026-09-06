import { describe, expect, it } from 'vitest'
import { planSync, safeFilename } from '../src/lib/sync'

describe('device reconciliation', () => {
  it('downloads missing and stale results but never overwrites unowned files', () => {
    const plan = planSync(
      [{ path: 'a.png', sha256: 'new' }, { path: 'b.png', sha256: 'b' }],
      { 'a.png': 'old', 'extra.png': 'x' },
      { 'a.png': 'old', 'obsolete.png': 'gone' },
    )
    expect(plan.download).toEqual(['a.png', 'b.png'])
    expect(plan.conflicts).toEqual([])
    expect(plan.remove).toEqual([])
  })
  it('refuses modified managed files and unowned collisions', () => {
    expect(planSync([{ path: 'a.png', sha256: 'new' }], { 'a.png': 'manual' }, { 'a.png': 'old' }).conflicts).toEqual(['a.png'])
    expect(planSync([{ path: 'a.png', sha256: 'new' }], { 'a.png': 'foreign' }, {}).conflicts).toEqual(['a.png'])
  })
  it('does not claim ownership of identical foreign files', () => {
    expect(planSync([{path:'a.png',sha256:'same'}], {'a.png':'same'}, {}).conflicts).toEqual(['a.png'])
  })
  it('removes obsolete files only when bytes still equal recorded owned version', () => {
    expect(planSync([], { 'a.png': 'old', 'b.png': 'manual' }, { 'a.png': 'old', 'b.png': 'old' }).remove).toEqual(['a.png'])
  })
  it('rejects filesystem traversal, reserved names and separators', () => {
    for (const bad of ['../a', '/tmp/a', 'a/b', 'a\\b', '..', 'CON', 'a:', 'a.']) expect(safeFilename(bad)).toBe(false)
    expect(safeFilename('小满_B001_1.png')).toBe(true)
  })
})
