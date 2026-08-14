import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
// Imports index.css (as a cascade layer) plus the Tailwind utilities.
import './styles.css'
import App from './App.tsx'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
