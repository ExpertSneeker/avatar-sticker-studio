import { spawn } from 'node:child_process'
import { existsSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..')
process.chdir(root)
if(existsSync('.env'))process.loadEnvFile('.env')
const mode=process.argv[2]||'start',children=new Set()
let stopping=false
function stop(code=0){
  if(stopping)return
  stopping=true
  for(const child of children)child.kill('SIGTERM')
  const deadline=setTimeout(()=>process.exit(code),5000)
  deadline.unref()
  if(!children.size)process.exit(code)
}
process.on('SIGINT',()=>stop())
process.on('SIGTERM',()=>stop())
function run(command,args,env={}){
  return new Promise((resolve,reject)=>{
    const child=spawn(command,args,{cwd:root,stdio:'inherit',env:{...process.env,...env}})
    children.add(child)
    child.on('error',error=>{children.delete(child);reject(error)})
    child.on('exit',(code,signal)=>{
      children.delete(child)
      if(stopping){if(!children.size)process.exit(0);return}
      code===0?resolve():reject(new Error(`${command} exited (${code??signal})`))
    })
  })
}
const port=process.env.STUDIO_PORT||'8000'
if(!/^\d+$/.test(port)||Number(port)<1024||Number(port)>65535)throw new Error('STUDIO_PORT 必须为 1024–65535')
const server=()=>run('uv',['run','uvicorn','backend.app.main:app_factory','--factory','--host','127.0.0.1','--port',port,'--no-access-log'],{STUDIO_DATA_DIR:process.env.STUDIO_DATA_DIR||path.join(root,'.data')})
try{
  if(mode==='setup'){
    await run('uv',['sync','--python','3.12'])
    await run('npm',['ci','--prefix','frontend'])
  }else if(mode==='start'){
    await run('npm',['run','build','--prefix','frontend'])
    console.log(`\n头像贴纸工作台：http://127.0.0.1:${port}\n按 Ctrl+C 停止本机服务。\n`)
    await server()
  }else if(mode==='dev'){
    console.log('\n开发工作台：http://127.0.0.1:5173\n')
    await Promise.all([server(),run('npm',['run','dev','--prefix','frontend','--','--port','5173','--strictPort'],{STUDIO_API_PROXY:`http://127.0.0.1:${port}`})])
  }else throw new Error('可用命令：setup / start / dev')
}catch(error){console.error(error.message);stop(1)}
