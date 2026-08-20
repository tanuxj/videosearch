/**
 * Inline icons — self-contained.
 *
 * Every presentation attribute lives on the `<svg>` itself. These used to
 * inherit `fill: none; stroke: currentColor; stroke-width: …` from rules in
 * `index.css` scoped to class names like `.side-link svg` and `.btn svg`; when
 * those classes were replaced with utilities the icons lost their styling and
 * fell back to the SVG defaults (`fill: black; stroke: none`), which turned
 * outline shapes into solid black blobs. Nothing here depends on a parent rule
 * any more.
 *
 * Drawn on a 24x24 grid with a 1.75 stroke and round caps/joins, so they stay
 * legible down to ~14px. Colour comes from `currentColor`; size comes from the
 * `className` you pass (or the base `svg` rule in `styles.css`).
 */

import type { ReactNode } from 'react'

type Props = { className?: string }

/** Outline glyph. */
function Stroke({ children, className }: Props & { children: ReactNode }) {
  return (
    <svg
      viewBox="0 0 24 24"
      aria-hidden="true"
      className={className}
      fill="none"
      stroke="currentColor"
      strokeWidth={1.75}
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      {children}
    </svg>
  )
}

/** Solid glyph — for shapes that read better filled at small sizes. */
function Solid({ children, className }: Props & { children: ReactNode }) {
  return (
    <svg
      viewBox="0 0 24 24"
      aria-hidden="true"
      className={className}
      fill="currentColor"
      stroke="none"
    >
      {children}
    </svg>
  )
}

export const PlayIcon = ({ className }: Props) => (
  <Solid className={className}>
    <path d="M8 5.14v13.72L19 12 8 5.14z" />
  </Solid>
)

// Circle pulled slightly up-left and shrunk so the handle has room to read as a
// handle rather than a stub.
export const SearchIcon = ({ className }: Props) => (
  <Stroke className={className}>
    <circle cx="10.5" cy="10.5" r="6.5" />
    <path d="M15.4 15.4L20 20" />
  </Stroke>
)

// Filled: a sparkle drawn as an outline reads as noise at 14px.
export const SparkIcon = ({ className }: Props) => (
  <Solid className={className}>
    <path d="M11.5 2.5l1.7 4.8 4.8 1.7-4.8 1.7-1.7 4.8-1.7-4.8L5 9l4.8-1.7 1.7-4.8z" />
    <path d="M18.5 15.5l.85 2.15 2.15.85-2.15.85-.85 2.15-.85-2.15L15.5 18.5l2.15-.85.85-2.15z" />
  </Solid>
)

export const UploadIcon = ({ className }: Props) => (
  <Stroke className={className}>
    <path d="M12 15.5V4" />
    <path d="M7.5 8.5L12 4l4.5 4.5" />
    <path d="M4 16v2.5A1.5 1.5 0 005.5 20h13a1.5 1.5 0 001.5-1.5V16" />
  </Stroke>
)

// Chain link — used for the paste-a-link import mode.
export const LinkIcon = ({ className }: Props) => (
  <Stroke className={className}>
    <path d="M10.5 13.5a4 4 0 005.66 0l3-3a4 4 0 00-5.66-5.66l-1.2 1.2" />
    <path d="M13.5 10.5a4 4 0 00-5.66 0l-3 3a4 4 0 005.66 5.66l1.2-1.2" />
  </Stroke>
)

export const DownloadIcon = ({ className }: Props) => (
  <Stroke className={className}>
    <path d="M12 4v11.5" />
    <path d="M7.5 11L12 15.5 16.5 11" />
    <path d="M4 16v2.5A1.5 1.5 0 005.5 20h13a1.5 1.5 0 001.5-1.5V16" />
  </Stroke>
)

// Share: an arrow out of a tray — "hand this to someone" rather than "store".
export const ShareIcon = ({ className }: Props) => (
  <Stroke className={className}>
    <path d="M12 14.5V4" />
    <path d="M8 8L12 4l4 4" />
    <path d="M5 13.5v4A2.5 2.5 0 007.5 20h9a2.5 2.5 0 002.5-2.5v-4" />
  </Stroke>
)

// Film strip: outer frame plus two perforation columns. The old version drew a
// full centre cross-hatch, which turned into a muddy grid at small sizes.
export const FilmIcon = ({ className }: Props) => (
  <Stroke className={className}>
    <rect x="3" y="4.5" width="18" height="15" rx="2.5" />
    <path d="M7.5 4.5v15M16.5 4.5v15" />
    <path d="M3 12h4.5M16.5 12h4.5" />
  </Stroke>
)

