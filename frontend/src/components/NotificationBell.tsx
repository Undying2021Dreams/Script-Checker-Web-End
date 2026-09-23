import { useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { Button } from '@/components/ui/button'
import { useMarkNotificationsRead, useNotifications } from '@/lib/queries'
import type { NotificationItem } from '@/lib/types'

/**
 * What has happened since you last looked.
 *
 * The only thing in the application that is about events rather than
 * state, which is why it is also the only thing polled on a timer: a
 * released mark looks the same whether it arrived a minute ago or last
 * term, so there is nothing in the current state of a page to notice.
 *
 * Reading one clears it and takes you to the thing it is about. Marks
 * on the panel as a whole are read when the panel is opened, because a
 * count you have already seen is noise.
 */
export function NotificationBell() {
  const [open, setOpen] = useState(false)
  const navigate = useNavigate()
  const { data } = useNotifications()
  const markRead = useMarkNotificationsRead()

  const unread = data?.unread ?? 0
  const items = data?.items ?? []

  const openItem = (item: NotificationItem) => {
    setOpen(false)
    if (!item.read) markRead.mutate(item.id)
    if (item.link) navigate(item.link)
  }

  return (
    <div className="relative">
      <Button
        variant="ghost"
        size="sm"
        aria-label={unread ? `${unread} unread notifications` : 'Notifications'}
        onClick={() => setOpen((v) => !v)}
        className="relative px-2"
      >
        <svg
          viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"
          className="size-5" aria-hidden="true"
        >
          <path d="M18 8a6 6 0 1 0-12 0c0 7-3 8-3 8h18s-3-1-3-8" strokeLinecap="round" strokeLinejoin="round" />
          <path d="M13.7 21a2 2 0 0 1-3.4 0" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
        {unread > 0 && (
          <span className="absolute -right-0.5 -top-0.5 flex min-w-4 items-center justify-center rounded-full bg-destructive px-1 text-[10px] font-semibold text-white">
            {unread > 9 ? '9+' : unread}
          </span>
        )}
      </Button>

      {open && (
        <>
          {/* Clicking anywhere else closes it — a panel you cannot
              dismiss without finding the button again is worse than no
              panel. */}
          <button
            aria-hidden="true" tabIndex={-1}
            className="fixed inset-0 z-40 cursor-default"
            onClick={() => setOpen(false)}
          />
          <div className="absolute right-0 z-50 mt-1 w-80 max-w-[90vw] overflow-hidden rounded-lg border bg-card shadow-lg">
            <div className="flex items-center justify-between gap-2 border-b px-3 py-2">
              <span className="text-sm font-medium">Notifications</span>
              {unread > 0 && (
                <button
                  onClick={() => markRead.mutate(undefined)}
                  className="text-xs text-muted-foreground underline-offset-2 hover:underline"
                >
                  Mark all read
                </button>
              )}
            </div>

            <div className="max-h-80 overflow-y-auto">
              {items.length === 0 && (
                <p className="px-3 py-6 text-center text-sm text-muted-foreground">
                  Nothing yet.
                </p>
              )}
              {items.map((item) => (
                <button
                  key={item.id}
                  onClick={() => openItem(item)}
                  className={`block w-full border-b px-3 py-2 text-left text-sm last:border-b-0 hover:bg-muted ${
                    item.read ? 'opacity-60' : ''
                  }`}
                >
                  <span className="flex items-start gap-2">
                    {!item.read && (
                      <span className="mt-1.5 size-1.5 shrink-0 rounded-full bg-primary" />
                    )}
                    <span className="min-w-0">
                      <span className="block font-medium">{item.title}</span>
                      {item.body && (
                        <span className="block truncate text-xs text-muted-foreground">
                          {item.body}
                        </span>
                      )}
                      <span className="block text-xs text-muted-foreground">
                        {new Date(item.created_at).toLocaleString()}
                      </span>
                    </span>
                  </span>
                </button>
              ))}
            </div>
          </div>
        </>
      )}
    </div>
  )
}
