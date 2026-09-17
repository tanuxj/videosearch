import { MarketingShell, APP_NAME } from '../components/Shell'
import { Link } from '../lib/router'
import { useAuth } from '../lib/auth'
import { AUTH_ENABLED } from '../lib/http'
import { ButtonLink } from '../components/ui/Button'
import { CheckIcon, CloseIcon } from '../components/Icons'

/**
 * Pricing / plans page.
 *
 * Compares the anonymous homepage demo with the full product, so the trial's
 * limits read as a plan boundary rather than arbitrariness. The paid tier
 * deliberately has no checkout yet — "Get started" routes to signup, which is
 * where a subscription flow attaches when one exists. Nothing here invents
 * features: every line maps to something the app already does.
 */

type Plan = {
  name: string
  price: string
  cadence: string
  blurb: string
  cta: { label: string; to: string }
  highlight?: boolean
  features: { label: string; included: boolean }[]
}

const PLANS: Plan[] = [
  {
    name: 'Free — Try it',
    price: '$0',
    cadence: 'no account needed',
    blurb: 'Test the search on the homepage, straight from your browser.',
    cta: { label: 'Try the demo', to: '/' },
    features: [
      { label: 'Upload one video at a time', included: true },
      { label: 'Search the uploaded video by description', included: true },
      { label: 'Watch the matching clips', included: true },
      { label: 'Video and searches auto-deleted after 30 minutes', included: true },
      { label: 'Clip downloads', included: false },
      { label: 'Saved clips, collections and history', included: false },
      { label: 'Transcript search and subtitles', included: false },
      { label: 'Persistent library across sessions', included: false },
    ],
  },
  {
    name: 'Pro',
    price: 'Sign up',
    cadence: 'free while in beta',
    blurb: 'The full product — everything the trial holds back.',
    cta: { label: 'Get started', to: '/signup' },
    highlight: true,
    features: [
      { label: 'Unlimited videos in your library', included: true },
      { label: 'Search across every video, any time', included: true },
      { label: 'Create, trim and edit clips', included: true },
      { label: 'Download clips as MP4', included: true },
      { label: 'Save clips and organise collections', included: true },
      { label: 'Transcript search, subtitles and re-transcription', included: true },
      { label: 'Search history and replayable past searches', included: true },
      { label: 'Share links, teams and workspaces', included: true },
    ],
  },
]

export default function Pricing() {
  const { user } = useAuth()

  return (
    <MarketingShell>
      <section className="mx-auto w-full max-w-[1080px] px-6 pt-14 pb-20">
        <div className="text-center">
          <h1 className="mx-auto max-w-[24ch] text-[clamp(2rem,4.5vw,2.9rem)] leading-[1.08] font-semibold tracking-[-0.03em] text-ink">
            Start free. Sign up for everything.
          </h1>
          <p className="mx-auto mt-4 max-w-[58ch] text-[16px] leading-relaxed text-ink-mid">
            The homepage demo is the real search engine on a short leash. An
            account takes the leash off — {APP_NAME} keeps your library,
            clips and history for as long as you want them.
          </p>
        </div>

        <div className="mt-12 grid gap-5 lg:grid-cols-2">
          {PLANS.map((plan) => (
            <div
              key={plan.name}
              className={
                plan.highlight
                  ? 'relative flex flex-col rounded-2xl border-2 border-brand bg-panel p-6 sm:p-7'
                  : 'flex flex-col rounded-2xl border border-line bg-panel p-6 sm:p-7'
              }
            >
              {plan.highlight && (
                <span className="absolute -top-3 left-6 rounded-full bg-brand px-2.5 py-0.5 text-[11px] font-semibold text-white">
                  Full product
                </span>
              )}

              <div className="flex items-baseline justify-between gap-3">
                <h2 className="text-[17px] font-semibold tracking-[-0.02em] text-ink">
                  {plan.name}
                </h2>
                <span className="text-[13px] text-ink-faint">{plan.cadence}</span>
              </div>
              <p className="mt-1 text-[26px] font-semibold tracking-[-0.02em] text-ink">
                {plan.price}
              </p>
              <p className="mt-2 text-[13.5px] leading-relaxed text-ink-dim">
                {plan.blurb}
              </p>

              <ul className="mt-5 flex flex-1 flex-col gap-2.5 border-t border-line pt-5">
                {plan.features.map((feature) => (
                  <li
                    key={feature.label}
                    className={
                      feature.included
                        ? 'flex items-start gap-2.5 text-[13.5px] text-ink'
                        : 'flex items-start gap-2.5 text-[13.5px] text-ink-faint'
                    }
                  >
                    <span
                      className={
                        feature.included
                          ? 'mt-px grid size-4.5 shrink-0 place-items-center rounded-full bg-brand-wash text-brand [&_svg]:size-3'
                          : 'mt-px grid size-4.5 shrink-0 place-items-center rounded-full bg-surface-sunk text-ink-faint [&_svg]:size-3'
                      }
                    >
                      {feature.included ? <CheckIcon /> : <CloseIcon />}
                    </span>
                    {feature.label}
                  </li>
                ))}
              </ul>

              <div className="mt-6">
                {plan.highlight && user ? (
                  <ButtonLink as={Link} to="/dashboard" variant="primary" size="lg" className="w-full">
                    Open your workspace
                  </ButtonLink>
                ) : (
                  <ButtonLink
                    as={Link}
                    to={plan.cta.to}
                    variant={plan.highlight ? 'primary' : 'secondary'}
                    size="lg"
                    className="w-full"
                  >
                    {plan.cta.label}
                  </ButtonLink>
                )}
              </div>
            </div>
          ))}
        </div>

        <p className="mx-auto mt-10 max-w-[62ch] text-center text-[13px] leading-relaxed text-ink-faint">
          {AUTH_ENABLED
            ? 'Trial uploads live for 30 minutes and are then deleted from our servers — nothing you do on the homepage is kept.'
            : 'This instance runs in open-access mode: every visitor shares one library and accounts are disabled.'}
        </p>
      </section>
    </MarketingShell>
  )
}
