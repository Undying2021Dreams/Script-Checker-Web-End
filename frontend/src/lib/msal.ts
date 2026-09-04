import { PublicClientApplication } from '@azure/msal-browser'
import type { Configuration } from '@azure/msal-browser'

// "common" = work/school accounts AND personal Microsoft accounts, matching
// the app registration's "Any Entra ID Tenant + Personal Microsoft accounts"
// setting. "organizations" would reject personal accounts.
const tenantId = import.meta.env.VITE_AZURE_TENANT_ID || 'common'

export const msalConfig: Configuration = {
  auth: {
    clientId: import.meta.env.VITE_AZURE_CLIENT_ID || '',
    authority: `https://login.microsoftonline.com/${tenantId}`,
    redirectUri: '/',
  },
  cache: {
    cacheLocation: 'sessionStorage',
  },
}

export const loginRequest = {
  scopes: [import.meta.env.VITE_AZURE_API_SCOPE || 'openid profile email'],
}

export const msalInstance = new PublicClientApplication(msalConfig)
