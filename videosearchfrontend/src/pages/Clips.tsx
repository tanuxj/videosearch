import { useEffect, useState } from 'react'
import { useNavigate } from '../lib/router'
import { useAuth } from '../lib/auth'
import {
  captureFrames,
  clearHistory,
  removeHistoryRecord,
  sourceFor,
  streamSourceFor,
  useHistory,
  useVideos,
} from '../lib/store'
import type { Clip } from '../lib/api'
import { API_ENABLED } from '../lib/http'
import { AppShell } from '../components/Shell'
import { ClipLightbox } from '../components/ClipLightbox'
import { Button } from '../components/ui/Button'
import { Card } from '../components/ui/Card'
import { EmptyState, Panel } from '../components/ui/Data'
import {
  ArrowRightIcon,
  ChevronIcon,
  FilmIcon,
  PlayIcon,
  TrashIcon,
} from '../components/Icons'
import { relativeTime, timecode } from '../lib/format'

// Stable empty-clips reference so the thumbnail effect's deps don't churn
// when no search is expanded.
const EMPTY_CLIPS: Clip[] = []

/**
 * Clips — every prompt the user ran, the video it ran against, and the
 * clips that came back. Clips are stored as a snapshot at search time,
 * so replaying one shows exactly what was found. Expanding a search loads
 * its playback source and captures real thumbnails from the video.
 */
