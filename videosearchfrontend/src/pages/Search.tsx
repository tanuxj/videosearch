import { useEffect, useMemo, useRef, useState } from 'react'
import type { KeyboardEvent } from 'react'
import { Link, useLocation } from '../lib/router'
import { useAuth } from '../lib/auth'
import { attachSource, captureFrames, sourceFor, useVideos } from '../lib/store'
import type { VideoRecord } from '../lib/store'
import { SUGGESTIONS, searchClips } from '../lib/api'
import type { Clip } from '../lib/api'
import { AppShell } from '../components/Shell'
import {
  FilmIcon,
  PlayIcon,
  SearchIcon,
  SparkIcon,
  UploadIcon,
} from '../components/Icons'
import { humanDuration, timecode } from '../lib/format'

export default function Search() {
  const { user } = useAuth()
  const { query } = useLocation()
  const videos = useVideos(user?.id)

  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [prompt, setPrompt] = useState('')
  const [clips, setClips] = useState<Clip[] | null>(null)
  const [thumbs, setThumbs] = useState<Map<number, string>>(new Map())
  const [activeClip, setActiveClip] = useState<string | null>(null)
  const [searching, setSearching] = useState(false)
  const [meta, setMeta] = useState<{ source: string; tookMs: number } | null>(
    null,
  )
  const [lastQuery, setLastQuery] = useState('')

  const playerRef = useRef<HTMLVideoElement>(null)
  const reattachRef = useRef<HTMLInputElement>(null)
  /** Object URL for the selected video — only present if it was attached in
   *  this tab session, so re-attaching updates it directly. */
  const [src, setSrc] = useState('')

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
    setSrc(selectedId ? (sourceFor(selectedId) ?? '') : '')
    setClips(null)
    setThumbs(new Map())
    setActiveClip(null)
    setMeta(null)
  }, [selectedId])

  async function runSearch(text: string) {
    const trimmed = text.trim()
    if (!trimmed || !selected) return

    setSearching(true)
    setActiveClip(null)
    setThumbs(new Map())
    setLastQuery(trimmed)

    const result = await searchClips(selected, trimmed)
    setClips(result.clips)
    setMeta({ source: result.source, tookMs: result.tookMs })
    setSearching(false)

    // Real thumbnails, pulled from the file that's already in the browser.
    const source = sourceFor(selected.id)
    if (source && result.clips.length > 0) {
      const frames = await captureFrames(
        source,
        result.clips.map((clip) => clip.frame),
      )
      setThumbs(frames)
    }
  }

  function playClip(clip: Clip) {
    setActiveClip(clip.id)
    const player = playerRef.current
    if (!player || !src) return
    player.currentTime = clip.start
    void player.play().catch(() => {
      /* autoplay blocked — the user can hit play */
    })
  }

  function onPromptKey(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      void runSearch(prompt)
    }
  }

  if (videos.length === 0) {
    return (
      <AppShell
        title="Search clips"
        subtitle="Describe a scene and jump to the moment it happens."
      >
        <section className="panel" style={{ marginTop: 0 }}>
          <div className="empty">
            <span className="empty-icon">
              <FilmIcon />
            </span>
            <h3>Nothing indexed yet</h3>
            <p>
              Upload a video first — once its frames are embedded you can search
              it by description.
            </p>
            <Link to="/upload" className="btn btn-primary">
              <UploadIcon />
              Upload a video
            </Link>
          </div>
        </section>
      </AppShell>
    )
  }

  return (
    <AppShell
      title="Search clips"
      subtitle="Describe a scene in plain language — results are ranked by visual similarity."
      actions={
        <Link to="/upload" className="btn btn-ghost btn-sm">
          <UploadIcon />
          Upload
        </Link>
      }
    >
      {videos.length > 1 && (
        <div className="picker">
          {videos.map((video) => (
            <button
              key={video.id}
              type="button"
              className={`picker-item${video.id === selectedId ? ' is-active' : ''}`}
              onClick={() => setSelectedId(video.id)}
            >
              <span className="picker-dot">
                <PlayIcon />
              </span>
              {video.name}
            </button>
          ))}
        </div>
      )}

      <div className="search-layout">
        <div>
          <div className="prompt-bar">
            <div className="prompt-input">
              <textarea
                value={prompt}
                onChange={(event) => setPrompt(event.target.value)}
                onKeyDown={onPromptKey}
                placeholder="e.g. a red car driving on a highway at sunset"
                aria-label="Describe the scene you're looking for"
              />
              <button
                type="button"
                className="btn btn-primary"
                style={{ height: 46 }}
                disabled={searching || !prompt.trim()}
                onClick={() => void runSearch(prompt)}
              >
                {searching ? <span className="spinner" /> : <SearchIcon />}
                {searching ? 'Searching' : 'Search'}
              </button>
            </div>

            <div className="prompt-foot">
              {SUGGESTIONS.slice(0, 3).map((suggestion) => (
                <button
                  key={suggestion}
                  type="button"
                  className="suggest"
                  onClick={() => {
                    setPrompt(suggestion)
                    void runSearch(suggestion)
                  }}
                >
                  <SparkIcon /> {suggestion}
                </button>
              ))}
              <span className="hint">Enter to search · Shift + Enter for a new line</span>
            </div>
          </div>

          {searching && (
            <>
              <div className="results-head">
                <h2>Searching frames…</h2>
              </div>
              <div className="clip-grid">
                {Array.from({ length: 6 }, (_, index) => (
                  <div key={index} className="skeleton" />
                ))}
              </div>
            </>
          )}

          {!searching && clips && (
            <>
              <div className="results-head">
                <h2>
                  {clips.length} {clips.length === 1 ? 'clip' : 'clips'} for “
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
                      Try describing what’s visible in the shot — objects,
                      setting, colours — rather than what’s said.
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
                        className={`clip${activeClip === clip.id ? ' is-playing' : ''}`}
                        style={{ animationDelay: `${index * 30}ms` }}
                        onClick={() => playClip(clip)}
                      >
                        <span className="clip-thumb">
                          {thumb ? (
                            <img src={thumb} alt="" />
                          ) : (
                            <span className="clip-thumb-fallback">
                              Frame at {timecode(clip.frame)}
                            </span>
                          )}
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
                            Match #{index + 1} · frame at {timecode(clip.frame)}
                          </span>
                          <span className="clip-foot">
                            <span className="match">
                              <i
                                style={{
                                  width: `${Math.round(clip.score * 100)}%`,
                                }}
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
            <section className="panel">
              <div className="empty">
                <span className="empty-icon">
                  <SparkIcon />
                </span>
                <h3>Describe what you’re looking for</h3>
                <p>
                  Matching runs on what the camera saw, so describe the visuals:
                  “two people shaking hands in an office”, “a close-up of a
                  laptop screen”.
                </p>
                <div
                  style={{
                    display: 'flex',
                    gap: 8,
                    flexWrap: 'wrap',
                    justifyContent: 'center',
                  }}
                >
                  {SUGGESTIONS.map((suggestion) => (
                    <button
                      key={suggestion}
                      type="button"
                      className="suggest"
                      onClick={() => {
                        setPrompt(suggestion)
                        void runSearch(suggestion)
                      }}
                    >
                      {suggestion}
                    </button>
                  ))}
                </div>
              </div>
            </section>
          )}
        </div>

        <aside className="player-card">
          <div className="player-frame">
            {src ? (
              <video ref={playerRef} src={src} controls playsInline />
            ) : (
              <div className="player-placeholder">
                <FilmIcon />
                <p>
                  The video file isn’t attached to this tab. Re-attach it to play
                  matches back.
                </p>
                <button
                  type="button"
                  className="btn btn-ghost btn-sm"
                  style={{ marginTop: 12 }}
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
              </div>
            )}
          </div>

          {selected && (
            <div className="player-meta">
              <span className="lib-thumb" style={{ width: 54, height: 32 }}>
                {selected.poster ? (
                  <img src={selected.poster} alt="" />
                ) : (
                  <PlayIcon />
                )}
              </span>
              <div style={{ minWidth: 0 }}>
                <b>{selected.name}</b>
                <span>
                  {humanDuration(selected.duration)} ·{' '}
                  {selected.frames.toLocaleString()} frames indexed
                </span>
              </div>
            </div>
          )}
        </aside>
      </div>
    </AppShell>
  )
}
