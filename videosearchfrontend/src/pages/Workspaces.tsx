import { useEffect, useState } from 'react'
import { useAuth } from '../lib/auth'
import { Link } from '../lib/router'
import {
  createWorkspace,
  deleteWorkspace,
  fetchWorkspace,
  inviteMember,
  isManagerRole,
  leaveWorkspace,
  removeMember,
  renameWorkspace,
  setMemberRole,
  useWorkspaces,
} from '../lib/workspaces'
import type { WorkspaceMember, WorkspaceRole } from '../lib/workspaces'
import { AppShell } from '../components/Shell'
import { Alert, Spinner } from '../components/AuthLayout'
import { Button, ButtonLink } from '../components/ui/Button'
import { Chip, EmptyState, Panel } from '../components/ui/Data'
import { ArrowLeftIcon, TeamsIcon, TrashIcon } from '../components/Icons'
import { initials } from '../lib/auth'
import { relativeTime } from '../lib/format'

/**
 * Teams — create workspaces, invite members by email, and manage roles.
 *
 * The whole teams page's frontend. The server owns every permission (a
 * viewer calling these endpoints gets 403 regardless of what the UI shows);
 * the client just hides what a role can't do.
 */

/** Roles the owner/admin may assign. `owner` is never offered — the backend
 *  rejects it (a workspace always has exactly one owner). */
const ROLE_OPTIONS: { value: WorkspaceRole; label: string }[] = [
  { value: 'admin', label: 'Admin' },
  { value: 'member', label: 'Member' },
  { value: 'viewer', label: 'Viewer' },
]

function roleTone(role: WorkspaceRole): 'brand' | 'warn' | 'neutral' {
  if (role === 'owner') return 'brand'
  if (role === 'admin') return 'warn'
  return 'neutral'
}

