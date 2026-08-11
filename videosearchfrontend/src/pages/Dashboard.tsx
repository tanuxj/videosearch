import { useState } from 'react'
import { useNavigate } from '../lib/router'
import { useAuth } from '../lib/auth'
import { removeVideo, sourceFor, useVideos } from '../lib/store'
import { AppShell } from '../components/Shell'
import { UploadDialog } from '../components/UploadDialog'
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
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            onClick={() => setUploadOpen(true)}
          >
            <UploadIcon />
            Add video
          </button>
          <button
            type="button"
            className="btn btn-primary btn-sm"
            onClick={() => navigate('/search')}
          >
            <SearchIcon />
            Find a scene
          </button>
        </>
      }
    >
      <div className="stat-grid">
        <div className="stat">
          <span className="stat-top">
            <FilmIcon />
            Videos
          </span>
          <b>{videos.length}</b>
          <span>{ready} ready to search</span>
        </div>
        <div className="stat">
          <span className="stat-top">
            <LayersIcon />
            Frames indexed
          </span>
          <b>{compactNumber(totalFrames)}</b>
          <span>1 frame per second</span>
        </div>
        <div className="stat">
          <span className="stat-top">
            <ClockIcon />
            Footage
          </span>
          <b>{humanDuration(totalSeconds)}</b>
          <span>searchable end to end</span>
        </div>
        <div className="stat">
          <span className="stat-top">
            <SearchIcon />
            Storage
          </span>
          <b>{fileSize(totalBytes)}</b>
          <span>across your workspace</span>
        </div>
      </div>

      <section className="panel">
        <div className="panel-head">
          <div>
            <h2>Your videos</h2>
            <p>Pick one to search, or add something new.</p>
          </div>
          <div className="panel-head-actions">
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              onClick={() => setUploadOpen(true)}
            >
              <UploadIcon />
              Add video
            </button>
          </div>
        </div>

        {videos.length === 0 ? (
          <div className="empty">
            <span className="empty-icon">
              <UploadIcon />
            </span>
            <h3>No videos yet</h3>
            <p>
              Add your first video and we’ll index every frame so you can search
              it by description.
            </p>
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => setUploadOpen(true)}
            >
              <UploadIcon />
              Add a video
            </button>
          </div>
        ) : (
          videos.map((video) => (
            <article key={video.id} className="lib-row">
              <span className="lib-thumb">
                {video.poster ? <img src={video.poster} alt="" /> : <PlayIcon />}
              </span>
              <div className="lib-meta">
                <b>{video.name}</b>
                <span>
                  {humanDuration(video.duration)} ·{' '}
                  {compactNumber(video.frames)} frames ·{' '}
                  {fileSize(video.sizeBytes)} · {relativeTime(video.createdAt)}
                </span>
              </div>
              <div className="lib-actions">
                {video.status === 'ready' ? (
                  <span className="chip chip-ok">Indexed</span>
                ) : (
                  <span className="chip chip-warn">Processing</span>
                )}
                {!sourceFor(video.id) && (
                  <span
                    className="chip"
                    title="The file handle was lost when the tab reloaded — re-attach it on the search page to play clips back."
                  >
                    Playback offline
                  </span>
                )}
                <button
                  type="button"
                  className="btn btn-ghost btn-sm"
                  onClick={() => navigate(`/search?v=${video.id}`)}
                >
                  <SearchIcon />
                  Search
                </button>
                <button
                  type="button"
                  className="btn btn-quiet btn-sm"
                  aria-label={`Delete ${video.name}`}
                  onClick={() => {
                    if (!user) return
                    if (confirm(`Delete “${video.name}” and its frame index?`))
                      removeVideo(user.id, video.id)
                  }}
                >
                  <TrashIcon />
                </button>
              </div>
            </article>
          ))
        )}
      </section>

      <UploadDialog
        open={uploadOpen}
        onClose={() => setUploadOpen(false)}
        onReady={(video) => navigate(`/search?v=${video.id}`)}
      />
    </AppShell>
  )
}
