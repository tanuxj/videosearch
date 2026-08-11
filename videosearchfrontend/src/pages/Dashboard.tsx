import { Link, useNavigate } from '../lib/router'
import { useAuth } from '../lib/auth'
import { removeVideo, sourceFor, useVideos } from '../lib/store'
import { AppShell } from '../components/Shell'
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

  const totalFrames = videos.reduce((sum, video) => sum + video.frames, 0)
  const totalSeconds = videos.reduce((sum, video) => sum + video.duration, 0)
  const ready = videos.filter((video) => video.status === 'ready').length

  const firstName = user?.name.split(' ')[0] ?? 'there'

  return (
    <AppShell
      title={`Welcome back, ${firstName}`}
      subtitle="Your indexed library at a glance."
      actions={
        <>
          <Link to="/search" className="btn btn-ghost btn-sm">
            <SearchIcon />
            Search clips
          </Link>
          <Link to="/upload" className="btn btn-primary btn-sm">
            <UploadIcon />
            Upload video
          </Link>
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
          <b>
            {fileSize(videos.reduce((sum, video) => sum + video.sizeBytes, 0))}
          </b>
          <span>across your workspace</span>
        </div>
      </div>

      <section className="panel">
        <div className="panel-head">
          <div>
            <h2>Your videos</h2>
            <p>Pick one to search, or upload something new.</p>
          </div>
          <div className="panel-head-actions">
            <Link to="/upload" className="btn btn-ghost btn-sm">
              <UploadIcon />
              Upload
            </Link>
          </div>
        </div>

        {videos.length === 0 ? (
          <div className="empty">
            <span className="empty-icon">
              <UploadIcon />
            </span>
            <h3>No videos yet</h3>
            <p>
              Upload your first video and we’ll index every frame so you can
              search it by description.
            </p>
            <Link to="/upload" className="btn btn-primary">
              <UploadIcon />
              Upload a video
            </Link>
          </div>
        ) : (
          videos.map((video) => {
            const attached = Boolean(sourceFor(video.id))
            return (
              <article key={video.id} className="lib-row">
                <span className="lib-thumb">
                  {video.poster ? (
                    <img src={video.poster} alt="" />
                  ) : (
                    <PlayIcon />
                  )}
                </span>
                <div className="lib-meta">
                  <b>{video.name}</b>
                  <span>
                    {humanDuration(video.duration)} ·{' '}
                    {compactNumber(video.frames)} frames ·{' '}
                    {fileSize(video.sizeBytes)} ·{' '}
                    {relativeTime(video.createdAt)}
                  </span>
                </div>
                <div className="lib-actions">
                  {video.status === 'ready' ? (
                    <span className="chip chip-ok">Indexed</span>
                  ) : (
                    <span className="chip chip-warn">Processing</span>
                  )}
                  {!attached && (
                    <span
                      className="chip"
                      title="The file handle was lost when the tab reloaded — re-upload to play it back."
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
            )
          })
        )}
      </section>
    </AppShell>
  )
}
