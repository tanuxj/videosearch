/**
 * Headline treatments: staged word reveal and animated gradient text.
 */

import { type ReactNode } from 'react'
import { motion } from 'motion/react'
import { cn } from '../../lib/cn'

/**
 * Reveals a headline word by word.
 *
 * Splitting on whitespace and animating each word keeps the text selectable and
 * readable by screen readers (unlike a canvas or per-character approach), and
 * the whole phrase is present in the DOM from the first paint — the animation
 * only moves opacity and a few pixels of Y.
 */
export function TextGenerate({
  text,
  className,
  delay = 0,
  stagger = 0.045,
}: {
  text: string
  className?: string
  delay?: number
  stagger?: number
}) {
  const words = text.split(' ')

  return (
    <span className={className}>
      {words.map((word, index) => (
        <motion.span
          // Words repeat within a headline, so index has to be part of the key.
          key={`${word}-${index}`}
          className="inline-block whitespace-pre"
          initial={{ opacity: 0, y: '0.35em' }}
          animate={{ opacity: 1, y: 0 }}
          transition={{
            duration: 0.5,
            delay: delay + index * stagger,
            ease: [0.22, 1, 0.36, 1],
          }}
        >
          {word}
          {index < words.length - 1 ? ' ' : ''}
        </motion.span>
      ))}
    </span>
  )
}

/**
 * Text filled with a slowly drifting brand gradient.
 *
 * `background-clip: text` needs a transparent text colour, and `index.css`
 * sets an explicit colour on h1–h4 — the `text-transparent` utility wins
 * because Tailwind's layer outranks the legacy layer (see styles.css).
 */
export function GradientText({
  children,
  className,
}: {
  children: ReactNode
  className?: string
}) {
  return (
    <span
      className={cn(
        'bg-clip-text text-transparent',
        'bg-[linear-gradient(100deg,var(--accent),var(--accent-2),var(--accent))]',
        'bg-[length:220%_100%] animate-shimmer',
        className,
      )}
    >
      {children}
    </span>
  )
}

/** Small pill used above headlines. */
export function Eyebrow({
  children,
  className,
}: {
  children: ReactNode
  className?: string
}) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-2 rounded-full border border-brand-line bg-brand-wash',
        'px-3 py-1 text-[12.5px] font-medium text-brand',
        className,
      )}
    >
      {children}
    </span>
  )
}
