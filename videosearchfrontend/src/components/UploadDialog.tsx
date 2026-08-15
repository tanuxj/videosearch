import { useEffect, useRef, useState } from 'react'
import type { DragEvent } from 'react'
import { useAuth } from '../lib/auth'
import {
  attachSource,
  captureFrames,
  createVideoApi,
  createVideoFromUrl,
  createVideosFromUrls,
  getVideo,
  readVideoDuration,
  saveVideo,
  streamSourceFor,
} from '../lib/store'
import type { VideoRecord } from '../lib/store'
import { addVideosToCollection, createCollection, useCollections } from '../lib/collections'
import { API_ENABLED } from '../lib/http'
import { Modal } from './Modal'
import { cn } from '../lib/cn'
import { Alert, Spinner } from './AuthLayout'
import { Button } from './ui/Button'
import { Chip } from './ui/Data'
import {
  CheckIcon,
  FilmIcon,
  LayersIcon,
  LinkIcon,
  PlayIcon,
  SearchIcon,
  UploadIcon,
} from './Icons'
import { compactNumber, fileSize, humanDuration } from '../lib/format'

/**
 * One row of a bulk import — a pasted link or a picked file.
 *
 * Both sources converge on this shape so the progress list below renders them
 * identically: `label` is what to show until the server names the video,
 * `transfer` drives the bar during the upload (files only — a URL import has
 * no client-side bytes to count), and `done` means the row has stopped moving,
 * whether it landed indexed, failed, or was skipped up front.
 */
type BatchItem = {
  /** Stable react key: the URL, or `name:index` for a file. */
  key: string
  label: string
  video?: VideoRecord
  error?: string
  /** 0–1 upload progress, before a video row exists to poll. */
  transfer?: number
  done: boolean
}

/** How many files upload at once. More saturates the uplink and the API. */
const UPLOAD_CONCURRENCY = 3

/** Sentinel `<select>` value that reveals the "new collection" name field. */
const NEW_COLLECTION = '__new__'

/**
 * Share of the bar given to the transfer, before indexing starts.
 *
 * Indexing is usually the longer half, but the upload is the part with an
 * exact byte count, so it gets a fixed slice and indexing gets the rest.
 */
const UPLOAD_SHARE = 30

/**
 * The three things that actually happen, in order.
 *
 * There used to be four — "extracting", "embedding" and "writing vectors" were
 * listed separately — but the backend does not work that way: it decodes,
 * embeds and inserts one 32-frame chunk at a time, so those phases interleave
 * from the first second to the last. Showing them as sequential steps meant the
 * UI had to guess which one was "current", and it guessed wrong. One honest
 * indexing step with a real frame count beats three invented ones.
 */
const FILE_STAGES = [
  { label: 'Uploading file' },
  { label: 'Indexing frames (1 fps)' },
  { label: 'Ready to search' },
]

// URL imports swap the first stage for the server-side download — the client
// has no bytes to count, so it holds here until the first frames appear.
const URL_STAGES = [
  { label: 'Downloading video' },
  { label: 'Indexing frames (1 fps)' },
  { label: 'Ready to search' },
]

/** How long indexing may report no new frames before we call it stuck. */
const STALL_LIMIT_MS = 120_000

// Matches the backend's MAX_UPLOAD_BYTES default (10 GiB). Files above 5 GiB
// use the presigned multipart flow so the API never buffers the bytes.
const MAX_BYTES = 10 * 1024 * 1024 * 1024

/** `n` with the unit pluralised — "1 frame", "9.3K frames". */
function framesLabel(n: number): string {
  return `${compactNumber(n)} ${n === 1 ? 'frame' : 'frames'}`
}

/**
 * Pull URLs out of arbitrary pasted text.
 *
 * Users paste links in every shape — one per line, comma or space separated,
 * wrapped in quotes or brackets, buried mid-sentence, or even jammed directly
 * against the next link with no separator at all (“…KaX8https://…LYE…”). The
 * text is first split on whitespace/commas/semicolons, then each token is cut
 * at every http(s):// scheme boundary (so back-to-back links split apart) and
 * at the first character a link can't contain. Only `https://` links are
 * kept; anything else is reported separately so nothing silently vanishes.
 */
