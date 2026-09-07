export function selectedImageCount(templates: readonly {id: string; images: readonly unknown[]}[], ids: readonly string[]): number {
  const selected = new Set(ids)
  return templates.reduce((total, template) => total + (selected.has(template.id) ? template.images.length : 0), 0)
}
