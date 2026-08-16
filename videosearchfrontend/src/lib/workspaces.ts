import { useCallback, useEffect, useState } from 'react'
import { API_ENABLED, apiFetch } from './http'

/**
 * Workspaces: team-shared video libraries.
 *
 * A video either lives in its uploader's personal library (`workspace_id:
 * null`) or in a workspace every member can see. This module is the teams
 * page's client: list/create/rename/delete workspaces, invite members by
 * email, and manage roles.
 *
 * Server-only, like collections: demo mode (no `VITE_API_URL`) has no
 * workspaces and the UI hides the whole feature rather than keeping a second
 * localStorage implementation in sync with the real one.
 */

export type WorkspaceRole = 'owner' | 'admin' | 'member' | 'viewer'

/** Whether a role may manage the workspace itself and its members. */
export function isManagerRole(role: WorkspaceRole | undefined | null): boolean {
  return role === 'owner' || role === 'admin'
}

/** Whether a role may upload/move/delete videos in the workspace. */
export function isEditorRole(role: WorkspaceRole | undefined | null): boolean {
  return role === 'owner' || role === 'admin' || role === 'member'
}

export type Workspace = {
  id: string
  name: string
  /** The caller's role — what the UI renders its permissions from. */
  role: WorkspaceRole
  memberCount: number
  createdAt: string
  updatedAt: string
}

export type WorkspaceMember = {
  userId: string
  name: string
  email: string
  role: WorkspaceRole
  createdAt: string
}

/** Backend `WorkspaceOut` shape (snake_case). */
type ApiWorkspace = {
  id: string
  name: string
  role: string
  member_count: number
  created_at: string
  updated_at: string
}

type ApiMember = {
  user_id: string
  name: string
  email: string
  role: string
  created_at: string
}

function toWorkspace(item: ApiWorkspace): Workspace {
  return {
    id: item.id,
    name: item.name,
    role: item.role as WorkspaceRole,
    memberCount: item.member_count,
    createdAt: item.created_at,
    updatedAt: item.updated_at,
  }
}

function toMember(item: ApiMember): WorkspaceMember {
  return {
    userId: item.user_id,
    name: item.name,
    email: item.email,
    role: item.role as WorkspaceRole,
    createdAt: item.created_at,
  }
}

/** Notifies every `useWorkspaces` mount that the list changed. */
const listeners = new Set<() => void>()

function emit(): void {
  for (const listener of listeners) listener()
}

/** Every workspace the user belongs to, A–Z. Empty in demo mode. */
export async function listWorkspaces(): Promise<Workspace[]> {
  if (!API_ENABLED) return []
  const data = await apiFetch<{ items: ApiWorkspace[] }>('/api/v1/workspaces')
  return data.items.map(toWorkspace)
}

export async function createWorkspace(name: string): Promise<Workspace> {
  const data = await apiFetch<ApiWorkspace>('/api/v1/workspaces', {
    method: 'POST',
    body: JSON.stringify({ name }),
  })
  emit()
  return toWorkspace(data)
}

export async function renameWorkspace(id: string, name: string): Promise<Workspace> {
  const data = await apiFetch<ApiWorkspace>(`/api/v1/workspaces/${id}`, {
    method: 'PATCH',
    body: JSON.stringify({ name }),
  })
  emit()
  return toWorkspace(data)
}

/** Delete the workspace. Its videos revert to their uploaders' libraries. */
export async function deleteWorkspace(id: string): Promise<void> {
  await apiFetch<unknown>(`/api/v1/workspaces/${id}`, { method: 'DELETE' })
  emit()
}

export async function inviteMember(
  workspaceId: string,
  email: string,
  role: WorkspaceRole,
): Promise<WorkspaceMember> {
  const data = await apiFetch<ApiMember>(`/api/v1/workspaces/${workspaceId}/members`, {
    method: 'POST',
    body: JSON.stringify({ email, role }),
  })
  emit()
  return toMember(data)
}

export async function setMemberRole(
  workspaceId: string,
  userId: string,
  role: WorkspaceRole,
): Promise<WorkspaceMember> {
  const data = await apiFetch<ApiMember>(
    `/api/v1/workspaces/${workspaceId}/members/${userId}`,
    {
      method: 'PATCH',
      body: JSON.stringify({ role }),
    },
  )
  emit()
  return toMember(data)
}

export async function removeMember(workspaceId: string, userId: string): Promise<void> {
  await apiFetch<unknown>(`/api/v1/workspaces/${workspaceId}/members/${userId}`, {
    method: 'DELETE',
  })
  emit()
}

export async function leaveWorkspace(workspaceId: string): Promise<void> {
  await apiFetch<unknown>(`/api/v1/workspaces/${workspaceId}/leave`, { method: 'POST' })
  emit()
}

/**
 * A workspace's full detail: the workspace plus its member roster — the
 * teams page's payload.
 */
export async function fetchWorkspace(
  id: string,
): Promise<{ workspace: Workspace; members: WorkspaceMember[] }> {
  const data = await apiFetch<{ workspace: ApiWorkspace; members: ApiMember[] }>(
    `/api/v1/workspaces/${id}`,
  )
  return { workspace: toWorkspace(data.workspace), members: data.members.map(toMember) }
}

/**
 * Live view of the user's workspaces (memberships).
 *
 * No polling: workspaces only change when this user changes them, so a
 * mutation-driven `emit()` is enough. `refresh` is returned for the rare
 * case a caller needs to force one.
 */
export function useWorkspaces(): {
  workspaces: Workspace[]
  refresh: () => void
  loading: boolean
} {
  const [workspaces, setWorkspaces] = useState<Workspace[]>([])
  const [loading, setLoading] = useState(API_ENABLED)

  const refresh = useCallback(() => {
    if (!API_ENABLED) {
      setWorkspaces([])
      setLoading(false)
      return
    }
    void listWorkspaces()
      .then(setWorkspaces)
      // A transient failure leaves the last good list on screen rather than
      // blanking the teams page — the next mutation or mount retries.
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    refresh()
    listeners.add(refresh)
    return () => {
      listeners.delete(refresh)
    }
  }, [refresh])

  return { workspaces, refresh, loading }
}
