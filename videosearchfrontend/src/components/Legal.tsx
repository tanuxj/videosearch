import type { ReactNode } from 'react'
import { MarketingShell, APP_NAME } from './Shell'
import { Eyebrow } from './ui/Text'
import {
  LEGAL_CONTACT_EMAIL,
  LEGAL_OPERATOR,
} from '../lib/legal'

/**
 * Legal-document furniture (Terms of Service / Privacy Policy).
 *
 * Public pages rendered inside the marketing shell, with typography tuned
 * for long-form reading rather than the marketing grid.
 *
 * Legal identity constants (operator name, contact email, grievance officer)
 * live in `lib/legal` — update them before shipping. Have a lawyer review
 * both documents; nothing here is legal advice.
 */

/** Body paragraph. */
export function P({ children }: { children: ReactNode }) {
  return (
    <p className="mt-3 text-[14.5px] leading-[1.8] text-ink-dim">{children}</p>
  )
}

/** Bulleted list. */
export function Ul({ children }: { children: ReactNode }) {
  return (
    <ul className="mt-3 flex list-disc flex-col gap-2 pl-5 text-[14.5px] leading-[1.8] text-ink-dim marker:text-ink-faint">
      {children}
    </ul>
  )
}

/** Inline emphasis — a bold run inside a paragraph. */
export function B({ children }: { children: ReactNode }) {
  return <b className="font-semibold text-ink">{children}</b>
}

/** One numbered/headed section of a legal document. */
export function LegalSection({
  title,
  children,
}: {
  title: string
  children: ReactNode
}) {
  return (
    <section>
      <h2 className="text-[17px] font-semibold tracking-[-0.02em] text-ink">
        {title}
      </h2>
      <div className="mt-1">{children}</div>
    </section>
  )
}

/**
 * Short closing block for every legal document: a reminder that the
 * document isn't legal advice, plus the contact channel.
 */
export function LegalContactNote() {
  return (
    <p className="mt-2 border-t border-line pt-6 text-[13px] leading-relaxed text-ink-faint">
      This document is provided as-is and does not constitute legal advice.
      Questions about it? Email us at{' '}
      <b className="font-medium text-ink-dim">{LEGAL_CONTACT_EMAIL}</b>.
    </p>
  )
}

/** Full-page legal document shell. */
export function LegalDoc({
  eyebrow = 'Legal',
  title,
  updated,
  children,
}: {
  eyebrow?: string
  title: string
  /** Human-readable date, e.g. "August 16, 2026". */
  updated: string
  children: ReactNode
}) {
  const service = APP_NAME
  return (
    <MarketingShell>
      <article className="mx-auto w-full max-w-[760px] px-6 py-14">
        <Eyebrow>{eyebrow}</Eyebrow>
        <h1 className="mt-5 text-[clamp(1.9rem,4vw,2.6rem)] leading-tight font-semibold tracking-[-0.03em] text-ink">
          {title}
        </h1>
        <p className="mt-3 text-[12.5px] text-ink-faint">
          Last updated: {updated} · {service} · {LEGAL_OPERATOR}
        </p>
        <div className="mt-10 flex flex-col gap-9">{children}</div>
      </article>
    </MarketingShell>
  )
}
