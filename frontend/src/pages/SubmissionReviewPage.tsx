import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { toast } from 'sonner'

import { AuthedImage } from '@/components/AuthedImage'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import {
  useOverrideGrade,
  useReleaseGrades,
  useRunGrading,
  useSubmissionAnswers,
  useSubmissionGrades,
} from '@/lib/queries'
import type { AnswerGrade, GroupedAnswerBox } from '@/lib/types'
import { MathText } from '@/components/MathText'

const PROVIDERS = [
  { value: 'self_hosted', label: 'Self-hosted (free)' },
  { value: 'gemini', label: 'Gemini' },
  { value: 'openai', label: 'OpenAI' },
  { value: 'claude', label: 'Claude' },
]

function cropPath(cropUrl: string): string {
  // Stored as an absolute URL against PUBLIC_BASE_URL; AuthedImage wants
  // the API path so it can attach the bearer token.
  const idx = cropUrl.indexOf('/api/')
  return idx >= 0 ? cropUrl.slice(idx + 4) : cropUrl
}

function QrBadge({ qr }: { qr: string | null }) {
  if (qr === 'pass') return <Badge variant="secondary">QR verified</Badge>
  if (qr === 'fail') {
    // The crop may not be the region it claims to be — worth a human look
    // before trusting any mark derived from it.
    return <Badge variant="destructive">QR mismatch</Badge>
  }
  return <Badge variant="outline">No QR</Badge>
}

