import { useState } from 'react'
import { toast } from 'sonner'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { useCheckAnswerKey, useSuggestRubric } from '@/lib/queries'
import type { AnswerBox, CorrectnessResult, GroundTruthBox, RubricSuggestion } from '@/lib/types'
import { MathText } from '@/components/MathText'

const PROVIDERS = [
  { value: 'self_hosted', label: 'Self-hosted (free)' },
  { value: 'gemini', label: 'Gemini' },
  { value: 'openai', label: 'OpenAI' },
  { value: 'claude', label: 'Claude' },
]

function ProviderSelect({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="rounded-md border bg-transparent px-2 py-1 text-xs"
    >
      {PROVIDERS.map((p) => (
        <option key={p.value} value={p.value}>
          {p.label}
        </option>
      ))}
    </select>
  )
}

/**
 * Checks the teacher's own answer key against their own questions.
 *
 * Worth running before students ever see the paper: the model answer is
 * what grading marks against, so a wrong or ambiguous one doesn't just
 * mislead a student, it propagates into every mark on that part.
 */
export function AnswerKeyCheck({
  questionId,
  groundTruthBoxes,
}: {
  questionId: string
  groundTruthBoxes: GroundTruthBox[]
}) {
  const [provider, setProvider] = useState('self_hosted')
  // Keyed by box so a single check updates just its own row, and results
  // from earlier checks stay on screen.
  const [results, setResults] = useState<Record<string, CorrectnessResult>>({})
  const [running, setRunning] = useState<string | null>(null)
  const check = useCheckAnswerKey(questionId)

  const run = async (groundTruthBoxId?: string) => {
    setRunning(groundTruthBoxId ?? 'all')
    try {
      const res = await check.mutateAsync({ provider, groundTruthBoxId })
      setResults((prev) => {
        const next = { ...prev }
        for (const r of res.results) next[r.ground_truth_box_id] = r
        return next
      })
    } catch (err) {
      toast.error((err as Error).message)
    } finally {
      setRunning(null)
    }
  }

  return (
    <Card>
      <CardHeader className="flex flex-row items-start justify-between gap-3">
        <div>
          <CardTitle className="text-base">Check my answer key</CardTitle>
          <p className="text-sm text-muted-foreground">
            Has a model read a question against your own answer, looking for a wrong or ambiguous
            answer key before it reaches students — and before grading marks against it. Check one
            question while you write it, or the whole paper at once.
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <ProviderSelect value={provider} onChange={setProvider} />
          <Button size="sm" variant="outline" onClick={() => run()} disabled={!!running}>
            {running === 'all' ? 'Checking…' : 'Check all'}
          </Button>
        </div>
      </CardHeader>

      <CardContent className="space-y-3">
        {groundTruthBoxes.length === 0 && (
          <p className="text-sm text-muted-foreground">
            No model answers yet — add one in the editor and it'll appear here.
          </p>
        )}

        {groundTruthBoxes.map((box, i) => {
          const r = results[box.id]
          return (
            <div key={box.id} className="rounded-md border px-3 py-2 text-sm">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-medium">
                  Question {i + 1}
                  {box.label ? ` — ${box.label}` : ''}
                </span>
                {r?.ok === true && <Badge variant="secondary">Looks right</Badge>}
                {r?.ok === false && (
                  <Badge variant="destructive">{r.issue || 'Possible problem'}</Badge>
                )}
                {r?.ok === null && <Badge variant="outline">Couldn't check</Badge>}
                <Button
                  size="sm"
                  variant="ghost"
                  className="ml-auto"
                  onClick={() => run(box.id)}
                  disabled={!!running}
                >
                  {running === box.id ? 'Checking…' : r ? 'Re-check' : 'Check this one'}
                </Button>
              </div>

              {r?.explanation && (
                <p className="mt-1 text-muted-foreground">
                  <MathText text={r.explanation} />
                </p>
              )}
              {r?.suggested_answer && (
                <p className="mt-1">
                  <span className="text-muted-foreground">Suggested answer: </span>
                  <MathText text={r.suggested_answer} />
                </p>
              )}
              {r?.suggested_question && (
                <p className="mt-1">
                  <span className="text-muted-foreground">Suggested question: </span>
                  <MathText text={r.suggested_question} />
                </p>
              )}
            </div>
          )
        })}

        {Object.keys(results).length > 0 && (
          <>
            <p className="text-xs text-muted-foreground">
              Advisory only — nothing here changes your paper. Apply anything you agree with in the
              editor yourself.
            </p>
            <p className="text-xs text-muted-foreground">
              Treat "Looks right" as weak evidence, particularly on the self-hosted model: tested
              against a deliberately wrong answer key, it passed it and explained why the wrong
              answer was correct. A flagged problem is worth reading; a clean pass is not proof.
            </p>
          </>
        )}
      </CardContent>
    </Card>
  )
}


/**
 * Proposes marks per answer box. Suggestions are shown next to what the
 * box is currently worth and are never applied automatically — the marks
 * a paper carries are the teacher's decision.
 */
export function RubricSuggestions({
  questionId,
  answerBoxes,
}: {
  questionId: string
  answerBoxes: AnswerBox[]
}) {
  const [provider, setProvider] = useState('self_hosted')
  const [suggestions, setSuggestions] = useState<RubricSuggestion[] | null>(null)
  const suggest = useSuggestRubric(questionId)

  const run = async () => {
    try {
      const res = await suggest.mutateAsync(provider)
      setSuggestions(res.suggestions)
    } catch (err) {
      toast.error((err as Error).message)
    }
  }

  const currentPoints = new Map(answerBoxes.map((b) => [b.id, b.points]))
  const labels = new Map(answerBoxes.map((b) => [b.id, b.label]))

  return (
    <Card>
      <CardHeader className="flex flex-row items-start justify-between gap-3">
        <div>
          <CardTitle className="text-base">Suggest marks</CardTitle>
          <p className="text-sm text-muted-foreground">
            Proposes how many marks each answer box is worth, and what to look for in an answer.
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <ProviderSelect value={provider} onChange={setProvider} />
          <Button size="sm" variant="outline" onClick={run} disabled={suggest.isPending}>
            {suggest.isPending ? 'Thinking…' : 'Suggest'}
          </Button>
        </div>
      </CardHeader>

      {suggestions && (
        <CardContent className="space-y-2">
          {suggestions.map((s) => {
            const now = currentPoints.get(s.id)
            const changed = now != null && now !== s.suggested_points
            return (
              <div key={s.id} className="rounded-md border px-3 py-2 text-sm">
                <div className="flex items-center gap-2">
                  <span className="font-medium">{labels.get(s.id) || 'unlabelled'}</span>
                  <span className="text-muted-foreground">
                    now {now} → suggested {s.suggested_points}
                  </span>
                  {changed && <Badge variant="outline">differs</Badge>}
                </div>
                {s.rubric && (
                  <p className="mt-1 text-muted-foreground">
                    <MathText text={s.rubric} />
                  </p>
                )}
              </div>
            )
          })}
          <p className="text-xs text-muted-foreground">
            Advisory only. Change a box's marks in the editor if you agree — what the paper is
            worth stays your decision.
          </p>
        </CardContent>
      )}
    </Card>
  )
}
