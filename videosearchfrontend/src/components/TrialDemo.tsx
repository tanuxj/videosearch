import { useCallback, useEffect, useRef, useState } from 'react'
import type { DragEvent, KeyboardEvent } from 'react'
import {
  captureFrames,
  createVideoApi,
  createVideoFromUrl,
  getVideo,
  streamSourceFor,
} from '../lib/store'
import type { VideoRecord } from '../lib/store'
import { SUGGESTIONS, searchClips } from '../lib/api'
import type { Clip } from '../lib/api'
import { timecode } from '../lib/format'
import { Button, ButtonLink } from './ui/Button'
import { Link } from '../lib/router'
import { Card } from './ui/Card'
import { ClipLightbox } from './ClipLightbox'
import { ClipResultCard } from './ClipResultCard'
import { PaywallModal } from './PaywallModal'
import { Shimmer } from './ui/Motion'
import { Spinner } from './AuthLayout'
import {
  ClockIcon,
  LinkIcon,
  SearchIcon,
  SparkIcon,
  UploadIcon,
} from './Icons'
import { cn } from '../lib/cn'

/**
 * The homepage's try-it demo: the whole product loop, nothing persistent.
 *
 * Anonymous visitors get the real pipeline — upload, index, search, watch the
 * matched clip — through the same API endpoints an account uses (the backend
 * resolves the request to a throwaway trial session via the `vs_guest`
 * cookie). What they don't get is anything that costs storage: download,
 * share and history are locked behind the paywall modal, enforced server-side
 * by `require_registered_user` and mirrored here.
 *
 * `expiresAt` is stamped by the server on every trial upload and swept by its
 * purge job; the countdown is the honest, visible half of that promise.
 */

/** Matches TRIAL_TTL_MINUTES in the backend's config — display only. */
const TRIAL_MINUTES = 30

/** One trial per browser per page-load: the server enforces a real quota via its purge sweep; we simply track the one video this session is about. */
type Phase = 'idle' | 'uploading' | 'importing' | 'indexing' | 'ready' | 'failed'

/**
 * First https:// URL in pasted text, trimmed of trailing punctuation.
 *
 * Users paste links surrounded by prose, quotes, or a list — grab the first
 * https:// token rather than demanding an exact paste. http:// is not
 * matched: the backend refuses it (SSRF guard), so reporting "no link found"
 * with the scheme requirement spelled out is clearer than a 422.
 */
