import { useRef, useState } from 'react'

import { MathText } from '@/components/MathText'
import { Button } from '@/components/ui/button'

/**
 * Where a teacher writes the comment a student will read.
 *
 * Maths was always going to be in these comments — half of marking a
 * script is writing down the step that went wrong — and it has always
 * rendered, because the same KaTeX renderer sets the student's copy.
 * What was missing was any help producing it: a teacher had to know
 * that `\frac{a}{b}` is a fraction and type it by hand, into a field
 * that showed them nothing until they saved.
 *
 * So: buttons that insert the notation, and the comment set underneath
 * exactly as the student will see it. Deliberately not a rich editor —
 * bold and bullet lists are worth little in a two-line comment, and
 * they would cost a change of storage format, a migration, and a
 * second renderer for the student's side.
 */

/** Inserted around the selection, or at the cursor. `caret` says where
 *  to leave the cursor, counted back from the end of the snippet. */
const TOOLS: { label: string; title: string; before: string; after: string; caret?: number }[] = [
  { label: '$x$', title: 'Maths, inline', before: '$', after: '$' },
  { label: '$$x$$', title: 'Maths, on its own line', before: '\n$$', after: '$$\n' },
  { label: 'a⁄b', title: 'Fraction', before: '\\frac{', after: '}{}', caret: 1 },
  { label: 'xⁿ', title: 'Power', before: '^{', after: '}', caret: 1 },
  { label: 'xₙ', title: 'Subscript', before: '_{', after: '}', caret: 1 },
  { label: '√', title: 'Square root', before: '\\sqrt{', after: '}', caret: 1 },
  { label: '∫', title: 'Integral', before: '\\int_{', after: '}^{} ', caret: 4 },
  { label: '≤', title: 'Less than or equal', before: '\\leq ', after: '' },
  { label: '≥', title: 'Greater than or equal', before: '\\geq ', after: '' },
  { label: '≠', title: 'Not equal', before: '\\neq ', after: '' },
  { label: '×', title: 'Times', before: '\\times ', after: '' },
  { label: 'π', title: 'Pi', before: '\\pi ', after: '' },
  { label: '°', title: 'Degrees', before: '^{\\circ}', after: '' },
]

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
  const box = useRef<HTMLTextAreaElement>(null)
  const [showHistory, setShowHistory] = useState(false)

  const insert = (before: string, after: string, caret = 0) => {
    const el = box.current
    if (!el) return
    const start = el.selectionStart ?? value.length
    const end = el.selectionEnd ?? start
    const chosen = value.slice(start, end)
    onChange(value.slice(0, start) + before + chosen + after + value.slice(end))

    // With something selected, it becomes the first part of the
    // notation and the cursor belongs in the next empty slot. With
    // nothing selected, every slot is empty, so the cursor belongs in
    // the first one — otherwise clicking the fraction button leaves you
    // typing the denominator.
    const at = chosen
      ? start + before.length + chosen.length + after.length - caret
      : start + before.length

    // After React has written the new value back, or the cursor lands
    // in the old text and the next keystroke appears somewhere
    // surprising.
    requestAnimationFrame(() => {
      el.focus()
      el.setSelectionRange(at, at)
    })
  }

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

      <div className="flex flex-wrap gap-1">
        {TOOLS.map((t) => (
          <Button
            key={t.label}
            type="button"
            variant="outline"
            size="sm"
            disabled={disabled}
            title={t.title}
            className="h-7 px-2 font-serif text-xs"
            onClick={() => insert(t.before, t.after, t.caret)}
          >
            {t.label}
          </Button>
        ))}
      </div>

      <textarea
        ref={box}
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
