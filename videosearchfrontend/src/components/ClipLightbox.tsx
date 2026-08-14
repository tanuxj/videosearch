import { useCallback, useEffect, useRef, useState } from 'react'
import type { Clip } from '../lib/api'
import { downloadClip, saveBlob } from '../lib/api'
import { API_ENABLED } from '../lib/http'
import type { VideoRecord } from '../lib/store'
import type { ReactNode } from 'react'
import { Modal } from './Modal'
import { ClipTrimmer, type Range } from './ClipTrimmer'
import { Button } from './ui/Button'
import {
  ArrowLeftIcon,
  ArrowRightIcon,
  CloseIcon,
  DownloadIcon,
  FilmIcon,
} from './Icons'
import { timecode } from '../lib/format'

/**
 * Mirrors `MAX_CLIP_SECONDS` in the backend's video routes. The server rejects
 * anything longer with a 422, so the trimmer refuses to build one in the first
 * place — keep the two in step.
 */
const MAX_CLIP_SECONDS = 600

/** Square icon-only control used by the lightbox toolbar. */
function IconButton({
  label,
  children,
  disabled,
  onClick,
}: {
  label: string
  children: ReactNode
  disabled?: boolean
  onClick: () => void
}) {
  return (
    <button
      type="button"
      aria-label={label}
      disabled={disabled}
      onClick={onClick}
      className="grid size-8 place-items-center rounded-lg text-ink-dim transition-colors hover:bg-surface-sunk hover:text-ink disabled:pointer-events-none disabled:opacity-40 [&_svg]:size-4"
    >
      {children}
    </button>
  )
}

type Props = {
  clip: Clip | null
  clips: Clip[]
  video: VideoRecord | null
  src: string
  prompt: string
  onSelect: (clip: Clip) => void
  onClose: () => void
}

