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

const path = require('path');
const HtmlWebpackPlugin = require('html-webpack-plugin');
const CopyWebpackPlugin = require('copy-webpack-plugin');
const webpack = require('webpack');

// WebXR input profile assets are used by default when @webxr-input-profiles/assets is installed.
// Set USE_LOCAL_WEBXR_ASSETS=0 to skip bundling local assets (build needs internet at runtime to load assets).
const useLocalWebxrAssets = process.env.USE_LOCAL_WEBXR_ASSETS !== '0';
let webxrAssetsPackagePath = null;
let WEBXR_ASSETS_VERSION = '';
if (useLocalWebxrAssets) {
  try {
    webxrAssetsPackagePath = require.resolve('@webxr-input-profiles/assets/package.json');
    const webxrAssetsPackage = require(webxrAssetsPackagePath);
    WEBXR_ASSETS_VERSION = webxrAssetsPackage.version;
  } catch {
    console.warn(
      'webpack: @webxr-input-profiles/assets not found; building without WebXR input profile assets (controller models will use fallback or be disabled).'
    );
  }
}

module.exports = {
  entry: './src/index.tsx',

  // Enable webpack 5 persistent filesystem caching for faster incremental builds
  cache: {
    type: 'filesystem',
    buildDependencies: {
      config: [__filename],
    },
  },

  // Module rules define how different file types are processed
  module: {
    rules: [
      {
        test: /\.tsx?$/,
        use: {
          loader: 'ts-loader',
          options: {
            // Only transpile, don't type-check (faster builds)
            transpileOnly: true,
          },
        },
        exclude: /node_modules/,
      },
      {
        test: /\.css$/,
        use: ['style-loader', 'css-loader'],
      },
    ],
  },

  // Resolve configuration for module resolution
  resolve: {
    extensions: ['.tsx', '.ts', '.js'],
    alias: {
      // @helpers can be used instead of relative paths to the helpers directory
      '@helpers': path.resolve(__dirname, './helpers'),
    },
  },

  // Output configuration for bundled files
  output: {
    filename: 'bundle.js',
    path: path.resolve(__dirname, './build'),
  },

  // Webpack plugins that extend webpack's functionality
  plugins: [
    // Generates HTML file and automatically injects bundled JavaScript
    new HtmlWebpackPlugin({
      template: './src/index.html',
      favicon: './favicon.ico',
    }),

    // Inject environment variables
    new webpack.DefinePlugin({
      'process.env.WEBXR_ASSETS_VERSION': JSON.stringify(WEBXR_ASSETS_VERSION),
    }),

    // Copies WebXR input profile assets when available; always copies public and favicon
    new CopyWebpackPlugin({
      patterns: [
        ...(webxrAssetsPackagePath
          ? [
              'meta-quest-touch-plus',
              'meta-quest-touch-plus-v2',
              'oculus-touch-v2',
              'oculus-touch-v3',
              'pico-4u',
              'generic-hand',
              'generic-trigger-squeeze-thumbstick',
            ].map(profile => ({
              from: path.join(path.dirname(webxrAssetsPackagePath), 'dist', 'profiles', profile),
              to: `npm/@webxr-input-profiles/assets@${WEBXR_ASSETS_VERSION}/dist/profiles/${profile}`,
            }))
          : []),
        {
          from: 'public',
          to: '.',
          globOptions: {
            ignore: ['**/index.html', ...(useLocalWebxrAssets ? [] : ['**/npm/**'])],
          },
        },
        { from: './favicon.ico', to: 'favicon.ico' },
      ],
    }),
  ],
};
