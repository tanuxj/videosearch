/**
 * Editor-style in/out trimmer for the clip lightbox.
 *
 * ## Why it shows a window, not the whole video
 *
 * A full-length track is unusable for this job. On a 2h35m recording, a
 * 640px-wide timeline puts ~15 seconds behind every pixel — you could not place
 * a 4-second selection if you tried. So the track spans a *window* centred on
 * the match (±10s by default, giving ~0.03s per pixel) and the zoom control
 * widens it when someone wants a longer clip. The window is always clamped to
 * the real video bounds.
 *
 * ## Interaction
 *
 * * Drag either handle to set the in/out point.
 * * Drag the selected region to slide the whole clip without resizing it.
 * * Click anywhere on the track to move the playhead.
 * * Handles are real `role="slider"` elements: Tab to them, then arrow keys
 *   nudge by 0.1s (Shift for 1s), so this is operable without a mouse.
 */

import {
  useCallback,
  useMemo,
  useRef,
  useState,
  type PointerEvent as ReactPointerEvent,
  type KeyboardEvent as ReactKeyboardEvent,
} from 'react'
import { cn } from '../lib/cn'
import { timecodeExact } from '../lib/format'

export type Range = { start: number; end: number }

/** Zoom presets: half-width of the window, in seconds. */
const ZOOMS = [
  { label: '±10s', half: 10 },
  { label: '±30s', half: 30 },
  { label: '±2m', half: 120 },
  { label: '±5m', half: 300 },
]

/** Shortest clip we allow — below this the handles overlap and ffmpeg balks. */
const MIN_CLIP = 0.3

type Props = {
  /** Full video length, seconds. */
  duration: number
  /** The matched moment, used for the marker and the reset button. */
  match: Range
  value: Range
  onChange: (next: Range) => void
  /** Current playhead position, seconds. */
  currentTime: number
  onSeek: (seconds: number) => void
  /** Server-side cap (`MAX_CLIP_SECONDS`). Selection can never exceed it. */
  maxSeconds: number
}

