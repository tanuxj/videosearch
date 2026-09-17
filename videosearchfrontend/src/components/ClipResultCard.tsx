import type { Clip } from '../lib/api'
import { timecode } from '../lib/format'
import { Card } from './ui/Card'
import { PlayIcon } from './Icons'

/**
 * One search result in a grid — thumbnail, rank, match meter.
 *
 * Shared by the authenticated Search page and the homepage trial so the demo
 * renders results exactly like the product does; `onOpen` hands the clip to
 * the caller's lightbox, which is where the two flows diverge (the trial's
 * is locked to playback-only).
 */
export function ClipResultCard({
  clip,
  index,
  topScore,
  minScore = 0,
  thumb,
  onOpen,
}: {
  clip: Clip
  index: number
  /** Highest score in this result set — the meter is rank-relative. */
  topScore: number
  /**
   * Backend's absolute match threshold for this search. Anchoring the meter
   * here keeps the display honest: a result set whose best score barely
   * cleared the floor reads as a weak match (small %), not a confident 100%.
   */
  minScore?: number
  /** JPEG data URL for the match frame, when it could be captured. */
  thumb?: string
  onOpen: (clip: Clip) => void
}) {
  // Hybrid confidence: rank-relative spread above the match floor, capped at
  // 100%. Pure rank-relative (score/top) shows a junk 0.243 as "100%" when
  // it's the best of a bad bunch; pure absolute shows every real CLIP match
  // (~0.25–0.45) as a discouraging near-miss. Scaling the band [floor, top]
  // to [0, 100] keeps ordering, rewards a clear winner, and refuses to
  // celebrate a result set where nothing actually matched.
  const band = Math.max(topScore - minScore, 0.001)
  const percent = Math.min(
    100,
    Math.max(1, Math.round(((clip.score - minScore) / band) * 100)),
  )

  return (
    // `group` is required here — the play overlay below reveals itself with
    // `group-hover`.
    <Card className="group h-full" interactive>
      <button
        type="button"
        onClick={() => onOpen(clip)}
        className="block w-full cursor-pointer p-2.5 text-left"
      >
        <span className="relative block aspect-video overflow-hidden rounded-xl border border-line bg-surface-sunk">
          {thumb ? (
            <img src={thumb} alt="" className="size-full object-cover" />
          ) : (
            <span className="grid size-full place-items-center bg-surface-sunk text-brand [&_svg]:size-6">
              <PlayIcon />
            </span>
          )}

          {/* Rank — the only place the result's position is stated. */}
          <span className="absolute top-2 left-2 rounded-md bg-ink/70 px-1.5 py-0.5 font-mono text-[11px] font-medium text-white">
            #{index + 1}
          </span>

          <span className="absolute inset-0 grid place-items-center bg-ink/0 opacity-0 transition-[opacity,background-color] duration-200 group-hover:bg-ink/20 group-hover:opacity-100">
            <i className="grid size-11 place-items-center rounded-full bg-panel text-brand [&_svg]:size-5">
              <PlayIcon />
            </i>
          </span>

          <span className="absolute right-2 bottom-2 rounded-md bg-ink/70 px-1.5 py-0.5 font-mono text-[11px] text-white">
            {timecode(clip.start)} – {timecode(clip.end)}
          </span>
        </span>

        <span className="mt-2.5 block px-0.5">
          <span className="block truncate text-[13.5px] font-medium text-ink">
            Frame at {timecode(clip.frame)}
          </span>

          {/* Match meter. Track is a lighter step of the same hue as the fill
              so the whole bar reads as one scale; the value stays in ink, the
              bar carries the colour. */}
          <span className="mt-2 flex items-center gap-2">
            <span className="relative block h-1.5 flex-1 overflow-hidden rounded-full bg-brand-wash">
              <i
                className="absolute inset-y-0 left-0 rounded-full bg-brand"
                style={{ width: `${percent}%` }}
              />
            </span>
            <span className="shrink-0 text-[12px] font-semibold text-ink-mid">
              {percent}%
            </span>
          </span>
        </span>
      </button>
    </Card>
  )
}
