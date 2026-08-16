import { useRef } from 'react'
import { useAuth } from '../lib/auth'
import { cn } from '../lib/cn'
import { relativeTime } from '../lib/format'
import { API_ENABLED } from '../lib/http'
import { useNotifications } from '../lib/notifications'
import { useNavigate } from '../lib/router'
import { BellIcon, CheckIcon } from './Icons'

/**
 * The bell in the app header: an unread badge over a `<details>` popover
 * listing "indexing finished" notifications.
 *
 * The pipeline runs server-side, so this rings even after the upload tab has
 * closed. Clicking a notification marks it read and opens the video in
 * search (`/search?v=<id>`), the same route the upload dialog's "Search this
 * video" button uses.
 */
export function NotificationBell() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const panelRef = useRef<HTMLDetailsElement>(null)
  const { items, unread, refresh, markRead, markAllRead } = useNotifications()

  // Hooks above run unconditionally; the bell itself is server-mode only.
  if (!API_ENABLED || !user) return null

  function openVideo(id: string, videoId: string): void {
    void markRead(id)
    // Closing the `<details>` before navigating keeps the panel from
    // re-opening on the next page's render.
    panelRef.current?.removeAttribute('open')
    navigate(`/search?v=${videoId}`)
  }

  return (
    <details ref={panelRef} className="relative">
      <summary
        onClick={() => void refresh()}
        aria-label={
          unread > 0
            ? `Notifications, ${unread} unread`
            : 'Notifications'
        }
        className="relative grid size-9 cursor-pointer list-none place-items-center rounded-lg border border-line text-ink-dim transition-colors hover:bg-surface-soft hover:text-ink [&_svg]:size-[18px] [&::-webkit-details-marker]:hidden"
      >
        <BellIcon />
        {unread > 0 && (
          <span className="absolute -top-1 -right-1 grid min-w-4 place-items-center rounded-full bg-danger px-1 text-[10px] leading-4 font-semibold text-white">
            {unread > 9 ? '9+' : unread}
          </span>
        )}
      </summary>

      <div className="absolute right-0 z-30 mt-1.5 w-80 rounded-xl border border-line bg-panel shadow-lg">
        <div className="flex items-center justify-between gap-2 border-b border-line px-3.5 py-2.5">
          <b className="text-[13px] font-semibold text-ink">Notifications</b>
          {unread > 0 && (
            <button
              type="button"
              onClick={() => void markAllRead()}
              className="flex items-center gap-1 text-[12px] font-medium text-brand transition-colors hover:text-brand-strong [&_svg]:size-3"
            >
              <CheckIcon />
              Mark all read
            </button>
          )}
        </div>

        <ul className="max-h-80 overflow-y-auto p-1.5">
          {items.length === 0 ? (
            <li className="px-3 py-7 text-center">
              <p className="text-[13px] font-medium text-ink">
                No notifications yet
              </p>
              <p className="mx-auto mt-1 max-w-[30ch] text-[12px] leading-relaxed text-ink-faint">
                When a video finishes indexing, it lands here — even if you
                closed the tab while it processed.
              </p>
            </li>
          ) : (
            items.map((item) => (
              <li key={item.id}>
                <button
                  type="button"
                  onClick={() => openVideo(item.id, item.videoId)}
                  className={cn(
                    'flex w-full items-start gap-2.5 rounded-lg px-2.5 py-2 text-left transition-colors',
                    item.read
                      ? 'hover:bg-surface-soft'
                      : 'bg-brand-wash hover:bg-brand-wash',
                  )}
                >
                  <span
                    className={cn(
                      'mt-1.5 size-2 shrink-0 rounded-full',
                      item.read ? 'bg-transparent' : 'bg-brand',
                    )}
                  />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-[13px] font-medium text-ink">
                      {item.videoName}
                    </span>
                    <span className="block text-[12px] text-ink-dim">
                      Finished indexing
                    </span>
                  </span>
                  <span className="mt-0.5 shrink-0 text-[11px] text-ink-faint">
                    {relativeTime(item.createdAt)}
                  </span>
                </button>
              </li>
            ))
          )}
        </ul>
      </div>
    </details>
  )
}
