import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Served by Flask under /next/ while the old interface (frontend/) stays at /. `npm run dev` runs Vite on :5173 and
// forwards the API and the game connection to the Flask dev server (python app.py, :5000).
export default defineConfig({
  base: '/next/',
  plugins: [react()],
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    assetsDir: 'assets',     // file names carry a content hash -> Flask may cache them for a year
    sourcemap: false,
  },
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://127.0.0.1:5000',
      '/photos': 'http://127.0.0.1:5000',
      '/socket.io': { target: 'http://127.0.0.1:5000', ws: true },
    },
  },
});
