import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { fetchTranscript, startTranscription } from '../lib/api'
import type { Transcript, TranscriptSegment } from '../lib/api'
import { API_ENABLED, ApiError } from '../lib/http'
import type { VideoRecord } from '../lib/store'
import { Button } from '../components/ui/Button'
import { Chip, EmptyState, Panel } from '../components/ui/Data'
import { Shimmer } from '../components/ui/Motion'
import { FilmIcon, SearchIcon } from '../components/Icons'
import { timecode } from '../lib/format'

/**
 * The video's spoken content, as clickable timed text.
 *
 * Transcription runs alongside frame embedding on the backend and finishes
 * first, so this panel deliberately does *not* wait for `video.status` to be
 * `ready` — it polls its own endpoint and fills in the moment the text exists,
 * usually while the indexing bar above it is still moving.
 */

/** Re-poll this often while the server is still transcribing. */
const POLL_MS = 2500

const LANGUAGE_NAMES =
  typeof Intl !== 'undefined' && 'DisplayNames' in Intl
    ? new Intl.DisplayNames(undefined, { type: 'language' })
    : null

/** "hi" → "Hindi". Falls back to the raw code on anything unrecognised. */
function languageLabel(code: string): string {
  try {
    return LANGUAGE_NAMES?.of(code) ?? code
  } catch {
    return code
  }
}

/** Case-insensitive substring match, used to filter and to highlight. */
function matches(text: string, needle: string): boolean {
  return text.toLowerCase().includes(needle.toLowerCase())
}

/**
 * Split a line around every occurrence of `needle`, so the matching runs can
 * be marked without `dangerouslySetInnerHTML`.
 */
function highlight(text: string, needle: string) {
  if (!needle) return text
  const lower = text.toLowerCase()
  const target = needle.toLowerCase()
  const parts: Array<{ text: string; hit: boolean }> = []
  let cursor = 0
  for (;;) {
    const at = lower.indexOf(target, cursor)
    if (at === -1) break
    if (at > cursor) parts.push({ text: text.slice(cursor, at), hit: false })
    parts.push({ text: text.slice(at, at + needle.length), hit: true })
    cursor = at + needle.length
  }
  if (cursor === 0) return text
  if (cursor < text.length) parts.push({ text: text.slice(cursor), hit: false })
  return parts.map((part, index) =>
    part.hit ? (
      <mark key={index} className="rounded bg-brand-wash px-0.5 text-brand">
        {part.text}
      </mark>
    ) : (
      <span key={index}>{part.text}</span>
    ),
  )
}

type Props = {
  video: VideoRecord | null
  /**
   * Called with a segment's time range when a line is clicked — the Search
   * page turns it into a playable clip. Omit on pages without a player
   * (Recordings), where the transcript is read-only.
   */
  onSeek?: (segment: TranscriptSegment) => void
}

