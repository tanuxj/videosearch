import { useState } from 'react'
import type { Collection } from '../lib/collections'
import {
  addVideosToCollection,
  createCollection,
  deleteCollection,
  removeVideosFromCollection,
  renameCollection,
} from '../lib/collections'
import type { VideoRecord } from '../lib/store'
import { refreshVideos } from '../lib/store'
import { cn } from '../lib/cn'
import { Button } from './ui/Button'
import { LayersIcon, TrashIcon } from './Icons'

/**
 * Collection controls for the library page.
 *
 * `CollectionBar` is the filter rail across the top; `CollectionMenu` is the
 * per-video membership toggle. Both mutate through `lib/collections`, then ask
 * the video store to re-list — membership lives on the video rows, so the grid
 * has to come back from the server for the change to show.
 */

/** Filter chips plus create / rename / delete for the selected collection. */
export function CollectionBar({
  collections,
  activeId,
  onSelect,
  totalCount,
}: {
  collections: Collection[]
  activeId: string | null
  onSelect: (id: string | null) => void
  /** How many videos the library holds in total — the "All" chip's count. */
  totalCount: number
}) {
  const [creating, setCreating] = useState(false)
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const active = collections.find((item) => item.id === activeId) ?? null

  async function submit(): Promise<void> {
    const trimmed = name.trim()
    if (!trimmed || busy) return
    setBusy(true)
    setError('')
    try {
      const created = await createCollection(trimmed)
      setName('')
      setCreating(false)
      onSelect(created.id)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not create that.')
    } finally {
      setBusy(false)
    }
  }

  async function rename(): Promise<void> {
    if (!active) return
    const next = window.prompt('Rename collection', active.name)?.trim()
    if (!next || next === active.name) return
    try {
      await renameCollection(active.id, next)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not rename that.')
    }
  }

  async function remove(): Promise<void> {
    if (!active) return
    const message =
      `Delete the “${active.name}” collection?\n\n` +
      `The ${active.videoCount} ${active.videoCount === 1 ? 'video' : 'videos'} ` +
      `inside it stay in your library.`
    if (!window.confirm(message)) return
    try {
      await deleteCollection(active.id)
      onSelect(null)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not delete that.')
    }
  }

  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-1.5">
        <FilterChip
          label="All videos"
          count={totalCount}
          active={activeId === null}
          onClick={() => onSelect(null)}
        />
        {collections.map((collection) => (
          <FilterChip
            key={collection.id}
            label={collection.name}
            count={collection.videoCount}
            active={collection.id === activeId}
            onClick={() => onSelect(collection.id)}
          />
        ))}

        {creating ? (
          <span className="flex items-center gap-1.5">
            <input
              value={name}
              onChange={(event) => setName(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter') void submit()
                if (event.key === 'Escape') {
                  setCreating(false)
                  setName('')
                }
              }}
              placeholder="Collection name"
              aria-label="New collection name"
              autoFocus
              className="w-44 rounded-full border border-brand bg-panel px-3 py-1 text-[12.5px] text-ink outline-none placeholder:text-ink-faint"
            />
            <Button size="sm" disabled={!name.trim() || busy} onClick={() => void submit()}>
              Create
            </Button>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => {
                setCreating(false)
                setName('')
                setError('')
              }}
            >
              Cancel
            </Button>
          </span>
        ) : (
          <button
            type="button"
            onClick={() => setCreating(true)}
            className="rounded-full border border-dashed border-line-strong px-3 py-1 text-[12.5px] font-medium text-ink-faint transition-colors hover:border-brand hover:text-brand"
          >
            + New collection
          </button>
        )}

        {active && (
          <span className="ml-auto flex items-center gap-1">
            <Button size="sm" variant="ghost" onClick={() => void rename()}>
              Rename
            </Button>
            <Button
              size="sm"
              variant="ghost"
              aria-label={`Delete the ${active.name} collection`}
              className="px-2 hover:bg-danger-wash hover:text-danger [&_svg]:size-4"
              onClick={() => void remove()}
            >
              <TrashIcon />
            </Button>
          </span>
        )}
      </div>

      {error && <p className="text-[12.5px] text-danger">{error}</p>}
    </div>
  )
}

function FilterChip({
  label,
  count,
  active,
  onClick,
}: {
  label: string
  count: number
  active: boolean
  onClick: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={cn(
        'rounded-full border px-3 py-1 text-[12.5px] font-medium transition-colors',
        active
          ? 'border-brand bg-brand-wash text-brand'
          : 'border-line bg-surface-soft text-ink-dim hover:border-line-strong hover:text-ink',
      )}
    >
      {label}
      <span className={cn('ml-1.5 tabular-nums', active ? 'text-brand' : 'text-ink-faint')}>
        {count}
      </span>
    </button>
  )
}

/**
 * Per-video membership toggle.
 *
 * A `<details>` popover rather than a custom dropdown: the browser handles
 * open/close, focus and Escape for free, which is the whole widget here.
 */
export function CollectionMenu({
  video,
  collections,
}: {
  video: VideoRecord
  collections: Collection[]
}) {
  const [busy, setBusy] = useState<string | null>(null)

  if (collections.length === 0) return null

  async function toggle(collection: Collection, member: boolean): Promise<void> {
    setBusy(collection.id)
    try {
      if (member) {
        await removeVideosFromCollection(collection.id, [video.id])
      } else {
        await addVideosToCollection(collection.id, [video.id])
      }
      // Membership is carried on the video rows, so the grid has to re-list.
      refreshVideos()
    } catch {
      // Leave the checkbox as it was — the next open reflects server truth.
    } finally {
      setBusy(null)
    }
  }

  const memberCount = video.collectionIds.length

  return (
    <details className="relative">
      <summary
        className={cn(
          'flex cursor-pointer list-none items-center gap-1.5 rounded-lg border px-2.5 py-1.5',
          'text-[12.5px] font-medium transition-colors [&::-webkit-details-marker]:hidden',
          memberCount > 0
            ? 'border-brand-line bg-brand-wash text-brand'
            : 'border-line bg-surface-soft text-ink-dim hover:text-ink',
          '[&_svg]:size-3.5',
        )}
        title={
          memberCount > 0
            ? `In ${memberCount} ${memberCount === 1 ? 'collection' : 'collections'}`
            : 'Not in any collection'
        }
      >
        <LayersIcon />
        {memberCount > 0 ? memberCount : 'File'}
      </summary>
      <div className="absolute right-0 z-20 mt-1.5 w-56 rounded-xl border border-line bg-panel p-1.5 shadow-lg">
        {collections.map((collection) => {
          const member = video.collectionIds.includes(collection.id)
          return (
            <label
              key={collection.id}
              className="flex cursor-pointer items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-[13px] text-ink hover:bg-surface-soft"
            >
              <input
                type="checkbox"
                checked={member}
                disabled={busy !== null}
                onChange={() => void toggle(collection, member)}
                className="size-3.5 accent-brand"
              />
              <span className="min-w-0 flex-1 truncate">{collection.name}</span>
              <span className="tabular-nums text-[11.5px] text-ink-faint">
                {collection.videoCount}
              </span>
            </label>
          )
        })}
      </div>
    </details>
  )
}
