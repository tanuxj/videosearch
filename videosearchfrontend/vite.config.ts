import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // Pin to IPv4 loopback: Node resolves 'localhost' to IPv6 first on
    // Windows, which makes the port unreachable at 127.0.0.1.
    host: '127.0.0.1',
    port: 5174,
    strictPort: true,
  },
})
