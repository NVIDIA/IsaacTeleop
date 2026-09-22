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

/**
 * Standalone build for tests/mock/MockCloudXRTests - a manual/visual harness for MockCloudXR.
 *
 * Deliberately separate from webpack.common.js: the production config's chunk-splitting
 * (webpack.chunkNames.js) is tuned for exactly one entry producing bundle.js +
 * bundle.emulator.js, and this page has its own single-entry, single-chunk output in
 * build-mock/ so it can't interfere with that invariant.
 */

const path = require('path');
const HtmlWebpackPlugin = require('html-webpack-plugin');

module.exports = {
  mode: 'development',
  devtool: 'eval-source-map',
  entry: {
    mockCloudXR: './tests/mock/MockCloudXRTests.ts',
  },
  module: {
    rules: [
      {
        test: /\.tsx?$/,
        use: { loader: 'ts-loader', options: { transpileOnly: true } },
        exclude: /node_modules/,
      },
    ],
  },
  resolve: {
    extensions: ['.tsx', '.ts', '.js'],
    alias: {
      '@helpers': path.resolve(__dirname, './helpers'),
    },
  },
  output: {
    filename: 'bundle.mock.js',
    path: path.resolve(__dirname, './build-mock'),
    clean: true,
  },
  plugins: [
    new HtmlWebpackPlugin({
      filename: 'MockCloudXRTests.html',
      template: './tests/mock/MockCloudXRTests.html',
      chunks: ['mockCloudXR'],
    }),
  ],
  devServer: {
    static: { directory: path.resolve(__dirname, './build-mock') },
    // Matches webpack.dev.js: don't auto-open a browser tab on every dev-server
    // (re)start/recompile.
    open: false,
    port: 8081,
  },
};
