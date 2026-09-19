import { useState } from 'react'
import { useLocation, useNavigate } from '../lib/router'
import { useAuth } from '../lib/auth'
import { removeVideo, sourceFor, useVideos } from '../lib/store'
import { useCollections } from '../lib/collections'
import { isEditorRole, useWorkspaces } from '../lib/workspaces'
import type { WorkspaceRole } from '../lib/workspaces'
import { API_ENABLED } from '../lib/http'
import { AppShell } from '../components/Shell'
import { UploadDialog } from '../components/UploadDialog'
import { ShareButton } from '../components/ShareButton'
import { ProcessingTimer } from '../components/ProcessingTimer'
import { SavedClips } from '../components/SavedClips'
import { CollectionBar, CollectionMenu } from '../components/Collections'
import {
  MoveMenu,
  PERSONAL_LIBRARY,
  WorkspaceSwitcher,
} from '../components/WorkspaceControls'
import { Button } from '../components/ui/Button'
import {
  Chip,
  EmptyState,
  Panel,
  StatRow,
  StatTile,
} from '../components/ui/Data'
import {
  ClockIcon,
  FilmIcon,
  FolderIcon,
  LayersIcon,
  MicIcon,
  PlayIcon,
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

export default function Dashboard() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const videos = useVideos(user?.id)
  const { collections } = useCollections()
  const { workspaces } = useWorkspaces()
  const location = useLocation()
  const [uploadOpen, setUploadOpen] = useState(false)
  /** Collection currently filtering the grid; null is "all videos". */
  const [activeCollection, setActiveCollection] = useState<string | null>(null)
  /** Workspace currently scoping the grid; null is "all libraries". */
  const [activeWorkspace, setActiveWorkspace] = useState<string | null>(
    () => location.query.get('ws'),
  )

  // Filtered here rather than through the API's params: the library is
  // already loaded and carries its membership (each video knows its
  // workspace), so switching scopes is instant. The server-side filters are
  // still there for libraries too large to hold client-side.
  const workspaceFilter =
    activeWorkspace === PERSONAL_LIBRARY ||
    (activeWorkspace !== null &&
      workspaces.some((workspace) => workspace.id === activeWorkspace))
      ? activeWorkspace
      : null
  const scoped = videos.filter((video) => {
    if (workspaceFilter === null) return true
    if (workspaceFilter === PERSONAL_LIBRARY) return video.workspaceId == null
    return video.workspaceId === workspaceFilter
  })
  const shown =
    activeCollection === null
      ? scoped
      : scoped.filter((video) => video.collectionIds.includes(activeCollection))

  // Stats describe the whole library, not the current filter — they are the
  // workspace summary at the top of the page, not a readout of the grid.
  const totalFrames = videos.reduce((sum, video) => sum + video.frames, 0)
  const totalSeconds = videos.reduce((sum, video) => sum + video.duration, 0)
  const totalBytes = videos.reduce((sum, video) => sum + video.sizeBytes, 0)
  const ready = videos.filter((video) => video.status === 'ready').length

  const activeName =
    collections.find((item) => item.id === activeCollection)?.name ?? null
  const activeWorkspaceName =
    workspaces.find((workspace) => workspace.id === workspaceFilter)?.name ?? null

  /** The caller's role in a workspace, for permission-aware rendering. */
  function roleIn(workspaceId: string | null | undefined): WorkspaceRole | null {
    if (!workspaceId) return null
    return workspaces.find((workspace) => workspace.id === workspaceId)?.role ?? null
  }

  // Viewing a workspace you can't contribute to hides the upload buttons —
  // the dialog would default to your personal library, which reads wrong
  // from inside someone else's team space.
  const canUploadHere =
    workspaceFilter === null ||
    workspaceFilter === PERSONAL_LIBRARY ||
    isEditorRole(roleIn(workspaceFilter))

  const firstName = user?.name.split(' ')[0] ?? 'there'

  return (
    <AppShell
      title={`Welcome back, ${firstName}`}
      subtitle="Everything you've indexed, ready to search."
      actions={
        <>
          {canUploadHere && (
            <Button
              variant="secondary"
              size="sm"
              onClick={() => setUploadOpen(true)}
              className="[&_svg]:size-4"
            >
              <UploadIcon />
              Add video
            </Button>
          )}
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
        
        <Panel
            title="Your videos"
            subtitle={
              activeName
                ? `Showing the “${activeName}” collection.`
                : activeWorkspaceName
                  ? `Showing the “${activeWorkspaceName}” workspace.`
                  : 'Pick one to search, or add something new.'
            }
            actions={
              canUploadHere && (
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => setUploadOpen(true)}
                  className="[&_svg]:size-4"
                >
                  <UploadIcon />
                  Add videos
                </Button>
              )
            }
          >
            {API_ENABLED && workspaces.length > 0 && (
              <div className="border-b border-line px-4 py-3 sm:px-5">
                <WorkspaceSwitcher
                  workspaces={workspaces}
                  value={workspaceFilter}
                  onChange={setActiveWorkspace}
                />
              </div>
            )}

            {API_ENABLED && videos.length > 0 && (
              <div className="border-b border-line px-4 py-3 sm:px-5">
                <CollectionBar
                  collections={collections}
                  activeId={activeCollection}
                  onSelect={setActiveCollection}
                  totalCount={videos.length}
                />
              </div>
            )}

            {videos.length === 0 ? (
              <EmptyState
                icon={<UploadIcon />}
                title="No videos yet"
                body="Add your first videos and we’ll index every frame so you can search them by description."
                action={
                  <Button
                    onClick={() => setUploadOpen(true)}
                    className="[&_svg]:size-4"
                  >
                    <UploadIcon />
                    Add videos
                  </Button>
                }
              />
            ) : shown.length === 0 ? (
              <EmptyState
                icon={<LayersIcon />}
                title="Nothing here yet"
                body={
                  activeWorkspaceName
                    ? `No videos are in the “${activeWorkspaceName}” workspace yet. Add some from the upload dialog, or switch libraries.`
                    : `No videos are in “${activeName ?? ''}”. Use the File button on any video to add it, or pick a collection when you upload.`
                }
                action={
                  <Button
                    variant="secondary"
                    onClick={() => {
                      setActiveCollection(null)
                      setActiveWorkspace(null)
                    }}
                  >
                    Show all videos
                  </Button>
                }
              />
            ) : (
              <ul className="divide-y divide-[var(--border)]">
                {shown.map((video) => (
                  <li
                    key={video.id}
                    className="transition-colors hover:bg-surface-soft"
                  >
                    <div className="group flex flex-wrap items-center gap-3 px-4 py-3 sm:px-5">
                    <span className="grid size-14 shrink-0 place-items-center overflow-hidden rounded-xl border border-line bg-surface-sunk text-brand [&_svg]:size-5">
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
                        {/* Only once indexing has finished and the server
                            actually measured it — older videos have no
                            timing and simply omit this. */}
                        {video.processingSeconds !== undefined && (
                          <>
                            {' '}
                            · processed in{' '}
                            {humanDuration(video.processingSeconds)}
                          </>
                        )}
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
                          {video.processingStartedAt && (
                            <>
                              {' '}
                              <ProcessingTimer
                                startedAt={video.processingStartedAt}
                              />
                            </>
                          )}
                        </Chip>
                      )}

                      {/* Saves from the Record tab carry a tag so they read
                          differently from plain uploads at a glance. */}
                      {video.source === 'recording' && (
                        <Chip tone="brand" icon={<MicIcon />}>
                          Recording
                        </Chip>
                      )}
                      {/* Audio-only recordings have no frames to scene-search
                          — the tag keeps them distinct from screen captures. */}
                      {video.hasVideo === false && (
                        <Chip tone="neutral" icon={<WaveIcon />}>
                          Audio
                        </Chip>
                      )}

                      {/* Workspace videos carry their home's name so shared
                          footage is distinguishable from personal at a glance. */}
                      {API_ENABLED && video.workspaceId && (
                        <Chip tone="neutral" icon={<FolderIcon />}>
                          {workspaces.find((w) => w.id === video.workspaceId)?.name ??
                            'Workspace'}
                        </Chip>
                      )}

                      {!API_ENABLED && !sourceFor(video.id) && (
                        <Chip title="The file handle was lost when the tab reloaded — re-attach it on the search page to play clips back.">
                          Playback offline
                        </Chip>
                      )}

                      {API_ENABLED && (
                        <CollectionMenu video={video} collections={collections} />
                      )}

                      {API_ENABLED && (
                        <MoveMenu video={video} workspaces={workspaces} />
                      )}

                      {API_ENABLED && <ShareButton videoId={video.id} />}

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
                      {/* A viewer of a workspace video can watch but not
                          delete — the button only renders for editors. */}
                      {!video.workspaceId ||
                        isEditorRole(roleIn(video.workspaceId)) ? (
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
                      ) : null}
                    </div>
                    </div>
                    {/* Auto-extracted scenes — only renders when this video
                        has saved clips. */}
                    <SavedClips video={video} />
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
        initialWorkspaceId={
          canUploadHere && workspaceFilter !== PERSONAL_LIBRARY
            ? workspaceFilter
            : null
        }
      />
    </AppShell>
  )
}
