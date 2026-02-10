// Device profiles provide per-device defaults used by the example UIs.
// These are not hard requirements; they are applied as suggested values and remain user-editable.
export type DeviceProfileId = 'custom' | 'quest3' | 'pico4ultra';

export interface DeviceProfile {
  id: DeviceProfileId;
  label: string;
  description?: string;
  // Constraints that affect hosting or connection requirements (e.g., HTTPS-only devices).
  connection?: {
    httpsRequired?: boolean;
  };
  // Web-side settings that impact WebGL or XR configuration in the examples.
  // "Antialias" is split into WebGL vs XRWebGLLayer because they are configured separately.
  web?: {
    webglAntialias?: boolean;
    xrWebGLLayerAntialias?: boolean;
    powerPreference?: WebGLPowerPreference;
    preserveDrawingBuffer?: boolean;
    failIfMajorPerformanceCaveat?: boolean;
    depth?: boolean;
    stencil?: boolean;
    alpha?: boolean;
    framebufferScaleFactor?: number;
    fixedFoveation?: number | null;
    frameBufferScaling?: number;
    foveation?: number;
  };
  // CloudXR session options that are device-tunable defaults.
  cloudxr?: {
    perEyeWidth?: number;
    perEyeHeight?: number;
    deviceFrameRate?: number;
    maxStreamingBitrateKbps?: number;
    codec?: 'av1' | 'h264' | 'h265';
    enablePoseSmoothing?: boolean;
    posePredictionFactor?: number;
    enableTexSubImage2D?: boolean;
    useQuestColorWorkaround?: boolean;
  };
}

// Custom profile is a no-op; it provides no defaults.
const CUSTOM_PROFILE: DeviceProfile = {
  id: 'custom',
  label: 'Custom',
  description: 'No device defaults applied.',
};

// Quest 3 defaults tuned for balanced performance and quality.
const QUEST3_PROFILE: DeviceProfile = {
  id: 'quest3',
  label: 'Quest 3',
  description: 'Balanced defaults for Meta Quest 3.',
  connection: {
    httpsRequired: false,
  },
  web: {
    webglAntialias: false,
    xrWebGLLayerAntialias: false,
    powerPreference: 'high-performance',
    framebufferScaleFactor: 1.5,
    fixedFoveation: 0.666,
    frameBufferScaling: 1.5,
    foveation: 0.666,
  },
  cloudxr: {
    perEyeWidth: 2048,
    perEyeHeight: 1792,
    deviceFrameRate: 90,
    maxStreamingBitrateKbps: 150000,
    codec: 'av1',
    enablePoseSmoothing: true,
    posePredictionFactor: 1.0,
    enableTexSubImage2D: true,
    useQuestColorWorkaround: true,
  },
};

// Pico 4 Ultra defaults are conservative until device-specific validation is complete.
const PICO4ULTRA_PROFILE: DeviceProfile = {
  id: 'pico4ultra',
  label: 'Pico 4 Ultra',
  description: 'Conservative defaults for Pico 4 Ultra.',
  connection: {
    httpsRequired: true,
  },
  web: {
    webglAntialias: false,
    xrWebGLLayerAntialias: false,
    powerPreference: 'high-performance',
    framebufferScaleFactor: 1.3,
    fixedFoveation: null,
    frameBufferScaling: 1.3,
  },
  cloudxr: {
    perEyeWidth: 2048,
    perEyeHeight: 1792,
    deviceFrameRate: 90,
    maxStreamingBitrateKbps: 100000,
    codec: 'av1',
    enablePoseSmoothing: true,
    posePredictionFactor: 1.0,
    enableTexSubImage2D: false,
    useQuestColorWorkaround: false,
  },
};

export const DEVICE_PROFILES: Record<DeviceProfileId, DeviceProfile> = {
  custom: CUSTOM_PROFILE,
  quest3: QUEST3_PROFILE,
  pico4ultra: PICO4ULTRA_PROFILE,
};

export function resolveDeviceProfileId(value: string | null | undefined): DeviceProfileId {
  if (value === 'quest3' || value === 'pico4ultra' || value === 'custom') {
    return value;
  }
  return 'custom';
}

export function getDeviceProfile(id: DeviceProfileId): DeviceProfile {
  return DEVICE_PROFILES[id] ?? CUSTOM_PROFILE;
}
