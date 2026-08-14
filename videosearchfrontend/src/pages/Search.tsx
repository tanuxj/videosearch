import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { KeyboardEvent } from 'react'
import { useLocation } from '../lib/router'
import { useAuth } from '../lib/auth'
import {
  attachSource,
  captureFrames,
  saveSearchRecord,
  sourceFor,
  streamSourceFor,
  useVideos,
} from '../lib/store'
import type { VideoRecord } from '../lib/store'
import { API_ENABLED } from '../lib/http'
import { SUGGESTIONS, searchClips, startRemoteIndex } from '../lib/api'
import type { Clip, SearchEngine, TranscriptSegment } from '../lib/api'
import { AppShell } from '../components/Shell'
import { VideoSelect } from '../components/VideoSelect'
import { UploadDialog } from '../components/UploadDialog'
import { ClipLightbox } from '../components/ClipLightbox'
import { TranscriptPanel } from '../components/TranscriptPanel'
import { Button } from '../components/ui/Button'
import { Card } from '../components/ui/Card'
import { Chip, EmptyState, Panel } from '../components/ui/Data'
import { Shimmer } from '../components/ui/Motion'
import { Spinner } from '../components/AuthLayout'
import { PlayIcon, SearchIcon, SparkIcon, UploadIcon } from '../components/Icons'
import { timecode } from '../lib/format'
import { cn } from '../lib/cn'

