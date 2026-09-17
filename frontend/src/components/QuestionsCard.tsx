import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { toast } from 'sonner'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Pending } from '@/components/ui/feedback'
import { openAuthedPdf } from '@/lib/pdf'
import { useCourseQuestions, useCreateQuestion } from '@/lib/queries'
import type { Question } from '@/lib/types'


/**
 * One paper in the course list.
 *
 * A finalized paper can be opened from here rather than only from
 * inside its editor. A student has that button in their own list, and
 * a teacher printing a stack of papers was the one person who had to
 * go through a page to reach it.
 */
function QuestionRow({ question }: { question: Question }) {
  const navigate = useNavigate()
  const [opening, setOpening] = useState(false)
  const marks = question.answer_boxes.reduce((sum, b) => sum + (b.points ?? 0), 0)
  const isFinalized = question.state === 'finalized'

  const openPdf = async () => {
    if (opening) return
    setOpening(true)
    try {
      const name = `${question.title || 'paper'}.pdf`.replace(/[/\\]/g, '-')
      const how = await openAuthedPdf(`/questions/${question.question_id}/pdf`, name)
      if (how === 'download') {
        toast.success('Your browser blocked the new tab, so the PDF was saved instead.')
      }
    } catch (err) {
      toast.error(`Could not open the PDF: ${(err as Error).message}`)
    } finally {
      setOpening(false)
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-2 rounded-md border px-3 py-2 text-sm">
      <button
        onClick={() => navigate(`/questions/${question.question_id}`)}
        className="flex min-w-0 flex-1 flex-wrap items-center justify-between gap-2 text-left hover:underline"
      >
        <span className="flex items-center gap-2">
          <span className={question.title ? 'font-medium' : 'text-muted-foreground'}>
            {question.title || 'Untitled paper'}
          </span>
          <Badge variant={isFinalized ? 'secondary' : 'outline'}>{question.state}</Badge>
        </span>
        <span className="text-muted-foreground">
          {question.answer_boxes.length} box(es) · {marks} marks
          {question.page_count ? ` · ${question.page_count} page(s)` : ''}
        </span>
      </button>

      {isFinalized && (
        <Button size="sm" variant="outline" onClick={openPdf} disabled={opening}>
          {opening ? <Pending>Opening…</Pending> : 'Open PDF'}
        </Button>
      )}
    </div>
  )
}

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

        {questions?.map((q) => (
          <QuestionRow key={q.question_id} question={q} />
        ))}
      </CardContent>
    </Card>
  )
}
