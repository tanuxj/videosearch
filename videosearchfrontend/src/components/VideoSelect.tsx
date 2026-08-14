import { useEffect, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import type { VideoRecord } from '../lib/store'
import { cn } from '../lib/cn'
import { CheckIcon, ChevronIcon, FilmIcon, PlayIcon, UploadIcon } from './Icons'
import { compactNumber, humanDuration } from '../lib/format'

/**
 * What this video is actually searchable by.
 *
 * A frame count is only meaningful when the local CLIP index is the one
 * answering. With it disabled server-side a video has zero frames forever, so
 * reporting "0 frames indexed" beside a green "Indexed" chip describes
 * nothing and reads like a failure. Name the index that exists instead.
 */
function indexSummary(video: VideoRecord): string {
  const hasLocal = video.frames > 0
  const remote = video.remoteIndexStatus

  if (hasLocal && remote === 'ready') return 'visual + speech search'
  if (hasLocal) return `${compactNumber(video.frames)} frames indexed`
  if (remote === 'ready') return 'visual + speech search'
  if (remote === 'processing' || remote === 'pending') return 'indexing…'
  if (remote === 'failed') return 'indexing failed'
  return 'not searchable yet'
}

type Props = {
  videos: VideoRecord[]
  selectedId: string | null
  onSelect: (id: string) => void
  onUpload: () => void
}

const THUMB =
  'grid size-9 shrink-0 place-items-center overflow-hidden rounded-lg border border-line bg-surface-sunk text-brand [&_svg]:size-4 [&_img]:size-full [&_img]:object-cover'

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
    <div className="relative min-w-0 flex-1" ref={rootRef}>
      <button
        type="button"
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
        className={cn(
          'flex w-full items-center gap-2.5 rounded-xl border bg-panel px-2.5 py-2 text-left',
          'transition-[border-color,background-color] duration-150',
          open
            ? 'border-brand bg-brand-wash/40'
            : 'border-line hover:border-line-strong hover:bg-surface-soft',
        )}
      >
        <span className={THUMB}>
          {selected?.poster ? (
            <img src={selected.poster} alt="" />
          ) : (
            <FilmIcon />
          )}
        </span>
        <span className="min-w-0 flex-1">
          <b className="block truncate text-[13.5px] font-semibold text-ink">
            {selected ? selected.name : 'Select a video'}
          </b>
          <span className="block truncate text-[11.5px] text-ink-faint">
            {selected
              ? `${humanDuration(selected.duration)} · ${indexSummary(selected)}`
              : videos.length === 0
                ? 'Nothing indexed yet — upload one to start'
                : `${videos.length} videos ready`}
          </span>
        </span>
        <span
          className={cn(
            'shrink-0 text-ink-faint transition-transform duration-200 [&_svg]:size-4',
            open && 'rotate-180',
          )}
        >
          <ChevronIcon />
        </span>
      </button>

      <AnimatePresence>
        {open && (
          <motion.div
            role="listbox"
            initial={{ opacity: 0, y: -4, scale: 0.99 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -4, scale: 0.99 }}
            transition={{ duration: 0.16, ease: [0.22, 1, 0.36, 1] }}
            className="absolute top-[calc(100%+6px)] left-0 z-50 max-h-[340px] w-full min-w-[280px] overflow-y-auto rounded-xl border border-line bg-panel p-1.5 shadow-[0_12px_28px_-12px_rgba(16,19,26,0.18)]"
          >
            {videos.length > 0 && (
              <p className="px-2 pt-1 pb-1.5 text-[11px] font-semibold tracking-[0.07em] text-ink-faint uppercase">
                Indexed videos
              </p>
            )}
            {videos.map((video) => {
              const isSelected = video.id === selectedId
              return (
                <button
                  key={video.id}
                  type="button"
                  role="option"
                  aria-selected={isSelected}
                  onClick={() => {
                    onSelect(video.id)
                    setOpen(false)
                  }}
                  className={cn(
                    'flex w-full items-center gap-2.5 rounded-lg px-2 py-1.5 text-left transition-colors',
                    isSelected
                      ? 'bg-brand-wash'
                      : 'hover:bg-surface-sunk',
                  )}
                >
                  <span className={THUMB}>
                    {video.poster ? (
                      <img src={video.poster} alt="" />
                    ) : (
                      <PlayIcon />
                    )}
                  </span>
                  <span className="min-w-0 flex-1">
                    <b
                      className={cn(
                        'block truncate text-[13px] font-medium',
                        isSelected ? 'text-brand' : 'text-ink',
                      )}
                    >
                      {video.name}
                    </b>
                    <span className="block truncate text-[11px] text-ink-faint">
                      {humanDuration(video.duration)} ·{' '}
                      {indexSummary(video)}
                      {video.status === 'processing' && ' · indexing'}
                    </span>
                  </span>
                  {isSelected && (
                    <span className="shrink-0 text-brand [&_svg]:size-4">
                      <CheckIcon />
                    </span>
                  )}
                </button>
              )
            })}

            <button
              type="button"
              onClick={() => {
                setOpen(false)
                onUpload()
              }}
              className="mt-1 flex w-full items-center gap-2 rounded-lg border-t border-line px-2 py-2 text-[13px] font-medium text-brand transition-colors hover:bg-brand-wash [&_svg]:size-4"
            >
              <UploadIcon />
              Upload a new video
            </button>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
