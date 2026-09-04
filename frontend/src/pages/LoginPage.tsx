import { useMsal } from '@azure/msal-react'
import { useState } from 'react'

import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { loginRequest } from '@/lib/msal'

export function LoginPage() {
  const { instance } = useMsal()
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const handleLogin = async () => {
    setError(null)
    setLoading(true)
    try {
      const result = await instance.loginPopup(loginRequest)
      instance.setActiveAccount(result.account)
    } catch (err) {
      console.error('Login failed:', err)
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex min-h-svh items-center justify-center">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle>Sign in</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <Button className="w-full" onClick={handleLogin} disabled={loading}>
            {loading ? 'Signing in…' : 'Sign in with Microsoft'}
          </Button>
          {error && <p className="text-sm text-destructive break-words">{error}</p>}
        </CardContent>
      </Card>
    </div>
  )
}
