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

import {
  WebGLState,
  WebGLBufferState,
  WebGLTextureState,
  WebGLTextureUnitState,
  WebGLProgramState,
  WebGLFramebufferState,
  WebGLVertexArrayState,
  WebGLVertexAttribState,
  WebGLCapabilityState,
  WebGLViewportState,
  WebGLClearState,
  WebGLBlendState,
  WebGLDepthState,
  WebGLStencilState,
  WebGLColorState,
  WebGLCullingState,
  WebGLLineState,
  WebGLPolygonOffsetState,
  WebGLSampleState,
  WebGLPixelStoreState,
  WebGLTransformFeedbackState,
  WebGLRenderbufferState,
  WebGLSamplerState,
  WebGLQueryState,
  WebGLIndexedBufferBinding,
  GL_MAX_VERTEX_ATTRIBS,
  GL_MAX_UNIFORM_BUFFER_BINDINGS,
  GL_MAX_TRANSFORM_FEEDBACK_SEPARATE_ATTRIBS,
  GL_MAX_COMBINED_TEXTURE_IMAGE_UNITS,
  GL_MAX_COLOR_ATTACHMENTS,
  GLUndefined,
  isDefined,
} from './WebGLState';

/**
 * Global flag to enable WebGL error checking after each state operation.
 * Set to true for debugging to catch GL errors immediately after they occur.
 * Default: false
 */
export let CHECK_ERRORS = false;

/**
 * Helper function to check if a property is defined on a state object,
 * handling the case where the state object itself might be undefined
 */
function isPropertyDefined<T>(state: T | undefined, prop: keyof T): boolean {
  return state !== undefined && isDefined((state as any)[prop]);
}

/**
 * Helper function to determine if state should be applied based on saved vs current state.
 * Returns true if the states differ or if one is undefined and the other is not.
 *
 * @param saved - The saved/desired state (may be undefined to reset to defaults)
 * @param current - The current state (may be undefined if not tracked)
 * @returns true if the state should be applied, false if no change needed
 */
function shouldApplyState<T extends { equals(other: T): boolean }>(
  saved: T | undefined,
  current: T | undefined
): boolean {
  // Both undefined - no change needed
  if (saved === undefined && current === undefined) {
    return false;
  }

  // One is undefined and the other isn't - need to apply/reset
  if (saved === undefined || current === undefined) {
    return true;
  }

  // Both defined - check if they're different using equals()
  return !saved.equals(current);
}

/**
 * Helper function to check and log WebGL errors after state application
 * @param gl - The WebGL2RenderingContext to check
 * @param stepName - Name of the state application step for logging
 */
function checkGLError(gl: WebGL2RenderingContext, stepName: string): void {
  if (!CHECK_ERRORS) return;

  const error = gl.getError();
  if (error !== gl.NO_ERROR) {
    const errorName = getGLErrorName(gl, error);
    const message = `[WebGLStateApply] GL error after ${stepName}: ${errorName} (0x${error.toString(16)})`;

    throw new Error(message);
  }
}

/**
 * Get human-readable name for a WebGL error code
 */
function getGLErrorName(gl: WebGL2RenderingContext, error: number): string {
  switch (error) {
    case gl.INVALID_ENUM:
      return 'INVALID_ENUM';
    case gl.INVALID_VALUE:
      return 'INVALID_VALUE';
    case gl.INVALID_OPERATION:
      return 'INVALID_OPERATION';
    case gl.INVALID_FRAMEBUFFER_OPERATION:
      return 'INVALID_FRAMEBUFFER_OPERATION';
    case gl.OUT_OF_MEMORY:
      return 'OUT_OF_MEMORY';
    case gl.CONTEXT_LOST_WEBGL:
      return 'CONTEXT_LOST_WEBGL';
    default:
      return 'UNKNOWN_ERROR';
  }
}

/**
 * Apply all defined state from a WebGLState object to a WebGL context
 * @param gl - The WebGL2RenderingContext to apply state to
 * @param state - The WebGLState object containing tracked state
 * @param current - The current WebGLState for comparison
 */
