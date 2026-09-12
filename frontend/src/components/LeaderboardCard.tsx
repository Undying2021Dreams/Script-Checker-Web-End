import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { EmptyState, Skeleton, StatusPill } from '@/components/ui/feedback'
import { useLeaderboard } from '@/lib/queries'
import { cn } from '@/lib/utils'

/**
 * How the course is going, and where you stand in it.
 *
 * Built only from released marks, and anonymous unless you teach the
 * course: a table of names beside scores publishes the standing of
 * whoever is at the bottom of it, and they did not ask for that. Your
 * own row is always yours to see, which is where the motivation comes
 * from anyway.
 */
export function LeaderboardCard({ courseId, enabled = true }: { courseId: string; enabled?: boolean }) {
  const { data, isLoading, error } = useLeaderboard(courseId, enabled)

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between gap-2 pb-3">
        <CardTitle className="text-base">Standings</CardTitle>
        {data && data.class_average != null && (
          <StatusPill tone="info">average {data.class_average}</StatusPill>
        )}
      </CardHeader>

      <CardContent className="space-y-2">
        {isLoading && (
          <>
            <Skeleton className="h-8 w-full" />
            <Skeleton className="h-8 w-full" />
          </>
        )}
        {error && <p className="text-sm text-destructive">{(error as Error).message}</p>}

        {data?.entries.length === 0 && (
          <EmptyState
            title="Nothing released yet"
            hint="Standings appear once marks have been released to students."
          />
        )}

        {data?.entries.map((e) => (
          <div
            key={e.rank}
            className={cn(
              'flex items-center gap-3 rounded-lg border px-3 py-2 text-sm',
              e.is_me && 'border-primary/40 bg-accent',
            )}
          >
            <span className="w-8 shrink-0 text-center font-medium tabular-nums text-muted-foreground">
              {e.rank}
            </span>
            <span className="min-w-0 flex-1 truncate">
              {e.display_name ?? <span className="text-muted-foreground">Another student</span>}
              {e.is_me && <span className="ml-2 text-xs text-primary">you</span>}
            </span>
            <span className="shrink-0 tabular-nums">
              {e.earned} / {e.max_score}
            </span>
          </div>
        ))}

        {data && !data.named && data.my_rank != null && (
          <p className="pt-1 text-xs text-muted-foreground">
            You're {data.my_rank} of {data.ranked}. Other students' names are hidden — only your
            own row is yours to see.
          </p>
        )}
      </CardContent>
    </Card>
  )
}
