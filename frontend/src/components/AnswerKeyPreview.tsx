import { AuthedImage } from '@/components/AuthedImage'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { useGroundTruthPreviews } from '@/lib/queries'

/**
 * What finalizing actually produced, per sub-question.
 *
 * This isn't decoration. The rendered model answer below is the exact
 * image handed to the grader as the answer key, so looking at it is how a
 * mis-rendered answer (a broken equation, an empty box) gets caught
 * before it quietly produces wrong marks for a whole class.
 */
export function AnswerKeyPreview({ questionId, enabled }: { questionId: string; enabled: boolean }) {
  const { data: boxes, isLoading, error } = useGroundTruthPreviews(questionId, enabled)

  if (!enabled) return null

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Answer key, as rendered</CardTitle>
        <p className="text-sm text-muted-foreground">
          These images are what the grader compares each student's answer against.
        </p>
      </CardHeader>

      <CardContent className="space-y-6">
        {isLoading && <p className="text-sm text-muted-foreground">Loading…</p>}
        {error && <p className="text-sm text-destructive">{(error as Error).message}</p>}
        {boxes?.length === 0 && (
          <p className="text-sm text-muted-foreground">
            This paper has no model answers, so nothing can be marked automatically. Add a model
            answer in the editor and finalize a fresh copy.
          </p>
        )}

        {boxes?.map((box, i) => (
          <div key={box.id} className="space-y-3">
            <div className="flex items-center gap-2">
              <span className="text-sm font-medium">
                {box.label || `Part ${i + 1}`}
              </span>
              {!box.image_id && (
                // An empty render means the grader gets no answer key for
                // this part and will flag it for manual marking.
                <Badge variant="destructive">Nothing rendered</Badge>
              )}
            </div>

            <div className="grid gap-4 md:grid-cols-2">
              <div className="space-y-1">
                <p className="text-xs text-muted-foreground">Question shown to the student</p>
                {box.question_image_id ? (
                  <AuthedImage
                    path={`/questions/question-images/${box.question_image_id}`}
                    alt={`Question for ${box.label}`}
                    className="w-full rounded border bg-white"
                  />
                ) : (
                  <p className="text-sm text-muted-foreground">Not rendered</p>
                )}
              </div>

              <div className="space-y-1">
                <p className="text-xs text-muted-foreground">Model answer</p>
                {box.image_id ? (
                  <AuthedImage
                    path={`/questions/ground-truth-images/${box.image_id}`}
                    alt={`Model answer for ${box.label}`}
                    className="w-full rounded border bg-white"
                  />
                ) : (
                  <p className="text-sm text-muted-foreground">Not rendered</p>
                )}
              </div>
            </div>
          </div>
        ))}
      </CardContent>
    </Card>
  )
}
