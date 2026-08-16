import { useState } from 'react'
import type { VideoRecord } from '../lib/store'
import { moveVideo } from '../lib/store'
import type { Workspace } from '../lib/workspaces'
import { isEditorRole } from '../lib/workspaces'
import { cn } from '../lib/cn'
import { FolderIcon } from './Icons'

/**
 * Workspace controls for the library page.
 *
 * `WorkspaceSwitcher` scopes the grid to one library (personal or a single
 * workspace); `MoveMenu` relocates a video between workspaces (or back to
 * the uploader's personal library). Mutations go through `lib/workspaces` /
 * `lib/store`, whose emit re-lists the video grid.
 */

/** Sentinel select value for the "uploader's personal library" filter. */
export const PERSONAL_LIBRARY = '__personal__'

/** Filter the library to one scope: all, personal, or a single workspace. */
export function WorkspaceSwitcher({
  workspaces,
  value,
  onChange,
}: {
  workspaces: Workspace[]
  value: string | null
  onChange: (value: string | null) => void
}) {
  return (
    <div className="flex items-center gap-2.5">
      <label
        htmlFor="library-workspace"
        className="shrink-0 text-[12.5px] font-medium text-ink-dim"
      >
        Library
      </label>
      <select
        id="library-workspace"
        value={value ?? ''}
        onChange={(event) => onChange(event.target.value || null)}
        className="w-full max-w-72 rounded-lg border border-line-strong bg-panel px-3 py-1.5 text-[13px] text-ink outline-none focus:border-brand"
      >
        <option value="">All libraries</option>
        <option value={PERSONAL_LIBRARY}>My library</option>
        {workspaces.map((workspace) => (
          <option key={workspace.id} value={workspace.id}>
            {workspace.name}
          </option>
        ))}
      </select>
    </div>
  )
}

/**
 * Per-video "move to a workspace" control.
 *
 * A `<details>` popover like the collection menu: the browser handles
 * open/close, focus and Escape for free. Only editor-role workspaces appear
 * as targets (a viewer can't move into one), and the control hides entirely
 * when the caller can't move the video at all — a viewer of its current
 * workspace, say.
 */
export function MoveMenu({
  video,
  workspaces,
}: {
  video: VideoRecord
  workspaces: Workspace[]
}) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  // The caller's role in the video's current home, when it's a workspace.
  const home = video.workspaceId
    ? workspaces.find((workspace) => workspace.id === video.workspaceId)
    : null
  const canMoveHere = video.workspaceId == null || isEditorRole(home?.role)
  // Workspaces the caller may move *into* — editors only.
  const targets = workspaces.filter((workspace) => isEditorRole(workspace.role))
  if (!canMoveHere || targets.length === 0) return null

  async function move(workspaceId: string | null): Promise<void> {
    setBusy(true)
    setError('')
    try {
      // The store re-lists the library when the move lands.
      await moveVideo(video.id, workspaceId)
    } catch (caught) {
      setError(
        caught instanceof Error ? caught.message : 'Could not move that video.',
      )
    } finally {
      setBusy(false)
    }
  }

  const optionClass = (current: boolean) =>
    cn(
      'flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-left text-[13px] transition-colors',
      current || busy
        ? 'text-ink-mid'
        : 'text-ink hover:bg-surface-soft disabled:opacity-50',
      current && 'font-medium',
    )

  return (
    <details className="relative">
      <summary
        className={cn(
          'flex cursor-pointer list-none items-center gap-1.5 rounded-lg border px-2.5 py-1.5',
          'text-[12.5px] font-medium transition-colors [&::-webkit-details-marker]:hidden',
          video.workspaceId
            ? 'border-brand-line bg-brand-wash text-brand'
            : 'border-line bg-surface-soft text-ink-dim hover:text-ink',
          '[&_svg]:size-3.5',
        )}
        title={
          video.workspaceId ? 'In a workspace — move it' : 'Move to a workspace'
        }
      >
        <FolderIcon />
        {video.workspaceId ? 'Workspace' : 'Move'}
      </summary>
      <div className="absolute right-0 z-20 mt-1.5 w-60 rounded-xl border border-line bg-panel p-1.5 shadow-lg">
        <p className="px-2.5 pt-1 pb-1 text-[11px] font-medium tracking-[0.06em] text-ink-faint uppercase">
          Move to
        </p>
        {error && <p className="px-2.5 py-1 text-[12px] text-danger">{error}</p>}
        <button
          type="button"
          disabled={busy || video.workspaceId == null}
          onClick={() => void move(null)}
          className={optionClass(video.workspaceId == null)}
        >
          <span className="min-w-0 flex-1 truncate">Personal library</span>
          {video.workspaceId == null && (
            <span className="text-[11px] text-ink-faint">current</span>
          )}
        </button>
        {targets.map((workspace) => {
          const current = video.workspaceId === workspace.id
          return (
            <button
              key={workspace.id}
              type="button"
              disabled={busy || current}
              onClick={() => void move(workspace.id)}
              className={optionClass(current)}
            >
              <span className="min-w-0 flex-1 truncate">{workspace.name}</span>
              {current && (
                <span className="text-[11px] text-ink-faint">current</span>
              )}
            </button>
          )
        })}
      </div>
    </details>
  )
}
