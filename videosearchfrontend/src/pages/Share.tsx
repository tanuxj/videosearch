import { useEffect, useRef, useState } from 'react'
import type { RefObject } from 'react'
import { useLocation } from '../lib/router'
import { useAuth } from '../lib/auth'
import { fetchPublicShare, fetchPublicTranscript } from '../lib/api'
import type { PublicShare, Transcript } from '../lib/api'
import { API_ENABLED, url } from '../lib/http'
import { Brand } from '../components/Shell'
import { Button, ButtonLink } from '../components/ui/Button'
import { Chip } from '../components/ui/Data'
import { Shimmer } from '../components/ui/Motion'
import {
  CheckIcon,
  FilmIcon,
  LinkIcon,
  PlayIcon,
  SearchIcon,
  ShareIcon,
  WaveIcon,
} from '../components/Icons'
import { parseTimecode, timecode } from '../lib/format'
import { Link } from '../lib/router'

/**
 * The public side of a share link (`/share/<token>`).
 *
 * Deliberately standalone — no app shell, no auth required. The recipient sees
 * the video (or audio) player, the transcript, and can copy the link, with or
 * without a `?t=` timecode to jump a viewer straight to a moment.
 */

const POLL_MS = 2500

const LANGUAGE_NAMES =
  typeof Intl !== 'undefined' && 'DisplayNames' in Intl
    ? new Intl.DisplayNames(undefined, { type: 'language' })
    : null

function languageLabel(code: string): string {
  try {
    return LANGUAGE_NAMES?.of(code) ?? code
  } catch {
    return code
  }
}

type Props = {
  token: string
}

