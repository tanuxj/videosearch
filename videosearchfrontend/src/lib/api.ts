import type { VideoRecord } from './store'

/**
 * Clip search. When VITE_API_URL is set the prompt goes to the backend's
 * CLIP-embedding search; otherwise the UI falls back to a deterministic local
 * ranking so the flow stays demonstrable with no server running.
 */

const API_URL = (import.meta.env.VITE_API_URL || '').replace(/\/$/, '')

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

  if (API_URL) {
    try {
      const response = await fetch(`${API_URL}/api/v1/search/clips`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ video_id: video.id, prompt, limit }),
      })
      if (response.ok) {
        const data = (await response.json()) as { items?: ApiClip[] }
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
        }
      }
    } catch {
      // Backend unreachable — fall through to the local ranking.
    }
  }

  // Keep the perceived latency honest-looking without stalling the UI.
  await new Promise((resolve) => setTimeout(resolve, 420))
  return {
    clips: localSearch(video, prompt, limit),
    source: 'local',
    tookMs: Math.round(performance.now() - startedAt),
  }
}
