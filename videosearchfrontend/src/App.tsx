const appName: string = import.meta.env.VITE_APP_NAME || 'VideoSearch'

function App() {
  return (
    <div className="app">
      <header className="site-header">
        <span className="brand">
          <span className="brand-mark">
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <path d="M8 5.14v13.72L19 12 8 5.14z" />
            </svg>
          </span>
          <span className="brand-name">{appName}</span>
        </span>
      </header>

      <main className="app-main">
        <h1 className="app-title">
          Semantic <span className="gradient-text">video search</span>
        </h1>
        <p className="app-sub">
          Upload a video, describe a scene in plain language, and jump straight
          to the matching moment.
        </p>
      </main>

      <footer className="site-footer">
        <p>React + TypeScript + Vite</p>
      </footer>
    </div>
  )
}

export default App
