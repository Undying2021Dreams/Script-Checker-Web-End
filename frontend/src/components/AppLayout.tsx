import { useMsal } from '@azure/msal-react'
import { Link, Outlet, useLocation } from 'react-router-dom'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { useMe } from '@/lib/queries'

const navItems = [
  { to: '/', label: 'My courses' },
  { to: '/search', label: 'Find a course' },
]

export function AppLayout() {
  const { instance } = useMsal()
  const { pathname } = useLocation()
  const { data: me } = useMe()

  return (
    <div className="min-h-svh">
      <header className="border-b">
        <div className="mx-auto flex max-w-5xl flex-wrap items-center gap-4 px-6 py-3">
          <Link to="/" className="font-semibold">
            Web-End
          </Link>

          <nav className="flex gap-1">
            {navItems.map((item) => (
              <Button
                key={item.to}
                variant={pathname === item.to ? 'secondary' : 'ghost'}
                size="sm"
                nativeButton={false}
                render={<Link to={item.to}>{item.label}</Link>}
              />
            ))}
          </nav>

          <div className="ml-auto flex items-center gap-3">
            {me && (
              <span className="flex items-center gap-2 text-sm text-muted-foreground">
                {me.display_name}
                <Badge variant="secondary">{me.role}</Badge>
              </span>
            )}
            <Button variant="outline" size="sm" onClick={() => instance.logoutPopup()}>
              Sign out
            </Button>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-5xl px-6 py-8">
        <Outlet />
      </main>
    </div>
  )
}
