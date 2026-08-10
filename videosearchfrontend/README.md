# VideoSearch — frontend

A React + TypeScript video search frontend built with Vite. Runs on **port 5174**.

## Quick start

```bash
npm install
npm run dev        # → http://localhost:5174
```

## Environment

Copy `.env.example` to `.env` and fill in your values:

| Variable                  | Purpose                                              |
| ------------------------- | ---------------------------------------------------- |
| `VITE_APP_NAME`           | App name shown in the header                         |
| `VITE_YOUTUBE_API_KEY`    | YouTube Data API v3 key (optional — see below)       |
| `VITE_API_URL`            | Optional backend endpoint for a custom search API    |
| `VITE_ENABLE_MOCK_DATA`   | `true` = run on bundled demo videos, no network      |

> Without `VITE_YOUTUBE_API_KEY`, the UI runs on the built-in demo catalog
> (the header shows a **Demo data** badge). Add a key to switch to **Live API**.

## Scripts

```bash
npm run dev      # dev server on http://localhost:5174 (strict port)
npm run build    # typecheck (tsc -b) + production build to dist/
npm run lint     # oxlint
npm run preview  # preview the production build
```
