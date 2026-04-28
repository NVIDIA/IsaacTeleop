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
 * When `headless` is true, no-ops only the per-frame `WebGLRenderer.render` on the R3F-owned
 * renderer. That is the main per-frame WebGL path for the scene (and WebXR submit in that call).
 * Startup and one-time GL (context init, `createSession`, uploads, etc.) are not touched.
 *
 * R3F still advances the frame so `useFrame` can use `getFrame()` and `sendTrackingStateToServer`.
 * Does not modify @react-three/fiber source.
 */
import { useThree } from '@react-three/fiber';
import { useEffect, useRef } from 'react';
import type { WebGLRenderer } from 'three';

export function SuppressWebGLRendererWhenHeadless({ headless }: { headless: boolean }) {
  const gl = useThree(s => s.gl) as WebGLRenderer;
  const origRender = useRef<WebGLRenderer['render'] | null>(null);

  useEffect(() => {
    if (headless) {
      if (!origRender.current) {
        origRender.current = gl.render.bind(gl) as WebGLRenderer['render'];
      }
      const noop: WebGLRenderer['render'] = () => {};
      gl.render = noop;
      return () => {
        if (origRender.current) {
          gl.render = origRender.current;
        }
      };
    }
    if (origRender.current) {
      gl.render = origRender.current;
    }
    return undefined;
  }, [headless, gl]);

  return null;
}
