import { useState } from 'react'
import { Link } from 'react-router-dom'
import { toast } from 'sonner'

import { Pending, StatusPill } from '@/components/ui/feedback'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { openAuthedPdf } from '@/lib/pdf'
import { useAssignments } from '@/lib/queries'
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

function AssignmentRow({ assignment, courseId }: { assignment: StudentAssignment; courseId: string }) {
  // The paper is fetched, not linked to, because the endpoint wants a
  // bearer token — so there is a wait, and the button has to show it.
  // Without that the only feedback is nothing happening, and pressing
  // again just opens another tab.
  const [opening, setOpening] = useState(false)

  const openPaper = async () => {
    if (opening) return
    setOpening(true)
    try {
      const name = `${assignment.title || 'paper'}.pdf`.replace(/[/\\]/g, '-')
      const how = await openAuthedPdf(
        `/student/assignments/${assignment.question_id}/pdf`,
        name,
      )
      if (how === 'download') {
        toast.success('Your browser blocked the new tab, so the paper was saved instead.')
      }
    } catch (err) {
      toast.error(`Could not open the paper: ${(err as Error).message}`)
    } finally {
      setOpening(false)
    }
  }

  // Uploading used to happen from this row, which left no way to see
  // what had been sent or to take a bad page back. Assembling a script
  // is its own task and has its own page now.
  const submitLink =
    `/assignments/${assignment.question_id}/submit?course=${courseId}` +
    (assignment.submission_id ? `&submission=${assignment.submission_id}` : '')

  return (
    <div className="space-y-3 rounded-lg border bg-card px-3 py-3">
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
        <Button size="sm" variant="outline" onClick={openPaper} disabled={opening}>
          {opening ? <Pending>Opening…</Pending> : 'Open paper'}
        </Button>

        {!assignment.handed_in && (
          <Button
            size="sm"
            nativeButton={false}
            render={
              <Link to={submitLink}>
                {assignment.submitted_pages > 0 ? 'Continue my answer' : 'Answer this'}
              </Link>
            }
          />
        )}

        {assignment.released && assignment.submission_id && (
          <Button
            size="sm"
            variant="outline"
            nativeButton={false}
            render={<Link to={`/results/${assignment.submission_id}`}>See my result</Link>}
          />
        )}
      </div>

      {assignment.submitted_pages > 0 && (
        <p className="text-xs text-muted-foreground">
          {assignment.submitted_pages} page{assignment.submitted_pages === 1 ? '' : 's'}
          {assignment.handed_in ? ' handed in' : ' added — not handed in yet'}
          {assignment.handed_in && !assignment.released && ". Your teacher hasn't released marks yet."}
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
          <AssignmentRow key={a.question_id} assignment={a} courseId={courseId} />
        ))}
      </CardContent>
    </Card>
  )
}
