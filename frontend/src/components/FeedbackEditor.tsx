import { useState } from 'react'

import { MathText } from '@/components/MathText'

/**
 * Where a teacher writes the comment a student will read.
 *
 * Maths was always going to be in these comments — half of marking a
 * script is writing down the step that went wrong — and the same KaTeX
 * renderer sets both this preview and the student's copy, so the two
 * cannot drift apart.
 *
 * The comment is set underneath exactly as the student will see it,
 * and a comment that is nothing but an equation is typeset whether or
 * not it was wrapped in dollars — see MathText. A row of symbol buttons
 * lived here briefly and was in the way: the preview is the thing that
 * tells you whether you have it right.
 *
 * Deliberately not a rich editor. Bold and bullet lists are worth
 * little in a two-line comment, and they would cost a change of storage
 * format, a migration, and a second renderer for the student's side.
 */

export function FeedbackEditor({
  value,
  onChange,
  modelFeedback,
  savedFeedback,
  provider,
  disabled,
}: {
  value: string
  onChange: (next: string) => void
  /** What the model said, if it has been asked. */
  modelFeedback?: string | null
  /** What this teacher last saved, if anything. */
  savedFeedback?: string | null
  provider?: string | null
  disabled?: boolean
}) {
  const [showHistory, setShowHistory] = useState(false)

  const hasHistory = !!(modelFeedback || savedFeedback)

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between gap-2">
        <label className="text-xs text-muted-foreground">Your feedback (optional)</label>
        {hasHistory && (
          <button
            type="button"
            onClick={() => setShowHistory((v) => !v)}
            className="text-xs text-muted-foreground underline-offset-2 hover:underline"
          >
            {showHistory ? 'Hide what was written before' : 'What was written before'}
          </button>
        )}
      </div>

      {/* Both earlier versions, on demand. Replacing a comment without
          being able to read the one you are replacing is how a teacher
          ends up repeating the model, or contradicting themselves. */}
      {showHistory && (
        <div className="space-y-2 rounded-lg border bg-muted/40 p-2 text-sm">
          {savedFeedback && (
            <div>
              <p className="mb-1 text-xs font-medium text-muted-foreground">
                Yours, as last saved
              </p>
              <MathText text={savedFeedback} />
            </div>
          )}
          {modelFeedback && (
            <div>
              <p className="mb-1 text-xs font-medium text-muted-foreground">
                The model's{provider ? ` (${provider})` : ''}
              </p>
              <MathText text={modelFeedback} />
            </div>
          )}
        </div>
      )}

      <textarea
        value={value}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled}
        rows={3}
        placeholder="Write the comment the student will see. Maths between $…$ is typeset."
        className="w-full rounded-md border bg-transparent px-3 py-2 text-sm"
      />

      {/* Set exactly as the student will read it — same renderer, same
          delimiters. What is typed is rarely what is read. */}
      {value.trim() !== '' && (
        <div className="rounded-lg border border-dashed bg-card p-2 text-sm">
          <p className="mb-1 text-xs font-medium text-muted-foreground">
            What the student will see
          </p>
          <MathText text={value} />
        </div>
      )}
    </div>
  )
}
