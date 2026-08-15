import { useEffect, useRef, useState } from 'react'
import { Modal } from './Modal'
import { cn } from '../lib/cn'
import { Button } from './ui/Button'
import {
  CameraIcon,
  CameraOffIcon,
  ChevronIcon,
  GlobeIcon,
  MicIcon,
  MonitorIcon,
  WaveIcon,
} from './Icons'
import { RECOGNITION_LANGUAGES, speechSupported } from '../lib/speech'

export type RecordMode = 'screen' | 'audio'

/** What the user chose in the setup dialog, handed to the recorder. */
export type RecordConfig = {
  mode: RecordMode
  /** '' means the browser's default microphone. */
  micId: string
  /** '' means no camera. */
  cameraId: string
  /** '' means the browser's default language. */
  language: string
}

type Props = {
  open: boolean
  onClose: () => void
  onStart: (config: RecordConfig) => void
}

function stopTracks(stream: MediaStream | null): void {
  if (!stream) return
  for (const track of stream.getTracks()) track.stop()
}

/** Map a getUserMedia failure to a human line for the warning banner. */
function permissionMessage(error: unknown): string {
  const name =
    error instanceof DOMException ? error.name : (error as { name?: string })?.name
  if (name === 'NotAllowedError' || name === 'PermissionDeniedError') {
    return 'Microphone or camera access is blocked. Allow access in your browser to preview and select devices.'
  }
  if (name === 'NotFoundError' || name === 'OverconstrainedError') {
    return 'No microphone was found on this device.'
  }
  if (name === 'SecurityError') {
    return 'Media access needs a secure context — open this app over https:// or localhost.'
  }
  return 'Could not reach the microphone. Check your browser’s permissions and try again.'
}

/**
 * The pre-flight dialog before a recording starts: pick what to capture
 * (screen or audio only), which mic/camera to use, and the transcription
 * language.
 *
 * A silent mic preview stream is requested the moment the dialog opens — the
 * same prompt the user will hit anyway — so the level meter runs and the
 * device lists come back labelled. When permission is denied the warning
 * banner explains how to fix it, matching the reference flow.
 */
