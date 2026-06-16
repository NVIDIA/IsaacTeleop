/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

import { defineConfig } from 'vite';
import type { Plugin } from 'vite';
import react from '@vitejs/plugin-react';

const SPDX_TEXT =
  'SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.\n' +
  'SPDX-License-Identifier: Apache-2.0';

function spdxBundleHeaders(): Plugin {
  return {
    name: 'spdx-bundle-headers',
    renderChunk(code) {
      return {
        code: `/* ${SPDX_TEXT.replace(/\n/g, '\n * ')}\n */\n${code}`,
        map: null,
      };
    },
    generateBundle(_, bundle) {
      for (const asset of Object.values(bundle)) {
        if (asset.type === 'chunk') {
          asset.code = `/* ${SPDX_TEXT.replace(/\n/g, '\n * ')}\n */\n${asset.code}`;
        }
        if (asset.type === 'asset' && asset.fileName.endsWith('.css') && typeof asset.source === 'string') {
          asset.source = `/* ${SPDX_TEXT.replace(/\n/g, '\n * ')}\n */\n${asset.source}`;
        }
      }
    },
  };
}

export default defineConfig({
  base: '/hub/',
  plugins: [react(), spdxBundleHeaders()],
  build: {
    outDir: 'build',
    emptyOutDir: true,
  },
  server: {
    host: '0.0.0.0',
    port: 5173,
    proxy: {
      '/api': {
        target: 'https://localhost:48322',
        changeOrigin: true,
        secure: false,
      },
      '/oob': {
        target: 'https://localhost:48322',
        changeOrigin: true,
        secure: false,
        ws: true,
      },
    },
  },
});
