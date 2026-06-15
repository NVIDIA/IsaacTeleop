/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 *
 * Human-readable chunk names for production builds.
 *
 * Target layout (two JS artifacts):
 * - ``bundle.js`` — main application (UIKit, MSDF text, Lucide icons, runtime)
 * - ``bundle.emulator.js`` — desktop XR / IWER code (DevUI, SEM scenes, deps)
 *
 * MSDF is pulled into the main entry (see ``webpack.common.js``) so in-VR text
 * does not depend on extra lazy chunks over OOB. The MSDF web worker is inlined
 * via ``asset/inline`` (data URL) so no separate worker file is emitted.
 *
 * Lazy boundary: ``@pmndrs/xr`` ``import('./emulate.js')`` → ``bundle.emulator.js``.
 * OOB/--host-client sync downloads ``index.html``, ``bundle.js``, and
 * ``bundle.emulator.js``.
 */

const path = require('path');

/** Only non-main async chunk basename. */
const EMULATOR_CHUNK = 'emulator';

/**
 * True when *resource* belongs in the single IWER / desktop-emulator async chunk.
 *
 * @param {string | undefined} resource Webpack module resource path.
 * @returns {boolean}
 */
function isEmulatorAsyncModule(resource = '') {
  if (!resource) {
    return false;
  }
  if (/[\\/]@pmndrs[\\/]xr[\\/]dist[\\/]emulate/.test(resource)) {
    return true;
  }
  if (/[\\/]node_modules[\\/]iwer[\\/]lib/.test(resource)) {
    return true;
  }
  if (/[\\/]node_modules[\\/]@iwer[\\/]/.test(resource)) {
    return true;
  }
  if (/[\\/]node_modules[\\/](?:styled-components|stylis|@fortawesome|gl-matrix)/.test(resource)) {
    return true;
  }
  if (
    /[\\/]node_modules[\\/](?:prop-types|@bufbuild[\\/]protobuf|scheduler|webxr-layers-polyfill)/.test(
      resource
    )
  ) {
    return true;
  }
  return false;
}

/** @type {import('webpack').Configuration['optimization']} */
const chunkOptimization = {
  chunkIds: 'named',
  splitChunks: {
    chunks: 'async',
    cacheGroups: {
      default: false,
      defaultVendors: false,
      emulator: {
        test: module => isEmulatorAsyncModule(module.resource),
        name: EMULATOR_CHUNK,
        chunks: 'async',
        enforce: true,
      },
    },
  },
};

/** @type {import('webpack').Configuration['output']['chunkFilename']} */
function chunkFilename(pathData) {
  const name = pathData.chunk?.name;
  if (name === EMULATOR_CHUNK) {
    return 'bundle.emulator.js';
  }
  const id = String(pathData.chunk?.id ?? 'unknown');
  throw new Error(
    `Unexpected async chunk "${id}" (name=${name ?? ''}). ` +
      'Only bundle.emulator.js is allowed besides bundle.js. ' +
      'Update webpack.common.js entry or webpack.chunkNames.js.'
  );
}

/**
 * Keep MSDF in ``bundle.js``: ``@pmndrs/uikit`` dynamically imports
 * ``@zappar/msdf-generator``, which would otherwise become a third lazy chunk.
 */
const msdfGeneratorEntry = path.resolve(
  __dirname,
  'node_modules/@zappar/msdf-generator/dist/index.js'
);

/** Inline MSDF worker as a data URL inside ``bundle.js`` (no extra worker file). */
const msdfInlineRules = {
  rules: [
    {
      test: /[\\/]@zappar[\\/]msdf-generator[\\/]dist[\\/]worker\.js$/,
      type: 'asset/inline',
    },
  ],
};

module.exports = {
  chunkFilename,
  chunkOptimization,
  msdfGeneratorEntry,
  msdfInlineRules,
};