export default function Search() {
  const { user } = useAuth()
  const { query } = useLocation()
  const videos = useVideos(user?.id)

  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [prompt, setPrompt] = useState('')
  const [clips, setClips] = useState<Clip[] | null>(null)
  const [thumbs, setThumbs] = useState<Map<number, string>>(new Map())
  const [openClip, setOpenClip] = useState<Clip | null>(null)
  const [searching, setSearching] = useState(false)
  /**
   * Which index answers. CLIP is local and visual-only; Marengo is remote and
   * also searches speech, so it can answer "what was said" questions CLIP
   * structurally cannot.
   */
  const [engine, setEngine] = useState<SearchEngine>('clip')
  const [indexingRemote, setIndexingRemote] = useState(false)
  const [meta, setMeta] = useState<{
    source: string
    tookMs: number
    expanded?: boolean
  } | null>(null)
  const [searchError, setSearchError] = useState<string | null>(null)
  const [lastQuery, setLastQuery] = useState('')
  const [uploadOpen, setUploadOpen] = useState(query.get('upload') === '1')
  /** Object URL for the selected video — only set if the file was attached in
   *  this tab session, so re-attaching updates it directly. */
  const [src, setSrc] = useState('')

  const reattachRef = useRef<HTMLInputElement>(null)
  const promptRef = useRef<HTMLTextAreaElement>(null)

  // Pick the video from ?v=, else the newest one in the library.
  useEffect(() => {
    if (videos.length === 0) {
      setSelectedId(null)
      return
    }
    const wanted = query.get('v')
    setSelectedId((current) => {
      if (current && videos.some((video) => video.id === current)) return current
      if (wanted && videos.some((video) => video.id === wanted)) return wanted
      return videos[0]!.id
    })
  }, [videos, query])

  const selected: VideoRecord | null = useMemo(
    () => videos.find((video) => video.id === selectedId) ?? null,
    [videos, selectedId],
  )

  /**
   * Pick the engine that can actually answer for this video.
   *
   * With local CLIP indexing turned off server-side, new videos have no
   * frames at all — defaulting to `clip` would show an empty result set and
   * look broken. A video with a remote index and no local one can only be
   * searched remotely, so select that.
   */
  useEffect(() => {
    if (!selected) return
    const hasLocal = selected.framesTotal > 0
    const hasRemote = selected.remoteIndexStatus === 'ready'
    if (!hasLocal && hasRemote) setEngine('twelvelabs')
    else if (hasLocal && !hasRemote) setEngine('clip')
  }, [selected])

  // Switching videos invalidates the previous results.
  useEffect(() => {
    setClips(null)
    setThumbs(new Map())
    setOpenClip(null)
    setMeta(null)
    setSearchError(null)
  }, [selectedId])

  // Playback source: a local file attached this session, or the server's
  // stream (downloaded once as an authenticated blob) once the video is ready.
  const selectedStatus = selected?.status ?? null
  useEffect(() => {
    let cancelled = false
    if (!selectedId) {
      setSrc('')
      return
    }
    const attached = sourceFor(selectedId)
    if (attached) {
      setSrc(attached)
      return
    }
    if (API_ENABLED && selectedStatus === 'ready') {
      streamSourceFor(selectedId)
        .then((streamUrl) => {
          if (!cancelled) setSrc(streamUrl)
        })
        .catch(() => {
          /* playback stays unavailable — results still rank */
        })
    } else {
      setSrc('')
    }
    return () => {
      cancelled = true
    }
  }, [selectedId, selectedStatus])

  /**
   * Play a transcript line. The lightbox is the only player in the page, so a
   * spoken segment is handed to it as a one-off clip rather than being added
   * to the search results — it isn't a match for the current prompt.
   */
  const playSegment = useCallback(
    (segment: TranscriptSegment) => {
      if (!selected) return
      setOpenClip({
        id: `transcript-${segment.start}`,
        videoId: selected.id,
        start: segment.start,
        // Zero-length cues exist; give the player something to actually play.
        end: Math.max(segment.end, segment.start + 1),
        frame: segment.start,
        score: 1,
      })
    },
    [selected],
  )

  /**
   * What the lightbox pages through. A transcript line isn't part of the
   * result set, so it opens as a set of one instead of reporting itself as
   * "match 0 of N" with dead prev/next arrows.
   */
  const lightboxClips = useMemo(() => {
    const results = clips ?? []
    if (openClip && !results.some((item) => item.id === openClip.id)) {
      return [openClip]
    }
    return results
  }, [clips, openClip])

  /**
   * Build the remote index for the selected video.
   *
   * Fire-and-forget: the server answers as soon as the job is queued, and the
   * library poll (which treats `processing` as still-settling) carries the
   * status the rest of the way.
   */
  async function enableRemoteIndex() {
    if (!selected) return
    setIndexingRemote(true)
    try {
      await startRemoteIndex(selected.id)
    } catch {
      /* the status chip reports the failure on the next poll */
    } finally {
      setIndexingRemote(false)
    }
  }

  async function runSearch(text: string) {
    const trimmed = text.trim()
    const target = selected
    if (!trimmed || !target) return
    const ready =
      engine === 'twelvelabs'
        ? target.remoteIndexStatus === 'ready'
        : target.status === 'ready'
    if (!ready) return

    setSearching(true)
    setOpenClip(null)
    setThumbs(new Map())
    setLastQuery(trimmed)
    setSearchError(null)

    const result = await searchClips(target, trimmed, 9, engine)
    setClips(result.clips)
    setMeta({
      source: result.source,
      tookMs: result.tookMs,
      expanded: result.expanded,
    })
    setSearchError(result.error ?? null)
    setSearching(false)

    // Remember the search for the History page — only when it actually ran.
    // The clips are a snapshot, so history replays the exact result shown.
    if (user && !result.error) {
      void saveSearchRecord(user.id, {
        videoId: target.id,
        prompt: trimmed,
        clips: result.clips,
        expanded: result.expanded ?? false,
        minScore: result.minScore,
      })
    }
  }

  // A deep link from the History page ("Re-run this search") arrives as
  // ?v=<video>&q=<prompt>: pick the video as usual, then run the search once
  // the video is ready. The ref guards against re-running on every render.
  const autoRanQueryRef = useRef<string | null>(null)
  useEffect(() => {
    const q = query.get('q')
    if (!q || autoRanQueryRef.current === q) return
    if (!selected || selected.status !== 'ready') return
    autoRanQueryRef.current = q
    setPrompt(q)
    void runSearch(q)
    // runSearch is stable enough for this effect's purposes — it closes over
    // the current `selected`, which is already a dependency.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected, query])

  // Real thumbnails, captured from whichever playback source is live (a
  // locally-attached file, a downloaded blob, or the signed edge URL). The
  // source can finish loading after the search, so this re-runs whenever the
  // results or the source change, and cancels stale work on re-render.
  useEffect(() => {
    if (!clips || clips.length === 0 || !src) return
    let cancelled = false
    void captureFrames(
      src,
      clips.map((clip) => clip.frame),
    ).then((frames) => {
      if (!cancelled) setThumbs(frames)
    })
    return () => {
      cancelled = true
    }
  }, [clips, src])

  function onPromptKey(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      void runSearch(prompt)
    }
  }

  /**
   * The two engines have different readiness requirements: CLIP needs every
   * frame embedded locally, while Marengo is built remotely and cares nothing
   * for the local index. Gating both on `status === 'ready'` would block
   * speech search on a video whose frames are still grinding away.
   */
  const engineReady =
    engine === 'twelvelabs'
      ? selected?.remoteIndexStatus === 'ready'
      : selected?.status === 'ready'

  /**
   * Whether *any* index can answer a query about this video.
   *
   * With local indexing disabled a video reports `status: 'ready'` with zero
   * frames almost immediately, so `status` alone no longer means "usable" —
   * it only means the pipeline is no longer working on the file locally.
   */
  const searchable = Boolean(
    selected &&
      ((selected.status === 'ready' && selected.framesTotal > 0) ||
        selected.remoteIndexStatus === 'ready'),
  )

  const canSearch = Boolean(engineReady) && Boolean(prompt.trim()) && !searching

  return (
    <AppShell
      title="Find a scene"
      subtitle="Pick an indexed video, describe the moment, and jump straight to it."
      actions={
        <Button
          variant="secondary"
          size="sm"
          onClick={() => setUploadOpen(true)}
          className="[&_svg]:size-4"
        >
          <UploadIcon />
          Add video
        </Button>
      }
    >
      <div className="mx-auto w-full max-w-[900px]">
        {/* ── Composer ─────────────────────────────────────── */}
        <Card className="p-3 sm:p-4">
          <div className="flex flex-wrap items-center gap-2">
            <VideoSelect
              videos={videos}
              selectedId={selectedId}
              onSelect={setSelectedId}
              onUpload={() => setUploadOpen(true)}
            />
            {/* Reports whether the video is *searchable*, which is not the
                same as `status === 'ready'` once local CLIP indexing is off:
                such a video is "ready" with zero frames the moment it is
                probed, while the only index that can answer is still being
                built remotely. Claiming "Indexed" there is simply untrue. */}
            {selected &&
              (selected.status === 'failed' ? (
                <Chip tone="danger">Indexing failed</Chip>
              ) : searchable ? (
                <Chip tone="ok">Searchable</Chip>
              ) : selected.remoteIndexStatus === 'failed' ? (
                <Chip tone="danger">Indexing failed</Chip>
              ) : (
                <Chip tone="warn" pulse>
                  Indexing
                </Chip>
              ))}

            {/* Engine switch. Only shown when there is a real choice — with
                no remote index the toggle would offer an option that always
                errors. */}
            {selected && API_ENABLED && (
              <div className="ml-auto flex items-center gap-1.5">
                <div
                  role="group"
                  aria-label="Search engine"
                  className="flex rounded-lg border border-line p-0.5"
                >
                  {(
                    [
                      ['clip', 'Visual', 'Local CLIP index — matches what the camera saw'],
                      ['twelvelabs', 'Visual + speech', 'Twelve Labs Marengo — also searches what was said'],
                    ] as const
                  ).map(([value, label, title]) => (
                    <button
                      key={value}
                      type="button"
                      title={title}
                      aria-pressed={engine === value}
                      disabled={value === 'twelvelabs' && selected.remoteIndexStatus !== 'ready'}
                      onClick={() => setEngine(value)}
                      className={cn(
                        'cursor-pointer rounded-md px-2.5 py-1 text-[12px] font-medium transition-colors',
                        engine === value
                          ? 'bg-brand-wash text-brand'
                          : 'text-ink-dim hover:text-ink',
                        'disabled:cursor-default disabled:opacity-40',
                      )}
                    >
                      {label}
                    </button>
                  ))}
                </div>

                {selected.remoteIndexStatus === 'processing' ? (
                  <Chip tone="brand" pulse>
                    Indexing remotely
                  </Chip>
                ) : selected.remoteIndexStatus !== 'ready' ? (
                  <button
                    type="button"
                    disabled={indexingRemote}
                    onClick={() => void enableRemoteIndex()}
                    title="Build a Twelve Labs index for this video so speech becomes searchable"
                    className="cursor-pointer text-[12px] font-medium text-brand underline underline-offset-2 transition-opacity hover:opacity-75 disabled:opacity-50"
                  >
                    {indexingRemote ? 'Starting…' : 'Enable speech search'}
                  </button>
                ) : null}
              </div>
            )}
          </div>

          <textarea
            ref={promptRef}
            value={prompt}
            onChange={(event) => setPrompt(event.target.value)}
            onKeyDown={onPromptKey}
            rows={3}
            placeholder={
              selected
                ? 'Describe the scene — “a red car driving on a highway at sunset”'
                : 'Add a video first, then describe the scene you want to find'
            }
            aria-label="Describe the scene you're looking for"
            className="mt-3 block w-full resize-none bg-transparent px-1.5 text-[16.5px] leading-relaxed text-ink outline-none placeholder:text-ink-faint"
          />

          <div className="mt-2 flex flex-wrap items-center gap-2 border-t border-line pt-3">
            <div className="flex min-w-0 flex-1 flex-wrap gap-1.5">
              {selected &&
                SUGGESTIONS.slice(0, 3).map((suggestion) => (
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

            <span className="hidden text-[12px] text-ink-faint sm:inline">
              <kbd className="rounded border border-line-strong bg-surface-soft px-1.5 py-0.5 font-mono text-[11px]">
                ⏎
              </kbd>{' '}
              to search
            </span>
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

        {selected && !src && selected.status !== 'failed' && (
          <p className="mt-3 flex flex-wrap items-center gap-x-1.5 gap-y-1 px-1 text-[13px] text-ink-dim">
            {selected.status === 'processing'
              ? 'Indexing is still running — search unlocks once every frame is embedded.'
              : API_ENABLED
                ? 'Loading playback from your library…'
                : 'Playback for this video isn’t attached to this tab — results still rank, but you’ll need the file to watch them.'}
            {!API_ENABLED && (
              <>
                <button
                  type="button"
                  onClick={() => reattachRef.current?.click()}
                  className="font-medium text-brand underline underline-offset-2 transition-opacity hover:opacity-75"
                >
                  Re-attach file
                </button>
                <input
                  ref={reattachRef}
                  type="file"
                  accept="video/*"
                  className="sr-only"
                  onChange={(event) => {
                    const file = event.target.files?.[0]
                    if (file && selected) setSrc(attachSource(selected.id, file))
                    event.target.value = ''
                  }}
                />
              </>
            )}
          </p>
        )}

        {/* Directly under the composer, inside the same column: the transcript
            belongs to the selected video, so it should be readable the moment
            one is picked — not buried under a page of search results. */}
        <TranscriptPanel video={selected} onSeek={playSegment} />
      </div>

      {searching && (
        <div className="mt-8">
          <h2 className="mb-4 text-[15.5px] font-semibold tracking-[-0.015em] text-ink">
            Scanning indexed frames…
          </h2>
          <div className="grid grid-cols-[repeat(auto-fill,minmax(220px,1fr))] gap-4">
            {Array.from({ length: 8 }, (_, index) => (
              <div
                key={index}
                className="overflow-hidden rounded-2xl border border-line bg-panel p-2.5"
              >
                <Shimmer className="aspect-video w-full rounded-xl" />
                <Shimmer className="mt-2.5 h-3 w-2/3" />
                <Shimmer className="mt-2 h-2 w-full" />
              </div>
            ))}
          </div>
        </div>
      )}

      {!searching && clips && (
        <div className="mt-8">
          <div className="mb-4 flex flex-wrap items-baseline justify-between gap-2">
            <h2 className="text-[15.5px] font-semibold tracking-[-0.015em] text-ink">
              {searchError
                ? 'Search couldn’t run'
                : `${clips.length} ${clips.length === 1 ? 'match' : 'matches'} for “${lastQuery}”`}
            </h2>
            {meta && (
              <span className="text-[12.5px] text-ink-faint">
                {meta.tookMs} ms ·{' '}
                {meta.source === 'api'
                  ? 'ranked by backend'
                  : 'demo ranking (no backend configured)'}
                {meta.expanded && ' · query expanded'}
              </span>
            )}
          </div>

          {clips.length === 0 ? (
            <Panel>
              <EmptyState
                icon={<SearchIcon />}
                title={searchError ? 'Search couldn’t run' : 'No scene matched'}
                body={
                  searchError ??
                  'Nothing in this video matches your description. Try rewording it, or describe what’s visible — objects, setting, colours — rather than what’s said.'
                }
              />
            </Panel>
          ) : (
            <div className="grid grid-cols-[repeat(auto-fill,minmax(220px,1fr))] gap-4">
              {clips.map((clip, index) => {
                const thumb = thumbs.get(clip.frame)
                // Rank-relative confidence: the best scene in this result set
                // always reads 100%, weaker scenes scale down from it. CLIP's
                // raw cosine similarities are compressed (~0.25–0.45 for real
                // matches), so an absolute scale would make every real match
                // look like a near-miss.
                const topScore = Math.max(...clips.map((c) => c.score))
                const percent = Math.round((clip.score / Math.max(topScore, 0.001)) * 100)
                return (
                  // `group` is required here — the play overlay below reveals
                  // itself with `group-hover`.
                  <Card key={clip.id} className="group h-full" interactive>
                      <button
                        type="button"
                        onClick={() => setOpenClip(clip)}
                        className="block w-full cursor-pointer p-2.5 text-left"
                      >
                        <span className="relative block aspect-video overflow-hidden rounded-xl border border-line bg-surface-sunk">
                          {thumb ? (
                            <img
                              src={thumb}
                              alt=""
                              className="size-full object-cover"
                            />
                          ) : (
                            <span className="grid size-full place-items-center bg-surface-sunk text-brand [&_svg]:size-6">
                              <PlayIcon />
                            </span>
                          )}

                          {/* Rank — the only place the result's position is stated. */}
                          <span className="absolute top-2 left-2 rounded-md bg-ink/70 px-1.5 py-0.5 font-mono text-[11px] font-medium text-white">
                            #{index + 1}
                          </span>

                          <span className="absolute inset-0 grid place-items-center bg-ink/0 opacity-0 transition-[opacity,background-color] duration-200 group-hover:bg-ink/20 group-hover:opacity-100">
                            <i className="grid size-11 place-items-center rounded-full bg-panel text-brand [&_svg]:size-5">
                              <PlayIcon />
                            </i>
                          </span>

                          <span className="absolute right-2 bottom-2 rounded-md bg-ink/70 px-1.5 py-0.5 font-mono text-[11px] text-white">
                            {timecode(clip.start)} – {timecode(clip.end)}
                          </span>
                        </span>

                        <span className="mt-2.5 block px-0.5">
                          <span className="block truncate text-[13.5px] font-medium text-ink">
                            {clip.text ? `Said at ${timecode(clip.start)}` : `Frame at ${timecode(clip.frame)}`}
                          </span>

                          {/* Marengo returns the speech that matched — it is
                              the clearest possible answer to "why this clip?",
                              which a similarity number never is. */}
                          {clip.text && (
                            <span className="mt-1 line-clamp-2 block text-[12.5px] leading-snug text-ink-dim">
                              “{clip.text}”
                            </span>
                          )}

                          {/* Match meter. Track is a lighter step of the same
                              hue as the fill so the whole bar reads as one
                              scale; the value stays in ink, the bar carries
                              the colour. */}
                          <span className="mt-2 flex items-center gap-2">
                            <span className="relative block h-1.5 flex-1 overflow-hidden rounded-full bg-brand-wash">
                              <i
                                className="absolute inset-y-0 left-0 rounded-full bg-brand"
                                style={{ width: `${percent}%` }}
                              />
                            </span>
                            <span className="shrink-0 text-[12px] font-semibold text-ink-mid">
                              {percent}%
                            </span>
                          </span>
                        </span>
                      </button>
                    </Card>
                )
              })}
            </div>
          )}
        </div>
      )}

      {!searching && !clips && (
        <div className="mx-auto mt-10 w-full max-w-[900px]">
          <div className="mb-5 text-center">
            <h2 className="text-[19px] font-semibold tracking-[-0.02em] text-ink">
              {selected ? 'Try describing…' : 'Start by adding a video'}
            </h2>
            <p className="mx-auto mt-2 max-w-[58ch] text-[14px] leading-relaxed text-ink-dim">
              {selected
                ? 'Matching runs on what the camera saw, so describe the visuals rather than the dialogue.'
                : 'Once a video is indexed, every second of it becomes searchable by description.'}
            </p>
          </div>

          {selected ? (
            <div className="grid grid-cols-[repeat(auto-fill,minmax(240px,1fr))] gap-3">
              {SUGGESTIONS.map((suggestion) => (
                <Card key={suggestion} className="h-full" interactive>
                    <button
                      type="button"
                      onClick={() => {
                        setPrompt(suggestion)
                        void runSearch(suggestion)
                      }}
                      className="flex w-full cursor-pointer items-start gap-2.5 p-3.5 text-left"
                    >
                      <span className="mt-px grid size-7 shrink-0 place-items-center rounded-lg border border-brand-line bg-brand-wash text-brand [&_svg]:size-3.5">
                        <SparkIcon />
                      </span>
                      <span className="text-[13.5px] leading-snug text-ink-mid">
                        {suggestion}
                      </span>
                    </button>
                  </Card>
              ))}
            </div>
          ) : (
            <div className="flex justify-center">
              <Button
                size="lg"
                onClick={() => setUploadOpen(true)}
                className="[&_svg]:size-[18px]"
              >
                <UploadIcon />
                Add your first video
              </Button>
            </div>
          )}
        </div>
      )}

      <UploadDialog
        open={uploadOpen}
        onClose={() => setUploadOpen(false)}
        onReady={(video) => {
          setSelectedId(video.id)
          promptRef.current?.focus()
        }}
      />

      <ClipLightbox
        clip={openClip}
        clips={lightboxClips}
        video={selected}
        src={src}
        prompt={lastQuery}
        onSelect={setOpenClip}
        onClose={() => setOpenClip(null)}
      />
    </AppShell>
  )
}
