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
import { Container, Image } from '@react-three/uikit';
import React, { useRef, useState, useEffect } from 'react';

import { useXRButton } from './useXRButton';
import { CanvasTexture } from 'three';

/** Canvas resolution (pixels). High values keep text sharp when the texture is scaled to the display size. */
const CANVAS_WIDTH = 1320;
// Collapsed: SQ(200) + gap(14) + 5×(120+14) + gap(14) + M2M(120) = 1032px content + ~78px margins = 1110
// Expanded:  + 6×(82+8) = + 540 = 1572px content + ~88px margins = 1660
const CANVAS_HEIGHT_COLLAPSED = 1110;
const CANVAS_HEIGHT_EXPANDED  = 1660;

/** uikit slot dimensions (half the canvas resolution for a sharp 2× texture). */
const SLOT_HEIGHT_COLLAPSED = CANVAS_HEIGHT_COLLAPSED / 2; // 555
const SLOT_HEIGHT_EXPANDED  = CANVAS_HEIGHT_EXPANDED  / 2; // 830

// Hardware stage constants (ms) — fixed delays outside the software stack.
const T_INPUT_MS  = 65;   // input device → first software sample
const T_OUTPUT_MS = 100;  // last command → physical robot motion

// Layout constants (canvas space) — compact card style with label + value side-by-side.
// Displayed at METRIC_SLOT 660×(480 collapsed / 830 expanded), maintaining 0.5× scale.
const LAYOUT = {
  fontSize: 60,
  sqCardHeight: 200, // session-quality bars card — must exceed tallest bar (160px) plus 10px padding
  cardHeight: 120, // metric text cards
  cardGap: 14,
  margin: 56,
  paddingLeft: 40,
  radius: 18,
  cardFillStyle: 'rgba(0, 0, 0, 0.5)',
  labelColor: 'rgba(180, 180, 180, 1)',
} as const;

/** RGBA fill colors for each session quality level (index = quality integer 0–4). */
const SESSION_QUALITY_COLORS = [
  'rgba(120, 120, 120, 1)', // NoData — grey
  'rgba(220, 50, 50, 1)', // Unsustainable — red
  'rgba(220, 160, 30, 1)', // Degraded — amber
  'rgba(80, 200, 80, 1)', // Good — green
  'rgba(0, 255, 128, 1)', // Excellent — bright green
] as const;

/** Dim fill used for unlit bars in the session quality indicator. */
const SESSION_QUALITY_BAR_DIM = 'rgba(60, 60, 60, 0.6)';

/** Heights (px, canvas space) of the 4 quality bars, shortest to tallest. */
const SESSION_QUALITY_BAR_HEIGHTS = [50, 80, 115, 160] as const;

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

/** Props for {@link PerformanceCanvasImage}: sizing and per-frame metric/quality signals. */
export interface PerformanceCanvasImageProps {
  /** Display width of the metrics slot (uikit units). Height is managed internally. */
  width?: number;
  /** Signal for render FPS value (e.g. "72.0"). Label "Render FPS: " is drawn here. */
  renderFpsText?: ReadonlySignal<string>;
  /** Signal for pose send FPS value (e.g. "72.0"). Label "Pose Send FPS: " is drawn here. */
  poseSendFpsText?: ReadonlySignal<string>;
  /** Signal for streaming FPS value. Label "Streaming FPS: " is drawn here. */
  streamingFpsText?: ReadonlySignal<string>;
  /** Signal for pose-to-render latency (e.g. "12.3ms"). Label "Pose-to-Render: " is drawn here. */
  poseToRenderText?: ReadonlySignal<string>;
  /** Signal for total Pose-to-Pose latency (P0 + P1 + P2 + P3). */
  poseToPoseText?: ReadonlySignal<string>;
  /** Indented sub-row signals for individual pipeline stages. */
  p2pP0Text?: ReadonlySignal<string>;  // Client-to-Host
  p2pP1Text?: ReadonlySignal<string>;  // Teleop (pico_manager)
  p2pP2Text?: ReadonlySignal<string>;  // Motion Policy (ONNX + lookahead)
  p2pP3Text?: ReadonlySignal<string>;  // Robot Driver (sim / real robot)
  /** Motion-to-Motion total: t_input(65ms) + P0+P1+P2+P3 + t_output(100ms). */
  motionToMotionText?: ReadonlySignal<string>;
  /** Signal carrying live session quality (0–4); see {@link CloudXR.MetricsName.SessionQuality}. */
  sessionQuality?: ReadonlySignal<number>;
}

