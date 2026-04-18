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
  // New script URL every build so browser cannot serve cached bundle
  output: {
    filename: 'bundle.[contenthash:8].js',
    clean: true,
  },
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
      // Derive HMR socket URL from window.location so it works behind the
      // docker-compose TLS proxy (https://<host>:8443) as well as directly
      // (http://<host>:8080). Sentinels per webpack-dev-server:
      //   hostname '0.0.0.0' -> window.location.hostname
      //   port     0         -> window.location.port
      //   protocol 'auto'    -> ws for http, wss for https
      webSocketURL: {
        hostname: '0.0.0.0',
        port: 0,
        protocol: 'auto',
        pathname: '/ws',
      },
    },
    devMiddleware: {
      writeToDisk: true,
    },
    compress: true,
    port: 8080,
  },
});
