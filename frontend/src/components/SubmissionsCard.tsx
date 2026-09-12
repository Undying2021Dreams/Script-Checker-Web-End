import { useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { toast } from 'sonner'

import { EmptyState, Pending, Skeleton, Spinner, StatusPill } from '@/components/ui/feedback'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { useGradeAll, useReleaseAll, useSubmissions, useUploadSubmission } from '@/lib/queries'
import type { SubmissionSummary } from '@/lib/types'

function StatusBadge({ submission }: { submission: SubmissionSummary }) {
  const { grading_status, released, needs_review_count } = submission

  if (grading_status === 'queued' || grading_status === 'grading') {
    return (
      <StatusPill tone="info">
        <Spinner className="size-3" />
        Marking
      </StatusPill>
    )
  }
  if (grading_status === 'failed') return <StatusPill tone="danger">Failed</StatusPill>
  if (grading_status === 'ungraded') return <StatusPill>Not marked</StatusPill>

  return (
    <span className="flex items-center gap-1.5">
      <StatusPill tone="success">Marked</StatusPill>
      {!!needs_review_count && (
        <StatusPill tone="warning">{needs_review_count} to review</StatusPill>
      )}
      {released && <StatusPill tone="info">Released</StatusPill>}
    </span>
  )
}

const PROVIDERS = [
  { value: 'self_hosted', label: 'Self-hosted (free)' },
  { value: 'gemini', label: 'Gemini' },
  { value: 'openai', label: 'OpenAI' },
  { value: 'claude', label: 'Claude' },
]

export function SubmissionsCard({ questionId }: { questionId: string }) {
  const navigate = useNavigate()
  const { data: submissions, isLoading, error } = useSubmissions(questionId)
  const upload = useUploadSubmission(questionId)
  const gradeAll = useGradeAll(questionId)
  const releaseAll = useReleaseAll(questionId)
  const fileRef = useRef<HTMLInputElement>(null)
  const [modality, setModality] = useState('photo')
  const [provider, setProvider] = useState('self_hosted')

  const inFlight = submissions?.some(
    (s) => s.grading_status === 'queued' || s.grading_status === 'grading',
  )
  const ungraded = submissions?.filter((s) => s.grading_status !== 'graded').length ?? 0
  const graded = submissions?.filter((s) => s.grading_status === 'graded').length ?? 0
  const released = submissions?.filter((s) => s.released).length ?? 0

  const runGradeAll = async (includeGraded: boolean) => {
    try {
      const res = await gradeAll.mutateAsync({ provider, includeGraded })
      if (res.queued === 0) {
        toast.info(`Nothing to mark — ${res.skipped} already done`)
      } else {
        toast.success(`Marking ${res.queued} submission(s)`)
      }
    } catch (err) {
      toast.error((err as Error).message)
    }
  }

  const runReleaseAll = async (released: boolean) => {
    try {
      const res = await releaseAll.mutateAsync(released)
      if (!released) {
        toast.success(`Withdrew ${res.changed} result(s)`)
      } else if (res.skipped) {
        // Named rather than passed over silently: pressing this means
        // "publish the class", and the teacher has to know when part of
        // it could not be.
        toast.warning(
          `Released ${res.changed}. ${res.skipped} not marked yet, so still hidden.`,
        )
      } else {
        toast.success(`Released ${res.changed} result(s) to students`)
      }
    } catch (err) {
      toast.error((err as Error).message)
    }
  }

  const handleFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    try {
      const result = await upload.mutateAsync({ file, modality })
      toast.success('Uploaded and extracted')
      navigate(`/submissions/${result.submission_id}`)
    } catch (err) {
      toast.error((err as Error).message)
    } finally {
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between">
        <CardTitle className="text-base">Submissions</CardTitle>
        <div className="flex items-center gap-2">
          <select
            value={modality}
            onChange={(e) => setModality(e.target.value)}
            className="rounded-md border bg-transparent px-2 py-1 text-xs"
            title="How the page was captured — this changes how it's aligned"
          >
            <option value="photo">Photo</option>
            <option value="scanner">Scanner</option>
          </select>
          <Button size="sm" onClick={() => fileRef.current?.click()} disabled={upload.isPending}>
            {upload.isPending ? 'Extracting…' : 'Upload a page'}
          </Button>
          <input
            ref={fileRef}
            type="file"
            accept="image/jpeg,image/png,image/webp,application/pdf,image/tiff"
            onChange={handleFile}
            className="hidden"
          />
        </div>
      </CardHeader>

      <CardContent className="space-y-2">
        {!!submissions?.length && (
          <div className="mb-3 flex flex-wrap items-center gap-2 rounded-md border bg-muted/30 px-3 py-2">
            <span className="text-sm font-medium">Mark all</span>
            <select
              value={provider}
              onChange={(e) => setProvider(e.target.value)}
              className="rounded-md border bg-transparent px-2 py-1 text-xs"
            >
              {PROVIDERS.map((p) => (
                <option key={p.value} value={p.value}>
                  {p.label}
                </option>
              ))}
            </select>
            <Button
              size="sm"
              onClick={() => runGradeAll(false)}
              disabled={gradeAll.isPending || inFlight}
            >
              {inFlight ? <Pending>Marking…</Pending> : `Mark ${ungraded} unmarked`}
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={() => runGradeAll(true)}
              disabled={gradeAll.isPending || inFlight}
              title="Re-marks everything, including work already marked. Your own marks are kept."
            >
              Re-mark all
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={() => runReleaseAll(true)}
              disabled={releaseAll.isPending || inFlight || !graded}
              title="Publishes every marked submission at once. Unmarked work stays hidden."
            >
              {releaseAll.isPending ? (
                <Pending>Releasing…</Pending>
              ) : (
                `Release ${graded} to students`
              )}
            </Button>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => runReleaseAll(false)}
              disabled={releaseAll.isPending || !released}
              title="Hides every result again."
            >
              Withdraw all
            </Button>
            <span className="text-xs text-muted-foreground">
              Runs one at a time. Open any submission to change a mark, or to re-mark just that one
              with a different model. Releasing publishes marked work to students all at once, so
              nobody sees their result minutes before the rest of the class.
            </span>
          </div>
        )}

        {isLoading && (
          <div className="space-y-2">
            <Skeleton className="h-12 w-full" />
            <Skeleton className="h-12 w-full" />
          </div>
        )}
        {error && <p className="text-sm text-destructive">{(error as Error).message}</p>}
        {submissions?.length === 0 && (
          <EmptyState
            title="No submissions yet"
            hint="Print the paper, have it answered, then upload a photo or scan of the completed page."
          />
        )}

        {submissions?.map((s) => (
          <button
            key={s.id}
            onClick={() => navigate(`/submissions/${s.id}`)}
            className="flex w-full items-center justify-between gap-3 rounded-md border px-3 py-2 text-left text-sm hover:bg-muted"
          >
            <span className="flex items-center gap-2">
              <span>{s.student_name ?? 'Uploaded by teacher'}</span>
              <span className="text-xs text-muted-foreground">
                {new Date(s.created_at).toLocaleString()}
              </span>
            </span>
            <span className="flex items-center gap-2">
              {s.earned != null && s.max_score != null && (
                <span className="text-muted-foreground">
                  {s.earned} / {s.max_score}
                </span>
              )}
              <StatusBadge submission={s} />
            </span>
          </button>
        ))}
      </CardContent>
    </Card>
  )
}
