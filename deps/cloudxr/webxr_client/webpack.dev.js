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

const { merge } = require('webpack-merge');
const common = require('./webpack.common.js');
const path = require('path');

// Check if HTTPS mode is enabled via environment variable
const useHttps = process.env.HTTPS === 'true';

module.exports = merge(common, {
  mode: 'development',
  devtool: 'eval-source-map',
  devServer: {
    allowedHosts: 'all',
    hot: true,
    open: false,
    // Enable HTTPS with self-signed certificate when HTTPS=true
    ...(useHttps && { server: 'https' }),
    static: [
      {
        directory: path.join(__dirname, './build'),
      },
      {
        directory: path.join(__dirname, './public'),
        publicPath: '/',
      },
    ],
    watchFiles: {
      paths: ['src/**/*', '../../build/**/*'],
      options: {
        usePolling: false,
        ignored: /node_modules/,
      },
    },
    client: {
      progress: true,
      overlay: {
        errors: true,
        warnings: false,
      },
    },
    devMiddleware: {
      writeToDisk: true,
    },
    compress: true,
    port: 8080,
  },
});
