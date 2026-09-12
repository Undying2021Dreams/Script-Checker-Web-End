import { useState } from 'react'
import { Link } from 'react-router-dom'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { CardSkeleton, EmptyState, Pending } from '@/components/ui/feedback'
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

export function CoursesPage() {
  const { data: me } = useMe()
  const { data: courses, isLoading, error } = useMyCourses()
  const isTeacher = me?.role === 'teacher' || me?.role === 'admin'

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">My courses</h1>
        {me && (isTeacher ? <CreateCourseDialog /> : <JoinCourseDialog />)}
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
          title={isTeacher ? 'No courses yet' : 'You haven’t joined any courses yet'}
          hint={
            isTeacher
              ? 'Create one to get a join code you can give your students.'
              : 'Ask your teacher for a join code, or search for a course.'
          }
        />
      )}

      <div className="grid gap-4 sm:grid-cols-2">
        {courses?.map((course) => (
          <Card key={course.id}>
            <CardHeader>
              <CardTitle>
                <Link to={`/courses/${course.id}`} className="hover:underline">
                  {course.title}
                </Link>
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-1 text-sm text-muted-foreground">
              <p>{isTeacher ? `${course.student_count} enrolled` : course.teacher_name}</p>
              {isTeacher && (
                <p>
                  Join code: <span className="font-mono tracking-widest">{course.join_code}</span>
                </p>
              )}
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  )
}
