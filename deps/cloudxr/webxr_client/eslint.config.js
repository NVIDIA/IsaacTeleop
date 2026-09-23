/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */
// Minimal ESLint flat config derived from /gitlab/cloudxr-js (examples / React client rules).
// Use CommonJS so Node can load without ESM; paths are relative to this package root.
const typescriptEslint = require('@typescript-eslint/eslint-plugin');
const typescriptParser = require('@typescript-eslint/parser');
const reactPlugin = require('eslint-plugin-react');
const reactHooksPlugin = require('eslint-plugin-react-hooks');
const simpleImportSort = require('eslint-plugin-simple-import-sort');

module.exports = [
  {
    linterOptions: {
      reportUnusedDisableDirectives: true,
    },
  },
  {
    ignores: ['node_modules/**', 'build/**', 'dist/**'],
  },
  {
    files: ['src/**/*.{ts,tsx}', 'helpers/**/*.{ts,tsx}', 'tests/**/*.{ts,tsx}'],
    languageOptions: {
      parser: typescriptParser,
      parserOptions: {
        ecmaVersion: 2020,
        sourceType: 'module',
        ecmaFeatures: {
          jsx: true,
        },
      },
    },
    plugins: {
      '@typescript-eslint': typescriptEslint,
      react: reactPlugin,
      'react-hooks': reactHooksPlugin,
      'simple-import-sort': simpleImportSort,
    },
    rules: {
      '@typescript-eslint/explicit-module-boundary-types': 'off',
      '@typescript-eslint/no-explicit-any': 'warn',
      '@typescript-eslint/no-unused-vars': [
        'warn',
        {
          argsIgnorePattern: '^_',
          varsIgnorePattern: '^_',
        },
      ],
      'react/react-in-jsx-scope': 'off',
      'react/prop-types': 'off',
      'react/jsx-uses-react': 'off',
      'react/jsx-uses-vars': 'error',
      'react-hooks/rules-of-hooks': 'error',
      'react-hooks/exhaustive-deps': 'warn',
      'no-console': ['warn', { allow: ['info', 'warn', 'error', 'debug'] }],
      // `import/order` from eslint-plugin-import does not reliably --fix
      // "empty line within import group" (see App.tsx + @helpers + TeleopProjects).
      // simple-import-sort rewrites the block and fixes that on `eslint --fix`.
      'simple-import-sort/imports': [
        'error',
        {
          groups: [
            // Side effect imports
            ['^\\u0000'],
            // `node:`
            ['^node:'],
            // External: not `../` and not the `@helpers/` alias
            ['^(?!\\.|@helpers/)'],
            // Internal alias
            ['^@helpers/'],
            // Relative
            ['^\\.'],
          ],
        },
      ],
      'simple-import-sort/exports': 'error',
    },
    settings: {
      react: {
        version: 'detect',
      },
    },
  },
  {
    // The production build (webpack.common.js entry is src/index.tsx) never resolves anything
    // under tests/ - nothing there is reachable from that entry point, and only
    // webpack.app-mock.js/webpack.mock.js (never build/dev/dev-server) alias '@nvidia/cloudxr' to
    // mock code. This rule makes that a hard, enforced guarantee rather than a coincidence: if
    // src/ or helpers/ ever grows a real import of tests/, that's a mistake, not a valid pattern
    // to lint around.
    files: ['src/**/*.{ts,tsx}', 'helpers/**/*.{ts,tsx}'],
    rules: {
      'no-restricted-imports': [
        'error',
        {
          patterns: [
            {
              group: ['**/tests/**'],
              message:
                'src/ and helpers/ ship in the production bundle and must never import test-only code under tests/.',
            },
          ],
        },
      ],
    },
  },
];