export function RecordSetupDialog({ open, onClose, onStart }: Props) {
  const [mode, setMode] = useState<RecordMode>('screen')
  const [mics, setMics] = useState<MediaDeviceInfo[]>([])
  const [cams, setCams] = useState<MediaDeviceInfo[]>([])
  const [micId, setMicId] = useState('')
  const [cameraId, setCameraId] = useState('')
  const [language, setLanguage] = useState('')
  const [blocked, setBlocked] = useState<string | null>(null)
  const [cameraBlocked, setCameraBlocked] = useState<string | null>(null)

  const previewStreamRef = useRef<MediaStream | null>(null)
  const cameraStreamRef = useRef<MediaStream | null>(null)
  const cameraPreviewRef = useRef<HTMLVideoElement>(null)
  const meterBarRef = useRef<HTMLSpanElement>(null)
  const meterRaf = useRef(0)
  const audioCtxRef = useRef<AudioContext | null>(null)

  function stopMeter() {
    cancelAnimationFrame(meterRaf.current)
    void audioCtxRef.current?.close().catch(() => {})
    audioCtxRef.current = null
  }

  function startMeter(stream: MediaStream) {
    stopMeter()
    const Ctor =
      window.AudioContext ??
      (window as typeof window & { webkitAudioContext?: typeof AudioContext })
        .webkitAudioContext
    if (!Ctor) return
    const ctx = new Ctor()
    const analyser = ctx.createAnalyser()
    analyser.fftSize = 512
    ctx.createMediaStreamSource(stream).connect(analyser)
    audioCtxRef.current = ctx

    const data = new Uint8Array(analyser.fftSize)
    const tick = () => {
      analyser.getByteTimeDomainData(data)
      let sum = 0
      for (let i = 0; i < data.length; i += 1) {
        const v = (data[i]! - 128) / 128
        sum += v * v
      }
      const level = Math.min(1, Math.sqrt(sum / data.length) * 4)
      if (meterBarRef.current) {
        meterBarRef.current.style.width = `${Math.round(level * 100)}%`
      }
      meterRaf.current = requestAnimationFrame(tick)
    }
    tick()
  }

  // Request a silent mic preview on open: it populates labelled device lists,
  // runs the level meter, and front-loads the permission prompt so "record"
  // never fails mid-flow. Denied → the banner shows instead.
  useEffect(() => {
    if (!open) return
    setMode('screen')
    setMicId('')
    setCameraId('')
    setLanguage('')
    setBlocked(null)
    setCameraBlocked(null)
    setMics([])
    setCams([])

    let cancelled = false
    void (async () => {
      if (!navigator.mediaDevices?.getUserMedia) {
        setBlocked(
          'Media capture isn’t available in this browser. Try Chrome, Edge or Safari.',
        )
        return
      }
      try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
        if (cancelled) {
          stopTracks(stream)
          return
        }
        previewStreamRef.current = stream
        startMeter(stream)
        const trackLabel = stream.getAudioTracks()[0]?.label ?? ''
        const devices = await navigator.mediaDevices.enumerateDevices()
        if (cancelled) return
        const audio = devices.filter((device) => device.kind === 'audioinput')
        const video = devices.filter((device) => device.kind === 'videoinput')
        setMics(audio)
        setCams(video)
        // Default the select to the device the preview actually captured, so
        // the meter and the label agree.
        const captured = audio.find((device) => device.label === trackLabel)
        if (captured) setMicId(captured.deviceId)
      } catch (error) {
        if (!cancelled) setBlocked(permissionMessage(error))
      }
    })()

    return () => {
      cancelled = true
      stopMeter()
      stopTracks(previewStreamRef.current)
      previewStreamRef.current = null
      stopTracks(cameraStreamRef.current)
      cameraStreamRef.current = null
    }
  }, [open])

  // Self-view when the user picks a camera from the list.
  useEffect(() => {
    if (!open || !cameraId) {
      setCameraBlocked(null)
      stopTracks(cameraStreamRef.current)
      cameraStreamRef.current = null
      return
    }
    let cancelled = false
    void (async () => {
      try {
        const stream = await navigator.mediaDevices.getUserMedia({
          video: { deviceId: { exact: cameraId } },
        })
        if (cancelled) {
          stopTracks(stream)
          return
        }
        cameraStreamRef.current = stream
        if (cameraPreviewRef.current) {
          cameraPreviewRef.current.srcObject = stream
        }
      } catch {
        if (!cancelled) {
          setCameraBlocked(
            'Camera access is blocked — allow it in your browser to preview.',
          )
        }
      }
    })()
    return () => {
      cancelled = true
    }
  }, [open, cameraId])

  const selectedMic = mics.find((device) => device.deviceId === micId)
  const selectedCam = cams.find((device) => device.deviceId === cameraId)
  const hasPreview = previewStreamRef.current !== null

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Recording Setup"
      subtitle="Capture your screen and mic — you'll get a live transcript as you speak."
    >
      <div className="p-5">
        {blocked && (
          <div className="mb-4 rounded-lg border border-danger/25 bg-danger-wash px-3.5 py-2.5 text-[13px] text-danger">
            {blocked}
          </div>
        )}

        {/* ── Mode cards ─────────────────────────────────── */}
        <div className="grid grid-cols-2 gap-2.5">
          {(
            [
              { key: 'screen', label: 'Screen', icon: <MonitorIcon /> },
              { key: 'audio', label: 'Audio only', icon: <WaveIcon /> },
            ] as const
          ).map((card) => (
            <button
              key={card.key}
              type="button"
              onClick={() => setMode(card.key)}
              aria-pressed={mode === card.key}
              className={cn(
                'flex cursor-pointer flex-col items-center gap-2 rounded-xl border px-4 py-4 text-[13.5px] font-medium transition-colors [&_svg]:size-6',
                mode === card.key
                  ? 'border-brand bg-brand-wash text-ink'
                  : 'border-line-strong bg-surface-soft text-ink-dim hover:border-line hover:text-ink',
              )}
            >
              {card.icon}
              {card.label}
            </button>
          ))}
        </div>

        {mode === 'screen' && (
          <p className="mt-3 rounded-lg bg-surface-sunk px-3.5 py-2.5 text-[12.5px] leading-relaxed text-ink-dim">
            Enable tab or system audio in the screen-share dialog to capture
            shared audio.
          </p>
        )}

        {/* ── Devices ────────────────────────────────────── */}
        <div className="mt-4 flex flex-col gap-3.5">
          <div>
            <label
              htmlFor="record-mic"
              className="mb-1.5 block text-[12.5px] font-medium text-ink-dim"
            >
              Microphone
            </label>
            <div className="flex items-center gap-2.5 rounded-xl border border-line-strong bg-panel px-3.5">
              <MicIcon className="size-[17px] shrink-0 text-ink-faint" />
              {/* Live input level — the one bit of feedback that the chosen
                  mic is actually the one being listened to. */}
              <span
                className={cn(
                  'h-1.5 w-14 shrink-0 overflow-hidden rounded-full bg-surface-sunk',
                  !hasPreview && 'opacity-40',
                )}
              >
                <span
                  ref={meterBarRef}
                  className="block h-full rounded-full bg-ok transition-none"
                  style={{ width: 0 }}
                />
              </span>
              <select
                id="record-mic"
                value={micId}
                onChange={(event) => setMicId(event.target.value)}
                className="h-11 min-w-0 flex-1 cursor-pointer appearance-none bg-transparent text-[13.5px] text-ink outline-none"
              >
                <option value="">
                  {selectedMic?.label ?? 'Default microphone'}
                </option>
                {mics.map((device, index) => (
                  <option key={device.deviceId} value={device.deviceId}>
                    {device.label || `Microphone ${index + 1}`}
                  </option>
                ))}
              </select>
              <ChevronIcon className="size-4 shrink-0 text-ink-faint" />
            </div>
          </div>

          <div>
            <label
              htmlFor="record-camera"
              className="mb-1.5 block text-[12.5px] font-medium text-ink-dim"
            >
              Camera
            </label>
            <div className="flex items-center gap-2.5 rounded-xl border border-line-strong bg-panel px-3.5">
              {selectedCam ? (
                <CameraIcon className="size-[17px] shrink-0 text-ink-faint" />
              ) : (
                <CameraOffIcon className="size-[17px] shrink-0 text-ink-faint" />
              )}
              <select
                id="record-camera"
                value={cameraId}
                onChange={(event) => setCameraId(event.target.value)}
                className="h-11 min-w-0 flex-1 cursor-pointer appearance-none bg-transparent text-[13.5px] text-ink outline-none"
              >
                <option value="">No camera</option>
                {cams.map((device, index) => (
                  <option key={device.deviceId} value={device.deviceId}>
                    {device.label || `Camera ${index + 1}`}
                  </option>
                ))}
              </select>
              <ChevronIcon className="size-4 shrink-0 text-ink-faint" />
            </div>
            {selectedCam && (
              <>
                <video
                  ref={cameraPreviewRef}
                  muted
                  playsInline
                  autoPlay
                  className="mt-2 aspect-video w-36 rounded-lg border border-line bg-surface-sunk object-cover"
                />
                {mode === 'screen' && (
                  <p className="mt-1.5 text-[11.5px] text-ink-faint">
                    Self-view only — the recording captures your screen.
                  </p>
                )}
              </>
            )}
            {cameraBlocked && (
              <p className="mt-1.5 text-[12px] text-danger">{cameraBlocked}</p>
            )}
          </div>

          <div>
            <label
              htmlFor="record-lang"
              className="mb-1.5 block text-[12.5px] font-medium text-ink-dim"
            >
              Transcription Language
            </label>
            <div className="flex items-center gap-2.5 rounded-xl border border-line-strong bg-panel px-3.5">
              <GlobeIcon className="size-[17px] shrink-0 text-ink-faint" />
              <select
                id="record-lang"
                value={language}
                onChange={(event) => setLanguage(event.target.value)}
                disabled={!speechSupported()}
                className="h-11 min-w-0 flex-1 cursor-pointer appearance-none bg-transparent text-[13.5px] text-ink outline-none disabled:cursor-default disabled:opacity-50"
              >
                {RECOGNITION_LANGUAGES.map((option) => (
                  <option key={option.code} value={option.code}>
                    {option.label}
                  </option>
                ))}
              </select>
              <ChevronIcon className="size-4 shrink-0 text-ink-faint" />
            </div>
            {!speechSupported() && (
              <p className="mt-1.5 text-[12px] text-ink-faint">
                Live transcription needs Chrome, Edge or Safari — your recording
                still captures audio.
              </p>
            )}
          </div>
        </div>
      </div>

      <footer className="flex items-center justify-end gap-2 border-t border-line bg-surface-soft px-5 py-3.5">
        <Button variant="secondary" onClick={onClose}>
          Cancel
        </Button>
        <Button
          onClick={() =>
            onStart({ mode, micId, cameraId, language })
          }
          className="[&_svg]:size-4"
        >
          {mode === 'screen' ? <MonitorIcon /> : <MicIcon />}
          {mode === 'screen'
            ? 'Share Screen & Start Recording'
            : 'Start Recording'}
        </Button>
      </footer>
    </Modal>
  )
}
