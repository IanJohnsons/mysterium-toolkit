import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],

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