export function apply(gl: WebGL2RenderingContext, state: WebGLState, current: WebGLState): void {
  // Apply state in a specific order to handle dependencies

  // 2. Vertex Array Object binding (this may temporarily change ARRAY_BUFFER)
  if (shouldApplyState(state.vertexArrays, current.vertexArrays)) {
    applyVertexArrayState(gl, state.vertexArrays, current.vertexArrays);
    checkGLError(gl, 'vertex array state');
  }

  // 1. Buffer bindings (needed before VAO state)
  if (shouldApplyState(state.buffers, current.buffers)) {
    applyBufferState(gl, state.buffers, current.buffers, state.validBuffers);
    checkGLError(gl, 'buffer state');
  }

  // 4. Texture bindings
  if (shouldApplyState(state.textures, current.textures)) {
    applyTextureState(gl, state.textures, current.textures);
    checkGLError(gl, 'texture state');
  }

  // 5. Sampler bindings
  if (shouldApplyState(state.samplers, current.samplers)) {
    applySamplerState(gl, state.samplers, current.samplers);
    checkGLError(gl, 'sampler state');
  }

  // 6. Program binding
  if (shouldApplyState(state.programs, current.programs)) {
    applyProgramState(gl, state.programs, current.programs);
    checkGLError(gl, 'program state');
  }

  // 7. Framebuffer bindings and attachments
  if (shouldApplyState(state.framebuffers, current.framebuffers)) {
    applyFramebufferState(gl, state.framebuffers, current.framebuffers);
    checkGLError(gl, 'framebuffer state');
  }

  // 8. Renderbuffer binding
  if (shouldApplyState(state.renderbuffer, current.renderbuffer)) {
    applyRenderbufferState(gl, state.renderbuffer, current.renderbuffer);
    checkGLError(gl, 'renderbuffer state');
  }

  // 9. Transform feedback
  if (shouldApplyState(state.transformFeedback, current.transformFeedback)) {
    applyTransformFeedbackState(gl, state.transformFeedback, current.transformFeedback);
    checkGLError(gl, 'transform feedback state');
  }

  // 10. Viewport and scissor
  if (shouldApplyState(state.viewport, current.viewport)) {
    applyViewportState(gl, state.viewport, current.viewport);
    checkGLError(gl, 'viewport state');
  }

  // 11. Capabilities (enable/disable)
  if (shouldApplyState(state.capabilities, current.capabilities)) {
    applyCapabilityState(gl, state.capabilities, current.capabilities);
    checkGLError(gl, 'capability state');
  }

  // 12. Clear values
  if (shouldApplyState(state.clear, current.clear)) {
    applyClearState(gl, state.clear, current.clear);
    checkGLError(gl, 'clear state');
  }

  // 13. Blend state
  if (shouldApplyState(state.blend, current.blend)) {
    applyBlendState(gl, state.blend, current.blend);
    checkGLError(gl, 'blend state');
  }

  // 14. Depth state
  if (shouldApplyState(state.depth, current.depth)) {
    applyDepthState(gl, state.depth, current.depth);
    checkGLError(gl, 'depth state');
  }

  // 15. Stencil state
  if (shouldApplyState(state.stencil, current.stencil)) {
    applyStencilState(gl, state.stencil, current.stencil);
    checkGLError(gl, 'stencil state');
  }

  // 16. Color write mask
  if (shouldApplyState(state.color, current.color)) {
    applyColorState(gl, state.color, current.color);
    checkGLError(gl, 'color state');
  }

  // 17. Culling state
  if (shouldApplyState(state.culling, current.culling)) {
    applyCullingState(gl, state.culling, current.culling);
    checkGLError(gl, 'culling state');
  }

  // 18. Line width
  if (shouldApplyState(state.line, current.line)) {
    applyLineState(gl, state.line, current.line);
    checkGLError(gl, 'line state');
  }

  // 19. Polygon offset
  if (shouldApplyState(state.polygonOffset, current.polygonOffset)) {
    applyPolygonOffsetState(gl, state.polygonOffset, current.polygonOffset);
    checkGLError(gl, 'polygon offset state');
  }

  // 20. Sample coverage
  if (shouldApplyState(state.sample, current.sample)) {
    applySampleState(gl, state.sample, current.sample);
    checkGLError(gl, 'sample state');
  }

  // 21. Pixel store parameters
  if (shouldApplyState(state.pixelStore, current.pixelStore)) {
    applyPixelStoreState(gl, state.pixelStore, current.pixelStore);
    checkGLError(gl, 'pixel store state');
  }

  // 22. Query objects
  if (state.queries && (!current.queries || !state.queries.equals(current.queries))) {
    applyQueryState(gl, state.queries);
    checkGLError(gl, 'query state');
  }
}

/**
 * Apply buffer binding state
 */
