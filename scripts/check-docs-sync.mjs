import { execFileSync } from 'node:child_process'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const args = process.argv.slice(2)
if (args.length && (args.length !== 2 || args[0] !== '--base' || !args[1])) {
  console.error('用法：npm run check:docs -- --base <基础提交或分支>')
  process.exit(2)
}
const git = (...values) => execFileSync('git', values, { cwd: root, encoding: 'utf8' }).split('\0').filter(Boolean)
try {
  const ref = execFileSync('git', ['rev-parse', '--verify', '--end-of-options', (args[1] || 'HEAD') + '^{commit}'], { cwd: root, encoding: 'utf8' }).trim()
  const paths = new Set([...git('diff', '--name-only', '-z', ref, '--'), ...git('ls-files', '--others', '--exclude-standard', '-z')])
  const behaviorChanged = [...paths].some(file => /^(backend\/app\/|frontend\/src\/)/.test(file))
  if (behaviorChanged && !paths.has('backend/content/staff-guide.json')) {
    console.error('网站代码有修改，但后台使用说明未同步更新。请修改 backend/content/staff-guide.json 的相关章节、版本、日期与更新记录，再提交或测试。')
    process.exit(1)
  }
  console.log('后台使用说明同步检查通过。')
} catch {
  console.error('无法检查说明同步：请在有效 Git 项目中运行，并核对基础提交。')
  process.exit(2)
}
