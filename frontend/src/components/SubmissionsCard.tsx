import { useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { toast } from 'sonner'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { useSubmissions, useUploadSubmission } from '@/lib/queries'
import type { SubmissionSummary } from '@/lib/types'

function StatusBadge({ submission }: { submission: SubmissionSummary }) {
  const { grading_status, released, needs_review_count } = submission

  if (grading_status === 'queued' || grading_status === 'grading') {
    return <Badge variant="outline">Grading…</Badge>
  }
  if (grading_status === 'failed') return <Badge variant="destructive">Failed</Badge>
  if (grading_status === 'ungraded') return <Badge variant="outline">Not graded</Badge>

  return (
    <span className="flex items-center gap-1.5">
      <Badge variant="secondary">Graded</Badge>
      {!!needs_review_count && <Badge variant="outline">{needs_review_count} to review</Badge>}
      {released && <Badge>Released</Badge>}
    </span>
  )
}

export function SubmissionsCard({ questionId }: { questionId: string }) {
  const navigate = useNavigate()
  const { data: submissions, isLoading, error } = useSubmissions(questionId)
  const upload = useUploadSubmission(questionId)
  const fileRef = useRef<HTMLInputElement>(null)
  const [modality, setModality] = useState('photo')

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
        {isLoading && <p className="text-sm text-muted-foreground">Loading…</p>}
        {error && <p className="text-sm text-destructive">{(error as Error).message}</p>}
        {submissions?.length === 0 && (
          <p className="text-sm text-muted-foreground">
            No submissions yet. Print the PDF, have it answered, then upload a photo or scan of the
            completed page.
          </p>
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
