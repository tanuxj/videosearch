import { useCallback, useEffect, useState } from 'react'
import { API_ENABLED, ApiError, apiFetch, getAccessToken, url } from './http'

/**
 * Video library.
 *
 * Two backends behind one interface:
 *
 * * **Server mode** (`VITE_API_URL` set) — videos live in Postgres, files in
 *   R2/local disk. `useVideos` lists via `GET /api/v1/videos` and keeps
 *   polling while any video is still `processing` so the real indexing
 *   progress shows up live. Playback is an object URL from the authenticated
 *   stream endpoint (fetched once per session, cached here).
 * * **Demo mode** (no backend) — metadata persists per user in localStorage
 *   and playback needs the original `File` handle, which only survives the
 *   current tab session.
 */

export type VideoStatus = 'processing' | 'ready' | 'failed'

export type VideoRecord = {
  id: string
  name: string
  sizeBytes: number
  duration: number
  frames: number
  status: VideoStatus
  createdAt: string
  /** Small JPEG data URL captured from the first seconds of the video. */
  poster?: string
  /** Server-side failure message (status === 'failed'). */
  error?: string
}

/** Backend `VideoOut` shape (snake_case) — mapped to `VideoRecord` below. */
type ApiVideo = {
  id: string
  name: string
  size_bytes: number
  duration_seconds: number | null
  status: VideoStatus
  error: string | null
  frames_total: number
  frames_indexed: number
  created_at: string
}

const objectUrls = new Map<string, string>()
const listeners = new Set<() => void>()

// While any video is still processing, re-poll the server this often so the
// dashboard/search pages show live indexing progress.
const POLL_MS = 3000

function key(userId: string): string {
  return `vs.videos.${userId}`
}

function emit(): void {
  for (const listener of listeners) listener()
}

/* ── Demo-mode localStorage persistence ──────────────────── */

function listLocal(userId: string): VideoRecord[] {
  try {
    const raw = localStorage.getItem(key(userId))
    const items = raw ? (JSON.parse(raw) as VideoRecord[]) : []
    return items.sort((a, b) => b.createdAt.localeCompare(a.createdAt))
  } catch {
    return []
  }
}

function writeLocal(userId: string, items: VideoRecord[]): void {
  try {
    localStorage.setItem(key(userId), JSON.stringify(items))
  } catch {
    // Quota exceeded — drop posters, they're the only heavy field.
    localStorage.setItem(
      key(userId),
      JSON.stringify(items.map(({ poster: _poster, ...rest }) => rest)),
    )
  }
  emit()
}

/* ── API mapping ─────────────────────────────────────────── */

function toRecord(video: ApiVideo): VideoRecord {
  return {
    id: video.id,
    name: video.name,
    sizeBytes: video.size_bytes,
    duration: video.duration_seconds ?? 0,
    frames: video.frames_indexed,
    status: video.status,
    createdAt: video.created_at,
    error: video.error ?? undefined,
  }
}

/* ── Public operations ───────────────────────────────────── */

/** Fetch the server's list of the user's videos, newest first. */
async function listApi(): Promise<VideoRecord[]> {
  const data = await apiFetch<{ items: ApiVideo[] }>('/api/v1/videos')
  return data.items
    .map(toRecord)
    .sort((a, b) => b.createdAt.localeCompare(a.createdAt))
}

export async function listVideos(userId: string): Promise<VideoRecord[]> {
  if (API_ENABLED) return listApi()
  return listLocal(userId)
}

/** Read a single video (used to poll indexing progress after an upload). */
export async function getVideo(videoId: string): Promise<VideoRecord | null> {
  if (!API_ENABLED) return null
  try {
    return toRecord(await apiFetch<ApiVideo>(`/api/v1/videos/${videoId}`))
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null
    throw error
  }
}

/**
 * Create a video on the server. The multipart body is sent directly (with the
 * bearer token) because `apiFetch` assumes JSON.
 */
export async function createVideoApi(
  file: File,
  onProgress?: (loaded: number, total: number) => void,
): Promise<VideoRecord> {
  const form = new FormData()
  form.append('file', file)

  const response = await fetch(url('/api/v1/videos'), {
    method: 'POST',
    credentials: 'include',
    headers: {
      ...(getAccessToken() ? { Authorization: `Bearer ${getAccessToken()}` } : {}),
    },
    body: form,
  })
  if (!response.ok) {
    throw new ApiError(response.status, await readError(response, 'Upload failed'))
  }
  const video = (await response.json()) as ApiVideo
  onProgress?.(file.size, file.size)
  return toRecord(video)
}

async function readError(response: Response, fallback: string): Promise<string> {
  try {
    const body = await response.json()
    const detail = body?.detail
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail) && detail[0]?.msg) return String(detail[0].msg)
  } catch {
    /* not JSON */
  }
  return fallback
}

export async function removeVideo(userId: string, videoId: string): Promise<void> {
  if (API_ENABLED) {
    await apiFetch(`/api/v1/videos/${videoId}`, { method: 'DELETE' })
  } else {
    writeLocal(
      userId,
      listLocal(userId).filter((item) => item.id !== videoId),
    )
  }
  revokeSource(videoId)
  emit()
}

export async function saveVideo(userId: string, video: VideoRecord): Promise<void> {
  if (API_ENABLED) {
    // The server owns the record — demo-mode persistence is a no-op.
    return
  }
  const items = listLocal(userId).filter((item) => item.id !== video.id)
  writeLocal(userId, [video, ...items])
}

/* ── Playback sources ────────────────────────────────────── */

