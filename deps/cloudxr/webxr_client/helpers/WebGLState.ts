/**
 * Sentinel value to represent undefined GL state.
 * This allows distinguishing between "not set" (GLUndefined) and "set to null" (null).
 */
export const GLUndefined = {} as const;

/**
 * Type representing the GLUndefined sentinel value.
 */
export type GLUndefined = typeof GLUndefined;

/**
 * Checks if a value is defined (not GLUndefined).
 * @param val - The value to check
 * @returns true if the value is defined, false if it's GLUndefined
 */
export function isDefined(val: any): boolean {
  return val !== GLUndefined;
}

/**
 * WebGL maximum array sizes
 * These are conservative minimum values guaranteed by the WebGL spec
 */
export const GL_MAX_VERTEX_ATTRIBS = 16; // Minimum guaranteed by WebGL 2.0
export const GL_MAX_UNIFORM_BUFFER_BINDINGS = 36; // Minimum guaranteed by WebGL 2.0
export const GL_MAX_TRANSFORM_FEEDBACK_SEPARATE_ATTRIBS = 4; // Minimum guaranteed by WebGL 2.0
export const GL_MAX_COMBINED_TEXTURE_IMAGE_UNITS = 32; // Minimum guaranteed by WebGL 2.0
export const GL_MAX_COLOR_ATTACHMENTS = 8; // Minimum guaranteed by WebGL 2.0 (typically 4, but commonly 8+)

/**
 * Generic dictionary/array container for indexed state with cloning support.
 * Used for storing WebGL state indexed by number keys.
 * @template T - The type of values stored in the dictionary, must have a clone() method
 */
export class GLAttributeArray<T extends { clone(): T; equals(other: T): boolean }> {
  [index: number]: T | GLUndefined;
  private _size: number;

  constructor(size: number) {
    this._size = size;
    for (let i = 0; i < size; i++) {
      this[i] = GLUndefined;
    }
  }

  get(index: number): T | GLUndefined {
    return this[index];
  }

  set(index: number, value: T | GLUndefined): void {
    this[index] = value;
  }

  clone(): GLAttributeArray<T> {
    const cloned = new GLAttributeArray<T>(this._size);
    for (let i = 0; i < this._size; i++) {
      cloned[i] = this[i] !== GLUndefined ? (this[i] as T).clone() : this[i];
    }
    return cloned;
  }

  equals(other: GLAttributeArray<T>): boolean {
    if (this._size !== other._size) return false;
    for (let i = 0; i < this._size; i++) {
      const thisVal = this[i];
      const otherVal = other[i];
      if (thisVal === GLUndefined && otherVal === GLUndefined) continue;
      if (thisVal === GLUndefined || otherVal === GLUndefined) return false;
      if (!(thisVal as T).equals(otherVal as T)) return false;
    }
    return true;
  }
}

/**
 * Generic dictionary container for string-keyed state with cloning support.
 * Used for storing WebGL state indexed by string keys (e.g., texture unit names).
 * @template T - The type of values stored in the dictionary, must have a clone() method
 */
export class GLUnitMap<T extends { clone(): T; equals(other: T): boolean }> {
  [key: string]: T | any;

  get(key: string): T | GLUndefined {
    return this[key] !== undefined ? this[key] : GLUndefined;
  }

  set(key: string, value: T): void {
    this[key] = value;
  }

  clone(): GLUnitMap<T> {
    const cloned = new GLUnitMap<T>();
    for (const [key, value] of Object.entries(this)) {
      if (value && typeof value === 'object' && 'clone' in value) {
        cloned[key] = value.clone();
      }
    }
    return cloned;
  }

  equals(other: GLUnitMap<T>): boolean {
    const thisKeys = Object.keys(this);
    const otherKeys = Object.keys(other);
    if (thisKeys.length !== otherKeys.length) return false;
    return thisKeys.every(key => {
      const thisVal = this.get(key);
      const otherVal = other.get(key);
      if (thisVal === GLUndefined && otherVal === GLUndefined) return true;
      if (thisVal === GLUndefined || otherVal === GLUndefined) return false;
      return (thisVal as T).equals(otherVal as T);
    });
  }
}

/**
 * WebGL State interfaces and state-only WebGL context
 *
 * This file contains the comprehensive WebGL state structure and a WebGLStateTracker
 * class that mimics the WebGL2RenderingContext interface but only updates state
 * without making actual WebGL calls.
 *
 * IMPORTANT: This tracker only tracks the state associated with DEFAULT/NULL objects.
 *
 * Per the WebGL 2.0 spec, state falls into three categories:
 *
 * 1. ALWAYS TRACKED (Global Context State):
 *    - Active texture unit (ACTIVE_TEXTURE)
 *    - Bound objects: VAO, program, framebuffer, renderbuffer, transform feedback
 *    - Buffer bindings: ARRAY_BUFFER, UNIFORM_BUFFER, etc. (except ELEMENT_ARRAY_BUFFER)
 *    - Texture bindings per unit (TEXTURE_BINDING_2D, etc.)
 *    - Viewport and scissor box
 *    - Clear colors (color, depth, stencil)
 *    - Enable/disable capabilities (BLEND, DEPTH_TEST, etc.)
 *    - Pixel store parameters (PACK_ALIGNMENT, UNPACK_FLIP_Y_WEBGL, etc.)
 *    - Blend state (equations, functions, color)
 *    - Depth state (func, range, mask)
 *    - Stencil state (func, ops, masks)
 *    - Color write mask
 *    - Cull face mode and front face
 *    - Line width
 *    - Polygon offset
 *    - Sample coverage
 *
 * 2. ONLY TRACKED WHEN DEFAULT VAO IS BOUND (Per-VAO State):
 *    - ELEMENT_ARRAY_BUFFER binding
 *    - Vertex attribute arrays (enabled/disabled per attribute index)
 *    - Vertex attribute pointers (buffer binding, size, type, stride, offset, normalized, divisor)
 *
 *    IMPORTANT: ARRAY_BUFFER is NOT per-VAO! It's always global.
 *    However, the buffer associated with each vertex attribute (captured when
 *    vertexAttribPointer is called) IS per-VAO state.
 *
 *    Note: When a non-default VAO is bound, we DON'T track these as we don't maintain
 *    per-VAO state. State updates to these will be silently accepted but not tracked.
 *
 * 3. ONLY TRACKED WHEN DEFAULT FRAMEBUFFER IS BOUND (Per-Framebuffer State):
 *    - Attachments (COLOR_ATTACHMENT0-15, DEPTH_ATTACHMENT, STENCIL_ATTACHMENT, DEPTH_STENCIL_ATTACHMENT)
 *      via framebufferTexture2D, framebufferRenderbuffer, framebufferTextureLayer
 *    - Draw buffers (drawBuffers) - which color attachments are written to
 *    - Read buffer (readBuffer) - which color attachment is read from
 *    Note: When a non-default framebuffer is bound, we DON'T track these as we don't
 *    maintain per-framebuffer state. State updates will be silently accepted but not tracked.
 *
 * 4. INDEXED BUFFER BINDINGS (Global Context State, Always Tracked):
 *    - Uniform buffer indexed bindings (bindBufferBase/Range with UNIFORM_BUFFER)
 *    - Transform feedback buffer indexed bindings (bindBufferBase/Range with TRANSFORM_FEEDBACK_BUFFER)
 *    Note: These are GLOBAL state, not per-object. bindBufferBase/Range updates BOTH
 *    the indexed binding and the generic binding.
 *
 * This is a deliberate simplification for tracking "current active context state" without
 * the complexity of per-object state management.
 */

/**
 * Comprehensive WebGL state structure
 */
export class WebGLTextureUnitState {
  texture2D: WebGLTexture | null | GLUndefined = GLUndefined;
  textureCubeMap: WebGLTexture | null | GLUndefined = GLUndefined;
  texture3D: WebGLTexture | null | GLUndefined = GLUndefined;
  texture2DArray: WebGLTexture | null | GLUndefined = GLUndefined;

  clone(): WebGLTextureUnitState {
    const cloned = new WebGLTextureUnitState();
    cloned.texture2D = this.texture2D;
    cloned.textureCubeMap = this.textureCubeMap;
    cloned.texture3D = this.texture3D;
    cloned.texture2DArray = this.texture2DArray;
    return cloned;
  }

  equals(other: WebGLTextureUnitState): boolean {
    return (
      this.texture2D === other.texture2D &&
      this.textureCubeMap === other.textureCubeMap &&
      this.texture3D === other.texture3D &&
      this.texture2DArray === other.texture2DArray
    );
  }
}

export class WebGLTextureState {
  activeTexture: number | GLUndefined = GLUndefined;
  textureUnits = new GLUnitMap<WebGLTextureUnitState>();

  clone(): WebGLTextureState {
    const cloned = new WebGLTextureState();
    cloned.activeTexture = this.activeTexture;
    cloned.textureUnits = this.textureUnits.clone();
    return cloned;
  }

  equals(other: WebGLTextureState): boolean {
    return (
      this.activeTexture === other.activeTexture && this.textureUnits.equals(other.textureUnits)
    );
  }
}

export class WebGLIndexedBufferBinding {
  buffer: WebGLBuffer | null | GLUndefined = GLUndefined;
  offset: number | GLUndefined = GLUndefined;
  size: number | GLUndefined = GLUndefined;

  clone(): WebGLIndexedBufferBinding {
    const cloned = new WebGLIndexedBufferBinding();
    cloned.buffer = this.buffer;
    cloned.offset = this.offset;
    cloned.size = this.size;
    return cloned;
  }

  equals(other: WebGLIndexedBufferBinding): boolean {
    return this.buffer === other.buffer && this.offset === other.offset && this.size === other.size;
  }
}

export class WebGLBufferState {
  arrayBuffer: WebGLBuffer | null | GLUndefined = GLUndefined;

  // Note: ELEMENT_ARRAY_BUFFER is NOT stored here!
  // Per OpenGL ES 3.0 spec section 2.10, ELEMENT_ARRAY_BUFFER binding is per-VAO state.
  // It is stored in WebGLPerVAOState.elementArrayBuffer instead.

  // Generic bindings (also affected by bindBufferBase/Range)
  uniformBuffer: WebGLBuffer | null | GLUndefined = GLUndefined;
  transformFeedbackBuffer: WebGLBuffer | null | GLUndefined = GLUndefined;

  // Indexed bindings (WebGL 2.0)
  // These are global context state, but bindBufferBase/Range also updates the generic binding
  uniformBufferBindings = new GLAttributeArray<WebGLIndexedBufferBinding>(
    GL_MAX_UNIFORM_BUFFER_BINDINGS
  );
  transformFeedbackBufferBindings = new GLAttributeArray<WebGLIndexedBufferBinding>(
    GL_MAX_TRANSFORM_FEEDBACK_SEPARATE_ATTRIBS
  );

  // Other global bindings
  pixelPackBuffer: WebGLBuffer | null | GLUndefined = GLUndefined;
  pixelUnpackBuffer: WebGLBuffer | null | GLUndefined = GLUndefined;
  copyReadBuffer: WebGLBuffer | null | GLUndefined = GLUndefined;
  copyWriteBuffer: WebGLBuffer | null | GLUndefined = GLUndefined;

  clone(): WebGLBufferState {
    const cloned = new WebGLBufferState();
    cloned.arrayBuffer = this.arrayBuffer;
    cloned.uniformBuffer = this.uniformBuffer;
    cloned.transformFeedbackBuffer = this.transformFeedbackBuffer;
    cloned.pixelPackBuffer = this.pixelPackBuffer;
    cloned.pixelUnpackBuffer = this.pixelUnpackBuffer;
    cloned.copyReadBuffer = this.copyReadBuffer;
    cloned.copyWriteBuffer = this.copyWriteBuffer;
    cloned.uniformBufferBindings = this.uniformBufferBindings.clone();
    cloned.transformFeedbackBufferBindings = this.transformFeedbackBufferBindings.clone();
    return cloned;
  }

