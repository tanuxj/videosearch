import { useState } from 'react'
import { useNavigate } from '../lib/router'
import { useAuth } from '../lib/auth'
import { removeVideo, sourceFor, useVideos } from '../lib/store'
import { API_ENABLED } from '../lib/http'
import { AppShell } from '../components/Shell'
import { UploadDialog } from '../components/UploadDialog'
import { ShareButton } from '../components/ShareButton'
import { TranscriptPanel } from '../components/TranscriptPanel'
import { Button } from '../components/ui/Button'
import {
  Chip,
  EmptyState,
  Panel,
} from '../components/ui/Data'
import {
  MicIcon,
  PlayIcon,
  RecordIcon,
  SearchIcon,
  TrashIcon,
  UploadIcon,
  WaveIcon,
} from '../components/Icons'
import {
  compactNumber,
  fileSize,
  humanDuration,
  relativeTime,
} from '../lib/format'

/**
 * The library's Recordings page — every save from the Record tab, screen
 * captures and audio-only notes together. Audio recordings have no frames to
 * scene-search, so they don't belong in the Search picker; this is where they
 * live, with their transcripts readable right on the row.
 */

export default function Recordings() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const videos = useVideos(user?.id)
  const [uploadOpen, setUploadOpen] = useState(false)

  const recordings = videos.filter((video) => video.source === 'recording')

  return (
    <AppShell
      title="Recordings"
      subtitle="Everything you've recorded — screen captures and voice notes."
      actions={
        <Button
          size="sm"
          onClick={() => navigate('/record')}
          className="[&_svg]:size-4"
        >
          <RecordIcon />
          Record new
        </Button>
      }
    >
      <div className="flex flex-col gap-5">
        <Panel
          title="Your recordings"
          subtitle={
            recordings.length > 0
              ? 'Audio notes stay here — only screen captures are searchable by scene.'
              : undefined
          }
          actions={
            <Button
              variant="secondary"
              size="sm"
              onClick={() => setUploadOpen(true)}
              className="[&_svg]:size-4"
            >
              <UploadIcon />
              Add videos
            </Button>
          }
        >
          {recordings.length === 0 ? (
            <EmptyState
              icon={<RecordIcon />}
              title="No recordings yet"
              body="Record your screen or mic from the Record tab and the finished file will land here, ready to play back and read."
              action={
                <Button onClick={() => navigate('/record')} className="[&_svg]:size-4">
                  <RecordIcon />
                  Record something
                </Button>
              }
            />
          ) : (
            <ul className="divide-y divide-[var(--border)]">
              {recordings.map((video) => (
                <li key={video.id} className="transition-colors hover:bg-surface-soft">
                  <div className="group flex flex-wrap items-center gap-3 px-4 py-3 sm:px-5">
                    <span className="grid size-14 shrink-0 place-items-center overflow-hidden rounded-xl border border-line bg-surface-sunk text-brand [&_svg]:size-5">
                      {video.poster ? (
                        <img
                          src={video.poster}
                          alt=""
                          className="size-full object-cover"
                        />
                      ) : video.hasVideo === false ? (
                        <WaveIcon />
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

                      <Chip tone="brand" icon={<MicIcon />}>
                        Recording
                      </Chip>

                      {/* Audio-only recordings have no frames to scene-search. */}
                      {video.hasVideo === false ? (
                        <Chip tone="neutral" icon={<WaveIcon />}>
                          Audio
                        </Chip>
                      ) : (
                        <Chip tone="neutral" icon={<PlayIcon />}>
                          Video
                        </Chip>
                      )}

                      {!API_ENABLED && !sourceFor(video.id) && (
                        <Chip title="The file handle was lost when the tab reloaded — re-attach it on the search page to play clips back.">
                          Playback offline
                        </Chip>
                      )}

                      {video.hasVideo !== false && (
                        <Button
                          variant="secondary"
                          size="sm"
                          onClick={() => navigate(`/search?v=${video.id}`)}
                          className="[&_svg]:size-4"
                        >
                          <SearchIcon />
                          Search
                        </Button>
                      )}

                      {API_ENABLED && <ShareButton videoId={video.id} />}

                      <Button
                        variant="ghost"
                        size="sm"
                        aria-label={`Delete ${video.name}`}
                        className="px-2 hover:bg-danger-wash hover:text-danger [&_svg]:size-4"
                        onClick={() => {
                          if (!user) return
                          if (confirm(`Delete “${video.name}”?`))
                            void removeVideo(user.id, video.id)
                        }}
                      >
                        <TrashIcon />
                      </Button>
                    </div>
                  </div>
                  {/* Audio recordings have no search page to read their
                      transcript on — it belongs right here on the row. */}
                  {video.hasVideo === false && (
                    <div className="px-4 pb-3 sm:px-5">
                      <TranscriptPanel video={video} />
                    </div>
                  )}
                </li>
              ))}
            </ul>
          )}
        </Panel>
      </div>

      <UploadDialog
        open={uploadOpen}
        onClose={() => setUploadOpen(false)}
        onReady={(video) => navigate(`/search?v=${video.id}`)}
      />
    </AppShell>
  )
}
