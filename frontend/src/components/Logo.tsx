import { cn } from '@/lib/utils'

/**
 * The AutoCheck mark, drawn rather than exported.
 *
 * Redrawn from the generated artwork in /images because a raster logo
 * is the wrong shape for this job: those files are ~700KB each against
 * roughly two for this, they carry a baked white background that turns
 * into a white box on a dark theme, and their fine circuit traces blur
 * into noise at the 16px a favicon is actually seen at.
 *
 * The colours are the application's own tokens rather than fixed hexes,
 * so the mark shifts with the theme instead of sitting on it. The
 * original blues and greens were already close to them.
 */

export function LogoMark({
  className,
  /**
   * The circuit traces are dropped below about 32px. At that size each
   * one is well under a pixel wide, so they stop reading as circuitry
   * and start reading as dirt around the edge of the sheet.
   */
  detail = true,
}: {
  className?: string
  detail?: boolean
}) {
  return (
    <svg
      viewBox="0 0 64 64"
      className={cn('size-8', className)}
      fill="none"
      role="img"
      aria-label="AutoCheck"
    >
      {/* The script: a sheet with a folded corner. */}
      <path
        d="M12 4H26L38 16V48A6 6 0 0 1 32 54H12A6 6 0 0 1 6 48V10A6 6 0 0 1 12 4Z"
        stroke="var(--primary)"
        strokeWidth="3.5"
        strokeLinejoin="round"
      />
      <path
        d="M26 4V10A6 6 0 0 0 32 16H38"
        stroke="var(--primary)"
        strokeWidth="3"
        strokeLinejoin="round"
      />

      {/* Written work on it. */}
      <path
        d="M14 21H27M14 28H29"
        stroke="var(--primary)"
        strokeWidth="3"
        strokeLinecap="round"
      />

      {/* The mark itself — the thing the app is for. */}
      <path
        d="M13 40L20 47L32 33"
        stroke="var(--success)"
        strokeWidth="4.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />

      {detail && (
        <g stroke="var(--success)" strokeWidth="2.5" strokeLinecap="round">
          <path d="M40 25H45L48 22H51" />
          <path d="M40 33H47L50 30H51" />
          <path d="M40 41H45L48 44H51" />
          <circle cx="55" cy="22" r="3" />
          <circle cx="55" cy="30" r="3" />
          <circle cx="55" cy="44" r="3" />
        </g>
      )}
    </svg>
  )
}

/** The mark beside the name, for the header and the sign-in screen. */
export function Logo({
  className,
  tagline = false,
  markClassName,
}: {
  className?: string
  tagline?: boolean
  markClassName?: string
}) {
  return (
    <span className={cn('flex items-center gap-2.5', className)}>
      <LogoMark className={cn('size-8', markClassName)} detail={false} />
      <span className="leading-none">
        <span className="text-lg font-semibold tracking-tight">
          <span className="text-primary">Auto</span>
          <span className="text-success">Check</span>
        </span>
        {tagline && (
          <span className="mt-0.5 block text-xs font-normal text-muted-foreground">
            Automating the boring stuff
          </span>
        )}
      </span>
    </span>
  )
}