function applyBufferState(
  gl: WebGL2RenderingContext,
  buffers: WebGLBufferState | undefined,
  current: WebGLBufferState | undefined,
  validBuffers: Set<WebGLBuffer>
): void {
  // Helper to validate a buffer
  const validateBuffer = (buffer: WebGLBuffer | null, bufferName: string): boolean => {
    if (!buffer) return true;

    if (!validBuffers.has(buffer)) {
      console.warn(
        `[WebGLStateApply] Cannot bind ${bufferName}: buffer has been deleted. Skipping.`
      );
      return false;
    }
    return true;
  };

  if (isPropertyDefined(buffers, 'arrayBuffer')) {
    if (validateBuffer(buffers!.arrayBuffer, 'ARRAY_BUFFER')) {
      gl.bindBuffer(gl.ARRAY_BUFFER, buffers!.arrayBuffer);
    }
  } else if (isDefined(current?.arrayBuffer)) {
    gl.bindBuffer(gl.ARRAY_BUFFER, null);
  }

  // NOTE: ELEMENT_ARRAY_BUFFER is NOT restored here!
  // Per OpenGL ES 3.0 spec section 2.10, ELEMENT_ARRAY_BUFFER binding is per-VAO state.
  // It is automatically restored when binding the VAO in applyVertexArrayState() above.

  if (isPropertyDefined(buffers, 'uniformBuffer')) {
    if (validateBuffer(buffers!.uniformBuffer, 'UNIFORM_BUFFER')) {
      gl.bindBuffer(gl.UNIFORM_BUFFER, buffers!.uniformBuffer);
    }
  } else if (isDefined(current?.uniformBuffer)) {
    gl.bindBuffer(gl.UNIFORM_BUFFER, null);
  }

  if (isPropertyDefined(buffers, 'transformFeedbackBuffer')) {
    if (validateBuffer(buffers!.transformFeedbackBuffer, 'TRANSFORM_FEEDBACK_BUFFER')) {
      gl.bindBuffer(gl.TRANSFORM_FEEDBACK_BUFFER, buffers!.transformFeedbackBuffer);
    }
  } else if (isDefined(current?.transformFeedbackBuffer)) {
    gl.bindBuffer(gl.TRANSFORM_FEEDBACK_BUFFER, null);
  }

  if (isPropertyDefined(buffers, 'pixelPackBuffer')) {
    if (validateBuffer(buffers!.pixelPackBuffer, 'PIXEL_PACK_BUFFER')) {
      gl.bindBuffer(gl.PIXEL_PACK_BUFFER, buffers!.pixelPackBuffer);
    }
  } else if (isDefined(current?.pixelPackBuffer)) {
    gl.bindBuffer(gl.PIXEL_PACK_BUFFER, null);
  }

  if (isPropertyDefined(buffers, 'pixelUnpackBuffer')) {
    if (validateBuffer(buffers!.pixelUnpackBuffer, 'PIXEL_UNPACK_BUFFER')) {
      gl.bindBuffer(gl.PIXEL_UNPACK_BUFFER, buffers!.pixelUnpackBuffer);
    }
  } else if (isDefined(current?.pixelUnpackBuffer)) {
    gl.bindBuffer(gl.PIXEL_UNPACK_BUFFER, null);
  }

  if (isPropertyDefined(buffers, 'copyReadBuffer')) {
    if (validateBuffer(buffers!.copyReadBuffer, 'COPY_READ_BUFFER')) {
      gl.bindBuffer(gl.COPY_READ_BUFFER, buffers!.copyReadBuffer);
    }
  } else if (isDefined(current?.copyReadBuffer)) {
    gl.bindBuffer(gl.COPY_READ_BUFFER, null);
  }

  if (isPropertyDefined(buffers, 'copyWriteBuffer')) {
    if (validateBuffer(buffers!.copyWriteBuffer, 'COPY_WRITE_BUFFER')) {
      gl.bindBuffer(gl.COPY_WRITE_BUFFER, buffers!.copyWriteBuffer);
    }
  } else if (isDefined(current?.copyWriteBuffer)) {
    gl.bindBuffer(gl.COPY_WRITE_BUFFER, null);
  }

  // Apply indexed buffer bindings
  if (buffers?.uniformBufferBindings) {
    for (let index = 0; index < GL_MAX_UNIFORM_BUFFER_BINDINGS; index++) {
      const bindingOrUndefined = buffers.uniformBufferBindings.get(index);
      if (!isDefined(bindingOrUndefined)) {
        continue;
      }

      const binding = bindingOrUndefined as WebGLIndexedBufferBinding;
      if (isDefined(binding.buffer)) {
        // Validate buffer exists
        if (!validateBuffer(binding.buffer, `UNIFORM_BUFFER at index ${index}`)) {
          continue;
        }

        const size = binding.size as number;
        const offset = binding.offset as number;

        // Per WebGLState.ts bindBufferBase logic: size=0 means entire buffer (bindBufferBase)
        // size>0 means specific range (bindBufferRange)
        if (size === 0) {
          // bindBufferBase was used originally
          gl.bindBufferBase(gl.UNIFORM_BUFFER, index, binding.buffer);
        } else {
          // bindBufferRange was used originally
          gl.bindBufferRange(gl.UNIFORM_BUFFER, index, binding.buffer, offset, size);
        }
      }
    }
  }

  if (buffers?.transformFeedbackBufferBindings) {
    for (let index = 0; index < GL_MAX_TRANSFORM_FEEDBACK_SEPARATE_ATTRIBS; index++) {
      const bindingOrUndefined = buffers.transformFeedbackBufferBindings.get(index);
      if (!isDefined(bindingOrUndefined)) {
        continue;
      }

      const binding = bindingOrUndefined as WebGLIndexedBufferBinding;
      if (isDefined(binding.buffer)) {
        // Validate buffer exists
        if (!validateBuffer(binding.buffer, `TRANSFORM_FEEDBACK_BUFFER at index ${index}`)) {
          continue;
        }

        const size = binding.size as number;
        const offset = binding.offset as number;

        // Per WebGLState.ts bindBufferBase logic: size=0 means entire buffer (bindBufferBase)
        // size>0 means specific range (bindBufferRange)
        if (size === 0) {
          // bindBufferBase was used originally
          gl.bindBufferBase(gl.TRANSFORM_FEEDBACK_BUFFER, index, binding.buffer);
        } else {
          // bindBufferRange was used originally
          gl.bindBufferRange(gl.TRANSFORM_FEEDBACK_BUFFER, index, binding.buffer, offset, size);
        }
      }
    }
  }
}

/**
 * Apply vertex array object state
 */
function applyVertexArrayState(
  gl: WebGL2RenderingContext,
  vertexArrays: WebGLVertexArrayState | undefined,
  current?: WebGLVertexArrayState
): void {
  // TODO: Currently only restores GL state for the currently bound VAO.
  // This means if you have multiple VAOs configured, save state, switch VAOs,
  // and restore, the non-current VAO states will not be restored in the tracker.
  // To fix this, we would need to:
  // 1. Copy all VAO states from saved state to current tracker's vaoStates Map
  // 2. Ensure this doesn't break existing behavior or cause performance issues
  // 3. Handle edge cases where VAOs are deleted between save and restore

  // Bind the VAO
  if (isPropertyDefined(vertexArrays, 'vertexArrayObject')) {
    const vaoToBind = vertexArrays!.vertexArrayObject;

    // Check if the VAO was deleted between save and restore
    // Since bindVertexArray now ensures all bound VAOs have vaoStates entries,
    // if the VAO is missing from current.vaoStates, it means it was deleted
    if (vaoToBind !== null && current && !current.vaoStates.has(vaoToBind)) {
      console.warn(
        '[WebGLStateApply] Cannot restore VAO state: the saved VAO has been deleted. ' +
          'Binding will revert to default VAO (null).'
      );
      gl.bindVertexArray(null);
      return;
    }

    gl.bindVertexArray(vaoToBind);
  } else if (isDefined(current?.vertexArrayObject)) {
    gl.bindVertexArray(null);
  }

  // Restore per-VAO state for the currently bound VAO
  // Per OpenGL ES 3.0 spec section 2.10: ELEMENT_ARRAY_BUFFER and vertex attributes are per-VAO state
  const vao =
    vertexArrays?.vertexArrayObject === GLUndefined ? null : vertexArrays?.vertexArrayObject;
  const vaoState = vertexArrays?.vaoStates.get(vao!);

  if (vaoState) {
    // Restore ELEMENT_ARRAY_BUFFER binding for this VAO
    if (isPropertyDefined(vaoState, 'elementArrayBuffer')) {
      gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, vaoState.elementArrayBuffer);
    }

    // Restore vertex attribute state
    if (vaoState.attributes) {
      // Iterate through all possible vertex attribute indices
      for (let idx = 0; idx < GL_MAX_VERTEX_ATTRIBS; idx++) {
        const attribOrUndefined = vaoState.attributes.get(idx);

        // Skip undefined attributes (never been set)
        if (!isDefined(attribOrUndefined)) {
          continue;
        }

        const attrib = attribOrUndefined as WebGLVertexAttribState;

        // Check if we have a complete vertex attribute configuration
        const hasCompleteConfig =
          isDefined(attrib.size) &&
          isDefined(attrib.type) &&
          isDefined(attrib.stride) &&
          isDefined(attrib.offset);

        // Only restore this attribute if we have complete configuration OR if we're explicitly disabling it
        const shouldRestore = hasCompleteConfig || (isDefined(attrib.enabled) && !attrib.enabled);

        if (!shouldRestore) {
          // Skip this attribute - incomplete configuration and not explicitly disabled
          continue;
        }

        // Bind the buffer that was associated with this attribute if defined
        if (isDefined(attrib.buffer)) {
          gl.bindBuffer(gl.ARRAY_BUFFER, attrib.buffer);
        }

        // Restore vertexAttribPointer configuration if all required parameters are defined
        if (hasCompleteConfig) {
          // Restore the vertex attribute pointer
          if (isDefined(attrib.normalized)) {
            gl.vertexAttribPointer(
              idx,
              attrib.size as number,
              attrib.type as number,
              attrib.normalized as boolean,
              attrib.stride as number,
              attrib.offset as number
            );
          } else {
            // For vertexAttribIPointer (integer attributes)
            gl.vertexAttribIPointer(
              idx,
              attrib.size as number,
              attrib.type as number,
              attrib.stride as number,
              attrib.offset as number
            );
          }
        }

        // Handle enable/disable state
        if (isDefined(attrib.enabled)) {
          if (attrib.enabled) {
            // Only enable if we have complete configuration
            if (hasCompleteConfig) {
              gl.enableVertexAttribArray(idx);
            }
          } else {
            // Always allow disabling, even without complete configuration
            gl.disableVertexAttribArray(idx);
          }
        }

        if (isDefined(attrib.divisor)) {
          gl.vertexAttribDivisor(idx, attrib.divisor as number);
        }
      }
    } // end if (vaoState.attributes)
  } // end if (vaoState)
}

