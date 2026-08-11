import { useCallback, useEffect, useState } from 'react'
import type { AnchorHTMLAttributes, MouseEvent, ReactNode } from 'react'

/**
 * Minimal History-API router — enough for this app's handful of pages and
 * one less dependency to keep in sync.
 */

const listeners = new Set<(href: string) => void>()

function currentHref(): string {
  return `${window.location.pathname || '/'}${window.location.search}`
}

export function navigate(to: string, replace = false): void {
  if (to === currentHref()) return
  if (replace) window.history.replaceState({}, '', to)
  else window.history.pushState({}, '', to)
  window.scrollTo(0, 0)
  for (const notify of listeners) notify(to)
}

/** Full location: `path` is the pathname, `query` the parsed search params. */
export function useLocation(): { path: string; query: URLSearchParams } {
  const [href, setHref] = useState(currentHref)

  useEffect(() => {
    const onPop = () => setHref(currentHref())
    listeners.add(setHref)
    window.addEventListener('popstate', onPop)
    return () => {
      listeners.delete(setHref)
      window.removeEventListener('popstate', onPop)
    }
  }, [])

  const [path, search = ''] = href.split('?')
  return { path: path || '/', query: new URLSearchParams(search) }
}

/** Just the pathname — handy for nav highlighting. */
export function useRoute(): string {
  return useLocation().path
}

export function useNavigate(): (to: string, replace?: boolean) => void {
  return useCallback(navigate, [])
}

type LinkProps = AnchorHTMLAttributes<HTMLAnchorElement> & {
  to: string
  children: ReactNode
}

export function Link({ to, children, onClick, ...rest }: LinkProps) {
  const handle = (event: MouseEvent<HTMLAnchorElement>) => {
    onClick?.(event)
    // Let the browser handle modified clicks (new tab, download, …).
    if (
      event.defaultPrevented ||
      event.button !== 0 ||
      event.metaKey ||
      event.ctrlKey ||
      event.shiftKey ||
      event.altKey
    ) {
      return
    }
    event.preventDefault()
    navigate(to)
  }

  return (
    <a href={to} onClick={handle} {...rest}>
      {children}
    </a>
  )
}
