import { useState } from 'react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Pending, StatusPill } from '@/components/ui/feedback'
import { useSetPaperTotal, useSuggestedMarks } from '@/lib/queries'
import type { AnswerBox, Question } from '@/lib/types'

/**
 * What each part is worth, and what the paper adds up to.
 *
 * The marks used to be read out of each marking scheme at finalize, and
 * three real schemes were parsed wrongly — alternatives counted as extra
 * criteria, a maximum stated after the word rather than before it, a
 * total written as a sum. Each was fixed, and the next scheme broke the
 * next assumption.
 *
 * What settled it is that the failures were silent. A wrong total does
 * not look wrong; it looks like a number, and it decides a grade. So the
 * scheme suggests and the teacher decides, before the paper is
 * finalized rather than after someone has been marked.
 */
export function MarksPanel({
  questionId,
  question,
  totalPoints,
  partsWithoutMarks,
  onApplyPoints,
}: {
  questionId: string
  question: Question
  totalPoints: number
  partsWithoutMarks: AnswerBox[]
  // Writes into the document rather than the database: while a paper is
  // a draft the document is what it is saved from, so a value written
  // straight to the row would be overwritten by the next autosave.
  onApplyPoints: (pointsById: Record<string, number>) => void
}) {
  const { data: suggestions } = useSuggestedMarks(questionId, true)
  const setTotal = useSetPaperTotal(questionId)
  const [declared, setDeclared] = useState(
    question.total_marks_declared?.toString() ?? '',
  )
  // What has been typed but not yet reflected back from the document.
  const [draft, setDraft] = useState<Record<string, string>>({})

  const setOne = (boxId: string, raw: string) => {
    setDraft((d) => ({ ...d, [boxId]: raw }))
    const trimmed = raw.trim()
    if (trimmed === '' || Number.isNaN(Number(trimmed))) return
    onApplyPoints({ [boxId]: Number(trimmed) })
  }

  // Emptying the field is not a value, so nothing is written — without
  // this the box would go on showing blank while the document still
  // held the old number.
  const restoreIfEmpty = (boxId: string) =>
    setDraft((d) => {
      if (d[boxId]?.trim() !== '') return d
      const { [boxId]: _cleared, ...rest } = d
      return rest
    })

  const useAllSuggestions = () => {
    const apply: Record<string, number> = {}
    for (const s of suggestions ?? []) {
      if (s.suggested != null && s.suggested !== s.points) apply[s.answer_box_id] = s.suggested
    }
    if (Object.keys(apply).length === 0) return
    onApplyPoints(apply)
    setDraft((d) => ({
      ...d,
      ...Object.fromEntries(Object.entries(apply).map(([k, v]) => [k, String(v)])),
    }))
    toast.success(`Set ${Object.keys(apply).length} part(s) from their schemes`)
  }

  // A teacher writes "a", or "Part 1", or nothing at all. Every one of
  // those has to read as a part rather than as "unlabelled part", which
  // is what the list used to show for all four boxes at once.
  const partName = (label: string | null | undefined, i: number) =>
    !label?.trim()
      ? `Part ${i + 1}`
      : /^part\b/i.test(label.trim())
        ? label.trim()
        : `Part ${label.trim()}`

  const mismatch =
    question.total_marks_declared != null && question.total_marks_declared !== totalPoints

  const saveTotal = async () => {
    const raw = declared.trim()
    try {
      await setTotal.mutateAsync(raw === '' ? null : Number(raw))
      toast.success(raw === '' ? 'Paper total cleared' : `Paper total set to ${raw}`)
    } catch (err) {
      toast.error((err as Error).message)
    }
  }

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between gap-2 pb-3">
        <CardTitle className="text-base">Marks</CardTitle>
        <StatusPill tone={partsWithoutMarks.length ? 'warning' : 'success'}>
          {totalPoints} across {question.answer_boxes.length} part(s)
        </StatusPill>
      </CardHeader>

      <CardContent className="space-y-4">
        {partsWithoutMarks.length > 0 && (
          <p className="text-sm text-destructive">
            {partsWithoutMarks.length} part(s) have no marks yet
            {partsWithoutMarks.some((b) => b.label)
              ? ` (${partsWithoutMarks.map((b) => b.label).filter(Boolean).join(', ')})`
              : ''}
            . Set what each is worth below, or on the answer box itself — finalizing is refused until
            every part has a mark.
          </p>
        )}

        {/* Set here, beside the suggestion, rather than only on the box
            itself. The panel used to list the parts and offer nowhere to
            act, which left the teacher hunting through the document for
            each one. */}
        {suggestions && suggestions.length > 0 && (
          <div className="space-y-2">
            <div className="flex items-center justify-between gap-2">
              <p className="text-xs font-medium text-muted-foreground">
                What each part is worth
              </p>
              {suggestions.some((s) => s.suggested != null && s.suggested !== s.points) && (
                <Button variant="outline" size="sm" onClick={useAllSuggestions}>
                  Use every scheme's number
                </Button>
              )}
            </div>

            {suggestions.map((s, i) => (
              <div key={s.answer_box_id} className="flex flex-wrap items-center gap-2 text-sm">
                <span className="min-w-0 flex-1 truncate">
                  {partName(s.label, i)}
                </span>

                <Input
                  value={draft[s.answer_box_id] ?? s.points?.toString() ?? ''}
                  onChange={(e) => setOne(s.answer_box_id, e.target.value)}
                  onBlur={() => restoreIfEmpty(s.answer_box_id)}
                  inputMode="numeric"
                  placeholder="—"
                  className="w-20"
                  aria-label={`Marks for ${partName(s.label, i)}`}
                />

                {s.suggested == null ? (
                  <StatusPill>scheme states no total</StatusPill>
                ) : s.suggested === s.points ? (
                  <StatusPill tone="success">scheme agrees</StatusPill>
                ) : (
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => setOne(s.answer_box_id, String(s.suggested))}
                  >
                    use {s.suggested}
                  </Button>
                )}
              </div>
            ))}

            <p className="pt-1 text-xs text-muted-foreground">
              The suggestion is read from the words of each scheme, so treat it as a second
              opinion. Writing "Max marks - 10" makes it unambiguous.
            </p>
          </div>
        )}

        <div className="space-y-2 border-t pt-3">
          <Label htmlFor="paper-total">This paper is out of (optional)</Label>
          <div className="flex items-center gap-2">
            <Input
              id="paper-total"
              value={declared}
              onChange={(e) => setDeclared(e.target.value)}
              inputMode="numeric"
              placeholder="e.g. 42"
              className="w-28"
            />
            <Button variant="outline" size="sm" onClick={saveTotal} disabled={setTotal.isPending}>
              {setTotal.isPending ? <Pending>Saving…</Pending> : 'Save'}
            </Button>
            {mismatch && (
              <StatusPill tone="danger">
                parts add up to {totalPoints}
              </StatusPill>
            )}
          </div>
          <p className="text-xs text-muted-foreground">
            Checked against the parts when you finalize. This catches the one mistake the
            parts cannot catch between them — a part left out altogether.
          </p>
        </div>
      </CardContent>
    </Card>
  )
}