/**
 * Apply texture binding state
 */
function applyTextureState(
  gl: WebGL2RenderingContext,
  textures: WebGLTextureState | undefined,
  current?: WebGLTextureState
): void {
  // Set active texture unit first
  if (isPropertyDefined(textures, 'activeTexture')) {
    gl.activeTexture(textures!.activeTexture as number);
  } else if (isDefined(current?.activeTexture)) {
    gl.activeTexture(gl.TEXTURE0);
  }

  // Bind textures to their respective units
  if (textures?.textureUnits) {
    for (let unitIndex = 0; unitIndex < GL_MAX_COMBINED_TEXTURE_IMAGE_UNITS; unitIndex++) {
      const unitKey = `TEXTURE${unitIndex}`;
      const unitStateOrUndefined = textures.textureUnits.get(unitKey);

      if (!isDefined(unitStateOrUndefined)) {
        continue;
      }

      const unitState = unitStateOrUndefined as WebGLTextureUnitState;

      gl.activeTexture(gl.TEXTURE0 + unitIndex);

      if (isDefined(unitState.texture2D)) {
        gl.bindTexture(gl.TEXTURE_2D, unitState.texture2D);
      }
      if (isDefined(unitState.textureCubeMap)) {
        gl.bindTexture(gl.TEXTURE_CUBE_MAP, unitState.textureCubeMap);
      }
      if (isDefined(unitState.texture3D)) {
        gl.bindTexture(gl.TEXTURE_3D, unitState.texture3D);
      }
      if (isDefined(unitState.texture2DArray)) {
        gl.bindTexture(gl.TEXTURE_2D_ARRAY, unitState.texture2DArray);
      }
    }

    // Restore the active texture unit
    if (isPropertyDefined(textures, 'activeTexture')) {
      gl.activeTexture(textures!.activeTexture as number);
    }
  }
}

/**
 * Apply sampler binding state
 */
function applySamplerState(
  gl: WebGL2RenderingContext,
  samplers: WebGLSamplerState | undefined,
  current?: WebGLSamplerState
): void {
  if (samplers?.samplerBindings) {
    for (let unit = 0; unit < GL_MAX_COMBINED_TEXTURE_IMAGE_UNITS; unit++) {
      const sampler = samplers.samplerBindings[unit];
      if (isDefined(sampler)) {
        gl.bindSampler(unit, sampler);
      }
    }
  } else if (current?.samplerBindings) {
    // Reset all sampler bindings to null
    for (let unit = 0; unit < GL_MAX_COMBINED_TEXTURE_IMAGE_UNITS; unit++) {
      if (isDefined(current.samplerBindings[unit])) {
        gl.bindSampler(unit, null);
      }
    }
  }
}

/**
 * Apply program binding state
 */
function applyProgramState(
  gl: WebGL2RenderingContext,
  programs: WebGLProgramState | undefined,
  current?: WebGLProgramState
): void {
  if (isPropertyDefined(programs, 'currentProgram')) {
    gl.useProgram(programs!.currentProgram);
  } else if (isDefined(current?.currentProgram)) {
    gl.useProgram(null);
  }
}

/**
 * Apply framebuffer binding and attachment state
 */
