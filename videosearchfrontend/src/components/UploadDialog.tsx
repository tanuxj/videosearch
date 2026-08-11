import { useEffect, useRef, useState } from 'react'
import type { DragEvent } from 'react'
import { useAuth } from '../lib/auth'
import {
  attachSource,
  captureFrames,
  readVideoDuration,
  saveVideo,
} from '../lib/store'
import type { VideoRecord } from '../lib/store'
import { Modal } from './Modal'
import { CheckIcon, PlayIcon, SearchIcon, UploadIcon } from './Icons'
import { compactNumber, fileSize, humanDuration } from '../lib/format'

const STAGES = [
  { label: 'Uploading file', to: 34 },
  { label: 'Extracting frames (1 fps)', to: 62 },
  { label: 'Embedding frames with CLIP', to: 90 },
  { label: 'Writing vectors to the index', to: 100 },
]

const MAX_BYTES = 512 * 1024 * 1024

type Props = {
  open: boolean
  onClose: () => void
  /** Called with the finished video when the user chooses to search it. */
  onReady?: (video: VideoRecord) => void
}

export function UploadDialog({ open, onClose, onReady }: Props) {
  const { user } = useAuth()
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

  // Reset for the next upload once the dialog is fully closed.
  useEffect(() => {
    if (open) return
    const timer = setTimeout(() => {
      setVideo(null)
      setProgress(0)
      setStage(0)
      setDone(false)
      setError('')
    }, 200)
    return () => clearTimeout(timer)
  }, [open])

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

    // Walk the indexing stages. The heavy lifting is server-side; the client
    // just reports where the pipeline is.
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

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Add a video"
      subtitle="Frames are extracted once per second and embedded with CLIP."
    >
      <div className="modal-body">
        {error && (
          <p className="alert" style={{ marginBottom: 14 }} role="alert">
            {error}
          </p>
        )}

        {!video ? (
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
            <h3>Drop your video here</h3>
            <p>
              Indexing starts the moment the file lands — a ten-minute clip takes
              about a minute.
            </p>
            <button
              type="button"
              className="btn btn-primary"
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
        ) : (
          <>
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
          </>
        )}
      </div>

      {video && (
        <footer className="modal-foot">
          <button
            type="button"
            className="btn btn-ghost"
            disabled={!done}
            onClick={() => {
              setVideo(null)
              setProgress(0)
              setStage(0)
              setDone(false)
            }}
          >
            Add another
          </button>
          <button
            type="button"
            className="btn btn-primary"
            disabled={!done}
            onClick={() => {
              if (video) onReady?.(video)
              onClose()
            }}
          >
            {done ? (
              <>
                <SearchIcon />
                Search this video
              </>
            ) : (
              <>
                <span className="spinner" />
                Indexing…
              </>
            )}
          </button>
        </footer>
      )}
    </Modal>
  )
}
