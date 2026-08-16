import { useEffect, useRef, useState } from 'react'
import { useNavigate } from '../lib/router'
import { useAuth } from '../lib/auth'
import { API_ENABLED } from '../lib/http'
import {
  attachSource,
  createVideoApi,
  readVideoDuration,
  saveVideo,
} from '../lib/store'
import type { VideoRecord } from '../lib/store'
import { saveBlob } from '../lib/api'
import { LiveCaptions, speechSupported } from '../lib/speech'
import type { Caption } from '../lib/speech'
import { AppShell } from '../components/Shell'
import { RecordSetupDialog } from '../components/RecordSetupDialog'
import type { RecordConfig } from '../components/RecordSetupDialog'
import { Button } from '../components/ui/Button'
import { Card } from '../components/ui/Card'
import { Chip, EmptyState, Panel } from '../components/ui/Data'
import { Spinner } from '../components/AuthLayout'
import { timecode } from '../lib/format'
import {
  CheckIcon,
  DownloadIcon,
  MicIcon,
  MonitorIcon,
  RecordIcon,
  StopIcon,
  UploadIcon,
  WaveIcon,
} from '../components/Icons'

/**
 * Record your screen (or mic) and get a live transcript as you speak.
 *
 * The recording itself stays in the browser: `getDisplayMedia` + `getUserMedia`
 * feed a `MediaRecorder` while the Web Speech API captions the microphone in
 * real time. When the user stops, the finished blob is reviewed right here —
 * and can be saved into the library, where it gets frame-indexed like any
 * other video (and transcribed server-side when the backend has an ASR key).
 */

type Phase = 'idle' | 'live' | 'review'

/** MIME types in preference order — the first one the browser supports wins. */
const MIME_CANDIDATES = [
  'video/webm;codecs=vp9,opus',
  'video/webm;codecs=vp8,opus',
  'video/webm',
  'audio/webm;codecs=opus',
  'audio/webm',
]

function pickMime(hasVideo: boolean): string | undefined {
  if (typeof MediaRecorder === 'undefined') return undefined
  for (const mime of MIME_CANDIDATES) {
    // Only offer audio MIMEs for audio-only recordings and vice versa —
    // recording an audio-only stream as "video/webm" plays fine, but the
    // container is a lie the moment the player expects a picture track.
    if (mime.startsWith('video') !== hasVideo) continue
    if (MediaRecorder.isTypeSupported(mime)) return mime
  }
  return undefined
}

function stopStream(stream: MediaStream | null): void {
  if (!stream) return
  for (const track of stream.getTracks()) track.stop()
}

const IDLE_FEATURES = [
  {
    icon: <WaveIcon />,
    title: 'Live transcript',
    body: 'Your words appear as captions while you speak — no waiting for an export.',
  },
  {
    icon: <MonitorIcon />,
    title: 'Screen + mic',
    body: 'Capture a tab, window or full screen, with your microphone and shared audio.',
  },
  {
    icon: <UploadIcon />,
    title: 'Goes to your library',
    body: 'Save the finished recording and it gets indexed like any other video.',
  },
]