export default function Share({ token }: Props) {
  const { query } = useLocation()
  const { user } = useAuth()
  const [share, setShare] = useState<PublicShare | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const playerRef = useRef<HTMLVideoElement | HTMLAudioElement>(null)
  const [currentTime, setCurrentTime] = useState(0)
  const [copied, setCopied] = useState<string | null>(null)

  // The share page exists only behind a real backend — there is no server to
  // hold a token in demo mode.
  useEffect(() => {
    let cancelled = false
    if (!API_ENABLED) {
      setLoading(false)
      setError('Sharing needs the backend running — this build is in demo mode.')
      return
    }
    setLoading(true)
    setError(null)
    fetchPublicShare(token)
      .then((data) => {
        if (!cancelled) setShare(data)
      })
      .catch(() => {
        if (!cancelled) setError("This video isn't shared — the link may have been revoked.")
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [token])

  // ?t=mm:ss (or plain seconds) seeks the player the moment it can.
  const seekOnLoad = parseTimecode(query.get('t'))

  useEffect(() => {
    const player = playerRef.current
    if (!player || seekOnLoad === null) return
    const seek = () => {
      player.currentTime = Math.min(seekOnLoad, player.duration || seekOnLoad)
    }
    // The duration isn't known until metadata loads — seek then, not before.
    if (player.readyState >= 1) seek()
    else player.addEventListener('loadedmetadata', seek, { once: true })
    return () => player.removeEventListener('loadedmetadata', seek)
  }, [seekOnLoad, share])

  // Keep the playhead for "copy link at current time".
  useEffect(() => {
    const player = playerRef.current
    if (!player) return
    const onTime = () => setCurrentTime(player.currentTime)
    player.addEventListener('timeupdate', onTime)
    return () => player.removeEventListener('timeupdate', onTime)
  }, [share])

  const path = `/share/${token}`

  async function copy(text: string, label: string) {
    try {
      await navigator.clipboard.writeText(text)
    } catch {
      // Clipboard blocked (non-secure context) — fall back to a prompt.
      window.prompt('Copy this link:', text)
    }
    setCopied(label)
    window.setTimeout(() => setCopied((current) => (current === label ? null : current)), 1600)
  }

  function seekTo(seconds: number) {
    const player = playerRef.current
    if (player) player.currentTime = seconds
    setCurrentTime(seconds)
  }

  return (
    <div className="flex min-h-screen flex-col bg-surface">
      <header className="sticky top-0 z-50 border-b border-line bg-surface">
        <div className="mx-auto flex h-16 w-full max-w-[860px] items-center gap-6 px-6">
          <Brand />
          <div className="ml-auto flex items-center gap-2">
            {user ? (
              <ButtonLink as={Link} to="/search" variant="ghost" size="sm">
                Open app
              </ButtonLink>
            ) : (
              <ButtonLink as={Link} to="/login" variant="ghost" size="sm">
                Sign in
              </ButtonLink>
            )}
          </div>
        </div>
      </header>

      <main className="mx-auto w-full max-w-[860px] flex-1 px-6 py-8">
        {loading ? (
          <div className="space-y-4">
            <Shimmer className="aspect-video w-full rounded-2xl" />
            <Shimmer className="h-5 w-1/3" />
            <Shimmer className="h-3 w-2/3" />
          </div>
        ) : error || !share ? (
          <div className="mx-auto max-w-[46ch] py-24 text-center">
            <span className="mx-auto grid size-14 place-items-center rounded-2xl border border-line bg-surface-soft text-ink-dim [&_svg]:size-6">
              <LinkIcon />
            </span>
            <h1 className="mt-6 text-[clamp(1.6rem,4vw,2.2rem)] font-semibold tracking-[-0.03em] text-ink">
              This link isn't shared
            </h1>
            <p className="mt-3 text-[14.5px] leading-relaxed text-ink-mid">
              {error ?? "This video isn't shared — the link may have been revoked."}
            </p>
            <div className="mt-7 flex justify-center gap-2">
              <ButtonLink as={Link} to="/" size="sm">
                Back to {import.meta.env.VITE_APP_NAME || 'home'}
              </ButtonLink>
            </div>
          </div>
        ) : (
          <>
            {/* Player stage — near-black so letterboxed media doesn't wash out. */}
            <div className="grid aspect-video w-full place-items-center overflow-hidden rounded-2xl border border-line bg-[#0c0e13]">
              {share.hasVideo === false ? (
                <audio
                  ref={playerRef as RefObject<HTMLAudioElement>}
                  src={url(share.streamUrl)}
                  controls
                  playsInline
                  className="w-[min(86%,30rem)]"
                />
              ) : (
                <video
                  ref={playerRef as RefObject<HTMLVideoElement>}
                  src={url(share.streamUrl)}
                  controls
                  playsInline
                  className="size-full"
                >
                  {share.transcriptStatus === 'ready' && (
                    <track
                      kind="subtitles"
                      src={url(`/api/v1/shares/${token}/captions.vtt`)}
                      srcLang={share.language || 'und'}
                      label={share.language ? share.language.toUpperCase() : 'Subtitles'}
                      default
                    />
                  )}
                </video>
              )}
            </div>

            <div className="mt-5 flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0">
                <h1 className="truncate text-[19px] font-semibold tracking-[-0.02em] text-ink">
                  {share.name}
                </h1>
                <div className="mt-1.5 flex flex-wrap items-center gap-2 text-[12.5px] text-ink-faint">
                  {share.duration > 0 && <span>{timecode(share.duration)}</span>}
                  {share.source === 'recording' && (
                    <Chip tone="brand" icon={share.hasVideo === false ? <WaveIcon /> : <PlayIcon />}>
                      Recording
                    </Chip>
                  )}
                  {share.hasVideo === false && <Chip tone="neutral">Audio only</Chip>}
                  {share.status === 'processing' && (
                    <Chip tone="warn" pulse>
                      Indexing
                    </Chip>
                  )}
                </div>
              </div>

              <div className="flex shrink-0 items-center gap-2">
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => void copy(`${window.location.origin}${path}`, 'link')}
                  className="[&_svg]:size-4"
                >
                  {copied === 'link' ? <CheckIcon /> : <LinkIcon />}
                  {copied === 'link' ? 'Copied' : 'Copy link'}
                </Button>
                <Button
                  size="sm"
                  onClick={() =>
                    void copy(
                      `${window.location.origin}${path}?t=${timecode(currentTime)}`,
                      'time',
                    )
                  }
                  title="Copy a link that opens the video at the current moment"
                  className="[&_svg]:size-4"
                >
                  {copied === 'time' ? <CheckIcon /> : <ShareIcon />}
                  {copied === 'time' ? 'Copied' : 'Share at moment'}
                </Button>
              </div>
            </div>

            <ShareTranscript token={token} share={share} onSeek={seekTo} />
          </>
        )}
      </main>

      <footer className="border-t border-line py-6 text-center text-[12px] text-ink-faint">
        Shared via {import.meta.env.VITE_APP_NAME || 'SearchInVideo'}
      </footer>
    </div>
  )
}

/**
 * The shared video's transcript, fetched without auth and polled while the
 * server is still transcribing. Lines are clickable and seek the player.
 */
function ShareTranscript({
  token,
  share,
  onSeek,
}: {
  token: string
  share: PublicShare
  onSeek: (seconds: number) => void
}) {
  const [transcript, setTranscript] = useState<Transcript | null>(null)
  const [filter, setFilter] = useState('')
  const status = transcript?.status ?? share.transcriptStatus
  const segments = transcript?.segments ?? []
  const visible = filter.trim()
    ? segments.filter((segment) =>
        segment.text.toLowerCase().includes(filter.trim().toLowerCase()),
      )
    : segments

  useEffect(() => {
    let cancelled = false
    let timer: ReturnType<typeof setTimeout> | undefined

    const poll = (id: string) => {
      fetchPublicTranscript(id)
        .then((result) => {
          if (cancelled) return
          setTranscript(result)
          if (result.status === 'pending' || result.status === 'processing') {
            timer = setTimeout(() => poll(id), POLL_MS)
          }
        })
        .catch(() => {
          /* public page degrades to "no transcript" */
        })
    }

    poll(token)
    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  }, [token])

  if (status === 'skipped') {
    return (
      <p className="mt-6 flex items-center gap-2 px-1 text-[13px] text-ink-faint [&_svg]:size-3.5">
        <FilmIcon />
        <span>No transcript for this video.</span>
      </p>
    )
  }

  return (
    <div className="mt-6 overflow-hidden rounded-2xl border border-line bg-panel">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-4 py-3">
        <div className="flex items-center gap-2">
          <b className="text-[13.5px] font-semibold text-ink">Transcript</b>
          {share.language && status === 'ready' && (
            <Chip tone="neutral">{languageLabel(share.language)}</Chip>
          )}
          {(status === 'pending' || status === 'processing') && (
            <Chip tone="brand" pulse>
              Transcribing…
            </Chip>
          )}
          {status === 'failed' && <Chip tone="danger">Failed</Chip>}
        </div>
        {status === 'ready' && segments.length > 0 && (
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

      {status === 'ready' && segments.length === 0 && (
        <p className="px-4 py-6 text-center text-[13px] text-ink-faint">
          Nothing was said — the audio track carries no recognisable speech.
        </p>
      )}

      {status === 'failed' && (
        <p className="px-4 py-6 text-center text-[13px] text-ink-faint">
          The transcript could not be generated.
        </p>
      )}

      {(status === 'pending' || status === 'processing') && segments.length === 0 && (
        <div className="space-y-2.5 px-5 py-4">
          {Array.from({ length: 5 }, (_, index) => (
            <Shimmer key={index} className="h-4 w-full" />
          ))}
        </div>
      )}

      {visible.length > 0 && (
        <ol className="max-h-[24rem] divide-y divide-line overflow-y-auto">
          {visible.map((segment, index) => (
            <li key={`${segment.start}-${index}`}>
              <button
                type="button"
                onClick={() => onSeek(segment.start)}
                className="flex w-full cursor-pointer items-baseline gap-3 px-5 py-2.5 text-left transition-colors hover:bg-surface-sunk"
              >
                <span className="shrink-0 font-mono text-[11.5px] text-brand tabular-nums">
                  {timecode(segment.start)}
                </span>
                <span className="text-[13.5px] leading-relaxed text-ink">
                  {highlight(segment.text, filter.trim())}
                </span>
              </button>
            </li>
          ))}
        </ol>
      )}

      {status === 'ready' && visible.length === 0 && filter.trim() && (
        <p className="px-4 py-6 text-center text-[13px] text-ink-faint">
          Nothing in the transcript contains “{filter.trim()}”.
        </p>
      )}
    </div>
  )
}

/** Mark every occurrence of `needle` in `text` without dangerouslySetInnerHTML. */
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
