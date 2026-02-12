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
    },
    devMiddleware: {
      writeToDisk: true,
    },
    compress: true,
    port: 8080,
  },
});
