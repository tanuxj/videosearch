import { Link } from '../lib/router'
import { Modal } from './Modal'
import { ButtonLink } from './ui/Button'
import { CheckIcon, LockIcon } from './Icons'

/**
 * The trial → signup boundary, as a modal.
 *
 * Anonymous visitors can run the core search on the homepage, but every
 * persistent action (clip download, share links, transcription, history)
 * answers 401 from the server. Rather than showing an error, the UI catches
 * that status and opens this: one sentence naming what they were about to
 * do, the concrete things an account unlocks, and both ways in.
 */
export function PaywallModal({
  open,
  onClose,
  feature,
}: {
  open: boolean
  onClose: () => void
  /** What the visitor tried to do, e.g. "download this clip". */
  feature: string
}) {
  return (
    <Modal open={open} onClose={onClose} title="Create an account to unlock this feature">
      <div className="p-5 pt-4">
        <span className="grid size-11 place-items-center rounded-full border border-brand-line bg-brand-wash text-brand [&_svg]:size-5">
          <LockIcon />
        </span>

        <p className="mt-3.5 text-[14.5px] leading-relaxed text-ink">
          Sign up to {feature} — and to keep everything the trial throws away.
        </p>

        <ul className="mt-4 flex flex-col gap-2">
          {[
            'Download and save clips permanently',
            'Search across your whole library, not one video',
            'Transcripts, search history and shared links',
          ].map((line) => (
            <li key={line} className="flex items-start gap-2 text-[13.5px] text-ink-mid">
              <span className="mt-0.5 grid size-4.5 shrink-0 place-items-center rounded-full bg-brand-wash text-brand [&_svg]:size-3">
                <CheckIcon />
              </span>
              {line}
            </li>
          ))}
        </ul>

        <div className="mt-5 flex items-center gap-2">
          <ButtonLink as={Link} to="/signup" size="md" className="flex-1">
            Sign up free
          </ButtonLink>
          <ButtonLink as={Link} to="/login" variant="secondary" size="md" className="flex-1">
            Log in
          </ButtonLink>
        </div>

        <p className="mt-3.5 text-center text-[12px] text-ink-faint">
          Free · no credit card. Trial uploads are temporary — re-upload once
          you have an account and it's yours to keep.
        </p>
      </div>
    </Modal>
  )
}
