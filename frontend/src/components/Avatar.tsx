import { AuthedImage } from '@/components/AuthedImage'
import { useMe } from '@/lib/queries'

/**
 * A person's face, or their initials.
 *
 * The API says whether a picture exists, so the fallback is chosen
 * before any request rather than by letting an image fail — a broken
 * image icon beside somebody's name looks like the system lost
 * something.
 *
 * Fetched rather than linked, because the endpoint wants a bearer
 * token like every other image here.
 */
export function Avatar({
  userId,
  name,
  hasPicture,
  size = 32,
}: {
  userId: string
  name: string
  hasPicture: boolean
  size?: number
}) {
  const initials = name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? '')
    .join('')

  if (!hasPicture) {
    return (
      <span
        className="inline-flex shrink-0 items-center justify-center rounded-full bg-muted font-medium text-muted-foreground"
        style={{ width: size, height: size, fontSize: size * 0.4 }}
        aria-hidden="true"
      >
        {initials || '?'}
      </span>
    )
  }

  return (
    <span
      className="inline-block shrink-0 overflow-hidden rounded-full bg-muted"
      style={{ width: size, height: size }}
    >
      <AuthedImage path={`/users/${userId}/avatar`} className="size-full object-cover" />
    </span>
  )
}

/** The signed-in person's own face, for the header. */
export function MyAvatar({ size = 28 }: { size?: number }) {
  const { data: me } = useMe()
  if (!me) return null
  return (
    <Avatar userId={me.id} name={me.display_name} hasPicture={me.has_avatar} size={size} />
  )
}