// Library: four panes, evenly inset with a tighter corner radius so the shape
// stays crisp instead of blurring into four dots.
export const GridIcon = ({ className }: Props) => (
  <Stroke className={className}>
    <rect x="3.5" y="3.5" width="7.5" height="7.5" rx="1.75" />
    <rect x="13" y="3.5" width="7.5" height="7.5" rx="1.75" />
    <rect x="3.5" y="13" width="7.5" height="7.5" rx="1.75" />
    <rect x="13" y="13" width="7.5" height="7.5" rx="1.75" />
  </Stroke>
)

export const ClockIcon = ({ className }: Props) => (
  <Stroke className={className}>
    <circle cx="12" cy="12" r="8" />
    <path d="M12 7.5V12l3.2 1.9" />
  </Stroke>
)

export const BoltIcon = ({ className }: Props) => (
  <Stroke className={className}>
    <path d="M13.5 3L6 13h4.5l-1 8L18 11h-4.5l1-8z" />
  </Stroke>
)

export const LayersIcon = ({ className }: Props) => (
  <Stroke className={className}>
    <path d="M12 3.5l8.5 4.5-8.5 4.5L3.5 8 12 3.5z" />
    <path d="M3.5 12.5L12 17l8.5-4.5" />
    <path d="M3.5 16.5L12 21l8.5-4.5" />
  </Stroke>
)

export const ShieldIcon = ({ className }: Props) => (
  <Stroke className={className}>
    <path d="M12 3.2l7 2.6v5.4c0 4.3-2.9 8.2-7 9.6-4.1-1.4-7-5.3-7-9.6V5.8l7-2.6z" />
    <path d="M9.2 12l2.1 2.1 4.3-4.3" />
  </Stroke>
)

// Envelope. The flap now starts at the frame's own top corners — the old path
// began inside the rectangle, so the fold appeared to float.
export const MailIcon = ({ className }: Props) => (
  <Stroke className={className}>
    <rect x="3" y="5" width="18" height="14" rx="2.5" />
    <path d="M3.4 7.6l7.7 5.4a1.6 1.6 0 001.8 0l7.7-5.4" />
  </Stroke>
)

export const LockIcon = ({ className }: Props) => (
  <Stroke className={className}>
    <rect x="4.5" y="10" width="15" height="10" rx="2.5" />
    <path d="M8 10V7.5a4 4 0 018 0V10" />
  </Stroke>
)

export const UserIcon = ({ className }: Props) => (
  <Stroke className={className}>
    <circle cx="12" cy="8.5" r="3.75" />
    <path d="M5 19.5a7 7 0 0114 0" />
  </Stroke>
)

export const CheckIcon = ({ className }: Props) => (
  <Stroke className={className}>
    <path d="M5 12.5l4.5 4.5L19 7.5" />
  </Stroke>
)

export const SignOutIcon = ({ className }: Props) => (
  <Stroke className={className}>
    <path d="M14 6.5V5a2 2 0 00-2-2H6a2 2 0 00-2 2v14a2 2 0 002 2h6a2 2 0 002-2v-1.5" />
    <path d="M10.5 12H21M17.5 8.5L21 12l-3.5 3.5" />
  </Stroke>
)

export const CloseIcon = ({ className }: Props) => (
  <Stroke className={className}>
    <path d="M6.5 6.5l11 11M17.5 6.5l-11 11" />
  </Stroke>
)

export const ChevronIcon = ({ className }: Props) => (
  <Stroke className={className}>
    <path d="M7 10l5 5 5-5" />
  </Stroke>
)

export const ArrowLeftIcon = ({ className }: Props) => (
  <Stroke className={className}>
    <path d="M20 12H4M9.5 6.5L4 12l5.5 5.5" />
  </Stroke>
)

export const ArrowRightIcon = ({ className }: Props) => (
  <Stroke className={className}>
    <path d="M4 12h16M14.5 6.5L20 12l-5.5 5.5" />
  </Stroke>
)

export const TrashIcon = ({ className }: Props) => (
  <Stroke className={className}>
    <path d="M4.5 7h15" />
    <path d="M9.5 7V5.5A1.5 1.5 0 0111 4h2a1.5 1.5 0 011.5 1.5V7" />
    <path d="M6.5 7l.75 12a2 2 0 002 1.9h5.5a2 2 0 002-1.9L18.5 7" />
    <path d="M10.5 11v6M13.5 11v6" />
  </Stroke>
)

/** Overflow menu ("⋯"). */
export const MoreIcon = ({ className }: Props) => (
  <Solid className={className}>
    <circle cx="6" cy="12" r="1.6" />
    <circle cx="12" cy="12" r="1.6" />
    <circle cx="18" cy="12" r="1.6" />
  </Solid>
)