export function ClipTrimmer({
  duration,
  match,
  value,
  onChange,
  currentTime,
  onSeek,
  maxSeconds,
}: Props) {
  const trackRef = useRef<HTMLDivElement>(null)
  const [zoom, setZoom] = useState(0)
  // Which element the current pointer gesture is moving.
  const dragRef = useRef<{
    kind: 'start' | 'end' | 'region' | 'seek'
    grabOffset: number
  } | null>(null)

  const centre = (match.start + match.end) / 2
  const half = ZOOMS[zoom]!.half

  // The visible span, clamped so it never runs past either end of the video.
  const view = useMemo(() => {
    const span = Math.min(half * 2, Math.max(duration, MIN_CLIP))
    let from = centre - span / 2
    if (from < 0) from = 0
    if (from + span > duration) from = Math.max(0, duration - span)
    return { from, span }
  }, [centre, half, duration])

  const toPercent = useCallback(
    (seconds: number) =>
      ((seconds - view.from) / view.span) * 100,
    [view],
  )

  const fromClientX = useCallback(
    (clientX: number) => {
      const rect = trackRef.current?.getBoundingClientRect()
      if (!rect || rect.width === 0) return view.from
      const ratio = (clientX - rect.left) / rect.width
      return view.from + Math.min(1, Math.max(0, ratio)) * view.span
    },
    [view],
  )

  const clampRange = useCallback(
    (next: Range): Range => {
      let { start, end } = next
      start = Math.max(0, Math.min(start, duration - MIN_CLIP))
      end = Math.min(duration, Math.max(end, start + MIN_CLIP))
      // The server refuses anything longer than `maxSeconds`, so the UI must
      // not let you build one — trim from the end, which is the edge the user
      // was most likely moving.
      if (end - start > maxSeconds) end = start + maxSeconds
      return { start, end }
    },
    [duration, maxSeconds],
  )

  function beginDrag(
    event: ReactPointerEvent,
    kind: 'start' | 'end' | 'region' | 'seek',
  ) {
    event.preventDefault()
    ;(event.currentTarget as HTMLElement).setPointerCapture?.(event.pointerId)
    const at = fromClientX(event.clientX)
    dragRef.current = {
      kind,
      // For a region drag, remember where inside the block we grabbed it so it
      // doesn't jump to centre on the first move.
      grabOffset: kind === 'region' ? at - value.start : 0,
    }
    if (kind === 'seek') onSeek(at)
  }

  function onPointerMove(event: ReactPointerEvent) {
    const drag = dragRef.current
    if (!drag) return
    const at = fromClientX(event.clientX)

    if (drag.kind === 'start') {
      onChange(clampRange({ start: at, end: value.end }))
    } else if (drag.kind === 'end') {
      onChange(clampRange({ start: value.start, end: at }))
    } else if (drag.kind === 'region') {
      const length = value.end - value.start
      let start = at - drag.grabOffset
      start = Math.max(0, Math.min(start, duration - length))
      onChange({ start, end: start + length })
    } else {
      onSeek(at)
    }
  }

  function endDrag() {
    dragRef.current = null
  }

  function onHandleKey(
    event: ReactKeyboardEvent,
    which: 'start' | 'end',
  ) {
    const step = event.shiftKey ? 1 : 0.1
    let delta = 0
    if (event.key === 'ArrowLeft') delta = -step
    else if (event.key === 'ArrowRight') delta = step
    else return
    // These arrows would otherwise bubble to the lightbox, which uses them to
    // step between matches — that would throw away the trim in progress.
    event.preventDefault()
    event.stopPropagation()
    onChange(
      clampRange(
        which === 'start'
          ? { start: value.start + delta, end: value.end }
          : { start: value.start, end: value.end + delta },
      ),
    )
  }

  const selectionLength = value.end - value.start
  const atLimit = selectionLength >= maxSeconds - 0.05
  const trimmed =
    Math.abs(value.start - match.start) > 0.05 ||
    Math.abs(value.end - match.end) > 0.05

  return (
    <div className="border-t border-line px-4 py-3">
      {/* Readout */}
      <div className="mb-2.5 flex flex-wrap items-center gap-x-4 gap-y-1.5">
        <div className="flex items-center gap-3 font-mono text-[12px] text-ink-mid">
          <span>
            <span className="text-ink-faint">in </span>
            {timecodeExact(value.start)}
          </span>
          <span>
            <span className="text-ink-faint">out </span>
            {timecodeExact(value.end)}
          </span>
          <span className={cn(atLimit ? 'text-warn' : 'text-ink')}>
            {selectionLength.toFixed(1)}s
          </span>
        </div>

        <div className="ml-auto flex items-center gap-1">
          {trimmed && (
            <button
              type="button"
              onClick={() => onChange({ ...match })}
              className="rounded-full px-2.5 py-1 text-[12px] font-medium text-ink-dim transition-colors hover:bg-surface-sunk hover:text-ink"
            >
              Reset to match
            </button>
          )}
          {ZOOMS.map((preset, index) => (
            <button
              key={preset.label}
              type="button"
              onClick={() => setZoom(index)}
              aria-pressed={index === zoom}
              className={cn(
                'rounded-full px-2 py-1 text-[11.5px] font-medium transition-colors',
                index === zoom
                  ? 'bg-surface-sunk text-ink'
                  : 'text-ink-faint hover:text-ink',
              )}
            >
              {preset.label}
            </button>
          ))}
        </div>
      </div>

      {/* Track */}
      <div
        ref={trackRef}
        onPointerMove={onPointerMove}
        onPointerUp={endDrag}
        onPointerCancel={endDrag}
        className="relative h-11 cursor-pointer touch-none select-none rounded-lg bg-surface-sunk"
        onPointerDown={(event) => beginDrag(event, 'seek')}
      >
        {/* The matched moment, so you can always see what you're trimming from. */}
        <span
          aria-hidden="true"
          className="absolute inset-y-0 bg-brand/10"
          style={{
            left: `${toPercent(match.start)}%`,
            width: `${toPercent(match.end) - toPercent(match.start)}%`,
          }}
        />

        {/* Selection */}
        <span
          onPointerDown={(event) => {
            event.stopPropagation()
            beginDrag(event, 'region')
          }}
          className="absolute inset-y-0 cursor-grab border-y-2 border-brand bg-brand/20 active:cursor-grabbing"
          style={{
            left: `${toPercent(value.start)}%`,
            width: `${toPercent(value.end) - toPercent(value.start)}%`,
          }}
        />

        {/* Playhead */}
        <span
          aria-hidden="true"
          className="pointer-events-none absolute inset-y-0 w-0.5 bg-ink"
          style={{ left: `${toPercent(currentTime)}%` }}
        />

        {/* Handles */}
        {(['start', 'end'] as const).map((which) => (
          <button
            key={which}
            type="button"
            role="slider"
            tabIndex={0}
            aria-label={which === 'start' ? 'Clip start' : 'Clip end'}
            aria-valuemin={0}
            aria-valuemax={duration}
            aria-valuenow={Number(value[which].toFixed(2))}
            aria-valuetext={timecodeExact(value[which])}
            onPointerDown={(event) => {
              event.stopPropagation()
              beginDrag(event, which)
            }}
            onKeyDown={(event) => onHandleKey(event, which)}
            className={cn(
              'absolute top-1/2 z-10 h-9 w-3 -translate-x-1/2 -translate-y-1/2',
              'cursor-ew-resize rounded-full border-2 border-white bg-brand',
              'shadow-[0_1px_3px_rgba(16,19,26,0.35)]',
              'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand',
            )}
            style={{ left: `${toPercent(value[which])}%` }}
          />
        ))}
      </div>

      <p className="mt-2 text-[11.5px] text-ink-faint">
        {atLimit
          ? `Clips are capped at ${Math.round(maxSeconds / 60)} minutes.`
          : 'Drag the handles to set in and out, or drag the selection to move it. Arrow keys nudge by 0.1s.'}
      </p>
    </div>
  )
}
