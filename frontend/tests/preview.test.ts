import { expect, test } from 'vitest'
import { previewUrl } from '../src/lib/preview'

test('display variants only change local asset URLs, preserving originals for downloads',()=>{
  const original='/api/assets/'+'a'.repeat(32)
  expect(previewUrl(original)).toBe(original+'/preview?size=320')
  expect(previewUrl(original,1280)).toBe(original+'/preview?size=1280')
  expect(previewUrl('blob:local')).toBe('blob:local')
  expect(previewUrl('https://outside.example/image.png')).toBe('https://outside.example/image.png')
  expect(previewUrl(undefined)).toBeUndefined()
})
