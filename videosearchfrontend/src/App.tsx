import { useEffect, useMemo, useRef, useState } from 'react'
import SearchBar from './components/SearchBar'
import VideoGrid from './components/VideoGrid'
import { CATEGORIES, VIDEOS } from './data/videos'
import type { Video } from './data/videos'

const appName: string = import.meta.env.VITE_APP_NAME || 'VideoSearch'
const apiKey: string = (import.meta.env.VITE_YOUTUBE_API_KEY ?? '').trim()
const mockEnabled: boolean = import.meta.env.VITE_ENABLE_MOCK_DATA !== 'false'

const SEARCH_DELAY_MS = 650

function matchVideos(query: string, category: string): Video[] {
  const q = query.trim().toLowerCase()
  return VIDEOS.filter((video) => {
    const matchesQuery =
      q === '' ||
      video.title.toLowerCase().includes(q) ||
      video.channel.toLowerCase().includes(q)
    const matchesCategory = category === 'All' || video.category === category
    return matchesQuery && matchesCategory
  })
}

function App() {
  const [query, setQuery] = useState('')
  const [category, setCategory] = useState('All')
  const [results, setResults] = useState<Video[]>(VIDEOS)
  const [loading, setLoading] = useState(false)
  const [searched, setSearched] = useState(false)

  const timerRef = useRef<number | undefined>(undefined)
  const bootstrapped = useRef(false)

  const runSearch = (q: string, cat: string) => {
    window.clearTimeout(timerRef.current)
    setLoading(true)
    timerRef.current = window.setTimeout(() => {
      setResults(matchVideos(q, cat))
      setSearched(true)
      setLoading(false)
    }, SEARCH_DELAY_MS)
  }

  useEffect(() => {
    if (bootstrapped.current) return
    bootstrapped.current = true
    runSearch('', 'All')
  }, [])

  // Clear any pending search timer on unmount
  useEffect(() => () => window.clearTimeout(timerRef.current), [])

  const handleSearch = () => runSearch(query, category)

  const handlePickTerm = (term: string) => {
    setQuery(term)
    runSearch(term, category)
  }

  const handleCategory = (cat: string) => {
    setCategory(cat)
    runSearch(query, cat)
  }

  const resetAll = () => {
    setQuery('')
    setCategory('All')
    runSearch('', 'All')
  }

  const handleClear = () => {
    setQuery('')
    runSearch('', category)
  }

  const resultLabel = useMemo(() => {
    if (loading) return 'Searching…'
    if (results.length === 0) return 'No results'
    const context =
      searched && query.trim() ? `Results for “${query.trim()}”` : 'Trending now'
    return `${results.length} ${results.length === 1 ? 'video' : 'videos'} · ${context}`
  }, [loading, results.length, searched, query])

  return (
    <div className="app">
      <header className="site-header">
        <a className="brand" href="/" aria-label={`${appName} home`}>
          <span className="brand-mark">
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <path d="M8 5.14v13.72L19 12 8 5.14z" />
            </svg>
          </span>
          <span className="brand-name">{appName}</span>
        </a>

        <span className={`mode-badge ${apiKey ? 'online' : 'demo'}`}>
          <span className="mode-dot" />
          {apiKey ? 'Live API' : 'Demo data'}
        </span>
      </header>

      <main>
        <section className="hero">
          <h1 className="hero-title">
            Search the <span className="gradient-text">video universe</span>
          </h1>
          <p className="hero-sub">
            Find videos across every topic in milliseconds — no account, no
            ads. Just press enter and go.
          </p>
          <SearchBar
            query={query}
            onQueryChange={setQuery}
            onSearch={handleSearch}
            onPickTerm={handlePickTerm}
            onClear={handleClear}
          />
        </section>

        <section className="results-section" aria-live="polite">
          <div className="results-bar">
            <p className="results-count">{resultLabel}</p>
            <div className="category-chips" role="group" aria-label="Filter by category">
              {CATEGORIES.map((cat) => (
                <button
                  key={cat}
                  type="button"
                  aria-pressed={category === cat}
                  className={`chip ${category === cat ? 'chip-active' : ''}`}
                  onClick={() => handleCategory(cat)}
                >
                  {cat}
                </button>
              ))}
            </div>
          </div>

          <VideoGrid
            videos={results}
            loading={loading}
            query={query.trim()}
            onReset={resetAll}
          />
        </section>
      </main>

      <footer className="site-footer">
        <p>React + TypeScript + Vite</p>
        <p className="footer-note">
          {mockEnabled && !apiKey
            ? 'No API key in .env yet — showing bundled demo videos.'
            : 'Video data via YouTube Data API v3.'}
        </p>
      </footer>
    </div>
  )
}

export default App
