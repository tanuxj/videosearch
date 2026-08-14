import { useEffect, useState } from 'react'
import {
  captureFrames,
  listVideoClips,
  removeVideoClip,
  sourceFor,
  streamSourceFor,
} from '../lib/store'
import type { SavedClip, VideoRecord } from '../lib/store'
import { API_ENABLED } from '../lib/http'
import { ClipLightbox } from './ClipLightbox'
import { PlayIcon, SparkIcon, TrashIcon } from './Icons'
import { timecode } from '../lib/format'

// Stable empty reference so the thumbnail effect's deps don't churn before
// the first fetch resolves.
const EMPTY_CLIPS: SavedClip[] = []

/**
 * A video's auto-extracted scenes — the clips a URL import saved when it was
 * given a prompt. Renders nothing for uploaded videos (or ones still
 * indexing). Loading a video's clips pulls its playback source lazily, so a
 * library with many videos only streams the ones that actually have clips.
 */
export function SavedClips({ video }: { video: VideoRecord }) {
  const [clips, setClips] = useState<SavedClip[] | null>(null)
  const [src, setSrc] = useState('')
  const [thumbs, setThumbs] = useState<Map<number, string>>(new Map())
  const [openClip, setOpenClip] = useState<SavedClip | null>(null)

  const ready = video.status === 'ready' && API_ENABLED
  const clipCount = clips?.length ?? 0

  // Fetch the video's saved clips once it's ready (nothing before that).
  useEffect(() => {
    let cancelled = false
    if (!ready) {
      setClips(null)
      return
    }
    void listVideoClips(video.id).then((items) => {
      if (!cancelled) setClips(items)
    })
    return () => {
      cancelled = true
    }
  }, [ready, video.id])

  // Playback source, loaded only when there are clips to show.
  useEffect(() => {
    if (clipCount === 0) return
    const attached = sourceFor(video.id)
    if (attached) {
      setSrc(attached)
      return
    }
    let cancelled = false
    streamSourceFor(video.id)
      .then((streamUrl) => {
        if (!cancelled) setSrc(streamUrl)
      })
      .catch(() => {
        /* thumbnails stay placeholders */
      })
    return () => {
      cancelled = true
    }
  }, [clipCount, video.id])

  // Real thumbnails, captured from whichever playback source is live.
  const clipList = clips ?? EMPTY_CLIPS
  useEffect(() => {
    if (clipList.length === 0 || !src) return
    let cancelled = false
    void captureFrames(src, clipList.map((clip) => clip.frame)).then((frames) => {
      if (!cancelled) setThumbs(frames)
    })
    return () => {
      cancelled = true
    }
  }, [clipList, src])

  if (!clips || clips.length === 0) return null

  const topScore = Math.max(...clips.map((clip) => clip.score), 0.001)

  return (
    <>
      <div className="px-4 pb-3 sm:px-5">
        <span className="mb-2 flex items-center gap-1.5 text-[12px] font-medium text-ink-dim">
          <SparkIcon className="size-3.5 text-brand" />
          Auto-extracted scenes
        </span>
        <div className="flex gap-2.5 overflow-x-auto pb-1">
          {clips.map((clip) => {
            const thumb = thumbs.get(clip.frame)
            const percent = Math.round((clip.score / topScore) * 100)
            return (
              <div key={clip.id} className="group relative w-36 shrink-0">
                <button
                  type="button"
                  onClick={() => setOpenClip(clip)}
                  className="block w-full cursor-pointer overflow-hidden rounded-xl border border-line bg-surface-sunk text-left"
                  title={`“${clip.prompt}” · ${percent}% match`}
                >
                  {thumb ? (
                    <img
                      src={thumb}
                      alt=""
                      className="aspect-video w-full object-cover"
                    />
                  ) : (
                    <span className="grid aspect-video w-full place-items-center bg-surface-sunk text-brand [&_svg]:size-5">
                      <PlayIcon />
                    </span>
                  )}
                  <span className="absolute right-1.5 bottom-1.5 rounded bg-ink/70 px-1 py-0.5 font-mono text-[10.5px] text-white">
                    {timecode(clip.start)} – {timecode(clip.end)}
                  </span>
                </button>
                <button
                  type="button"
                  aria-label="Delete this saved clip"
                  onClick={() => {
                    if (confirm('Delete this saved clip?')) {
                      void removeVideoClip(video.id, clip.id).then(() => {
                        setClips(clips.filter((item) => item.id !== clip.id))
                      })
                    }
                  }}
                  className="absolute top-1.5 right-1.5 hidden size-6 place-items-center rounded-md bg-ink/70 text-white opacity-0 transition-opacity group-hover:grid group-hover:opacity-100 hover:bg-danger [&_svg]:size-3.5"
                >
                  <TrashIcon />
                </button>
              </div>
            )
          })}
        </div>
      </div>

      <ClipLightbox
        clip={openClip}
        clips={clipList}
        video={video}
        src={src}
        prompt={openClip?.prompt ?? ''}
        // The lightbox navigates within `clips` (SavedClip[]), so the Clip it
        // hands back is always a SavedClip at runtime.
        onSelect={(clip) => setOpenClip(clip as SavedClip)}
        onClose={() => setOpenClip(null)}
      />
    </>
  )
}