/**
 * Renders three performance metric lines on an offscreen canvas, uploads it to a
 * CanvasTexture, and displays it via a uikit Image. Redrawn every frame in useFrame
 * so values stay in sync without React re-renders.
 */
export function PerformanceCanvasImage({
  width = 660,
  renderFpsText,
  poseSendFpsText,
  streamingFpsText,
  poseToRenderText,
  poseToPoseText,
  p2pP0Text,
  p2pP1Text,
  p2pP2Text,
  p2pP3Text,
  motionToMotionText,
  sessionQuality,
}: PerformanceCanvasImageProps) {
  /** Tracks whether the sub-row pipeline breakdown is visible. */
  const [expanded, setExpanded] = useState(false);
  /** Mutable ref so useFrame reads the current value without waiting for React commit. */
  const expandedRef = useRef(false);
  const xrButton = useXRButton();
  const slotHeight = expanded ? SLOT_HEIGHT_EXPANDED : SLOT_HEIGHT_COLLAPSED;

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
    canvas.height = CANVAS_HEIGHT_EXPANDED; // always full size — avoid CanvasTexture resize issues
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

  /** Every frame: clear canvas, draw metric cards. Sub-rows shown only when expanded. */
  useFrame(() => {
    const canvas = canvasRef.current;
    const texture = textureRef.current;
    const ctx = ctxRef.current;
    if (!canvas || !texture || !ctx) return;

    const isExpanded = expandedRef.current;

    ctx.clearRect(0, 0, canvas.width, canvas.height);

    const {
      fontSize,
      sqCardHeight,
      cardHeight,
      cardGap,
      margin,
      paddingLeft,
      radius,
      cardFillStyle,
      labelColor,
    } = LAYOUT;

    const subRowHeight = 82;
    const subRowGap = 8;
    const subRowFontSize = 44;
    const subRowIndent = paddingLeft + 50;
    const subRowColor = 'rgba(255, 160, 200, 0.85)';
    // 6 sub-rows when expanded: 2 constant + 4 measured.
    const subRows: [string, string][] = isExpanded ? [
      ['Output Robot Latency', `${T_OUTPUT_MS}ms`],
      ['Robot Driver Latency',  p2pP3Text?.value ?? '—'],
      ['Motion Policy Latency', p2pP2Text?.value ?? '—'],
      ['Teleop Latency',        p2pP1Text?.value ?? '—'],
      ['Client-to-Host Latency', p2pP0Text?.value ?? '—'],
      ['Input Operator Latency', `${T_INPUT_MS}ms`],
    ] : [];

    // Each tuple: [label, value text, value color].
    const metrics: [string, string, string][] = [
      ['Render FPS',            renderFpsText?.value ?? '—',    'rgba(100, 255, 100, 1)'],
      ['Pose Send FPS',         poseSendFpsText?.value ?? '—',  'rgba(180, 255, 140, 1)'],
      ['Streaming FPS',         streamingFpsText?.value ?? '—', 'rgba(100, 200, 255, 1)'],
      ['Pose-to-Render Latency', poseToRenderText?.value ?? '—', 'rgba(255, 200, 100, 1)'],
      ['Pose-to-Pose Latency',  poseToPoseText?.value ?? '—',  'rgba(255, 120, 180, 1)'],
    ];

    // Center content within the VISIBLE portion of the canvas.
    // Canvas is always CANVAS_HEIGHT_EXPANDED (1660px); the Container clips it to
    // CANVAS_HEIGHT_COLLAPSED (1110px) when collapsed via overflow="hidden".
    const visibleH = isExpanded ? CANVAS_HEIGHT_EXPANDED : CANVAS_HEIGHT_COLLAPSED;
    const totalHeight =
      sqCardHeight + cardGap +
      metrics.length * (cardHeight + cardGap) +
      subRows.length * (subRowHeight + subRowGap) +
      cardGap + cardHeight; // M2M card always visible
    let cardY = (visibleH - totalHeight) / 2;

    ctx.font = `bold ${fontSize}px system-ui, sans-serif`;
    ctx.textBaseline = 'middle';

    // Session Quality card.
    const qualityLevel = Math.max(
      0,
      Math.min(SESSION_QUALITY_COLORS.length - 1, Math.round(sessionQuality?.value ?? 0))
    );
    const qualityColor = SESSION_QUALITY_COLORS[qualityLevel];
    ctx.fillStyle = cardFillStyle;
    drawRoundRect(ctx, margin, cardY, CARD_WIDTH, sqCardHeight, radius);
    ctx.fill();

    const numBars = SESSION_QUALITY_BAR_HEIGHTS.length;
    const barWidth = 130;
    const barGap = 70;
    const barsTotal = numBars * barWidth + (numBars - 1) * barGap;
    const barBaseX = margin + (CARD_WIDTH - barsTotal) / 2;
    const barBottomY = cardY + sqCardHeight - 10;
    for (let i = 0; i < numBars; i++) {
      const barH = SESSION_QUALITY_BAR_HEIGHTS[i];
      const barX = barBaseX + i * (barWidth + barGap);
      ctx.fillStyle = qualityLevel > 0 && i < qualityLevel ? qualityColor : SESSION_QUALITY_BAR_DIM;
      drawRoundRect(ctx, barX, barBottomY - barH, barWidth, barH, 8);
      ctx.fill();
    }
    cardY += sqCardHeight + cardGap;

    // Metric cards.
    const centerY = cardHeight / 2;
    for (const [label, value, valueColor] of metrics) {
      ctx.fillStyle = cardFillStyle;
      drawRoundRect(ctx, margin, cardY, CARD_WIDTH, cardHeight, radius);
      ctx.fill();

      const textY = cardY + centerY;
      ctx.textAlign = 'left';
      ctx.fillStyle = labelColor;

      // On the Pose-to-Pose card draw the expand/collapse indicator at the far right.
      if (label === 'Pose-to-Pose Latency') {
        const indicator = isExpanded ? '▼' : '▶';
        ctx.textAlign = 'right';
        ctx.fillStyle = 'rgba(180, 180, 180, 0.7)';
        ctx.fillText(indicator, margin + CARD_WIDTH - paddingLeft, textY);
        ctx.textAlign = 'left';
        ctx.fillStyle = labelColor;
      }

      ctx.fillText(label, margin + paddingLeft, textY);
      const labelWidth = ctx.measureText(label).width;
      ctx.fillStyle = valueColor;
      ctx.fillText('  ' + value, margin + paddingLeft + labelWidth, textY);

      cardY += cardHeight + cardGap;
    }

    // Sub-rows (only when expanded).
    if (isExpanded) {
      ctx.font = `${subRowFontSize}px system-ui, sans-serif`;
      const subCenterY = subRowHeight / 2;
      for (const [label, value] of subRows) {
        ctx.fillStyle = cardFillStyle;
        drawRoundRect(ctx, margin + 40, cardY, CARD_WIDTH - 40, subRowHeight, radius);
        ctx.fill();

        const textY = cardY + subCenterY;
        ctx.textAlign = 'left';
        ctx.fillStyle = labelColor;
        ctx.fillText(label, margin + subRowIndent, textY);
        const labelWidth = ctx.measureText(label).width;
        ctx.fillStyle = subRowColor;
        ctx.fillText('  ' + value, margin + subRowIndent + labelWidth, textY);

        cardY += subRowHeight + subRowGap;
      }
    }

    // Motion-to-Motion card (always visible).
    cardY += cardGap;
    ctx.font = `bold ${fontSize}px system-ui, sans-serif`;
    ctx.fillStyle = cardFillStyle;
    drawRoundRect(ctx, margin, cardY, CARD_WIDTH, cardHeight, radius);
    ctx.fill();
    const m2mLabel = 'Motion-to-Motion Latency';
    const m2mValue = motionToMotionText?.value ?? '—';
    const m2mCenterY = cardY + cardHeight / 2;
    ctx.textAlign = 'left';
    ctx.fillStyle = labelColor;
    ctx.fillText(m2mLabel, margin + paddingLeft, m2mCenterY);
    const m2mLabelWidth = ctx.measureText(m2mLabel).width;
    ctx.fillStyle = 'rgba(255, 220, 80, 1)';
    ctx.fillText('  ' + m2mValue, margin + paddingLeft + m2mLabelWidth, m2mCenterY);

    texture.needsUpdate = true;
  });

  const toggleExpanded = () => {
    const next = !expandedRef.current;
    expandedRef.current = next;
    setExpanded(next);
  };

  return (
    <Container width={width} height={slotHeight} overflow="hidden" alignItems="center" justifyContent="center">
      {/* Events go on the Image directly — it is the mesh that receives VR ray hits.
          A separate overlay Button would sit behind the Image in 3D and never get the ray. */}
      <Image
        ref={imageRef}
        width={width}
        height={SLOT_HEIGHT_EXPANDED}
        objectFit="fill"
        keepAspectRatio={false}
        {...xrButton('perf-expand', toggleExpanded)}
      />
    </Container>
  );
}
