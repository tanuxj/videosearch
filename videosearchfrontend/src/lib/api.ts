import type { VideoRecord } from './store'
import { API_ENABLED, apiFetch, getAccessToken, url } from './http'

/**
 * Clip search. When VITE_API_URL is set the prompt goes to the backend's
 * CLIP-embedding search (authenticated); otherwise the UI falls back to a
 * deterministic local ranking so the flow stays demonstrable with no server
 * running.
 */

export type Clip = {
  id: string
  videoId: string
  /** Seconds into the video where the matching moment begins. */
  start: number
  end: number
  /** Matching frame timestamp — what the thumbnail is captured from. */
  frame: number
  /** 0–1 similarity against the prompt. */
  score: number
}

export type SearchResult = {
  clips: Clip[]
  /** 'api' = ranked by the backend, 'local' = deterministic demo ranking. */
  source: 'api' | 'local'
  tookMs: number
  /**
   * Backend's minimum-similarity threshold (0–1) — everything below it was
   * filtered out as a non-match.
   */
  minScore?: number
  /** True when the backend rewrote/expanded the prompt into visual variants. */
  expanded?: boolean
  /** Set when the backend is configured but could not run the search. */
  error?: string
}

type ApiClip = {
  id?: string
  start?: number
  end?: number
  timestamp?: number
  score?: number
}

export const SUGGESTIONS = [
  'a red car driving on a highway',
  'someone writing on a whiteboard',
  'a wide shot of a city at night',
  'two people shaking hands',
  'a close-up of a laptop screen',
]

function seedFrom(text: string): number {
  let h = 2166136261
  for (let i = 0; i < text.length; i += 1) {
    h ^= text.charCodeAt(i)
    h = Math.imul(h, 16777619)
  }
  return h >>> 0
}

/** Small deterministic PRNG so the same prompt always ranks the same way. */
function mulberry32(seed: number): () => number {
  let a = seed
  return () => {
    a |= 0
    a = (a + 0x6d2b79f5) | 0
    let t = Math.imul(a ^ (a >>> 15), 1 | a)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

function localSearch(video: VideoRecord, prompt: string, limit: number): Clip[] {
  const duration = video.duration || 60
  const random = mulberry32(seedFrom(`${video.id}:${prompt.trim().toLowerCase()}`))

  // Score one candidate per sampling window, then keep the strongest windows.
  const windowCount = Math.max(limit, Math.min(48, Math.floor(duration / 4)))
  const windowSize = duration / windowCount

  const candidates = Array.from({ length: windowCount }, (_, i) => {
    const frame = Math.min(
      duration - 0.2,
      i * windowSize + random() * windowSize,
    )
    return { frame, score: 0.32 + random() * 0.63 }
  })

  return candidates
    .sort((a, b) => b.score - a.score)
    .slice(0, limit)
    .map((candidate, rank) => {
      const start = Math.max(0, candidate.frame - 1.8)
      return {
        id: `${video.id}-${rank}-${Math.round(candidate.frame * 100)}`,
        videoId: video.id,
        start,
        end: Math.min(duration, start + 4 + random() * 5),
        frame: candidate.frame,
        score: candidate.score,
      }
    })
}

export async function searchClips(
  video: VideoRecord,
  prompt: string,
  limit = 9,
): Promise<SearchResult> {
  const startedAt = performance.now()

  // No backend configured — deterministic demo ranking, clearly labelled.
  if (!API_ENABLED) {
    await new Promise((resolve) => setTimeout(resolve, 420))
    return {
      clips: localSearch(video, prompt, limit),
      source: 'local',
      tookMs: Math.round(performance.now() - startedAt),
    }
  }

  try {
    const response = await fetch(url('/api/v1/search/clips'), {
      method: 'POST',
      credentials: 'include',
      headers: {
        'Content-Type': 'application/json',
        ...(getAccessToken() ? { Authorization: `Bearer ${getAccessToken()}` } : {}),
      },
      body: JSON.stringify({ video_id: video.id, prompt, limit }),
    })
    if (response.ok) {
      const data = (await response.json()) as {
        items?: ApiClip[]
        min_score?: number
        expanded?: boolean
      }
      const clips = (data.items ?? []).map((item, index) => {
        const frame = item.timestamp ?? item.start ?? 0
        const start = item.start ?? Math.max(0, frame - 1.8)
        return {
          id: item.id ?? `${video.id}-api-${index}`,
          videoId: video.id,
          start,
          end: item.end ?? start + 6,
          frame,
          score: item.score ?? 0,
        }
      })
      return {
        clips,
        source: 'api',
        tookMs: Math.round(performance.now() - startedAt),
        minScore: data.min_score ?? 0,
        expanded: data.expanded ?? false,
      }
    }

    // The backend answered with a real error — surface it instead of
    // fabricating "matches" the video never contained.
    return {
      clips: [],
      source: 'api',
      tookMs: Math.round(performance.now() - startedAt),
      error: await readError(response, 'Search failed'),
    }
  } catch {
    return {
      clips: [],
      source: 'api',
      tookMs: Math.round(performance.now() - startedAt),
      error: 'The search backend is unreachable — check that it’s running.',
    }
  }
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

/**
 * Download a trimmed clip ([start, end) seconds) of a video as a Blob.
 *
 * The backend cuts the segment with ffmpeg and streams it back as an MP4
 * attachment. Falls back to the raw API error when the request fails.
 */
export async function downloadClip(
  videoId: string,
  start: number,
  end: number,
): Promise<Blob> {
  const params = new URLSearchParams({
    start: String(start),
    end: String(end),
  })
  return apiFetch<Blob>(`/api/v1/videos/${videoId}/clip?${params}`, {
    parseBlob: true,
  })
}

/** Save a Blob to the user's disk as a real file download. */
export function saveBlob(blob: Blob, filename: string): void {
  const objectUrl = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = objectUrl
  anchor.download = filename
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  // Revoke on the next tick so the browser has started the download.
  setTimeout(() => URL.revokeObjectURL(objectUrl), 10_000)
}
