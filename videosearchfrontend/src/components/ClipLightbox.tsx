import { useCallback, useEffect, useRef, useState } from 'react'
import type { Clip } from '../lib/api'
import { downloadClip, saveBlob } from '../lib/api'
import { API_ENABLED } from '../lib/http'
import type { VideoRecord } from '../lib/store'
import type { ReactNode } from 'react'
import { Modal } from './Modal'
import { Button } from './ui/Button'
import {
  ArrowLeftIcon,
  ArrowRightIcon,
  CloseIcon,
  DownloadIcon,
  FilmIcon,
} from './Icons'
import { timecode } from '../lib/format'

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

  // Seek to the match and play whenever the selected clip changes.
  useEffect(() => {
    const player = playerRef.current
    if (!player || !clip) return
    player.currentTime = clip.start
    void player.play().catch(() => {
      /* autoplay blocked — the controls are right there */
    })
  }, [clip])

  // The match has a defined window — stop the moment playback passes it
  // instead of letting the full video run on past the clip's end.
  useEffect(() => {
    const player = playerRef.current
    if (!player || !clip) return
    const stopAtEnd = () => {
      if (player.currentTime >= clip.end) player.pause()
    }
    player.addEventListener('timeupdate', stopAtEnd)
    return () => player.removeEventListener('timeupdate', stopAtEnd)
  }, [clip])

  useEffect(() => {
    if (!clip) return
    const onKey = (event: KeyboardEvent) => {
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

  const onDownload = useCallback(async () => {
    if (!video || !clip) return
    setDownloading(true)
    setDownloadError(null)
    try {
      const blob = await downloadClip(video.id, clip.start, clip.end)
      const base = video.name.replace(/\.[^/.]+$/, '').slice(0, 60) || 'clip'
      saveBlob(blob, `${base} [${timecode(clip.start)}-${timecode(clip.end)}].mp4`)
    } catch {
      setDownloadError('Could not download this clip — try again.')
    } finally {
      setDownloading(false)
    }
  }, [video, clip])

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

          <div className="flex flex-wrap items-center gap-3 border-t border-line px-4 py-3">
            <div className="min-w-0 flex-1">
              <b className="block truncate text-[13.5px] font-semibold text-ink">
                Match {index + 1} of {clips.length} ·{' '}
                <span className="font-mono font-medium">
                  {timecode(clip.start)} – {timecode(clip.end)}
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