function extractUrl(text: string): string | null {
  const match = text.match(/https:\/\/[^\s"'()\[\]{}<>,;]+/i)
  if (!match) return null
  return match[0].replace(/[.,;:!?]+$/, '')
}

/** Seconds left before the purge, driven by a 1s tick. */
function secondsLeft(expiresAt: string | undefined): number | null {
  if (!expiresAt) return null
  const left = Math.floor((new Date(expiresAt).getTime() - Date.now()) / 1000)
  return Number.isFinite(left) && left > 0 ? left : 0
}

function mmss(total: number): string {
  const m = Math.floor(total / 60)
  const s = total % 60
  return `${m}:${String(s).padStart(2, '0')}`
}

export function TrialDemo() {
  const [video, setVideo] = useState<VideoRecord | null>(null)
  const [phase, setPhase] = useState<Phase>('idle')
  const [uploadProgress, setUploadProgress] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const [dragging, setDragging] = useState(false)
  /** Which entry mode the idle box shows: a picked file or a pasted link. */
  const [mode, setMode] = useState<'file' | 'link'>('file')
  const [urlInput, setUrlInput] = useState('')

  const [prompt, setPrompt] = useState('')
  const [clips, setClips] = useState<Clip[] | null>(null)
  const [thumbs, setThumbs] = useState<Map<number, string>>(new Map())
  const [searching, setSearching] = useState(false)
  const [searchError, setSearchError] = useState<string | null>(null)
  const [lastQuery, setLastQuery] = useState('')
  const [openClip, setOpenClip] = useState<Clip | null>(null)
  const [src, setSrc] = useState('')

  const [paywall, setPaywall] = useState<string | null>(null)

  const inputRef = useRef<HTMLInputElement>(null)
  const aliveRef = useRef(true)
  const promptRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    aliveRef.current = true
    return () => {
      aliveRef.current = false
    }
  }, [])

  // Playback source once the video is ready — the trial is allowed to stream.
  const status = video?.status ?? null
  useEffect(() => {
    let cancelled = false
    if (!video || status !== 'ready') {
      setSrc('')
      return
    }
    streamSourceFor(video.id)
      .then((streamUrl) => {
        if (!cancelled) setSrc(streamUrl)
      })
      .catch(() => {
        /* playback is decorative here — search still works */
      })
    return () => {
      cancelled = true
    }
  }, [video, status])

  // Real thumbnails for the results, captured from the playback source.
  useEffect(() => {
    if (!clips || clips.length === 0 || !src) return
    let cancelled = false
    void captureFrames(src, clips.map((clip) => clip.frame)).then((frames) => {
      if (!cancelled) setThumbs(frames)
    })
    return () => {
      cancelled = true
    }
  }, [clips, src])

  // Poll the indexing pipeline while it runs, exactly like UploadDialog does.
  useEffect(() => {
    if (!video || video.status !== 'processing') return
    let cancelled = false
    const poll = async () => {
      while (!cancelled) {
        await new Promise((resolve) => setTimeout(resolve, 1000))
        if (cancelled) return
        const next = await getVideo(video.id).catch(() => null)
        if (!next) {
          // 404: the purge got here early (or the row died) — say so.
          setPhase('failed')
          setError('This trial video is no longer available.')
          return
        }
        setVideo(next)
        if (next.status !== 'processing') {
          // Advance the phase with the status — the render branches on
          // `phase`, so without this the progress card sits at 100% forever
          // even though `video.status` already says ready.
          setPhase(next.status === 'ready' ? 'ready' : 'failed')
          if (next.status === 'failed') {
            setError(next.error || 'Indexing failed on the server — try another file.')
          }
          return
        }
      }
    }
    void poll()
    return () => {
      cancelled = true
    }
  }, [video])

  // The 30-minute countdown, re-rendered every second.
  const [nowTick, setNowTick] = useState(0)
  const hasExpiry = Boolean(video?.expiresAt)
  useEffect(() => {
    if (!hasExpiry) return
    const timer = window.setInterval(() => setNowTick((t) => t + 1), 1000)
    return () => window.clearInterval(timer)
  }, [hasExpiry])
  const left = secondsLeft(video?.expiresAt)
  void nowTick // render driver only

  async function ingest(file: File) {
    if (
      phase === 'uploading' ||
      phase === 'importing' ||
      phase === 'indexing'
    ) {
      return
    }
    setError(null)
    setUploadProgress(0)
    setPhase('uploading')
    try {
      const record = await createVideoApi(file, {
        onProgress: (loaded, total) => {
          if (!aliveRef.current) return
          setUploadProgress(total > 0 ? loaded / total : 1)
        },
      })
      if (!aliveRef.current) return
      setVideo(record)
      if (record.status === 'ready') {
        setPhase('ready')
      } else if (record.status === 'failed') {
        setPhase('failed')
        setError(record.error || 'Indexing failed on the server — try another file.')
      } else {
        setPhase('indexing')
      }
    } catch (caught) {
      if (!aliveRef.current) return
      setPhase('idle')
      setError(caught instanceof Error ? caught.message : 'Upload failed.')
    }
  }

  function onDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault()
    setDragging(false)
    const file = event.dataTransfer.files?.[0]
    if (file) {
      void ingest(file)
      return
    }
    // A dropped link (dragged from another tab's address bar) lands here as
    // text — same entry point as pasting, so both behave identically.
    const droppedUrl = event.dataTransfer.getData('text/uri-list') || event.dataTransfer.getData('text/plain')
    const url = extractUrl(droppedUrl)
    if (url) {
      setUrlInput(url)
      setMode('link')
      void ingestUrl(url)
    }
  }

  /**
   * Paste-a-link import.
   *
   * The server downloads and indexes the video exactly like an upload (same
   * `from-url` endpoint the product's UploadDialog uses) and stamps the same
   * trial expiry — the demo leashes a YouTube video the same way it leashes
   * a file. `createVideoFromUrl` resolves once the row is reserved while the
   * download still runs server-side, so the UI holds on an indeterminate
   * "importing" stage until the first frames show up in the poll.
   */
  async function ingestUrl(rawUrl: string) {
    if (phase === 'uploading' || phase === 'importing' || phase === 'indexing') return
    const url = rawUrl.trim()
    setError(null)
    setPhase('importing')
    try {
      const record = await createVideoFromUrl(url)
      if (!aliveRef.current) return
      setVideo(record)
      setPhase('indexing')
    } catch (caught) {
      if (!aliveRef.current) return
      setPhase('idle')
      setError(caught instanceof Error ? caught.message : 'Import failed.')
    }
  }

  const runSearch = useCallback(
    async (text: string) => {
      const trimmed = text.trim()
      const target = video
      if (!trimmed || !target || target.status !== 'ready') return

      setSearching(true)
      setOpenClip(null)
      setThumbs(new Map())
      setLastQuery(trimmed)
      setSearchError(null)

      const result = await searchClips(target, trimmed)
      setClips(result.clips)
      setSearchError(result.error ?? null)
      setSearching(false)
    },
    [video],
  )

  function onPromptKey(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      void runSearch(prompt)
    }
  }

  // ── Phase: nothing imported yet ─────────────────────────────
  if (!video || phase === 'idle' || phase === 'failed') {
    return (
      <div>
        {/* File vs link, matching the product's Add-video dialog tabs. */}
        <div className="mb-3 flex justify-center">
          <div className="flex gap-1 rounded-full border border-line bg-surface-soft p-1">
            {(
              [
                { key: 'file', label: 'Upload a file' },
                { key: 'link', label: 'Paste a link' },
              ] as const
            ).map((tab) => (
              <button
                key={tab.key}
                type="button"
                onClick={() => setMode(tab.key)}
                className={cn(
                  'rounded-full px-3.5 py-1.5 text-[13px] font-medium transition-colors',
                  mode === tab.key
                    ? 'bg-panel text-ink shadow-sm'
                    : 'text-ink-faint hover:text-ink',
                )}
              >
                {tab.label}
              </button>
            ))}
          </div>
        </div>

        {mode === 'file' ? (
          <div
            onDragOver={(event) => {
              event.preventDefault()
              setDragging(true)
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={onDrop}
            className={cn(
              'flex flex-col items-center rounded-2xl border-2 border-dashed px-6 py-12 text-center',
              'transition-[border-color,background-color] duration-200',
              dragging ? 'border-brand bg-brand-wash' : 'border-line-strong bg-surface-soft',
            )}
          >
            <span
              className={cn(
                'mb-4 grid size-12 place-items-center rounded-full border transition-transform duration-200 [&_svg]:size-6',
                dragging
                  ? 'scale-105 border-brand bg-panel text-brand'
                  : 'border-brand-line bg-brand-wash text-brand',
              )}
            >
              <UploadIcon />
            </span>
            <h3 className="text-[17px] font-semibold tracking-[-0.02em] text-ink">
              Try it on your own video
            </h3>
            <p className="mt-2 max-w-[46ch] text-[13.5px] leading-relaxed text-ink-dim">
              Drop in an MP4, MOV or WebM. It indexes in minutes and every frame
              becomes searchable — no account needed.
            </p>
            <Button
              onClick={() => inputRef.current?.click()}
              disabled={phase === 'uploading'}
              className="mt-5 [&_svg]:size-4"
            >
              {phase === 'uploading' ? <Spinner /> : <UploadIcon />}
              {phase === 'uploading'
                ? `Uploading… ${Math.round(uploadProgress * 100)}%`
                : 'Upload a video'}
            </Button>
            <p className="mt-3.5 flex items-center gap-1.5 text-[12px] text-ink-faint">
              <ClockIcon className="size-3.5" />
              Temporary — your video and searches are deleted after {TRIAL_MINUTES} minutes.
            </p>
            {error && <p className="mt-2 text-[13px] text-danger">{error}</p>}
            <input
              ref={inputRef}
              type="file"
              accept="video/*"
              className="sr-only"
              onChange={(event) => {
                const file = event.target.files?.[0]
                if (file) void ingest(file)
                event.target.value = ''
              }}
            />
          </div>
        ) : (
          <div className="flex flex-col items-center rounded-2xl border-2 border-dashed px-6 py-10 text-center">
            <span className="mb-4 grid size-12 place-items-center rounded-full border border-brand-line bg-brand-wash text-brand [&_svg]:size-6">
              <LinkIcon />
            </span>
            <h3 className="text-[17px] font-semibold tracking-[-0.02em] text-ink">
              Or search a video from the web
            </h3>
            <p className="mt-2 max-w-[46ch] text-[13.5px] leading-relaxed text-ink-dim">
              YouTube, Vimeo, Twitch or any direct video URL. The server
              downloads and indexes it — same 30-minute trial clock applies.
            </p>
            <textarea
              value={urlInput}
              onChange={(event) => setUrlInput(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter' && !event.shiftKey) {
                  event.preventDefault()
                  const url = extractUrl(urlInput)
                  if (url) void ingestUrl(url)
                }
              }}
              rows={2}
              placeholder="https://www.youtube.com/watch?v=…"
              aria-label="Video URL"
              className="mt-5 w-full max-w-[440px] resize-none rounded-lg border border-line-strong bg-panel px-3.5 py-2.5 text-[13.5px] text-ink outline-none placeholder:text-ink-faint focus:border-brand"
            />
            <Button
              onClick={() => {
                const url = extractUrl(urlInput)
                if (url) void ingestUrl(url)
                else setError('Paste a link starting with https:// — or switch to file upload.')
              }}
              disabled={phase === 'importing'}
              className="mt-3.5 [&_svg]:size-4"
            >
              {phase === 'importing' ? <Spinner /> : <LinkIcon />}
              {phase === 'importing' ? 'Starting import…' : 'Import and search'}
            </Button>
            <p className="mt-3.5 flex items-center gap-1.5 text-[12px] text-ink-faint">
              <ClockIcon className="size-3.5" />
              Temporary — deleted after {TRIAL_MINUTES} minutes, same as uploads.
            </p>
            {error && <p className="mt-2 text-[13px] text-danger">{error}</p>}
          </div>
        )}
      </div>
    )
  }

  // ── Phase: upload done, indexing ────────────────────────────
  if (phase === 'indexing') {
    const ratio =
      video.framesTotal > 0 ? Math.min(1, video.frames / video.framesTotal) : 0
    return (
      <Card className="p-6">
        <div className="flex items-center gap-3">
          <Spinner />
          <div className="min-w-0 flex-1">
            <b className="block truncate text-[14.5px] font-semibold text-ink">
              Indexing {video.name}
            </b>
            <span className="block text-[12.5px] text-ink-faint">
              {video.framesTotal > 0
                ? `${video.frames} of ${video.framesTotal} frames embedded`
                : 'Probing the file…'}
            </span>
          </div>
          {video.framesTotal > 0 && (
            <span className="font-mono text-[12px] text-ink-mid">
              {Math.round(ratio * 100)}%
            </span>
          )}
        </div>
        <div className="mt-4 h-1.5 overflow-hidden rounded-full bg-surface-sunk">
          <i
            className="block h-full rounded-full bg-brand transition-[width] duration-500"
            style={{ width: `${Math.max(4, ratio * 100)}%` }}
          />
        </div>
        <p className="mt-3 flex items-center gap-1.5 text-[12px] text-ink-faint">
          <ClockIcon className="size-3.5" />
          Deleted after {TRIAL_MINUTES} minutes — long enough to test, short
          enough to stay private.
        </p>
      </Card>
    )
  }

  // ── Phase: ready — the actual demo surface ──────────────────
  const topScore = Math.max(...(clips ?? []).map((c) => c.score), 0.001)
  const canSearch = video.status === 'ready' && Boolean(prompt.trim()) && !searching

  return (
    <div className="flex flex-col gap-5">
      {/* Search composer */}
      <Card className="p-3 sm:p-4">
        <div className="flex flex-wrap items-center gap-2">
          <span className="min-w-0 flex-1 truncate text-[13.5px] font-medium text-ink">
            {video.name}
          </span>
          {video.status === 'ready' ? (
            <span className="rounded-full border border-line bg-surface-soft px-2.5 py-1 text-[12px] font-medium text-ink-mid">
              Indexed
            </span>
          ) : (
            <span className="rounded-full border border-line bg-surface-soft px-2.5 py-1 text-[12px] font-medium text-ink-mid">
              Indexing…
            </span>
          )}
        </div>

        <textarea
          ref={promptRef}
          value={prompt}
          onChange={(event) => setPrompt(event.target.value)}
          onKeyDown={onPromptKey}
          rows={2}
          placeholder="Describe the scene — “a red car driving on a highway at sunset”"
          aria-label="Describe the scene you're looking for"
          className="mt-3 block w-full resize-none bg-transparent px-1.5 text-[16px] leading-relaxed text-ink outline-none placeholder:text-ink-faint"
        />

        <div className="mt-2 flex flex-wrap items-center gap-2 border-t border-line pt-3">
          <div className="flex min-w-0 flex-1 flex-wrap gap-1.5">
            {SUGGESTIONS.slice(0, 2).map((suggestion) => (
              <button
                key={suggestion}
                type="button"
                onClick={() => {
                  setPrompt(suggestion)
                  void runSearch(suggestion)
                }}
                className="inline-flex items-center gap-1.5 rounded-full border border-line bg-surface-soft px-2.5 py-1 text-[12px] text-ink-dim transition-colors hover:border-brand-line hover:bg-brand-wash hover:text-brand [&_svg]:size-3.5"
              >
                <SparkIcon />
                {suggestion}
              </button>
            ))}
          </div>
          <Button
            disabled={!canSearch}
            onClick={() => void runSearch(prompt)}
            className="[&_svg]:size-4"
          >
            {searching ? <Spinner /> : <SearchIcon />}
            {searching ? 'Searching' : 'Find clips'}
          </Button>
        </div>
      </Card>

      {video.status === 'processing' && (
        <p className="flex items-center gap-2 px-1 text-[13px] text-ink-dim">
          <Spinner className="size-3.5" />
          Indexing is still running — search unlocks once every frame is embedded.
        </p>
      )}

      {/* Results */}
      {searching && (
        <div>
          <h3 className="mb-3 text-[15px] font-semibold tracking-[-0.015em] text-ink">
            Scanning indexed frames…
          </h3>
          <div className="grid grid-cols-[repeat(auto-fill,minmax(200px,1fr))] gap-3.5">
            {Array.from({ length: 6 }, (_, index) => (
              <div
                key={index}
                className="overflow-hidden rounded-2xl border border-line bg-panel p-2.5"
              >
                <Shimmer className="aspect-video w-full rounded-xl" />
                <Shimmer className="mt-2.5 h-3 w-2/3" />
              </div>
            ))}
          </div>
        </div>
      )}

      {!searching && clips && (
        <div>
          <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
            <h3 className="text-[15px] font-semibold tracking-[-0.015em] text-ink">
              {searchError
                ? 'Search couldn’t run'
                : `${clips.length} ${clips.length === 1 ? 'match' : 'matches'} for “${lastQuery}”`}
            </h3>
            {clips.length > 0 && (
              <span className="text-[12px] text-ink-faint">
                Click a clip to watch it · downloads need an account
              </span>
            )}
          </div>

          {clips.length === 0 ? (
            <Card className="px-6 py-10 text-center">
              <p className="text-[14px] font-medium text-ink">
                {searchError ? 'Search couldn’t run' : 'No scene matched'}
              </p>
              <p className="mx-auto mt-1.5 max-w-[46ch] text-[13px] leading-relaxed text-ink-dim">
                {searchError ??
                  'Nothing in this video matches your description. Try describing what’s visible — objects, setting, colours — rather than what’s said.'}
              </p>
            </Card>
          ) : (
            <div className="grid grid-cols-[repeat(auto-fill,minmax(200px,1fr))] gap-3.5">
              {clips.map((clip, index) => (
                <ClipResultCard
                  key={clip.id}
                  clip={clip}
                  index={index}
                  topScore={topScore}
                  thumb={thumbs.get(clip.frame)}
                  onOpen={setOpenClip}
                />
              ))}
            </div>
          )}
        </div>
      )}

      {!searching && !clips && (
        <p className="px-1 text-[13px] text-ink-dim">
          Once indexed, describe a moment and matching clips appear here.
        </p>
      )}

      {/* Retention notice + conversion — always visible once a video exists. */}
      <div className="flex flex-col gap-3 rounded-2xl border border-line bg-surface-soft px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
        <p className="flex items-center gap-2 text-[13px] text-ink-mid">
          <ClockIcon className="size-4 shrink-0 text-ink-faint" />
          {left !== null ? (
            <>
              Temporary — this video and its searches are deleted in{' '}
              <b className="font-mono font-semibold text-ink">{mmss(left)}</b>.
            </>
          ) : (
            <>
              Temporary — this video and its searches are deleted after{' '}
              {TRIAL_MINUTES} minutes.
            </>
          )}
        </p>
        <div className="flex shrink-0 items-center gap-2">
          <ButtonLink as={Link} to="/signup" size="sm">
            Sign up to keep clips
          </ButtonLink>
          <ButtonLink as={Link} to="/pricing" variant="ghost" size="sm">
            See pricing
          </ButtonLink>
        </div>
      </div>

      <ClipLightbox
        clip={openClip}
        clips={clips ?? (openClip ? [openClip] : [])}
        video={video}
        src={src}
        prompt={lastQuery}
        onSelect={setOpenClip}
        onClose={() => setOpenClip(null)}
        locked
        onLockedAction={() =>
          setPaywall(
            openClip
              ? `download this clip (${timecode(openClip.start)}–${timecode(openClip.end)})`
              : 'download clips',
          )
        }
      />

      <PaywallModal
        open={paywall !== null}
        onClose={() => setPaywall(null)}
        feature={paywall ?? 'use this feature'}
      />
    </div>
  )
}