  equals(other: WebGLBufferState): boolean {
    return (
      this.arrayBuffer === other.arrayBuffer &&
      this.uniformBuffer === other.uniformBuffer &&
      this.transformFeedbackBuffer === other.transformFeedbackBuffer &&
      this.pixelPackBuffer === other.pixelPackBuffer &&
      this.pixelUnpackBuffer === other.pixelUnpackBuffer &&
      this.copyReadBuffer === other.copyReadBuffer &&
      this.copyWriteBuffer === other.copyWriteBuffer &&
      this.uniformBufferBindings.equals(other.uniformBufferBindings) &&
      this.transformFeedbackBufferBindings.equals(other.transformFeedbackBufferBindings)
    );
  }
}

export class WebGLProgramState {
  currentProgram: WebGLProgram | null | GLUndefined = GLUndefined;

  clone(): WebGLProgramState {
    const cloned = new WebGLProgramState();
    cloned.currentProgram = this.currentProgram;
    return cloned;
  }

  equals(other: WebGLProgramState): boolean {
    return this.currentProgram === other.currentProgram;
  }
}

export class WebGLFramebufferAttachment {
  attachmentType: 'texture' | 'renderbuffer' | null | GLUndefined = GLUndefined;
  texture: WebGLTexture | null | GLUndefined = GLUndefined;
  renderbuffer: WebGLRenderbuffer | null | GLUndefined = GLUndefined;
  textureLevel: number | GLUndefined = GLUndefined;
  textureLayer: number | GLUndefined = GLUndefined; // For 3D textures or texture arrays
  textureCubeFace: number | GLUndefined = GLUndefined; // For cubemap faces

  clone(): WebGLFramebufferAttachment {
    const cloned = new WebGLFramebufferAttachment();
    cloned.attachmentType = this.attachmentType;
    cloned.texture = this.texture;
    cloned.renderbuffer = this.renderbuffer;
    cloned.textureLevel = this.textureLevel;
    cloned.textureLayer = this.textureLayer;
    cloned.textureCubeFace = this.textureCubeFace;
    return cloned;
  }

  equals(other: WebGLFramebufferAttachment): boolean {
    return (
      this.attachmentType === other.attachmentType &&
      this.texture === other.texture &&
      this.renderbuffer === other.renderbuffer &&
      this.textureLevel === other.textureLevel &&
      this.textureLayer === other.textureLayer &&
      this.textureCubeFace === other.textureCubeFace
    );
  }
}

export class WebGLFramebufferAttachments {
  // Color attachments (typically 0-7, but can query MAX_COLOR_ATTACHMENTS)
  [key: string]: WebGLFramebufferAttachment; // e.g., "COLOR_ATTACHMENT0"
}

export class WebGLDefaultFramebufferState {
  // Attachments for the default framebuffer (only valid when framebuffer === null)
  colorAttachments: WebGLFramebufferAttachments = new WebGLFramebufferAttachments();
  depthAttachment: WebGLFramebufferAttachment | null | GLUndefined = GLUndefined;
  stencilAttachment: WebGLFramebufferAttachment | null | GLUndefined = GLUndefined;
  depthStencilAttachment: WebGLFramebufferAttachment | null | GLUndefined = GLUndefined;
  // Draw buffers array (which color attachments are written to)
  drawBuffers: number[] | GLUndefined = GLUndefined;
  // Read buffer (which color attachment is read from)
  readBuffer: number | GLUndefined = GLUndefined;

  clone(): WebGLDefaultFramebufferState {
    const cloned = new WebGLDefaultFramebufferState();
    // Clone color attachments
    for (const [key, value] of Object.entries(this.colorAttachments)) {
      if (value instanceof WebGLFramebufferAttachment) {
        cloned.colorAttachments[key] = value.clone();
      }
    }
    cloned.depthAttachment = this.depthAttachment;
    cloned.stencilAttachment = this.stencilAttachment;
    cloned.depthStencilAttachment = this.depthStencilAttachment;
    cloned.drawBuffers = Array.isArray(this.drawBuffers) ? [...this.drawBuffers] : this.drawBuffers;
    cloned.readBuffer = this.readBuffer;
    return cloned;
  }

  equals(other: WebGLDefaultFramebufferState): boolean {
    // Compare color attachments
    const thisKeys = Object.keys(this.colorAttachments);
    const otherKeys = Object.keys(other.colorAttachments);
    if (thisKeys.length !== otherKeys.length) return false;
    const colorAttachmentsEqual = thisKeys.every(key => {
      const thisAttach = this.colorAttachments[key];
      const otherAttach = other.colorAttachments[key];
      if (!thisAttach || !otherAttach) return thisAttach === otherAttach;
      return thisAttach.equals(otherAttach);
    });

    // Compare draw buffers
    const drawBuffersEqual =
      this.drawBuffers === other.drawBuffers ||
      (Array.isArray(this.drawBuffers) &&
        Array.isArray(other.drawBuffers) &&
        this.drawBuffers.length === other.drawBuffers.length &&
        this.drawBuffers.every((v, i) => v === (other.drawBuffers as number[])[i]));

    return (
      colorAttachmentsEqual &&
      this.depthAttachment === other.depthAttachment &&
      this.stencilAttachment === other.stencilAttachment &&
      this.depthStencilAttachment === other.depthStencilAttachment &&
      drawBuffersEqual &&
      this.readBuffer === other.readBuffer
    );
  }
}

export class WebGLFramebufferState {
  drawFramebuffer: WebGLFramebuffer | null | GLUndefined = GLUndefined;
  readFramebuffer: WebGLFramebuffer | null | GLUndefined = GLUndefined;
  framebuffer: WebGLFramebuffer | null | GLUndefined = GLUndefined;
  // State for the default framebuffer (only tracked when framebuffer === null)
  defaultFramebufferState: WebGLDefaultFramebufferState = new WebGLDefaultFramebufferState();

  clone(): WebGLFramebufferState {
    const cloned = new WebGLFramebufferState();
    cloned.drawFramebuffer = this.drawFramebuffer;
    cloned.readFramebuffer = this.readFramebuffer;
    cloned.framebuffer = this.framebuffer;
    cloned.defaultFramebufferState = this.defaultFramebufferState.clone();
    return cloned;
  }

  equals(other: WebGLFramebufferState): boolean {
    return (
      this.drawFramebuffer === other.drawFramebuffer &&
      this.readFramebuffer === other.readFramebuffer &&
      this.framebuffer === other.framebuffer &&
      this.defaultFramebufferState.equals(other.defaultFramebufferState)
    );
  }
}

export class WebGLVertexAttribState {
  enabled: boolean | GLUndefined = GLUndefined;
  buffer: WebGLBuffer | null | GLUndefined = GLUndefined;
  size: number | GLUndefined = GLUndefined;
  type: number | GLUndefined = GLUndefined;
  normalized: boolean | GLUndefined = GLUndefined;
  stride: number | GLUndefined = GLUndefined;
  offset: number | GLUndefined = GLUndefined;
  divisor: number | GLUndefined = GLUndefined;

  clone(): WebGLVertexAttribState {
    const cloned = new WebGLVertexAttribState();
    cloned.enabled = this.enabled;
    cloned.buffer = this.buffer;
    cloned.size = this.size;
    cloned.type = this.type;
    cloned.normalized = this.normalized;
    cloned.stride = this.stride;
    cloned.offset = this.offset;
    cloned.divisor = this.divisor;
    return cloned;
  }

  equals(other: WebGLVertexAttribState): boolean {
    return (
      this.enabled === other.enabled &&
      this.buffer === other.buffer &&
      this.size === other.size &&
      this.type === other.type &&
      this.normalized === other.normalized &&
      this.stride === other.stride &&
      this.offset === other.offset &&
      this.divisor === other.divisor
    );
  }
}

/**
 * Per-VAO state - according to OpenGL ES 3.0 spec section 2.10,
 * ELEMENT_ARRAY_BUFFER binding is part of VAO state
 */
export class WebGLPerVAOState {
  // ELEMENT_ARRAY_BUFFER binding is per-VAO (spec: section 2.10, table 6.2)
  elementArrayBuffer: WebGLBuffer | null | GLUndefined = GLUndefined;
  // Vertex attribute state is also per-VAO
  attributes = new GLAttributeArray<WebGLVertexAttribState>(GL_MAX_VERTEX_ATTRIBS);

  clone(): WebGLPerVAOState {
    const cloned = new WebGLPerVAOState();
    cloned.elementArrayBuffer = this.elementArrayBuffer;
    cloned.attributes = this.attributes.clone();
    return cloned;
  }

  equals(other: WebGLPerVAOState): boolean {
    return (
      this.elementArrayBuffer === other.elementArrayBuffer &&
      this.attributes.equals(other.attributes)
    );
  }
}

export class WebGLVertexArrayState {
  // Currently bound VAO (null = default VAO)
  vertexArrayObject: WebGLVertexArrayObject | null | GLUndefined = GLUndefined;

  // Per-VAO state storage
  // Key: VAO object (null represents default VAO)
  // Value: Per-VAO state including ELEMENT_ARRAY_BUFFER and attributes
  vaoStates: Map<WebGLVertexArrayObject | null, WebGLPerVAOState> = new Map();

  clone(): WebGLVertexArrayState {
    const cloned = new WebGLVertexArrayState();
    cloned.vertexArrayObject = this.vertexArrayObject;

    // Clone all VAO states
    for (const [vao, state] of this.vaoStates.entries()) {
      cloned.vaoStates.set(vao, state.clone());
    }

    return cloned;
  }

  equals(other: WebGLVertexArrayState): boolean {
    if (this.vertexArrayObject !== other.vertexArrayObject) return false;
    if (this.vaoStates.size !== other.vaoStates.size) return false;

    // Compare all VAO states
    for (const [vao, state] of this.vaoStates.entries()) {
      const otherState = other.vaoStates.get(vao);
      if (!otherState || !state.equals(otherState)) return false;
    }

    return true;
  }

  /**
   * Get or create the state for the currently bound VAO
   */
  getCurrentVAOState(): WebGLPerVAOState {
    const vao = this.vertexArrayObject === GLUndefined ? null : this.vertexArrayObject;

    if (!this.vaoStates.has(vao)) {
      this.vaoStates.set(vao, new WebGLPerVAOState());
    }

    return this.vaoStates.get(vao)!;
  }
}

export class WebGLViewportState {
  viewport: Int32Array | GLUndefined = GLUndefined;
  scissorBox: Int32Array | GLUndefined = GLUndefined;

  clone(): WebGLViewportState {
    const cloned = new WebGLViewportState();
    cloned.viewport =
      this.viewport !== GLUndefined ? new Int32Array(this.viewport as Int32Array) : this.viewport;
    cloned.scissorBox =
      this.scissorBox !== GLUndefined
        ? new Int32Array(this.scissorBox as Int32Array)
        : this.scissorBox;
    return cloned;
  }

  equals(other: WebGLViewportState): boolean {
    const viewportEqual =
      this.viewport === other.viewport ||
      (this.viewport !== GLUndefined &&
        other.viewport !== GLUndefined &&
        (this.viewport as Int32Array).every((v, i) => v === (other.viewport as Int32Array)[i]));
    const scissorEqual =
      this.scissorBox === other.scissorBox ||
      (this.scissorBox !== GLUndefined &&
        other.scissorBox !== GLUndefined &&
        (this.scissorBox as Int32Array).every((v, i) => v === (other.scissorBox as Int32Array)[i]));
    return viewportEqual && scissorEqual;
  }
}