export function TranscriptPanel({ video, onSeek }: Props) {
  const [transcript, setTranscript] = useState<Transcript | null>(null)
  const [loading, setLoading] = useState(false)
  const [filter, setFilter] = useState('')
  // Open by default — the point of this panel is that the text is *there*
  // without hunting for it. Collapsing is for getting a 500-line transcript
  // out of the way of the search results below.
  const [open, setOpen] = useState(true)
  const [starting, setStarting] = useState(false)
  const [startError, setStartError] = useState<string | null>(null)
  const videoId = video?.id ?? null
  // Read inside the poll effect but not a reason to restart it — a ref keeps
  // the interval from being torn down and rebuilt on every keystroke.
  const pollTimer = useRef<ReturnType<typeof setTimeout>>(undefined)

  // Switching videos must stop the in-flight chain from writing stale results
  // into the new video's panel. A ref, not effect-local state, because
  // `generate` restarts the same chain from outside the effect.
  const cancelled = useRef(false)

  const poll = useCallback((id: string) => {
    fetchTranscript(id)
      .then((result) => {
        if (cancelled.current) return
        setTranscript(result)
        setLoading(false)
        // Keep polling only while the server still has work to do.
        if (result.status === 'pending' || result.status === 'processing') {
          pollTimer.current = setTimeout(() => poll(id), POLL_MS)
        }
      })
      .catch(() => {
        if (!cancelled.current) setLoading(false)
      })
  }, [])

  useEffect(() => {
    setTranscript(null)
    setFilter('')
    setStartError(null)
    if (!videoId || !API_ENABLED) return

    cancelled.current = false
    setLoading(true)
    poll(videoId)

    return () => {
      cancelled.current = true
      clearTimeout(pollTimer.current)
    }
  }, [videoId, poll])

  /** Kick off transcription for a video that hasn't got one. */
  const generate = useCallback(async () => {
    if (!videoId) return
    setStarting(true)
    setStartError(null)
    try {
      await startTranscription(videoId)
      // Flip the UI to "working" immediately rather than waiting a poll
      // interval to reflect what the server already accepted.
      setTranscript({ status: 'pending', segments: [] })
      clearTimeout(pollTimer.current)
      pollTimer.current = setTimeout(() => poll(videoId), POLL_MS)
    } catch (error) {
      setStartError(
        error instanceof ApiError ? error.message : 'Could not start transcription.',
      )
    } finally {
      setStarting(false)
    }
  }, [videoId, poll])

  // Memoised so the filter below has a stable dependency — a fresh `[]` each
  // render would re-filter the whole transcript on every keystroke elsewhere.
  const segments = useMemo(() => transcript?.segments ?? [], [transcript])
  const visible = useMemo(
    () =>
      filter.trim()
        ? segments.filter((segment) => matches(segment.text, filter.trim()))
        : segments,
    [segments, filter],
  )

  if (!video || !API_ENABLED) return null

  const status = transcript?.status ?? video.transcriptStatus
  const language = transcript?.language ?? video.language

  // `skipped` is not a dead end: videos indexed before transcription existed
  // all land here, and the only thing standing between them and a transcript
  // is asking for one. One quiet line plus the button that fixes it — this
  // sits under the composer, so a full empty state would push the results off
  // the screen for every video that has no transcript yet.
  if (status === 'skipped') {
    return (
      <p className="mt-3 flex flex-wrap items-center gap-x-2 gap-y-1 px-1 text-[13px] text-ink-faint [&>svg]:size-3.5">
        <FilmIcon />
        <span>No transcript for this video yet.</span>
        <button
          type="button"
          disabled={starting}
          onClick={() => void generate()}
          className="cursor-pointer font-medium text-brand underline underline-offset-2 transition-opacity hover:opacity-75 disabled:cursor-default disabled:opacity-50"
        >
          {starting ? 'Starting…' : 'Generate transcript'}
        </button>
        {startError && <span className="text-danger">{startError}</span>}
      </p>
    )
  }

  return (
    <Panel
      className="mt-4"
      title="Transcript"
      subtitle={
        status === 'ready'
          ? onSeek
            ? `${segments.length} ${segments.length === 1 ? 'line' : 'lines'} · click any line to play it`
            : `${segments.length} ${segments.length === 1 ? 'line' : 'lines'}`
          : undefined
      }
      actions={
        <div className="flex items-center gap-2">
          {language && status === 'ready' && (
            <Chip tone="neutral" title={`Detected language: ${language}`}>
              {languageLabel(language)}
            </Chip>
          )}
          {(status === 'pending' || status === 'processing') && (
            <Chip tone="brand" pulse>
              Transcribing…
            </Chip>
          )}
          {status === 'failed' && <Chip tone="danger">Failed</Chip>}
          {status === 'ready' && segments.length > 0 && (
            <button
              type="button"
              onClick={() => setOpen((value) => !value)}
              aria-expanded={open}
              className="cursor-pointer rounded-lg border border-line px-2.5 py-1 text-[12px] font-medium text-ink-dim transition-colors hover:bg-surface-sunk hover:text-ink"
            >
              {open ? 'Hide' : 'Show'}
            </button>
          )}
          {status === 'ready' && segments.length > 0 && open && (
            <label className="relative flex items-center">
              <span className="sr-only">Filter transcript</span>
              <i className="pointer-events-none absolute left-2.5 text-ink-faint [&_svg]:size-3.5">
                <SearchIcon />
              </i>
              <input
                value={filter}
                onChange={(event) => setFilter(event.target.value)}
                placeholder="Find in transcript"
                className="w-44 rounded-lg border border-line bg-surface-sunk py-1.5 pr-2.5 pl-8 text-[12.5px] text-ink placeholder:text-ink-faint focus:border-brand focus:outline-none"
              />
            </label>
          )}
        </div>
      }
    >
      {(loading || status === 'pending' || status === 'processing') &&
        segments.length === 0 && (
          <div className="space-y-2.5 px-5 py-4">
            {Array.from({ length: 5 }, (_, index) => (
              <Shimmer key={index} className="h-4 w-full" />
            ))}
          </div>
        )}

      {status === 'failed' && (
        <EmptyState
          title="Transcription failed"
          body={startError ?? transcript?.error ?? 'The server could not transcribe this video.'}
          action={
            <Button size="sm" disabled={starting} onClick={() => void generate()}>
              {starting ? 'Starting…' : 'Try again'}
            </Button>
          }
        />
      )}

      {status === 'ready' && segments.length === 0 && (
        <EmptyState
          icon={<FilmIcon />}
          title="Nothing was said"
          body="The audio track carries no recognisable speech."
        />
      )}

      {visible.length > 0 && open && (
        // Capped height with its own scroll: a long transcript must not push
        // the rest of the page out of reach.
        <ol className="max-h-[22rem] divide-y divide-line overflow-y-auto">
          {visible.map((segment, index) => (
            <li key={`${segment.start}-${index}`}>
              {onSeek ? (
                <button
                  type="button"
                  onClick={() => onSeek(segment)}
                  className="flex w-full cursor-pointer items-baseline gap-3 px-5 py-2.5 text-left transition-colors hover:bg-surface-sunk"
                >
                  <span className="shrink-0 font-mono text-[11.5px] text-brand tabular-nums">
                    {timecode(segment.start)}
                  </span>
                  <span className="text-[13.5px] leading-relaxed text-ink">
                    {highlight(segment.text, filter.trim())}
                  </span>
                </button>
              ) : (
                <div className="flex items-baseline gap-3 px-5 py-2.5">
                  <span className="shrink-0 font-mono text-[11.5px] text-brand tabular-nums">
                    {timecode(segment.start)}
                  </span>
                  <span className="text-[13.5px] leading-relaxed text-ink">
                    {highlight(segment.text, filter.trim())}
                  </span>
                </div>
              )}
            </li>
          ))}
        </ol>
      )}

      {status === 'ready' && segments.length > 0 && visible.length === 0 && open && (
        <EmptyState
          icon={<SearchIcon />}
          title="No line matches"
          body={`Nothing in the transcript contains “${filter.trim()}”.`}
        />
      )}
    </Panel>
  )
}
