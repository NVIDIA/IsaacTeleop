import { WebGLStateTracker, WebGLState } from './WebGLState';
import { apply } from './WebGLStateApply';

/**
 * BoundWebGLState - A WebGL2 context with automatic state tracking
 *
 * This is the original WebGL2 context with state-changing functions rebound
 * to call the tracker before forwarding to the original implementation.
 */
export class BoundWebGLState {
  private gl: WebGL2RenderingContext;
  private tracker: WebGLStateTracker;
  private originalFunctions: Map<string, Function>;
  private savedState?: WebGLState;
  private trackingEnabled = true;

  constructor(
    gl: WebGL2RenderingContext,
    tracker: WebGLStateTracker,
    originalFunctions: Map<string, Function>
  ) {
    this.gl = gl;
    this.tracker = tracker;
    this.originalFunctions = originalFunctions;
  }

  /**
   * Get the internal state tracker
   */
  private getTracker(): WebGLStateTracker {
    return this.tracker;
  }

  /**
   * Save the current tracked WebGL state
   * This clones the state so it can be restored later
   */
  save(): void {
    this.savedState = this.tracker.getState();
  }

  /**
   * Restore the previously saved WebGL state
   * This applies the saved state back to the WebGL context
   * @throws {Error} If no state has been saved
   */
  restore(): void {
    if (!this.savedState) {
      throw new Error('No state has been saved. Call save() before restore().');
    }

    // Save the current tracking state and enable tracking during restore
    // This ensures the tracker stays synchronized with actual GL state
    const wasTrackingEnabled = this.trackingEnabled;
    this.trackingEnabled = true;

    const currentState = this.tracker.getState();
    apply(this.gl, this.savedState, currentState);

    // Restore the original tracking state
    this.trackingEnabled = wasTrackingEnabled;
  }

  enableTracking(enable: boolean): void {
    this.trackingEnabled = enable;
  }

  _enabled(): boolean {
    return this.trackingEnabled;
  }

  /**
   * Revert all tracked functions back to their original implementations
   * This removes state tracking from the WebGL context
   */
  revert(): void {
    const glAny = this.gl as any;

    for (const [name, originalFunction] of this.originalFunctions.entries()) {
      glAny[name] = originalFunction;
    }

    // Clear the map
    this.originalFunctions.clear();

    // Remove the stored BoundWebGLState from the GL context
    delete glAny.__cloudxrBoundState;
  }
}

/**
 * Bind a WebGL2 context with automatic state tracking
 *
 * Rebinds state-changing methods on the WebGL context to automatically track
 * state changes before forwarding to the original implementation.
 *
 * @param gl - The WebGL2RenderingContext to wrap
 * @returns A BoundWebGLState instance that provides access to the tracker and revert functionality
 *
 * @example
 * ```typescript
 * const canvas = document.getElementById('canvas') as HTMLCanvasElement;
 * const gl = canvas.getContext('webgl2')!;
 * const binding = bindGL(gl);
 *
 * // Use gl like a normal WebGL context - it's now tracked
 * gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
 * gl.bindVertexArray(vao);
 *
 * // Save the current state
 * binding.save();
 *
 * // Make some temporary changes
 * gl.bindBuffer(gl.ARRAY_BUFFER, tempBuffer);
 * gl.enable(gl.BLEND);
 *
 * // Restore the saved state
 * binding.restore();
 *
 * // Access tracked state
 * const state = binding.getTracker().getState();
 * console.log(state.buffers?.arrayBuffer); // The bound buffer
 *
 * // When done, revert to stop tracking
 * binding.revert();
 * ```
 */