export class WebGLClearState {
  colorClearValue: Float32Array | GLUndefined = GLUndefined;
  depthClearValue: number | GLUndefined = GLUndefined;
  stencilClearValue: number | GLUndefined = GLUndefined;

  clone(): WebGLClearState {
    const cloned = new WebGLClearState();
    cloned.colorClearValue =
      this.colorClearValue !== GLUndefined
        ? new Float32Array(this.colorClearValue as Float32Array)
        : this.colorClearValue;
    cloned.depthClearValue = this.depthClearValue;
    cloned.stencilClearValue = this.stencilClearValue;
    return cloned;
  }

  equals(other: WebGLClearState): boolean {
    const colorEqual =
      this.colorClearValue === other.colorClearValue ||
      (this.colorClearValue !== GLUndefined &&
        other.colorClearValue !== GLUndefined &&
        (this.colorClearValue as Float32Array).every(
          (v, i) => v === (other.colorClearValue as Float32Array)[i]
        ));
    return (
      colorEqual &&
      this.depthClearValue === other.depthClearValue &&
      this.stencilClearValue === other.stencilClearValue
    );
  }
}

export class WebGLCapabilityState {
  blend: boolean | GLUndefined = GLUndefined;
  cullFace: boolean | GLUndefined = GLUndefined;
  depthTest: boolean | GLUndefined = GLUndefined;
  dither: boolean | GLUndefined = GLUndefined;
  polygonOffsetFill: boolean | GLUndefined = GLUndefined;
  sampleAlphaToCoverage: boolean | GLUndefined = GLUndefined;
  sampleCoverage: boolean | GLUndefined = GLUndefined;
  scissorTest: boolean | GLUndefined = GLUndefined;
  stencilTest: boolean | GLUndefined = GLUndefined;
  rasterDiscard: boolean | GLUndefined = GLUndefined;

  clone(): WebGLCapabilityState {
    const cloned = new WebGLCapabilityState();
    Object.assign(cloned, this);
    return cloned;
  }

  equals(other: WebGLCapabilityState): boolean {
    return (
      this.blend === other.blend &&
      this.cullFace === other.cullFace &&
      this.depthTest === other.depthTest &&
      this.dither === other.dither &&
      this.polygonOffsetFill === other.polygonOffsetFill &&
      this.sampleAlphaToCoverage === other.sampleAlphaToCoverage &&
      this.sampleCoverage === other.sampleCoverage &&
      this.scissorTest === other.scissorTest &&
      this.stencilTest === other.stencilTest &&
      this.rasterDiscard === other.rasterDiscard
    );
  }
}

export class WebGLPixelStoreState {
  packAlignment: number | GLUndefined = GLUndefined;
  unpackAlignment: number | GLUndefined = GLUndefined;
  unpackFlipY: boolean | GLUndefined = GLUndefined;
  unpackPremultiplyAlpha: boolean | GLUndefined = GLUndefined;
  packRowLength: number | GLUndefined = GLUndefined;
  packSkipPixels: number | GLUndefined = GLUndefined;
  packSkipRows: number | GLUndefined = GLUndefined;
  unpackRowLength: number | GLUndefined = GLUndefined;
  unpackImageHeight: number | GLUndefined = GLUndefined;
  unpackSkipPixels: number | GLUndefined = GLUndefined;
  unpackSkipRows: number | GLUndefined = GLUndefined;
  unpackSkipImages: number | GLUndefined = GLUndefined;

  clone(): WebGLPixelStoreState {
    const cloned = new WebGLPixelStoreState();
    Object.assign(cloned, this);
    return cloned;
  }

  equals(other: WebGLPixelStoreState): boolean {
    return (
      this.packAlignment === other.packAlignment &&
      this.unpackAlignment === other.unpackAlignment &&
      this.unpackFlipY === other.unpackFlipY &&
      this.unpackPremultiplyAlpha === other.unpackPremultiplyAlpha &&
      this.packRowLength === other.packRowLength &&
      this.packSkipPixels === other.packSkipPixels &&
      this.packSkipRows === other.packSkipRows &&
      this.unpackRowLength === other.unpackRowLength &&
      this.unpackImageHeight === other.unpackImageHeight &&
      this.unpackSkipPixels === other.unpackSkipPixels &&
      this.unpackSkipRows === other.unpackSkipRows &&
      this.unpackSkipImages === other.unpackSkipImages
    );
  }
}

export class WebGLBlendState {
  blendEquationRgb: number | GLUndefined = GLUndefined;
  blendEquationAlpha: number | GLUndefined = GLUndefined;
  blendSrcRgb: number | GLUndefined = GLUndefined;
  blendDstRgb: number | GLUndefined = GLUndefined;
  blendSrcAlpha: number | GLUndefined = GLUndefined;
  blendDstAlpha: number | GLUndefined = GLUndefined;
  blendColor: Float32Array | GLUndefined = GLUndefined;

  clone(): WebGLBlendState {
    const cloned = new WebGLBlendState();
    cloned.blendEquationRgb = this.blendEquationRgb;
    cloned.blendEquationAlpha = this.blendEquationAlpha;
    cloned.blendSrcRgb = this.blendSrcRgb;
    cloned.blendDstRgb = this.blendDstRgb;
    cloned.blendSrcAlpha = this.blendSrcAlpha;
    cloned.blendDstAlpha = this.blendDstAlpha;
    cloned.blendColor =
      this.blendColor !== GLUndefined
        ? new Float32Array(this.blendColor as Float32Array)
        : this.blendColor;
    return cloned;
  }

  equals(other: WebGLBlendState): boolean {
    const blendColorEqual =
      this.blendColor === other.blendColor ||
      (this.blendColor !== GLUndefined &&
        other.blendColor !== GLUndefined &&
        (this.blendColor as Float32Array).every(
          (v, i) => v === (other.blendColor as Float32Array)[i]
        ));
    return (
      this.blendEquationRgb === other.blendEquationRgb &&
      this.blendEquationAlpha === other.blendEquationAlpha &&
      this.blendSrcRgb === other.blendSrcRgb &&
      this.blendDstRgb === other.blendDstRgb &&
      this.blendSrcAlpha === other.blendSrcAlpha &&
      this.blendDstAlpha === other.blendDstAlpha &&
      blendColorEqual
    );
  }
}

export class WebGLDepthState {
  depthFunc: number | GLUndefined = GLUndefined;
  depthRange: Float32Array | GLUndefined = GLUndefined;
  depthWritemask: boolean | GLUndefined = GLUndefined;

  clone(): WebGLDepthState {
    const cloned = new WebGLDepthState();
    cloned.depthFunc = this.depthFunc;
    cloned.depthRange =
      this.depthRange !== GLUndefined
        ? new Float32Array(this.depthRange as Float32Array)
        : this.depthRange;
    cloned.depthWritemask = this.depthWritemask;
    return cloned;
  }

  equals(other: WebGLDepthState): boolean {
    const depthRangeEqual =
      this.depthRange === other.depthRange ||
      (this.depthRange !== GLUndefined &&
        other.depthRange !== GLUndefined &&
        (this.depthRange as Float32Array).every(
          (v, i) => v === (other.depthRange as Float32Array)[i]
        ));
    return (
      this.depthFunc === other.depthFunc &&
      depthRangeEqual &&
      this.depthWritemask === other.depthWritemask
    );
  }
}

export class WebGLStencilState {
  stencilFunc: number | GLUndefined = GLUndefined;
  stencilRef: number | GLUndefined = GLUndefined;
  stencilValueMask: number | GLUndefined = GLUndefined;
  stencilWritemask: number | GLUndefined = GLUndefined;
  stencilFail: number | GLUndefined = GLUndefined;
  stencilPassDepthFail: number | GLUndefined = GLUndefined;
  stencilPassDepthPass: number | GLUndefined = GLUndefined;
  stencilBackFunc: number | GLUndefined = GLUndefined;
  stencilBackRef: number | GLUndefined = GLUndefined;
  stencilBackValueMask: number | GLUndefined = GLUndefined;
  stencilBackWritemask: number | GLUndefined = GLUndefined;
  stencilBackFail: number | GLUndefined = GLUndefined;
  stencilBackPassDepthFail: number | GLUndefined = GLUndefined;
  stencilBackPassDepthPass: number | GLUndefined = GLUndefined;

  clone(): WebGLStencilState {
    const cloned = new WebGLStencilState();
    Object.assign(cloned, this);
    return cloned;
  }

  equals(other: WebGLStencilState): boolean {
    return (
      this.stencilFunc === other.stencilFunc &&
      this.stencilRef === other.stencilRef &&
      this.stencilValueMask === other.stencilValueMask &&
      this.stencilWritemask === other.stencilWritemask &&
      this.stencilFail === other.stencilFail &&
      this.stencilPassDepthFail === other.stencilPassDepthFail &&
      this.stencilPassDepthPass === other.stencilPassDepthPass &&
      this.stencilBackFunc === other.stencilBackFunc &&
      this.stencilBackRef === other.stencilBackRef &&
      this.stencilBackValueMask === other.stencilBackValueMask &&
      this.stencilBackWritemask === other.stencilBackWritemask &&
      this.stencilBackFail === other.stencilBackFail &&
      this.stencilBackPassDepthFail === other.stencilBackPassDepthFail &&
      this.stencilBackPassDepthPass === other.stencilBackPassDepthPass
    );
  }
}

export class WebGLColorState {
  colorWritemask: boolean[] | GLUndefined = GLUndefined;

  clone(): WebGLColorState {
    const cloned = new WebGLColorState();
    cloned.colorWritemask =
      this.colorWritemask !== GLUndefined
        ? [...(this.colorWritemask as boolean[])]
        : this.colorWritemask;
    return cloned;
  }

  equals(other: WebGLColorState): boolean {
    return (
      this.colorWritemask === other.colorWritemask ||
      (this.colorWritemask !== GLUndefined &&
        other.colorWritemask !== GLUndefined &&
        (this.colorWritemask as boolean[]).every(
          (v, i) => v === (other.colorWritemask as boolean[])[i]
        ))
    );
  }
}

export class WebGLCullingState {
  cullFaceMode: number | GLUndefined = GLUndefined;
  frontFace: number | GLUndefined = GLUndefined;

  clone(): WebGLCullingState {
    const cloned = new WebGLCullingState();
    Object.assign(cloned, this);
    return cloned;
  }

  equals(other: WebGLCullingState): boolean {
    return this.cullFaceMode === other.cullFaceMode && this.frontFace === other.frontFace;
  }
}

export class WebGLLineState {
  lineWidth: number | GLUndefined = GLUndefined;

  clone(): WebGLLineState {
    const cloned = new WebGLLineState();
    cloned.lineWidth = this.lineWidth;
    return cloned;
  }

  equals(other: WebGLLineState): boolean {
    return this.lineWidth === other.lineWidth;
  }
}

export class WebGLPolygonOffsetState {
  polygonOffsetFactor: number | GLUndefined = GLUndefined;
  polygonOffsetUnits: number | GLUndefined = GLUndefined;

  clone(): WebGLPolygonOffsetState {
    const cloned = new WebGLPolygonOffsetState();
    Object.assign(cloned, this);
    return cloned;
  }

  equals(other: WebGLPolygonOffsetState): boolean {
    return (
      this.polygonOffsetFactor === other.polygonOffsetFactor &&
      this.polygonOffsetUnits === other.polygonOffsetUnits
    );
  }
}

export class WebGLSampleState {
  sampleCoverageValue: number | GLUndefined = GLUndefined;
  sampleCoverageInvert: boolean | GLUndefined = GLUndefined;

