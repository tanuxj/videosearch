import type { Video } from '../data/videos'
import VideoCard from './VideoCard'

interface VideoGridProps {
  videos: Video[]
  loading: boolean
  query: string
  onReset: () => void
}

export default function VideoGrid({
  videos,
  loading,
  query,
  onReset,
}: VideoGridProps) {
  if (loading) {
    return (
      <div className="video-grid" aria-label="Loading videos" aria-busy="true">
        {Array.from({ length: 8 }).map((_, i) => (
          <div className="video-card skeleton-card" key={i}>
            <div className="skeleton thumb" />
            <div className="video-meta">
              <div className="skeleton circle" />
              <div className="skeleton lines">
                <span className="skeleton line" />
                <span className="skeleton line short" />
              </div>
            </div>
          </div>
        ))}
      </div>
    )
  }

  if (videos.length === 0) {
    return (
      <div className="empty-state">
        <div className="empty-icon">
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path d="M8 5.14v13.72L19 12 8 5.14z" />
          </svg>
        </div>
        <h2>No videos found</h2>
        <p>
          We couldn&rsquo;t find anything for &ldquo;{query}&rdquo;. Try a
          different search term or browse a category.
        </p>
        <button type="button" className="chip chip-primary" onClick={onReset}>
          Clear search
        </button>
      </div>
    )
  }

  return (
    <div className="video-grid">
      {videos.map((video) => (
        <VideoCard key={video.id} video={video} />
      ))}
    </div>
  )
}
