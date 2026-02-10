export function getOrCreateCanvas(
  id: string,
  resolution?: { width: number; height: number }
): HTMLCanvasElement {
  let canvas = document.getElementById(id) as HTMLCanvasElement | null;
  if (!canvas) {
    canvas = document.createElement('canvas') as HTMLCanvasElement;
    canvas.id = id;
    // canvas.style.display = "none";
    document.body.appendChild(canvas);
  }
  if (!canvas) {
    throw new Error('Failed to create canvas');
  }
  if (resolution) {
    canvas.width = resolution.width;
    canvas.height = resolution.height;
  }
  return canvas;
}

export function logOrThrow(tagString: string, gl: WebGL2RenderingContext) {
  const err = gl.getError();
  if (err !== gl.NO_ERROR) {
    let errorString;
    switch (err) {
      case gl.INVALID_ENUM:
        errorString = 'INVALID_ENUM';
        break;
      case gl.INVALID_VALUE:
        errorString = 'INVALID_VALUE';
        break;
      case gl.INVALID_OPERATION:
        errorString = 'INVALID_OPERATION';
        break;
      case gl.INVALID_FRAMEBUFFER_OPERATION:
        errorString = 'INVALID_FRAMEBUFFER_OPERATION';
        break;
      case gl.OUT_OF_MEMORY:
        errorString = 'OUT_OF_MEMORY';
        break;
      case gl.CONTEXT_LOST_WEBGL:
        errorString = 'CONTEXT_LOST_WEBGL';
        break;
      default:
        errorString = 'UNKNOWN_ERROR';
        break;
    }

    throw new Error('WebGL error: ' + tagString + ': ' + errorString + ' (' + err + ')');
  } else {
    console.debug('WebGL no-error: ' + tagString);
  }
}