  clone(): WebGLSampleState {
    const cloned = new WebGLSampleState();
    Object.assign(cloned, this);
    return cloned;
  }

  equals(other: WebGLSampleState): boolean {
    return (
      this.sampleCoverageValue === other.sampleCoverageValue &&
      this.sampleCoverageInvert === other.sampleCoverageInvert
    );
  }
}

export class WebGLTransformFeedbackState {
  transformFeedback: WebGLTransformFeedback | null | GLUndefined = GLUndefined;
  transformFeedbackActive: boolean | GLUndefined = GLUndefined;
  transformFeedbackPaused: boolean | GLUndefined = GLUndefined;

  clone(): WebGLTransformFeedbackState {
    const cloned = new WebGLTransformFeedbackState();
    Object.assign(cloned, this);
    return cloned;
  }

  equals(other: WebGLTransformFeedbackState): boolean {
    return (
      this.transformFeedback === other.transformFeedback &&
      this.transformFeedbackActive === other.transformFeedbackActive &&
      this.transformFeedbackPaused === other.transformFeedbackPaused
    );
  }
}

export class WebGLRenderbufferState {
  renderbuffer: WebGLRenderbuffer | null | GLUndefined = GLUndefined;

  clone(): WebGLRenderbufferState {
    const cloned = new WebGLRenderbufferState();
    cloned.renderbuffer = this.renderbuffer;
    return cloned;
  }

  equals(other: WebGLRenderbufferState): boolean {
    return this.renderbuffer === other.renderbuffer;
  }
}

export class WebGLSamplerState {
  // Sampler bindings per texture unit (WebGL 2.0)
  samplerBindings: { [unit: number]: WebGLSampler | null | GLUndefined } = {};

  clone(): WebGLSamplerState {
    const cloned = new WebGLSamplerState();
    // Shallow copy is fine since samplerBindings contains WebGL objects (not cloneable state objects)
    Object.assign(cloned.samplerBindings, this.samplerBindings);
    return cloned;
  }

  equals(other: WebGLSamplerState): boolean {
    const thisKeys = Object.keys(this.samplerBindings);
    const otherKeys = Object.keys(other.samplerBindings);
    if (thisKeys.length !== otherKeys.length) return false;
    return thisKeys.every(
      key => this.samplerBindings[Number(key)] === other.samplerBindings[Number(key)]
    );
  }
}

export class WebGLQueryState {
  // Active queries per target (WebGL 2.0)
  // Only one query can be active per target at a time
  currentOcclusionQuery: WebGLQuery | null | GLUndefined = GLUndefined;
  currentTransformFeedbackPrimitivesWritten: WebGLQuery | null | GLUndefined = GLUndefined;
  currentAnySamplesPassed: WebGLQuery | null | GLUndefined = GLUndefined;
  currentAnySamplesPassedConservative: WebGLQuery | null | GLUndefined = GLUndefined;

  clone(): WebGLQueryState {
    const cloned = new WebGLQueryState();
    Object.assign(cloned, this);
    return cloned;
  }

  equals(other: WebGLQueryState): boolean {
    return (
      this.currentOcclusionQuery === other.currentOcclusionQuery &&
      this.currentTransformFeedbackPrimitivesWritten ===
        other.currentTransformFeedbackPrimitivesWritten &&
      this.currentAnySamplesPassed === other.currentAnySamplesPassed &&
      this.currentAnySamplesPassedConservative === other.currentAnySamplesPassedConservative
    );
  }
}

export class WebGLState {
  // Texture state
  textures?: WebGLTextureState;

  // Buffer state
  buffers?: WebGLBufferState;

  // Program state
  programs?: WebGLProgramState;

  // Framebuffer state
  framebuffers?: WebGLFramebufferState;

  // Vertex array state
  vertexArrays?: WebGLVertexArrayState;

  // Viewport and scissor
  viewport?: WebGLViewportState;

  // Clear values
  clear?: WebGLClearState;

  // Capabilities (enable/disable state)
  capabilities?: WebGLCapabilityState;

  // Pixel store parameters
  pixelStore?: WebGLPixelStoreState;

  // Blend state
  blend?: WebGLBlendState;

  // Depth state
  depth?: WebGLDepthState;

  // Stencil state
  stencil?: WebGLStencilState;

  // Color state
  color?: WebGLColorState;

  // Face culling
  culling?: WebGLCullingState;

  // Line rendering
  line?: WebGLLineState;

  // Polygon offset
  polygonOffset?: WebGLPolygonOffsetState;

  // Sample coverage
  sample?: WebGLSampleState;

  // Transform feedback (WebGL 2.0)
  transformFeedback?: WebGLTransformFeedbackState;

  // Renderbuffer
  renderbuffer?: WebGLRenderbufferState;

  // Sampler state (WebGL 2.0)
  samplers?: WebGLSamplerState;

  // Query state (WebGL 2.0)
  queries?: WebGLQueryState;

  // Buffer lifecycle tracking (for validation without GPU calls)
  validBuffers = new Set<WebGLBuffer>();

  readonly constants = new WebGLConstants();

  // Lazy getters for state components
  getTexturesState(): WebGLTextureState {
    if (!this.textures) {
      this.textures = new WebGLTextureState();
      this.textures.activeTexture = this.constants.TEXTURE0;
    }
    return this.textures;
  }

  getOrCreateTextureUnit(unit: string): WebGLTextureUnitState {
    const textures = this.getTexturesState();
    if (!textures.textureUnits[unit]) {
      textures.textureUnits[unit] = new WebGLTextureUnitState();
    }
    return textures.textureUnits[unit];
  }

  getBuffersState(): WebGLBufferState {
    if (!this.buffers) {
      this.buffers = new WebGLBufferState();
    }
    return this.buffers;
  }

  getProgramsState(): WebGLProgramState {
    if (!this.programs) {
      this.programs = new WebGLProgramState();
    }
    return this.programs;
  }

  getFramebuffersState(): WebGLFramebufferState {
    if (!this.framebuffers) {
      this.framebuffers = new WebGLFramebufferState();
      this.framebuffers.defaultFramebufferState.drawBuffers = [this.constants.BACK || 0x0405]; // Default to BACK
      this.framebuffers.defaultFramebufferState.readBuffer = this.constants.BACK || 0x0405;
    }
    return this.framebuffers;
  }

  getVertexArraysState(): WebGLVertexArrayState {
    if (!this.vertexArrays) {
      this.vertexArrays = new WebGLVertexArrayState();
    }
    return this.vertexArrays;
  }

  getOrCreateVertexAttrib(index: number): WebGLVertexAttribState {
    const vertexArrays = this.getVertexArraysState();
    const vaoState = vertexArrays.getCurrentVAOState();
    const existing = vaoState.attributes.get(index);
    if (!existing || existing === GLUndefined) {
      const newAttrib = new WebGLVertexAttribState();
      vaoState.attributes.set(index, newAttrib);
      return newAttrib;
    }
    return existing as WebGLVertexAttribState;
  }

  getViewportState(): WebGLViewportState {
    if (!this.viewport) {
      this.viewport = new WebGLViewportState();
    }
    return this.viewport;
  }

  getClearState(): WebGLClearState {
    if (!this.clear) {
      this.clear = new WebGLClearState();
    }
    return this.clear;
  }

  getCapabilitiesState(): WebGLCapabilityState {
    if (!this.capabilities) {
      this.capabilities = new WebGLCapabilityState();
    }
    return this.capabilities;
  }

  getPixelStoreState(): WebGLPixelStoreState {
    if (!this.pixelStore) {
      this.pixelStore = new WebGLPixelStoreState();
    }
    return this.pixelStore;
  }

  getBlendState(): WebGLBlendState {
    if (!this.blend) {
      this.blend = new WebGLBlendState();
    }
    return this.blend;
  }

  getDepthState(): WebGLDepthState {
    if (!this.depth) {
      this.depth = new WebGLDepthState();
    }
    return this.depth;
  }

  getStencilState(): WebGLStencilState {
    if (!this.stencil) {
      this.stencil = new WebGLStencilState();
    }
    return this.stencil;
  }

  getColorState(): WebGLColorState {
    if (!this.color) {
      this.color = new WebGLColorState();
    }
    return this.color;
  }

  getCullingState(): WebGLCullingState {
    if (!this.culling) {
      this.culling = new WebGLCullingState();
    }
    return this.culling;
  }

  getLineState(): WebGLLineState {
    if (!this.line) {
      this.line = new WebGLLineState();
    }
    return this.line;
  }

  getPolygonOffsetState(): WebGLPolygonOffsetState {
    if (!this.polygonOffset) {
      this.polygonOffset = new WebGLPolygonOffsetState();
    }
    return this.polygonOffset;
  }

  getSampleState(): WebGLSampleState {
    if (!this.sample) {
      this.sample = new WebGLSampleState();
    }
    return this.sample;
  }

  getTransformFeedbackState(): WebGLTransformFeedbackState {
    if (!this.transformFeedback) {
      this.transformFeedback = new WebGLTransformFeedbackState();
    }
    return this.transformFeedback;
  }

  getRenderbufferState(): WebGLRenderbufferState {
    if (!this.renderbuffer) {
      this.renderbuffer = new WebGLRenderbufferState();
    }
    return this.renderbuffer;
  }

  getSamplersState(): WebGLSamplerState {
    if (!this.samplers) {
      this.samplers = new WebGLSamplerState();
    }
    return this.samplers;
  }

  getQueriesState(): WebGLQueryState {
    if (!this.queries) {
      this.queries = new WebGLQueryState();
    }
    return this.queries;
  }

  // Public state accessors
  getState(): WebGLState {
    return this;
  }

  /**
   * Clone the current state into a new WebGLState object
   * This creates a deep clone of the state properties
   * Note: WebGL objects (buffers, textures, etc.) are not cloned, only references
   */
  clone(): WebGLState {
    const cloned = new WebGLState();

    // Clone each state property using their clone methods
    if (this.buffers) cloned.buffers = this.buffers.clone();
    if (this.vertexArrays) cloned.vertexArrays = this.vertexArrays.clone();
    if (this.textures) cloned.textures = this.textures.clone();
    if (this.samplers) cloned.samplers = this.samplers.clone();
    if (this.programs) cloned.programs = this.programs.clone();
    if (this.framebuffers) cloned.framebuffers = this.framebuffers.clone();
    if (this.renderbuffer) cloned.renderbuffer = this.renderbuffer.clone();
    if (this.transformFeedback) cloned.transformFeedback = this.transformFeedback.clone();
    if (this.viewport) cloned.viewport = this.viewport.clone();
    if (this.capabilities) cloned.capabilities = this.capabilities.clone();
    if (this.clear) cloned.clear = this.clear.clone();
    if (this.blend) cloned.blend = this.blend.clone();
    if (this.depth) cloned.depth = this.depth.clone();
    if (this.stencil) cloned.stencil = this.stencil.clone();
    if (this.color) cloned.color = this.color.clone();
    if (this.culling) cloned.culling = this.culling.clone();
    if (this.line) cloned.line = this.line.clone();
    if (this.polygonOffset) cloned.polygonOffset = this.polygonOffset.clone();
    if (this.sample) cloned.sample = this.sample.clone();
    if (this.pixelStore) cloned.pixelStore = this.pixelStore.clone();
    if (this.queries) cloned.queries = this.queries.clone();

    // Clone validBuffers Set
    cloned.validBuffers = new Set(this.validBuffers);

    return cloned;
  }
}

/**
 * WebGLStateTracker - A state-only WebGL context that mimics WebGL2RenderingContext
 *
 * This class provides the same interface as WebGL2RenderingContext but only updates
 * internal state without making actual WebGL calls. Useful for testing, debugging,
 * and state tracking without GPU dependencies.
 */
