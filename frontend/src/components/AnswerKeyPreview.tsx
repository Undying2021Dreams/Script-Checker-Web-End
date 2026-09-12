import { useState } from 'react'

import { AuthedImage } from '@/components/AuthedImage'
import { PaperSurface } from '@/components/Paper'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { useGroundTruthPreviews } from '@/lib/queries'

/**
 * What finalizing actually produced, per sub-question.
 *
 * This isn't decoration. The rendered model answer below is the exact
 * image handed to the grader as the answer key, so looking at it is how a
 * mis-rendered answer (a broken equation, an empty box) gets caught
 * before it quietly produces wrong marks for a whole class.
 */

interface Zoomed {
  path: string
  title: string
}

function PreviewPane({
  label,
  imageId,
  pathPrefix,
  alt,
  kind,
  onZoom,
}: {
  label: string
  imageId: string | null | undefined
  pathPrefix: string
  alt: string
  kind: 'student' | 'model' | 'page'
  onZoom: (z: Zoomed) => void
}) {
  const path = imageId ? `${pathPrefix}/${imageId}` : null

  return (
    <div className="space-y-1">
      {path ? (
        <PaperSurface
          caption={label}
          kind={kind}
          actions={<span className="text-muted-foreground">click to enlarge</span>}
        >
          <button
            type="button"
            onClick={() => onZoom({ path, title: alt })}
            className="block w-full cursor-zoom-in transition hover:brightness-[0.98]"
            title="Click to enlarge"
          >
            <AuthedImage path={path} alt={alt} className="block w-full" />
          </button>
        </PaperSurface>
      ) : (
        <p className="text-sm text-muted-foreground">Not rendered</p>
      )}
    </div>
  )
}

export function AnswerKeyPreview({ questionId, enabled }: { questionId: string; enabled: boolean }) {
  const { data: boxes, isLoading, error } = useGroundTruthPreviews(questionId, enabled)
  const [zoomed, setZoomed] = useState<Zoomed | null>(null)

  if (!enabled) return null

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Answer key, as rendered</CardTitle>
        <p className="text-sm text-muted-foreground">
          These images are what the grader compares each student's answer against. Click either to
          enlarge.
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

        {boxes?.map((box, i) => {
          const name = box.label || `Part ${i + 1}`
          return (
            <div key={box.id} className="space-y-3">
              <div className="flex items-center gap-2">
                <span className="text-sm font-medium">{name}</span>
                {!box.image_id && (
                  // An empty render means the grader gets no answer key for
                  // this part and will flag it for manual marking.
                  <Badge variant="destructive">Nothing rendered</Badge>
                )}
              </div>

              <div className="grid gap-4 md:grid-cols-2">
                <PreviewPane
                  label="The question, as the student sees it"
                  kind="page"
                  imageId={box.question_image_id}
                  pathPrefix="/questions/question-images"
                  alt={`Question — ${name}`}
                  onZoom={setZoomed}
                />
                <PreviewPane
                  label="Model answer, with the marking scheme"
                  kind="model"
                  imageId={box.image_id}
                  pathPrefix="/questions/ground-truth-images"
                  alt={`Model answer — ${name}`}
                  onZoom={setZoomed}
                />
              </div>
            </div>
          )
        })}
      </CardContent>

      <Dialog open={!!zoomed} onOpenChange={(open) => !open && setZoomed(null)}>
        <DialogContent className="max-h-[90vh] overflow-auto sm:max-w-4xl">
          <DialogHeader>
            <DialogTitle>{zoomed?.title}</DialogTitle>
          </DialogHeader>
          {zoomed && (
            <AuthedImage
              path={zoomed.path}
              alt={zoomed.title}
              className="w-full rounded border bg-white"
            />
          )}
        </DialogContent>
      </Dialog>
    </Card>
  )
}
