import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    // Bind all interfaces so the browser can use whichever loopback name it
    // resolves first (localhost → ::1 or 127.0.0.1, or 127.0.0.1 directly).
    host: true,
    // 5174 is taken on ::1 by a WSL port relay on this machine, which
    // Windows hands out before 127.0.0.1 — served by a different app
    // entirely. 5180 is free on both loopbacks, so pick it explicitly.
    port: 5180,
    strictPort: true,
    // Serve the API through this origin so the refresh cookie is first-party.
    //
    // The cookie is host-only with SameSite=Lax. Browsing `localhost:5180`
    // while calling `127.0.0.1:3006` is cross-site, so the browser drops the
    // cookie on `POST /auth/refresh` and every session ends after 15 minutes.
    // Proxying removes the cross-origin hop entirely — and CORS with it.
    //
    // Requires VITE_API_SAME_ORIGIN=true so the client uses relative URLs.
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:3006',
        // Keep the browser's Host header. The backend only reads it for CORS,
        // which no longer applies, and rewriting it would change the host the
        // Set-Cookie is attributed to.
        changeOrigin: false,
      },
    },
  },
})
