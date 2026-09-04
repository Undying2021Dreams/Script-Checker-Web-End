import { useNavigate } from 'react-router-dom'
import { toast } from 'sonner'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { useCourseQuestions, useCreateQuestion } from '@/lib/queries'

export function QuestionsCard({ courseId }: { courseId: string }) {
  const navigate = useNavigate()
  const { data: questions, isLoading, error } = useCourseQuestions(courseId)
  const createQuestion = useCreateQuestion(courseId)

  const handleCreate = async () => {
    try {
      const q = await createQuestion.mutateAsync()
      navigate(`/questions/${q.question_id}`)
    } catch (err) {
      toast.error((err as Error).message)
    }
  }

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between">
        <CardTitle className="text-base">Questions</CardTitle>
        <Button size="sm" onClick={handleCreate} disabled={createQuestion.isPending}>
          {createQuestion.isPending ? 'Creating…' : 'New question'}
        </Button>
      </CardHeader>
      <CardContent className="space-y-2">
        {isLoading && <p className="text-sm text-muted-foreground">Loading…</p>}
        {error && <p className="text-sm text-destructive">{(error as Error).message}</p>}
        {questions?.length === 0 && (
          <p className="text-sm text-muted-foreground">
            No questions yet. Create one to write the paper and print it for students.
          </p>
        )}

        {questions?.map((q) => {
          const marks = q.answer_boxes.reduce((sum, b) => sum + b.points, 0)
          return (
            <button
              key={q.question_id}
              onClick={() => navigate(`/questions/${q.question_id}`)}
              className="flex w-full items-center justify-between rounded-md border px-3 py-2 text-left text-sm hover:bg-muted"
            >
              <span className="flex items-center gap-2">
                <span className={q.title ? 'font-medium' : 'text-muted-foreground'}>
                  {q.title || 'Untitled paper'}
                </span>
                <Badge variant={q.state === 'finalized' ? 'secondary' : 'outline'}>{q.state}</Badge>
              </span>
              <span className="text-muted-foreground">
                {q.answer_boxes.length} box(es) · {marks} marks
                {q.page_count ? ` · ${q.page_count} page(s)` : ''}
              </span>
            </button>
          )
        })}
      </CardContent>
    </Card>
  )
}
