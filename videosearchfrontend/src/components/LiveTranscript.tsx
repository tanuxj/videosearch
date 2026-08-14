import { useEffect, useMemo, useRef, useState } from 'react'
import { fetchTranscript } from '../lib/api'
import type { TranscriptSegment } from '../lib/api'
import { API_ENABLED } from '../lib/http'
import { cn } from '../lib/cn'
import { timecode } from '../lib/format'

/**
 * The spoken text, below the player, following playback.
 *
 * Complements the burned-in `<track>` captions rather than duplicating them:
 * a caption shows only the line being said *right now* and vanishes with it,
 * which is useless for reading ahead, skimming back, or jumping to a line you
 * half-remember. This keeps the surrounding lines on screen and makes every
 * one of them a seek target.
 */

type Props = {
  videoId: string | null
  /** Playhead position, in seconds — drives which line is active. */
  currentTime: number
  onSeek: (seconds: number) => void
}

export function LiveTranscript({ videoId, currentTime, onSeek }: Props) {
  const [segments, setSegments] = useState<TranscriptSegment[]>([])
  const listRef = useRef<HTMLOListElement>(null)
  const activeRef = useRef<HTMLLIElement>(null)
  /**
   * Auto-scrolling fights the user the moment they scroll to read elsewhere,
   * so it stops until the active line comes back into view on its own.
   */
  const [following, setFollowing] = useState(true)

  useEffect(() => {
    setSegments([])
    setFollowing(true)
    if (!videoId || !API_ENABLED) return
    let cancelled = false
    fetchTranscript(videoId)
      .then((result) => {
        if (!cancelled && result.status === 'ready') setSegments(result.segments)
      })
      .catch(() => {
        /* no transcript — the strip simply doesn't render */
      })
    return () => {
      cancelled = true
    }
  }, [videoId])

  /**
   * The line being spoken now.
   *
   * Falls back to the last line that has *started* rather than requiring the
   * playhead to sit inside a segment: transcripts have gaps between
   * utterances, and blanking the highlight during every pause reads as a bug.
   */
  const activeIndex = useMemo(() => {
    if (segments.length === 0) return -1
    let candidate = -1
    for (let i = 0; i < segments.length; i += 1) {
      const segment = segments[i]!
      if (segment.start <= currentTime) candidate = i
      else break
    }
    return candidate
  }, [segments, currentTime])

  /**
   * Built only when the *active line* changes, not on every playhead tick.
   *
   * `timeupdate` fires ~4x/second and a long transcript runs to hundreds of
   * lines, so rendering the list inline would rebuild all of them several
   * times a second to move one highlight. Keying the memo on `activeIndex`
   * collapses that to once per spoken line.
   */
  const rows = useMemo(
    () =>
      segments.map((segment, index) => {
        const active = index === activeIndex
        return (
          <li key={`${segment.start}-${index}`} ref={active ? activeRef : undefined}>
            <button
              type="button"
              onClick={() => onSeek(segment.start)}
              className={cn(
                'flex w-full cursor-pointer items-baseline gap-2.5 rounded-md px-1.5 py-1 text-left transition-colors',
                active ? 'bg-brand-wash' : 'hover:bg-surface-sunk',
              )}
            >
              <span
                className={cn(
                  'shrink-0 font-mono text-[11px] tabular-nums',
                  active ? 'text-brand' : 'text-ink-faint',
                )}
              >
                {timecode(segment.start)}
              </span>
              <span
                className={cn(
                  'text-[13px] leading-snug',
                  active ? 'font-medium text-ink' : 'text-ink-dim',
                )}
              >
                {segment.text}
              </span>
            </button>
          </li>
        )
      }),
    [segments, activeIndex, onSeek],
  )

  // Keep the active line visible, unless the user has scrolled away.
  useEffect(() => {
    if (!following || activeIndex < 0) return
    activeRef.current?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
  }, [activeIndex, following])

  if (segments.length === 0) return null

  return (
    <div className="border-t border-line bg-panel">
      <ol
        ref={listRef}
        // `list-none` is load-bearing: this is an <ol> for the semantics, and
        // without it the browser numbers every line ("0. 1. 2.") down the
        // left-hand side.
        //
        // Short on purpose: this sits under a video in a modal, so it must
        // stay a strip rather than become the page.
        className="max-h-28 list-none overflow-y-auto px-4 py-2"
        onScroll={() => {
          const list = listRef.current
          const active = activeRef.current
          if (!list || !active) return
          // Re-arm following once the active line is back in view, so the user
          // never has to find a control to resume it.
          const inView =
            active.offsetTop >= list.scrollTop &&
            active.offsetTop + active.offsetHeight <= list.scrollTop + list.clientHeight
          setFollowing(inView)
        }}
      >
        {rows}
      </ol>
    </div>
  )
}