export function attachSource(videoId: string, file: File): string {
  const previous = objectUrls.get(videoId)
  if (previous) URL.revokeObjectURL(previous)
  const url = URL.createObjectURL(file)
  objectUrls.set(videoId, url)
  return url
}

export function sourceFor(videoId: string): string | undefined {
  return objectUrls.get(videoId)
}

function revokeSource(videoId: string): void {
  const url = objectUrls.get(videoId)
  if (url) {
    URL.revokeObjectURL(url)
    objectUrls.delete(videoId)
  }
}

/**
 * A playable source for a server video.
 *
 * Prefers the signed edge URL served by the Cloudflare streaming Worker
 * (`worker: true`) — the browser streams it directly from the edge with
 * Range support, so no bytes touch the API. Falls back to downloading the
 * file once via the authenticated stream endpoint and caching a blob URL
 * for this tab session.
 */
export async function streamSourceFor(videoId: string): Promise<string> {
  const cached = objectUrls.get(videoId)
  if (cached) return cached

  let edgeUrl: string | null = null
  try {
    const data = await apiFetch<{ url: string; worker: boolean }>(
      `/api/v1/videos/${videoId}/stream-url`,
    )
    if (data.worker) edgeUrl = data.url
  } catch {
    // Older backend without stream-url — fall through to the blob path.
  }

  if (edgeUrl) {
    // Signed URLs are short-lived; mint a fresh one each time rather than
    // caching it for the whole session.
    return edgeUrl
  }

  const blob = await apiFetch<Blob>(`/api/v1/videos/${videoId}/stream`, {
    headers: { Accept: 'video/*' },
    parseBlob: true,
  })
  const blobUrl = URL.createObjectURL(blob)
  objectUrls.set(videoId, blobUrl)
  return blobUrl
}

/* ── Live library view ───────────────────────────────────── */

/**
 * Live view of the user's library; re-renders when videos change and, in
 * server mode, re-polls while anything is still indexing.
 */
export function useVideos(userId: string | undefined): VideoRecord[] {
  const [videos, setVideos] = useState<VideoRecord[]>([])
  const [refreshTick, setRefreshTick] = useState(0)

  const refresh = useCallback(() => {
    if (!userId) {
      setVideos([])
      return
    }
    void listVideos(userId)
      .then((items) => {
        setVideos(items)
        // If anything is still indexing, keep polling so status/progress move.
        if (items.some((video) => video.status === 'processing')) {
          window.setTimeout(() => setRefreshTick((tick) => tick + 1), POLL_MS)
        }
      })
      .catch(() => {
        // Transient network/refresh failure — keep the poll alive so the
        // dashboard recovers instead of freezing on stale data. The timeout
        // is scheduled regardless of success.
        window.setTimeout(() => setRefreshTick((tick) => tick + 1), POLL_MS)
      })
  }, [userId])

  useEffect(() => {
    refresh()
    listeners.add(refresh)
    window.addEventListener('storage', refresh)
    return () => {
      listeners.delete(refresh)
      window.removeEventListener('storage', refresh)
    }
  }, [refresh, refreshTick])

  return videos
}

/* ── Media helpers ──────────────────────────────────────── */

export function readVideoDuration(file: File): Promise<number> {
  return new Promise((resolve) => {
    const url = URL.createObjectURL(file)
    const el = document.createElement('video')
    el.preload = 'metadata'
    el.muted = true
    el.onloadedmetadata = () => {
      const duration = Number.isFinite(el.duration) ? el.duration : 0
      URL.revokeObjectURL(url)
      resolve(duration)
    }
    el.onerror = () => {
      URL.revokeObjectURL(url)
      resolve(0)
    }
    el.src = url
  })
}

/**
 * Grabs frames from a video URL at the given timestamps and returns JPEG data
 * URLs, keyed by timestamp. Missing entries simply mean the frame could not be
 * decoded (cross-origin source, unsupported codec) — callers fall back to a
 * placeholder.
 */
export function captureFrames(
  src: string,
  times: number[],
  width = 320,
): Promise<Map<number, string>> {
  return new Promise((resolve) => {
    const out = new Map<number, string>()
    if (!src || times.length === 0) {
      resolve(out)
      return
    }

    const el = document.createElement('video')
    el.preload = 'auto'
    el.muted = true
    el.crossOrigin = 'anonymous'
    el.playsInline = true

    const canvas = document.createElement('canvas')
    const ctx = canvas.getContext('2d')
    let index = 0
    let settled = false

    const finish = () => {
      if (settled) return
      settled = true
      el.removeAttribute('src')
      el.load()
      resolve(out)
    }

    const seekNext = () => {
      if (index >= times.length) {
        finish()
        return
      }
      const time = times[index]!
      const safe = Math.min(Math.max(time, 0), Math.max(el.duration - 0.05, 0))
      if (Math.abs(el.currentTime - safe) < 0.01) onSeeked()
      else el.currentTime = safe
    }

    const onSeeked = () => {
      if (!ctx) {
        finish()
        return
      }
      try {
        const ratio = el.videoHeight / el.videoWidth || 9 / 16
        canvas.width = width
        canvas.height = Math.round(width * ratio)
        ctx.drawImage(el, 0, 0, canvas.width, canvas.height)
        out.set(times[index]!, canvas.toDataURL('image/jpeg', 0.72))
      } catch {
        // Tainted canvas — skip this frame.
      }
      index += 1
      seekNext()
    }

    el.onloadeddata = seekNext
    el.onseeked = onSeeked
    el.onerror = finish
    // Never hang the UI on a stubborn decode.
    setTimeout(finish, 8000 + times.length * 400)
    el.src = src
  })
}
