import { useState, type ReactNode } from 'react'

import { AuthedImage } from '@/components/AuthedImage'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { cn } from '@/lib/utils'

/**
 * A frame for anything that is a piece of paper.
 *
 * Scans, model answers and the rendered page are all white, and so were
 * the cards holding them, so the only thing separating the student's
 * script from the application around it was a hairline border.
 *
 * The paper itself is never touched — not tinted, not dimmed, not
 * inverted in dark mode. A teacher judging faint pencil is judging the
 * scan's real tone, and altering it would change the evidence. So the
 * separation comes entirely from what sits behind and around it: a
 * muted mat, a border, a shadow, and a strip naming what this is.
 */

type Kind = 'student' | 'model' | 'page'

const KIND = {
  /**
   * Student work and model answers are told apart on sight, because on
   * the review screen they sit near each other and mistaking one for the
   * other is the actual risk. The grading prompt already guards against
   * exactly this confusion for the model — "the first N images are the
   * official model answer … reproducing them as the student's work is a
   * serious error" — while the person marking got no such cue.
   */
  student: { bar: 'text-info', dot: 'bg-info' },
  model: { bar: 'text-success', dot: 'bg-success' },
  page: { bar: 'text-muted-foreground', dot: 'bg-muted-foreground' },
} as const satisfies Record<Kind, { bar: string; dot: string }>

export function PaperSurface({
  caption,
  kind = 'page',
  children,
  actions,
}: {
  caption?: ReactNode
  kind?: Kind
  children: ReactNode
  actions?: ReactNode
}) {
  return (
    <div className="overflow-hidden rounded-xl border bg-muted/60">
      {caption && (
        <div className="flex items-center gap-2 px-3 py-1.5 text-xs font-medium">
          <span className={cn('size-1.5 rounded-full', KIND[kind].dot)} />
          <span className={KIND[kind].bar}>{caption}</span>
          {actions && <span className="ml-auto">{actions}</span>}
        </div>
      )}
      {/* The mat: padding in the muted surface so the white page has
          something to sit on rather than meeting a white card edge-on. */}
      <div className={cn('px-3 pb-3', !caption && 'pt-3')}>
        <div className="overflow-hidden rounded-lg border border-border/80 bg-white shadow-sm">
          {children}
        </div>
      </div>
    </div>
  )
}

export function PaperImage({
  path,
  alt,
  caption,
  kind = 'page',
  /**
   * Tall scans are capped and scroll inside their own frame. A full page
   * at full width otherwise pushes the marks, the feedback and every
   * other part off the screen, so reading one answer means losing the
   * rest of the submission.
   */
  maxHeight = '28rem',
}: {
  path: string
  alt: string
  caption?: ReactNode
  kind?: Kind
  maxHeight?: string | false
}) {
  const [zoomed, setZoomed] = useState(false)

  return (
    <>
      <PaperSurface
        caption={caption}
        kind={kind}
        actions={<span className="text-muted-foreground">click to enlarge</span>}
      >
        <button
          type="button"
          onClick={() => setZoomed(true)}
          className="block w-full cursor-zoom-in overflow-auto text-left transition hover:brightness-[0.98]"
          style={maxHeight === false ? undefined : { maxHeight }}
          title="Enlarge"
        >
          <AuthedImage path={path} alt={alt} className="block w-full" />
        </button>
      </PaperSurface>

      {/* Marking means looking closely at handwriting, and a thumbnail
          in a column is not enough to read a worked solution. */}
      <Dialog open={zoomed} onOpenChange={setZoomed}>
        <DialogContent className="max-h-[92vh] overflow-auto sm:max-w-5xl">
          <DialogHeader>
            <DialogTitle>{caption ?? alt}</DialogTitle>
          </DialogHeader>
          <div className="rounded-lg border bg-white">
            <AuthedImage path={path} alt={alt} className="block w-full" />
          </div>
        </DialogContent>
      </Dialog>
    </>
  )
}
