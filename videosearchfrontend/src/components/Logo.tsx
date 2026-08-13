/**
 * Brand mark — a search lens with a play glyph centred in it, on a gradient
 * tile. Kept identical to `public/favicon.svg` so the tab icon and the header
 * never drift apart; edit both together.
 *
 * The glyph geometry is deliberate: the triangle's centroid sits exactly on
 * the lens centre (14.4, 14.4), so it reads as balanced down to 16px.
 */

type Props = {
  /** Rendered size in px. The artwork is drawn on a 32-unit grid. */
  size?: number
  className?: string
}

export function LogoMark({ size = 32, className }: Props) {
  return (
    <svg
      viewBox="0 0 32 32"
      width={size}
      height={size}
      className={className}
      role="img"
      aria-hidden="true"
    >
      <defs>
        <linearGradient
          id="sivTile"
          x1="0"
          y1="0"
          x2="32"
          y2="32"
          gradientUnits="userSpaceOnUse"
        >
          <stop offset="0" stopColor="#6366F1" />
          <stop offset=".55" stopColor="#7C5CF5" />
          <stop offset="1" stopColor="#9333EA" />
        </linearGradient>
        <radialGradient
          id="sivSheen"
          cx="0"
          cy="0"
          r="1"
          gradientUnits="userSpaceOnUse"
          gradientTransform="translate(5 3) rotate(52) scale(30)"
        >
          <stop offset="0" stopColor="#fff" stopOpacity=".34" />
          <stop offset="1" stopColor="#fff" stopOpacity="0" />
        </radialGradient>
      </defs>

      <rect width="32" height="32" rx="8" fill="url(#sivTile)" />
      <rect width="32" height="32" rx="8" fill="url(#sivSheen)" />
      <rect
        x=".5"
        y=".5"
        width="31"
        height="31"
        rx="7.5"
        fill="none"
        stroke="#fff"
        strokeOpacity=".22"
      />

      <g fill="none" stroke="#fff" strokeWidth="2.6" strokeLinecap="round">
        <circle cx="14.4" cy="14.4" r="6.9" />
        <path d="M19.85 19.85 24 24" />
      </g>

      <path
        d="M12.5 11.5 18.3 14.4 12.5 17.3Z"
        fill="#fff"
        stroke="#fff"
        strokeWidth="1.1"
        strokeLinejoin="round"
      />
    </svg>
  )
}

/**
 * Wordmark. Splits a `SearchInVideo`-style name into three parts so the
 * connecting word can carry the gradient; any other name renders as-is.
 */
const WORDMARK =
  'text-[15.5px] font-semibold tracking-[-0.02em] text-ink whitespace-nowrap'

export function Wordmark({ name }: { name: string }) {
  const parts = /^(search)(in)(video)$/i.exec(name)
  if (!parts) return <span className={WORDMARK}>{name}</span>

  return (
    <span className={WORDMARK}>
      {parts[1]}
      {/* The connecting word carries the brand colour — flat, no gradient. */}
      <em className="text-brand not-italic">{parts[2]}</em>
      {parts[3]}
    </span>
  )
}
