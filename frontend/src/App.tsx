import { Shell } from './components/Shell'
import { LabelPage } from './label/LabelPage'
import { usePath } from './lib/navigation'
import { AboutPage } from './pages/AboutPage'
import { EvalPage } from './pages/EvalPage'
import { ReportPage } from './pages/report/ReportPage'
import { UploadPage } from './pages/upload/UploadPage'

function NotFound() {
  return <p className="text-ink/60">Page not found.</p>
}

export default function App() {
  const path = usePath()
  // The labelling tool has its own full-width layout.
  if (path.startsWith('/label')) return <LabelPage />

  const report = path.match(/^\/documents\/([a-f0-9]{24})$/)
  let page
  if (path === '/') page = <UploadPage />
  else if (report) page = <ReportPage key={report[1]} documentId={report[1]} />
  else if (path === '/eval') page = <EvalPage />
  else if (path === '/about') page = <AboutPage />
  else page = <NotFound />

  return <Shell path={path}>{page}</Shell>
}
