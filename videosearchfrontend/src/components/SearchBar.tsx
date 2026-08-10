import { useRef } from 'react'
import type { FormEvent, KeyboardEvent } from 'react'
import { HOT_SEARCHES } from '../data/videos'

interface SearchBarProps {
  query: string
  onQueryChange: (q: string) => void
  onSearch: () => void
  onPickTerm: (term: string) => void
  onClear: () => void
}

export default function SearchBar({
  query,
  onQueryChange,
  onSearch,
  onPickTerm,
  onClear,
}: SearchBarProps) {
  const inputRef = useRef<HTMLInputElement>(null)

  const handleSubmit = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    onSearch()
  }

  const handleKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Escape') {
      onClear()
      inputRef.current?.focus()
    }
  }

  return (
    <div className="search-zone">
      <form className="search-bar" role="search" onSubmit={handleSubmit}>
        <svg
          className="search-icon"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2.2"
          strokeLinecap="round"
          aria-hidden="true"
        >
          <circle cx="11" cy="11" r="7" />
          <path d="M21 21l-4.3-4.3" />
        </svg>
        <input
          ref={inputRef}
          type="search"
          value={query}
          onChange={(e) => onQueryChange(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Search videos, channels, topics…"
          aria-label="Search videos"
          spellCheck={false}
          autoComplete="off"
        />
        <button type="submit" className="search-btn">
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path d="M8 5.14v13.72L19 12 8 5.14z" />
          </svg>
          <span>Search</span>
        </button>
      </form>

      <div className="hot-chips" aria-label="Popular searches">
        {HOT_SEARCHES.map((term) => (
          <button
            key={term}
            type="button"
            className="chip"
            onClick={() => onPickTerm(term)}
          >
            {term}
          </button>
        ))}
      </div>
    </div>
  )
}
