import { Link } from '../lib/router'
import { useAuth } from '../lib/auth'
import { APP_NAME, MarketingShell } from '../components/Shell'
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
  },
  {
    icon: LayersIcon,
    title: 'Every frame indexed',
    body: 'Frames are sampled through the upload and embedded with CLIP, so the whole timeline is searchable — not just the parts you labelled.',
  },
  {
    icon: BoltIcon,
    title: 'Jump straight to the moment',
    body: 'Results come back as clips with timestamps. Click one and the player seeks to that exact second.',
  },
  {
    icon: ClockIcon,
    title: 'Minutes, not afternoons',
    body: 'A ten-minute video indexes in the time it takes to make coffee, and stays searchable forever after.',
  },
  {
    icon: SearchIcon,
    title: 'Visual search, no transcript',
    body: 'Matching runs on what the camera saw, so silent footage, screen recordings and B-roll all work the same.',
  },
  {
    icon: ShieldIcon,
    title: 'Your library, your rules',
    body: 'Videos stay in your workspace. Delete one and its frame vectors go with it.',
  },
]

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
  { time: '02:14', score: '94%', label: 'Wide shot, red car entering frame', top: true },
  { time: '05:38', score: '87%', label: 'Highway overpass, traffic moving' },
  { time: '11:02', score: '71%', label: 'Car park exit, similar palette' },
]

export default function Home() {
  const { user } = useAuth()
  const primaryHref = user ? '/search' : '/signup'
  const primaryLabel = user ? 'Open your workspace' : 'Start free'

  return (
    <MarketingShell>
      <section className="wrap hero">
        <span className="eyebrow">
          <b>New</b> Visual search powered by CLIP
        </span>
        <h1>
          Find the exact <span className="gradient-text">moment</span> in any
          video
        </h1>
        <p className="hero-sub">
          {APP_NAME} indexes every frame of your footage, so you can describe a
          scene in plain language and land on the second it happens — no
          scrubbing, no transcripts, no tagging.
        </p>
        <div className="hero-cta">
          <Link to={primaryHref} className="btn btn-primary btn-lg">
            {primaryLabel}
          </Link>
          <a href="#how" className="btn btn-ghost btn-lg">
            See how it works
          </a>
        </div>
        <p className="hero-note">
          No credit card required · Your first 5 videos are on us
        </p>

        <div className="preview" aria-hidden="true">
          <div className="preview-bar">
            <span className="preview-dots">
              <i />
              <i />
              <i />
            </span>
            <span className="preview-omni">
              <SearchIcon />
              a red car driving on a highway
            </span>
          </div>
          <div className="preview-body">
            <div className="preview-stage">
              <div className="preview-screen">
                <span className="preview-play">
                  <PlayIcon />
                </span>
              </div>
              <div className="preview-scrub">
                <i />
                <b />
              </div>
            </div>
            <div className="preview-list">
              <p className="preview-list-title">Matching clips</p>
              {PREVIEW_ROWS.map((row) => (
                <div
                  key={row.time}
                  className={`preview-row${row.top ? ' is-top' : ''}`}
                >
                  <span className="preview-thumb" />
                  <div>
                    <p>{row.label}</p>
                    <span>{row.time}</span>
                  </div>
                  <span className="preview-score">{row.score}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>

      <section className="wrap section" id="how">
        <div className="section-head">
          <h2>Three steps from upload to answer</h2>
          <p>
            The pipeline is deliberately small: extract frames, embed them,
            compare your prompt against them.
          </p>
        </div>
        <div className="steps">
          {STEPS.map((step, index) => (
            <article key={step.title} className="step">
              <span className="step-num">{index + 1}</span>
              <h3>{step.title}</h3>
              <p>{step.body}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="wrap section" id="features">
        <div className="section-head">
          <h2>Built for people who live in footage</h2>
          <p>
            Editors, researchers and support teams who need one shot out of
            hours of material.
          </p>
        </div>
        <div className="grid-3">
          {FEATURES.map((feature) => {
            const Icon = feature.icon
            return (
              <article key={feature.title} className="feature">
                <span className="feature-icon">
                  <Icon />
                </span>
                <h3>{feature.title}</h3>
                <p>{feature.body}</p>
              </article>
            )
          })}
        </div>
      </section>

      <section className="wrap" id="pricing">
        <div className="cta-band">
          <h2>Put your first video to the test</h2>
          <p>
            Upload something you know well, describe a scene from memory, and
            see how close it lands.
          </p>
          <Link to={primaryHref} className="btn btn-primary btn-lg">
            {primaryLabel}
          </Link>
        </div>
      </section>
    </MarketingShell>
  )
}