export function bindGL(gl: WebGL2RenderingContext): BoundWebGLState {
  const glAny = gl as any;

  // Check if this GL context is already wrapped - prevent double-wrapping
  if (glAny.__cloudxrBoundState) {
    console.warn(
      'WebGL context is already wrapped with state tracking. Returning existing BoundWebGLState.'
    );
    return glAny.__cloudxrBoundState;
  }

  // Create the tracker
  const tracker = new WebGLStateTracker();

  // Store original functions for later reversion
  const originalFunctions = new Map<string, Function>();
  const wrappedFunctions = new Map<string, Function>();

  const state = new BoundWebGLState(gl, tracker, originalFunctions);

  // Store the BoundWebGLState on the GL context to prevent double-wrapping
  glAny.__cloudxrBoundState = state;

  // Helper function to bind a method
  const bind = (name: string, trackerMethod: Function) => {
    // CRITICAL: Store the original BEFORE we replace it, otherwise we'll store the wrapper
    const originalMethod = glAny[name];
    if (!originalMethod) {
      throw new Error('Original method not found for ' + name);
    }
    if (originalMethod === wrappedFunctions.get(name)) {
      throw new Error('Wrapped function already bound for ' + name);
    }

    const original = originalMethod.bind(gl);
    originalFunctions.set(name, original);
    const wrappedFunction = (...args: any[]) => {
      if (state._enabled()) {
        trackerMethod.apply(tracker, args);
      }
      return original(...args);
    };
    wrappedFunctions.set(name, wrappedFunction);

    glAny[name] = wrappedFunction;
  };

  // Buffer bindings
  bind('bindBuffer', tracker.bindBuffer);
  bind('bindBufferBase', tracker.bindBufferBase);
  bind('bindBufferRange', tracker.bindBufferRange);

  // Buffer lifecycle tracking (for validation without GPU calls)
  const originalCreateBuffer = glAny.createBuffer.bind(gl);
  originalFunctions.set('createBuffer', originalCreateBuffer);
  glAny.createBuffer = (): WebGLBuffer | null => {
    const buffer = originalCreateBuffer();
    if (buffer) {
      tracker.createBuffer(buffer);
    }
    return buffer;
  };
  bind('deleteBuffer', tracker.deleteBuffer);

  // VAO and vertex attributes
  bind('bindVertexArray', tracker.bindVertexArray);
  bind('deleteVertexArray', tracker.deleteVertexArray);
  bind('enableVertexAttribArray', tracker.enableVertexAttribArray);
  bind('disableVertexAttribArray', tracker.disableVertexAttribArray);
  bind('vertexAttribPointer', tracker.vertexAttribPointer);
  bind('vertexAttribIPointer', tracker.vertexAttribIPointer);
  bind('vertexAttribDivisor', tracker.vertexAttribDivisor);

  // Texture bindings
  bind('activeTexture', tracker.activeTexture);
  bind('bindTexture', tracker.bindTexture);

  // Program binding
  bind('useProgram', tracker.useProgram);

  // Framebuffer bindings
  bind('bindFramebuffer', tracker.bindFramebuffer);
  bind('framebufferTexture2D', tracker.framebufferTexture2D);
  bind('framebufferRenderbuffer', tracker.framebufferRenderbuffer);
  bind('framebufferTextureLayer', tracker.framebufferTextureLayer);
  bind('drawBuffers', tracker.drawBuffers);
  bind('readBuffer', tracker.readBuffer);

  // Renderbuffer binding
  bind('bindRenderbuffer', tracker.bindRenderbuffer);

  // Transform feedback
  bind('bindTransformFeedback', tracker.bindTransformFeedback);
  bind('beginTransformFeedback', tracker.beginTransformFeedback);
  bind('endTransformFeedback', tracker.endTransformFeedback);
  bind('pauseTransformFeedback', tracker.pauseTransformFeedback);
  bind('resumeTransformFeedback', tracker.resumeTransformFeedback);

  // Capabilities (enable/disable)
  bind('enable', tracker.enable);
  bind('disable', tracker.disable);

  // Viewport and scissor
  bind('viewport', tracker.viewport);
  bind('scissor', tracker.scissor);

  // Clear values
  bind('clearColor', tracker.clearColor);
  bind('clearDepth', tracker.clearDepth);
  bind('clearStencil', tracker.clearStencil);

  // Blend state
  bind('blendColor', tracker.blendColor);
  bind('blendEquation', tracker.blendEquation);
  bind('blendEquationSeparate', tracker.blendEquationSeparate);
  bind('blendFunc', tracker.blendFunc);
  bind('blendFuncSeparate', tracker.blendFuncSeparate);

  // Depth state
  bind('depthFunc', tracker.depthFunc);
  bind('depthMask', tracker.depthMask);
  bind('depthRange', tracker.depthRange);

  // Stencil state
  bind('stencilFunc', tracker.stencilFunc);
  bind('stencilFuncSeparate', tracker.stencilFuncSeparate);
  bind('stencilMask', tracker.stencilMask);
  bind('stencilMaskSeparate', tracker.stencilMaskSeparate);
  bind('stencilOp', tracker.stencilOp);
  bind('stencilOpSeparate', tracker.stencilOpSeparate);

  // Color mask
  bind('colorMask', tracker.colorMask);

  // Culling and face orientation
  bind('cullFace', tracker.cullFace);
  bind('frontFace', tracker.frontFace);

  // Line width
  bind('lineWidth', tracker.lineWidth);

  // Polygon offset
  bind('polygonOffset', tracker.polygonOffset);

  // Sample coverage
  bind('sampleCoverage', tracker.sampleCoverage);

  // Pixel store parameters
  bind('pixelStorei', tracker.pixelStorei);

  // Sampler binding
  bind('bindSampler', tracker.bindSampler);

  // Query operations
  bind('beginQuery', tracker.beginQuery);
  bind('endQuery', tracker.endQuery);

  return state;
}
