import { defineConfig } from 'vite';

export default defineConfig({
  server: {
    proxy: {
      '/layers': 'http://localhost:8000',
    },
  },
});
