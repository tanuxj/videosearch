/**
 * Build-time feature switches.
 *
 * Kept separate from `lib/http`'s `AUTH_ENABLED`, which changes how requests
 * are made (tokens, refresh). These only change what the UI offers, so the
 * two are independent: an open-access instance can still expose every page,
 * and a single-page instance can still require accounts.
 */

/**
 * Single-page mode: the app is just "add a video, index it, find the scene".
 *
 * `VITE_SINGLE_PAGE=true` hides the sidebar and folds Clips, Record,
 * Recordings, Teams and Library away — their routes redirect to the search
 * page instead of rendering. Nothing is deleted: every page, component and
 * API endpoint stays in the build, so setting this back to false (or dropping
 * it) restores the full workspace with no code change.
 */
export const SINGLE_PAGE = import.meta.env.VITE_SINGLE_PAGE === 'true'

/** Where single-page mode sends every route it has folded away. */
export const SINGLE_PAGE_ROUTE = '/search'
