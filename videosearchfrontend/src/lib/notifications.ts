import { useCallback, useEffect, useRef, useState } from 'react'
import { useAuth } from './auth'
import { API_ENABLED, apiFetch } from './http'

/**
 * In-app notifications — today exactly one kind: `indexed`, written by the
 * backend pipeline when a video finishes indexing.
 *
 * Indexing runs server-side, so the bell polls rather than reacting to the
 * upload dialog: a video can settle minutes after the upload tab closed, and
 * the notification must still appear.
 */

export type AppNotification = {
  id: string
  kind: string
  read: boolean
  createdAt: string
  videoId: string
  videoName: string
}

type ApiNotification = {
  id: string
  kind: string
  read: boolean
  created_at: string
  video_id: string
  video_name: string
}

/** How often the bell re-checks the server for newly finished videos. */
const NOTIFY_POLL_MS = 15_000

function toNotification(item: ApiNotification): AppNotification {
  return {
    id: item.id,
    kind: item.kind,
    read: item.read,
    createdAt: item.created_at,
    videoId: item.video_id,
    videoName: item.video_name,
  }
}

export async function listNotifications(): Promise<{
  items: AppNotification[]
  unread: number
}> {
  const data = await apiFetch<{ items: ApiNotification[]; unread: number }>(
    '/api/v1/notifications',
  )
  return { items: data.items.map(toNotification), unread: data.unread }
}

export async function markNotificationRead(id: string): Promise<void> {
  await apiFetch(`/api/v1/notifications/${id}/read`, { method: 'POST' })
}

export async function markAllNotificationsRead(): Promise<void> {
  await apiFetch('/api/v1/notifications/read-all', { method: 'POST' })
}

/**
 * The bell's state: the notification list plus the unread badge count, kept
 * fresh by a background poll while the user is signed in.
 *
 * Marking read updates local state optimistically so the badge clears
 * instantly; the next poll reconciles if the request failed.
 */
export function useNotifications() {
  const { user } = useAuth()
  const [items, setItems] = useState<AppNotification[]>([])
  const [unread, setUnread] = useState(0)
  const timer = useRef<ReturnType<typeof setInterval> | undefined>(undefined)

  const refresh = useCallback(async () => {
    if (!API_ENABLED || !user) return
    try {
      const data = await listNotifications()
      setItems(data.items)
      setUnread(data.unread)
    } catch {
      // The bell is non-critical — a failed poll must never break the shell.
    }
  }, [user])

  useEffect(() => {
    if (!API_ENABLED || !user) {
      setItems([])
      setUnread(0)
      return
    }
    void refresh()
    timer.current = setInterval(() => void refresh(), NOTIFY_POLL_MS)
    return () => clearInterval(timer.current)
  }, [user, refresh])

  const markRead = useCallback(async (id: string) => {
    setItems((prev) =>
      prev.map((item) => (item.id === id ? { ...item, read: true } : item)),
    )
    setUnread((prev) => Math.max(0, prev - 1))
    try {
      await markNotificationRead(id)
    } catch {
      // Optimistic already — the next poll reconciles.
    }
  }, [])

  const markAllRead = useCallback(async () => {
    setItems((prev) => prev.map((item) => ({ ...item, read: true })))
    setUnread(0)
    try {
      await markAllNotificationsRead()
    } catch {
      // Optimistic already — the next poll reconciles.
    }
  }, [])

  return { items, unread, refresh, markRead, markAllRead }
}