function applyFramebufferState(
  gl: WebGL2RenderingContext,
  framebuffers: WebGLFramebufferState | undefined,
  current?: WebGLFramebufferState
): void {
  // Bind framebuffers first
  if (isPropertyDefined(framebuffers, 'framebuffer')) {
    gl.bindFramebuffer(gl.FRAMEBUFFER, framebuffers!.framebuffer);
  } else if (isDefined(current?.framebuffer)) {
    gl.bindFramebuffer(gl.FRAMEBUFFER, null);
  }

  if (isPropertyDefined(framebuffers, 'drawFramebuffer')) {
    gl.bindFramebuffer(gl.DRAW_FRAMEBUFFER, framebuffers!.drawFramebuffer);
  } else if (isDefined(current?.drawFramebuffer)) {
    gl.bindFramebuffer(gl.DRAW_FRAMEBUFFER, null);
  }

  if (isPropertyDefined(framebuffers, 'readFramebuffer')) {
    gl.bindFramebuffer(gl.READ_FRAMEBUFFER, framebuffers!.readFramebuffer);
  } else if (isDefined(current?.readFramebuffer)) {
    gl.bindFramebuffer(gl.READ_FRAMEBUFFER, null);
  }

  // Apply default framebuffer state (only drawBuffers and readBuffer)
  // NOTE: We do NOT apply attachments to the default framebuffer (null) because:
  // 1. The default framebuffer is provided by the canvas/context
  // 2. You cannot call framebufferTexture2D/framebufferRenderbuffer on the default framebuffer
  // 3. Attempting to do so results in INVALID_OPERATION errors
  const isDefaultDrawFB = framebuffers?.drawFramebuffer === null;
  const hasDefaultFBState = framebuffers?.defaultFramebufferState;

  // Only apply drawBuffers and readBuffer for default framebuffer
  if (isDefaultDrawFB && hasDefaultFBState) {
    const fbState = framebuffers!.defaultFramebufferState;

    // Apply draw buffers (this IS valid for default framebuffer)
    if (isDefined(fbState.drawBuffers)) {
      gl.drawBuffers(fbState.drawBuffers as number[]);
    }

    // Apply read buffer (this IS valid for default framebuffer)
    if (isDefined(fbState.readBuffer)) {
      gl.readBuffer(fbState.readBuffer as number);
    }
  }
}

/**
 * Apply renderbuffer binding state
 */
function applyRenderbufferState(
  gl: WebGL2RenderingContext,
  renderbuffer: WebGLRenderbufferState | undefined,
  current?: WebGLRenderbufferState
): void {
  if (isPropertyDefined(renderbuffer, 'renderbuffer')) {
    gl.bindRenderbuffer(gl.RENDERBUFFER, renderbuffer!.renderbuffer);
  } else if (isDefined(current?.renderbuffer)) {
    gl.bindRenderbuffer(gl.RENDERBUFFER, null);
  }
}

/**
 * Apply transform feedback state
 */
function applyTransformFeedbackState(
  gl: WebGL2RenderingContext,
  transformFeedback: WebGLTransformFeedbackState | undefined,
  current?: WebGLTransformFeedbackState
): void {
  if (isPropertyDefined(transformFeedback, 'transformFeedback')) {
    gl.bindTransformFeedback(gl.TRANSFORM_FEEDBACK, transformFeedback!.transformFeedback);
  } else if (isDefined(current?.transformFeedback)) {
    gl.bindTransformFeedback(gl.TRANSFORM_FEEDBACK, null);
  }

  if (
    isPropertyDefined(transformFeedback, 'transformFeedbackActive') &&
    transformFeedback!.transformFeedbackActive
  ) {
    // Note: beginTransformFeedback requires a primitive mode parameter
    // which isn't tracked, so this is a simplified version
    // gl.beginTransformFeedback(primitiveMode);
  }

  if (
    isPropertyDefined(transformFeedback, 'transformFeedbackPaused') &&
    transformFeedback!.transformFeedbackPaused
  ) {
    gl.pauseTransformFeedback();
  }
}

/**
 * Apply viewport and scissor state
 */
function applyViewportState(
  gl: WebGL2RenderingContext,
  viewport: WebGLViewportState | undefined,
  current?: WebGLViewportState
): void {
  // Viewport - default: typically [0, 0, canvas.width, canvas.height]
  if (isPropertyDefined(viewport, 'viewport')) {
    const vp = viewport!.viewport as Int32Array;
    gl.viewport(vp[0], vp[1], vp[2], vp[3]);
  } else if (isDefined(current?.viewport)) {
    // Reset to canvas dimensions
    const canvas = gl.canvas;
    gl.viewport(0, 0, canvas.width, canvas.height);
  }

  // Scissor box - default: typically [0, 0, canvas.width, canvas.height]
  if (isPropertyDefined(viewport, 'scissorBox')) {
    const scissor = viewport!.scissorBox as Int32Array;
    gl.scissor(scissor[0], scissor[1], scissor[2], scissor[3]);
  } else if (isDefined(current?.scissorBox)) {
    // Reset to canvas dimensions
    const canvas = gl.canvas;
    gl.scissor(0, 0, canvas.width, canvas.height);
  }
}

/**
 * Apply capability enable/disable state
 * @param gl - The WebGL2RenderingContext
 * @param capabilities - The desired capability state (undefined resets all to defaults)
 * @param currentCapabilities - Optional current capability state. If provided and a capability
 *                              is currently enabled (true) but not defined in capabilities,
 *                              it will be explicitly disabled.
 */
function applyCapabilityState(
  gl: WebGL2RenderingContext,
  capabilities: WebGLCapabilityState | undefined,
  currentCapabilities?: WebGLCapabilityState
): void {
  // Helper to apply a capability state
  const applyCapability = (cap: keyof WebGLCapabilityState, glEnum: number) => {
    const desired = capabilities?.[cap];
    const current = currentCapabilities?.[cap];

    if (isDefined(desired)) {
      // If desired state is defined, apply it
      desired ? gl.enable(glEnum) : gl.disable(glEnum);
    } else if (isDefined(current) && current === true) {
      // If desired state is undefined but current is enabled, disable it
      gl.disable(glEnum);
    }
  };

  applyCapability('blend', gl.BLEND);
  applyCapability('cullFace', gl.CULL_FACE);
  applyCapability('depthTest', gl.DEPTH_TEST);
  applyCapability('dither', gl.DITHER);
  applyCapability('polygonOffsetFill', gl.POLYGON_OFFSET_FILL);
  applyCapability('sampleAlphaToCoverage', gl.SAMPLE_ALPHA_TO_COVERAGE);
  applyCapability('sampleCoverage', gl.SAMPLE_COVERAGE);
  applyCapability('scissorTest', gl.SCISSOR_TEST);
  applyCapability('stencilTest', gl.STENCIL_TEST);
  applyCapability('rasterDiscard', gl.RASTERIZER_DISCARD);
}

