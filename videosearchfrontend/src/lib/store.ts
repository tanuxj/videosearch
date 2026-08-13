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
  /** Frames embedded so far — the numerator of indexing progress. */
  frames: number
  /**
   * Frames the backend expects to embed in total.
   *
   * Published before any embedding starts and re-projected as sampling
   * proceeds, so `frames / framesTotal` is real progress. 0 until the server
   * has probed the file.
   */
  framesTotal: number
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
    framesTotal: video.frames_total,
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

type PresignUpload = {
  video: ApiVideo
  upload_url: string | null
  expires_in: number
}

type CompleteUpload = {
  video: ApiVideo
  message: string
}

type MultipartPart = {
  part_number: number
  url: string
}

type PresignMultipart = {
  video: ApiVideo
  upload_id: string
  part_size: number
  parts: MultipartPart[]
  expires_in: number
}

// S3/R2 hard cap for a single PUT — files larger than this go through the
// chunked multipart flow (presigned per-part URLs) instead.
const SINGLE_PUT_LIMIT = 5 * 1024 * 1024 * 1024

/**
 * PUT a file (or chunk) to a presigned URL with real upload progress.
 *
 * `fetch` cannot report upload progress, so this uses XHR for the body
 * transfer only — the progress callback drives the dialog's progress bar
 * while the browser streams the bytes straight to R2. Resolves with the
 * object's ETag, which multipart completion needs.
 */
function putFile(
  url: string,
  file: Blob,
  onProgress?: (loaded: number, total: number) => void,
): Promise<string | null> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open('PUT', url)
    xhr.setRequestHeader('Content-Type', file.type || 'application/octet-stream')
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress?.(event.loaded, event.total)
    }
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(xhr.getResponseHeader('ETag'))
      } else {
        reject(new ApiError(xhr.status, `Upload to storage failed (${xhr.status})`))
      }
    }
    xhr.onerror = () => reject(new ApiError(0, 'Upload to storage failed — check your connection'))
    xhr.send(file)
  })
}

/**
 * Chunked upload of a file larger than the 5 GiB single-PUT cap.
 *
 * The API opens an S3/R2 multipart upload and returns one presigned PUT URL
 * per chunk; the browser slices the file, PUTs each chunk straight to
 * storage (tracking overall progress), then the API assembles them. Bytes
 * never buffer in the API.
 */
async function createMultipartApi(
  file: File,
  onProgress?: (loaded: number, total: number) => void,
): Promise<VideoRecord> {
  const data = await apiFetch<PresignMultipart>('/api/v1/videos/presign/multipart', {
    method: 'POST',
    body: JSON.stringify({
      filename: file.name,
      size_bytes: file.size,
      content_type: file.type || 'application/octet-stream',
    }),
  })

  let uploaded = 0
  const parts: { part_number: number; etag: string }[] = []
  try {
    for (const part of data.parts) {
      const chunk = file.slice(
        (part.part_number - 1) * data.part_size,
        Math.min(part.part_number * data.part_size, file.size),
      )
      const etag = await putFile(part.url, chunk, (loaded, total) => {
        if (total > 0) onProgress?.(uploaded + loaded, file.size)
      })
      if (!etag) {
        throw new ApiError(0, 'Storage did not confirm a chunk — try again.')
      }
      parts.push({ part_number: part.part_number, etag })
      uploaded += chunk.size
    }

    const completed = await apiFetch<CompleteUpload>(
      `/api/v1/videos/${data.video.id}/complete/multipart`,
      {
        method: 'POST',
        body: JSON.stringify({ upload_id: data.upload_id, parts }),
      },
    )
    return toRecord(completed.video)
  } catch (error) {
    // The transfer or the confirmation failed — don't leave a zombie
    // `processing` row (and its orphaned object) behind.
    void apiFetch(`/api/v1/videos/${data.video.id}`, { method: 'DELETE' }).catch(() => {})
    throw error
  }
}

/** Upload through the API (local dev storage / presigning unavailable). */
async function uploadViaApi(
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

/**
 * Create a video on the server.
 *
 * Fast path: the API reserves a `processing` row and hands back a presigned
 * PUT URL, the browser uploads the file straight to R2 (no API buffering, no
 * double hop), then calls `complete` to start indexing.
 *
 * Fallback: when the backend cannot presign (local storage), upload via the
 * classic multipart endpoint so dev/test setups keep working unchanged.
 */
export async function createVideoApi(
  file: File,
  onProgress?: (loaded: number, total: number) => void,
): Promise<VideoRecord> {
  // Files above the 5 GiB single-PUT cap go through the chunked multipart
  // flow. A 409 there means storage can't presign at all (local dev) — the
  // file then buffers through the API instead.
  if (file.size > SINGLE_PUT_LIMIT) {
    try {
      return await createMultipartApi(file, onProgress)
    } catch (error) {
      if (error instanceof ApiError && error.status === 409) {
        return uploadViaApi(file, onProgress)
      }
      throw error
    }
  }

  // Fast path: presigned direct upload. 409 here means storage can't presign
  // (e.g. local dev) — fall through to multipart. Other errors are real
  // failures (unsupported type, too large) and must surface to the user.
  let presigned: PresignUpload | null = null
  try {
    const data = await apiFetch<PresignUpload>('/api/v1/videos/presign', {
      method: 'POST',
      body: JSON.stringify({
        filename: file.name,
        size_bytes: file.size,
        content_type: file.type || 'application/octet-stream',
      }),
    })
    presigned = data.upload_url ? data : null
  } catch (error) {
    if (error instanceof ApiError && error.status === 409) {
      presigned = null
    } else {
      throw error
    }
  }

  if (presigned && presigned.upload_url) {
    try {
      await putFile(presigned.upload_url, file, onProgress)
      const completed = await apiFetch<CompleteUpload>(
        `/api/v1/videos/${presigned.video.id}/complete`,
        { method: 'POST' },
      )
      return toRecord(completed.video)
    } catch (error) {
      // The transfer or the confirmation failed — don't leave a zombie
      // `processing` row (and its orphaned object) behind.
      void apiFetch(`/api/v1/videos/${presigned.video.id}`, { method: 'DELETE' }).catch(() => {})
      throw error
    }
  }

  // Fallback: multipart through the API (local dev storage / older backend).
  return uploadViaApi(file, onProgress)
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