export default function Record() {
  const { user } = useAuth()
  const navigate = useNavigate()

  const [setupOpen, setSetupOpen] = useState(false)
  const [phase, setPhase] = useState<Phase>('idle')
  const [config, setConfig] = useState<RecordConfig | null>(null)
  const [elapsed, setElapsed] = useState(0)
  const [captions, setCaptions] = useState<Caption[]>([])
  const [interim, setInterim] = useState('')
  const [resultUrl, setResultUrl] = useState<string | null>(null)
  /** The live capture stream, for the preview element (state, not a ref, so
   *  the video mounts before we attach it — a ref can be null mid-await). */
  const [liveStream, setLiveStream] = useState<MediaStream | null>(null)
  const [copied, setCopied] = useState(false)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  /** Set when the browser (not the user) ends the capture — e.g. switching
   *  away from a captured tab cuts it. Shown on the review screen so a
   *  shortened recording reads as an interruption, not a mystery. */
  const [captureCut, setCaptureCut] = useState<string | null>(null)

  const aliveRef = useRef(true)
  const combinedRef = useRef<MediaStream | null>(null)
  const audioCtxRef = useRef<AudioContext | null>(null)
  const recorderRef = useRef<MediaRecorder | null>(null)
  const chunksRef = useRef<Blob[]>([])
  const resultBlobRef = useRef<Blob | null>(null)
  const captionsRef = useRef<LiveCaptions | null>(null)
  const startAtRef = useRef(0)
  const lastCaptionEndRef = useRef(0)
  const timerRef = useRef<ReturnType<typeof setInterval> | undefined>(undefined)
  const discardRef = useRef(false)
  const previewRef = useRef<HTMLVideoElement>(null)

  useEffect(() => {
    aliveRef.current = true
    return () => {
      aliveRef.current = false
      captionsRef.current?.abort()
      if (recorderRef.current && recorderRef.current.state !== 'inactive') {
        try {
          recorderRef.current.stop()
        } catch {
          /* already stopping */
        }
      }
      clearInterval(timerRef.current)
      stopStream(combinedRef.current)
      void audioCtxRef.current?.close().catch(() => {})
    }
  }, [])

  /** Mix the display's audio (tab/system) with the mic into one stream. */
  function mixScreenAndMic(screen: MediaStream, mic: MediaStream): MediaStream {
    const Ctor =
      window.AudioContext ??
      (window as typeof window & { webkitAudioContext?: typeof AudioContext })
        .webkitAudioContext
    if (Ctor) {
      const ctx = new Ctor()
      const dest = ctx.createMediaStreamDestination()
      ctx.createMediaStreamSource(mic).connect(dest)
      if (screen.getAudioTracks().length > 0) {
        ctx.createMediaStreamSource(screen).connect(dest)
      }
      audioCtxRef.current = ctx
      return new MediaStream([
        ...screen.getVideoTracks(),
        ...dest.stream.getAudioTracks(),
      ])
    }
    // No Web Audio (rare) — fall back to the mic alone.
    return new MediaStream([...screen.getVideoTracks(), ...mic.getAudioTracks()])
  }

  function stopAllSources() {
    clearInterval(timerRef.current)
    stopStream(combinedRef.current)
    combinedRef.current = null
    void audioCtxRef.current?.close().catch(() => {})
    audioCtxRef.current = null
  }

  function stopLive() {
    captionsRef.current?.stop()
    setInterim('')
    setCaptureCut(null)
    // The recorder's onstop builds the review and tears the sources down —
    // stopping the tracks there keeps the final chunk from being truncated.
    clearInterval(timerRef.current)
    if (recorderRef.current && recorderRef.current.state !== 'inactive') {
      recorderRef.current.stop()
    }
  }

  /**
   * The browser ended the capture (toolbar "Stop sharing", or — for a
   * captured tab — switching away from it). Stop cleanly so the recorder
   * flushes what it has, and when the tab was hidden at that moment, tell
   * the user why the recording shortened: Chromium cuts tab captures when
   * you switch away. "Entire screen" / a window keep recording across tabs.
   */
  function handleTrackEnded() {
    if (!recorderRef.current || recorderRef.current.state === 'inactive') return
    const wasHidden = document.hidden
    stopLive()
    if (wasHidden) {
      setCaptureCut(
        'Chrome stopped the capture because you switched away from the tab ' +
          'being recorded — the recording up to that point is still saved. To ' +
          'keep recording across tabs, pick “Entire screen” or a window in the ' +
          'share dialog next time.',
      )
    }
  }

  function cancelLive() {
    captionsRef.current?.abort()
    setInterim('')
    // Stopping with the discard flag set drops the captured data — no review
    // screen. (`abort()` isn't in every browser's MediaRecorder, so stop +
    // flag is the portable way to discard.)
    discardRef.current = true
    const recorder = recorderRef.current
    if (recorder && recorder.state !== 'inactive') {
      try {
        recorder.stop()
      } catch {
        /* already stopped */
      }
    }
    stopAllSources()
    setLiveStream(null)
    setCaptureCut(null)
    setPhase('idle')
    setConfig(null)
  }

  async function start(config: RecordConfig) {
    if (!navigator.mediaDevices?.getUserMedia) {
      setError('Media capture isn’t available in this browser — try Chrome, Edge or Safari.')
      return
    }
    setError(null)
    setCaptureCut(null)
    setCaptions([])
    setInterim('')
    setElapsed(0)
    setConfig(config)
    setPhase('live')

    let screen: MediaStream | null = null
    let mic: MediaStream | null = null
    try {
      const audioConstraint: MediaTrackConstraints | boolean = config.micId
        ? { deviceId: { exact: config.micId } }
        : true

      if (config.mode === 'screen') {
        screen = await navigator.mediaDevices.getDisplayMedia({
          video: true,
          audio: true,
        })
        if (!aliveRef.current) {
          stopStream(screen)
          return
        }
        // "Stop sharing" in the browser's own UI — or, for a captured tab,
        // switching away from it — ends the session. Handle it cleanly
        // instead of leaving a dead recorder running, and explain it when
        // the tab was hidden (the switch-away case).
        screen.getVideoTracks()[0]?.addEventListener('ended', handleTrackEnded)
        mic = await navigator.mediaDevices.getUserMedia({ audio: audioConstraint })
        if (!aliveRef.current) {
          stopStream(screen)
          stopStream(mic)
          return
        }
      } else if (config.cameraId) {
        // Audio-only mode with a camera chosen: record the webcam too.
        mic = await navigator.mediaDevices.getUserMedia({
          audio: audioConstraint,
          video: { deviceId: { exact: config.cameraId } },
        })
      } else {
        mic = await navigator.mediaDevices.getUserMedia({ audio: audioConstraint })
      }
      if (!aliveRef.current) {
        stopStream(screen)
        stopStream(mic)
        return
      }

      const combined =
        screen && config.mode === 'screen'
          ? mixScreenAndMic(screen, mic)
          : new MediaStream([...mic.getTracks()])
      combinedRef.current = combined

      // Live preview: the display (or webcam) muted, so no audio feedback.
      setLiveStream(combined)

      const hasVideo = combined.getVideoTracks().length > 0
      const mime = pickMime(hasVideo)
      const recorder = mime
        ? new MediaRecorder(combined, { mimeType: mime })
        : new MediaRecorder(combined)
      recorderRef.current = recorder
      chunksRef.current = []
      discardRef.current = false

      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) chunksRef.current.push(event.data)
      }
      recorder.onstop = () => {
        if (discardRef.current) return
        if (!aliveRef.current) return
        const type = recorder.mimeType || (hasVideo ? 'video/webm' : 'audio/webm')
        const blob = new Blob(chunksRef.current, { type })
        resultBlobRef.current = blob
        setResultUrl(URL.createObjectURL(blob))
        setPhase('review')
        stopAllSources()
      }
      recorder.start(1000)

      // Live captions from the Web Speech API, committed to the list as
      // phrases settle. Timestamps are relative to the recording start.
      lastCaptionEndRef.current = 0
      const captions = new LiveCaptions({
        lang: config.language || undefined,
        onFinal: (text) => {
          if (!aliveRef.current) return
          const now = (Date.now() - startAtRef.current) / 1000
          const start = lastCaptionEndRef.current
          lastCaptionEndRef.current = now
          setCaptions((list) => [...list, { start, end: now, text }])
          setInterim('')
        },
        onInterim: setInterim,
      })
      captionsRef.current = captions
      if (captions.supported) captions.start()

      startAtRef.current = Date.now()
      timerRef.current = setInterval(() => {
        if (!aliveRef.current) return
        setElapsed((Date.now() - startAtRef.current) / 1000)
      }, 250)
    } catch (caught) {
      stopStream(screen)
      stopStream(mic)
      stopAllSources()
      setPhase('idle')
      setConfig(null)
      const name =
        caught instanceof DOMException ? caught.name : (caught as { name?: string })?.name
      setError(
        name === 'NotAllowedError'
          ? 'You declined the permission prompt — recording needs screen or mic access.'
          : name === 'NotFoundError'
            ? 'The selected microphone could not be opened.'
            : 'Recording could not start — check the permissions and try again.',
      )
    }
  }

  /** Save the recording into the library like any other video. */
  async function saveToLibrary() {
    if (!user || !resultBlobRef.current) return
    setSaving(true)
    setSaveError(null)
    try {
      const blob = resultBlobRef.current
      const stamp = new Date()
        .toISOString()
        .replace(/[:T]/g, '-')
        .slice(0, 19)
      const file = new File([blob], `Recording ${stamp}.webm`, {
        type: blob.type || 'video/webm',
      })
      // Screen captures (and audio-only saves that kept a webcam) carry a
      // video track; a plain mic recording is audio-only. Audio-only saves
      // have no frames to scene-search, so they land on the library's
      // Recordings page instead of the search box.
      const hasVideo = isScreen || Boolean(config?.cameraId)
      const next = hasVideo
        ? (id: string) => `/search?v=${id}`
        : () => '/recordings'
      if (!API_ENABLED) {
        // Demo mode: attach the blob for playback and persist the record.
        const id = crypto.randomUUID()
        attachSource(id, file)
        const duration = await readVideoDuration(file)
        const record: VideoRecord = {
          id,
          name: file.name,
          sizeBytes: file.size,
          duration,
          frames: 0,
          framesTotal: 0,
          status: 'ready',
          // Marked so the library can tag it as a recording.
          source: 'recording',
          // Audio-only saves have no video track to search.
          hasVideo,
          transcriptStatus: 'skipped',
          collectionIds: [],
          createdAt: new Date().toISOString(),
        }
        await saveVideo(user.id, record)
        navigate(next(id))
      } else {
        const record = await createVideoApi(file, { source: 'recording' })
        navigate(next(record.id))
      }
    } catch (caught) {
      setSaveError(
        caught instanceof Error ? caught.message : 'Could not save the recording.',
      )
    } finally {
      setSaving(false)
    }
  }

  function copyTranscript() {
    if (captions.length === 0) return
    void navigator.clipboard
      ?.writeText(
        captions
          .map((caption) => `[${timecode(caption.start)}] ${caption.text}`)
          .join('\n'),
      )
      .then(() => {
        setCopied(true)
        setTimeout(() => setCopied(false), 1500)
      })
      .catch(() => {})
  }

  function resetToIdle() {
    if (resultUrl) URL.revokeObjectURL(resultUrl)
    setResultUrl(null)
    resultBlobRef.current = null
    setLiveStream(null)
    setCaptions([])
    setConfig(null)
    setElapsed(0)
    setCaptureCut(null)
    setPhase('idle')
  }

  const isScreen = config?.mode === 'screen'
  const hasVideoPreview =
    phase === 'live' && (isScreen || Boolean(config?.cameraId))

  // Attach the capture stream to the preview once both exist — the element is
  // only mounted during the live phase, and the stream arrives after the
  // display/mic promises resolve.
  useEffect(() => {
    const preview = previewRef.current
    if (!preview || !liveStream || phase !== 'live') return
    preview.srcObject = liveStream
    void preview.play().catch(() => {})
  }, [liveStream, phase])

  return (
    <AppShell
      title="Record a screen"
      subtitle="Capture your screen or mic — speak and watch the transcript build live."
    >
      <div className="mx-auto w-full max-w-[760px]">
        {error && (
          <p
            role="alert"
            className="mb-4 rounded-lg bg-danger-wash px-3.5 py-2.5 text-[13px] text-danger"
          >
            {error}
          </p>
        )}

        {/* ── Idle: the big blue CTA ─────────────────────── */}
        {phase === 'idle' && (
          <div className="flex flex-col items-center pt-14 pb-8 text-center">
            <h2 className="text-[clamp(1.45rem,3.4vw,1.9rem)] font-semibold tracking-[-0.025em] text-ink">
              Present, explain, record —<br className="hidden sm:block" /> and
              keep the transcript
            </h2>
            <p className="mt-3 max-w-[46ch] text-[14.5px] leading-relaxed text-ink-dim">
              Record your screen or just your voice. Everything you say is
              captioned live, and the finished recording drops straight into
              your library, ready to search.
            </p>

            <button
              type="button"
              onClick={() => setSetupOpen(true)}
              className="mt-9 inline-flex cursor-pointer flex-col items-center gap-2.5 rounded-2xl bg-brand px-12 py-6 text-white shadow-[0_18px_40px_-14px_rgba(37,99,235,0.55)] transition-colors duration-150 hover:bg-brand-hover focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand [&_svg]:size-7"
            >
              <MonitorIcon />
              <span className="text-[15.5px] font-medium tracking-[-0.01em]">
                Record Screen
              </span>
            </button>
            <p className="mt-3 text-[12.5px] text-ink-faint">
              Screen + mic · tab audio optional · live captions
            </p>

            <div className="mt-12 grid w-full grid-cols-1 gap-3 sm:grid-cols-3">
              {IDLE_FEATURES.map((feature) => (
                <Card key={feature.title} className="p-4 text-left">
                  <span className="mb-2.5 grid size-8 place-items-center rounded-lg bg-brand-wash text-brand [&_svg]:size-4">
                    {feature.icon}
                  </span>
                  <b className="block text-[13.5px] font-semibold text-ink">
                    {feature.title}
                  </b>
                  <p className="mt-1 text-[12.5px] leading-relaxed text-ink-dim">
                    {feature.body}
                  </p>
                </Card>
              ))}
            </div>
          </div>
        )}

        {/* ── Live ───────────────────────────────────────── */}
        {phase === 'live' && (
          <div className="flex flex-col gap-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2.5">
                <span className="inline-flex items-center gap-1.5 rounded-full bg-danger-wash px-2.5 py-1 text-[11.5px] font-semibold text-danger">
                  <i className="size-1.5 animate-pulse rounded-full bg-current" />
                  REC
                </span>
                <span className="font-mono text-[15px] font-medium text-ink tabular-nums">
                  {timecode(elapsed)}
                </span>
              </div>
              <Chip tone="neutral" icon={isScreen ? <MonitorIcon /> : <MicIcon />}>
                {isScreen ? 'Screen + mic' : 'Audio only'}
              </Chip>
            </div>

            {hasVideoPreview ? (
              <div className="relative aspect-video w-full overflow-hidden rounded-2xl border border-line bg-black">
                <video
                  ref={previewRef}
                  muted
                  playsInline
                  autoPlay
                  className="size-full object-contain"
                />
              </div>
            ) : (
              <Card className="flex aspect-video w-full flex-col items-center justify-center gap-3 text-center">
                <span className="grid size-14 place-items-center rounded-full bg-brand-wash text-brand">
                  <WaveIcon className="size-6" />
                </span>
                <div>
                  <b className="block text-[15px] font-semibold text-ink">
                    Listening…
                  </b>
                  <p className="mt-1 text-[13px] text-ink-dim">
                    Speak now — your words appear below as captions.
                  </p>
                </div>
              </Card>
            )}

            <Panel
              title="Live transcript"
              subtitle={
                captions.length === 0
                  ? speechSupported()
                    ? 'Start speaking — captions appear here.'
                    : 'Transcription isn’t supported in this browser, but the recording still captures audio.'
                  : `${captions.length} ${captions.length === 1 ? 'line' : 'lines'} so far`
              }
            >
              {captions.length === 0 && !interim ? (
                <EmptyState
                  icon={<WaveIcon />}
                  title={speechSupported() ? 'Waiting for speech' : 'Transcription unavailable'}
                  body={
                    speechSupported()
                      ? 'The recogniser is live — begin speaking and the words will land here.'
                      : 'This browser has no speech recognition. The recording will still be saved with its audio.'
                  }
                />
              ) : (
                <ol className="max-h-[16rem] divide-y divide-line overflow-y-auto">
                  {captions.map((caption, index) => (
                    <li key={`${caption.start}-${index}`}>
                      <div className="flex items-baseline gap-3 px-5 py-2.5">
                        <span className="shrink-0 font-mono text-[11.5px] text-brand tabular-nums">
                          {timecode(caption.start)}
                        </span>
                        <span className="text-[13.5px] leading-relaxed text-ink">
                          {caption.text}
                        </span>
                      </div>
                    </li>
                  ))}
                  {interim && (
                    <li className="px-5 py-2.5 text-[13.5px] leading-relaxed text-ink-faint italic">
                      {interim}…
                    </li>
                  )}
                </ol>
              )}
            </Panel>

            <div className="flex items-center justify-center gap-2">
              <Button variant="danger" onClick={stopLive} className="[&_svg]:size-4">
                <StopIcon />
                Stop recording
              </Button>
              <Button variant="ghost" onClick={cancelLive}>
                Cancel
              </Button>
            </div>
          </div>
        )}

        {/* ── Review ─────────────────────────────────────── */}
        {phase === 'review' && resultUrl && (
          <div className="flex flex-col gap-4">
            {captureCut && (
              <div className="rounded-lg border border-warn/30 bg-warn-wash px-3.5 py-2.5 text-[13px] leading-relaxed text-warn">
                {captureCut}
              </div>
            )}
            <Panel
              title="Your recording"
              subtitle={`${isScreen ? 'Screen capture' : config?.cameraId ? 'Webcam' : 'Audio only'} · ${timecode(elapsed)} · ${(resultBlobRef.current?.size ?? 0) > 0 ? `${Math.round((resultBlobRef.current?.size ?? 0) / 1024)} KB` : ''}`}
              actions={
                <div className="flex items-center gap-2">
                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={() =>
                      resultBlobRef.current &&
                      saveBlob(resultBlobRef.current, `Recording ${Date.now()}.webm`)
                    }
                    className="[&_svg]:size-4"
                  >
                    <DownloadIcon />
                    Download
                  </Button>
                  <Button
                    size="sm"
                    disabled={saving}
                    onClick={() => void saveToLibrary()}
                    className="[&_svg]:size-4"
                  >
                    {saving ? <Spinner /> : <UploadIcon />}
                    {saving ? 'Saving…' : 'Save to library'}
                  </Button>
                </div>
              }
            >
              <div className="p-4">
                {isScreen || config?.cameraId ? (
                  <video
                    controls
                    src={resultUrl}
                    className="aspect-video w-full rounded-xl bg-black"
                  />
                ) : (
                  <audio controls src={resultUrl} className="w-full" />
                )}
              </div>
              {saveError && (
                <p className="px-4 pb-3 text-[12.5px] text-danger">{saveError}</p>
              )}
            </Panel>

            <Panel
              title="Transcript"
              subtitle={
                captions.length > 0
                  ? `${captions.length} ${captions.length === 1 ? 'line' : 'lines'} · captured while you spoke`
                  : 'Nothing was recognised'
              }
              actions={
                captions.length > 0 && (
                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={copyTranscript}
                    className="[&_svg]:size-4"
                  >
                    {copied ? <CheckIcon /> : <RecordIcon />}
                    {copied ? 'Copied' : 'Copy'}
                  </Button>
                )
              }
            >
              {captions.length === 0 ? (
                <EmptyState
                  icon={<WaveIcon />}
                  title="No captions captured"
                  body={
                    speechSupported()
                      ? 'The audio was recorded, but nothing was recognised — it may have been silent.'
                      : 'Live transcription isn’t supported in this browser. The audio is still in the recording.'
                  }
                />
              ) : (
                <ol className="max-h-[22rem] divide-y divide-line overflow-y-auto">
                  {captions.map((caption, index) => (
                    <li key={`${caption.start}-${index}`}>
                      <div className="flex items-baseline gap-3 px-5 py-2.5">
                        <span className="shrink-0 font-mono text-[11.5px] text-brand tabular-nums">
                          {timecode(caption.start)}
                        </span>
                        <span className="text-[13.5px] leading-relaxed text-ink">
                          {caption.text}
                        </span>
                      </div>
                    </li>
                  ))}
                </ol>
              )}
            </Panel>

            <div className="flex justify-center">
              <Button variant="ghost" onClick={resetToIdle}>
                Record another
              </Button>
            </div>
          </div>
        )}
      </div>

      <RecordSetupDialog
        open={setupOpen}
        onClose={() => setSetupOpen(false)}
        onStart={(config) => {
          setSetupOpen(false)
          void start(config)
        }}
      />
    </AppShell>
  )
}
