export function selectedImageCount(templates: readonly {id: string; images: readonly unknown[]}[], ids: readonly string[]): number {
  const selected = new Set(ids)
  return templates.reduce((total, template) => total + (selected.has(template.id) ? template.images.length : 0), 0)
}

export function selectionSummary(templates: readonly import('./types').TemplateSet[], templateIds: readonly string[], stickers: readonly import('./types').Sticker[], stickerIds: readonly string[] = []) {
  const entries: {id:string;revision:number;code:string;url:string;source:string}[]=[]
  for(const id of templateIds){const t=templates.find(t=>t.id===id);if(t)for(const image of t.images)entries.push({id:image.sticker_id||image.id,revision:image.revision??t.revision,code:image.code||t.code,url:image.url,source:t.name})}
  for(const id of stickerIds){const s=stickers.find(s=>s.id===id);if(s)entries.push({id:s.id,revision:s.revision,code:s.code,url:s.image.url,source:'单张贴纸'})}
  return {entries,exportCount:entries.length,generationCount:new Set(entries.map(e=>JSON.stringify([e.id,e.revision]))).size}
}
