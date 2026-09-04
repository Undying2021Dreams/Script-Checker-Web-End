import { useEffect, useState } from 'react'

import { apiFetchBlobUrl } from '@/lib/api'

/**
 * An <img> for endpoints that require a bearer token.
 *
 * The browser sends no Authorization header when it loads an <img src>,
 * so anything served from our API (question figures, answer crops,
 * submission scans) comes back 401 and renders as a broken image. This
 * fetches the bytes properly and displays them as a blob URL, revoking it
 * on unmount so blobs don't accumulate as the user moves around.
 */
export function AuthedImage({
  path,
  alt = '',
  className,
}: {
  /** API path without the /api prefix, e.g. "/images/abc" */
  path: string
  alt?: string
  className?: string
}) {
  const [url, setUrl] = useState<string | null>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    let revoked = false
    let objectUrl: string | null = null

    setUrl(null)
    setFailed(false)

    apiFetchBlobUrl(path)
      .then((blobUrl) => {
        // The component may have unmounted (or the path changed) while the
        // fetch was in flight; revoke straight away rather than leaking.
        if (revoked) {
          URL.revokeObjectURL(blobUrl)
          return
        }
        objectUrl = blobUrl
        setUrl(blobUrl)
      })
      .catch(() => setFailed(true))

    return () => {
      revoked = true
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [path])

  if (failed) {
    return (
      <span className={`inline-block rounded border border-dashed px-2 py-1 text-xs text-muted-foreground ${className ?? ''}`}>
        Image unavailable
      </span>
    )
  }

  if (!url) {
    return <span className={`inline-block h-24 w-full animate-pulse rounded bg-muted ${className ?? ''}`} />
  }

  return <img src={url} alt={alt} className={className} />
}

/** Turns a stored absolute image URL into the API path AuthedImage wants. */
export function toApiPath(src: string): string | null {
  const match = src.match(/\/api(\/images\/[0-9a-fA-F-]{36})/)
  return match ? match[1] : null
}
