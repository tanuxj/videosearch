import { useState } from 'react'
import { shareLinkFor } from '../lib/api'
import { Button } from './ui/Button'
import { CheckIcon, ShareIcon } from './Icons'

/**
 * Copies a video's share link to the clipboard and confirms with a check.
 *
 * The link is minted lazily on the backend and stable, so clicking again
 * copies the same URL. `suffix` is appended to the link — the clip lightbox
 * passes `?t=<timecode>` so a viewer lands on the exact moment.
 */
export function ShareButton({
  videoId,
  suffix = '',
  label = 'Copy share link',
  withText = false,
}: {
  videoId: string
  /** Appended to the copied link, e.g. `?t=4:08` to share a moment. */
  suffix?: string
  label?: string
  /** Render as a labelled button instead of an icon-only ghost. */
  withText?: boolean
}) {
  const [copied, setCopied] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function onShare() {
    try {
      const link = await shareLinkFor(videoId)
      await navigator.clipboard.writeText(`${link}${suffix}`)
      setCopied(true)
      setError(null)
      window.setTimeout(() => setCopied(false), 1600)
    } catch {
      setError('Could not copy the link — try again.')
      window.setTimeout(() => setError(null), 2000)
    }
  }

  if (withText) {
    return (
      <Button
        variant="secondary"
        size="sm"
        onClick={() => void onShare()}
        title={error ?? label}
        className="[&_svg]:size-4"
      >
        {copied ? <CheckIcon /> : <ShareIcon />}
        {copied ? 'Copied' : 'Share moment'}
      </Button>
    )
  }

  return (
    <button
      type="button"
      aria-label={label}
      title={error ?? (copied ? 'Link copied' : label)}
      onClick={() => void onShare()}
      className={`grid size-8 shrink-0 place-items-center rounded-lg transition-colors [&_svg]:size-4 ${
        copied
          ? 'bg-brand-wash text-brand'
          : 'text-ink-dim hover:bg-surface-sunk hover:text-ink'
      }`}
    >
      {copied ? <CheckIcon /> : <ShareIcon />}
    </button>
  )
}
