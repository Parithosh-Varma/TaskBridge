import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import App from './App.jsx'
import './styles/global.css'

// IMPORTANT: vite's base './' is for asset URLs only — react-router's
// basename must be an absolute path or the router silently matches nothing.
const basename = import.meta.env.BASE_URL === './' ? '/' : import.meta.env.BASE_URL

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <BrowserRouter basename={basename}>
      <App />
    </BrowserRouter>
  </React.StrictMode>,
)
