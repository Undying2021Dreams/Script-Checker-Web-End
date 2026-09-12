import { Link, useParams } from 'react-router-dom'
import { toast } from 'sonner'

import { AssignmentsCard } from '@/components/AssignmentsCard'
import { LeaderboardCard } from '@/components/LeaderboardCard'
import { QuestionsCard } from '@/components/QuestionsCard'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { useCourse, useMe, useRemoveStudent, useRoster } from '@/lib/queries'

export function CourseDetailPage() {
  const { courseId = '' } = useParams()
  const { data: me } = useMe()
  const { data: course, isLoading, error } = useCourse(courseId)

  const isTeacher = !!me && !!course && (course.teacher_id === me.id || me.role === 'admin')
  const { data: roster } = useRoster(courseId, isTeacher)
  const removeStudent = useRemoveStudent(courseId)

  const remove = async (studentId: string, name: string) => {
    try {
      await removeStudent.mutateAsync(studentId)
      toast.success(`Removed ${name}`)
    } catch (err) {
      toast.error((err as Error).message)
    }
  }

  if (isLoading) return <p className="text-muted-foreground">Loading…</p>
  if (error) return <p className="text-destructive">{(error as Error).message}</p>
  if (!course) return null

  return (
    <div className="space-y-6">
      <div>
        <Link to="/" className="text-sm text-muted-foreground hover:underline">
          ← My courses
        </Link>
        <div className="mt-2 flex flex-wrap items-center justify-between gap-3">
          <h1 className="text-2xl font-semibold">{course.title}</h1>
          {isTeacher && (
            <Button variant="outline" size="sm" render={<Link to={`/courses/${courseId}/gradebook`}>Gradebook</Link>} nativeButton={false} />
          )}
        </div>
        <p className="text-sm text-muted-foreground">
          {course.teacher_name} · {course.student_count} enrolled
        </p>
      </div>

      {isTeacher && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Join code</CardTitle>
          </CardHeader>
          <CardContent className="flex items-center gap-3">
            <span className="font-mono text-2xl tracking-widest">{course.join_code}</span>
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                navigator.clipboard.writeText(course.join_code)
                toast.success('Join code copied')
              }}
            >
              Copy
            </Button>
          </CardContent>
        </Card>
      )}

      {isTeacher && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Students</CardTitle>
          </CardHeader>
          <CardContent>
            {roster?.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                Nobody has joined yet. Share the join code above.
              </p>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Name</TableHead>
                    <TableHead>Email</TableHead>
                    <TableHead className="w-0" />
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {roster?.map((student) => (
                    <TableRow key={student.id}>
                      <TableCell>{student.display_name}</TableCell>
                      <TableCell className="text-muted-foreground">{student.email}</TableCell>
                      <TableCell>
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => remove(student.id, student.display_name)}
                        >
                          Remove
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>
      )}

      {isTeacher ? (
        <QuestionsCard courseId={courseId} />
      ) : (
        <AssignmentsCard courseId={courseId} enabled={!!me} />
      )}

      <LeaderboardCard courseId={courseId} enabled={!!me} />
    </div>
  )
}