/**
 * WebGL Constants
 */
export class WebGLConstants {
  // Buffer targets
  readonly ARRAY_BUFFER = 0x8892;
  readonly ELEMENT_ARRAY_BUFFER = 0x8893;
  readonly UNIFORM_BUFFER = 0x8a11;
  readonly TRANSFORM_FEEDBACK_BUFFER = 0x8c8e;
  readonly PIXEL_PACK_BUFFER = 0x88eb;
  readonly PIXEL_UNPACK_BUFFER = 0x88ec;
  readonly COPY_READ_BUFFER = 0x8f36;
  readonly COPY_WRITE_BUFFER = 0x8f37;

  // Texture targets and units
  readonly TEXTURE0 = 0x84c0;
  readonly TEXTURE_2D = 0x0de1;
  readonly TEXTURE_CUBE_MAP = 0x8513;
  readonly TEXTURE_3D = 0x806f;
  readonly TEXTURE_2D_ARRAY = 0x8c1a;

  // Framebuffer targets
  readonly FRAMEBUFFER = 0x8d40;
  readonly DRAW_FRAMEBUFFER = 0x8ca9;
  readonly READ_FRAMEBUFFER = 0x8ca8;

  // Capabilities
  readonly BLEND = 0x0be2;
  readonly CULL_FACE = 0x0b44;
  readonly DEPTH_TEST = 0x0b71;
  readonly DITHER = 0x0bd0;
  readonly POLYGON_OFFSET_FILL = 0x8037;
  readonly SAMPLE_ALPHA_TO_COVERAGE = 0x809e;
  readonly SAMPLE_COVERAGE = 0x80a0;
  readonly SCISSOR_TEST = 0x0c11;
  readonly STENCIL_TEST = 0x0b90;
  readonly RASTERIZER_DISCARD = 0x8c89;

  // Blend equations
  readonly FUNC_ADD = 0x8006;
  readonly FUNC_SUBTRACT = 0x800a;

  // Blend functions
  readonly ZERO = 0;
  readonly ONE = 1;
  readonly SRC_ALPHA = 0x0302;
  readonly ONE_MINUS_SRC_ALPHA = 0x0303;

  // Depth functions
  readonly NEVER = 0x0200;
  readonly LESS = 0x0201;
  readonly EQUAL = 0x0202;
  readonly LEQUAL = 0x0203;

  // Stencil operations
  readonly KEEP = 0x1e00;
  readonly REPLACE = 0x1e01;
  readonly INCR = 0x1e02;

  // Stencil functions
  readonly ALWAYS = 0x0207;

  // Culling
  readonly FRONT = 0x0404;
  readonly BACK = 0x0405;
  readonly FRONT_AND_BACK = 0x0408;
  readonly CW = 0x0900;
  readonly CCW = 0x0901;

  // Pixel store parameters
  readonly PACK_ALIGNMENT = 0x0d05;
  readonly UNPACK_ALIGNMENT = 0x0cf5;
  readonly UNPACK_FLIP_Y_WEBGL = 0x9240;
  readonly UNPACK_PREMULTIPLY_ALPHA_WEBGL = 0x9241;
  readonly PACK_ROW_LENGTH = 0x0d02;
  readonly PACK_SKIP_PIXELS = 0x0d04;
  readonly PACK_SKIP_ROWS = 0x0d03;
  readonly UNPACK_ROW_LENGTH = 0x0cf2;
  readonly UNPACK_IMAGE_HEIGHT = 0x806e;
  readonly UNPACK_SKIP_PIXELS = 0x0cf4;
  readonly UNPACK_SKIP_ROWS = 0x0cf3;
  readonly UNPACK_SKIP_IMAGES = 0x806d;

  // Framebuffer attachments
  readonly COLOR_ATTACHMENT0 = 0x8ce0;
  readonly DEPTH_ATTACHMENT = 0x8d00;
  readonly STENCIL_ATTACHMENT = 0x8d20;
  readonly DEPTH_STENCIL_ATTACHMENT = 0x821a;

  // Query targets
  readonly ANY_SAMPLES_PASSED = 0x8c2f;
  readonly ANY_SAMPLES_PASSED_CONSERVATIVE = 0x8d6a;
  readonly TRANSFORM_FEEDBACK_PRIMITIVES_WRITTEN = 0x8c88;

  // Data types
  readonly BYTE = 0x1400;
  readonly UNSIGNED_BYTE = 0x1401;
  readonly SHORT = 0x1402;
  readonly UNSIGNED_SHORT = 0x1403;
  readonly INT = 0x1404;
  readonly UNSIGNED_INT = 0x1405;
  readonly FLOAT = 0x1406;

  // Renderbuffer
  readonly RENDERBUFFER = 0x8d41;

  // Transform feedback
  readonly TRANSFORM_FEEDBACK = 0x8e22;

  // Texture parameters
  readonly TEXTURE_MIN_FILTER = 0x2801;
  readonly LINEAR = 0x2601;

  // Draw modes
  readonly TRIANGLES = 0x0004;
  readonly POINTS = 0x0000;

  // Buffer usage
  readonly STATIC_DRAW = 0x88e4;
}

export class WebGLStateTracker {
  private state: WebGLState = new WebGLState();
  readonly constants = this.state.constants;

  constructor() {
    // State is created in field initializer
  }

  // Buffer lifecycle tracking methods
  createBuffer(buffer: WebGLBuffer): void {
    this.state.validBuffers.add(buffer);
  }

  deleteBuffer(buffer: WebGLBuffer): void {
    this.state.validBuffers.delete(buffer);
  }

  isValidBuffer(buffer: WebGLBuffer | null): boolean {
    if (!buffer) return false;
    return this.state.validBuffers.has(buffer);
  }

  // Buffer binding methods
  bindBuffer(target: number, buffer: WebGLBuffer | null): void {
    const buffers = this.state.getBuffersState();
    switch (target) {
      case this.constants.ARRAY_BUFFER:
        buffers.arrayBuffer = buffer;
        break;
      case this.constants.ELEMENT_ARRAY_BUFFER:
        {
          // ELEMENT_ARRAY_BUFFER is per-VAO state (OpenGL ES 3.0 spec section 2.10)
          // Store it in the currently bound VAO's state
          const vertexArrays = this.state.getVertexArraysState();
          const vaoState = vertexArrays.getCurrentVAOState();
          vaoState.elementArrayBuffer = buffer;
        }
        break;
      case this.constants.UNIFORM_BUFFER:
        buffers.uniformBuffer = buffer;
        break;
      case this.constants.TRANSFORM_FEEDBACK_BUFFER:
        buffers.transformFeedbackBuffer = buffer;
        break;
      case this.constants.PIXEL_PACK_BUFFER:
        buffers.pixelPackBuffer = buffer;
        break;
      case this.constants.PIXEL_UNPACK_BUFFER:
        buffers.pixelUnpackBuffer = buffer;
        break;
      case this.constants.COPY_READ_BUFFER:
        buffers.copyReadBuffer = buffer;
        break;
      case this.constants.COPY_WRITE_BUFFER:
        buffers.copyWriteBuffer = buffer;
        break;
    }
  }

  // Vertex Array Object methods
  bindVertexArray(vao: WebGLVertexArrayObject | null): void {
    const vertexArrays = this.state.getVertexArraysState();
    vertexArrays.vertexArrayObject = vao;

    // Ensure a vaoStates entry exists for this VAO
    // This allows us to reliably detect if a VAO was deleted (missing from vaoStates)
    if (!vertexArrays.vaoStates.has(vao)) {
      vertexArrays.vaoStates.set(vao, new WebGLPerVAOState());
    }

    // Note: When switching VAOs, the ELEMENT_ARRAY_BUFFER binding is automatically
    // switched to the new VAO's ELEMENT_ARRAY_BUFFER (per OpenGL ES 3.0 spec section 2.10)
    // This happens automatically via the per-VAO state mechanism.
  }

  deleteVertexArray(vao: WebGLVertexArrayObject | null): void {
    if (!vao) return;

    const vertexArrays = this.state.getVertexArraysState();

    // If the deleted VAO is currently bound, bind to null (default VAO)
    // Per WebGL spec: "If the deleted object is currently bound, the binding reverts to 0"
    if (vertexArrays.vertexArrayObject === vao) {
      vertexArrays.vertexArrayObject = null;
    }

    // Remove the VAO state to prevent memory leaks
    vertexArrays.vaoStates.delete(vao);
  }

  // Vertex attribute methods (per-VAO state - OpenGL ES 3.0 spec section 2.10)
  // Now tracked for ALL VAOs, not just default
  enableVertexAttribArray(index: number): void {
    const attrib = this.state.getOrCreateVertexAttrib(index);
    attrib.enabled = true;
  }

  disableVertexAttribArray(index: number): void {
    const attrib = this.state.getOrCreateVertexAttrib(index);
    attrib.enabled = false;
  }

  vertexAttribPointer(
    index: number,
    size: number,
    type: number,
    normalized: boolean,
    stride: number,
    offset: number
  ): void {
    const attrib = this.state.getOrCreateVertexAttrib(index);
    // Capture the current ARRAY_BUFFER binding
    const buffers = this.state.buffers;
    attrib.buffer = buffers?.arrayBuffer || GLUndefined;
    attrib.size = size;
    attrib.type = type;
    attrib.normalized = normalized;
    attrib.stride = stride;
    attrib.offset = offset;
  }

  vertexAttribIPointer(
    index: number,
    size: number,
    type: number,
    stride: number,
    offset: number
  ): void {
    // Same as vertexAttribPointer but for integer attributes
    const attrib = this.state.getOrCreateVertexAttrib(index);
    const buffers = this.state.buffers;
    attrib.buffer = buffers?.arrayBuffer || GLUndefined;
    attrib.size = size;
    attrib.type = type;
    attrib.normalized = false; // Integer attributes are never normalized
    attrib.stride = stride;
    attrib.offset = offset;
  }

  vertexAttribDivisor(index: number, divisor: number): void {
    const attrib = this.state.getOrCreateVertexAttrib(index);
    attrib.divisor = divisor;
  }

  // Texture methods
  activeTexture(texture: number): void {
    const textures = this.state.getTexturesState();
    const unitIndex = texture - this.constants.TEXTURE0;

    // Validate unit index is within valid range
    if (unitIndex < 0 || unitIndex >= GL_MAX_COMBINED_TEXTURE_IMAGE_UNITS) {
      console.warn(`Invalid activeTexture value: ${texture} (unit index: ${unitIndex})`);
      return;
    }

    textures.activeTexture = texture;
  }

  bindTexture(target: number, texture: WebGLTexture | null): void {
    const textures = this.state.getTexturesState();
    const activeTextureValue =
      textures.activeTexture === GLUndefined
        ? this.constants.TEXTURE0
        : (textures.activeTexture as number);
    const unitIndex = activeTextureValue - this.constants.TEXTURE0;

    // Validate unit index is within valid range
    if (unitIndex < 0 || unitIndex >= GL_MAX_COMBINED_TEXTURE_IMAGE_UNITS) {
      console.warn(
        `Invalid texture unit index: ${unitIndex} (activeTexture: ${activeTextureValue})`
      );
      return;
    }

    const unitKey = `TEXTURE${unitIndex}`;

    if (!textures.textureUnits[unitKey]) {
      textures.textureUnits[unitKey] = new WebGLTextureUnitState();
    }

    switch (target) {
      case this.constants.TEXTURE_2D:
        textures.textureUnits[unitKey].texture2D = texture;
        break;
      case this.constants.TEXTURE_CUBE_MAP:
        textures.textureUnits[unitKey].textureCubeMap = texture;
        break;
      case this.constants.TEXTURE_3D:
        textures.textureUnits[unitKey].texture3D = texture;
        break;
      case this.constants.TEXTURE_2D_ARRAY:
        textures.textureUnits[unitKey].texture2DArray = texture;
        break;
    }
  }

