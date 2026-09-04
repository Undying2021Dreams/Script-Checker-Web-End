import { Link, useNavigate, useParams } from 'react-router-dom'

import { Badge } from '@/components/ui/badge'
import { Card, CardContent } from '@/components/ui/card'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { useCourse, useGradebook } from '@/lib/queries'
import type { GradebookCell } from '@/lib/types'

function Cell({ cell, onOpen }: { cell: GradebookCell; onOpen: () => void }) {
  if (!cell.submission_id) {
    return <span className="text-muted-foreground">—</span>
  }

  const marked = cell.status === 'graded' && cell.earned != null

  return (
    <button
      type="button"
      onClick={onOpen}
      className="flex flex-col items-start gap-0.5 rounded px-1 py-0.5 text-left hover:bg-muted"
      title="Open this submission"
    >
      {marked ? (
        <span className="font-medium">
          {cell.earned} / {cell.max}
        </span>
      ) : (
        <span className="text-muted-foreground">
          {cell.status === 'queued' || cell.status === 'grading'
            ? 'marking…'
            : cell.status === 'failed'
              ? 'failed'
              : 'not marked'}
        </span>
      )}

      <span className="flex gap-1">
        {!!cell.needs_review_count && (
          <Badge variant="outline" className="px-1 py-0 text-[10px]">
            {cell.needs_review_count} to review
          </Badge>
        )}
        {marked && !cell.released && (
          // A mark the student can't see yet is worth surfacing here — it's
          // the difference between "marked" and "actually handed back".
          <Badge variant="outline" className="px-1 py-0 text-[10px]">
            unreleased
          </Badge>
        )}
      </span>
    </button>
  )
}

export function GradebookPage() {
  const { courseId = '' } = useParams()
  const navigate = useNavigate()
  const { data: course } = useCourse(courseId)
  const { data, isLoading, error } = useGradebook(courseId, true)

  if (isLoading) return <p className="text-muted-foreground">Loading…</p>
  if (error) return <p className="text-destructive">{(error as Error).message}</p>
  if (!data) return null

  const hasQuestions = data.questions.length > 0

  return (
    <div className="space-y-4">
      <div>
        <Link to={`/courses/${courseId}`} className="text-sm text-muted-foreground hover:underline">
          ← Back to course
        </Link>
        <h1 className="mt-1 text-xl font-semibold">Gradebook</h1>
        <p className="text-sm text-muted-foreground">
          {course?.title} · {data.rows.length} student(s) · {data.questions.length} paper(s)
        </p>
      </div>

      {!hasQuestions && (
        <Card>
          <CardContent className="py-10 text-center text-muted-foreground">
            No papers in this course yet.
          </CardContent>
        </Card>
      )}

      {data.rows.length === 0 && hasQuestions && (
        <Card>
          <CardContent className="py-10 text-center text-muted-foreground">
            Nobody has joined this course yet.
          </CardContent>
        </Card>
      )}

      {hasQuestions && data.rows.length > 0 && (
        // Wide tables scroll inside their own container rather than making
        // the whole page scroll sideways.
        <div className="overflow-x-auto rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="sticky left-0 bg-card">Student</TableHead>
                {data.questions.map((q, i) => (
                  <TableHead key={q.id} className="whitespace-nowrap">
                    Paper {i + 1}
                    <span className="ml-1 font-mono text-[10px] font-normal text-muted-foreground">
                      {q.id.slice(0, 6)}
                    </span>
                  </TableHead>
                ))}
                <TableHead className="whitespace-nowrap">Total</TableHead>
              </TableRow>
            </TableHeader>

            <TableBody>
              {data.rows.map((row) => {
                // Totalled from marked papers only — counting unmarked ones
                // as zero would misrepresent a student who simply hasn't
                // been marked yet.
                const marked = row.cells.filter((c) => c.status === 'graded' && c.earned != null)
                const earned = marked.reduce((sum, c) => sum + (c.earned ?? 0), 0)
                const outOf = marked.reduce((sum, c) => sum + (c.max ?? 0), 0)

                return (
                  <TableRow key={row.student_id}>
                    <TableCell className="sticky left-0 bg-card">
                      <div className="font-medium">{row.display_name}</div>
                      <div className="text-xs text-muted-foreground">{row.email}</div>
                    </TableCell>

                    {row.cells.map((cell) => (
                      <TableCell key={cell.question_id}>
                        <Cell
                          cell={cell}
                          onOpen={() => navigate(`/submissions/${cell.submission_id}`)}
                        />
                      </TableCell>
                    ))}

                    <TableCell className="whitespace-nowrap font-medium">
                      {marked.length ? `${earned} / ${outOf}` : '—'}
                    </TableCell>
                  </TableRow>
                )
              })}
            </TableBody>
          </Table>
        </div>
      )}

      <p className="text-xs text-muted-foreground">
        Totals count marked papers only, so a student who hasn't been marked yet isn't shown as
        having scored zero.
      </p>
    </div>
  )
}
