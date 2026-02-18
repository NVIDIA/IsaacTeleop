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
 * Override PressureObserver to catch errors from unexpected browser implementations.
 *
 * Some browsers have buggy PressureObserver implementations that throw errors
 * when observe() is called. This wrapper catches and logs those errors instead
 * of letting them propagate.
 *
 * This should be called early in your application, before any code attempts
 * to use PressureObserver.
 */
export function overridePressureObserver(): void {
  if (typeof window === 'undefined' || !(window as any).PressureObserver) {
    return;
  }

  const OriginalPressureObserver = (window as any).PressureObserver;

  (window as any).PressureObserver = class PressureObserver extends OriginalPressureObserver {
    observe(source: any) {
      try {
        const result = super.observe(source);
        if (result && typeof result.catch === 'function') {
          return result.catch((e: Error) => {
            console.warn('PressureObserver.observe() failed:', e.message);
            return undefined;
          });
        }
        return result;
      } catch (e: any) {
        console.warn('PressureObserver.observe() failed:', e.message);
        return undefined;
      }
    }
  };
}