export default function Clips() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const videos = useVideos(user?.id)
  const records = useHistory(user?.id)

  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [openClip, setOpenClip] = useState<Clip | null>(null)
  /** Object URL for the expanded search's video — resolves lazily. */
  const [src, setSrc] = useState('')
  const [thumbs, setThumbs] = useState<Map<number, string>>(new Map())

  const expanded = records.find((record) => record.id === expandedId) ?? null
  const expandedVideo = expanded
    ? (videos.find((video) => video.id === expanded.videoId) ?? null)
    : null
  // Primitive views of the expanded search, so the effects below can key on
  // stable values instead of recreated objects.
  const expandedVideoId = expanded?.videoId ?? null
  const expandedVideoStatus = expandedVideo?.status ?? null
  const expandedClips = expanded?.clips ?? EMPTY_CLIPS

  // Switching the expanded search resets playback + thumbnails.
  useEffect(() => {
    setSrc('')
    setThumbs(new Map())
    setOpenClip(null)
  }, [expandedId])

  // Playback source: a local file attached this session (demo mode) or the
  // server's stream once the video is ready.
  useEffect(() => {
    if (!expandedVideoId) {
      setSrc('')
      return
    }
    const attached = sourceFor(expandedVideoId)
    if (attached) {
      setSrc(attached)
      return
    }
    if (API_ENABLED && expandedVideoStatus === 'ready') {
      let cancelled = false
      streamSourceFor(expandedVideoId)
        .then((streamUrl) => {
          if (!cancelled) setSrc(streamUrl)
        })
        .catch(() => {
          /* playback stays unavailable — clips still show timecodes */
        })
      return () => {
        cancelled = true
      }
    }
    setSrc('')
  }, [expandedVideoId, expandedVideoStatus])

  // Real thumbnails for the expanded search's clips, captured from whichever
  // playback source is live. Cancels stale work when the source changes.
  useEffect(() => {
    if (expandedClips.length === 0 || !src) return
    let cancelled = false
    void captureFrames(
      src,
      expandedClips.map((clip) => clip.frame),
    ).then((frames) => {
      if (!cancelled) setThumbs(frames)
    })
    return () => {
      cancelled = true
    }
  }, [expandedClips, src])

  function onClearAll() {
    if (!user) return
    if (confirm('Clear all clips?')) void clearHistory(user.id)
  }

  return (
    <AppShell
      title="Clips"
      subtitle="Every search you've run, and the clips each one found."
      actions={
        records.length > 0 ? (
          <Button
            variant="ghost"
            size="sm"
            onClick={onClearAll}
            className="[&_svg]:size-4"
          >
            <TrashIcon />
            Clear all
          </Button>
        ) : undefined
      }
    >
      <div className="mx-auto w-full max-w-[900px]">
        {records.length === 0 ? (
          <Panel>
            <EmptyState
              icon={<FilmIcon />}
              title="No clips yet"
              body="Run a search on any indexed video and it will show up here, with the clips it found — ready to replay or re-run."
              action={
                <Button
                  onClick={() => navigate('/search')}
                  className="[&_svg]:size-4"
                >
                  <ArrowRightIcon />
                  Find a scene
                </Button>
              }
            />
          </Panel>
        ) : (
          <ul className="flex flex-col gap-3">
            {records.map((record) => {
              const video = videos.find((item) => item.id === record.videoId)
              const isOpen = record.id === expandedId
              const topScore = Math.max(
                ...record.clips.map((clip) => clip.score),
                0.001,
              )
              return (
                <li key={record.id}>
                  <Card className={isOpen ? 'ring-1 ring-brand-line' : undefined}>
                    <div className="flex items-start gap-3 p-4">
                      <button
                        type="button"
                        onClick={() =>
                          setExpandedId(isOpen ? null : record.id)
                        }
                        className="min-w-0 flex-1 cursor-pointer text-left"
                      >
                        <span className="flex items-start gap-2.5">
                          <span className="mt-0.5 grid size-7 shrink-0 place-items-center rounded-lg border border-brand-line bg-brand-wash text-brand [&_svg]:size-3.5">
                            <FilmIcon />
                          </span>
                          <span className="min-w-0">
                            <b className="block truncate text-[14.5px] font-semibold text-ink">
                              “{record.prompt}”
                            </b>
                            <span className="mt-1 block truncate text-[12.5px] text-ink-faint">
                              {video?.name ?? 'Video no longer in your library'} ·{' '}
                              {record.clips.length}{' '}
                              {record.clips.length === 1 ? 'match' : 'matches'} ·{' '}
                              {relativeTime(record.createdAt)}
                              {record.expanded && ' · query expanded'}
                            </span>
                          </span>
                        </span>
                      </button>

                      <div className="flex shrink-0 items-center gap-1">
                        <Button
                          variant="secondary"
                          size="sm"
                          onClick={() =>
                            navigate(
                              `/search?v=${record.videoId}&q=${encodeURIComponent(record.prompt)}`,
                            )
                          }
                          title="Re-run this search on the search page"
                          className="[&_svg]:size-4"
                        >
                          <ArrowRightIcon />
                          Re-run
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          aria-label={`Delete search “${record.prompt}”`}
                          className="px-2 hover:bg-danger-wash hover:text-danger [&_svg]:size-4"
                          onClick={() => {
                            if (user) void removeHistoryRecord(user.id, record.id)
                          }}
                        >
                          <TrashIcon />
                        </Button>
                        <button
                          type="button"
                          aria-label={isOpen ? 'Collapse clips' : 'Show clips'}
                          onClick={() =>
                            setExpandedId(isOpen ? null : record.id)
                          }
                          className="grid size-8 place-items-center rounded-lg text-ink-dim transition-colors hover:bg-surface-sunk hover:text-ink [&_svg]:size-4"
                        >
                          <ChevronIcon
                            className={`transition-transform ${isOpen ? 'rotate-180' : ''}`}
                          />
                        </button>
                      </div>
                    </div>

                    {isOpen && (
                      <div className="border-t border-line p-4">
                        {record.clips.length === 0 ? (
                          <p className="text-[13px] text-ink-dim">
                            This search found no matching scene — the video had
                            nothing close enough to the description.
                          </p>
                        ) : (
                          <div className="grid grid-cols-[repeat(auto-fill,minmax(210px,1fr))] gap-4">
                            {record.clips.map((clip, index) => {
                              const thumb = thumbs.get(clip.frame)
                              const percent = Math.round(
                                (clip.score / topScore) * 100,
                              )
                              return (
                                <Card
                                  key={clip.id}
                                  className="group h-full"
                                  interactive
                                >
                                  <button
                                    type="button"
                                    onClick={() => setOpenClip(clip)}
                                    className="block w-full cursor-pointer p-2.5 text-left"
                                  >
                                    <span className="relative block aspect-video overflow-hidden rounded-xl border border-line bg-surface-sunk">
                                      {thumb ? (
                                        <img
                                          src={thumb}
                                          alt=""
                                          className="size-full object-cover"
                                        />
                                      ) : (
                                        <span className="grid size-full place-items-center bg-surface-sunk text-brand [&_svg]:size-6">
                                          <PlayIcon />
                                        </span>
                                      )}

                                      <span className="absolute top-2 left-2 rounded-md bg-ink/70 px-1.5 py-0.5 font-mono text-[11px] font-medium text-white">
                                        #{index + 1}
                                      </span>

                                      <span className="absolute inset-0 grid place-items-center bg-ink/0 opacity-0 transition-[opacity,background-color] duration-200 group-hover:bg-ink/20 group-hover:opacity-100">
                                        <i className="grid size-11 place-items-center rounded-full bg-panel text-brand [&_svg]:size-5">
                                          <PlayIcon />
                                        </i>
                                      </span>

                                      <span className="absolute right-2 bottom-2 rounded-md bg-ink/70 px-1.5 py-0.5 font-mono text-[11px] text-white">
                                        {timecode(clip.start)} – {timecode(clip.end)}
                                      </span>
                                    </span>

                                    <span className="mt-2.5 block px-0.5">
                                      <span className="block truncate text-[13.5px] font-medium text-ink">
                                        Frame at {timecode(clip.frame)}
                                      </span>
                                      <span className="mt-2 flex items-center gap-2">
                                        <span className="relative block h-1.5 flex-1 overflow-hidden rounded-full bg-brand-wash">
                                          <i
                                            className="absolute inset-y-0 left-0 rounded-full bg-brand"
                                            style={{ width: `${percent}%` }}
                                          />
                                        </span>
                                        <span className="shrink-0 text-[12px] font-semibold text-ink-mid">
                                          {percent}%
                                        </span>
                                      </span>
                                    </span>
                                  </button>
                                </Card>
                              )
                            })}
                          </div>
                        )}

                        {src ? null : (
                          <p className="mt-4 text-[12.5px] text-ink-faint">
                            {expandedVideo?.status === 'ready' && API_ENABLED
                              ? 'Loading playback…'
                              : 'Playback for this video isn’t attached to this tab — clips still show their timecodes.'}
                          </p>
                        )}
                      </div>
                    )}
                  </Card>
                </li>
              )
            })}
          </ul>
        )}
      </div>

      <ClipLightbox
        clip={openClip}
        clips={expanded?.clips ?? []}
        video={expandedVideo}
        src={src}
        prompt={expanded?.prompt ?? ''}
        onSelect={setOpenClip}
        onClose={() => setOpenClip(null)}
      />
    </AppShell>
  )
}
