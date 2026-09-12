import { useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { toast } from 'sonner'

import { AuthedImage } from '@/components/AuthedImage'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import {
  useOverrideGrade,
  useReleaseGrades,
  useRunGrading,
  useSetAnswerBoxMarks,
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

/**
 * Change what a box is worth, after the paper has been finalized.
 *
 * This lives here rather than in the question editor because here is
 * where the problem becomes visible: the teacher is looking at "marked
 * 0.5 / 1" beside a model answer whose scheme is out of ten. Boxes
 * default to one mark, and nothing says so until something has been
 * marked against it.
 */
function MarksEditor({
  box,
  onSetMarks,
}: {
  box: GroupedAnswerBox
  onSetMarks: (answerBoxId: string, points: number) => Promise<void>
}) {
  const [open, setOpen] = useState(false)
  const [points, setPoints] = useState(String(box.points))
  const [saving, setSaving] = useState(false)

  const apply = async () => {
    setSaving(true)
    try {
      await onSetMarks(box.answer_box_id, Number(points))
      setOpen(false)
      toast.success(`This part is now out of ${points}. Re-run the evaluation to mark against it.`)
    } catch (err) {
      toast.error((err as Error).message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger
        render={
          <Button variant="ghost" size="sm" className="ml-1 h-6 px-2 text-xs font-normal">
            Change marks
          </Button>
        }
      />
      <DialogContent>
        <DialogHeader>
          <DialogTitle>What is this part worth?</DialogTitle>
          <DialogDescription>
            Set this to the total of the marking scheme in your model answer. A scheme worth
            ten marked out of one is why a good answer can come back as 0.5.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-2">
          <Label htmlFor={`marks-${box.answer_box_id}`}>Marks</Label>
          <Input
            id={`marks-${box.answer_box_id}`}
            value={points}
            onChange={(e) => setPoints(e.target.value)}
            inputMode="numeric"
          />
          <p className="text-xs text-muted-foreground">
            This changes the paper for every student who answered it, not just this one. Marks
            already awarded keep the total they were given out of — a score out of one cannot
            honestly be rescaled — so re-run the evaluation afterwards.
          </p>
        </div>

        <DialogFooter>
          <DialogClose render={<Button variant="ghost">Cancel</Button>} />
          <Button onClick={apply} disabled={saving || !points.trim() || Number.isNaN(Number(points))}>
            {saving ? 'Saving…' : 'Set marks'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}


function GradeRow({
  box,
  grade,
  onOverride,
  onSetMarks,
  disabled,
}: {
  box: GroupedAnswerBox
  grade?: AnswerGrade
  onOverride: (score: number | null, feedback: string) => Promise<void>
  onSetMarks: (answerBoxId: string, points: number) => Promise<void>
  disabled: boolean
}) {
  // Seeded from whatever already stands for this box: the teacher's own
  // mark if they have set one, otherwise the model's proposal, so a
  // teacher adjusts what is there instead of retyping it.
  //
  // These are re-seeded whenever the saved values change, because the
  // grades arrive after this row first renders — a plain useState
  // initialiser captured the empty state and the fields stayed blank
  // even once a mark existed. `dirty` keeps a re-seed from overwriting
  // edits in progress, which a bare useEffect would do on every poll
  // while a grading run is live.
  const savedScore = grade?.override_score ?? grade?.llm_score ?? null
  const savedFeedback = grade?.override_feedback ?? grade?.llm_feedback ?? ''

  const [score, setScore] = useState<string>(savedScore?.toString() ?? '')
  const [feedback, setFeedback] = useState<string>(savedFeedback)
  const [dirty, setDirty] = useState(false)
  const [saving, setSaving] = useState(false)
  const [confirming, setConfirming] = useState(false)

  // A run of the model is allowed to take the fields over, including
  // from half-typed text: the teacher asked for a fresh opinion and
  // expects to see it. Ordinary edits are still protected from the
  // two-second poll, which is what `dirty` is for — so the two cases are
  // told apart by whether the model's own answer actually changed.
  //
  // A mark the teacher has already saved still wins over both: it is
  // what `savedScore` resolves to, so re-running the model never undoes
  // a decision that has been committed.
  const modelStamp = `${grade?.llm_score ?? ''}|${grade?.llm_feedback ?? ''}`
  const lastModelStamp = useRef(modelStamp)

  useEffect(() => {
    const freshlyEvaluated = lastModelStamp.current !== modelStamp
    lastModelStamp.current = modelStamp

    if (!freshlyEvaluated && dirty) return
    if (freshlyEvaluated) setDirty(false)

    setScore(savedScore?.toString() ?? '')
    setFeedback(savedFeedback)
  }, [modelStamp, savedScore, savedFeedback, dirty])

  const save = async () => {
    setSaving(true)
    try {
      await onOverride(score.trim() === '' ? null : Number(score), feedback)
      setDirty(false)
      setConfirming(false)
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
          <MarksEditor box={box} onSetMarks={onSetMarks} />
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
              onChange={(e) => {
                setDirty(true)
                setScore(e.target.value)
              }}
              placeholder={grade?.llm_score?.toString() ?? '—'}
              inputMode="decimal"
            />
          </div>
          <div className="min-w-48 flex-1">
            <label className="text-xs text-muted-foreground">Your feedback (optional)</label>
            <Input
              value={feedback}
              onChange={(e) => {
                setDirty(true)
                setFeedback(e.target.value)
              }}
            />
          </div>
          <Dialog open={confirming} onOpenChange={setConfirming}>
            <DialogTrigger
              render={
                <Button variant="outline" disabled={disabled || saving}>
                  {saving ? 'Saving…' : 'Save mark'}
                </Button>
              }
            />
            <DialogContent>
              <DialogHeader>
                <DialogTitle>Save your mark?</DialogTitle>
                <DialogDescription>
                  This becomes the mark of record for{' '}
                  {box.label || `part ${box.order_index + 1}`}, and the model's
                  will not replace it if you evaluate again.
                </DialogDescription>
              </DialogHeader>

              <div className="space-y-2 rounded-md border p-3 text-sm">
                <p>
                  <span className="text-muted-foreground">Mark: </span>
                  {score.trim() === '' ? (
                    <span className="text-muted-foreground">
                      blank — the model's {grade?.llm_score ?? '—'} / {box.points} will stand
                    </span>
                  ) : (
                    <span className="font-medium">
                      {score} / {box.points}
                    </span>
                  )}
                </p>
                <p>
                  <span className="text-muted-foreground">Feedback: </span>
                  {feedback.trim() === '' ? (
                    <span className="text-muted-foreground">
                      blank — the model's comment will stand
                    </span>
                  ) : (
                    <MathText text={feedback} />
                  )}
                </p>
              </div>

              <DialogFooter>
                <DialogClose render={<Button variant="ghost">Cancel</Button>} />
                <Button onClick={save} disabled={saving}>
                  {saving ? 'Saving…' : 'Save mark'}
                </Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>
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
  const setMarks = useSetAnswerBoxMarks(answers?.question_id ?? '', submissionId)

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
            onSetMarks={async (answerBoxId, points) => {
              await setMarks.mutateAsync({ answerBoxId, points })
            }}
          />
        ))}
      </div>
    </div>
  )
}
