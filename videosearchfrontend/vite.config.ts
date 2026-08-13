import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    // Pin to IPv4 loopback: Node resolves 'localhost' to IPv6 first on
    // Windows, which makes the port unreachable at 127.0.0.1.
    host: '127.0.0.1',
    port: 5174,
    strictPort: true,
    // Serve the API through this origin so the refresh cookie is first-party.
    //
    // The cookie is host-only with SameSite=Lax. Browsing `localhost:5174`
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
