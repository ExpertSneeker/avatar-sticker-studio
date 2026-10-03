const filingUrl = 'https://beian.miit.gov.cn/'

export function IcpFiling() {
  return <div className="icp-filing">
    <a href={filingUrl} target="_blank" rel="noopener noreferrer">鲁ICP备20019500号</a>
    <a className="icp-query" href={filingUrl} target="_blank" rel="noopener noreferrer">工信部备案管理系统</a>
  </div>
}
