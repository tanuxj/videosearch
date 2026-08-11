import { useCallback, useEffect, useState } from 'react'

/**
 * Video library — metadata is persisted per user in localStorage, while the
 * playable object URL only lives for the current tab session (a File handle
 * can't be serialized). Videos uploaded in an earlier session therefore stay
 * listed and searchable, but show a "re-attach the file" state in the player.
 */

export type VideoStatus = 'processing' | 'ready'

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
}

const objectUrls = new Map<string, string>()
const listeners = new Set<() => void>()

function key(userId: string): string {
  return `vs.videos.${userId}`
}

function emit(): void {
  for (const listener of listeners) listener()
}

export function listVideos(userId: string): VideoRecord[] {
  try {
    const raw = localStorage.getItem(key(userId))
    const items = raw ? (JSON.parse(raw) as VideoRecord[]) : []
    return items.sort((a, b) => b.createdAt.localeCompare(a.createdAt))
  } catch {
    return []
  }
}

function write(userId: string, items: VideoRecord[]): void {
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

export function saveVideo(userId: string, video: VideoRecord): void {
  const items = listVideos(userId).filter((item) => item.id !== video.id)
  write(userId, [video, ...items])
}

export function removeVideo(userId: string, videoId: string): void {
  write(
    userId,
    listVideos(userId).filter((item) => item.id !== videoId),
  )
  const url = objectUrls.get(videoId)
  if (url) {
    URL.revokeObjectURL(url)
    objectUrls.delete(videoId)
  }
}

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

/** Live view of a user's library; re-renders when videos are added/removed. */
export function useVideos(userId: string | undefined): VideoRecord[] {
  const [videos, setVideos] = useState<VideoRecord[]>(() =>
    userId ? listVideos(userId) : [],
  )

  const refresh = useCallback(() => {
    setVideos(userId ? listVideos(userId) : [])
  }, [userId])

  useEffect(() => {
    refresh()
    listeners.add(refresh)
    window.addEventListener('storage', refresh)
    return () => {
      listeners.delete(refresh)
      window.removeEventListener('storage', refresh)
    }
  }, [refresh])

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