function GradeRow({
  box,
  grade,
  onOverride,
  disabled,
}: {
  box: GroupedAnswerBox
  grade?: AnswerGrade
  onOverride: (score: number | null, feedback: string) => Promise<void>
  disabled: boolean
}) {
  const [score, setScore] = useState<string>(grade?.override_score?.toString() ?? '')
  const [feedback, setFeedback] = useState<string>('')
  const [saving, setSaving] = useState(false)

  const save = async () => {
    setSaving(true)
    try {
      await onOverride(score.trim() === '' ? null : Number(score), feedback)
      toast.success(`Saved mark for ${box.label || 'this part'}`)
    } catch (err) {
      toast.error((err as Error).message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between gap-3 pb-3">
        <CardTitle className="text-base">
          {box.label || `Part ${box.order_index + 1}`}
          <span className="ml-2 text-sm font-normal text-muted-foreground">
            out of {box.points}
          </span>
        </CardTitle>
        <div className="flex items-center gap-2">
          {!box.complete && <Badge variant="destructive">Missing a page</Badge>}
          {grade?.needs_manual_review && <Badge variant="outline">Needs review</Badge>}
        </div>
      </CardHeader>

      <CardContent className="space-y-4">
        <div className="space-y-2">
          {box.parts.length === 0 && (
            <p className="text-sm text-muted-foreground">
              Nothing was extracted for this box — the page it's on may not have been uploaded.
            </p>
          )}
          {box.parts.map((part) => (
            <div key={part.part} className="space-y-1">
              <div className="flex items-center gap-2 text-xs text-muted-foreground">
                <span>
                  Part {part.part + 1}
                  {part.page_index != null && ` · page ${part.page_index + 1}`}
                </span>
                <QrBadge qr={part.qr_check} />
                {part.registration && <span>{part.registration} alignment</span>}
              </div>
              <AuthedImage
                path={cropPath(part.crop_url)}
                alt={`Answer ${box.label} part ${part.part + 1}`}
                className="max-w-full rounded border bg-white"
              />
            </div>
          ))}
        </div>

        {grade && (
          <div className="rounded-md bg-muted/50 p-3 text-sm">
            {grade.needs_manual_review ? (
              <p className="text-muted-foreground">
                Not marked automatically: {grade.review_reason}
              </p>
            ) : (
              <p>
                <span className="font-medium">
                  Model marked {grade.llm_score} / {grade.max_score}
                </span>
                {grade.provider && (
                  <span className="text-muted-foreground"> · {grade.provider}</span>
                )}
              </p>
            )}
            {grade.feedback && (
              <p className="mt-1 text-muted-foreground">
                <MathText text={grade.feedback} />
              </p>
            )}
          </div>
        )}

        <div className="flex flex-wrap items-end gap-2">
          <div className="w-24">
            <label className="text-xs text-muted-foreground">Your mark</label>
            <Input
              value={score}
              onChange={(e) => setScore(e.target.value)}
              placeholder={grade?.llm_score?.toString() ?? '—'}
              inputMode="decimal"
            />
          </div>
          <div className="min-w-48 flex-1">
            <label className="text-xs text-muted-foreground">Your feedback (optional)</label>
            <Input value={feedback} onChange={(e) => setFeedback(e.target.value)} />
          </div>
          <Button variant="outline" onClick={save} disabled={disabled || saving}>
            {saving ? 'Saving…' : 'Save mark'}
          </Button>
        </div>
        <p className="text-xs text-muted-foreground">
          Leave the mark blank to fall back to the model's. Your mark always wins, and both are
          kept on record.
        </p>
      </CardContent>
    </Card>
  )
}

export function SubmissionReviewPage() {
  const { submissionId = '' } = useParams()
  const [provider, setProvider] = useState('self_hosted')

  const { data: answers, isLoading: loadingAnswers, error: answersError } =
    useSubmissionAnswers(submissionId)
  const { data: current } = useSubmissionGrades(submissionId)
  const inFlight = current?.grading_status === 'queued' || current?.grading_status === 'grading'

  const runGrading = useRunGrading(submissionId)
  const override = useOverrideGrade(submissionId)
  const release = useReleaseGrades(submissionId)

  const gradeByBox = new Map((current?.grades ?? []).map((g) => [g.answer_box_id, g]))

  const handleGrade = async () => {
    try {
      await runGrading.mutateAsync(provider)
      toast.success('Grading started')
    } catch (err) {
      toast.error((err as Error).message)
    }
  }

  const handleRelease = async () => {
    try {
      await release.mutateAsync(!current?.released)
      toast.success(current?.released ? 'Marks withdrawn' : 'Marks released to the student')
    } catch (err) {
      toast.error((err as Error).message)
    }
  }

  if (loadingAnswers) return <p className="text-muted-foreground">Loading…</p>
  if (answersError) return <p className="text-destructive">{(answersError as Error).message}</p>
  if (!answers) return null

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <Link
            to={`/questions/${answers.question_id}`}
            className="text-sm text-muted-foreground hover:underline"
          >
            ← Back to question
          </Link>
          <h1 className="mt-1 text-xl font-semibold">Review submission</h1>
          <p className="text-sm text-muted-foreground">
            {answers.modality} · {answers.answer_boxes.length} answer box(es)
            {current && ` · ${current.earned} / ${current.max_score} marks`}
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <select
            value={provider}
            onChange={(e) => setProvider(e.target.value)}
            className="rounded-md border bg-transparent px-2 py-1.5 text-sm"
          >
            {PROVIDERS.map((p) => (
              <option key={p.value} value={p.value}>
                {p.label}
              </option>
            ))}
          </select>
          <Button onClick={handleGrade} disabled={runGrading.isPending || inFlight}>
            {inFlight ? 'Grading…' : current?.grades.length ? 'Re-grade' : 'Grade with AI'}
          </Button>
          <Button
            variant="outline"
            onClick={handleRelease}
            disabled={current?.grading_status !== 'graded'}
          >
            {current?.released ? 'Withdraw marks' : 'Release to student'}
          </Button>
        </div>
      </div>

      {current?.grading_status === 'failed' && (
        <p className="text-sm text-destructive">Grading failed: {current.grading_error}</p>
      )}

      {current && !current.released && current.grading_status === 'graded' && (
        <p className="text-sm text-muted-foreground">
          The student can't see these marks yet. Review them, then release.
        </p>
      )}

      <div className="space-y-4">
        {answers.answer_boxes.map((box) => (
          <GradeRow
            key={box.answer_box_id}
            box={box}
            grade={gradeByBox.get(box.answer_box_id)}
            disabled={!!inFlight}
            onOverride={async (score, feedback) => {
              await override.mutateAsync({
                answerBoxId: box.answer_box_id,
                score,
                feedback: feedback || undefined,
              })
            }}
          />
        ))}
      </div>
    </div>
  )
}
