/**
 * SimpleEnvironment – simple HDRI for scene lighting (no CDN/file).
 * Approximation of the HDRI at https://dl.polyhaven.org/file/ph-assets/HDRIs/hdr/1k/potsdamer_platz_1k.hdr.
 * Each band is [R, G, B] in linear space (sky, horizon, ground).
 */

import { useThree } from '@react-three/fiber';
import { useEffect } from 'react';
import * as THREE from 'three';

export const HDRI_BANDS: [number, number, number][] = [
  [1.41, 1.45, 1.73], // sky
  [0.16, 0.14, 0.16], // horizon
  [0.13, 0.07, 0.07], // ground
];

export function SimpleEnvironment() {
  const { scene } = useThree();
  useEffect(() => {
    // 64×32 is the minimum equirect size supported by Three's PMREMGenerator.
    const width = 64;
    const height = 32;
    const data = new Uint16Array(width * height * 4);
    const bands = HDRI_BANDS;

    // Fill equirect: top row = sky, bottom = ground. Each row is one scanline (same color across x).
    for (let y = 0; y < height; y++) {
      const v = y / height; // 0 at top, 1 at bottom
      const bandF = v * (bands.length - 1); // continuous index into band range
      const bi = Math.min(Math.floor(bandF), bands.length - 2);
      const t = bandF - bi; // blend factor between bands[bi] and bands[bi + 1]
      const [r0, g0, b0] = bands[bi];
      const [r1, g1, b1] = bands[bi + 1];
      // Linear interpolate and encode as half-float for HDR
      const r = THREE.DataUtils.toHalfFloat(r0 + t * (r1 - r0));
      const g = THREE.DataUtils.toHalfFloat(g0 + t * (g1 - g0));
      const b = THREE.DataUtils.toHalfFloat(b0 + t * (b1 - b0));
      const a = THREE.DataUtils.toHalfFloat(1);
      for (let x = 0; x < width; x++) {
        const i = (y * width + x) * 4;
        data[i] = r;
        data[i + 1] = g;
        data[i + 2] = b;
        data[i + 3] = a;
      }
    }

    const texture = new THREE.DataTexture(
      data,
      width,
      height,
      THREE.RGBAFormat,
      THREE.HalfFloatType
    );
    texture.mapping = THREE.EquirectangularReflectionMapping;
    texture.colorSpace = THREE.LinearSRGBColorSpace;
    texture.magFilter = THREE.LinearFilter;
    texture.minFilter = THREE.LinearFilter;
    texture.generateMipmaps = false;
    texture.flipY = true;
    texture.needsUpdate = true;

    scene.environment = texture;
    scene.environmentIntensity = 2;

    return () => {
      scene.environment = null;
      scene.environmentIntensity = 1;
      texture.dispose();
    };
  }, [scene]);
  return null;
}
