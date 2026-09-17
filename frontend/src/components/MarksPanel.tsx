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
}: {
  questionId: string
  question: Question
  totalPoints: number
  partsWithoutMarks: AnswerBox[]
}) {
  const { data: suggestions } = useSuggestedMarks(questionId, true)
  const setTotal = useSetPaperTotal(questionId)
  const [declared, setDeclared] = useState(
    question.total_marks_declared?.toString() ?? '',
  )

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
            . Set what each is worth on the answer box itself — finalizing is refused until
            every part has a mark.
          </p>
        )}

        {/* Suggestions, not decisions. Shown beside what the teacher has
            set so a disagreement is visible rather than silently
            resolved one way or the other. */}
        {suggestions && suggestions.length > 0 && (
          <div className="space-y-1">
            <p className="text-xs font-medium text-muted-foreground">
              What each marking scheme looks like it adds up to
            </p>
            {suggestions.map((s) => (
              <div key={s.answer_box_id} className="flex items-center gap-2 text-sm">
                <span className="min-w-0 flex-1 truncate">
                  {s.label || 'unlabelled part'}
                </span>
                <span className="tabular-nums text-muted-foreground">
                  set to {s.points ?? '—'}
                </span>
                {s.suggested == null ? (
                  <StatusPill>scheme states no total</StatusPill>
                ) : s.suggested === s.points ? (
                  <StatusPill tone="success">scheme agrees</StatusPill>
                ) : (
                  <StatusPill tone="warning">scheme says {s.suggested}</StatusPill>
                )}
              </div>
            ))}
            <p className="pt-1 text-xs text-muted-foreground">
              Read from the words of each scheme, so treat it as a second opinion. Writing
              "Max marks - 10" makes it unambiguous.
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
