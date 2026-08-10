import type { Video } from '../data/videos'
import { avatarUrl, formatViews, thumbUrl, timeAgo } from '../data/videos'

interface VideoCardProps {
  video: Video
}

export default function VideoCard({ video }: VideoCardProps) {
  return (
    <article className="video-card">
      <button
        type="button"
        className="video-thumb"
        aria-label={`Play: ${video.title}`}
        title={video.title}
      >
        <img src={thumbUrl(video.seed)} alt="" loading="lazy" />
        <span className="duration">{video.duration}</span>
        <span className="play-overlay">
          <span className="play-circle">
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <path d="M8 5.14v13.72L19 12 8 5.14z" />
            </svg>
          </span>
        </span>
      </button>

      <div className="video-meta">
        <img
          className="avatar"
          src={avatarUrl(video.seed)}
          alt=""
          loading="lazy"
        />
        <div className="video-info">
          <h3 className="video-title">{video.title}</h3>
          <p className="video-channel">{video.channel}</p>
          <p className="video-stats">
            {formatViews(video.views)} · {timeAgo(video.publishedDaysAgo)}
          </p>
        </div>
      </div>
    </article>
  )
}
