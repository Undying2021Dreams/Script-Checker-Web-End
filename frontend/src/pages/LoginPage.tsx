import { useMsal } from '@azure/msal-react'
import { useState } from 'react'

import { LogoMark } from '@/components/Logo'
import { Button } from '@/components/ui/button'
import { Pending } from '@/components/ui/feedback'
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
    <div className="flex min-h-svh flex-col items-center justify-center gap-6 px-4">
      {/* The one screen with room for the mark at a size where the
          circuit detail actually reads. */}
      <div className="flex flex-col items-center gap-3 text-center">
        <LogoMark className="size-16" />
        <div>
          <p className="text-2xl font-semibold tracking-tight">
            <span className="text-primary">Auto</span>
            <span className="text-success">Check</span>
          </p>
          <p className="mt-1 text-sm text-muted-foreground">Automating the boring stuff</p>
        </div>
      </div>

      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle>Sign in</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <Button className="w-full" onClick={handleLogin} disabled={loading}>
            {loading ? <Pending>Signing in…</Pending> : 'Sign in with Microsoft'}
          </Button>
          <p className="text-center text-xs text-muted-foreground">
            Use your university Microsoft account.
          </p>
          {error && <p className="text-sm text-destructive break-words">{error}</p>}
        </CardContent>
      </Card>
    </div>
  )
}
