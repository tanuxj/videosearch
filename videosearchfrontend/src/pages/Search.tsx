import { useEffect, useMemo, useRef, useState } from 'react'
import type { KeyboardEvent } from 'react'
import { useLocation } from '../lib/router'
import { useAuth } from '../lib/auth'
import {
  attachSource,
  captureFrames,
  sourceFor,
  streamSourceFor,
  useVideos,
} from '../lib/store'
import type { VideoRecord } from '../lib/store'
import { API_ENABLED } from '../lib/http'
import { SUGGESTIONS, searchClips } from '../lib/api'
import type { Clip } from '../lib/api'
import { AppShell } from '../components/Shell'
import { VideoSelect } from '../components/VideoSelect'
import { UploadDialog } from '../components/UploadDialog'
import { ClipLightbox } from '../components/ClipLightbox'
import { PlayIcon, SearchIcon, SparkIcon, UploadIcon } from '../components/Icons'
import { timecode } from '../lib/format'

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
  const [meta, setMeta] = useState<{ source: string; tookMs: number } | null>(
    null,
  )
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

  // Switching videos invalidates the previous results.
  useEffect(() => {
    setClips(null)
    setThumbs(new Map())
    setOpenClip(null)
    setMeta(null)
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

  async function runSearch(text: string) {
    const trimmed = text.trim()
    const target = selected
    if (!trimmed || !target || target.status !== 'ready') return

    setSearching(true)
    setOpenClip(null)
    setThumbs(new Map())
    setLastQuery(trimmed)

    const result = await searchClips(target, trimmed)
    setClips(result.clips)
    setMeta({ source: result.source, tookMs: result.tookMs })
    setSearching(false)

    // Real thumbnails, pulled from the file that's already in the browser.
    const source = sourceFor(target.id)
    if (source && result.clips.length > 0) {
      setThumbs(
        await captureFrames(
          source,
          result.clips.map((clip) => clip.frame),
        ),
      )
    }
  }

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
        <button
          type="button"
          className="btn btn-ghost btn-sm"
          onClick={() => setUploadOpen(true)}
        >
          <UploadIcon />
          Add video
        </button>
      }
    >
      <div className="composer-wrap">
        <div className="composer">
          <div className="composer-top">
            <VideoSelect
              videos={videos}
              selectedId={selectedId}
              onSelect={setSelectedId}
              onUpload={() => setUploadOpen(true)}
            />
            {selected && (
              <span
                className={`chip ${
                  selected.status === 'ready'
                    ? 'chip-ok'
                    : selected.status === 'failed'
                      ? 'chip-bad'
                      : 'chip-warn'
                }`}
              >
                {selected.status === 'ready'
                  ? 'Indexed'
                  : selected.status === 'failed'
                    ? 'Indexing failed'
                    : 'Indexing'}
              </span>
            )}
          </div>

          <textarea
            ref={promptRef}
            className="composer-input"
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
          />

          <div className="composer-foot">
            <div className="composer-chips">
              {selected &&
                SUGGESTIONS.slice(0, 3).map((suggestion) => (
                  <button
                    key={suggestion}
                    type="button"
                    className="suggest"
                    onClick={() => {
                      setPrompt(suggestion)
                      void runSearch(suggestion)
                    }}
                  >
                    <SparkIcon />
                    {suggestion}
                  </button>
                ))}
            </div>

            <span className="composer-hint">⏎ to search</span>
            <button
              type="button"
              className="btn btn-primary"
              disabled={!canSearch}
              onClick={() => void runSearch(prompt)}
            >
              {searching ? <span className="spinner" /> : <SearchIcon />}
              {searching ? 'Searching' : 'Find clips'}
            </button>
          </div>
        </div>

        {selected && !src && selected.status !== 'failed' && (
          <p className="composer-note">
            {selected.status === 'processing'
              ? 'Indexing is still running — search unlocks once every frame is embedded.'
              : API_ENABLED
                ? 'Loading playback from your library…'
                : 'Playback for this video isn’t attached to this tab — results still rank, but you’ll need the file to watch them.'}
            {!API_ENABLED && (
              <>
                <button
                  type="button"
                  className="linkish"
                  onClick={() => reattachRef.current?.click()}
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
      </div>

      {searching && (
        <>
          <div className="results-head">
            <h2>Scanning indexed frames…</h2>
          </div>
          <div className="clip-grid">
            {Array.from({ length: 8 }, (_, index) => (
              <div key={index} className="skeleton" />
            ))}
          </div>
        </>
      )}

      {!searching && clips && (
        <>
          <div className="results-head">
            <h2>
              {clips.length} {clips.length === 1 ? 'match' : 'matches'} for “
              {lastQuery}”
            </h2>
            {meta && (
              <span>
                {meta.tookMs} ms ·{' '}
                {meta.source === 'api'
                  ? 'ranked by backend'
                  : 'demo ranking (no backend configured)'}
              </span>
            )}
          </div>

          {clips.length === 0 ? (
            <section className="panel" style={{ marginTop: 0 }}>
              <div className="empty">
                <span className="empty-icon">
                  <SearchIcon />
                </span>
                <h3>No frames matched</h3>
                <p>
                  Try describing what’s visible in the shot — objects, setting,
                  colours — rather than what’s said.
                </p>
              </div>
            </section>
          ) : (
            <div className="clip-grid">
              {clips.map((clip, index) => {
                const thumb = thumbs.get(clip.frame)
                return (
                  <button
                    key={clip.id}
                    type="button"
                    className="clip"
                    style={{ animationDelay: `${index * 28}ms` }}
                    onClick={() => setOpenClip(clip)}
                  >
                    <span className="clip-thumb">
                      {thumb ? (
                        <img src={thumb} alt="" />
                      ) : (
                        <span className="clip-thumb-fallback">
                          <PlayIcon />
                        </span>
                      )}
                      <span className="clip-rank">#{index + 1}</span>
                      <span className="clip-play">
                        <i>
                          <PlayIcon />
                        </i>
                      </span>
                      <span className="clip-time">
                        {timecode(clip.start)} – {timecode(clip.end)}
                      </span>
                    </span>
                    <span className="clip-body">
                      <span className="clip-title">
                        Frame at {timecode(clip.frame)}
                      </span>
                      <span className="clip-foot">
                        <span className="match">
                          <i
                            style={{ width: `${Math.round(clip.score * 100)}%` }}
                          />
                        </span>
                        <span className="match-val">
                          {Math.round(clip.score * 100)}%
                        </span>
                      </span>
                    </span>
                  </button>
                )
              })}
            </div>
          )}
        </>
      )}

      {!searching && !clips && (
        <div className="prompt-guide">
          <div className="prompt-guide-head">
            <h2>{selected ? 'Try describing…' : 'Start by adding a video'}</h2>
            <p>
              {selected
                ? 'Matching runs on what the camera saw, so describe the visuals rather than the dialogue.'
                : 'Once a video is indexed, every second of it becomes searchable by description.'}
            </p>
          </div>
          {selected ? (
            <div className="prompt-guide-grid">
              {SUGGESTIONS.map((suggestion) => (
                <button
                  key={suggestion}
                  type="button"
                  className="prompt-card"
                  onClick={() => {
                    setPrompt(suggestion)
                    void runSearch(suggestion)
                  }}
                >
                  <SparkIcon />
                  <span>{suggestion}</span>
                </button>
              ))}
            </div>
          ) : (
            <button
              type="button"
              className="btn btn-primary btn-lg"
              onClick={() => setUploadOpen(true)}
            >
              <UploadIcon />
              Add your first video
            </button>
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
        clips={clips ?? []}
        video={selected}
        src={src}
        prompt={lastQuery}
        onSelect={setOpenClip}
        onClose={() => setOpenClip(null)}
      />
    </AppShell>
  )
}