export default function Workspaces() {
  const { user } = useAuth()
  const { workspaces } = useWorkspaces()

  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [members, setMembers] = useState<WorkspaceMember[] | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [detailError, setDetailError] = useState('')
  /** Bump to re-fetch the roster after a mutation (invite, role, remove). */
  const [tick, setTick] = useState(0)

  // Create-workspace form.
  const [creating, setCreating] = useState(false)
  const [newName, setNewName] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  // Invite form.
  const [inviteEmail, setInviteEmail] = useState('')
  const [inviteRole, setInviteRole] = useState<WorkspaceRole>('member')
  const [inviteBusy, setInviteBusy] = useState(false)
  const [inviteError, setInviteError] = useState('')

  const selected = workspaces.find((workspace) => workspace.id === selectedId) ?? null
  const isManager = isManagerRole(selected?.role)

  useEffect(() => {
    if (!selectedId) {
      setMembers(null)
      return
    }
    let alive = true
    setDetailLoading(true)
    setDetailError('')
    void fetchWorkspace(selectedId)
      .then((data) => {
        if (alive) setMembers(data.members)
      })
      .catch(() => {
        if (alive) setDetailError('Could not load this workspace.')
      })
      .finally(() => {
        if (alive) setDetailLoading(false)
      })
    return () => {
      alive = false
    }
  }, [selectedId, tick])

  async function submitCreate(): Promise<void> {
    const name = newName.trim()
    if (!name || busy) return
    setBusy(true)
    setError('')
    try {
      await createWorkspace(name)
      setNewName('')
      setCreating(false)
    } catch (caught) {
      setError(
        caught instanceof Error ? caught.message : 'Could not create that workspace.',
      )
    } finally {
      setBusy(false)
    }
  }

  async function rename(): Promise<void> {
    if (!selected) return
    const next = window.prompt('Rename workspace', selected.name)?.trim()
    if (!next || next === selected.name) return
    setError('')
    try {
      await renameWorkspace(selected.id, next)
    } catch (caught) {
      setError(
        caught instanceof Error ? caught.message : 'Could not rename that workspace.',
      )
    }
  }

  async function remove(): Promise<void> {
    if (!selected) return
    const message =
      `Delete “${selected.name}”?\n\n` +
      `Every video in it moves back to its uploader's personal library — ` +
      `nothing is deleted.`
    if (!window.confirm(message)) return
    setError('')
    try {
      await deleteWorkspace(selected.id)
      setSelectedId(null)
    } catch (caught) {
      setError(
        caught instanceof Error ? caught.message : 'Could not delete that workspace.',
      )
    }
  }

  async function leave(): Promise<void> {
    if (!selected) return
    if (!window.confirm(`Leave “${selected.name}”? You'll lose access to its videos.`)) return
    setError('')
    try {
      await leaveWorkspace(selected.id)
      setSelectedId(null)
    } catch (caught) {
      setError(
        caught instanceof Error ? caught.message : 'Could not leave that workspace.',
      )
    }
  }

  async function submitInvite(): Promise<void> {
    if (!selected || inviteBusy) return
    const email = inviteEmail.trim()
    if (!email) return
    setInviteBusy(true)
    setInviteError('')
    try {
      await inviteMember(selected.id, email, inviteRole)
      setInviteEmail('')
      setTick((value) => value + 1)
    } catch (caught) {
      setInviteError(
        caught instanceof Error ? caught.message : 'Could not invite that member.',
      )
    } finally {
      setInviteBusy(false)
    }
  }

  async function changeRole(member: WorkspaceMember, role: WorkspaceRole): Promise<void> {
    if (!selected) return
    setDetailError('')
    try {
      await setMemberRole(selected.id, member.userId, role)
      setTick((value) => value + 1)
    } catch (caught) {
      setDetailError(
        caught instanceof Error ? caught.message : 'Could not change that role.',
      )
    }
  }

  async function kick(member: WorkspaceMember): Promise<void> {
    if (!selected) return
    if (!window.confirm(`Remove ${member.name} from “${selected.name}”?`)) return
    setDetailError('')
    try {
      await removeMember(selected.id, member.userId)
      setTick((value) => value + 1)
    } catch (caught) {
      setDetailError(
        caught instanceof Error ? caught.message : 'Could not remove that member.',
      )
    }
  }

  return (
    <AppShell
      title="Teams"
      subtitle="Share a library — invite people, and everyone searches the same footage."
    >
      <div className="flex flex-col gap-5">
        {error && <Alert>{error}</Alert>}

        {!selected ? (
          <>
            {workspaces.length === 0 ? (
              <EmptyState
                icon={<TeamsIcon />}
                title="No teams yet"
                body="Create a workspace and invite people by email. Everyone in it can watch and search the shared videos; editors can add their own."
              />
            ) : (
              <Panel
                title="Your teams"
                subtitle="Each one is a shared video library."
                bodyClassName="flex flex-col divide-y divide-[var(--border)]"
              >
                {workspaces.map((workspace) => (
                  <div
                    key={workspace.id}
                    className="flex flex-wrap items-center gap-3 px-4 py-3.5 sm:px-5"
                  >
                    <span className="grid size-11 shrink-0 place-items-center rounded-xl border border-line bg-surface-sunk text-brand [&_svg]:size-5">
                      <TeamsIcon />
                    </span>
                    <div className="min-w-0 flex-1">
                      <b className="block truncate text-[14.5px] font-semibold text-ink">
                        {workspace.name}
                      </b>
                      <span className="mt-0.5 block truncate text-[12.5px] text-ink-faint">
                        {workspace.memberCount}{' '}
                        {workspace.memberCount === 1 ? 'member' : 'members'} · created{' '}
                        {relativeTime(workspace.createdAt)}
                      </span>
                    </div>
                    <Chip tone={roleTone(workspace.role)}>{workspace.role}</Chip>
                    <div className="flex shrink-0 items-center gap-2">
                      <ButtonLink
                        as={Link}
                        to={`/dashboard?ws=${workspace.id}`}
                        variant="secondary"
                        size="sm"
                      >
                        Open library
                      </ButtonLink>
                      <Button size="sm" onClick={() => setSelectedId(workspace.id)}>
                        Manage
                      </Button>
                    </div>
                  </div>
                ))}
              </Panel>
            )}

            <Panel
              title="New workspace"
              subtitle="Start a team library — you'll be its owner."
              bodyClassName="p-5"
            >
              {creating ? (
                <form
                  className="flex flex-col gap-2 sm:flex-row"
                  onSubmit={(event) => {
                    event.preventDefault()
                    void submitCreate()
                  }}
                >
                  <input
                    value={newName}
                    onChange={(event) => setNewName(event.target.value)}
                    placeholder="Workspace name, e.g. “Design”"
                    aria-label="Workspace name"
                    autoFocus
                    className="w-full flex-1 rounded-lg border border-line-strong bg-panel px-3.5 py-2 text-[13.5px] text-ink outline-none placeholder:text-ink-faint focus:border-brand"
                  />
                  <div className="flex gap-2">
                    <Button type="submit" disabled={!newName.trim() || busy}>
                      Create
                    </Button>
                    <Button
                      type="button"
                      variant="ghost"
                      onClick={() => {
                        setCreating(false)
                        setNewName('')
                      }}
                    >
                      Cancel
                    </Button>
                  </div>
                </form>
              ) : (
                <Button onClick={() => setCreating(true)} className="[&_svg]:size-4">
                  <TeamsIcon />
                  New workspace
                </Button>
              )}
            </Panel>
          </>
        ) : (
          <>
            <div>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setSelectedId(null)}
                className="[&_svg]:size-4"
              >
                <ArrowLeftIcon />
                All teams
              </Button>
            </div>

            <Panel
              title={selected.name}
              subtitle={`${selected.memberCount} ${selected.memberCount === 1 ? 'member' : 'members'} · you are ${selected.role}`}
              actions={
                <>
                  {isManager && (
                    <Button size="sm" variant="secondary" onClick={() => void rename()}>
                      Rename
                    </Button>
                  )}
                  <ButtonLink
                    as={Link}
                    to={`/dashboard?ws=${selected.id}`}
                    variant="secondary"
                    size="sm"
                  >
                    Open library
                  </ButtonLink>
                </>
              }
              bodyClassName="flex flex-col divide-y divide-[var(--border)]"
            >
              {detailLoading ? (
                <div className="flex items-center justify-center gap-2 px-5 py-8 text-[13px] text-ink-faint">
                  <Spinner />
                  Loading members…
                </div>
              ) : detailError ? (
                <p className="px-5 py-6 text-[13px] text-danger">{detailError}</p>
              ) : (
                (members ?? []).map((member) => {
                  const isMe = member.userId === user?.id
                  return (
                    <div
                      key={member.userId}
                      className="flex flex-wrap items-center gap-3 px-4 py-3 sm:px-5"
                    >
                      <span className="grid size-9 shrink-0 place-items-center rounded-full bg-brand text-[12px] font-semibold text-white">
                        {initials(member.name)}
                      </span>
                      <div className="min-w-0 flex-1">
                        <b className="block truncate text-[13.5px] font-semibold text-ink">
                          {member.name}
                          {isMe && (
                            <span className="ml-1.5 font-normal text-ink-faint">(you)</span>
                          )}
                        </b>
                        <span className="block truncate text-[12px] text-ink-faint">
                          {member.email}
                        </span>
                      </div>
                      {member.role === 'owner' || !isManager ? (
                        <Chip tone={roleTone(member.role)}>{member.role}</Chip>
                      ) : (
                        <select
                          value={member.role}
                          onChange={(event) =>
                            void changeRole(member, event.target.value as WorkspaceRole)
                          }
                          aria-label={`Role for ${member.name}`}
                          className="rounded-lg border border-line-strong bg-panel px-2.5 py-1.5 text-[12.5px] text-ink outline-none focus:border-brand"
                        >
                          {ROLE_OPTIONS.map((option) => (
                            <option key={option.value} value={option.value}>
                              {option.label}
                            </option>
                          ))}
                        </select>
                      )}
                      {isManager && member.role !== 'owner' && (
                        <Button
                          variant="ghost"
                          size="sm"
                          aria-label={`Remove ${member.name}`}
                          className="px-2 hover:bg-danger-wash hover:text-danger [&_svg]:size-4"
                          onClick={() => void kick(member)}
                        >
                          <TrashIcon />
                        </Button>
                      )}
                    </div>
                  )
                })
              )}
            </Panel>

            {isManager && (
              <Panel
                title="Invite a member"
                subtitle="They must already have an account — invite by the email they signed up with."
                bodyClassName="p-5"
              >
                <form
                  className="flex flex-col gap-2 sm:flex-row"
                  onSubmit={(event) => {
                    event.preventDefault()
                    void submitInvite()
                  }}
                >
                  <input
                    type="email"
                    value={inviteEmail}
                    onChange={(event) => setInviteEmail(event.target.value)}
                    placeholder="teammate@company.com"
                    aria-label="Member email"
                    className="w-full flex-1 rounded-lg border border-line-strong bg-panel px-3.5 py-2 text-[13.5px] text-ink outline-none placeholder:text-ink-faint focus:border-brand"
                  />
                  <select
                    value={inviteRole}
                    onChange={(event) =>
                      setInviteRole(event.target.value as WorkspaceRole)
                    }
                    aria-label="Role to assign"
                    className="rounded-lg border border-line-strong bg-panel px-3 py-2 text-[13.5px] text-ink outline-none focus:border-brand"
                  >
                    {ROLE_OPTIONS.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                  <Button
                    type="submit"
                    disabled={!inviteEmail.trim() || inviteBusy}
                  >
                    Invite
                  </Button>
                </form>
                {inviteError && (
                  <p className="mt-2.5 text-[12.5px] text-danger">{inviteError}</p>
                )}
              </Panel>
            )}

            <Panel
              title="Danger zone"
              subtitle="Ownership is the only thing that can't be undone."
              bodyClassName="flex flex-col items-start gap-2.5 p-5"
            >
              {selected.role === 'owner' ? (
                <Button variant="danger" onClick={() => void remove()}>
                  Delete workspace
                </Button>
              ) : (
                <Button variant="secondary" onClick={() => void leave()}>
                  Leave workspace
                </Button>
              )}
              <p className="max-w-[52ch] text-[12.5px] leading-relaxed text-ink-faint">
                Deleting a workspace moves every video back to its uploader's
                personal library — nothing is lost. Only the owner can delete;
                anyone else leaves instead.
              </p>
            </Panel>
          </>
        )}
      </div>
    </AppShell>
  )
}
