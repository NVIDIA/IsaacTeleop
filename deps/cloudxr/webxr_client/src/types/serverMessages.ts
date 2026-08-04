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
 * serverMessages.ts - Types for messages the server sends to this client.
 *
 * These travel over the `teleop_command` CloudXR MessageChannel, the same
 * channel this client uses to send teleop commands the other way. Every message
 * is UTF-8 JSON carrying a `type` discriminator.
 *
 * Unknown `type` values must be ignored rather than treated as errors: the
 * server and client are versioned independently, so a newer host may send message
 * kinds this client does not know about.
 */

/** One unmet workstation requirement reported by the host. */
export interface SystemNoticeItem {
  /** Requirement name, e.g. `"CPU governor"`. */
  name: string;
  /** The measured value on the host, e.g. `"powersave"`. */
  actual: string;
  /** The threshold that was not met, e.g. `"performance"`. */
  required: string;
  /** Optional actionable hint, e.g. a command that resolves the item. */
  detail?: string;
}

/**
 * Advisory from the host that its workstation is below the recommended spec
 * for teleoperation. Informational only -- the session still runs.
 */
export interface SystemNotice {
  level: 'warning' | 'info';
  title: string;
  summary: string;
  items: SystemNoticeItem[];
  /** Link to the documented requirements. */
  doc_url?: string;
}

/** A `system_notice` message as it appears on the wire. */
export interface SystemNoticeMessage {
  type: 'system_notice';
  message: SystemNotice;
}

/** Narrow an unknown value to a {@link SystemNoticeItem}. */
function isSystemNoticeItem(value: unknown): value is SystemNoticeItem {
  if (typeof value !== 'object' || value === null) return false;
  const item = value as Record<string, unknown>;
  return (
    typeof item.name === 'string' &&
    typeof item.actual === 'string' &&
    typeof item.required === 'string' &&
    (item.detail === undefined || typeof item.detail === 'string')
  );
}

/**
 * Narrow an arbitrary parsed payload to a {@link SystemNoticeMessage}.
 *
 * Every field is validated, not just the shape of the envelope. This runs on
 * data straight off the wire, and an accepted notice is dereferenced field by
 * field while rendering the XR panel -- so a payload with, say, `items: [null]`
 * or a non-string title would throw inside the render loop rather than being
 * rejected here. Anything that does not match is ignored like an unknown
 * message type: the session keeps running without the notice.
 */
export function isSystemNoticeMessage(value: unknown): value is SystemNoticeMessage {
  if (typeof value !== 'object' || value === null) return false;
  const candidate = value as { type?: unknown; message?: unknown };
  if (candidate.type !== 'system_notice') return false;

  const body = candidate.message;
  if (typeof body !== 'object' || body === null) return false;
  const notice = body as Record<string, unknown>;

  return (
    (notice.level === 'warning' || notice.level === 'info') &&
    typeof notice.title === 'string' &&
    typeof notice.summary === 'string' &&
    Array.isArray(notice.items) &&
    notice.items.every(isSystemNoticeItem) &&
    (notice.doc_url === undefined || typeof notice.doc_url === 'string')
  );
}

/**
 * Render everything below the title: the summary, one line per unmet
 * requirement, each item's remediation hint, and the documentation link.
 *
 * Shared by both display surfaces. The XR panel styles the title separately
 * from the body, so it needs the body on its own; the 2D banner appends this
 * to the title via {@link formatSystemNotice}. Keeping one formatter is what
 * stops the two surfaces from drifting -- the in-headset banner is the primary
 * display, so it must not be the one missing the actionable hint.
 *
 * Bullets are plain ASCII on purpose: the XR text is rendered from an MSDF
 * font atlas with no guaranteed glyph coverage for characters like `•`.
 */
export function formatSystemNoticeBody(notice: SystemNotice): string {
  const lines = [notice.summary];
  for (const item of notice.items) {
    lines.push(`- ${item.name}: ${item.actual} (need ${item.required})`);
    if (item.detail) lines.push(`   ${item.detail}`);
  }
  if (notice.doc_url) lines.push(notice.doc_url);
  return lines.join('\n');
}

/**
 * Render a notice as plain text for the 2D status banner.
 *
 * The banner sets `textContent`, so this uses newlines rather than markup; the
 * `.error-message-box` style declares `white-space: pre-line` to preserve them.
 */
export function formatSystemNotice(notice: SystemNotice): string {
  return `${notice.title}\n${formatSystemNoticeBody(notice)}`;
}
