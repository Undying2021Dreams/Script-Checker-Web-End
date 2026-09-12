import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { toast } from 'sonner'

import { AnswerKeyPreview } from '@/components/AnswerKeyPreview'
import { AnswerKeyCheck, RubricSuggestions } from '@/components/AuthoringHelpers'
import { SubmissionsCard } from '@/components/SubmissionsCard'
import QuestionEditor from '@/components/editor/QuestionEditor'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
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
import { Label } from '@/components/ui/label'
import { apiFetch, apiFetchBlobUrl } from '@/lib/api'
import { Input } from '@/components/ui/input'
import {
  useCloneQuestion,
  useDeleteQuestion,
  useFinalizeQuestion,
  useQuestion,
  useRenameQuestion,
  useSaveQuestion,
} from '@/lib/queries'
import type { QuestionDocPayload } from '@/lib/types'

type SaveState = 'idle' | 'saving' | 'saved' | 'error'

/**
 * Remove a paper and everything students did on it.
 *
 * Confirmation is typed rather than clicked. This destroys work that
 * belongs to other people — every submission, every mark, released or
 * not — and none of it can be recovered, so it should not be one
 * mis-aimed click away from a button that sits beside "Edit as a new
 * copy".
 */
function DeleteQuestionButton({
  questionId,
  courseId,
}: {
  questionId: string
  courseId: string
}) {
  const [open, setOpen] = useState(false)
  const [typed, setTyped] = useState('')
  const navigate = useNavigate()
  const remove = useDeleteQuestion(questionId)

  const confirmed = typed.trim().toLowerCase() === 'delete'

  const handleDelete = async () => {
    try {
      const result = await remove.mutateAsync()
      toast.success(
        result.submissions_deleted
          ? `Assignment deleted, along with ${result.submissions_deleted} submission(s) and ${result.marks_deleted} mark(s).`
          : 'Assignment deleted.',
      )
      navigate(`/courses/${courseId}`)
    } catch (err) {
      toast.error((err as Error).message)
    }
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger render={<Button variant="ghost">Delete</Button>} />
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Delete this assignment?</DialogTitle>
          <DialogDescription>
            Every submission students made against this paper goes with it, along with every
            mark and comment, released or not. This cannot be undone.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-2">
          <Label htmlFor="confirm-delete">Type DELETE to confirm</Label>
          <Input
            id="confirm-delete"
            value={typed}
            onChange={(e) => setTyped(e.target.value)}
            placeholder="DELETE"
            autoComplete="off"
          />
        </div>

        <DialogFooter>
          <DialogClose render={<Button variant="ghost">Cancel</Button>} />
          <Button
            variant="destructive"
            onClick={handleDelete}
            disabled={!confirmed || remove.isPending}
          >
            {remove.isPending ? 'Deleting…' : 'Delete assignment'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

export function QuestionEditorPage() {
  const { questionId = '' } = useParams()
  const navigate = useNavigate()
  const { data: question, isLoading, error } = useQuestion(questionId)
  const save = useSaveQuestion(questionId)
  const finalize = useFinalizeQuestion(questionId)
  const rename = useRenameQuestion(questionId)
  const clone = useCloneQuestion(questionId)

  const [saveState, setSaveState] = useState<SaveState>('idle')
  const latest = useRef<QuestionDocPayload | null>(null)

  const isFinalized = question?.state === 'finalized'

  const handleDocChange = async (payload: QuestionDocPayload) => {
    // The editor's autosave is debounced, so a keystroke from just before
    // finalizing can land after it. A finalized question rejects saves
    // (409), which surfaced as an error the teacher could do nothing
    // about — drop the stale save instead.
    if (isFinalized) return

    latest.current = payload
    setSaveState('saving')
    try {
      await save.mutateAsync(payload)
      setSaveState('saved')
    } catch (err) {
      setSaveState('error')
      toast.error((err as Error).message)
    }
  }

  // Warn before leaving with an in-flight save, so a last edit isn't lost.
  useEffect(() => {
    const handler = (e: BeforeUnloadEvent) => {
      if (saveState === 'saving') e.preventDefault()
    }
    window.addEventListener('beforeunload', handler)
    return () => window.removeEventListener('beforeunload', handler)
  }, [saveState])

  const handleFinalize = async () => {
    // Finalizing freezes the layout and bakes the fiducial markers, so
    // flush any pending edit first — otherwise the printed page and the
    // stored answer boxes disagree.
    if (latest.current) {
      try {
        await save.mutateAsync(latest.current)
      } catch (err) {
        toast.error(`Could not save before finalizing: ${(err as Error).message}`)
        return
      }
    }
    try {
      await finalize.mutateAsync()
      // Nothing further should be saved against this question now.
      latest.current = null
      toast.success('Finalized — the PDF is ready to print')
    } catch (err) {
      toast.error((err as Error).message)
    }
  }

  const handleClone = async () => {
    try {
      const copy = await clone.mutateAsync()
      toast.success('Copied to a new draft')
      navigate(`/questions/${copy.question_id}`)
    } catch (err) {
      toast.error((err as Error).message)
    }
  }

  const handleOpenPdf = async () => {
    try {
      // The PDF endpoint needs a bearer token, so it has to be fetched
      // rather than linked to directly.
      const url = await apiFetchBlobUrl(`/questions/${questionId}/pdf`)
      window.open(url, '_blank')
      // Give the new tab time to load it before releasing the blob.
      setTimeout(() => URL.revokeObjectURL(url), 60_000)
    } catch (err) {
      toast.error(`Could not open the PDF: ${(err as Error).message}`)
    }
  }

  const handleUploadImage = async (file: File, qid?: string): Promise<string> => {
    const form = new FormData()
    form.append('image', file)
    const res = await apiFetch<{ url: string }>(`/questions/${qid ?? questionId}/images`, {
      method: 'POST',
      body: form,
    })
    return res.url
  }

  const handleEquationFromImage = async (
    file: File,
    provider: string,
    qid?: string,
  ): Promise<string> => {
    const form = new FormData()
    form.append('image', file)
    form.append('provider', provider)
    const res = await apiFetch<{ latex: string }>(
      `/questions/${qid ?? questionId}/equation-from-image`,
      { method: 'POST', body: form },
    )
    return res.latex
  }

  if (isLoading) return <p className="text-muted-foreground">Loading…</p>
  if (error) return <p className="text-destructive">{(error as Error).message}</p>
  if (!question) return null

  const totalPoints = question.answer_boxes.reduce((sum, b) => sum + (b.points ?? 0), 0)
  // Parts whose worth was never decided. The marking scheme in the model
  // answer states no figure and nobody set one by hand, so grading will
  // refuse them rather than mark them out of an assumed number.
  const partsWithoutMarks = question.answer_boxes.filter((b) => b.points == null)

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <Link
            to={`/courses/${question.course_id}`}
            className="text-sm text-muted-foreground hover:underline"
          >
            ← Back to course
          </Link>
          {/* Renaming stays available after finalizing: the title is
              metadata and never reaches the printed page. */}
          <Input
            key={question.question_id}
            defaultValue={question.title ?? ''}
            placeholder="Untitled paper"
            onBlur={(e) => {
              const next = e.target.value.trim()
              if (next !== (question.title ?? '')) rename.mutate(next)
            }}
            className="mt-1 h-auto border-none px-0 text-xl font-semibold shadow-none focus-visible:ring-0"
          />
        </div>

        <div className="flex items-center gap-3">
          <span className="text-sm text-muted-foreground">
            {question.answer_boxes.length} answer box(es) · {totalPoints} marks
          </span>

          {!isFinalized && (
            <span className="text-sm text-muted-foreground">
              {saveState === 'saving' && 'Saving…'}
              {saveState === 'saved' && 'Saved'}
              {saveState === 'error' && <span className="text-destructive">Save failed</span>}
            </span>
          )}

          {isFinalized ? (
            <>
              <Badge variant="secondary">Finalized</Badge>
              <Button variant="outline" onClick={handleOpenPdf}>
                Open PDF
              </Button>
              {/* The only way to change a finalized paper: its layout and
                  printed markers are frozen, so edits go into a fresh copy. */}
              <Button variant="outline" onClick={handleClone} disabled={clone.isPending}>
                {clone.isPending ? 'Copying…' : 'Edit as a new copy'}
              </Button>
              <DeleteQuestionButton questionId={questionId} courseId={question.course_id} />
            </>
          ) : (
            <Button onClick={handleFinalize} disabled={finalize.isPending}>
              {finalize.isPending ? 'Finalizing…' : 'Finalize'}
            </Button>
          )}
        </div>
      </div>

      {!isFinalized && (
        <p className="text-sm text-muted-foreground">
          Finalizing freezes the layout and prints the alignment markers students' scans are
          matched against. It also reads what each part is worth from the marking scheme in its
          model answer. You can still edit freely now; once finalized, changes go into a new
          copy instead.
        </p>
      )}

      {/* Said plainly rather than filled in with a guess. A box silently
          standing at one mark while the scheme beside it was worth ten is
          exactly how a correct answer came back as 0.5. */}
      {partsWithoutMarks.length > 0 && (
        <p className="text-sm text-destructive">
          {partsWithoutMarks.length} part(s) have no marks yet
          {partsWithoutMarks.some((b) => b.label)
            ? ` (${partsWithoutMarks.map((b) => b.label).filter(Boolean).join(', ')})`
            : ''}
          . Write the marks into the model answer — "5 marks for the method, 5 marks for the
          answer" — and they will be picked up
          {isFinalized ? ' when you re-finalize a copy' : ' when you finalize'}. Grading skips a
          part whose worth is undecided rather than marking it out of a guess.
        </p>
      )}

      {/* Authoring aids belong while the paper can still change; once
          finalized, acting on their advice means cloning it anyway. */}
      {!isFinalized && (
        <AnswerKeyCheck
          questionId={questionId}
          groundTruthBoxes={question.ground_truth_boxes}
        />
      )}
      {!isFinalized && question.answer_boxes.length > 0 && (
        <RubricSuggestions questionId={questionId} answerBoxes={question.answer_boxes} />
      )}

      {/* Both only exist once the paper is frozen: finalize is what
          renders the answer key and makes the paper printable. */}
      {isFinalized && <AnswerKeyPreview questionId={questionId} enabled={isFinalized} />}
      {isFinalized && <SubmissionsCard questionId={questionId} />}

      <QuestionEditor
        question={question}
        onDocChange={handleDocChange}
        onUploadImage={handleUploadImage}
        onEquationFromImage={handleEquationFromImage}
      />
    </div>
  )
}
