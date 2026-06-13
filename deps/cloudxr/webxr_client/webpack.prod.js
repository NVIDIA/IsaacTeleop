/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 * http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

const fs = require('fs');
const path = require('path');
const { merge } = require('webpack-merge');
const common = require('./webpack.common.js');

/**
 * Webpack plugin: write ``asset-manifest.json`` after a production build.
 *
 * Isaac Teleop OOB/--host-client sync reads this manifest to download and
 * serve lazy chunks (``[id].bundle.js``) in addition to ``index.html`` and
 * ``bundle.js``. See docs ``build_from_source/webxr.rst``.
 */
class AssetManifestPlugin {
  /**
   * @param {import('webpack').Compiler} compiler
   */
  apply(compiler) {
    // After emit: write sorted asset list for OOB manifest-driven sync.
    compiler.hooks.done.tap('AssetManifestPlugin', stats => {
      const outDir = stats.compilation.outputOptions.path;
      // Every emitted asset except the manifest itself (avoid self-reference).
      const files = stats.compilation
        .getAssets()
        .map(a => a.name)
        .filter(name => name !== 'asset-manifest.json')
        .sort();
      fs.writeFileSync(
        path.join(outDir, 'asset-manifest.json'),
        JSON.stringify({ files }, null, 2)
      );
    });
  }
}

module.exports = merge(common, {
  mode: 'production',
  // Remove stale chunks when chunk ids change between builds.
  output: { clean: true },
  plugins: [new AssetManifestPlugin()],
});
