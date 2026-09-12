import { useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { toast } from 'sonner'

import { Pending, StatusPill } from '@/components/ui/feedback'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { apiFetchBlobUrl } from '@/lib/api'
import { useAssignments, useUploadSubmission } from '@/lib/queries'
import type { StudentAssignment } from '@/lib/types'

function MarkOrStatus({ a }: { a: StudentAssignment }) {
  if (!a.submission_id) return <StatusPill>Not submitted</StatusPill>

  if (a.released && a.earned != null) {
    return (
      <StatusPill tone="success">
        {a.earned} / {a.max_score}
      </StatusPill>
    )
  }

  // Deliberately says the work arrived without hinting at the mark — an
  // unreleased mark is not the student's to see yet.
  if (a.submission_status === 'queued' || a.submission_status === 'grading') {
    return <StatusPill tone="info">Being marked</StatusPill>
  }
  return <StatusPill tone="info">Submitted</StatusPill>
}

function AssignmentRow({ assignment }: { assignment: StudentAssignment }) {
  const fileRef = useRef<HTMLInputElement>(null)
  const [modality, setModality] = useState('photo')
  const upload = useUploadSubmission(assignment.question_id)

  // The server refuses a replacement once the work is marked; the UI
  // stops offering one rather than letting the student pick a file and
  // meet a 409.
  const locked = assignment.submission_status === 'graded' || assignment.released

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

        {!locked && (
          <>
            <select
              value={modality}
              onChange={(e) => setModality(e.target.value)}
              className="rounded-md border bg-background px-2 py-1 text-xs"
              title="How you captured the page"
            >
              <option value="photo">Photo</option>
              <option value="scanner">Scanner</option>
            </select>

            <Button size="sm" onClick={() => fileRef.current?.click()} disabled={upload.isPending}>
              {upload.isPending ? (
                <Pending>Uploading…</Pending>
              ) : assignment.submission_id ? (
                'Replace my answer'
              ) : (
                'Upload my answer'
              )}
            </Button>
            <input
              ref={fileRef}
              type="file"
              accept="image/jpeg,image/png,image/webp,application/pdf"
              onChange={handleFile}
              className="hidden"
            />
          </>
        )}

        {assignment.released && assignment.submission_id && (
          <Button
            size="sm"
            nativeButton={false}
            render={<Link to={`/results/${assignment.submission_id}`}>See my result</Link>}
          />
        )}
      </div>

      {/* Once the work has been marked it cannot be swapped for another
          attempt — the mark on record has to belong to the work on
          record, and a released result comes with the solution. Saying
          so beats a button that fails when pressed. */}
      {locked && (
        <p className="text-xs text-muted-foreground">
          This has been marked, so it can no longer be replaced.
        </p>
      )}

      {assignment.submission_id && !assignment.released && !locked && (
        <p className="text-xs text-muted-foreground">
          Your teacher hasn't released marks for this yet.
        </p>
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
