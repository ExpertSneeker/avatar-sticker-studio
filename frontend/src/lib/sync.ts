export function safeFilename(value:string):boolean {
  return !!value.trim() && !/[\\/:*?"<>|\x00-\x1f\x7f]/.test(value) && !/[. ]$/.test(value) && value!=='.' && value!=='..' && !/^(con|prn|aux|nul|com[1-9]|lpt[1-9])(\.|$)/i.test(value)
}
export function planSync(files:{path:string;sha256:string}[],local:Record<string,string>,owned:Record<string,string>,repairModified=false) {
  const download:string[]=[], conflicts:string[]=[], remove:string[]=[]
  const wanted=new Set(files.map(f=>f.path))
  for (const file of files) {
    if (!safeFilename(file.path)) {conflicts.push(file.path);continue}
    if (local[file.path] && !Object.hasOwn(owned,file.path)) {conflicts.push(file.path);continue}
    if (local[file.path]===file.sha256) continue
    if (local[file.path] && local[file.path]!==owned[file.path] && !repairModified) conflicts.push(file.path)
    else download.push(file.path)
  }
  for (const [path,hash] of Object.entries(owned)) if(!wanted.has(path)&&local[path]===hash) remove.push(path)
  return {download,conflicts,remove}
}
