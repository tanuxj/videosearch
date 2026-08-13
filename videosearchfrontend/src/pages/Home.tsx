import { Link } from '../lib/router'
import { useAuth } from '../lib/auth'
import { APP_NAME, MarketingShell } from '../components/Shell'
import { BentoCard, BentoGrid, Card } from '../components/ui/Card'
import { Eyebrow, SectionHead } from '../components/ui/Text'
import { ButtonLink } from '../components/ui/Button'
import {
  BoltIcon,
  ClockIcon,
  LayersIcon,
  PlayIcon,
  SearchIcon,
  ShieldIcon,
  SparkIcon,
} from '../components/Icons'

const FEATURES = [
  {
    icon: SparkIcon,
    title: 'Describe it, don’t scrub for it',
    body: 'Type the scene the way you’d describe it out loud. No tags, no filenames, no manual chaptering.',
    span: '2x1',
  },
  {
    icon: LayersIcon,
    title: 'Every frame indexed',
    body: 'Frames are sampled through the upload and embedded with CLIP, so the whole timeline is searchable — not just the parts you labelled.',
    span: '1x2',
  },
  {
    icon: BoltIcon,
    title: 'Jump straight to the moment',
    body: 'Results come back as clips with timestamps. Click one and the player seeks to that exact second.',
    span: '1x1',
  },
  {
    icon: ClockIcon,
    title: 'Minutes, not afternoons',
    body: 'A ten-minute video indexes in the time it takes to make coffee, and stays searchable forever after.',
    span: '1x1',
  },
  {
    icon: SearchIcon,
    title: 'Visual search, no transcript',
    body: 'Matching runs on what the camera saw, so silent footage, screen recordings and B-roll all work the same.',
    span: '2x1',
  },
  {
    icon: ShieldIcon,
    title: 'Your library, your rules',
    body: 'Videos stay in your workspace. Delete one and its frame vectors go with it.',
    span: '1x1',
  },
] as const

const STEPS = [
  {
    title: 'Upload your video',
    body: 'Drop in an MP4, MOV or WebM. Indexing starts the moment the file lands.',
  },
  {
    title: 'We index every frame',
    body: 'Frames are pulled at a fixed interval, embedded with CLIP and stored with their timestamps.',
  },
  {
    title: 'Prompt and jump',
    body: 'Describe the scene. Matching clips come back ranked, and one click seeks the player there.',
  },
]

const PREVIEW_ROWS = [
  { time: '02:14', score: 94, label: 'Wide shot, red car entering frame', top: true },
  { time: '05:38', score: 87, label: 'Highway overpass, traffic moving' },
  { time: '11:02', score: 71, label: 'Car park exit, similar palette' },
]

