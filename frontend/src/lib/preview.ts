/** Display-only URL. Keep manifests, downloads and provider inputs on the original URL. */
export function previewUrl(url:string|undefined,size:320|1280=320):string|undefined {
  return url&&/^\/api\/assets\/[0-9a-f]{32}$/.test(url)?`${url}/preview?size=${size}`:url
}
