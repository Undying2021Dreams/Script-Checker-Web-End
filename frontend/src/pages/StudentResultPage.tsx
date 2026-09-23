import { Link, useParams } from 'react-router-dom'

import { PaperImage } from '@/components/Paper'
import { FeedbackView } from '@/components/FeedbackEditor'
import { MathText } from '@/components/MathText'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  CardSkeleton,
  EmptyState,
  PageHeader,
  StatusPill,
} from '@/components/ui/feedback'
import { useSubmissionAnswers, useSubmissionGrades } from '@/lib/queries'

/**
 * A student's own result, on its own page.
 *
 * This used to unfold inside the assignment row on the course page,
 * which meant a mark, a comment and a full worked solution for every
 * part were pushed into a list item sitting beside every other
 * assignment. Reading your result is its own task and deserves its own
 * screen — and a page can be linked to, reloaded and kept open.
 */
/** Crops are stored as absolute URLs; AuthedImage wants the API path
 *  so it can attach the bearer token. */
function cropPath(cropUrl: string): string {
  const idx = cropUrl.indexOf('/api/')
  return idx >= 0 ? cropUrl.slice(idx + 4) : cropUrl
}

export function StudentResultPage() {
  const { submissionId = '' } = useParams()
  const { data, isLoading, error } = useSubmissionGrades(submissionId)
  // The crops themselves are refused until the marks are released, so
  // this is only ever asked for a result the student is allowed to see.
  const { data: answers } = useSubmissionAnswers(submissionId)

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

      {data.grades.map((g) => {
        const mine = answers?.answer_boxes.find((b) => b.answer_box_id === g.answer_box_id)
        return (
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
            {/* What was actually marked. A student told they lost two
                marks has no way to check that against their own
                working unless they can see the piece of it the marking
                was done on — and if the wrong part of the page was
                cropped, this is where they would notice. */}
            {mine && mine.parts.length > 0 && (
              <div className="space-y-2">
                {mine.parts.map((part) => (
                  <PaperImage
                    key={`${part.part}-${part.crop_url}`}
                    kind="student"
                    path={cropPath(part.crop_url)}
                    alt={`Your answer to ${g.label || `part ${g.order_index + 1}`}`}
                    caption={
                      mine.parts.length > 1
                        ? `Your answer — part ${part.part + 1} of ${mine.parts.length}`
                        : 'Your answer'
                    }
                  />
                ))}
              </div>
            )}

            {g.feedback && (
              <div className="rounded-lg bg-muted/60 p-3 text-sm">
                {/* Only claim the teacher wrote it when they did. The
                    merged field falls back to the model's words, and
                    attributing those to a person is a small lie a
                    student could catch. */}
                <p className="mb-1 text-xs font-medium text-muted-foreground">
                  {g.override_feedback ? "Your teacher's comment" : 'Comment on your answer'}
                </p>
                {/* Written as a document where the teacher wrote one,
                    so the equations are set rather than described. The
                    flattened text is what everything else falls back
                    to, including a comment the model wrote. */}
                {g.override_feedback_doc ? (
                  <FeedbackView doc={g.override_feedback_doc} />
                ) : (
                  <MathText text={g.feedback} />
                )}
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
        )
      })}
    </div>
  )
}
