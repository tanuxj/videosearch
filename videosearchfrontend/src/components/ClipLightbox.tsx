import { useEffect, useRef } from 'react'
import type { Clip } from '../lib/api'
import type { VideoRecord } from '../lib/store'
import { Modal } from './Modal'
import { ArrowLeftIcon, ArrowRightIcon, CloseIcon, FilmIcon } from './Icons'
import { timecode } from '../lib/format'

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
  const index = clip ? clips.findIndex((item) => item.id === clip.id) : -1

  // Seek to the match and play whenever the selected clip changes.
  useEffect(() => {
    const player = playerRef.current
    if (!player || !clip) return
    player.currentTime = clip.start
    void player.play().catch(() => {
      /* autoplay blocked — the controls are right there */
    })
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

  return (
    <Modal open={Boolean(clip)} onClose={onClose} variant="stage">
      {clip && (
        <>
          <div className="stage-frame">
            {src ? (
              <video ref={playerRef} src={src} controls playsInline autoPlay />
            ) : (
              <div className="player-placeholder">
                <FilmIcon />
                <p>
                  The video file isn’t attached to this tab, so playback is
                  unavailable. The match is at {timecode(clip.frame)}.
                </p>
              </div>
            )}
          </div>

          <div className="stage-bar">
            <div className="stage-info">
              <b>
                Match {index + 1} of {clips.length} · {timecode(clip.start)} –{' '}
                {timecode(clip.end)}
              </b>
              <span>
                {video?.name}
                {prompt && ` · “${prompt}”`}
              </span>
            </div>

            <span className="stage-score">
              {Math.round(clip.score * 100)}% match
            </span>

            <div className="stage-nav">
              <button
                type="button"
                className="icon-btn"
                aria-label="Previous match"
                disabled={index <= 0}
                onClick={() => onSelect(clips[index - 1]!)}
              >
                <ArrowLeftIcon />
              </button>
              <button
                type="button"
                className="icon-btn"
                aria-label="Next match"
                disabled={index >= clips.length - 1}
                onClick={() => onSelect(clips[index + 1]!)}
              >
                <ArrowRightIcon />
              </button>
              <button
                type="button"
                className="icon-btn"
                aria-label="Close"
                onClick={onClose}
              >
                <CloseIcon />
              </button>
            </div>
          </div>
        </>
      )}
    </Modal>
  )
}
