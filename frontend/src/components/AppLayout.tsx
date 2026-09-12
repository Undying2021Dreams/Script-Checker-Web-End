import { useMsal } from '@azure/msal-react'
import { Link, Outlet, useLocation } from 'react-router-dom'

import { Logo } from '@/components/Logo'
import { ThemeToggle } from '@/components/ThemeToggle'
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
    <div className="min-h-svh bg-background">
      {/* Sticky, so the way back out of a long review or editor screen is
          always on screen rather than a scroll away. */}
      <header className="sticky top-0 z-30 border-b bg-card/85 backdrop-blur">
        <div className="mx-auto flex max-w-5xl flex-wrap items-center gap-4 px-6 py-3">
          <Link to="/" aria-label="AutoCheck home">
            <Logo />
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
            {/* No role badge. "You are a student" stopped being a true
                statement about a person once the same account could teach
                one course and take another — the label belongs on the
                course, and that is where it now appears. */}
            {me && <span className="text-sm text-muted-foreground">{me.display_name}</span>}
            <ThemeToggle />
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
