import { MsalProvider } from '@azure/msal-react'
import { QueryClientProvider } from '@tanstack/react-query'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'

import App from './App.tsx'
import './index.css'
import { msalInstance } from './lib/msal'
import { queryClient } from './lib/queryClient'

const url = window.location.href
const hasAuthResponse = /[?#&](code|error)=/.test(url) && /[?#&]state=/.test(url)

/*
 * Our redirectUri is "/", so MSAL's login popup lands back on this same
 * entry point to deliver the auth response. In MSAL v5 that page must
 * actively publish the response to the opener over a BroadcastChannel —
 * rendering the app there instead would both show a login page inside the
 * popup (which MSAL rejects as block_nested_popups when clicked) and never
 * deliver the response, timing the sign-in out. broadcastResponseToMainFrame
 * handles it: it strips the response from the URL, posts it to the opener,
 * and closes the popup.
 */
if (hasAuthResponse) {
  const { broadcastResponseToMainFrame } = await import('@azure/msal-browser/redirect-bridge')
  await broadcastResponseToMainFrame()
} else {
  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <MsalProvider instance={msalInstance}>
        <QueryClientProvider client={queryClient}>
          <BrowserRouter>
            <App />
          </BrowserRouter>
        </QueryClientProvider>
      </MsalProvider>
    </StrictMode>,
  )
}
