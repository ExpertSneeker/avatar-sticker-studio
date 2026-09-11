import { lazy, StrictMode, Suspense } from 'react'
import { createRoot } from 'react-dom/client'
import './styles.css'

// Each entry is loaded independently. Customer browsers never load the staff shell.
const Entry=window.location.pathname.replace(/\/$/,'')==='/guest'?lazy(()=>import('./pages/Guest')):lazy(()=>import('./App'))
createRoot(document.getElementById('root')!).render(<StrictMode><Suspense fallback={<div className="startup" role="status">正在加载…</div>}><Entry/></Suspense></StrictMode>)
