import { toast } from 'sonner'

import { Avatar } from '@/components/Avatar'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Pending, StatusPill } from '@/components/ui/feedback'
import { useDecideJoinRequest, useJoinRequests } from '@/lib/queries'

/**
 * Students waiting to be let into a course.
 *
 * Hidden entirely when nobody is waiting. A card that is empty most of
 * the time trains a teacher to stop looking at it, which is the
 * opposite of what a queue is for.
 */
export function JoinRequestsCard({ courseId, isTeacher }: { courseId: string; isTeacher: boolean }) {
  const { data: requests } = useJoinRequests(courseId, isTeacher)
  const decide = useDecideJoinRequest(courseId)

  if (!isTeacher || !requests || requests.length === 0) return null

  const answer = async (requestId: string, approve: boolean, who: string) => {
    try {
      await decide.mutateAsync({ requestId, approve })
      toast.success(approve ? `${who} added to the course` : `Turned ${who} down`)
    } catch (err) {
      toast.error((err as Error).message)
    }
  }

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between gap-2 pb-3">
        <CardTitle className="text-base">Asking to join</CardTitle>
        <StatusPill tone="warning">{requests.length} waiting</StatusPill>
      </CardHeader>
      <CardContent className="space-y-2">
        {requests.map((r) => (
          <div
            key={r.id}
            className="flex flex-wrap items-center gap-3 rounded-md border px-3 py-2 text-sm"
          >
            <Avatar userId={r.student_id} name={r.student_name} hasPicture={false} size={32} />
            <div className="min-w-0 flex-1">
              <p className="truncate font-medium">{r.student_name}</p>
              <p className="truncate text-xs text-muted-foreground">{r.student_email}</p>
            </div>
            <div className="flex gap-2">
              <Button
                size="sm" variant="outline" disabled={decide.isPending}
                onClick={() => answer(r.id, false, r.student_name)}
              >
                Decline
              </Button>
              <Button
                size="sm" disabled={decide.isPending}
                onClick={() => answer(r.id, true, r.student_name)}
              >
                {decide.isPending ? <Pending>Adding…</Pending> : 'Let them in'}
              </Button>
            </div>
          </div>
        ))}
      </CardContent>
    </Card>
  )
}