  // Program methods
  useProgram(program: WebGLProgram | null): void {
    const programs = this.state.getProgramsState();
    programs.currentProgram = program;
  }

  // Framebuffer methods
  bindFramebuffer(target: number, framebuffer: WebGLFramebuffer | null): void {
    const framebuffers = this.state.getFramebuffersState();
    switch (target) {
      case this.constants.FRAMEBUFFER:
        // FRAMEBUFFER target binds to both DRAW_FRAMEBUFFER and READ_FRAMEBUFFER
        framebuffers.framebuffer = framebuffer;
        framebuffers.drawFramebuffer = framebuffer;
        framebuffers.readFramebuffer = framebuffer;
        break;
      case this.constants.DRAW_FRAMEBUFFER:
        framebuffers.drawFramebuffer = framebuffer;
        break;
      case this.constants.READ_FRAMEBUFFER:
        framebuffers.readFramebuffer = framebuffer;
        break;
    }
  }

  // Capability methods
  enable(cap: number): void {
    const capabilities = this.state.getCapabilitiesState();
    switch (cap) {
      case this.constants.BLEND:
        capabilities.blend = true;
        break;
      case this.constants.CULL_FACE:
        capabilities.cullFace = true;
        break;
      case this.constants.DEPTH_TEST:
        capabilities.depthTest = true;
        break;
      case this.constants.DITHER:
        capabilities.dither = true;
        break;
      case this.constants.POLYGON_OFFSET_FILL:
        capabilities.polygonOffsetFill = true;
        break;
      case this.constants.SAMPLE_ALPHA_TO_COVERAGE:
        capabilities.sampleAlphaToCoverage = true;
        break;
      case this.constants.SAMPLE_COVERAGE:
        capabilities.sampleCoverage = true;
        break;
      case this.constants.SCISSOR_TEST:
        capabilities.scissorTest = true;
        break;
      case this.constants.STENCIL_TEST:
        capabilities.stencilTest = true;
        break;
      case this.constants.RASTERIZER_DISCARD:
        capabilities.rasterDiscard = true;
        break;
    }
  }

  disable(cap: number): void {
    const capabilities = this.state.getCapabilitiesState();
    switch (cap) {
      case this.constants.BLEND:
        capabilities.blend = false;
        break;
      case this.constants.CULL_FACE:
        capabilities.cullFace = false;
        break;
      case this.constants.DEPTH_TEST:
        capabilities.depthTest = false;
        break;
      case this.constants.DITHER:
        capabilities.dither = false;
        break;
      case this.constants.POLYGON_OFFSET_FILL:
        capabilities.polygonOffsetFill = false;
        break;
      case this.constants.SAMPLE_ALPHA_TO_COVERAGE:
        capabilities.sampleAlphaToCoverage = false;
        break;
      case this.constants.SAMPLE_COVERAGE:
        capabilities.sampleCoverage = false;
        break;
      case this.constants.SCISSOR_TEST:
        capabilities.scissorTest = false;
        break;
      case this.constants.STENCIL_TEST:
        capabilities.stencilTest = false;
        break;
      case this.constants.RASTERIZER_DISCARD:
        capabilities.rasterDiscard = false;
        break;
    }
  }

  // Viewport methods
  viewport(x: number, y: number, width: number, height: number): void {
    const viewportState = this.state.getViewportState();
    if (!isDefined(viewportState.viewport)) {
      viewportState.viewport = new Int32Array(4);
    }
    const arr = viewportState.viewport as Int32Array;
    arr[0] = x;
    arr[1] = y;
    arr[2] = width;
    arr[3] = height;
  }

  scissor(x: number, y: number, width: number, height: number): void {
    const viewportState = this.state.getViewportState();
    if (!isDefined(viewportState.scissorBox)) {
      viewportState.scissorBox = new Int32Array(4);
    }
    const arr = viewportState.scissorBox as Int32Array;
    arr[0] = x;
    arr[1] = y;
    arr[2] = width;
    arr[3] = height;
  }

  // Clear methods
  clearColor(red: number, green: number, blue: number, alpha: number): void {
    const clear = this.state.getClearState();
    if (!isDefined(clear.colorClearValue)) {
      clear.colorClearValue = new Float32Array(4);
    }
    const arr = clear.colorClearValue as Float32Array;
    arr[0] = red;
    arr[1] = green;
    arr[2] = blue;
    arr[3] = alpha;
  }

  clearDepth(depth: number): void {
    const clear = this.state.getClearState();
    clear.depthClearValue = depth;
  }

  clearStencil(stencil: number): void {
    const clear = this.state.getClearState();
    clear.stencilClearValue = stencil;
  }

  // Blend state methods
  blendColor(red: number, green: number, blue: number, alpha: number): void {
    const blend = this.state.getBlendState();
    if (!isDefined(blend.blendColor)) {
      blend.blendColor = new Float32Array(4);
    }
    const arr = blend.blendColor as Float32Array;
    arr[0] = red;
    arr[1] = green;
    arr[2] = blue;
    arr[3] = alpha;
  }

  blendEquation(mode: number): void {
    const blend = this.state.getBlendState();
    blend.blendEquationRgb = mode;
    blend.blendEquationAlpha = mode;
  }

  blendEquationSeparate(modeRGB: number, modeAlpha: number): void {
    const blend = this.state.getBlendState();
    blend.blendEquationRgb = modeRGB;
    blend.blendEquationAlpha = modeAlpha;
  }

  blendFunc(sfactor: number, dfactor: number): void {
    const blend = this.state.getBlendState();
    blend.blendSrcRgb = sfactor;
    blend.blendDstRgb = dfactor;
    blend.blendSrcAlpha = sfactor;
    blend.blendDstAlpha = dfactor;
  }

  blendFuncSeparate(srcRGB: number, dstRGB: number, srcAlpha: number, dstAlpha: number): void {
    const blend = this.state.getBlendState();
    blend.blendSrcRgb = srcRGB;
    blend.blendDstRgb = dstRGB;
    blend.blendSrcAlpha = srcAlpha;
    blend.blendDstAlpha = dstAlpha;
  }

  // Depth state methods
  depthFunc(func: number): void {
    const depth = this.state.getDepthState();
    depth.depthFunc = func;
  }

  depthMask(flag: boolean): void {
    const depth = this.state.getDepthState();
    depth.depthWritemask = flag;
  }

  depthRange(zNear: number, zFar: number): void {
    const depth = this.state.getDepthState();
    if (!isDefined(depth.depthRange)) {
      depth.depthRange = new Float32Array(2);
    }
    const arr = depth.depthRange as Float32Array;
    arr[0] = zNear;
    arr[1] = zFar;
  }

  // Stencil state methods
  stencilFunc(func: number, ref: number, mask: number): void {
    const stencil = this.state.getStencilState();
    stencil.stencilFunc = func;
    stencil.stencilRef = ref;
    stencil.stencilValueMask = mask;
    stencil.stencilBackFunc = func;
    stencil.stencilBackRef = ref;
    stencil.stencilBackValueMask = mask;
  }

  stencilFuncSeparate(face: number, func: number, ref: number, mask: number): void {
    const stencil = this.state.getStencilState();
    if (face === this.constants.FRONT || face === this.constants.FRONT_AND_BACK) {
      stencil.stencilFunc = func;
      stencil.stencilRef = ref;
      stencil.stencilValueMask = mask;
    }
    if (face === this.constants.BACK || face === this.constants.FRONT_AND_BACK) {
      stencil.stencilBackFunc = func;
      stencil.stencilBackRef = ref;
      stencil.stencilBackValueMask = mask;
    }
  }

  stencilMask(mask: number): void {
    const stencil = this.state.getStencilState();
    stencil.stencilWritemask = mask;
    stencil.stencilBackWritemask = mask;
  }

  stencilMaskSeparate(face: number, mask: number): void {
    const stencil = this.state.getStencilState();
    if (face === this.constants.FRONT || face === this.constants.FRONT_AND_BACK) {
      stencil.stencilWritemask = mask;
    }
    if (face === this.constants.BACK || face === this.constants.FRONT_AND_BACK) {
      stencil.stencilBackWritemask = mask;
    }
  }

  stencilOp(fail: number, zfail: number, zpass: number): void {
    const stencil = this.state.getStencilState();
    stencil.stencilFail = fail;
    stencil.stencilPassDepthFail = zfail;
    stencil.stencilPassDepthPass = zpass;
    stencil.stencilBackFail = fail;
    stencil.stencilBackPassDepthFail = zfail;
    stencil.stencilBackPassDepthPass = zpass;
  }

  stencilOpSeparate(face: number, fail: number, zfail: number, zpass: number): void {
    const stencil = this.state.getStencilState();
    if (face === this.constants.FRONT || face === this.constants.FRONT_AND_BACK) {
      stencil.stencilFail = fail;
      stencil.stencilPassDepthFail = zfail;
      stencil.stencilPassDepthPass = zpass;
    }
    if (face === this.constants.BACK || face === this.constants.FRONT_AND_BACK) {
      stencil.stencilBackFail = fail;
      stencil.stencilBackPassDepthFail = zfail;
      stencil.stencilBackPassDepthPass = zpass;
    }
  }

  // Color state methods
  colorMask(red: boolean, green: boolean, blue: boolean, alpha: boolean): void {
    const color = this.state.getColorState();
    color.colorWritemask = [red, green, blue, alpha];
  }

  // Culling state methods
  cullFace(mode: number): void {
    const culling = this.state.getCullingState();
    culling.cullFaceMode = mode;
  }

  frontFace(mode: number): void {
    const culling = this.state.getCullingState();
    culling.frontFace = mode;
  }

  // Line width
  lineWidth(width: number): void {
    const line = this.state.getLineState();
    line.lineWidth = width;
  }

  // Polygon offset
  polygonOffset(factor: number, units: number): void {
    const polygonOffset = this.state.getPolygonOffsetState();
    polygonOffset.polygonOffsetFactor = factor;
    polygonOffset.polygonOffsetUnits = units;
  }

  // Sample coverage
  sampleCoverage(value: number, invert: boolean): void {
    const sample = this.state.getSampleState();
    sample.sampleCoverageValue = value;
    sample.sampleCoverageInvert = invert;
  }

  // Pixel store methods
  pixelStorei(pname: number, param: number): void {
    const pixelStore = this.state.getPixelStoreState();
    switch (pname) {
      case this.constants.PACK_ALIGNMENT:
        pixelStore.packAlignment = param;
        break;
      case this.constants.UNPACK_ALIGNMENT:
        pixelStore.unpackAlignment = param;
        break;
      case this.constants.UNPACK_FLIP_Y_WEBGL:
        pixelStore.unpackFlipY = !!param;
        break;
      case this.constants.UNPACK_PREMULTIPLY_ALPHA_WEBGL:
        pixelStore.unpackPremultiplyAlpha = !!param;
        break;
      case this.constants.PACK_ROW_LENGTH:
        pixelStore.packRowLength = param;
        break;
      case this.constants.PACK_SKIP_PIXELS:
        pixelStore.packSkipPixels = param;
        break;
      case this.constants.PACK_SKIP_ROWS:
        pixelStore.packSkipRows = param;
        break;
      case this.constants.UNPACK_ROW_LENGTH:
        pixelStore.unpackRowLength = param;
        break;
      case this.constants.UNPACK_IMAGE_HEIGHT:
        pixelStore.unpackImageHeight = param;
        break;
      case this.constants.UNPACK_SKIP_PIXELS:
        pixelStore.unpackSkipPixels = param;
        break;
      case this.constants.UNPACK_SKIP_ROWS:
        pixelStore.unpackSkipRows = param;
        break;
      case this.constants.UNPACK_SKIP_IMAGES:
        pixelStore.unpackSkipImages = param;
        break;
    }
  }

