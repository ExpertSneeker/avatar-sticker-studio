import {expect,it} from 'vitest'
import {searchMatcher} from '../src/lib/search'
import {selectedImageCount} from '../src/lib/templates'

it('matches all whitespace-separated terms independently of order, case and full-width spaces',()=>{
  for(const query of ['A1 13','  a1   13  ','13 A1','Ａ１　１３','A1-13',''])expect(searchMatcher(query)('通用 A1-13')).toBe(true)
  expect(searchMatcher('A1 13 动物')('动物 A1-13')).toBe(true)
  expect(searchMatcher('A1 13 动物')('通用 A1-13')).toBe(false)
  expect(searchMatcher('A1 14')('A1-13')).toBe(false)
})
it('counts actual selected template images rather than twelve per set',()=>{
  const sets=[{id:'one',images:[{}]},{id:'many',images:Array(13).fill({})}]
  expect(selectedImageCount(sets,['one','many'])).toBe(14)
  expect(selectedImageCount(sets,['one','one','missing'])).toBe(1)
})
