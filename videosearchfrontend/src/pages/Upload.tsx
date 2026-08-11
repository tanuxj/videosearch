import { useEffect, useRef, useState } from 'react'
import type { DragEvent } from 'react'
import { Link, useNavigate } from '../lib/router'
import { useAuth } from '../lib/auth'
import {
  attachSource,
  captureFrames,
  readVideoDuration,
  saveVideo,
  sourceFor,
} from '../lib/store'
import type { VideoRecord } from '../lib/store'
import { AppShell } from '../components/Shell'
import {
  CheckIcon,
  PlayIcon,
  SearchIcon,
  UploadIcon,
} from '../components/Icons'
import { compactNumber, fileSize, humanDuration } from '../lib/format'

const STAGES = [
  { label: 'Uploading file', to: 34 },
  { label: 'Extracting frames (1 fps)', to: 62 },
  { label: 'Embedding frames with CLIP', to: 90 },
  { label: 'Writing vectors to the index', to: 100 },
]

const MAX_BYTES = 512 * 1024 * 1024

export default function Upload() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const inputRef = useRef<HTMLInputElement>(null)
  const aliveRef = useRef(true)

  const [dragging, setDragging] = useState(false)
  const [error, setError] = useState('')
  const [video, setVideo] = useState<VideoRecord | null>(null)
  const [progress, setProgress] = useState(0)
  const [stage, setStage] = useState(0)
  const [done, setDone] = useState(false)

  useEffect(() => {
    aliveRef.current = true
    return () => {
      aliveRef.current = false
    }
  }, [])

  async function ingest(file: File) {
    if (!user) return
    setError('')

    if (!file.type.startsWith('video/')) {
      setError('That file isn’t a video. Try an MP4, MOV or WebM.')
      return
    }
    if (file.size > MAX_BYTES) {
      setError(`Files are capped at ${fileSize(MAX_BYTES)} for now.`)
      return
    }

    const id = crypto.randomUUID()
    const url = attachSource(id, file)
    const duration = await readVideoDuration(file)
    if (!aliveRef.current) return

    const record: VideoRecord = {
      id,
      name: file.name,
      sizeBytes: file.size,
      duration,
      frames: Math.max(1, Math.round(duration)),
      status: 'processing',
      createdAt: new Date().toISOString(),
    }

    setVideo(record)
    setDone(false)
    setStage(0)
    setProgress(0)
    saveVideo(user.id, record)

    // Grab a poster from a second in — the very first frame is often black.
    const posters = await captureFrames(url, [Math.min(1.5, duration / 2)], 400)
    if (!aliveRef.current) return
    const poster = posters.values().next().value
    const withPoster = poster ? { ...record, poster } : record
    setVideo(withPoster)
    saveVideo(user.id, withPoster)

    // Walk the indexing stages. Real work happens server-side; the client just
    // reports where the pipeline is.
    for (let index = 0; index < STAGES.length; index += 1) {
      if (!aliveRef.current) return
      setStage(index)
      const target = STAGES[index]!.to
      const from = index === 0 ? 0 : STAGES[index - 1]!.to
      const steps = 12
      for (let step = 1; step <= steps; step += 1) {
        await new Promise((resolve) => setTimeout(resolve, 45))
        if (!aliveRef.current) return
        setProgress(from + ((target - from) * step) / steps)
      }
    }

    const ready: VideoRecord = { ...withPoster, status: 'ready' }
    setVideo(ready)
    saveVideo(user.id, ready)
    setDone(true)
  }

  function onDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault()
    setDragging(false)
    const file = event.dataTransfer.files?.[0]
    if (file) void ingest(file)
  }

  const busy = Boolean(video) && !done

  return (
    <AppShell
      title="Upload a video"
      subtitle="Frames are extracted once per second and embedded with CLIP."
      actions={
        <Link to="/dashboard" className="btn btn-ghost btn-sm">
          Back to dashboard
        </Link>
      }
    >
      <div className="page-narrow">
        {error && (
          <p className="alert" role="alert" style={{ marginBottom: 16 }}>
            {error}
          </p>
        )}

        {!video && (
          <div
            className={`dropzone${dragging ? ' is-over' : ''}`}
            onDragOver={(event) => {
              event.preventDefault()
              setDragging(true)
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={onDrop}
          >
            <span className="dropzone-icon">
              <UploadIcon />
            </span>
            <h2>Drop your video here</h2>
            <p>
              Or pick a file from your machine. Indexing starts as soon as the
              file lands — a ten-minute clip takes about a minute.
            </p>
            <button
              type="button"
              className="btn btn-primary btn-lg"
              onClick={() => inputRef.current?.click()}
            >
              <UploadIcon />
              Choose a file
            </button>
            <p className="dropzone-formats">
              MP4, MOV, WebM or MKV · up to {fileSize(MAX_BYTES)}
            </p>
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
        )}

        {video && (
          <section className="panel" style={{ marginTop: 0 }}>
            <div className="upload-card">
              <span className="lib-thumb">
                {video.poster ? <img src={video.poster} alt="" /> : <PlayIcon />}
              </span>
              <div className="lib-meta">
                <b>{video.name}</b>
                <span>
                  {fileSize(video.sizeBytes)}
                  {video.duration > 0 && ` · ${humanDuration(video.duration)}`}
                  {` · ${compactNumber(video.frames)} frames`}
                </span>
                <div className="progress">
                  <i style={{ width: `${progress}%` }} />
                </div>
              </div>
              <span className={`chip ${done ? 'chip-ok' : 'chip-accent'}`}>
                {done ? 'Indexed' : `${Math.round(progress)}%`}
              </span>
            </div>

            <div style={{ padding: '0 18px 18px' }}>
              <div className="stage-list">
                {STAGES.map((item, index) => {
                  const state =
                    done || index < stage
                      ? 'is-done'
                      : index === stage
                        ? 'is-active'
                        : ''
                  return (
                    <div key={item.label} className={`stage ${state}`}>
                      <span className="stage-dot">
                        {(done || index < stage) && <CheckIcon />}
                      </span>
                      {item.label}
                      {index === 1 && (
                        <span className="stage-count">
                          {compactNumber(video.frames)} frames
                        </span>
                      )}
                    </div>
                  )
                })}
              </div>

              <div
                style={{
                  display: 'flex',
                  gap: 10,
                  marginTop: 18,
                  flexWrap: 'wrap',
                }}
              >
                <button
                  type="button"
                  className="btn btn-primary"
                  disabled={!done}
                  onClick={() => navigate(`/search?v=${video.id}`)}
                >
                  <SearchIcon />
                  {done ? 'Search this video' : 'Indexing…'}
                </button>
                <button
                  type="button"
                  className="btn btn-ghost"
                  disabled={busy}
                  onClick={() => {
                    setVideo(null)
                    setProgress(0)
                    setStage(0)
                    setDone(false)
                  }}
                >
                  Upload another
                </button>
                {!sourceFor(video.id) && (
                  <span className="chip">Playback unavailable</span>
                )}
              </div>
            </div>
          </section>
        )}
      </div>
    </AppShell>
  )
}