function extractUrls(text: string): { https: string[]; http: string[] } {
  const https: string[] = []
  const http: string[] = []
  const seen = new Set<string>()
  for (const token of text.split(/[\s,;]+/)) {
    if (!token) continue
    // Every scheme start in this token. A URL body runs from one start to the
    // next — that's what splits “…KaX8https://…LYEhttps://…” into three links.
    const starts = [...token.matchAll(/https?:\/\//gi)].map((m) => m.index!)
    for (let i = 0; i < starts.length; i += 1) {
      const from = starts[i]!
      const to = i + 1 < starts.length ? starts[i + 1]! : token.length
      const body = token.slice(from, to)
      // Stop at the first char a link can't contain (whitespace, quotes,
      // brackets, comma, semicolon), then drop trailing sentence punctuation
      // like the period on “https://a.com/v1.mp4.” in prose.
      const cut = body.search(/[\s"'()[\]{}<>,;]/)
      const raw = (cut === -1 ? body : body.slice(0, cut)).replace(/[.,;:!?]+$/, '')
      if (!raw) continue
      if (/^https:\/\//i.test(raw)) {
        if (!seen.has(raw)) {
          seen.add(raw)
          https.push(raw)
        }
      } else {
        http.push(raw)
      }
    }
  }
  return { https, http }
}

type Props = {
  open: boolean
  onClose: () => void
  /** Called with the finished video when the user chooses to search it. */
  onReady?: (video: VideoRecord) => void
}

export function UploadDialog({ open, onClose, onReady }: Props) {
  const { user } = useAuth()
  const inputRef = useRef<HTMLInputElement>(null)
  const folderRef = useRef<HTMLInputElement>(null)
  const aliveRef = useRef(true)
  const { collections, refresh: refreshCollections } = useCollections()

  const [dragging, setDragging] = useState(false)
  const [error, setError] = useState('')
  /** Non-fatal heads-up (e.g. http:// links skipped for https-only import). */
  const [note, setNote] = useState('')
  const [video, setVideo] = useState<VideoRecord | null>(null)
  const [progress, setProgress] = useState(0)
  const [stage, setStage] = useState(0)
  const [done, setDone] = useState(false)
  /** Which way the video enters the library: file upload or pasted link. */
  const [mode, setMode] = useState<'file' | 'url'>('file')
  const [urlInput, setUrlInput] = useState('')
  /** Optional auto-extract prompt for URL imports: best matching scenes are
   *  saved as clips once each video finishes indexing. */
  const [prompt, setPrompt] = useState('')
  /** Bulk import in flight — one row per file or resolved target URL. */
  const [batch, setBatch] = useState<BatchItem[] | null>(null)
  /**
   * Collection everything in this dialog is filed into.
   *
   * '' is "don't file it anywhere" and NEW_COLLECTION opens the name field —
   * filing at upload time is the only moment the user has the whole batch in
   * mind, so it's much cheaper than tagging forty videos afterwards.
   */
  const [collectionId, setCollectionId] = useState('')
  const [newCollection, setNewCollection] = useState('')
  /** Seconds remaining, once enough frames have landed to estimate a rate. */
  const [eta, setEta] = useState<number | null>(null)

  // URL imports hold on the transfer stage while the server downloads the
  // video — there are no client-side bytes to count, so the bar reads as an
  // indeterminate pulse instead of a fake percentage.
  const downloading = mode === 'url' && stage === 0 && !done
  const stages = mode === 'url' ? URL_STAGES : FILE_STAGES

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
      setNote('')
      setMode('file')
      setUrlInput('')
      setPrompt('')
      setBatch(null)
      setCollectionId('')
      setNewCollection('')
    }, 200)
    return () => clearTimeout(timer)
  }, [open])

  /**
   * Server mode: start an import (file upload or URL download), then poll
   * until the pipeline finishes.
   *
   * `create` performs the transfer and resolves with the `processing` record
   * the server owns. For a file that means the upload is complete when it
   * resolves; for a URL it resolves as soon as the row is reserved while the
   * download still runs server-side — so the dialog holds on the transfer
   * stage until the first frames appear.
   */
  async function ingestServer(
    create: (onProgress: (loaded: number, total: number) => void) => Promise<VideoRecord>,
    isUrl: boolean,
    collection?: string,
  ): Promise<void> {
    if (!user) return
    setStage(0)
    setProgress(0)

    // Stage 0 — the transfer, the one phase with an exact byte count. URL
    // imports have no client-side bytes (the server downloads them), so
    // `isUrl` skips the immediate advance to the indexing stage.
    const record = await create((loaded, total) => {
      if (!aliveRef.current) return
      const fraction = total > 0 ? loaded / total : 1
      setProgress(Math.round(UPLOAD_SHARE * fraction))
    })
    if (!aliveRef.current) return
    setVideo(record) // server owns the record — nothing to persist locally
    if (collection) {
      // Best effort: the video is uploaded either way, and a filing failure
      // must not read as a failed import.
      await addVideosToCollection(collection, [record.id]).catch(() => {})
    }
    if (!isUrl) {
      setStage(1)
      setProgress(UPLOAD_SHARE)
    }

    // Stage 1 — poll until the backend reports ready (or failed).
    //
    // Progress is `frames_indexed / frames_total`, both straight from the
    // server. The previous version divided by a hardcoded 60, so anything
    // longer than a minute pinned the bar near the top within seconds and then
    // sat there — which is exactly what "stale, then jumps to 100" was.
    let current = record
    let lastFrames = -1
    let lastChange = Date.now()
    // A file upload is done when `create` resolves. A URL import is not:
    // `frames_total` stays 0 until the download lands, so the transfer stage
    // holds (and the stall clock doesn't start) until then.
    let indexingStarted = !isUrl
    const startedAt = Date.now()

    while (aliveRef.current) {
      await new Promise((resolve) => setTimeout(resolve, 1000))
      if (!aliveRef.current) return
      current = (await getVideo(record.id)) ?? current
      setVideo(current)

      if (current.status === 'ready') break
      if (current.status === 'failed') {
        throw new Error(
          current.error || 'Indexing failed on the server — try another file.',
        )
      }

      // `frames_total` is 0 until the server has probed the file. Hold at the
      // start of the indexing band rather than dividing by zero.
      if (current.framesTotal > 0) {
        if (!indexingStarted) {
          // URL mode: the download finished and indexing has begun.
          indexingStarted = true
          setStage(1)
          setProgress(UPLOAD_SHARE)
          lastChange = Date.now()
        }
        if (current.frames !== lastFrames) {
          lastFrames = current.frames
          lastChange = Date.now()
        }
        const ratio = Math.min(1, current.frames / current.framesTotal)
        setProgress(UPLOAD_SHARE + (100 - UPLOAD_SHARE) * ratio)
        // A rate needs a few seconds of history to mean anything.
        const elapsed = (Date.now() - startedAt) / 1000
        if (current.frames > 0 && elapsed > 4) {
          const perSecond = current.frames / elapsed
          const left = (current.framesTotal - current.frames) / perSecond
          setEta(Number.isFinite(left) && left > 1 ? left : null)
        }
      }

      // Bound on *silence*, not on total time: a two-hour film legitimately
      // takes many minutes, and the old 300-second cap failed those uploads
      // with "taking longer than expected" while they were working fine. The
      // clock only starts once indexing produces frames — a long download
      // must not trip it.
      if (indexingStarted && Date.now() - lastChange > STALL_LIMIT_MS) {
        throw new Error(
          'Indexing has stopped responding. It may still finish — check your library in a few minutes.',
        )
      }
    }
    if (!aliveRef.current) return

    setStage(2)
    setProgress(100)
    setEta(null)

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

    // One sampled frame per second of video, matching the real pipeline.
    const expectedFrames = Math.max(1, Math.round(duration))
    const record: VideoRecord = {
      id,
      name: file.name,
      sizeBytes: file.size,
      duration,
      frames: 0,
      framesTotal: expectedFrames,
      status: 'processing',
      source: 'upload',
      // Demo mode has no server, so there is no transcription to wait for.
      transcriptStatus: 'skipped',
      // Collections are server-only; demo mode files nothing.
      collectionIds: [],
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

    // No server to poll, so walk the frame counter to the expected total. This
    // drives the same `frames / framesTotal` readout the real pipeline uses, so
    // demo mode and server mode render identically.
    setStage(0)
    for (let step = 1; step <= 10; step += 1) {
      await new Promise((resolve) => setTimeout(resolve, 40))
      if (!aliveRef.current) return
      setProgress((UPLOAD_SHARE * step) / 10)
    }

    setStage(1)
    const ticks = Math.min(24, expectedFrames)
    for (let tick = 1; tick <= ticks; tick += 1) {
      await new Promise((resolve) => setTimeout(resolve, 60))
      if (!aliveRef.current) return
      const indexed = Math.round((expectedFrames * tick) / ticks)
      setVideo({ ...withPoster, frames: indexed })
      setProgress(UPLOAD_SHARE + ((100 - UPLOAD_SHARE) * tick) / ticks)
    }
    setStage(2)

    const ready: VideoRecord = { ...withPoster, status: 'ready' }
    setVideo(ready)
    saveVideo(user.id, ready)
    setDone(true)
  }

  /** Why this file can't be indexed, or null when it's fine. */
  function rejectReason(file: File): string | null {
    // A folder pick yields every file in the tree, so this is the filter that
    // keeps the README and the cover art out of the queue — hence skipping
    // silently rather than erroring the whole batch.
    if (!file.type.startsWith('video/')) {
      return 'Not a video file'
    }
    if (file.size > MAX_BYTES) {
      return `Larger than the ${fileSize(MAX_BYTES)} limit`
    }
    return null
  }

  /**
   * Resolve the collection picker to an id, creating the collection first when
   * the user typed a new name.
   *
   * Typing the name of a collection that already exists reuses it rather than
   * failing on the server's uniqueness check — from the user's side "put these
   * in Lectures" means the same thing whether or not Lectures exists yet.
   */
  async function ensureCollection(): Promise<string | undefined> {
    if (!API_ENABLED) return undefined
    if (collectionId !== NEW_COLLECTION) return collectionId || undefined
    const name = newCollection.trim()
    if (!name) return undefined
    const existing = collections.find(
      (item) => item.name.toLowerCase() === name.toLowerCase(),
    )
    if (existing) return existing.id
    const created = await createCollection(name)
    return created.id
  }

  /**
   * Poll every row holding a video until it stops progressing.
   *
   * `moreComing` keeps the loop alive while uploads are still in flight —
   * without it a file batch would exit on the first tick, before the first
   * upload had produced a video row to poll.
   */
  async function pollBatch(items: BatchItem[], moreComing: () => boolean): Promise<void> {
    while (aliveRef.current) {
      const pending = items.filter((item) => item.video && !item.done)
      if (pending.length === 0 && !moreComing()) break
      await new Promise((resolve) => setTimeout(resolve, 1000))
      if (!aliveRef.current) return
      const updated = await Promise.all(
        pending.map(async (item) => {
          const current = (await getVideo(item.video!.id)) ?? item.video!
          return { ...item, video: current, done: current.status !== 'processing' }
        }),
      )
      for (const item of updated) {
        const index = items.findIndex((candidate) => candidate.key === item.key)
        if (index >= 0) items[index] = item
      }
      setBatch([...items])
    }
  }

  /**
   * Upload many files at once, `UPLOAD_CONCURRENCY` at a time.
   *
   * Each file is independent: one rejected type or failed transfer marks its
   * own row and the rest carry on. Uploading and indexing overlap — a file that
   * finished transferring is already being polled while later files are still
   * going up.
   */
  async function ingestFiles(files: File[]): Promise<void> {
    if (!user) return

    let targetCollection: string | undefined
    try {
      targetCollection = await ensureCollection()
    } catch (caught) {
      setError(
        caught instanceof Error
          ? caught.message
          : 'Could not create that collection.',
      )
      return
    }

    const items: BatchItem[] = files.map((file, index) => {
      const reason = rejectReason(file)
      return {
        key: `${file.name}:${index}`,
        label: file.name,
        ...(reason ? { error: reason } : { transfer: 0 }),
        done: reason !== null,
      }
    })
    setBatch(items)

    const update = (index: number, patch: Partial<BatchItem>) => {
      items[index] = { ...items[index]!, ...patch }
      setBatch([...items])
    }

    const queue = files
      .map((file, index) => ({ file, index }))
      .filter(({ index }) => !items[index]!.done)
    let cursor = 0
    let remaining = queue.length

    async function worker(): Promise<void> {
      while (aliveRef.current) {
        const next = queue[cursor++]
        if (!next) return
        const { file, index } = next
        try {
          const record = await createVideoApi(file, {
            onProgress: (loaded, total) => {
              if (!aliveRef.current) return
              update(index, { transfer: total > 0 ? loaded / total : 1 })
            },
          })
          update(index, { video: record, transfer: 1 })
          if (targetCollection) {
            // Best effort: a video that uploaded fine must not be reported as
            // failed just because filing it away didn't stick.
            await addVideosToCollection(targetCollection, [record.id]).catch(() => {})
          }
        } catch (caught) {
          update(index, {
            error: caught instanceof Error ? caught.message : 'Upload failed.',
            done: true,
          })
        } finally {
          remaining -= 1
        }
      }
    }

    await Promise.all([
      Promise.all(
        Array.from({ length: Math.min(UPLOAD_CONCURRENCY, queue.length) }, worker),
      ),
      pollBatch(items, () => remaining > 0),
    ])
    if (!aliveRef.current) return
    setDone(true)
    refreshCollections()
  }

  /**
   * Entry point for picked or dropped files.
   *
   * One file keeps the detailed single-video card (stages, ETA, poster); more
   * than one switches to the per-row batch list, which is the same list a
   * multi-link URL import uses.
   */
  async function ingest(files: File[]) {
    if (!user || files.length === 0) return
    setError('')
    setNote('')

    if (!API_ENABLED) {
      // Demo mode has no server to parallelise against — walk them in turn so
      // nothing is silently dropped from a multi-file pick.
      try {
        for (const file of files) {
          if (!aliveRef.current) return
          if (rejectReason(file)) continue
          await ingestDemo(file)
        }
      } catch (caught) {
        if (!aliveRef.current) return
        setError(caught instanceof Error ? caught.message : 'Upload failed.')
      }
      return
    }

    if (files.length > 1) {
      const skipped = files.filter((file) => rejectReason(file)).length
      if (skipped > 0) {
        setNote(
          `${skipped} of ${files.length} files aren’t indexable videos — they’re listed below as skipped.`,
        )
      }
      try {
        await ingestFiles(files)
      } catch (caught) {
        if (!aliveRef.current) return
        setError(caught instanceof Error ? caught.message : 'Upload failed.')
      }
      return
    }

    const file = files[0]!
    const reason = rejectReason(file)
    if (reason) {
      setError(
        reason === 'Not a video file'
          ? 'That file isn’t a video. Try an MP4, MOV or WebM.'
          : `Files are capped at ${fileSize(MAX_BYTES)} for now.`,
      )
      return
    }

    try {
      let collection: string | undefined
      try {
        collection = await ensureCollection()
      } catch (caught) {
        setError(
          caught instanceof Error ? caught.message : 'Could not create that collection.',
        )
        return
      }
      await ingestServer(
        (onProgress) => createVideoApi(file, { onProgress }),
        false,
        collection,
      )
      refreshCollections()
    } catch (caught) {
      if (!aliveRef.current) return
      setError(caught instanceof Error ? caught.message : 'Upload failed.')
    }
  }

  /** URL mode: pull the https:// links out of the pasted text and let the
   *  server import them. One link gets the polished single-video progress
   *  card; several get a list of per-video rows. */
  async function ingestUrl() {
    if (!user) return
    const { https, http } = extractUrls(urlInput)
    if (https.length === 0) {
      setError(
        http.length > 0
          ? 'Only https:// links are supported — switch these to https:// (http:// isn’t accepted).'
          : 'Paste at least one link starting with https://.',
      )
      return
    }
    setError('')
    // http:// links pasted alongside https:// ones are skipped, not fatal —
    // but the user should know some of their links didn't make it in.
    setNote(
      http.length > 0
        ? `Skipped ${http.length} ${http.length === 1 ? 'link' : 'links'} — only https:// is supported.`
        : '',
    )
    const autoPrompt = prompt.trim()
    try {
      const collection = await ensureCollection()
      if (https.length === 1) {
        await ingestServer(
          () =>
            createVideoFromUrl(https[0]!, {
              prompt: autoPrompt || undefined,
              clipLimit: autoPrompt ? 3 : 0,
            }),
          true,
          collection,
        )
      } else {
        await ingestBatch(https, autoPrompt, collection)
      }
      refreshCollections()
    } catch (caught) {
      if (!aliveRef.current) return
      setError(caught instanceof Error ? caught.message : 'Import failed.')
    }
  }

  /** Multi-URL import: the server reserves a row per link (playlists and
   *  channels expand into their videos), then each row is polled until it
   *  stops progressing — indexed, failed, or skipped up front. */
  async function ingestBatch(
    urls: string[],
    autoPrompt: string,
    collection?: string,
  ): Promise<void> {
    const created = await createVideosFromUrls(urls, {
      prompt: autoPrompt || undefined,
      clipLimit: autoPrompt ? 3 : 0,
    })
    if (!aliveRef.current) return
    const items: BatchItem[] = created.map((item) => ({
      key: item.url,
      label: item.url,
      ...(item.video ? { video: item.video } : {}),
      ...(item.error ? { error: item.error } : {}),
      done: !item.video,
    }))
    setBatch(items)

    if (collection) {
      const ids = items.flatMap((item) => (item.video ? [item.video.id] : []))
      await addVideosToCollection(collection, ids).catch(() => {})
    }

    // Every row already has its video (or its error) — nothing more is coming.
    await pollBatch(items, () => false)
    if (!aliveRef.current) return
    setDone(true)
  }

  function onDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault()
    setDragging(false)
    const files = Array.from(event.dataTransfer.files ?? [])
    if (files.length > 0) void ingest(files)
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
        {note && (
          <div className="mb-3.5">
            <p className="rounded-lg bg-brand-wash px-3.5 py-2.5 text-[13px] text-brand">
              {note}
            </p>
          </div>
        )}

        {!video && !batch ? (
          <div className="flex flex-col gap-4">
            {API_ENABLED && (
              <div className="flex gap-1 rounded-xl border border-line bg-surface-soft p-1">
                {(
                  [
                    { key: 'file', label: 'Upload a file' },
                    { key: 'url', label: 'Paste a link' },
                  ] as const
                ).map((tab) => (
                  <button
                    key={tab.key}
                    type="button"
                    onClick={() => setMode(tab.key)}
                    className={cn(
                      'flex-1 rounded-lg px-3 py-1.5 text-[13px] font-medium transition-colors',
                      mode === tab.key
                        ? 'bg-panel text-ink shadow-sm'
                        : 'text-ink-faint hover:text-ink',
                    )}
                  >
                    {tab.label}
                  </button>
                ))}
              </div>
            )}

          {mode === 'file' ? (
          <div
            onDragOver={(event) => {
              event.preventDefault()
              setDragging(true)
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={onDrop}
            className={cn(
              'flex flex-col items-center rounded-xl border-2 border-dashed px-6 py-10 text-center',
              'transition-[border-color,background-color] duration-200',
              dragging
                ? 'border-brand bg-brand-wash'
                : 'border-line-strong bg-surface-soft',
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
              Drop your videos here
            </h3>
            <p className="mt-2 max-w-[42ch] text-[13.5px] leading-relaxed text-ink-dim">
              Drop as many as you like — {UPLOAD_CONCURRENCY} upload at a time
              and each starts indexing the moment it lands.
            </p>
            <div className="mt-5 flex flex-wrap items-center justify-center gap-2">
              <Button
                onClick={() => inputRef.current?.click()}
                className="[&_svg]:size-4"
              >
                <UploadIcon />
                Choose files
              </Button>
              {API_ENABLED && (
                <Button
                  variant="secondary"
                  onClick={() => folderRef.current?.click()}
                  className="[&_svg]:size-4"
                >
                  <LayersIcon />
                  Choose a folder
                </Button>
              )}
            </div>
            <p className="mt-3.5 text-[12px] text-ink-faint">
              MP4, MOV, WebM or MKV · up to {fileSize(MAX_BYTES)} each
              {API_ENABLED && ' · non-video files in a folder are skipped'}
            </p>
            <input
              ref={inputRef}
              type="file"
              accept="video/*"
              multiple
              className="sr-only"
              onChange={(event) => {
                const files = Array.from(event.target.files ?? [])
                if (files.length > 0) void ingest(files)
                event.target.value = ''
              }}
            />
            {/* `webkitdirectory` is non-standard but supported everywhere that
                matters; it hands back every file in the tree, which is why
                `rejectReason` filters rather than erroring. */}
            <input
              ref={folderRef}
              type="file"
              // @ts-expect-error - webkitdirectory isn't in React's HTML types
              webkitdirectory=""
              directory=""
              multiple
              className="sr-only"
              onChange={(event) => {
                const files = Array.from(event.target.files ?? [])
                if (files.length > 0) void ingest(files)
                event.target.value = ''
              }}
            />
          </div>
          ) : (
            <div className="flex flex-col items-center rounded-xl border-2 border-dashed px-6 py-8 text-center">
              <span className="mb-4 grid size-12 place-items-center rounded-full border border-brand-line bg-brand-wash text-brand [&_svg]:size-6">
                <LinkIcon />
              </span>
              <h3 className="text-[17px] font-semibold tracking-[-0.02em] text-ink">
                Paste video links
              </h3>
              <p className="mt-2 max-w-[48ch] text-[13.5px] leading-relaxed text-ink-dim">
                YouTube, Twitch, Zoom, Vimeo — or any direct video file URL.
                Paste them however they come — one per line, comma or space
                separated — each becomes its own searchable video.
              </p>
              <textarea
                value={urlInput}
                onChange={(event) => setUrlInput(event.target.value)}
                onKeyDown={(event) => {
                  if (
                    event.key === 'Enter' &&
                    (event.metaKey || event.ctrlKey)
                  ) {
                    event.preventDefault()
                    void ingestUrl()
                  }
                }}
                rows={3}
                placeholder={
                  'https://www.youtube.com/watch?v=…\n' +
                  'https://vimeo.com/123456789'
                }
                aria-label="Video URLs"
                className="mt-5 w-full resize-none rounded-lg border border-line-strong bg-panel px-3.5 py-2.5 text-left text-[14px] text-ink outline-none placeholder:text-ink-faint focus:border-brand"
              />
              <input
                value={prompt}
                onChange={(event) => setPrompt(event.target.value)}
                placeholder="Optional: auto-save scenes that match, e.g. “a red car driving on a highway”"
                aria-label="Auto-extract prompt"
                className="mt-2.5 w-full rounded-lg border border-line-strong bg-panel px-3.5 py-2.5 text-[13.5px] text-ink outline-none placeholder:text-ink-faint focus:border-brand"
              />
              <Button
                onClick={() => void ingestUrl()}
                disabled={!urlInput.trim()}
                className="mt-4 [&_svg]:size-4"
              >
                <LinkIcon />
                Start importing
              </Button>
              <p className="mt-3 text-[12px] text-ink-faint">
                Only https:// links are imported. Live streams and private
                recordings can’t be indexed, and channel/playlist links aren’t
                supported yet — paste individual videos.
              </p>
            </div>
          )}

          {/* Filing happens here because this is the one moment the user has
              the whole batch in mind — tagging forty videos afterwards is a
              chore nobody does. */}
          {API_ENABLED && (
            <div className="flex flex-col gap-2 rounded-xl border border-line bg-surface-soft p-3.5">
              <label
                htmlFor="upload-collection"
                className="text-[12.5px] font-medium text-ink-dim"
              >
                Add to collection{' '}
                <span className="font-normal text-ink-faint">(optional)</span>
              </label>
              <select
                id="upload-collection"
                value={collectionId}
                onChange={(event) => setCollectionId(event.target.value)}
                className="w-full rounded-lg border border-line-strong bg-panel px-3 py-2 text-[13.5px] text-ink outline-none focus:border-brand"
              >
                <option value="">Don’t file it anywhere</option>
                {collections.map((collection) => (
                  <option key={collection.id} value={collection.id}>
                    {collection.name} ({collection.videoCount})
                  </option>
                ))}
                <option value={NEW_COLLECTION}>+ New collection…</option>
              </select>
              {collectionId === NEW_COLLECTION && (
                <input
                  value={newCollection}
                  onChange={(event) => setNewCollection(event.target.value)}
                  placeholder="Collection name, e.g. “Lectures”"
                  aria-label="New collection name"
                  autoFocus
                  className="w-full rounded-lg border border-line-strong bg-panel px-3 py-2 text-[13.5px] text-ink outline-none placeholder:text-ink-faint focus:border-brand"
                />
              )}
            </div>
          )}
          </div>
        ) : (
          <>
            {batch ? (
              <ul className="flex flex-col gap-2">
                {batch.map((item) => (
                  <li
                    key={item.key}
                    className="flex items-center gap-3 rounded-xl border border-line bg-surface-soft p-3"
                  >
                    <span className="grid size-10 shrink-0 place-items-center rounded-lg border border-line bg-surface-sunk text-brand [&_svg]:size-4">
                      <FilmIcon />
                    </span>
                    <div className="min-w-0 flex-1">
                      <b
                        className="block truncate text-[13px] font-semibold text-ink"
                        title={item.label}
                      >
                        {item.video?.name ?? item.label}
                      </b>
                      <span className="block truncate text-[12px] text-ink-faint">
                        {item.video
                          ? `${fileSize(item.video.sizeBytes)}${item.video.duration > 0 ? ` · ${humanDuration(item.video.duration)}` : ''}`
                          : item.error}
                      </span>
                      {/* Two bars, one track: bytes while the file is going up,
                          then frames once the server has a row to report. */}
                      {!item.video && item.transfer !== undefined && !item.done && (
                        <div className="mt-1.5 h-1 overflow-hidden rounded-full bg-brand-wash">
                          <i
                            className="block h-full rounded-full bg-brand transition-[width] duration-300"
                            style={{ width: `${Math.round(item.transfer * 100)}%` }}
                          />
                        </div>
                      )}
                      {item.video && item.video.status === 'processing' && (
                        <div className="mt-1.5 h-1 overflow-hidden rounded-full bg-brand-wash">
                          <i
                            className={cn(
                              'block h-full rounded-full bg-brand transition-[width] duration-300',
                              item.video.framesTotal === 0 && 'animate-pulse',
                            )}
                            style={{
                              width:
                                item.video.framesTotal > 0
                                  ? `${Math.min(100, (item.video.frames / item.video.framesTotal) * 100)}%`
                                  : '30%',
                            }}
                          />
                        </div>
                      )}
                    </div>
                    {item.video ? (
                      item.video.status === 'ready' ? (
                        <Chip tone="ok">Indexed</Chip>
                      ) : item.video.status === 'failed' ? (
                        <Chip
                          tone="danger"
                          title={item.video.error || 'Import failed on the server'}
                        >
                          Failed
                        </Chip>
                      ) : (
                        <Chip tone="warn" pulse>
                          {item.video.framesTotal > 0 ? 'Indexing' : 'Downloading'}
                        </Chip>
                      )
                    ) : item.done ? (
                      <Chip tone="danger" title={item.error}>
                        Skipped
                      </Chip>
                    ) : (
                      <Chip tone="warn" pulse>
                        {item.transfer ? `${Math.round(item.transfer * 100)}%` : 'Queued'}
                      </Chip>
                    )}
                  </li>
                ))}
              </ul>
            ) : video ? (
              <>
            <div className="flex items-center gap-3 rounded-xl border border-line bg-surface-soft p-3">
              <span className="grid size-12 shrink-0 place-items-center overflow-hidden rounded-lg border border-line bg-surface-sunk text-brand [&_svg]:size-5">
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
                  {/* Only claim a frame count once one exists. The old
                      `Math.max(frames, 1)` printed "1 frames" for every video
                      before indexing had produced anything. */}
                  {video.framesTotal > 0 &&
                    ` · ${framesLabel(video.framesTotal)} to index`}
                </span>
                {/* Progress track is a lighter step of the fill's own hue, so
                    the bar reads as one scale rather than fill-on-grey. While
                    a URL import downloads there are no client-side bytes to
                    count, so the fill pulses at the transfer share instead of
                    pretending to be a real percentage. */}
                <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-brand-wash">
                  <i
                    className={cn(
                      'block h-full rounded-full bg-brand transition-[width] duration-300',
                      downloading && 'animate-pulse',
                    )}
                    style={{
                      width: downloading ? `${UPLOAD_SHARE}%` : `${progress}%`,
                    }}
                  />
                </div>
              </div>
              {done ? (
                <Chip tone="ok">Indexed</Chip>
              ) : (
                <div className="shrink-0 text-right">
                  <span className="block text-[12.5px] font-semibold text-brand">
                    {downloading ? '…' : `${Math.round(progress)}%`}
                  </span>
                  {eta !== null && (
                    <span className="block text-[11px] text-ink-faint">
                      ~{humanDuration(eta)} left
                    </span>
                  )}
                </div>
              )}
            </div>

            <div className="mt-4 flex flex-col gap-0.5">
              {stages.map((item, index) => {
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
                    {/* Live count on the indexing row: "1.2K / 9.3K frames"
                        moves every second, which is the whole point — the old
                        bare "0 frames" never changed until it was already done. */}
                    {index === 1 && (active || complete) && (
                      <span className="ml-auto font-mono text-[11.5px] text-ink-faint">
                        {video.framesTotal > 0
                          ? `${compactNumber(video.frames)} / ${framesLabel(video.framesTotal)}`
                          : 'reading video…'}
                      </span>
                    )}
                  </div>
                )
              })}
            </div>
              </>
            ) : null}
          </>
        )}
      </div>

      {(video || batch) && (
        <footer className="flex items-center justify-end gap-2 border-t border-line bg-surface-soft px-5 py-3.5">
          <Button
            variant="ghost"
            disabled={!done}
            onClick={() => {
              setVideo(null)
              setBatch(null)
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
              if (batch) {
                const target = batch.find(
                  (item) => item.video?.status === 'ready',
                )?.video
                if (target) onReady?.(target)
              } else if (video) {
                onReady?.(video)
              }
              onClose()
            }}
            className="[&_svg]:size-4"
          >
            {done ? (
              <>
                <SearchIcon />
                {batch ? 'Search first result' : 'Search this video'}
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
