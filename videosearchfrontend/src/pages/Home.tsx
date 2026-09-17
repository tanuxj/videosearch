import { TrialDemo } from '../components/TrialDemo'
import { APP_NAME, MarketingShell } from '../components/Shell'
import { useAuth } from '../lib/auth'
import { AUTH_ENABLED } from '../lib/http'
import { Link, useNavigate } from '../lib/router'
import { ButtonLink } from '../components/ui/Button'
import { Eyebrow } from '../components/ui/Text'

/**
 * Public homepage.
 *
 * Signed-out visitors get the demo itself, not a brochure: the trial below is
 * the real pipeline (upload → index → search → watch), with everything
 * persistent locked behind signup. Signed-in visitors are pointed into the
 * product.
 */
export default function Home() {
  const { user } = useAuth()
  const navigate = useNavigate()

  // Auth off (open access) or signed in — the app is the product, skip the demo.
  if (!AUTH_ENABLED || user) {
    return (
      <MarketingShell>
        <section className="mx-auto w-full max-w-[1080px] px-6 pt-16 pb-12 text-center sm:pt-24">
          <h1 className="mx-auto max-w-[24ch] text-[clamp(2rem,4.5vw,3rem)] leading-[1.08] font-semibold tracking-[-0.03em] text-ink">
            Welcome back
          </h1>
          <p className="mx-auto mt-4 max-w-[56ch] text-[16px] leading-relaxed text-ink-mid">
            Your library is right where you left it.
          </p>
          <div className="mt-7 flex justify-center">
            <ButtonLink as={Link} to="/search" size="lg">
              Open your workspace
            </ButtonLink>
          </div>
        </section>
      </MarketingShell>
    )
  }

  return (
    <MarketingShell>
      {/* ── Hero + trial ────────────────────────────────────── */}
      <section className="mx-auto w-full max-w-[760px] px-6 pt-12 pb-16 sm:pt-16">
        <div className="text-center">
          <Eyebrow>
            <span className="rounded-full bg-brand px-1.5 py-px text-[11px] font-semibold text-white">
              Free demo
            </span>
            No account needed
          </Eyebrow>

          <h1 className="mx-auto mt-5 max-w-[22ch] text-[clamp(2rem,5vw,3.25rem)] leading-[1.07] font-semibold tracking-[-0.03em] text-ink">
            Search inside your video
          </h1>

          <p className="mx-auto mt-4 max-w-[58ch] text-[16px] leading-relaxed text-ink-mid">
            Upload a clip, describe a moment in plain language, and land on the
            exact second it happens. {APP_NAME} indexes every frame — try it
            right here, right now.
          </p>
        </div>

        <div className="mt-8">
          <TrialDemo />
        </div>
      </section>

      {/* ── What an account adds ────────────────────────────── */}
      <section className="border-t border-line bg-surface-soft">
        <div className="mx-auto w-full max-w-[1080px] px-6 py-16">
          <div className="text-center">
            <h2 className="mx-auto max-w-[30ch] text-[clamp(1.4rem,3vw,1.9rem)] leading-tight font-semibold tracking-[-0.025em] text-ink">
              The demo throws everything away.
              <br className="hidden sm:block" /> An account keeps it.
            </h2>
            <p className="mx-auto mt-3 max-w-[56ch] text-[15px] leading-relaxed text-ink-dim">
              Signing up unlocks the full product — built for people who live
              in footage.
            </p>
          </div>

          <div className="mx-auto mt-9 grid max-w-[860px] gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {[
              {
                title: 'Search your whole library',
                body: 'Every video you upload stays indexed and searchable — across files, not one at a time.',
              },
              {
                title: 'Download and save clips',
                body: 'Cut the exact moments you found and export them as MP4, trimmed to the frame.',
              },
              {
                title: 'Transcripts and history',
                body: 'Search what was said, revisit past searches, and share links to any moment.',
              },
            ].map((item) => (
              <div key={item.title} className="rounded-2xl border border-line bg-panel p-5">
                <h3 className="text-[14.5px] font-semibold text-ink">{item.title}</h3>
                <p className="mt-1.5 text-[13.5px] leading-relaxed text-ink-dim">
                  {item.body}
                </p>
              </div>
            ))}
          </div>

          <div className="mt-8 flex flex-wrap items-center justify-center gap-2.5">
            <ButtonLink as={Link} to="/signup" size="lg">
              Create a free account
            </ButtonLink>
            <button
              type="button"
              onClick={() => navigate('/pricing')}
              className="text-[14px] font-medium text-ink-mid underline underline-offset-4 transition-colors hover:text-ink"
            >
              Compare plans
            </button>
          </div>
        </div>
      </section>
    </MarketingShell>
  )
}
