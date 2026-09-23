import { useState } from 'react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Pending, StatusPill } from '@/components/ui/feedback'
import { useCourseSearch, usePopularCourses, useRequestToJoin } from '@/lib/queries'
import type { CourseSummary } from '@/lib/types'

function CourseRow({ course }: { course: CourseSummary }) {
  const request = useRequestToJoin()

  const ask = async () => {
    try {
      await request.mutateAsync(course.id)
      toast.success('Asked to join — your teacher will decide')
    } catch (err) {
      toast.error((err as Error).message)
    }
  }

  return (
    <Card>
      <CardContent className="flex flex-wrap items-center justify-between gap-3 py-4">
        <div className="min-w-0">
          <p className="truncate font-medium">{course.title}</p>
          <p className="truncate text-sm text-muted-foreground">{course.teacher_name}</p>
        </div>

        <div className="flex items-center gap-2">
          <StatusPill>{course.student_count} enrolled</StatusPill>

          {/* The search result already says where you stand, so this
              knows what to offer without asking the server again. */}
          {course.my_status === 'teaching' && <StatusPill tone="info">You teach this</StatusPill>}
          {course.my_status === 'enrolled' && <StatusPill tone="success">You're in</StatusPill>}
          {course.my_status === 'pending' && <StatusPill tone="warning">Asked</StatusPill>}
          {(course.my_status === 'none' || course.my_status === 'declined') && (
            <Button size="sm" variant="outline" onClick={ask} disabled={request.isPending}>
              {request.isPending ? (
                <Pending>Asking…</Pending>
              ) : course.my_status === 'declined' ? (
                'Ask again'
              ) : (
                'Request to join'
              )}
            </Button>
          )}
        </div>
      </CardContent>
    </Card>
  )
}

export function SearchPage() {
  const [term, setTerm] = useState('')
  const { data: results, isFetching, error } = useCourseSearch(term)
  const { data: popular } = usePopularCourses()

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold">Find a course</h1>

      <div className="space-y-2">
        <Label htmlFor="search">Search by course title or teacher</Label>
        <Input
          id="search"
          value={term}
          onChange={(e) => setTerm(e.target.value)}
          placeholder="e.g. Numerical Methods, or a teacher's name"
        />
        <p className="text-xs text-muted-foreground">
          To enrol you still need the join code from the teacher.
        </p>
      </div>

      {error && <p className="text-destructive">{(error as Error).message}</p>}
      {isFetching && <p className="text-muted-foreground">Searching…</p>}
      {results?.length === 0 && !isFetching && (
        <p className="text-muted-foreground">No courses matched “{term}”.</p>
      )}

      <div className="space-y-3">
        {results?.map((course) => (
          <CourseRow key={course.id} course={course} />
        ))}
      </div>

      {/* Arriving here with nothing to search for is the common case —
          a student sent a link, with no join code and no course name in
          mind. An empty box is a dead end; the busiest courses are at
          least somewhere to start. Enrolment counts only, nothing
          derived from anyone's marks. */}
      {!term.trim() && (popular?.length ?? 0) > 0 && (
        <section className="space-y-3">
          <h2 className="text-sm font-medium text-muted-foreground">Busiest courses</h2>
          <div className="space-y-3">
            {popular?.map((course) => (
              <CourseRow key={course.id} course={course} />
            ))}
          </div>
        </section>
      )}
    </div>
  )
}
