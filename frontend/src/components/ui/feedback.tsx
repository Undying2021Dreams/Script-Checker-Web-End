import type { ReactNode } from 'react'

import { cn } from '@/lib/utils'

/**
 * The small pieces that tell someone what the app is doing.
 *
 * They live together because they are answers to the same question —
 * "what is happening right now?" — and the app was previously silent on
 * it: a pressed button looked identical to an unpressed one until its
 * result arrived, and a loading page was the word "Loading…".
 */

export function Spinner({ className }: { className?: string }) {
  return (
    <svg
      className={cn('size-4 shrink-0 animate-spin', className)}
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden="true"
    >
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeOpacity="0.25" strokeWidth="3" />
      <path
        d="M21 12a9 9 0 0 0-9-9"
        stroke="currentColor"
        strokeWidth="3"
        strokeLinecap="round"
      />
    </svg>
  )
}

/**
 * A button's label while its work is in flight.
 *
 * Takes the place of the label rather than sitting beside it, so the
 * button keeps its size and the row doesn't jump as it changes.
 */
export function Pending({ children }: { children: ReactNode }) {
  return (
    <span className="inline-flex items-center gap-2">
      <Spinner />
      {children}
    </span>
  )
}

/** Grey blocks in the shape of the content that is coming. */
export function Skeleton({ className }: { className?: string }) {
  return <div className={cn('animate-pulse rounded-md bg-muted', className)} />
}

export function CardSkeleton({ rows = 3 }: { rows?: number }) {
  return (
    <div className="space-y-3 rounded-xl border bg-card p-4">
      <Skeleton className="h-4 w-1/3" />
      {Array.from({ length: rows }).map((_, i) => (
        <Skeleton key={i} className="h-3 w-full" />
      ))}
    </div>
  )
}

/**
 * What to show where there is nothing yet.
 *
 * An empty region with no explanation reads as something that failed to
 * load. This says which it is and, where there is one, what to do about
 * it.
 */
export function EmptyState({
  title,
  hint,
  action,
}: {
  title: string
  hint?: string
  action?: ReactNode
}) {
  return (
    <div className="flex flex-col items-center gap-2 rounded-xl border border-dashed px-6 py-10 text-center">
      <p className="text-sm font-medium">{title}</p>
      {hint && <p className="max-w-md text-sm text-muted-foreground">{hint}</p>}
      {action}
    </div>
  )
}

/**
 * A coloured status pill.
 *
 * Marking is a status-heavy job — marked, waiting, needs a human,
 * published — and badges that differ only in wording have to be read one
 * at a time instead of scanned.
 */
const TONES = {
  neutral: 'bg-muted text-muted-foreground',
  success: 'bg-success-muted text-success',
  warning: 'bg-warning-muted text-warning',
  info: 'bg-info-muted text-info',
  danger: 'bg-destructive/10 text-destructive',
} as const

export function StatusPill({
  tone = 'neutral',
  children,
  className,
}: {
  tone?: keyof typeof TONES
  children: ReactNode
  className?: string
}) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium whitespace-nowrap',
        TONES[tone],
        className,
      )}
    >
      {children}
    </span>
  )
}

/** A page heading with its actions, used the same way on every screen. */
export function PageHeader({
  title,
  description,
  back,
  actions,
}: {
  title: string
  description?: ReactNode
  back?: ReactNode
  actions?: ReactNode
}) {
  return (
    <div className="space-y-3 border-b pb-4">
      {back}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
          {description && (
            <div className="mt-1 text-sm text-muted-foreground">{description}</div>
          )}
        </div>
        {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
      </div>
    </div>
  )
}
