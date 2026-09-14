import { useEffect, useState } from 'react'
import { BookOpen, Search } from 'lucide-react'
import { api } from '../lib/api'
import { Spinner } from '../components/UI'
import './StaffGuide.css'

type Block = { type: 'paragraph'; text: string } | { type: 'list' | 'steps'; items: string[] } | { type: 'table'; headers: string[]; rows: string[][] }
interface Section { id: string; title: string; summary: string; blocks: Block[] }
interface Guide { title: string; version: string; updated_at: string; summary: string; sections: Section[] }

function GuideBlock({ block }: { block: Block }) {
  if (block.type === 'paragraph') return <p>{block.text}</p>
  if (block.type === 'table') return <div className="guide-table-scroll" tabIndex={0} role="region" aria-label="说明表格"><table><thead><tr>{block.headers.map((header, index) => <th key={index} scope="col">{header}</th>)}</tr></thead><tbody>{block.rows.map((row, index) => <tr key={index}>{row.map((cell, i) => <td key={i}>{cell}</td>)}</tr>)}</tbody></table></div>
  const List = block.type === 'steps' ? 'ol' : 'ul'
  return <List>{block.items.map((text, index) => <li key={index}>{text}</li>)}</List>
}

export default function StaffGuide() {
  const [guide, setGuide] = useState<Guide | null>(null)
  const [query, setQuery] = useState(''), [error, setError] = useState(''), [attempt, setAttempt] = useState(0)
  useEffect(() => {
    const controller = new AbortController()
    setGuide(null); setError('')
    void api<Guide>('/staff-guide', { signal: controller.signal }).then(value => {
      if (!controller.signal.aborted) setGuide(value)
    }).catch(e => { if (!controller.signal.aborted) setError(e.message) })
    return () => controller.abort()
  }, [attempt])
  if (error) return <div className="error-banner" role="alert">{error}<button className="button" onClick={() => setAttempt(value => value + 1)}>重新读取说明</button></div>
  if (!guide) return <div className="startup"><Spinner/>正在读取使用说明</div>
  const words = query.trim().toLocaleLowerCase().split(/\s+/).filter(Boolean)
  const sections = guide.sections.filter(section => words.every(word => JSON.stringify(section).toLocaleLowerCase().includes(word)))
  return <div className="staff-guide">
    <div className="page-heading"><div><h1><BookOpen size={26}/>{guide.title}</h1><p>{guide.summary}</p></div><span className="hint">更新于 {guide.updated_at} · v{guide.version}</span></div>
    <div className="guide-search"><Search size={18}/><input type="search" aria-label="搜索使用说明" placeholder="搜索开户、重做、打印、店铺接入…" value={query} onChange={e => setQuery(e.target.value)}/><span role="status">{sections.length} 个章节</span></div>
    <div className="guide-layout">
      <nav className="guide-toc" aria-label="说明目录">{sections.map(section => <a key={section.id} href={'#guide-' + section.id}>{section.title}</a>)}</nav>
      <div className="guide-sections">{sections.length ? sections.map(section => <section className="guide-section" key={section.id} id={'guide-' + section.id} aria-labelledby={'guide-title-' + section.id}><h2 id={'guide-title-' + section.id}>{section.title}</h2><p className="guide-summary">{section.summary}</p>{section.blocks.map((block, index) => <GuideBlock key={index} block={block}/>)}</section>) : <div className="guide-empty"><h2>没有找到相关说明</h2><p>换一个关键词，或清空搜索查看全部章节。</p><button className="button" onClick={() => setQuery('')}>查看全部说明</button></div>}</div>
    </div>
  </div>
}
