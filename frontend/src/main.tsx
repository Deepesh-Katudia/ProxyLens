import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { LabelPage } from './label/LabelPage.tsx'

// Two pages so far; path-based routing keeps us free of a router dependency.
const Page = window.location.pathname.startsWith('/label') ? LabelPage : App

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <Page />
  </StrictMode>,
)
