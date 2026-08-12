import { useState } from 'react'
import { useNavigate } from '../lib/router'
import { useAuth } from '../lib/auth'
import { removeVideo, sourceFor, useVideos } from '../lib/store'
import { API_ENABLED } from '../lib/http'
import { AppShell } from '../components/Shell'
import { UploadDialog } from '../components/UploadDialog'
import { Button } from '../components/ui/Button'
import {
  Chip,
  EmptyState,
  Panel,
  StatRow,
  StatTile,
} from '../components/ui/Data'
import { Reveal } from '../components/ui/Motion'
import {
  ClockIcon,
  FilmIcon,
  LayersIcon,
  PlayIcon,
  SearchIcon,
  TrashIcon,
  UploadIcon,
} from '../components/Icons'
import {
  compactNumber,
  fileSize,
  humanDuration,
  relativeTime,
} from '../lib/format'

export default function Dashboard() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const videos = useVideos(user?.id)
  const [uploadOpen, setUploadOpen] = useState(false)

  const totalFrames = videos.reduce((sum, video) => sum + video.frames, 0)
  const totalSeconds = videos.reduce((sum, video) => sum + video.duration, 0)
  const totalBytes = videos.reduce((sum, video) => sum + video.sizeBytes, 0)
  const ready = videos.filter((video) => video.status === 'ready').length

  const firstName = user?.name.split(' ')[0] ?? 'there'

  return (
    <AppShell
      title={`Welcome back, ${firstName}`}
      subtitle="Everything you've indexed, ready to search."
      actions={
        <>
          <Button
            variant="secondary"
            size="sm"
            onClick={() => setUploadOpen(true)}
            className="[&_svg]:size-4"
          >
            <UploadIcon />
            Add video
          </Button>
          <Button
            size="sm"
            onClick={() => navigate('/search')}
            className="[&_svg]:size-4"
          >
            <SearchIcon />
            Find a scene
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-5">
        <Reveal y={10}>
          <StatRow>
            <StatTile
              label="Videos"
              value={String(videos.length)}
              meta={`${ready} ready to search`}
              icon={<FilmIcon />}
            />
            <StatTile
              label="Frames indexed"
              value={compactNumber(totalFrames)}
              meta="1 frame per second"
              icon={<LayersIcon />}
            />
            <StatTile
              label="Footage"
              value={humanDuration(totalSeconds)}
              meta="Searchable end to end"
              icon={<ClockIcon />}
            />
            <StatTile
              label="Storage"
              value={fileSize(totalBytes)}
              meta="Across your workspace"
              icon={<SearchIcon />}
            />
          </StatRow>
        </Reveal>

        <Reveal y={10} delay={0.06}>
          <Panel
            title="Your videos"
            subtitle="Pick one to search, or add something new."
            actions={
              <Button
                variant="secondary"
                size="sm"
                onClick={() => setUploadOpen(true)}
                className="[&_svg]:size-4"
              >
                <UploadIcon />
                Add video
              </Button>
            }
          >
            {videos.length === 0 ? (
              <EmptyState
                icon={<UploadIcon />}
                title="No videos yet"
                body="Add your first video and we’ll index every frame so you can search it by description."
                action={
                  <Button
                    onClick={() => setUploadOpen(true)}
                    className="[&_svg]:size-4"
                  >
                    <UploadIcon />
                    Add a video
                  </Button>
                }
              />
            ) : (
              <ul className="divide-y divide-[var(--border)]">
                {videos.map((video) => (
                  <li
                    key={video.id}
                    className="group flex flex-wrap items-center gap-3 px-4 py-3 transition-colors hover:bg-surface-soft sm:px-5"
                  >
                    <span className="grid size-14 shrink-0 place-items-center overflow-hidden rounded-xl border border-line bg-[linear-gradient(135deg,var(--bg-sunk),color-mix(in_oklab,var(--accent)_12%,var(--bg-sunk)))] text-brand [&_svg]:size-5">
                      {video.poster ? (
                        <img
                          src={video.poster}
                          alt=""
                          className="size-full object-cover"
                        />
                      ) : (
                        <PlayIcon />
                      )}
                    </span>

                    <div className="min-w-0 flex-1">
                      <b className="block truncate text-[14.5px] font-semibold text-ink">
                        {video.name}
                      </b>
                      <span className="mt-0.5 block truncate text-[12.5px] text-ink-faint">
                        {humanDuration(video.duration)} ·{' '}
                        {compactNumber(video.frames)} frames ·{' '}
                        {fileSize(video.sizeBytes)} ·{' '}
                        {relativeTime(video.createdAt)}
                      </span>
                    </div>

                    <div className="flex shrink-0 items-center gap-2">
                      {video.status === 'ready' ? (
                        <Chip tone="ok">Indexed</Chip>
                      ) : video.status === 'failed' ? (
                        <Chip
                          tone="danger"
                          title={video.error || 'Indexing failed on the server'}
                        >
                          Failed
                        </Chip>
                      ) : (
                        <Chip tone="warn" pulse>
                          Processing
                        </Chip>
                      )}

                      {!API_ENABLED && !sourceFor(video.id) && (
                        <Chip title="The file handle was lost when the tab reloaded — re-attach it on the search page to play clips back.">
                          Playback offline
                        </Chip>
                      )}

                      <Button
                        variant="secondary"
                        size="sm"
                        onClick={() => navigate(`/search?v=${video.id}`)}
                        className="[&_svg]:size-4"
                      >
                        <SearchIcon />
                        Search
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        aria-label={`Delete ${video.name}`}
                        className="px-2 hover:bg-danger-wash hover:text-danger [&_svg]:size-4"
                        onClick={() => {
                          if (!user) return
                          if (
                            confirm(`Delete “${video.name}” and its frame index?`)
                          )
                            void removeVideo(user.id, video.id)
                        }}
                      >
                        <TrashIcon />
                      </Button>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </Panel>
        </Reveal>
      </div>

      <UploadDialog
        open={uploadOpen}
        onClose={() => setUploadOpen(false)}
        onReady={(video) => navigate(`/search?v=${video.id}`)}
      />
    </AppShell>
  )
}
