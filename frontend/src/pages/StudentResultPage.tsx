import { Link, useParams } from 'react-router-dom'

import { PaperImage } from '@/components/Paper'
import { MathText } from '@/components/MathText'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  CardSkeleton,
  EmptyState,
  PageHeader,
  StatusPill,
} from '@/components/ui/feedback'
import { useSubmissionGrades } from '@/lib/queries'

/**
 * A student's own result, on its own page.
 *
 * This used to unfold inside the assignment row on the course page,
 * which meant a mark, a comment and a full worked solution for every
 * part were pushed into a list item sitting beside every other
 * assignment. Reading your result is its own task and deserves its own
 * screen — and a page can be linked to, reloaded and kept open.
 */
export function StudentResultPage() {
  const { submissionId = '' } = useParams()
  const { data, isLoading, error } = useSubmissionGrades(submissionId)

  const courseLink = (
    <Link to="/" className="text-sm text-muted-foreground hover:underline">
      ← Back to my courses
    </Link>
  )

  if (isLoading) {
    return (
      <div className="space-y-4">
        <PageHeader title="Your result" back={courseLink} />
        <CardSkeleton rows={4} />
        <CardSkeleton rows={4} />
      </div>
    )
  }

  if (error) {
    return (
      <div className="space-y-4">
        <PageHeader title="Your result" back={courseLink} />
        <EmptyState
          title="This result isn't available"
          hint={(error as Error).message}
        />
      </div>
    )
  }

  if (!data) return null

  return (
    <div className="space-y-5">
      <PageHeader
        title="Your result"
        back={courseLink}
        description={
          <span className="flex flex-wrap items-center gap-2">
            <StatusPill tone="success">
              {data.earned} out of {data.max_score}
            </StatusPill>
            <span>
              {data.grades.length} part{data.grades.length === 1 ? '' : 's'} marked
            </span>
          </span>
        }
      />

      {data.grades.length === 0 && (
        <EmptyState
          title="Nothing has been marked on this yet"
          hint="Your teacher has released this submission, but no parts carry a mark."
        />
      )}

      {data.grades.map((g) => (
        <Card key={g.answer_box_id}>
          <CardHeader className="flex flex-row items-center justify-between gap-3 pb-3">
            <CardTitle className="text-base">
              {g.label || `Part ${g.order_index + 1}`}
            </CardTitle>
            <StatusPill tone={g.score === g.max_score ? 'success' : 'info'}>
              {g.score ?? '—'} / {g.max_score}
            </StatusPill>
          </CardHeader>

          <CardContent className="space-y-4">
            {g.feedback && (
              <div className="rounded-lg bg-muted/60 p-3 text-sm">
                <p className="mb-1 text-xs font-medium text-muted-foreground">
                  Your teacher's comment
                </p>
                <MathText text={g.feedback} />
              </div>
            )}

            {(g.model_answer_images.length > 0 || g.model_answer_text) && (
              <div className="space-y-2">
                {g.model_answer_images.length > 0 ? (
                  g.model_answer_images.map((url) => (
                    <PaperImage
                      key={url}
                      kind="model"
                      path={url.replace(/^\/api/, '')}
                      alt="Worked solution"
                      caption="Your teacher's solution"
                    />
                  ))
                ) : (
                  <p className="text-sm">
                    <MathText text={g.model_answer_text ?? ''} />
                  </p>
                )}
              </div>
            )}
          </CardContent>
        </Card>
      ))}
    </div>
  )
}
