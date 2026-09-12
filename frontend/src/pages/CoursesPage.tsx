import { useState } from 'react'
import { Link } from 'react-router-dom'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { CardSkeleton, EmptyState, Pending, StatusPill } from '@/components/ui/feedback'
import type { Course } from '@/lib/types'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useCreateCourse, useJoinCourse, useMe, useMyCourses } from '@/lib/queries'

function CreateCourseDialog() {
  const [open, setOpen] = useState(false)
  const [title, setTitle] = useState('')
  const createCourse = useCreateCourse()

  const submit = async () => {
    try {
      const course = await createCourse.mutateAsync(title)
      toast.success(`Created "${course.title}" — join code ${course.join_code}`)
      setTitle('')
      setOpen(false)
    } catch (err) {
      toast.error((err as Error).message)
    }
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger render={<Button>Create course</Button>} />
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Create a course</DialogTitle>
          <DialogDescription>
            Students join with the code generated for this course.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-2">
          <Label htmlFor="course-title">Course title</Label>
          <Input
            id="course-title"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="e.g. Numerical Methods"
            onKeyDown={(e) => e.key === 'Enter' && title.trim() && submit()}
          />
        </div>
        <DialogFooter>
          <Button onClick={submit} disabled={!title.trim() || createCourse.isPending}>
            {createCourse.isPending ? <Pending>Creating…</Pending> : 'Create'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function JoinCourseDialog() {
  const [open, setOpen] = useState(false)
  const [code, setCode] = useState('')
  const joinCourse = useJoinCourse()

  const submit = async () => {
    try {
      const course = await joinCourse.mutateAsync(code)
      toast.success(`Joined "${course.title}"`)
      setCode('')
      setOpen(false)
    } catch (err) {
      toast.error((err as Error).message)
    }
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger render={<Button>Join a course</Button>} />
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Join a course</DialogTitle>
          <DialogDescription>Enter the code your teacher gave you.</DialogDescription>
        </DialogHeader>
        <div className="space-y-2">
          <Label htmlFor="join-code">Join code</Label>
          <Input
            id="join-code"
            value={code}
            onChange={(e) => setCode(e.target.value.toUpperCase())}
            placeholder="ABC123"
            className="font-mono tracking-widest"
            onKeyDown={(e) => e.key === 'Enter' && code.trim() && submit()}
          />
        </div>
        <DialogFooter>
          <Button onClick={submit} disabled={!code.trim() || joinCourse.isPending}>
            {joinCourse.isPending ? 'Joining…' : 'Join'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

/**
 * One card, told from the point of view the course puts you in.
 *
 * A teacher wants the join code and how many have enrolled; a student
 * wants to know whose course it is. Which of the two you are is a fact
 * about this course, not about you — the same person can be either, on
 * different rows of the same page.
 */
function CourseCard({ course }: { course: Course }) {
  const teaching = course.my_role === 'teacher'

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="flex items-start justify-between gap-2 text-base">
          <Link to={`/courses/${course.id}`} className="hover:underline">
            {course.title}
          </Link>
          <StatusPill tone={teaching ? 'success' : 'info'}>
            {teaching ? 'Teaching' : 'Taking'}
          </StatusPill>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-1 text-sm text-muted-foreground">
        {teaching ? (
          <>
            <p>{course.student_count} enrolled</p>
            <p>
              Join code: <span className="font-mono tracking-widest">{course.join_code}</span>
            </p>
          </>
        ) : (
          <p>Taught by {course.teacher_name}</p>
        )}
      </CardContent>
    </Card>
  )
}

export function CoursesPage() {
  const { data: me } = useMe()
  const { data: courses, isLoading, error } = useMyCourses()

  // The one permission that really is global: whether you may start a
  // course of your own. Everything else about being a teacher or a
  // student is decided per course.
  const canCreateCourses = me?.role === 'teacher' || me?.role === 'admin'

  const teaching = courses?.filter((c) => c.my_role === 'teacher') ?? []
  const taking = courses?.filter((c) => c.my_role === 'student') ?? []

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold tracking-tight">My courses</h1>
        {/* Both, always. Whoever teaches one course may be taking
            another, and offering only one of these was what made that
            impossible. */}
        {me && (
          <div className="flex items-center gap-2">
            {canCreateCourses && <CreateCourseDialog />}
            <JoinCourseDialog />
          </div>
        )}
      </div>

      {isLoading && (
        <div className="grid gap-4 sm:grid-cols-2">
          <CardSkeleton rows={2} />
          <CardSkeleton rows={2} />
        </div>
      )}
      {error && <p className="text-destructive">{(error as Error).message}</p>}

      {courses?.length === 0 && (
        <EmptyState
          title="Nothing here yet"
          hint={
            canCreateCourses
              ? 'Create a course to get a join code for your students, or join one with a code someone gave you.'
              : 'Ask your teacher for a join code, or search for a course.'
          }
        />
      )}

      {teaching.length > 0 && (
        <section className="space-y-3">
          <h2 className="text-sm font-medium text-muted-foreground">Courses I teach</h2>
          <div className="grid gap-4 sm:grid-cols-2">
            {teaching.map((course) => (
              <CourseCard key={course.id} course={course} />
            ))}
          </div>
        </section>
      )}

      {taking.length > 0 && (
        <section className="space-y-3">
          <h2 className="text-sm font-medium text-muted-foreground">Courses I'm taking</h2>
          <div className="grid gap-4 sm:grid-cols-2">
            {taking.map((course) => (
              <CourseCard key={course.id} course={course} />
            ))}
          </div>
        </section>
      )}
    </div>
  )
}
