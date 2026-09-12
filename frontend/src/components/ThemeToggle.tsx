import { Button } from '@/components/ui/button'
import { useTheme, type Theme } from '@/lib/theme'

/**
 * Cycles light -> dark -> follow the machine.
 *
 * One button rather than a menu: three states is few enough to cycle,
 * and the icon plus its tooltip say which one you are in. The third
 * state is worth keeping visible — without it, someone whose laptop
 * switches at sunset loses that the first time they touch this.
 */

const NEXT: Record<Theme, Theme> = { light: 'dark', dark: 'system', system: 'light' }

const LABEL: Record<Theme, string> = {
  light: 'Light theme — switch to dark',
  dark: 'Dark theme — switch to following your device',
  system: 'Following your device — switch to light',
}

function Icon({ theme }: { theme: Theme }) {
  if (theme === 'light') {
    return (
      <svg viewBox="0 0 24 24" className="size-4" fill="none" stroke="currentColor" strokeWidth="2">
        <circle cx="12" cy="12" r="4" />
        <path
          d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"
          strokeLinecap="round"
        />
      </svg>
    )
  }
  if (theme === 'dark') {
    return (
      <svg viewBox="0 0 24 24" className="size-4" fill="none" stroke="currentColor" strokeWidth="2">
        <path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8Z" strokeLinejoin="round" />
      </svg>
    )
  }
  return (
    <svg viewBox="0 0 24 24" className="size-4" fill="none" stroke="currentColor" strokeWidth="2">
      <rect x="2" y="4" width="20" height="13" rx="2" />
      <path d="M8 21h8M12 17v4" strokeLinecap="round" />
    </svg>
  )
}

export function ThemeToggle() {
  const { theme, setTheme } = useTheme()

  return (
    <Button
      variant="ghost"
      size="sm"
      onClick={() => setTheme(NEXT[theme])}
      title={LABEL[theme]}
      aria-label={LABEL[theme]}
    >
      <Icon theme={theme} />
    </Button>
  )
}