export function ClipLightbox({
  clip,
  clips,
  video,
  src,
  prompt,
  onSelect,
  onClose,
}: Props) {
  const playerRef = useRef<HTMLVideoElement>(null)
  const [downloading, setDownloading] = useState(false)
  const [downloadError, setDownloadError] = useState<string | null>(null)
  const index = clip ? clips.findIndex((item) => item.id === clip.id) : -1
  // Rank-relative confidence — matches the grid's bars (see Search.tsx).
  const topScore = Math.max(...clips.map((item) => item.score))

  /**
   * The user's trim. Starts at the match window and is what actually gets
   * played back and downloaded — `clip.start`/`clip.end` stay untouched so
   * "Reset to match" always has something to return to.
   */
  const [range, setRange] = useState<Range | null>(null)
  const [currentTime, setCurrentTime] = useState(0)

  // A new match resets the trim.
  useEffect(() => {
    setRange(clip ? { start: clip.start, end: clip.end } : null)
  }, [clip])

  const videoDuration = video?.duration ?? 0

  // Seek to the in-point and play whenever the selected match changes. Keyed on
  // clip.id rather than `range`, or every handle drag would restart playback.
  useEffect(() => {
    const player = playerRef.current
    if (!player || !clip) return
    player.currentTime = clip.start
    void player.play().catch(() => {
      /* autoplay blocked — the controls are right there */
    })
  }, [clip])

  // Stop at the out-point instead of letting the whole video run on, and keep
  // the playhead marker in sync. Reads the live range from a ref-like closure
  // over state so the listener doesn't need re-binding on every drag frame.
  useEffect(() => {
    const player = playerRef.current
    if (!player || !range) return
    const onTime = () => {
      setCurrentTime(player.currentTime)
      if (player.currentTime >= range.end) player.pause()
    }
    player.addEventListener('timeupdate', onTime)
    return () => player.removeEventListener('timeupdate', onTime)
  }, [range])

  useEffect(() => {
    if (!clip) return
    const onKey = (event: KeyboardEvent) => {
      // Don't steal arrows from the trimmer's handles — they nudge the in/out
      // points, and stepping to another match would discard the trim.
      const target = event.target as HTMLElement | null
      if (target?.closest('[role="slider"]')) return
      if (event.key === 'ArrowRight' && index < clips.length - 1) {
        onSelect(clips[index + 1]!)
      }
      if (event.key === 'ArrowLeft' && index > 0) {
        onSelect(clips[index - 1]!)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [clip, clips, index, onSelect])

  const seekTo = useCallback((seconds: number) => {
    const player = playerRef.current
    if (player) player.currentTime = seconds
    setCurrentTime(seconds)
  }, [])

  const onDownload = useCallback(async () => {
    if (!video || !range) return
    setDownloading(true)
    setDownloadError(null)
    try {
      const blob = await downloadClip(video.id, range.start, range.end)
      const base = video.name.replace(/\.[^/.]+$/, '').slice(0, 60) || 'clip'
      saveBlob(
        blob,
        `${base} [${timecode(range.start)}-${timecode(range.end)}].mp4`,
      )
    } catch {
      setDownloadError('Could not download this clip — try again.')
    } finally {
      setDownloading(false)
    }
  }, [video, range])

  return (
    <Modal open={Boolean(clip)} onClose={onClose} variant="stage">
      {clip && (
        <>
          {/* Media sits on near-black regardless of the light chrome around it —
              letterboxing a video against white washes out the picture. */}
          <div className="grid aspect-video w-full place-items-center bg-[#0c0e13]">
            {src ? (
              <video
                ref={playerRef}
                src={src}
                controls
                playsInline
                autoPlay
                className="size-full"
              />
            ) : (
              <div className="flex flex-col items-center px-8 text-center text-white/70 [&_svg]:size-8">
                <FilmIcon />
                <p className="mt-3 max-w-[46ch] text-[13.5px] leading-relaxed">
                  The video file isn’t attached to this tab, so playback is
                  unavailable. The match is at {timecode(clip.frame)}.
                </p>
              </div>
            )}
          </div>

          {/* Trimmer — only when we have a real duration to scale the track
              against and a playable source to scrub. */}
          {range && src && videoDuration > 0 && (
            <ClipTrimmer
              duration={videoDuration}
              match={{ start: clip.start, end: clip.end }}
              value={range}
              onChange={setRange}
              currentTime={currentTime}
              onSeek={seekTo}
              maxSeconds={MAX_CLIP_SECONDS}
            />
          )}

          <div className="flex flex-wrap items-center gap-3 border-t border-line px-4 py-3">
            <div className="min-w-0 flex-1">
              <b className="block truncate text-[13.5px] font-semibold text-ink">
                Match {index + 1} of {clips.length} ·{' '}
                <span className="font-mono font-medium">
                  {timecode(range?.start ?? clip.start)} –{' '}
                  {timecode(range?.end ?? clip.end)}
                </span>
              </b>
              <span className="block truncate text-[12px] text-ink-faint">
                {video?.name}
                {prompt && ` · “${prompt}”`}
              </span>
            </div>

            <span className="shrink-0 rounded-full border border-brand-line bg-brand-wash px-2.5 py-1 text-[12px] font-semibold text-brand">
              {Math.round((clip.score / Math.max(topScore, 0.001)) * 100)}% match
            </span>

            {API_ENABLED && (
              <Button
                variant="secondary"
                size="sm"
                disabled={downloading || !video}
                onClick={() => void onDownload()}
                title="Download this exact clip (start–end)"
                className="[&_svg]:size-4"
              >
                <DownloadIcon />
                {downloading ? 'Preparing…' : 'Download clip'}
              </Button>
            )}

            {downloadError && (
              <span className="text-[12px] text-danger">{downloadError}</span>
            )}

            <div className="flex shrink-0 items-center gap-1">
              <IconButton
                label="Previous match"
                disabled={index <= 0}
                onClick={() => onSelect(clips[index - 1]!)}
              >
                <ArrowLeftIcon />
              </IconButton>
              <IconButton
                label="Next match"
                disabled={index >= clips.length - 1}
                onClick={() => onSelect(clips[index + 1]!)}
              >
                <ArrowRightIcon />
              </IconButton>
              <IconButton label="Close" onClick={onClose}>
                <CloseIcon />
              </IconButton>
            </div>
          </div>
        </>
      )}
    </Modal>
  )
}