export default function Home() {
  const { user } = useAuth()
  const primaryHref = user ? '/search' : '/signup'
  const primaryLabel = user ? 'Open your workspace' : 'Start free'

  return (
    <MarketingShell>
      {/* ── Hero ───────────────────────────────────────────── */}
      <section className="mx-auto w-full max-w-[1080px] px-6 pt-16 pb-12 text-center sm:pt-24">
        <Eyebrow>
          <span className="rounded-full bg-brand px-1.5 py-px text-[11px] font-semibold text-white">
            New
          </span>
          Visual search powered by CLIP
        </Eyebrow>

        <h1 className="mx-auto mt-6 max-w-[20ch] text-[clamp(2.2rem,5.5vw,3.75rem)] leading-[1.06] font-semibold tracking-[-0.03em] text-ink">
          Find the exact moment in any video
        </h1>

        <p className="mx-auto mt-5 max-w-[60ch] text-[16.5px] leading-relaxed text-ink-mid">
          {APP_NAME} indexes every frame of your footage, so you can describe a
          scene in plain language and land on the second it happens — no
          scrubbing, no transcripts, no tagging.
        </p>

        <div className="mt-8 flex flex-wrap items-center justify-center gap-2.5">
          <ButtonLink as={Link} to={primaryHref} size="lg">
            {primaryLabel}
          </ButtonLink>
          <ButtonLink as="a" href="#how" variant="secondary" size="lg">
            See how it works
          </ButtonLink>
        </div>

        <p className="mt-4 text-[12.5px] text-ink-faint">
          No credit card required · Your first 5 videos are on us
        </p>
      </section>

      {/* ── Product preview ────────────────────────────────── */}
      <section className="mx-auto w-full max-w-[960px] px-6 pb-20">
        <Card className="overflow-hidden">
          <div aria-hidden="true">
            {/* Search bar */}
            <div className="flex items-center gap-3 border-b border-line px-4 py-3">
              <span className="flex flex-1 items-center gap-2 rounded-full border border-line bg-surface-soft px-3.5 py-2 text-[13px] text-ink-mid [&_svg]:text-ink-faint">
                <SearchIcon />
                a red car driving on a highway
              </span>
            </div>

            <div className="grid gap-4 p-4 sm:grid-cols-[1.35fr_1fr]">
              {/* Player */}
              <div>
                <div className="grid aspect-video place-items-center rounded-lg bg-surface-sunk">
                  <span className="grid size-12 place-items-center rounded-full bg-panel text-brand [&_svg]:size-5">
                    <PlayIcon />
                  </span>
                </div>
                <div className="relative mt-3 h-1 overflow-hidden rounded-full bg-surface-sunk">
                  <i className="absolute inset-y-0 left-0 w-[34%] rounded-full bg-brand" />
                </div>
              </div>

              {/* Results */}
              <div>
                <p className="mb-2 text-[11px] font-medium tracking-[0.06em] text-ink-faint uppercase">
                  Matching clips
                </p>
                <div className="flex flex-col gap-1.5">
                  {PREVIEW_ROWS.map((row) => (
                    <div
                      key={row.time}
                      className={
                        row.top
                          ? 'flex items-center gap-2.5 rounded-lg bg-brand-wash p-2'
                          : 'flex items-center gap-2.5 rounded-lg p-2'
                      }
                    >
                      <span className="size-9 shrink-0 rounded-md bg-surface-sunk" />
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-[12.5px] text-ink">
                          {row.label}
                        </p>
                        <span className="font-mono text-[11px] text-ink-faint">
                          {row.time}
                        </span>
                      </div>
                      <span className="shrink-0 text-[12px] font-medium text-ink-mid">
                        {row.score}%
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>
        </Card>
      </section>

      {/* ── How it works ───────────────────────────────────── */}
      <section id="how" className="mx-auto w-full max-w-[1080px] px-6 pb-20">
        <SectionHead title="Three steps from upload to answer">
          The pipeline is deliberately small: extract frames, embed them,
          compare your prompt against them.
        </SectionHead>

        <div className="mt-10 grid gap-3 md:grid-cols-3">
          {STEPS.map((step, index) => (
            <Card key={step.title} className="p-5">
              <span className="grid size-7 place-items-center rounded-full bg-brand-wash text-[12.5px] font-semibold text-brand">
                {index + 1}
              </span>
              <h3 className="mt-3.5 text-[15px] font-semibold text-ink">
                {step.title}
              </h3>
              <p className="mt-1.5 text-[13.5px] leading-relaxed text-ink-dim">
                {step.body}
              </p>
            </Card>
          ))}
        </div>
      </section>

      {/* ── Features ───────────────────────────────────────── */}
      <section id="features" className="mx-auto w-full max-w-[1080px] px-6 pb-20">
        <SectionHead title="Built for people who live in footage">
          Editors, researchers and support teams who need one shot out of hours
          of material.
        </SectionHead>

        <BentoGrid className="mt-10">
          {FEATURES.map((feature) => {
            const Icon = feature.icon
            return (
              <BentoCard
                key={feature.title}
                title={feature.title}
                body={feature.body}
                span={feature.span}
                icon={<Icon />}
              />
            )
          })}
        </BentoGrid>
      </section>

      {/* ── Closing CTA ────────────────────────────────────── */}
      <section id="pricing" className="mx-auto w-full max-w-[1080px] px-6 pb-24">
        <Card className="px-6 py-12 text-center sm:px-14">
          <h2 className="mx-auto max-w-[26ch] text-[clamp(1.4rem,3vw,2rem)] leading-tight font-semibold tracking-[-0.025em] text-ink">
            Put your first video to the test
          </h2>
          <p className="mx-auto mt-3 max-w-[52ch] text-[15px] leading-relaxed text-ink-dim">
            Upload something you know well, describe a scene from memory, and see
            how close it lands.
          </p>
          <div className="mt-7 flex justify-center">
            <ButtonLink as={Link} to={primaryHref} size="lg">
              {primaryLabel}
            </ButtonLink>
          </div>
        </Card>
      </section>
    </MarketingShell>
  )
}
