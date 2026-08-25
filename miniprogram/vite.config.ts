import { defineConfig } from 'vite'
import uni from '@dcloudio/vite-plugin-uni'
import { fileURLToPath } from 'node:url'

export default defineConfig(({ mode }) => {
  const mockBuild = mode === 'mock' || process.env.VITE_API_MODE === 'mock'
  return {
    plugins: [uni()],
    resolve: {
      alias: {
        '@': fileURLToPath(new URL('./src', import.meta.url)),
        '@api-runtime': fileURLToPath(new URL(mockBuild ? './src/api/runtime-mock.ts' : './src/api/runtime-real.ts', import.meta.url)),
      },
    },
    test: {
      environment: 'node',
      include: ['tests/**/*.test.ts'],
      coverage: {
        reporter: ['text', 'html'],
      },
    },
  }
})
