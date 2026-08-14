/**
 * Brand mark — a play glyph above a scrubber: *a moment located on a timeline*,
 * which is the one thing this product does.
 *
 * Kept identical to `public/favicon.svg` so the tab icon and the header never
 * drift apart; edit both together.
 *
 * ## Why it is this simple
 *
 * The previous mark stacked six shapes — gradient tile, radial sheen, inner
 * hairline, lens circle, lens handle, triangle — inside a tile that renders at
 * **20px** in the sidebar. At that size the lens was ~8px across carrying a
 * 2.6-unit stroke, with a 3.5px triangle inside it: unreadable by construction.
 * This version is three shapes and survives 16px.
 *
 * It also drops the indigo→violet gradient, which stopped being on-brand when
 * the UI moved to one flat blue.
 *
 * Geometry notes: the triangle's centroid sits at x≈15.8 rather than 16 — a
 * right-pointing triangle looks centred only when nudged slightly left of true
 * centre. The bar is drawn as a translucent full-width track with an opaque
 * segment laid over it, rather than two adjacent rects, so no seam artefact
 * appears at the join when the mark is scaled down.
 */

/** Brand blue. Literal, not a token: a logo should not re-theme, and this has
 *  to match `public/favicon.svg`, which cannot read CSS variables. */
const BRAND = '#2563EB'

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
      <rect width="32" height="32" rx="7.5" fill={BRAND} />

      {/* The moment. */}
      <path
        d="M12.8 8.6 21.8 14.2 12.8 19.8Z"
        fill="#fff"
        stroke="#fff"
        strokeWidth="1.6"
        strokeLinejoin="round"
      />

      {/* The timeline it was found on. */}
      <rect
        x="8.2"
        y="23.1"
        width="15.6"
        height="2.6"
        rx="1.3"
        fill="#fff"
        fillOpacity=".42"
      />
      <rect x="8.2" y="23.1" width="8.6" height="2.6" rx="1.3" fill="#fff" />
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