  // Renderbuffer methods
  bindRenderbuffer(target: number, renderbuffer: WebGLRenderbuffer | null): void {
    const renderbufferState = this.state.getRenderbufferState();
    renderbufferState.renderbuffer = renderbuffer;
  }

  // Transform feedback methods
  bindTransformFeedback(target: number, transformFeedback: WebGLTransformFeedback | null): void {
    const tfState = this.state.getTransformFeedbackState();
    tfState.transformFeedback = transformFeedback;
  }

  beginTransformFeedback(primitiveMode: number): void {
    const tfState = this.state.getTransformFeedbackState();
    tfState.transformFeedbackActive = true;
    tfState.transformFeedbackPaused = false;
  }

  endTransformFeedback(): void {
    const tfState = this.state.getTransformFeedbackState();
    tfState.transformFeedbackActive = false;
    tfState.transformFeedbackPaused = false;
  }

  pauseTransformFeedback(): void {
    const tfState = this.state.getTransformFeedbackState();
    if (tfState.transformFeedbackActive) {
      tfState.transformFeedbackPaused = true;
    }
  }

  resumeTransformFeedback(): void {
    const tfState = this.state.getTransformFeedbackState();
    if (tfState.transformFeedbackActive) {
      tfState.transformFeedbackPaused = false;
    }
  }

  // Buffer binding range methods
  bindBufferBase(target: number, index: number, buffer: WebGLBuffer | null): void {
    const buffers = this.state.getBuffersState();
    // Per WebGL spec: bindBufferBase updates BOTH the indexed binding AND the generic binding
    switch (target) {
      case this.constants.UNIFORM_BUFFER:
        buffers.uniformBuffer = buffer;
        const uniformBinding = new WebGLIndexedBufferBinding();
        uniformBinding.buffer = buffer;
        uniformBinding.offset = 0;
        uniformBinding.size = 0; // 0 means entire buffer
        buffers.uniformBufferBindings.set(index, uniformBinding);
        break;
      case this.constants.TRANSFORM_FEEDBACK_BUFFER:
        buffers.transformFeedbackBuffer = buffer;
        const tfBinding = new WebGLIndexedBufferBinding();
        tfBinding.buffer = buffer;
        tfBinding.offset = 0;
        tfBinding.size = 0; // 0 means entire buffer
        buffers.transformFeedbackBufferBindings.set(index, tfBinding);
        break;
    }
  }

  bindBufferRange(
    target: number,
    index: number,
    buffer: WebGLBuffer | null,
    offset: number,
    size: number
  ): void {
    const buffers = this.state.getBuffersState();
    // Per WebGL spec: bindBufferRange updates BOTH the indexed binding AND the generic binding
    switch (target) {
      case this.constants.UNIFORM_BUFFER:
        buffers.uniformBuffer = buffer;
        const uniformBinding = new WebGLIndexedBufferBinding();
        uniformBinding.buffer = buffer;
        uniformBinding.offset = offset;
        uniformBinding.size = size;
        buffers.uniformBufferBindings.set(index, uniformBinding);
        break;
      case this.constants.TRANSFORM_FEEDBACK_BUFFER:
        buffers.transformFeedbackBuffer = buffer;
        const transformBinding = new WebGLIndexedBufferBinding();
        transformBinding.buffer = buffer;
        transformBinding.offset = offset;
        transformBinding.size = size;
        buffers.transformFeedbackBufferBindings.set(index, transformBinding);
        break;
    }
  }

  // Framebuffer attachment methods (per-framebuffer state, only tracked for default FB)
  framebufferTexture2D(
    target: number,
    attachment: number,
    textarget: number,
    texture: WebGLTexture | null,
    level: number
  ): void {
    const framebuffers = this.state.framebuffers;
    const isDefaultFB =
      !framebuffers ||
      (target === this.constants.FRAMEBUFFER && framebuffers.framebuffer === null) ||
      (target === this.constants.DRAW_FRAMEBUFFER && framebuffers.drawFramebuffer === null);

    if (isDefaultFB) {
      const fbState = this.state.getFramebuffersState().defaultFramebufferState;
      const attachmentObj = new WebGLFramebufferAttachment();
      attachmentObj.attachmentType = texture ? 'texture' : GLUndefined;
      attachmentObj.texture = texture || GLUndefined;
      attachmentObj.renderbuffer = GLUndefined;
      attachmentObj.textureLevel = level;
      attachmentObj.textureLayer = 0;
      attachmentObj.textureCubeFace = textarget;

      this.setFramebufferAttachment(fbState, attachment, attachmentObj);
    }
    // else: Non-default framebuffer - don't track
  }

  framebufferRenderbuffer(
    target: number,
    attachment: number,
    renderbuffertarget: number,
    renderbuffer: WebGLRenderbuffer | null
  ): void {
    const framebuffers = this.state.framebuffers;
    const isDefaultFB =
      !framebuffers ||
      (target === this.constants.FRAMEBUFFER && framebuffers.framebuffer === null) ||
      (target === this.constants.DRAW_FRAMEBUFFER && framebuffers.drawFramebuffer === null);

    if (isDefaultFB) {
      const fbState = this.state.getFramebuffersState().defaultFramebufferState;
      const attachmentObj = new WebGLFramebufferAttachment();
      attachmentObj.attachmentType = renderbuffer ? 'renderbuffer' : GLUndefined;
      attachmentObj.texture = GLUndefined;
      attachmentObj.renderbuffer = renderbuffer || GLUndefined;
      attachmentObj.textureLevel = 0;
      attachmentObj.textureLayer = 0;
      attachmentObj.textureCubeFace = 0;

      this.setFramebufferAttachment(fbState, attachment, attachmentObj);
    }
    // else: Non-default framebuffer - don't track
  }

  framebufferTextureLayer(
    target: number,
    attachment: number,
    texture: WebGLTexture | null,
    level: number,
    layer: number
  ): void {
    const framebuffers = this.state.framebuffers;
    const isDefaultFB =
      !framebuffers ||
      (target === this.constants.FRAMEBUFFER && framebuffers.framebuffer === null) ||
      (target === this.constants.DRAW_FRAMEBUFFER && framebuffers.drawFramebuffer === null);

    if (isDefaultFB) {
      const fbState = this.state.getFramebuffersState().defaultFramebufferState;
      const attachmentObj = new WebGLFramebufferAttachment();
      attachmentObj.attachmentType = texture ? 'texture' : GLUndefined;
      attachmentObj.texture = texture || GLUndefined;
      attachmentObj.renderbuffer = GLUndefined;
      attachmentObj.textureLevel = level;
      attachmentObj.textureLayer = layer;
      attachmentObj.textureCubeFace = 0;

      this.setFramebufferAttachment(fbState, attachment, attachmentObj);
    }
    // else: Non-default framebuffer - don't track
  }

  private setFramebufferAttachment(
    fbState: WebGLDefaultFramebufferState,
    attachment: number,
    attachmentObj: WebGLFramebufferAttachment
  ): void {
    if (attachment === this.constants.DEPTH_ATTACHMENT) {
      fbState.depthAttachment = attachmentObj;
    } else if (attachment === this.constants.STENCIL_ATTACHMENT) {
      fbState.stencilAttachment = attachmentObj;
    } else if (attachment === this.constants.DEPTH_STENCIL_ATTACHMENT) {
      fbState.depthStencilAttachment = attachmentObj;
    } else if (
      attachment >= this.constants.COLOR_ATTACHMENT0 &&
      attachment <= this.constants.COLOR_ATTACHMENT0 + 15
    ) {
      const index = attachment - this.constants.COLOR_ATTACHMENT0;
      fbState.colorAttachments[`COLOR_ATTACHMENT${index}`] = attachmentObj;
    }
  }

  // Draw buffer methods (per-framebuffer state, only tracked for default FB)
  drawBuffers(buffers: number[]): void {
    const framebuffers = this.state.framebuffers;
    const isDefaultFB = !framebuffers || framebuffers.drawFramebuffer === null;

    if (isDefaultFB) {
      const fbState = this.state.getFramebuffersState().defaultFramebufferState;
      fbState.drawBuffers = [...buffers];
    }
    // else: Non-default framebuffer - don't track
  }

  readBuffer(mode: number): void {
    const framebuffers = this.state.framebuffers;
    const isDefaultFB = !framebuffers || framebuffers.readFramebuffer === null;

    if (isDefaultFB) {
      const fbState = this.state.getFramebuffersState().defaultFramebufferState;
      fbState.readBuffer = mode;
    }
    // else: Non-default framebuffer - don't track
  }

  // Hint method
  hint(target: number, mode: number): void {
    // Hints don't typically affect state in a way we need to track
    // This is a no-op but maintains interface compatibility
  }

  // No-op state changing methods that don't affect our tracked state
  // but are part of the WebGL2RenderingContext interface

  // Buffer data methods (don't affect binding state)
  bufferData(
    target: number,
    sizeOrData: number | ArrayBufferView | ArrayBuffer | null,
    usage: number,
    srcOffset?: number,
    length?: number
  ): void {
    // Data operations don't change binding state
  }

  bufferSubData(
    target: number,
    dstByteOffset: number,
    srcData: ArrayBufferView | ArrayBuffer,
    srcOffset?: number,
    length?: number
  ): void {
    // Data operations don't change binding state
  }

  copyBufferSubData(
    readTarget: number,
    writeTarget: number,
    readOffset: number,
    writeOffset: number,
    size: number
  ): void {
    // Copy operations don't change binding state
  }

  // Texture parameter methods (don't affect binding state)
  texParameterf(target: number, pname: number, param: number): void {
    // Parameter changes don't affect binding state
  }

  texParameteri(target: number, pname: number, param: number): void {
    // Parameter changes don't affect binding state
  }

  // Texture data methods (don't affect binding state)
  texImage2D(...args: any[]): void {
    // Data operations don't change binding state
  }

  texSubImage2D(...args: any[]): void {
    // Data operations don't change binding state
  }

  texImage3D(...args: any[]): void {
    // Data operations don't change binding state
  }

  texSubImage3D(...args: any[]): void {
    // Data operations don't change binding state
  }

  compressedTexImage2D(...args: any[]): void {
    // Data operations don't change binding state
  }

  compressedTexSubImage2D(...args: any[]): void {
    // Data operations don't change binding state
  }

  compressedTexImage3D(...args: any[]): void {
    // Data operations don't change binding state
  }

  compressedTexSubImage3D(...args: any[]): void {
    // Data operations don't change binding state
  }

  texStorage2D(
    target: number,
    levels: number,
    internalformat: number,
    width: number,
    height: number
  ): void {
    // Storage allocation doesn't change binding state
  }

  texStorage3D(
    target: number,
    levels: number,
    internalformat: number,
    width: number,
    height: number,
    depth: number
  ): void {
    // Storage allocation doesn't change binding state
  }

  copyTexImage2D(
    target: number,
    level: number,
    internalformat: number,
    x: number,
    y: number,
    width: number,
    height: number,
    border: number
  ): void {
    // Copy operations don't change binding state
  }

  copyTexSubImage2D(
    target: number,
    level: number,
    xoffset: number,
    yoffset: number,
    x: number,
    y: number,
    width: number,
    height: number
  ): void {
    // Copy operations don't change binding state
  }

  copyTexSubImage3D(
    target: number,
    level: number,
    xoffset: number,
    yoffset: number,
    zoffset: number,
    x: number,
    y: number,
    width: number,
    height: number
  ): void {
    // Copy operations don't change binding state
  }

