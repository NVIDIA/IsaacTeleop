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
 * Console diagnostics: WebXR at startup (no session) and when an immersive session starts.
 */

/** Lines describing the live XRSession (authoritative mode vs @react-three/xr store). */
export function dumpXRSessionDetails(
  session: XRSession | null | undefined,
  xrStoreMode?: string
): string[] {
  if (session == null) {
    return ['XRSession: null'];
  }

  const lines: string[] = [];
  const extended = session as XRSession & {
    mode?: XRSessionMode;
    interactionMode?: string;
  };

  if (xrStoreMode != null) {
    lines.push(`@react-three/xr store mode: ${xrStoreMode}`);
  }

  const apiMode = extended.mode;
  if (apiMode != null) {
    lines.push(`session.mode (WebXR): ${apiMode}`);
    if (apiMode === 'immersive-vr') {
      lines.push('  → WebXR reports immersive-vr (VR / opaque headset environment).');
    } else if (apiMode === 'immersive-ar') {
      lines.push('  → WebXR reports immersive-ar (passthrough / camera-backed).');
    }
    if (xrStoreMode != null && xrStoreMode !== apiMode) {
      lines.push(
        `  WARNING: store mode and session.mode differ — trust session.mode for what the browser is running.`
      );
    }
  } else {
    lines.push('session.mode (WebXR): — (missing on this UA; infer from store / blend mode)');
  }

  lines.push(`session.environmentBlendMode: ${session.environmentBlendMode}`);
  if (extended.interactionMode != null) {
    lines.push(`session.interactionMode: ${extended.interactionMode}`);
  }

  const feats = session.enabledFeatures ?? [];
  lines.push(`session.enabledFeatures [${feats.length}]: ${feats.map(String).join(', ') || '(none)'}`);

  const rs = session.renderState;
  lines.push(`session.renderState.depthNear: ${rs.depthNear}`);
  lines.push(`session.renderState.depthFar: ${rs.depthFar}`);
  const iFoV = rs.inlineVerticalFieldOfView;
  lines.push(
    `session.renderState.inlineVerticalFieldOfView: ${iFoV != null ? String(iFoV) : '—'}`
  );

  const base = rs.baseLayer;
  if (base == null) {
    lines.push('session.renderState.baseLayer: null');
  } else if ('framebufferWidth' in base && 'framebufferHeight' in base) {
    const layer = base as XRWebGLLayer;
    lines.push(
      `session.renderState.baseLayer: XRWebGLLayer ${layer.framebufferWidth}x${layer.framebufferHeight}px`
    );
    lines.push(`  antialias: ${layer.antialias}`);
    if ('ignoreDepthValues' in layer) {
      lines.push(`  ignoreDepthValues: ${layer.ignoreDepthValues}`);
    }
  } else {
    const tag =
      base != null && typeof base === 'object' && 'constructor' in base
        ? (base as { constructor?: { name?: string } }).constructor?.name
        : undefined;
    lines.push(`session.renderState.baseLayer: ${tag ?? typeof base}`);
  }

  lines.push(`session (object): ${session.constructor?.name ?? 'XRSession'}`);

  return lines;
}

/** Call when an immersive session begins — confirms VR vs AR from the WebXR session object. */
export function logImmersiveXRSessionToConsole(
  session: XRSession | null | undefined,
  xrStoreMode: string
): void {
  console.groupCollapsed(`[Isaac Teleop] WebXR session (entered immersive: ${xrStoreMode})`);
  console.info(dumpXRSessionDetails(session, xrStoreMode).join('\n'));
  console.groupEnd();
}
