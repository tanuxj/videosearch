import { useEffect, useRef, useState } from 'react'
import type { DragEvent } from 'react'
import { useAuth } from '../lib/auth'
import {
  attachSource,
  captureFrames,
  createVideoApi,
  getVideo,
  readVideoDuration,
  saveVideo,
  streamSourceFor,
} from '../lib/store'
import type { VideoRecord } from '../lib/store'
import { API_ENABLED } from '../lib/http'
import { Modal } from './Modal'
import { cn } from '../lib/cn'
import { Alert, Spinner } from './AuthLayout'
import { Button } from './ui/Button'
import { Chip } from './ui/Data'
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

  /** Server mode: upload the file, then poll until the pipeline finishes. */
  async function ingestServer(file: File): Promise<void> {
    if (!user) return
    setStage(0)
    setProgress(0)

    // Stage 0 = the actual multipart upload.
    const record = await createVideoApi(file, (loaded, total) => {
      if (!aliveRef.current) return
      const fraction = total > 0 ? loaded / total : 1
      setProgress(Math.round(STAGES[0]!.to * fraction))
    })
    if (!aliveRef.current) return
    setStage(1)
    setProgress(STAGES[0]!.to)
    setVideo(record)  // server owns the record — nothing to persist locally

    // Poll the video until the backend marks it ready (or failed).
    let current = record
    for (let attempt = 0; attempt < 300; attempt += 1) {
      await new Promise((resolve) => setTimeout(resolve, 1000))
      if (!aliveRef.current) return
      current = (await getVideo(record.id)) ?? current
      setVideo(current)
      if (current.status === 'ready') break
      if (current.status === 'failed') {
        throw new Error('Indexing failed on the server — try another file.')
      }
      // Progress between stages 1–3 maps to the real frames indexed.
      const ratio = current.frames > 0 ? Math.min(1, 0.2 + current.frames / 60) : 0.2
      setStage(2)
      setProgress(STAGES[1]!.to + (STAGES[3]!.to - STAGES[1]!.to) * ratio)
    }

    if (current.status !== 'ready') {
      throw new Error('Indexing is taking longer than expected — check back soon.')
    }

    setStage(3)
    setProgress(STAGES[3]!.to)

    // Grab a real poster frame from the server-side stream.
    try {
      const src = await streamSourceFor(current.id)
      if (!aliveRef.current) return
      const posters = await captureFrames(
        src,
        [Math.min(1.5, (current.duration || 4) / 2)],
        400,
      )
      const poster = posters.values().next().value
      if (poster) {
        current = { ...current, poster }
        setVideo(current)
      }
    } catch {
      // Poster is decorative — playback still works without it.
    }
    setDone(true)
  }

  /** Demo mode: pretend through the stages with the local file handle. */
  async function ingestDemo(file: File): Promise<void> {
    if (!user) return

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

    try {
      if (API_ENABLED) await ingestServer(file)
      else await ingestDemo(file)
    } catch (caught) {
      if (!aliveRef.current) return
      setError(caught instanceof Error ? caught.message : 'Upload failed.')
    }
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
      <div className="p-5">
        {error && (
          <div className="mb-3.5">
            <Alert>{error}</Alert>
          </div>
        )}

        {!video ? (
          <div
            onDragOver={(event) => {
              event.preventDefault()
              setDragging(true)
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={onDrop}
            className={cn(
              'flex flex-col items-center rounded-2xl border-2 border-dashed px-6 py-10 text-center',
              'transition-[border-color,background-color] duration-200',
              dragging
                ? 'border-brand bg-brand-wash'
                : 'border-line-strong bg-surface-soft',
            )}
          >
            <span
              className={cn(
                'mb-4 grid size-14 place-items-center rounded-2xl border transition-transform duration-200 [&_svg]:size-6',
                dragging
                  ? 'scale-105 border-brand bg-panel text-brand'
                  : 'border-brand-line bg-brand-wash text-brand',
              )}
            >
              <UploadIcon />
            </span>
            <h3 className="text-[17px] font-semibold tracking-[-0.02em] text-ink">
              Drop your video here
            </h3>
            <p className="mt-2 max-w-[42ch] text-[13.5px] leading-relaxed text-ink-dim">
              Indexing starts the moment the file lands — a ten-minute clip
              takes about a minute.
            </p>
            <Button
              onClick={() => inputRef.current?.click()}
              className="mt-5 [&_svg]:size-4"
            >
              <UploadIcon />
              Choose a file
            </Button>
            <p className="mt-3.5 text-[12px] text-ink-faint">
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
            <div className="flex items-center gap-3 rounded-xl border border-line bg-surface-soft p-3">
              <span className="grid size-12 shrink-0 place-items-center overflow-hidden rounded-lg border border-line bg-[linear-gradient(135deg,var(--bg-sunk),color-mix(in_oklab,var(--accent)_12%,var(--bg-sunk)))] text-brand [&_svg]:size-5">
                {video.poster ? (
                  <img
                    src={video.poster}
                    alt=""
                    className="size-full object-cover"
                  />
                ) : (
                  <PlayIcon />
                )}
              </span>
              <div className="min-w-0 flex-1">
                <b className="block truncate text-[13.5px] font-semibold text-ink">
                  {video.name}
                </b>
                <span className="block truncate text-[12px] text-ink-faint">
                  {fileSize(video.sizeBytes)}
                  {video.duration > 0 && ` · ${humanDuration(video.duration)}`}
                  {` · ${compactNumber(Math.max(video.frames, 1))} frames`}
                </span>
                {/* Progress track is a lighter step of the fill's own hue, so
                    the bar reads as one scale rather than fill-on-grey. */}
                <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-brand-wash">
                  <i
                    className="block h-full rounded-full bg-[linear-gradient(90deg,var(--accent),var(--accent-2))] transition-[width] duration-300"
                    style={{ width: `${progress}%` }}
                  />
                </div>
              </div>
              {done ? (
                <Chip tone="ok">Indexed</Chip>
              ) : (
                <span className="shrink-0 text-[12.5px] font-semibold text-brand">
                  {Math.round(progress)}%
                </span>
              )}
            </div>

            <div className="mt-4 flex flex-col gap-0.5">
              {STAGES.map((item, index) => {
                const complete = done || index < stage
                const active = !done && index === stage
                return (
                  <div
                    key={item.label}
                    className={cn(
                      'flex items-center gap-2.5 rounded-lg px-2 py-2 text-[13px] transition-colors',
                      complete
                        ? 'text-ink'
                        : active
                          ? 'bg-brand-wash font-medium text-brand'
                          : 'text-ink-faint',
                    )}
                  >
                    <span
                      className={cn(
                        'grid size-[18px] shrink-0 place-items-center rounded-full border [&_svg]:size-3',
                        complete
                          ? 'border-ok bg-ok text-white'
                          : active
                            ? 'animate-pulse border-brand bg-brand-wash'
                            : 'border-line-strong',
                      )}
                    >
                      {complete && <CheckIcon />}
                    </span>
                    {item.label}
                    {index === 1 && (
                      <span className="ml-auto font-mono text-[11.5px] text-ink-faint">
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
        <footer className="flex items-center justify-end gap-2 border-t border-line bg-surface-soft px-5 py-3.5">
          <Button
            variant="ghost"
            disabled={!done}
            onClick={() => {
              setVideo(null)
              setProgress(0)
              setStage(0)
              setDone(false)
            }}
          >
            Add another
          </Button>
          <Button
            disabled={!done}
            onClick={() => {
              if (video) onReady?.(video)
              onClose()
            }}
            className="[&_svg]:size-4"
          >
            {done ? (
              <>
                <SearchIcon />
                Search this video
              </>
            ) : (
              <>
                <Spinner />
                Indexing…
              </>
            )}
          </Button>
        </footer>
      )}
    </Modal>
  )
}
