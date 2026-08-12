import { Link } from '../lib/router'
import { useAuth } from '../lib/auth'
import { APP_NAME, MarketingShell } from '../components/Shell'
import {
  AuroraBackground,
  DotPattern,
  GridPattern,
} from '../components/ui/Backgrounds'
import {
  BentoCard,
  BentoGrid,
  GlowBorderCard,
  SpotlightCard,
} from '../components/ui/Card'
import { Eyebrow, GradientText, TextGenerate } from '../components/ui/Text'
import { ButtonLink, GlowButton } from '../components/ui/Button'
import { Marquee, Reveal } from '../components/ui/Motion'
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

// Doubles as social proof and as a hint at what a good prompt looks like.
const EXAMPLE_PROMPTS = [
  'a red car driving on a highway',
  'two people shaking hands',
  'someone writing on a whiteboard',
  'aerial shot over a city at dusk',
  'a dog running on the beach',
  'close-up of hands typing',
  'a goal being scored',
  'slide with a bar chart',
]

export default function Home() {
  const { user } = useAuth()
  const primaryHref = user ? '/search' : '/signup'
  const primaryLabel = user ? 'Open your workspace' : 'Start free'

  return (
    <MarketingShell>
      {/* ── Hero ───────────────────────────────────────────── */}
      <AuroraBackground className="pt-16 pb-10 sm:pt-24">
        <GridPattern />
        <div className="mx-auto w-full max-w-[1120px] px-6 text-center">
          <Reveal y={8}>
            <Eyebrow>
              <span className="rounded-full bg-brand px-1.5 py-px text-[11px] font-semibold text-white">
                New
              </span>
              Visual search powered by CLIP
            </Eyebrow>
          </Reveal>

          <h1 className="mx-auto mt-6 max-w-[19ch] text-[clamp(2.4rem,6vw,4.25rem)] leading-[1.03] font-bold tracking-[-0.035em] text-ink">
            <TextGenerate text="Find the exact" />{' '}
            <GradientText>moment</GradientText>{' '}
            <TextGenerate text="in any video" delay={0.18} />
          </h1>

          <Reveal delay={0.35}>
            <p className="mx-auto mt-6 max-w-[62ch] text-[17px] leading-relaxed text-ink-mid">
              {APP_NAME} indexes every frame of your footage, so you can
              describe a scene in plain language and land on the second it
              happens — no scrubbing, no transcripts, no tagging.
            </p>

            <div className="mt-9 flex flex-wrap items-center justify-center gap-3">
              <GlowButton as={Link} to={primaryHref}>
                {primaryLabel}
              </GlowButton>
              <ButtonLink
                as="a"
                href="#how"
                variant="secondary"
                size="lg"
                className="backdrop-blur"
              >
                See how it works
              </ButtonLink>
            </div>

            <p className="mt-5 text-[13px] text-ink-faint">
              No credit card required · Your first 5 videos are on us
            </p>
          </Reveal>
        </div>

        {/* ── Product preview ──────────────────────────────── */}
        <Reveal delay={0.15} y={26} className="mt-14">
          <div className="mx-auto w-full max-w-[1000px] px-6">
            <GlowBorderCard
              className="shadow-[0_40px_90px_-40px_rgba(16,19,26,0.3)]"
              innerClassName="overflow-hidden"
            >
              <div aria-hidden="true">
                {/* Window chrome + omnibox */}
                <div className="flex items-center gap-3 border-b border-line bg-surface-soft px-4 py-3">
                  <span className="flex gap-1.5">
                    <i className="block size-2.5 rounded-full bg-[#ff5f57]" />
                    <i className="block size-2.5 rounded-full bg-[#febc2e]" />
                    <i className="block size-2.5 rounded-full bg-[#28c840]" />
                  </span>
                  <span className="flex flex-1 items-center gap-2 rounded-lg border border-line bg-panel px-3 py-1.5 text-[13px] text-ink-mid [&_svg]:size-4 [&_svg]:text-brand">
                    <SearchIcon />
                    a red car driving on a highway
                    <i className="ml-0.5 inline-block h-4 w-px animate-pulse bg-brand align-middle" />
                  </span>
                </div>

                <div className="grid gap-4 p-4 sm:grid-cols-[1.35fr_1fr]">
                  {/* Player */}
                  <div>
                    <div className="relative grid aspect-video place-items-center overflow-hidden rounded-xl border border-line bg-[linear-gradient(135deg,var(--bg-sunk),color-mix(in_oklab,var(--accent)_9%,var(--bg-soft)))]">
                      <DotPattern className="opacity-60" />
                      <span className="grid size-14 place-items-center rounded-full bg-panel/85 text-brand shadow-[0_8px_24px_-8px_rgba(16,19,26,0.35)] backdrop-blur [&_svg]:size-6">
                        <PlayIcon />
                      </span>
                    </div>
                    <div className="relative mt-3 h-1.5 overflow-hidden rounded-full bg-surface-sunk">
                      <i className="absolute inset-y-0 left-0 w-[34%] rounded-full bg-[linear-gradient(90deg,var(--accent),var(--accent-2))]" />
                      <b className="absolute top-1/2 left-[34%] size-3 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-white bg-brand shadow-[0_1px_4px_rgba(16,19,26,0.3)]" />
                    </div>
                  </div>

                  {/* Results */}
                  <div>
                    <p className="mb-2 text-[11.5px] font-semibold tracking-[0.07em] text-ink-faint uppercase">
                      Matching clips
                    </p>
                    <div className="flex flex-col gap-2">
                      {PREVIEW_ROWS.map((row) => (
                        <div
                          key={row.time}
                          className={
                            row.top
                              ? 'flex items-center gap-2.5 rounded-xl border border-brand-line bg-brand-wash p-2'
                              : 'flex items-center gap-2.5 rounded-xl border border-line bg-panel p-2'
                          }
                        >
                          <span className="size-9 shrink-0 rounded-lg bg-[linear-gradient(135deg,var(--bg-sunk),color-mix(in_oklab,var(--accent)_16%,var(--bg-sunk)))]" />
                          <div className="min-w-0 flex-1">
                            <p className="truncate text-[12.5px] font-medium text-ink">
                              {row.label}
                            </p>
                            <span className="font-mono text-[11px] text-ink-faint">
                              {row.time}
                            </span>
                          </div>
                          <span className="shrink-0 font-mono text-[11.5px] font-semibold text-brand">
                            {row.score}%
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              </div>
            </GlowBorderCard>
          </div>
        </Reveal>

        {/* ── Example prompts ──────────────────────────────── */}
        <div className="mt-14">
          <p className="text-center text-[12px] font-medium tracking-[0.09em] text-ink-faint uppercase">
            Prompts that work
          </p>
          <Marquee className="mt-4 py-1">
            {EXAMPLE_PROMPTS.map((prompt) => (
              <span
                key={prompt}
                className="flex items-center gap-2 rounded-full border border-line bg-panel px-4 py-2 text-[13px] whitespace-nowrap text-ink-mid shadow-[0_1px_2px_rgba(16,19,26,0.04)] [&_svg]:size-3.5 [&_svg]:text-brand"
              >
                <SearchIcon />
                {prompt}
              </span>
            ))}
          </Marquee>
        </div>
      </AuroraBackground>

      {/* ── How it works ───────────────────────────────────── */}
      <section id="how" className="mx-auto w-full max-w-[1120px] px-6 py-20">
        <Reveal className="mx-auto max-w-[54ch] text-center">
          <h2 className="text-[clamp(1.7rem,3.4vw,2.4rem)] leading-tight font-bold tracking-[-0.03em] text-ink">
            Three steps from upload to answer
          </h2>
          <p className="mt-3 text-[16px] leading-relaxed text-ink-mid">
            The pipeline is deliberately small: extract frames, embed them,
            compare your prompt against them.
          </p>
        </Reveal>

        <div className="mt-10 grid gap-4 md:grid-cols-3">
          {STEPS.map((step, index) => (
            <Reveal key={step.title} delay={index * 0.08}>
              <SpotlightCard className="h-full p-6">
                <span className="grid size-10 place-items-center rounded-xl bg-[linear-gradient(180deg,color-mix(in_oklab,var(--accent)_92%,white),var(--accent))] font-mono text-[15px] font-semibold text-white shadow-[0_8px_18px_-10px_color-mix(in_oklab,var(--accent)_70%,transparent)]">
                  {index + 1}
                </span>
                <h3 className="mt-4 text-[16.5px] font-semibold tracking-[-0.015em] text-ink">
                  {step.title}
                </h3>
                <p className="mt-2 text-[14px] leading-relaxed text-ink-dim">
                  {step.body}
                </p>
              </SpotlightCard>
            </Reveal>
          ))}
        </div>
      </section>

      {/* ── Features (bento) ───────────────────────────────── */}
      <section
        id="features"
        className="relative mx-auto w-full max-w-[1120px] px-6 pb-20"
      >
        <Reveal className="mx-auto max-w-[54ch] text-center">
          <h2 className="text-[clamp(1.7rem,3.4vw,2.4rem)] leading-tight font-bold tracking-[-0.03em] text-ink">
            Built for people who live in footage
          </h2>
          <p className="mt-3 text-[16px] leading-relaxed text-ink-mid">
            Editors, researchers and support teams who need one shot out of
            hours of material.
          </p>
        </Reveal>

        <Reveal delay={0.1} className="mt-10">
          <BentoGrid>
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
        </Reveal>
      </section>

      {/* ── Closing CTA ────────────────────────────────────── */}
      <section id="pricing" className="mx-auto w-full max-w-[1120px] px-6 pb-24">
        <Reveal>
          <GlowBorderCard innerClassName="relative overflow-hidden px-6 py-14 text-center sm:px-14">
            <div
              aria-hidden="true"
              className="pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_70%_120%_at_50%_0%,color-mix(in_oklab,var(--accent)_10%,transparent),transparent_70%)]"
            />
            <div className="relative">
              <h2 className="mx-auto max-w-[26ch] text-[clamp(1.6rem,3.2vw,2.3rem)] leading-tight font-bold tracking-[-0.03em] text-ink">
                Put your first video to the test
              </h2>
              <p className="mx-auto mt-3 max-w-[52ch] text-[16px] leading-relaxed text-ink-mid">
                Upload something you know well, describe a scene from memory,
                and see how close it lands.
              </p>
              <div className="mt-8 flex justify-center">
                <GlowButton as={Link} to={primaryHref}>
                  {primaryLabel}
                </GlowButton>
              </div>
            </div>
          </GlowBorderCard>
        </Reveal>
      </section>
    </MarketingShell>
  )
}
