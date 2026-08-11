import { useEffect } from 'react'
import type { ReactNode } from 'react'
import { createPortal } from 'react-dom'
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

  if (!open) return null

  return createPortal(
    <div className="overlay" onMouseDown={onClose}>
      <div
        className={`modal modal-${variant}`}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onMouseDown={(event) => event.stopPropagation()}
      >
        {title && (
          <header className="modal-head">
            <div>
              <h2>{title}</h2>
              {subtitle && <p>{subtitle}</p>}
            </div>
            <button
              type="button"
              className="icon-btn"
              onClick={onClose}
              aria-label="Close"
            >
              <CloseIcon />
            </button>
          </header>
        )}
        {children}
      </div>
    </div>,
    document.body,
  )
}
