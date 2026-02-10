/**
 * Meta Quest foveation levels for fixed foveated rendering (FFR).
 *
 * Settings for foveation modes in WebXR in Quest Browser
 *
 * @see https://developers.meta.com/horizon/documentation/web/webxr-ffr/
 */
const QuestBrowserFoveationLevel = {
  /** No foveation - full resolution everywhere */
  NONE: 0.0,
  /** Minimal peripheral reduction */
  LOW: 0.333,
  /** Balanced quality/performance */
  MEDIUM: 0.666,
  /** Maximum peripheral reduction */
  HIGH: 1.0,
} as const;

/**
 * Default performance settings for CloudXR WebGL/WebXR rendering
 *
 * These settings have been tuned for Meta Quest 3 to achieve 90 fps while maintaining
 * visual quality. The configuration disables expensive antialiasing features and uses
 * moderate framebuffer scaling and foveation.
 */
export const kPerformanceOptions = {
  /** WebGL2 context antialiasing - disabled due to high cost with minimal benefit */
  webglContext_antialias: false,

  /** XRWebGLLayer antialiasing - disabled (no observed impact on Quest 3) */
  xrWebGLLayer_antialias: false,

  /**
   * Framebuffer scale factor -
   *  - 1.5 is the maximum effective value on Quest 3.
   *  - 1.2 is approximately the native resolution of the Quest 3
   *  - 1.0 is "the default", but specifying this value causes Quest 3 Browser to
   *        take more frame time than not including this option in the layer creation options.
   */
  xrWebGLLayer_framebufferScaleFactor: 1.5,

  /**
   * Fixed foveation level - MEDIUM provides good balance between performance and quality.
   */
  xrWebGLLayer_fixedFoveationLevel: QuestBrowserFoveationLevel.MEDIUM,
} as const;
