import { useEffect } from 'react'
import type { ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { AnimatePresence, motion } from 'motion/react'
import { cn } from '../lib/cn'
import { CloseIcon } from './Icons'

type ModalProps = {
  open: boolean
  onClose: () => void
  title?: string
  subtitle?: string
  /** `sheet` is the standard centred dialog, `stage` is the wide media view. */
  variant?: 'sheet' | 'stage'
  children: ReactNode
}

export function Modal({
  open,
  onClose,
  title,
  subtitle,
  variant = 'sheet',
  children,
}: ModalProps) {
  useEffect(() => {
    if (!open) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    window.addEventListener('keydown', onKey)
    return () => {
      document.body.style.overflow = previousOverflow
      window.removeEventListener('keydown', onKey)
    }
  }, [open, onClose])

  return createPortal(
    // AnimatePresence keeps the node mounted through its exit transition, so
    // the dialog fades out instead of vanishing on close.
    <AnimatePresence>
      {open && (
        <motion.div
          className="fixed inset-0 z-[100] grid place-items-center overflow-y-auto bg-ink/20 p-4"
          onMouseDown={onClose}
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.18 }}
        >
          <motion.div
            role="dialog"
            aria-modal="true"
            aria-label={title}
            onMouseDown={(event) => event.stopPropagation()}
            initial={{ opacity: 0, y: 10, scale: 0.985 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 6, scale: 0.99 }}
            transition={{ duration: 0.22, ease: [0.22, 1, 0.36, 1] }}
            className={cn(
              'relative w-full overflow-hidden rounded-2xl border border-line bg-panel',
              'shadow-[0_16px_40px_-16px_rgba(16,19,26,0.18)]',
              variant === 'stage' ? 'max-w-[1080px]' : 'max-w-[520px]',
            )}
          >
            {title && (
              <header className="flex items-start justify-between gap-4 border-b border-line px-5 py-4">
                <div>
                  <h2 className="text-[16.5px] font-semibold tracking-[-0.02em] text-ink">
                    {title}
                  </h2>
                  {subtitle && (
                    <p className="mt-0.5 text-[13px] text-ink-dim">
                      {subtitle}
                    </p>
                  )}
                </div>
                <button
                  type="button"
                  onClick={onClose}
                  aria-label="Close"
                  className="grid size-8 shrink-0 place-items-center rounded-lg text-ink-dim transition-colors hover:bg-surface-sunk hover:text-ink [&_svg]:size-4"
                >
                  <CloseIcon />
                </button>
              </header>
            )}
            {children}
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>,
    document.body,
  )
}
