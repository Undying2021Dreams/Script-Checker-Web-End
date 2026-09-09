import { useRef, useState } from 'react'
import { toast } from 'sonner'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { apiFetchBlobUrl } from '@/lib/api'
import { AuthedImage } from '@/components/AuthedImage'
import { MathText } from '@/components/MathText'
import { useAssignments, useSubmissionGrades, useUploadSubmission } from '@/lib/queries'
import type { StudentAssignment } from '@/lib/types'

function MarkOrStatus({ a }: { a: StudentAssignment }) {
  if (!a.submission_id) return <Badge variant="outline">Not submitted</Badge>

  if (a.released && a.earned != null) {
    return (
      <Badge variant="secondary">
        {a.earned} / {a.max_score}
      </Badge>
    )
  }

  // Deliberately says the work arrived without hinting at the mark — an
  // unreleased mark is not the student's to see yet.
  if (a.submission_status === 'queued' || a.submission_status === 'grading') {
    return <Badge variant="outline">Being marked</Badge>
  }
  return <Badge variant="outline">Submitted</Badge>
}

/**
 * A student's own marks once the teacher has released them.
 *
 * The teacher's worked answer is shown beside each mark, not just the
 * mark and a comment: a student who wants to understand why they lost
 * two marks needs to see what the answer was meant to look like, and
 * the marking scheme the teacher wrote sits in that same block.
 */
function MyResults({ submissionId }: { submissionId: string }) {
  const [open, setOpen] = useState(false)
  const { data, isLoading, error } = useSubmissionGrades(submissionId, open)

  if (!open) {
    return (
      <Button variant="outline" size="sm" onClick={() => setOpen(true)}>
        See my marks and the solutions
      </Button>
    )
  }

  return (
    <div className="space-y-3">
      <Button variant="ghost" size="sm" onClick={() => setOpen(false)}>
        Hide my marks
      </Button>

      {isLoading && <p className="text-sm text-muted-foreground">Loading your marks…</p>}
      {error && <p className="text-sm text-destructive">{(error as Error).message}</p>}

      {data?.grades.map((g) => (
        <div key={g.answer_box_id} className="space-y-2 rounded-md border p-3">
          <div className="flex items-center justify-between gap-2">
            <span className="text-sm font-medium">
              {g.label || `Part ${g.order_index + 1}`}
            </span>
            <Badge variant="secondary">
              {g.score ?? '—'} / {g.max_score}
            </Badge>
          </div>

          {g.feedback && (
            <p className="text-sm text-muted-foreground">
              <MathText text={g.feedback} />
            </p>
          )}

          {(g.model_answer_images.length > 0 || g.model_answer_text) && (
            <div className="space-y-2 border-t pt-2">
              <p className="text-xs font-medium text-muted-foreground">
                Your teacher's solution
              </p>
              {g.model_answer_images.length > 0 ? (
                g.model_answer_images.map((url) => (
                  <AuthedImage
                    key={url}
                    path={url.replace(/^\/api/, '')}
                    alt="Teacher's worked solution"
                    className="max-w-full rounded border bg-white"
                  />
                ))
              ) : (
                <p className="text-sm">
                  <MathText text={g.model_answer_text ?? ''} />
                </p>
              )}
            </div>
          )}
        </div>
      ))}
    </div>
  )
}


function AssignmentRow({ assignment }: { assignment: StudentAssignment }) {
  const fileRef = useRef<HTMLInputElement>(null)
  const [modality, setModality] = useState('photo')
  const upload = useUploadSubmission(assignment.question_id)

  const openPaper = async () => {
    try {
      const url = await apiFetchBlobUrl(`/student/assignments/${assignment.question_id}/pdf`)
      window.open(url, '_blank')
      setTimeout(() => URL.revokeObjectURL(url), 60_000)
    } catch (err) {
      toast.error(`Could not open the paper: ${(err as Error).message}`)
    }
  }

  const handleFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    try {
      await upload.mutateAsync({
        file,
        modality,
        // Attach to the existing submission so re-uploading a page
        // replaces it rather than starting a second attempt.
        submissionId: assignment.submission_id ?? undefined,
      })
      toast.success('Answer uploaded')
    } catch (err) {
      toast.error((err as Error).message)
    } finally {
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  return (
    <div className="space-y-3 rounded-md border px-3 py-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="text-sm">
          <span className={assignment.title ? 'font-medium' : 'text-muted-foreground'}>
            {assignment.title || 'Untitled paper'}
          </span>
          <span className="ml-2 text-muted-foreground">
            {assignment.total_marks} marks
            {assignment.page_count ? ` · ${assignment.page_count} page(s)` : ''}
          </span>
        </div>
        <MarkOrStatus a={assignment} />
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <Button size="sm" variant="outline" onClick={openPaper}>
          Open paper
        </Button>

        <select
          value={modality}
          onChange={(e) => setModality(e.target.value)}
          className="rounded-md border bg-transparent px-2 py-1 text-xs"
          title="How you captured the page"
        >
          <option value="photo">Photo</option>
          <option value="scanner">Scanner</option>
        </select>

        <Button size="sm" onClick={() => fileRef.current?.click()} disabled={upload.isPending}>
          {upload.isPending
            ? 'Uploading…'
            : assignment.submission_id
              ? 'Replace my answer'
              : 'Upload my answer'}
        </Button>
        <input
          ref={fileRef}
          type="file"
          accept="image/jpeg,image/png,image/webp,application/pdf"
          onChange={handleFile}
          className="hidden"
        />
      </div>

      {assignment.submission_id && !assignment.released && (
        <p className="text-xs text-muted-foreground">
          Your teacher hasn't released marks for this yet.
        </p>
      )}

      {assignment.submission_id && assignment.released && (
        <MyResults submissionId={assignment.submission_id} />
      )}
    </div>
  )
}

export function AssignmentsCard({ courseId, enabled }: { courseId: string; enabled: boolean }) {
  const { data, isLoading, error } = useAssignments(courseId, enabled)

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Assignments</CardTitle>
        <p className="text-sm text-muted-foreground">
          Open the paper, write your answers on it, then upload a photo or scan of the completed
          page.
        </p>
      </CardHeader>
      <CardContent className="space-y-3">
        {isLoading && <p className="text-sm text-muted-foreground">Loading…</p>}
        {error && <p className="text-sm text-destructive">{(error as Error).message}</p>}
        {data?.length === 0 && (
          <p className="text-sm text-muted-foreground">
            Nothing set yet — your teacher hasn't published a paper for this course.
          </p>
        )}
        {data?.map((a) => (
          <AssignmentRow key={a.question_id} assignment={a} />
        ))}
      </CardContent>
    </Card>
  )
}
