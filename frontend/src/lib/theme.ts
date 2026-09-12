import { useEffect, useState } from 'react'

/**
 * Light, dark, or whatever the machine is set to.
 *
 * "System" is a real third choice rather than a starting value: someone
 * whose laptop switches at sunset expects this to switch with it, and
 * collapsing that to a remembered light/dark the first time they touch
 * the control takes the behaviour away.
 *
 * The dark palette has existed in index.css from the start; nothing ever
 * applied the class that selects it. Meanwhile `color-scheme: light
 * dark` was already declared, so a machine in dark mode drew dark
 * scrollbars and form controls around a determinedly light page.
 */

export type Theme = 'system' | 'light' | 'dark'

const KEY = 'webend-theme'

export function readTheme(): Theme {
  try {
    const stored = localStorage.getItem(KEY)
    if (stored === 'light' || stored === 'dark' || stored === 'system') return stored
  } catch {
    // Private windows and blocked site data throw rather than return
    // null. Following the machine is a fine answer when we can't ask.
  }
  return 'system'
}

export function applyTheme(theme: Theme) {
  const dark =
    theme === 'dark' ||
    (theme === 'system' && window.matchMedia('(prefers-color-scheme: dark)').matches)
  document.documentElement.classList.toggle('dark', dark)
}

export function useTheme() {
  const [theme, setThemeState] = useState<Theme>(readTheme)

  useEffect(() => {
    applyTheme(theme)
    try {
      localStorage.setItem(KEY, theme)
    } catch {
      // Not being able to remember the choice is survivable; not being
      // able to apply it is not, and that already happened above.
    }

    if (theme !== 'system') return

    // Only while following the machine: otherwise an explicit choice
    // would be overridden the moment the machine changed its mind.
    const media = window.matchMedia('(prefers-color-scheme: dark)')
    const onChange = () => applyTheme('system')
    media.addEventListener('change', onChange)
    return () => media.removeEventListener('change', onChange)
  }, [theme])

  return { theme, setTheme: setThemeState }
}