/**
 * Apply clear value state
 */
function applyClearState(
  gl: WebGL2RenderingContext,
  clear: WebGLClearState | undefined,
  current?: WebGLClearState
): void {
  // ColorClearValue - default: [0, 0, 0, 0]
  if (isPropertyDefined(clear, 'colorClearValue')) {
    const color = clear!.colorClearValue as Float32Array;
    gl.clearColor(color[0], color[1], color[2], color[3]);
  } else if (isDefined(current?.colorClearValue)) {
    gl.clearColor(0, 0, 0, 0);
  }

  // DepthClearValue - default: 1
  if (isPropertyDefined(clear, 'depthClearValue')) {
    gl.clearDepth(clear!.depthClearValue as number);
  } else if (isDefined(current?.depthClearValue)) {
    gl.clearDepth(1);
  }

  // StencilClearValue - default: 0
  if (isPropertyDefined(clear, 'stencilClearValue')) {
    gl.clearStencil(clear!.stencilClearValue as number);
  } else if (isDefined(current?.stencilClearValue)) {
    gl.clearStencil(0);
  }
}

/**
 * Apply blend state
 */
function applyBlendState(
  gl: WebGL2RenderingContext,
  blend: WebGLBlendState | undefined,
  current?: WebGLBlendState
): void {
  // BlendColor - default: [0, 0, 0, 0]
  if (isPropertyDefined(blend, 'blendColor')) {
    const color = blend!.blendColor as Float32Array;
    gl.blendColor(color[0], color[1], color[2], color[3]);
  } else if (isDefined(current?.blendColor)) {
    gl.blendColor(0, 0, 0, 0);
  }

  // BlendEquation - default: FUNC_ADD for both RGB and Alpha
  if (
    isPropertyDefined(blend, 'blendEquationRgb') &&
    isPropertyDefined(blend, 'blendEquationAlpha')
  ) {
    gl.blendEquationSeparate(
      blend!.blendEquationRgb as number,
      blend!.blendEquationAlpha as number
    );
  } else if (isDefined(current?.blendEquationRgb) && isDefined(current?.blendEquationAlpha)) {
    gl.blendEquationSeparate(gl.FUNC_ADD, gl.FUNC_ADD);
  }

  // BlendFunc - default: src=ONE, dst=ZERO for both RGB and Alpha
  if (
    isPropertyDefined(blend, 'blendSrcRgb') &&
    isPropertyDefined(blend, 'blendDstRgb') &&
    isPropertyDefined(blend, 'blendSrcAlpha') &&
    isPropertyDefined(blend, 'blendDstAlpha')
  ) {
    gl.blendFuncSeparate(
      blend!.blendSrcRgb as number,
      blend!.blendDstRgb as number,
      blend!.blendSrcAlpha as number,
      blend!.blendDstAlpha as number
    );
  } else if (
    isDefined(current?.blendSrcRgb) &&
    isDefined(current?.blendDstRgb) &&
    isDefined(current?.blendSrcAlpha) &&
    isDefined(current?.blendDstAlpha)
  ) {
    gl.blendFuncSeparate(gl.ONE, gl.ZERO, gl.ONE, gl.ZERO);
  }
}

/**
 * Apply depth state
 */
function applyDepthState(
  gl: WebGL2RenderingContext,
  depth: WebGLDepthState | undefined,
  current?: WebGLDepthState
): void {
  // DepthFunc - default: LESS
  if (isPropertyDefined(depth, 'depthFunc')) {
    gl.depthFunc(depth!.depthFunc as number);
  } else if (isDefined(current?.depthFunc)) {
    gl.depthFunc(gl.LESS);
  }

  // DepthWritemask - default: true
  if (isPropertyDefined(depth, 'depthWritemask')) {
    gl.depthMask(depth!.depthWritemask as boolean);
  } else if (isDefined(current?.depthWritemask)) {
    gl.depthMask(true);
  }

  // DepthRange - default: [0, 1]
  if (isPropertyDefined(depth, 'depthRange')) {
    const range = depth!.depthRange as Float32Array;
    gl.depthRange(range[0], range[1]);
  } else if (isDefined(current?.depthRange)) {
    gl.depthRange(0, 1);
  }
}

/**
 * Apply stencil state
 */
