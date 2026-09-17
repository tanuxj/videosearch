import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { KeyboardEvent } from 'react'
import { useLocation, useNavigate } from '../lib/router'
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
import { SINGLE_PAGE } from '../lib/features'
import { SUGGESTIONS, searchClips } from '../lib/api'
import type { Clip, TranscriptSegment } from '../lib/api'
import { AppShell } from '../components/Shell'
import { VideoSelect } from '../components/VideoSelect'
import { UploadDialog } from '../components/UploadDialog'
import { ClipLightbox } from '../components/ClipLightbox'
import { ClipResultCard } from '../components/ClipResultCard'
import { TranscriptPanel } from '../components/TranscriptPanel'
import { Button } from '../components/ui/Button'
import { Card } from '../components/ui/Card'
import { Chip, EmptyState, Panel } from '../components/ui/Data'
import { Shimmer } from '../components/ui/Motion'
import { Spinner } from '../components/AuthLayout'
import { MicIcon, SearchIcon, SparkIcon, UploadIcon } from '../components/Icons'

export default function Search() {
  const { user } = useAuth()
  const { query } = useLocation()
  const navigate = useNavigate()
  const videos = useVideos(user?.id)

  // Audio-only recordings (mic-only saves) have no frames to scene-search, so
  // they stay in the library — the picker only offers videos with a picture
  // track. `hasVideo` is undefined until the server probes the file, which is
  // treated as "has video" so processing uploads don't flicker out.
  const searchable = videos.filter((video) => video.hasVideo !== false)

  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [prompt, setPrompt] = useState('')
  const [clips, setClips] = useState<Clip[] | null>(null)
  const [thumbs, setThumbs] = useState<Map<number, string>>(new Map())
  const [openClip, setOpenClip] = useState<Clip | null>(null)
  const [searching, setSearching] = useState(false)
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
    if (searchable.length === 0) {
      setSelectedId(null)
      return
    }
    const wanted = query.get('v')
    setSelectedId((current) => {
      if (current && searchable.some((video) => video.id === current)) return current
      if (wanted && searchable.some((video) => video.id === wanted)) return wanted
      return searchable[0]!.id
    })
  }, [searchable, query])

  const selected: VideoRecord | null = useMemo(
    () => searchable.find((video) => video.id === selectedId) ?? null,
    [searchable, selectedId],
  )

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

  async function runSearch(text: string) {
    const trimmed = text.trim()
    const target = selected
    if (!trimmed || !target || target.status !== 'ready') return

    setSearching(true)
    setOpenClip(null)
    setThumbs(new Map())
    setLastQuery(trimmed)
    setSearchError(null)

    const result = await searchClips(target, trimmed)
    setClips(result.clips)
    setMeta({
      source: result.source,
      tookMs: result.tookMs,
      expanded: result.expanded,
    })
    setSearchError(result.error ?? null)
    setSearching(false)

    // Remember the search for the Clips page — only when it actually ran.
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

  // A deep link from the Clips page ("Re-run this search") arrives as
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

  const canSearch =
    selected?.status === 'ready' &&
    Boolean(prompt.trim()) &&
    !searching

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
              videos={searchable}
              selectedId={selectedId}
              onSelect={setSelectedId}
              onUpload={() => setUploadOpen(true)}
            />
            {selected &&
              (selected.status === 'ready' ? (
                <Chip tone="ok">Indexed</Chip>
              ) : selected.status === 'failed' ? (
                <Chip tone="danger">Indexing failed</Chip>
              ) : (
                <Chip tone="warn" pulse>
                  Indexing
                </Chip>
              ))}
            {selected?.source === 'recording' && (
              <Chip tone="brand" icon={<MicIcon />}>
                Recording
              </Chip>
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
              {clips.map((clip, index) => (
                <ClipResultCard
                  key={clip.id}
                  clip={clip}
                  index={index}
                  topScore={Math.max(...clips.map((c) => c.score), 0.001)}
                  thumb={thumbs.get(clip.frame)}
                  onOpen={setOpenClip}
                />
              ))}
            </div>
          )}
        </div>
      )}

      {!searching && !clips && (
        <div className="mx-auto mt-10 w-full max-w-[900px]">
          <div className="mb-5 text-center">
            <h2 className="text-[19px] font-semibold tracking-[-0.02em] text-ink">
              {selected
                ? 'Try describing…'
                : videos.length > 0
                  ? 'Nothing to search yet'
                  : 'Start by adding a video'}
            </h2>
            <p className="mx-auto mt-2 max-w-[58ch] text-[14px] leading-relaxed text-ink-dim">
              {selected
                ? 'Matching runs on what the camera saw, so describe the visuals rather than the dialogue.'
                : videos.length > 0
                  ? 'Your library only has audio recordings — they have no frames to search. Head to the library to read their transcripts.'
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
          ) : videos.length > 0 && !SINGLE_PAGE ? (
            // Only audio-only recordings in the library: there is nothing to
            // scene-search, so point at the page that can play them. Hidden in
            // single-page mode, where that page is folded away — the "add a
            // video" branch below is the useful thing to offer instead.
            <div className="flex justify-center">
              <Button
                variant="secondary"
                size="lg"
                onClick={() => navigate('/recordings')}
                className="[&_svg]:size-[18px]"
              >
                <MicIcon />
                Open recordings
              </Button>
            </div>
          ) : (
            <div className="flex justify-center">
              <Button
                size="lg"
                onClick={() => setUploadOpen(true)}
                className="[&_svg]:size-[18px]"
              >
                <UploadIcon />
                {/* "First" is wrong once the library holds something the
                    search cannot use — audio-only recordings in single-page
                    mode reach this branch too. */}
                {videos.length > 0 ? 'Add a video' : 'Add your first video'}
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
