const path = require('path');
const HtmlWebpackPlugin = require('html-webpack-plugin');
const CopyWebpackPlugin = require('copy-webpack-plugin');
const webpack = require('webpack');

const webxrAssetsPackagePath = require.resolve('@webxr-input-profiles/assets/package.json');
const webxrAssetsPackage = require(webxrAssetsPackagePath);
const WEBXR_ASSETS_VERSION = webxrAssetsPackage.version;

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
      '@helpers': path.resolve(__dirname, 'helpers'),
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

    // Copies static assets from public directory to build output
    new CopyWebpackPlugin({
      patterns: [
        {
          from: path.join(path.dirname(webxrAssetsPackagePath), 'dist', 'profiles'),
          to: `npm/@webxr-input-profiles/assets@${WEBXR_ASSETS_VERSION}/dist/profiles`,
        },
        {
          from: 'public',
          to: '.',
          globOptions: {
            // Don't copy index.html since HtmlWebpackPlugin handles it
            ignore: ['**/index.html'],
          },
        },
        { from: './favicon.ico', to: 'favicon.ico' },
      ],
    }),
  ],
};
