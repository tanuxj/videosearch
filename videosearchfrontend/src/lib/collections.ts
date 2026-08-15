import { useCallback, useEffect, useState } from 'react'
import { API_ENABLED, apiFetch } from './http'

/**
 * Collections: user-made groupings of videos.
 *
 * Many-to-many by design — a video can sit in "Lectures" and "To review" at
 * once — so the same feature reads as folders or as tags depending on how the
 * user files things.
 *
 * Server-only, like saved clips: demo mode (no `VITE_API_URL`) has no
 * collections and the UI hides the rail rather than keeping a second
 * localStorage implementation in sync with the real one.
 */

export type Collection = {
  id: string
  name: string
  /** How many videos are filed here — shown next to the name in the rail. */
  videoCount: number
  createdAt: string
}

/** Backend `CollectionOut` shape (snake_case). */
type ApiCollection = {
  id: string
  name: string
  video_count: number
  created_at: string
}

function toCollection(item: ApiCollection): Collection {
  return {
    id: item.id,
    name: item.name,
    videoCount: item.video_count,
    createdAt: item.created_at,
  }
}

/** Notifies every `useCollections` mount that the list changed. */
const listeners = new Set<() => void>()

function emit(): void {
  for (const listener of listeners) listener()
}

/** Every collection the user owns, A–Z. Empty in demo mode. */
export async function listCollections(): Promise<Collection[]> {
  if (!API_ENABLED) return []
  const data = await apiFetch<{ items: ApiCollection[] }>('/api/v1/collections')
  return data.items.map(toCollection)
}

export async function createCollection(name: string): Promise<Collection> {
  const data = await apiFetch<ApiCollection>('/api/v1/collections', {
    method: 'POST',
    body: JSON.stringify({ name }),
  })
  emit()
  return toCollection(data)
}

export async function renameCollection(id: string, name: string): Promise<Collection> {
  const data = await apiFetch<ApiCollection>(`/api/v1/collections/${id}`, {
    method: 'PATCH',
    body: JSON.stringify({ name }),
  })
  emit()
  return toCollection(data)
}

/** Delete the collection. The videos inside it stay in the library. */
export async function deleteCollection(id: string): Promise<void> {
  await apiFetch<unknown>(`/api/v1/collections/${id}`, { method: 'DELETE' })
  emit()
}

/**
 * File videos into a collection. Idempotent — re-adding a video already in it
 * is a no-op server-side, so callers can send a whole selection blind.
 */
export async function addVideosToCollection(
  id: string,
  videoIds: string[],
): Promise<number> {
  if (videoIds.length === 0) return 0
  const data = await apiFetch<{ count: number }>(`/api/v1/collections/${id}/videos`, {
    method: 'POST',
    body: JSON.stringify({ video_ids: videoIds }),
  })
  emit()
  return data.count
}

/** Unfile videos from a collection. The videos themselves are untouched. */
export async function removeVideosFromCollection(
  id: string,
  videoIds: string[],
): Promise<number> {
  if (videoIds.length === 0) return 0
  const data = await apiFetch<{ count: number }>(
    `/api/v1/collections/${id}/videos/remove`,
    {
      method: 'POST',
      body: JSON.stringify({ video_ids: videoIds }),
    },
  )
  emit()
  return data.count
}

/**
 * Live view of the user's collections.
 *
 * No polling: unlike indexing progress, collections only change when this user
 * changes them, so a mutation-driven `emit()` is enough. `refresh` is returned
 * for the rare case a caller needs to force one (e.g. after a bulk upload that
 * filed new videos).
 */
export function useCollections(): {
  collections: Collection[]
  refresh: () => void
  loading: boolean
} {
  const [collections, setCollections] = useState<Collection[]>([])
  const [loading, setLoading] = useState(API_ENABLED)

  const refresh = useCallback(() => {
    if (!API_ENABLED) {
      setCollections([])
      setLoading(false)
      return
    }
    void listCollections()
      .then(setCollections)
      // A transient failure leaves the last good list on screen rather than
      // blanking the rail — the next mutation or mount retries.
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    refresh()
    listeners.add(refresh)
    return () => {
      listeners.delete(refresh)
    }
  }, [refresh])

  return { collections, refresh, loading }
}