function applyStencilState(
  gl: WebGL2RenderingContext,
  stencil: WebGLStencilState | undefined,
  current?: WebGLStencilState
): void {
  // Front face stencil func - default: ALWAYS, ref=0, mask=0xFFFFFFFF
  if (
    isPropertyDefined(stencil, 'stencilFunc') &&
    isPropertyDefined(stencil, 'stencilRef') &&
    isPropertyDefined(stencil, 'stencilValueMask')
  ) {
    gl.stencilFuncSeparate(
      gl.FRONT,
      stencil!.stencilFunc as number,
      stencil!.stencilRef as number,
      stencil!.stencilValueMask as number
    );
  } else if (
    isDefined(current?.stencilFunc) &&
    isDefined(current?.stencilRef) &&
    isDefined(current?.stencilValueMask)
  ) {
    gl.stencilFuncSeparate(gl.FRONT, gl.ALWAYS, 0, 0xffffffff);
  }

  // Front face stencil writemask - default: 0xFFFFFFFF
  if (isPropertyDefined(stencil, 'stencilWritemask')) {
    gl.stencilMaskSeparate(gl.FRONT, stencil!.stencilWritemask as number);
  } else if (isDefined(current?.stencilWritemask)) {
    gl.stencilMaskSeparate(gl.FRONT, 0xffffffff);
  }

  // Front face stencil operations - default: KEEP for all
  if (
    isPropertyDefined(stencil, 'stencilFail') &&
    isPropertyDefined(stencil, 'stencilPassDepthFail') &&
    isPropertyDefined(stencil, 'stencilPassDepthPass')
  ) {
    gl.stencilOpSeparate(
      gl.FRONT,
      stencil!.stencilFail as number,
      stencil!.stencilPassDepthFail as number,
      stencil!.stencilPassDepthPass as number
    );
  } else if (
    isDefined(current?.stencilFail) &&
    isDefined(current?.stencilPassDepthFail) &&
    isDefined(current?.stencilPassDepthPass)
  ) {
    gl.stencilOpSeparate(gl.FRONT, gl.KEEP, gl.KEEP, gl.KEEP);
  }

  // Back face stencil func - default: ALWAYS, ref=0, mask=0xFFFFFFFF
  if (
    isPropertyDefined(stencil, 'stencilBackFunc') &&
    isPropertyDefined(stencil, 'stencilBackRef') &&
    isPropertyDefined(stencil, 'stencilBackValueMask')
  ) {
    gl.stencilFuncSeparate(
      gl.BACK,
      stencil!.stencilBackFunc as number,
      stencil!.stencilBackRef as number,
      stencil!.stencilBackValueMask as number
    );
  } else if (
    isDefined(current?.stencilBackFunc) &&
    isDefined(current?.stencilBackRef) &&
    isDefined(current?.stencilBackValueMask)
  ) {
    gl.stencilFuncSeparate(gl.BACK, gl.ALWAYS, 0, 0xffffffff);
  }

  // Back face stencil writemask - default: 0xFFFFFFFF
  if (isPropertyDefined(stencil, 'stencilBackWritemask')) {
    gl.stencilMaskSeparate(gl.BACK, stencil!.stencilBackWritemask as number);
  } else if (isDefined(current?.stencilBackWritemask)) {
    gl.stencilMaskSeparate(gl.BACK, 0xffffffff);
  }

  // Back face stencil operations - default: KEEP for all
  if (
    isPropertyDefined(stencil, 'stencilBackFail') &&
    isPropertyDefined(stencil, 'stencilBackPassDepthFail') &&
    isPropertyDefined(stencil, 'stencilBackPassDepthPass')
  ) {
    gl.stencilOpSeparate(
      gl.BACK,
      stencil!.stencilBackFail as number,
      stencil!.stencilBackPassDepthFail as number,
      stencil!.stencilBackPassDepthPass as number
    );
  } else if (
    isDefined(current?.stencilBackFail) &&
    isDefined(current?.stencilBackPassDepthFail) &&
    isDefined(current?.stencilBackPassDepthPass)
  ) {
    gl.stencilOpSeparate(gl.BACK, gl.KEEP, gl.KEEP, gl.KEEP);
  }
}

/**
 * Apply color write mask state
 */
function applyColorState(
  gl: WebGL2RenderingContext,
  color: WebGLColorState | undefined,
  current?: WebGLColorState
): void {
  // ColorWritemask - default: [true, true, true, true]
  if (isPropertyDefined(color, 'colorWritemask')) {
    const mask = color!.colorWritemask as boolean[];
    gl.colorMask(mask[0], mask[1], mask[2], mask[3]);
  } else if (isDefined(current?.colorWritemask)) {
    gl.colorMask(true, true, true, true);
  }
}

/**
 * Apply culling state
 */
function applyCullingState(
  gl: WebGL2RenderingContext,
  culling: WebGLCullingState | undefined,
  current?: WebGLCullingState
): void {
  // CullFaceMode - default: BACK
  if (isPropertyDefined(culling, 'cullFaceMode')) {
    gl.cullFace(culling!.cullFaceMode as number);
  } else if (isDefined(current?.cullFaceMode)) {
    gl.cullFace(gl.BACK);
  }

  // FrontFace - default: CCW (counter-clockwise)
  if (isPropertyDefined(culling, 'frontFace')) {
    gl.frontFace(culling!.frontFace as number);
  } else if (isDefined(current?.frontFace)) {
    gl.frontFace(gl.CCW);
  }
}

/**
 * Apply line width state
 */
function applyLineState(
  gl: WebGL2RenderingContext,
  line: WebGLLineState | undefined,
  current?: WebGLLineState
): void {
  // LineWidth - default: 1
  if (isPropertyDefined(line, 'lineWidth')) {
    gl.lineWidth(line!.lineWidth as number);
  } else if (isDefined(current?.lineWidth)) {
    gl.lineWidth(1);
  }
}

/**
 * Apply polygon offset state
 */
function applyPolygonOffsetState(
  gl: WebGL2RenderingContext,
  polygonOffset: WebGLPolygonOffsetState | undefined,
  current?: WebGLPolygonOffsetState
): void {
  // PolygonOffset - default: factor=0, units=0
  if (
    isPropertyDefined(polygonOffset, 'polygonOffsetFactor') &&
    isPropertyDefined(polygonOffset, 'polygonOffsetUnits')
  ) {
    gl.polygonOffset(
      polygonOffset!.polygonOffsetFactor as number,
      polygonOffset!.polygonOffsetUnits as number
    );
  } else if (isDefined(current?.polygonOffsetFactor) && isDefined(current?.polygonOffsetUnits)) {
    gl.polygonOffset(0, 0);
  }
}

/**
 * Apply sample coverage state
 */
function applySampleState(
  gl: WebGL2RenderingContext,
  sample: WebGLSampleState | undefined,
  current?: WebGLSampleState
): void {
  // SampleCoverage - default: value=1, invert=false
  if (
    isPropertyDefined(sample, 'sampleCoverageValue') &&
    isPropertyDefined(sample, 'sampleCoverageInvert')
  ) {
    gl.sampleCoverage(
      sample!.sampleCoverageValue as number,
      sample!.sampleCoverageInvert as boolean
    );
  } else if (isDefined(current?.sampleCoverageValue) && isDefined(current?.sampleCoverageInvert)) {
    gl.sampleCoverage(1, false);
  }
}

/**
 * Apply pixel store parameters
 */
