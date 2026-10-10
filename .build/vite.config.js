import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import fs from 'node:fs'
import path from 'node:path'

// v1.4.65: write the toolkit version into the build. The Toolkit health check
// compared file dates — dist/index.html against VERSION — and a `git pull` or
// branch switch after a good build made VERSION newer, which read as a failed
// build. It now compares this file with the running version.
const buildVersion = () => ({
  name: 'toolkit-build-version',
  closeBundle() {
    try {
      const v = fs.readFileSync(path.resolve('VERSION'), 'utf8').trim()
      if (v) fs.writeFileSync(path.resolve('dist', 'BUILD_VERSION'), v + '\n')
    } catch (e) {
      // No VERSION next to the config (a build outside the toolkit directory).
    }
  },
})

export default defineConfig({
  plugins: [react(), buildVersion()],

  // Production build output
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    sourcemap: false,
    // In production the frontend is served by nginx at /
    // The Flask backend is proxied at /api/
    rollupOptions: {
      output: {
        manualChunks: undefined,
      }
    }
  },

  server: {
    host: '0.0.0.0',
    port: 3000,
    open: false,  // Don't auto-open browser on VPS/headless
    headers: {
      'Cache-Control': 'no-store',
    },
    proxy: {
      '/api': {
        target: 'http://localhost:5000',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
        configure: (proxy) => {
          proxy.on('proxyReq', (proxyReq, req) => {
            const realIp = req.socket?.remoteAddress || req.headers['x-forwarded-for'] || '';
            if (realIp) proxyReq.setHeader('X-Forwarded-For', realIp);
          });
        }
      },
      '/config': {
        target: 'http://localhost:5000',
        changeOrigin: true,
      }
    }
  }
})

