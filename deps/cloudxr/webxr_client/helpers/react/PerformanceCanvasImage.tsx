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
 * PerformanceCanvasImage - Canvas-backed performance metrics display.
 *
 * Renders Render FPS, Streaming FPS, and Pose-to-Render in a single canvas texture
 * with rounded rectangles per line. Used as a uikit Image for efficient per-frame
 * updates without triggering layout.
 *
 * Why canvas + texture instead of uikit Text?
 * - Updating uikit Text from signals can trigger layout recalculations every frame.
 * - Drawing to a canvas and setting texture.needsUpdate = true updates the image
 *   without affecting the rest of the UI tree.
 *
 * The texture is assigned to the Image via ref (imageRef.current.texture.value), not
 * the `src` prop, because the uikit bridge would stringify a Texture object and
 * cause a 404 if passed as src.
 */

import { ReadonlySignal } from '@preact/signals-react';
import { useFrame } from '@react-three/fiber';
import { Image } from '@react-three/uikit';
import React, { useRef, useState, useEffect } from 'react';
import { CanvasTexture } from 'three';

/** Canvas resolution (pixels). High values keep text sharp when the texture is scaled to the display size. */
const CANVAS_WIDTH = 1024;
const CANVAS_HEIGHT = 500;

// Layout constants (canvas space) — compact card style with label + value side-by-side.
const LAYOUT = {
  fontSize: 56,
  cardHeight: 130,
  cardGap: 18,
  numCards: 3,
  margin: 32,
  paddingLeft: 40,
  radius: 18,
  cardFillStyle: 'rgba(0, 0, 0, 0.5)',
  labelColor: 'rgba(180, 180, 180, 1)',
} as const;

const CARD_WIDTH = CANVAS_WIDTH - LAYOUT.margin * 2;

/** Draw a rounded rectangle path; caller must ctx.fill() or ctx.stroke() after. */
function drawRoundRect(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  w: number,
  h: number,
  r: number
): void {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.lineTo(x + w - r, y);
  ctx.quadraticCurveTo(x + w, y, x + w, y + r);
  ctx.lineTo(x + w, y + h - r);
  ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
  ctx.lineTo(x + r, y + h);
  ctx.quadraticCurveTo(x, y + h, x, y + h - r);
  ctx.lineTo(x, y + r);
  ctx.quadraticCurveTo(x, y, x + r, y);
  ctx.closePath();
}

export interface PerformanceCanvasImageProps {
  /** Display width of the metrics image (uikit units). */
  width?: number;
  /** Display height of the metrics image (uikit units). */
  height?: number;
  /** Signal for render FPS value (e.g. "72.0"). Label "Render FPS: " is drawn here. */
  renderFpsText?: ReadonlySignal<string>;
  /** Signal for streaming FPS value. Label "Streaming FPS: " is drawn here. */
  streamingFpsText?: ReadonlySignal<string>;
  /** Signal for pose-to-render latency (e.g. "12.3ms"). Label "Pose-to-Render: " is drawn here. */
  poseToRenderText?: ReadonlySignal<string>;
}

/**
 * Renders three performance metric lines on an offscreen canvas, uploads it to a
 * CanvasTexture, and displays it via a uikit Image. Redrawn every frame in useFrame
 * so values stay in sync without React re-renders.
 */
export function PerformanceCanvasImage({
  width = 512,
  height = 512,
  renderFpsText,
  streamingFpsText,
  poseToRenderText,
}: PerformanceCanvasImageProps) {
  /** Ref for the uikit Image; we set .texture.value on it to use our CanvasTexture. */
  const imageRef = useRef<{ texture: { value: CanvasTexture | undefined } } | null>(null);
  /** Offscreen canvas we draw into each frame. */
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  /** Cached 2D context for the canvas (avoids getContext('2d') every frame). */
  const ctxRef = useRef<CanvasRenderingContext2D | null>(null);
  /** Three.js texture wrapping the canvas; needsUpdate = true each frame after drawing. */
  const textureRef = useRef<CanvasTexture | null>(null);
  const [textureReady, setTextureReady] = useState(false);

  /** Create the offscreen canvas and CanvasTexture once on mount; dispose on unmount. */
  useEffect(() => {
    const canvas = document.createElement('canvas');
    canvas.width = CANVAS_WIDTH;
    canvas.height = CANVAS_HEIGHT;
    canvasRef.current = canvas;
    ctxRef.current = canvas.getContext('2d');
    const tex = new CanvasTexture(canvas);
    tex.matrixAutoUpdate = false;
    textureRef.current = tex;
    setTextureReady(true);
    return () => {
      tex.dispose();
      textureRef.current = null;
      canvasRef.current = null;
      ctxRef.current = null;
      setTextureReady(false);
    };
  }, []);

  /** Assign our texture to the uikit Image via ref (avoids src stringification). */
  useEffect(() => {
    if (!textureReady || !textureRef.current || !imageRef.current) return;
    const img = imageRef.current;
    img.texture.value = textureRef.current;
    return () => {
      if (img) img.texture.value = undefined;
    };
  }, [textureReady]);

  /** Every frame: clear canvas, draw three vertically-stacked metric cards. */
  useFrame(() => {
    const canvas = canvasRef.current;
    const texture = textureRef.current;
    const ctx = ctxRef.current;
    if (!canvas || !texture || !ctx) return;
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    const {
      fontSize,
      cardHeight,
      cardGap,
      numCards,
      margin,
      paddingLeft,
      radius,
      cardFillStyle,
      labelColor,
    } = LAYOUT;
    // Vertically center the stack of cards within the canvas.
    const totalHeight = numCards * cardHeight + (numCards - 1) * cardGap;
    let cardY = (canvas.height - totalHeight) / 2;

    // Each tuple: [label, current signal value (or em-dash fallback), value color].
    const metrics: [string, string, string][] = [
      ['Render FPS', renderFpsText?.value ?? '—', 'rgba(100, 255, 100, 1)'],
      ['Streaming FPS', streamingFpsText?.value ?? '—', 'rgba(100, 200, 255, 1)'],
      ['Pose-to-Render', poseToRenderText?.value ?? '—', 'rgba(255, 200, 100, 1)'],
    ];

    ctx.font = `bold ${fontSize}px system-ui, sans-serif`;
    ctx.textBaseline = 'middle';
    // Offset to vertically center text within each card.
    const centerY = cardHeight / 2;

    for (const [label, value, valueColor] of metrics) {
      // Draw the rounded card background.
      ctx.fillStyle = cardFillStyle;
      drawRoundRect(ctx, margin, cardY, CARD_WIDTH, cardHeight, radius);
      ctx.fill();

      const textY = cardY + centerY;

      // Draw the grey label (e.g. "Render FPS") on the left side of the card.
      ctx.textAlign = 'left';
      ctx.fillStyle = labelColor;
      ctx.fillText(label, margin + paddingLeft, textY);

      // Draw the colored value immediately after the label, with a small gap.
      const labelWidth = ctx.measureText(label).width;
      ctx.fillStyle = valueColor;
      ctx.fillText('  ' + value, margin + paddingLeft + labelWidth, textY);

      // Advance to the next card position.
      cardY += cardHeight + cardGap;
    }

    texture.needsUpdate = true;
  });

  /** Single uikit Image; texture is set via ref, width/height from props. */
  return (
    <Image ref={imageRef} width={width} height={height} objectFit="fill" keepAspectRatio={false} />
  );
}
