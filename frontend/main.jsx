import React from 'react'
import ReactDOM from 'react-dom/client'
import MysteriumDashboard from './Dashboard'
import { ErrorBoundary } from './Dashboard'
import './index.css'

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <ErrorBoundary>
      <MysteriumDashboard />
    </ErrorBoundary>
  </React.StrictMode>,
)