/** Tag, for metadata pills. */
export const TagIcon = ({ className }: Props) => (
  <Stroke className={className}>
    <path d="M11.6 3.5H5.5A2 2 0 003.5 5.5v6.1a2 2 0 00.59 1.42l7.4 7.4a2 2 0 002.83 0l6.1-6.1a2 2 0 000-2.83l-7.4-7.4a2 2 0 00-1.42-.59z" />
    <circle cx="8" cy="8" r="1.4" />
  </Stroke>
)

/* ── Recording ──────────────────────────────────────────── */

// Record glyph for the sidebar tab: a ring around a filled dot, drawn at
// stroke weight like every other nav icon.
export const RecordIcon = ({ className }: Props) => (
  <Stroke className={className}>
    <circle cx="12" cy="12" r="7.5" />
    <circle cx="12" cy="12" r="3.4" fill="currentColor" stroke="none" />
  </Stroke>
)

// Monitor with a small recording dot on its upper-right corner — the CTA for
// screen capture, and the selected state of the "Screen" mode card.
export const MonitorIcon = ({ className }: Props) => (
  <Stroke className={className}>
    <rect x="3" y="4.5" width="18" height="12.5" rx="2.5" />
    <path d="M9.5 20.5h5" />
    <path d="M12 17v3.5" />
    <circle cx="17.8" cy="7.2" r="1.5" fill="currentColor" stroke="none" />
  </Stroke>
)

export const MicIcon = ({ className }: Props) => (
  <Stroke className={className}>
    <rect x="9" y="3" width="6" height="11" rx="3" />
    <path d="M5.5 11.5a6.5 6.5 0 0013 0" />
    <path d="M12 18v3" />
  </Stroke>
)

// Camera body with the lens hood triangle on top-right.
export const CameraIcon = ({ className }: Props) => (
  <Stroke className={className}>
    <path d="M4 8.5A2 2 0 016 6.5h8a2 2 0 012 2v7a2 2 0 01-2 2H6a2 2 0 01-2-2v-7z" />
    <path d="M16 10.5l4-2.5v8l-4-2.5" />
  </Stroke>
)

// Same body crossed out — the "No camera" placeholder in the setup modal.
export const CameraOffIcon = ({ className }: Props) => (
  <Stroke className={className}>
    <path d="M4 8.5A2 2 0 016 6.5h8a2 2 0 012 2v7a2 2 0 01-2 2H6a2 2 0 01-2-2v-7z" />
    <path d="M16 10.5l4-2.5v8l-4-2.5" />
    <path d="M3.5 3.5l17 17" />
  </Stroke>
)

// Audio waveform bars — the "Audio only" mode card.
export const WaveIcon = ({ className }: Props) => (
  <Stroke className={className}>
    <path d="M4 10.5v3" />
    <path d="M8 8v8" />
    <path d="M12 5.5v13" />
    <path d="M16 8.5v7" />
    <path d="M20 11v2" />
  </Stroke>
)

export const GlobeIcon = ({ className }: Props) => (
  <Stroke className={className}>
    <circle cx="12" cy="12" r="8" />
    <path d="M4 12h16" />
    <path d="M12 4c2.5 2.3 3.8 5 3.8 8s-1.3 5.7-3.8 8c-2.5-2.3-3.8-5-3.8-8s1.3-5.7 3.8-8z" />
  </Stroke>
)

// Solid square — stop recording.
export const StopIcon = ({ className }: Props) => (
  <Solid className={className}>
    <rect x="6.5" y="6.5" width="11" height="11" rx="2.2" />
  </Solid>
)

/* ── Notifications ─────────────────────────────────────── */

// Bell — the header's in-app notification alert.
export const BellIcon = ({ className }: Props) => (
  <Stroke className={className}>
    <path d="M6 9.5a6 6 0 0112 0c0 4.5 1.5 5.5 1.5 5.5h-15S6 14 6 9.5z" />
    <path d="M10 18.5a2 2 0 004 0" />
  </Stroke>
)

/* ── Teams ──────────────────────────────────────────────── */

// Folder — the per-video "move to workspace" control.
export const FolderIcon = ({ className }: Props) => (
  <Stroke className={className}>
    <path d="M3.5 7.5A2 2 0 015.5 5.5h4l2 2.5h7a2 2 0 012 2v7a2 2 0 01-2 2h-13a2 2 0 01-2-2v-9.5z" />
  </Stroke>
)

// Two people — the Teams page's nav glyph. Drawn as overlapping busts so it
// reads as a group rather than a single person.
export const TeamsIcon = ({ className }: Props) => (
  <Stroke className={className}>
    <circle cx="9" cy="8.5" r="3.6" />
    <path d="M3.8 19.5a5.4 5.4 0 0110.4 0" />
    <circle cx="16.4" cy="10.2" r="2.7" />
    <path d="M15.8 14.4a4.6 4.6 0 014.9 5.1" />
  </Stroke>
)