function applyPixelStoreState(
  gl: WebGL2RenderingContext,
  pixelStore: WebGLPixelStoreState | undefined,
  current?: WebGLPixelStoreState
): void {
  // PackAlignment - default: 4
  if (isPropertyDefined(pixelStore, 'packAlignment')) {
    gl.pixelStorei(gl.PACK_ALIGNMENT, pixelStore!.packAlignment as number);
  } else if (isDefined(current?.packAlignment)) {
    gl.pixelStorei(gl.PACK_ALIGNMENT, 4);
  }

  // UnpackAlignment - default: 4
  if (isPropertyDefined(pixelStore, 'unpackAlignment')) {
    gl.pixelStorei(gl.UNPACK_ALIGNMENT, pixelStore!.unpackAlignment as number);
  } else if (isDefined(current?.unpackAlignment)) {
    gl.pixelStorei(gl.UNPACK_ALIGNMENT, 4);
  }

  // UnpackFlipY - default: false
  if (isPropertyDefined(pixelStore, 'unpackFlipY')) {
    gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, pixelStore!.unpackFlipY ? 1 : 0);
  } else if (isDefined(current?.unpackFlipY)) {
    gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, 0);
  }

  // UnpackPremultiplyAlpha - default: false
  if (isPropertyDefined(pixelStore, 'unpackPremultiplyAlpha')) {
    gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, pixelStore!.unpackPremultiplyAlpha ? 1 : 0);
  } else if (isDefined(current?.unpackPremultiplyAlpha)) {
    gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, 0);
  }

  // PackRowLength - default: 0
  if (isPropertyDefined(pixelStore, 'packRowLength')) {
    gl.pixelStorei(gl.PACK_ROW_LENGTH, pixelStore!.packRowLength as number);
  } else if (isDefined(current?.packRowLength)) {
    gl.pixelStorei(gl.PACK_ROW_LENGTH, 0);
  }

  // PackSkipPixels - default: 0
  if (isPropertyDefined(pixelStore, 'packSkipPixels')) {
    gl.pixelStorei(gl.PACK_SKIP_PIXELS, pixelStore!.packSkipPixels as number);
  } else if (isDefined(current?.packSkipPixels)) {
    gl.pixelStorei(gl.PACK_SKIP_PIXELS, 0);
  }

  // PackSkipRows - default: 0
  if (isPropertyDefined(pixelStore, 'packSkipRows')) {
    gl.pixelStorei(gl.PACK_SKIP_ROWS, pixelStore!.packSkipRows as number);
  } else if (isDefined(current?.packSkipRows)) {
    gl.pixelStorei(gl.PACK_SKIP_ROWS, 0);
  }

  // UnpackRowLength - default: 0
  if (isPropertyDefined(pixelStore, 'unpackRowLength')) {
    gl.pixelStorei(gl.UNPACK_ROW_LENGTH, pixelStore!.unpackRowLength as number);
  } else if (isDefined(current?.unpackRowLength)) {
    gl.pixelStorei(gl.UNPACK_ROW_LENGTH, 0);
  }

  // UnpackImageHeight - default: 0
  if (isPropertyDefined(pixelStore, 'unpackImageHeight')) {
    gl.pixelStorei(gl.UNPACK_IMAGE_HEIGHT, pixelStore!.unpackImageHeight as number);
  } else if (isDefined(current?.unpackImageHeight)) {
    gl.pixelStorei(gl.UNPACK_IMAGE_HEIGHT, 0);
  }

  // UnpackSkipPixels - default: 0
  if (isPropertyDefined(pixelStore, 'unpackSkipPixels')) {
    gl.pixelStorei(gl.UNPACK_SKIP_PIXELS, pixelStore!.unpackSkipPixels as number);
  } else if (isDefined(current?.unpackSkipPixels)) {
    gl.pixelStorei(gl.UNPACK_SKIP_PIXELS, 0);
  }

  // UnpackSkipRows - default: 0
  if (isPropertyDefined(pixelStore, 'unpackSkipRows')) {
    gl.pixelStorei(gl.UNPACK_SKIP_ROWS, pixelStore!.unpackSkipRows as number);
  } else if (isDefined(current?.unpackSkipRows)) {
    gl.pixelStorei(gl.UNPACK_SKIP_ROWS, 0);
  }

  // UnpackSkipImages - default: 0
  if (isPropertyDefined(pixelStore, 'unpackSkipImages')) {
    gl.pixelStorei(gl.UNPACK_SKIP_IMAGES, pixelStore!.unpackSkipImages as number);
  } else if (isDefined(current?.unpackSkipImages)) {
    gl.pixelStorei(gl.UNPACK_SKIP_IMAGES, 0);
  }
}

/**
 * Apply query state
 */
function applyQueryState(gl: WebGL2RenderingContext, queries: WebGLQueryState): void {
  // Note: Query state includes active queries, but we can't directly set them
  // as beginQuery requires starting a new query operation.
  // This is here for completeness but may need special handling.

  if (isDefined(queries.currentAnySamplesPassed) && queries.currentAnySamplesPassed) {
    console.warn(
      '[WebGLStateApply] Cannot restore active query state for ANY_SAMPLES_PASSED - queries cannot be directly restored'
    );
    // gl.beginQuery(gl.ANY_SAMPLES_PASSED, queries.currentAnySamplesPassed);
  }
  if (
    isDefined(queries.currentAnySamplesPassedConservative) &&
    queries.currentAnySamplesPassedConservative
  ) {
    console.warn(
      '[WebGLStateApply] Cannot restore active query state for ANY_SAMPLES_PASSED_CONSERVATIVE - queries cannot be directly restored'
    );
    // gl.beginQuery(gl.ANY_SAMPLES_PASSED_CONSERVATIVE, queries.currentAnySamplesPassedConservative);
  }
  if (
    isDefined(queries.currentTransformFeedbackPrimitivesWritten) &&
    queries.currentTransformFeedbackPrimitivesWritten
  ) {
    console.warn(
      '[WebGLStateApply] Cannot restore active query state for TRANSFORM_FEEDBACK_PRIMITIVES_WRITTEN - queries cannot be directly restored'
    );
    // gl.beginQuery(gl.TRANSFORM_FEEDBACK_PRIMITIVES_WRITTEN, queries.currentTransformFeedbackPrimitivesWritten);
  }
}