  generateMipmap(target: number): void {
    // Mipmap generation doesn't change binding state
  }

  // Framebuffer methods (attachment doesn't affect binding state)
  invalidateFramebuffer(target: number, attachments: number[]): void {
    // Invalidation doesn't change binding state
  }

  invalidateSubFramebuffer(
    target: number,
    attachments: number[],
    x: number,
    y: number,
    width: number,
    height: number
  ): void {
    // Invalidation doesn't change binding state
  }

  // Renderbuffer storage (doesn't affect binding state)
  renderbufferStorage(target: number, internalformat: number, width: number, height: number): void {
    // Storage allocation doesn't change binding state
  }

  renderbufferStorageMultisample(
    target: number,
    samples: number,
    internalformat: number,
    width: number,
    height: number
  ): void {
    // Storage allocation doesn't change binding state
  }

  // Sampler methods (WebGL 2.0)
  bindSampler(unit: number, sampler: WebGLSampler | null): void {
    const samplers = this.state.getSamplersState();
    samplers.samplerBindings[unit] = sampler;
  }

  samplerParameteri(sampler: WebGLSampler, pname: number, param: number): void {
    // Sampler parameters don't affect binding state
  }

  samplerParameterf(sampler: WebGLSampler, pname: number, param: number): void {
    // Sampler parameters don't affect binding state
  }

  // Query methods (WebGL 2.0)
  beginQuery(target: number, query: WebGLQuery): void {
    const queries = this.state.getQueriesState();
    switch (target) {
      case this.constants.ANY_SAMPLES_PASSED:
        queries.currentAnySamplesPassed = query;
        break;
      case this.constants.ANY_SAMPLES_PASSED_CONSERVATIVE:
        queries.currentAnySamplesPassedConservative = query;
        break;
      case this.constants.TRANSFORM_FEEDBACK_PRIMITIVES_WRITTEN:
        queries.currentTransformFeedbackPrimitivesWritten = query;
        break;
      // SAMPLES_PASSED is WebGL 1.0 extension, we track as occlusion query
      default:
        queries.currentOcclusionQuery = query;
        break;
    }
  }

  endQuery(target: number): void {
    const queries = this.state.getQueriesState();
    switch (target) {
      case this.constants.ANY_SAMPLES_PASSED:
        queries.currentAnySamplesPassed = null;
        break;
      case this.constants.ANY_SAMPLES_PASSED_CONSERVATIVE:
        queries.currentAnySamplesPassedConservative = null;
        break;
      case this.constants.TRANSFORM_FEEDBACK_PRIMITIVES_WRITTEN:
        queries.currentTransformFeedbackPrimitivesWritten = null;
        break;
      default:
        queries.currentOcclusionQuery = null;
        break;
    }
  }

  // Generic vertex attribute setters (don't affect binding state)
  vertexAttrib1f(index: number, x: number): void {
    // Generic vertex attributes don't affect binding state
  }

  vertexAttrib2f(index: number, x: number, y: number): void {
    // Generic vertex attributes don't affect binding state
  }

  vertexAttrib3f(index: number, x: number, y: number, z: number): void {
    // Generic vertex attributes don't affect binding state
  }

  vertexAttrib4f(index: number, x: number, y: number, z: number, w: number): void {
    // Generic vertex attributes don't affect binding state
  }

  vertexAttribI4i(index: number, x: number, y: number, z: number, w: number): void {
    // Generic vertex attributes don't affect binding state
  }

  vertexAttribI4ui(index: number, x: number, y: number, z: number, w: number): void {
    // Generic vertex attributes don't affect binding state
  }

  vertexAttrib1fv(index: number, values: Float32Array | number[]): void {
    // Generic vertex attributes don't affect binding state
  }

  vertexAttrib2fv(index: number, values: Float32Array | number[]): void {
    // Generic vertex attributes don't affect binding state
  }

  vertexAttrib3fv(index: number, values: Float32Array | number[]): void {
    // Generic vertex attributes don't affect binding state
  }

  vertexAttrib4fv(index: number, values: Float32Array | number[]): void {
    // Generic vertex attributes don't affect binding state
  }

  vertexAttribI4iv(index: number, values: Int32Array | number[]): void {
    // Generic vertex attributes don't affect binding state
  }

  vertexAttribI4uiv(index: number, values: Uint32Array | number[]): void {
    // Generic vertex attributes don't affect binding state
  }

  // Uniform methods (don't affect binding state, only change uniform values)
  uniform1f(location: WebGLUniformLocation | null, x: number): void {}
  uniform2f(location: WebGLUniformLocation | null, x: number, y: number): void {}
  uniform3f(location: WebGLUniformLocation | null, x: number, y: number, z: number): void {}
  uniform4f(
    location: WebGLUniformLocation | null,
    x: number,
    y: number,
    z: number,
    w: number
  ): void {}

  uniform1i(location: WebGLUniformLocation | null, x: number): void {}
  uniform2i(location: WebGLUniformLocation | null, x: number, y: number): void {}
  uniform3i(location: WebGLUniformLocation | null, x: number, y: number, z: number): void {}
  uniform4i(
    location: WebGLUniformLocation | null,
    x: number,
    y: number,
    z: number,
    w: number
  ): void {}

  uniform1ui(location: WebGLUniformLocation | null, x: number): void {}
  uniform2ui(location: WebGLUniformLocation | null, x: number, y: number): void {}
  uniform3ui(location: WebGLUniformLocation | null, x: number, y: number, z: number): void {}
  uniform4ui(
    location: WebGLUniformLocation | null,
    x: number,
    y: number,
    z: number,
    w: number
  ): void {}

  uniform1fv(
    location: WebGLUniformLocation | null,
    data: Float32Array | number[],
    srcOffset?: number,
    srcLength?: number
  ): void {}
  uniform2fv(
    location: WebGLUniformLocation | null,
    data: Float32Array | number[],
    srcOffset?: number,
    srcLength?: number
  ): void {}
  uniform3fv(
    location: WebGLUniformLocation | null,
    data: Float32Array | number[],
    srcOffset?: number,
    srcLength?: number
  ): void {}
  uniform4fv(
    location: WebGLUniformLocation | null,
    data: Float32Array | number[],
    srcOffset?: number,
    srcLength?: number
  ): void {}

  uniform1iv(
    location: WebGLUniformLocation | null,
    data: Int32Array | number[],
    srcOffset?: number,
    srcLength?: number
  ): void {}
  uniform2iv(
    location: WebGLUniformLocation | null,
    data: Int32Array | number[],
    srcOffset?: number,
    srcLength?: number
  ): void {}
  uniform3iv(
    location: WebGLUniformLocation | null,
    data: Int32Array | number[],
    srcOffset?: number,
    srcLength?: number
  ): void {}
  uniform4iv(
    location: WebGLUniformLocation | null,
    data: Int32Array | number[],
    srcOffset?: number,
    srcLength?: number
  ): void {}

  uniform1uiv(
    location: WebGLUniformLocation | null,
    data: Uint32Array | number[],
    srcOffset?: number,
    srcLength?: number
  ): void {}
  uniform2uiv(
    location: WebGLUniformLocation | null,
    data: Uint32Array | number[],
    srcOffset?: number,
    srcLength?: number
  ): void {}
  uniform3uiv(
    location: WebGLUniformLocation | null,
    data: Uint32Array | number[],
    srcOffset?: number,
    srcLength?: number
  ): void {}
  uniform4uiv(
    location: WebGLUniformLocation | null,
    data: Uint32Array | number[],
    srcOffset?: number,
    srcLength?: number
  ): void {}

  uniformMatrix2fv(
    location: WebGLUniformLocation | null,
    transpose: boolean,
    data: Float32Array | number[],
    srcOffset?: number,
    srcLength?: number
  ): void {}
  uniformMatrix3fv(
    location: WebGLUniformLocation | null,
    transpose: boolean,
    data: Float32Array | number[],
    srcOffset?: number,
    srcLength?: number
  ): void {}
  uniformMatrix4fv(
    location: WebGLUniformLocation | null,
    transpose: boolean,
    data: Float32Array | number[],
    srcOffset?: number,
    srcLength?: number
  ): void {}
  uniformMatrix2x3fv(
    location: WebGLUniformLocation | null,
    transpose: boolean,
    data: Float32Array | number[],
    srcOffset?: number,
    srcLength?: number
  ): void {}
  uniformMatrix3x2fv(
    location: WebGLUniformLocation | null,
    transpose: boolean,
    data: Float32Array | number[],
    srcOffset?: number,
    srcLength?: number
  ): void {}
  uniformMatrix2x4fv(
    location: WebGLUniformLocation | null,
    transpose: boolean,
    data: Float32Array | number[],
    srcOffset?: number,
    srcLength?: number
  ): void {}
  uniformMatrix4x2fv(
    location: WebGLUniformLocation | null,
    transpose: boolean,
    data: Float32Array | number[],
    srcOffset?: number,
    srcLength?: number
  ): void {}
  uniformMatrix3x4fv(
    location: WebGLUniformLocation | null,
    transpose: boolean,
    data: Float32Array | number[],
    srcOffset?: number,
    srcLength?: number
  ): void {}
  uniformMatrix4x3fv(
    location: WebGLUniformLocation | null,
    transpose: boolean,
    data: Float32Array | number[],
    srcOffset?: number,
    srcLength?: number
  ): void {}

  // Drawing methods (don't affect state, only render)
  clear(mask: number): void {}
  drawArrays(mode: number, first: number, count: number): void {}
  drawElements(mode: number, count: number, type: number, offset: number): void {}
  drawArraysInstanced(mode: number, first: number, count: number, instanceCount: number): void {}
  drawElementsInstanced(
    mode: number,
    count: number,
    type: number,
    offset: number,
    instanceCount: number
  ): void {}
  drawRangeElements(
    mode: number,
    start: number,
    end: number,
    count: number,
    type: number,
    offset: number
  ): void {}

  // Read pixels (doesn't change state)
  readPixels(...args: any[]): void {}

  // Blit framebuffer (doesn't change binding state)
  blitFramebuffer(
    srcX0: number,
    srcY0: number,
    srcX1: number,
    srcY1: number,
    dstX0: number,
    dstY0: number,
    dstX1: number,
    dstY1: number,
    mask: number,
    filter: number
  ): void {}

  // Flush/Finish (doesn't change state)
  flush(): void {}
  finish(): void {}

  // State access methods - returns a clone to prevent external mutation
  getState(): WebGLState {
    return this.state.clone();
  }

  // Public getters that return state without lazy creation (tests use these)
  getBufferState(): WebGLBufferState | undefined {
    return this.state.buffers;
  }

  getVertexArrayState(): WebGLVertexArrayState | undefined {
    return this.state.vertexArrays;
  }

  getTextureState(): WebGLTextureState | undefined {
    return this.state.textures;
  }

  getProgramState(): WebGLProgramState | undefined {
    return this.state.programs;
  }

  getFramebufferState(): WebGLFramebufferState | undefined {
    return this.state.framebuffers;
  }

  getCapabilityState(): WebGLCapabilityState | undefined {
    return this.state.capabilities;
  }

  getSamplerState(): WebGLSamplerState | undefined {
    return this.state.samplers;
  }

  getQueryState(): WebGLQueryState | undefined {
    return this.state.queries;
  }

  getStencilState(): WebGLStencilState | undefined {
    return this.state.stencil;
  }

  getPixelStoreState(): WebGLPixelStoreState | undefined {
    return this.state.pixelStore;
  }

  getTransformFeedbackState(): WebGLTransformFeedbackState | undefined {
    return this.state.transformFeedback;
  }

  // Reset state to defaults (clears all lazily created state)
  reset(): void {
    this.state = new WebGLState();
  }
}
