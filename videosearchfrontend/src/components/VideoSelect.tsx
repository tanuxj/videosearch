import { useEffect, useRef, useState } from 'react'
import type { VideoRecord } from '../lib/store'
import { CheckIcon, ChevronIcon, FilmIcon, PlayIcon, UploadIcon } from './Icons'
import { compactNumber, humanDuration } from '../lib/format'

type Props = {
  videos: VideoRecord[]
  selectedId: string | null
  onSelect: (id: string) => void
  onUpload: () => void
}

export function VideoSelect({ videos, selectedId, onSelect, onUpload }: Props) {
  const [open, setOpen] = useState(false)
  const rootRef = useRef<HTMLDivElement>(null)
  const selected = videos.find((video) => video.id === selectedId) ?? null

  useEffect(() => {
    if (!open) return
    const onPointer = (event: MouseEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false)
    }
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onPointer)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onPointer)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  return (
    <div className="vselect" ref={rootRef}>
      <button
        type="button"
        className={`vselect-trigger${open ? ' is-open' : ''}`}
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      >
        <span className="vselect-thumb">
          {selected?.poster ? (
            <img src={selected.poster} alt="" />
          ) : (
            <FilmIcon />
          )}
        </span>
        <span className="vselect-text">
          <b>{selected ? selected.name : 'Select a video'}</b>
          <span>
            {selected
              ? `${humanDuration(selected.duration)} · ${compactNumber(selected.frames)} frames indexed`
              : videos.length === 0
                ? 'Nothing indexed yet — upload one to start'
                : `${videos.length} videos ready`}
          </span>
        </span>
        <ChevronIcon />
      </button>

      {open && (
        <div className="vselect-menu" role="listbox">
          {videos.length > 0 && (
            <p className="vselect-label">Indexed videos</p>
          )}
          {videos.map((video) => (
            <button
              key={video.id}
              type="button"
              role="option"
              aria-selected={video.id === selectedId}
              className={`vselect-option${video.id === selectedId ? ' is-selected' : ''}`}
              onClick={() => {
                onSelect(video.id)
                setOpen(false)
              }}
            >
              <span className="vselect-thumb">
                {video.poster ? <img src={video.poster} alt="" /> : <PlayIcon />}
              </span>
              <span className="vselect-text">
                <b>{video.name}</b>
                <span>
                  {humanDuration(video.duration)} ·{' '}
                  {compactNumber(video.frames)} frames
                  {video.status === 'processing' && ' · indexing'}
                </span>
              </span>
              {video.id === selectedId && (
                <span className="vselect-check">
                  <CheckIcon />
                </span>
              )}
            </button>
          ))}

          <button
            type="button"
            className="vselect-add"
            onClick={() => {
              setOpen(false)
              onUpload()
            }}
          >
            <UploadIcon />
            Upload a new video
          </button>
        </div>
      )}
    </div>
  )
}
