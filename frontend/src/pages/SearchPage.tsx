import { useState } from 'react'

import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useCourseSearch } from '@/lib/queries'

export function SearchPage() {
  const [term, setTerm] = useState('')
  const { data: results, isFetching, error } = useCourseSearch(term)

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
          <Card key={course.id}>
            <CardContent className="flex items-center justify-between py-4">
              <div>
                <p className="font-medium">{course.title}</p>
                <p className="text-sm text-muted-foreground">{course.teacher_name}</p>
              </div>
              <span className="text-sm text-muted-foreground">
                {course.student_count} enrolled
              </span>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  )
}
