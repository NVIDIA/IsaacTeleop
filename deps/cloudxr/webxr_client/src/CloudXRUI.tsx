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
 * CloudXRUI.tsx - CloudXR User Interface Component
 *
 * This component renders the in-VR user interface for the CloudXR application using
 * React Three UIKit. It provides:
 * - Server connection information and status display
 * - Interactive control buttons (Start Teleop, Reset Teleop, Disconnect)
 * - Responsive button layout with hover effects
 * - Integration with parent component event handlers
 * - Configurable position and rotation in world space for flexible UI placement
 * - Draggable handle bar for repositioning the UI in 3D space
 * - Face-camera rotation for optimal viewing angle (Y-axis only)
 *
 * The UI is positioned in 3D space and designed for VR/AR interaction with
 * visual feedback and clear button labeling. All interactions are passed
 * back to the parent component through callback props.
 */

import { ReadonlySignal } from '@preact/signals-react';
import { useFrame } from '@react-three/fiber';
import { Handle, HandleTarget } from '@react-three/handle';
import { Container, Text, Image } from '@react-three/uikit';
import { Button } from '@react-three/uikit-default';
import React, { useRef, useState, useEffect } from 'react';
import { Color, Euler, Group, Mesh, MeshStandardMaterial, Quaternion, Vector3 } from 'three';
import { damp } from 'three/src/math/MathUtils.js';

// Face-camera rotation constants
const FACE_CAMERA_DAMPING = 10; // Higher = faster rotation toward camera

interface CloudXRUIProps {
  onStartTeleop?: () => void;
  onDisconnect?: () => void;
  onResetTeleop?: () => void;
  serverAddress?: string;
  sessionStatus?: string;
  playLabel?: string;
  playInProgress?: boolean;
  countdownSeconds?: number;
  onCountdownIncrease?: () => void;
  onCountdownDecrease?: () => void;
  countdownDisabled?: boolean;
  position?: [number, number, number];
  rotation?: [number, number, number];
  /** Computed signal for render FPS text - updates without React re-render */
  renderFpsText?: ReadonlySignal<string>;
  /** Computed signal for streaming FPS text - updates without React re-render */
  streamingFpsText?: ReadonlySignal<string>;
  /** Computed signal for pose-to-render latency text - updates without React re-render */
  poseToRenderText?: ReadonlySignal<string>;
}

// Reusable objects for face-camera rotation (avoid allocations in render loop)
const eulerHelper = new Euler();
const quaternionHelper = new Quaternion();
const cameraPositionHelper = new Vector3();
const uiPositionHelper = new Vector3();
const zAxis = new Vector3(0, 0, 1);

// Handle hover colors (module-level to avoid per-render allocations)
const HANDLE_COLOR_DEFAULT = new Color('#666666');
const HANDLE_COLOR_HOVER = new Color('#aaaaaa');

export default function CloudXR3DUI({
  onStartTeleop,
  onDisconnect,
  onResetTeleop,
  serverAddress = '127.0.0.1',
  sessionStatus = 'Disconnected',
  playLabel = 'Play',
  playInProgress = false,
  countdownSeconds,
  onCountdownIncrease,
  onCountdownDecrease,
  countdownDisabled = false,
  position = [1.8, 1.75, -1.3],
  rotation = [0, 0, 0], // Note: Y rotation is controlled by face-camera logic
  renderFpsText,
  streamingFpsText,
  poseToRenderText,
}: CloudXRUIProps) {
  const MINIMIZE_ON_PLAY_KEY = 'cxr.isaac.minimizeOnPlay';

  const groupRef = useRef<Group>(null);
  const handleRef = useRef<Mesh>(null);
  // useState(initializer): React calls the fn once on mount to get the initial value; it returns [value, setter]. Setter used in onClick below.
  const [minimizeOnPlay, setMinimizeOnPlay] = useState(() => {
    try {
      const saved = localStorage.getItem(MINIMIZE_ON_PLAY_KEY);
      return saved === 'true';
    } catch {
      return false;
    }
  });

  // Keep localStorage in sync when the user toggles the option.
  useEffect(() => {
    try {
      localStorage.setItem(MINIMIZE_ON_PLAY_KEY, String(minimizeOnPlay));
    } catch (_) {}
  }, [minimizeOnPlay]);

  useEffect(() => {
    if (groupRef.current) {
      groupRef.current.position.set(position[0], position[1], position[2]);
    }
  }, [position[0], position[1], position[2]]);

  const isMinimized = minimizeOnPlay && playInProgress;

  // Face-camera rotation: smoothly rotate UI to face the user (Y-axis only)
  useFrame((state, dt) => {
    if (groupRef.current == null) {
      return;
    }
    state.camera.getWorldPosition(cameraPositionHelper);
    groupRef.current.getWorldPosition(uiPositionHelper);
    quaternionHelper.setFromUnitVectors(
      zAxis,
      cameraPositionHelper.sub(uiPositionHelper).normalize()
    );
    eulerHelper.setFromQuaternion(quaternionHelper, 'YXZ');
    groupRef.current.rotation.y = damp(
      groupRef.current.rotation.y,
      eulerHelper.y,
      FACE_CAMERA_DAMPING,
      dt
    );
  });

  return (
    <HandleTarget>
      <group
        ref={groupRef}
        position={position}
        rotation={rotation}
        pointerEventsType={{ deny: 'grab' }}
      >
        {/* Drag Handle Bar - grab to reposition the panel */}
        <Handle
          handleRef={handleRef}
          targetRef={groupRef}
          scale={false}
          multitouch={false}
          rotate={false}
        >
          <mesh
            ref={handleRef}
            position={[0, isMinimized ? -0.15 : -0.42, 0.01]}
            onPointerEnter={() => {
              const mat = handleRef.current?.material as MeshStandardMaterial | undefined;
              if (mat) {
                mat.color.copy(HANDLE_COLOR_HOVER);
                mat.opacity = 0.9;
              }
            }}
            onPointerLeave={() => {
              const mat = handleRef.current?.material as MeshStandardMaterial | undefined;
              if (mat) {
                mat.color.copy(HANDLE_COLOR_DEFAULT);
                mat.opacity = 0.6;
              }
            }}
          >
            <boxGeometry args={[isMinimized ? 0.28 : 1.0, 0.05, 0.02]} />
            <meshStandardMaterial color="#666666" transparent opacity={0.6} roughness={0.5} />
          </mesh>
        </Handle>

        <Container
          pixelSize={0.001}
          width={isMinimized ? 520 : 2000}
          height={isMinimized ? 320 : 1400}
          alignItems="center"
          justifyContent="center"
          pointerEvents="auto"
          padding={isMinimized ? 24 : 40}
          sizeX={isMinimized ? 0.87 : 3.33}
          sizeY={isMinimized ? 0.53 : 2.33}
          flexDirection="column"
        >
          {isMinimized ? (
            <Container
              width="100%"
              flexDirection="column"
              gap={16}
              alignItems="center"
              justifyContent="center"
              backgroundColor="rgba(40, 40, 40, 0.85)"
              borderRadius={20}
              padding={24}
            >
              <Button
                onClick={onStartTeleop}
                variant="default"
                width={400}
                height={80}
                borderRadius={24}
                backgroundColor="rgba(220, 220, 220, 0.9)"
                hover={{
                  backgroundColor: 'rgba(100, 150, 255, 1)',
                  borderColor: 'white',
                  borderWidth: 2,
                }}
                disabled={playInProgress}
              >
                <Container flexDirection="row" alignItems="center" gap={8}>
                  {playLabel === 'Play' && <Image src="./play-circle.svg" width={40} height={40} />}
                  <Text fontSize={36} color="black" fontWeight="medium">
                    {playLabel}
                  </Text>
                </Container>
              </Button>
              <Button
                onClick={onResetTeleop}
                variant="default"
                width={400}
                height={80}
                borderRadius={24}
                backgroundColor="rgba(220, 220, 220, 0.9)"
                hover={{
                  backgroundColor: 'rgba(100, 150, 255, 1)',
                  borderColor: 'white',
                  borderWidth: 2,
                }}
              >
                <Container flexDirection="row" alignItems="center" gap={8}>
                  <Image src="./arrow-uturn-left.svg" width={40} height={40} />
                  <Text fontSize={36} color="black" fontWeight="medium">
                    Reset
                  </Text>
                </Container>
              </Button>
            </Container>
          ) : (
            <Container
              width={1900}
              height={980}
              backgroundColor="rgba(40, 40, 40, 0.85)"
              borderRadius={20}
              padding={50}
              paddingLeft={50}
              paddingRight={50}
              alignItems="center"
              justifyContent="center"
              flexDirection="row"
              gap={36}
            >
              {/* Left Column - Performance Metrics */}
              <Container
                width={520}
                flexDirection="column"
                gap={24}
                alignItems="center"
                justifyContent="center"
              >
                <Container
                  width="100%"
                  flexDirection="column"
                  gap={20}
                  alignItems="center"
                  justifyContent="center"
                  backgroundColor="rgba(20, 20, 20, 0.6)"
                  borderRadius={20}
                  padding={36}
                >
                  <Text
                    fontSize={52}
                    fontWeight="bold"
                    color="white"
                    textAlign="center"
                    marginBottom={4}
                  >
                    Performance
                  </Text>

                  <Container
                    flexDirection="column"
                    gap={14}
                    alignItems="stretch"
                    justifyContent="center"
                    width="100%"
                  >
                    <Container
                      backgroundColor="rgba(0, 0, 0, 0.5)"
                      borderRadius={12}
                      paddingTop={16}
                      paddingBottom={16}
                      paddingLeft={20}
                      paddingRight={20}
                      alignItems="center"
                      justifyContent="center"
                    >
                      <Text
                        fontSize={26}
                        color="rgba(180, 180, 180, 1)"
                        textAlign="center"
                        marginBottom={12}
                      >
                        Render FPS
                      </Text>
                      <Container width={200} alignItems="center" justifyContent="center">
                        <Text
                          fontSize={40}
                          color="rgba(100, 255, 100, 1)"
                          textAlign="center"
                          fontWeight="bold"
                        >
                          {renderFpsText}
                        </Text>
                      </Container>
                    </Container>

                    <Container
                      backgroundColor="rgba(0, 0, 0, 0.5)"
                      borderRadius={12}
                      paddingTop={16}
                      paddingBottom={16}
                      paddingLeft={20}
                      paddingRight={20}
                      alignItems="center"
                      justifyContent="center"
                    >
                      <Text
                        fontSize={26}
                        color="rgba(180, 180, 180, 1)"
                        textAlign="center"
                        marginBottom={12}
                      >
                        Streaming FPS
                      </Text>
                      <Container width={200} alignItems="center" justifyContent="center">
                        <Text
                          fontSize={40}
                          color="rgba(100, 200, 255, 1)"
                          textAlign="center"
                          fontWeight="bold"
                        >
                          {streamingFpsText}
                        </Text>
                      </Container>
                    </Container>

                    <Container
                      backgroundColor="rgba(0, 0, 0, 0.5)"
                      borderRadius={12}
                      paddingTop={16}
                      paddingBottom={16}
                      paddingLeft={20}
                      paddingRight={20}
                      alignItems="center"
                      justifyContent="center"
                    >
                      <Text
                        fontSize={26}
                        color="rgba(180, 180, 180, 1)"
                        textAlign="center"
                        marginBottom={12}
                      >
                        Pose-to-Render
                      </Text>
                      <Container width={200} alignItems="center" justifyContent="center">
                        <Text
                          fontSize={40}
                          color="rgba(255, 200, 100, 1)"
                          textAlign="center"
                          fontWeight="bold"
                        >
                          {poseToRenderText}
                        </Text>
                      </Container>
                    </Container>
                  </Container>
                </Container>

                <Container
                  flexDirection="row"
                  alignItems="center"
                  justifyContent="center"
                  gap={14}
                  marginTop={20}
                  cursor="pointer"
                  onClick={() => setMinimizeOnPlay(v => !v)}
                >
                  <Container
                    width={48}
                    height={48}
                    borderRadius={8}
                    borderWidth={2}
                    borderColor="rgba(200, 200, 200, 1)"
                    backgroundColor="rgba(60, 60, 60, 0.8)"
                    alignItems="center"
                    justifyContent="center"
                    padding={8}
                  >
                    {minimizeOnPlay && (
                      <Container
                        width="100%"
                        height="100%"
                        borderRadius={4}
                        backgroundColor="rgba(100, 255, 100, 0.95)"
                      />
                    )}
                  </Container>
                  <Text fontSize={30} color="rgba(220, 220, 220, 1)">
                    Minimize on play
                  </Text>
                </Container>
              </Container>

              {/* Right Column - Controls */}
              <Container
                flexGrow={1}
                flexDirection="column"
                gap={20}
                alignItems="center"
                justifyContent="center"
              >
                {/* Title */}
                <Text fontSize={72} fontWeight="bold" color="white" textAlign="center">
                  Controls
                </Text>

                {/* Server Info */}
                <Container
                  flexDirection="column"
                  gap={8}
                  alignItems="center"
                  marginTop={4}
                  marginBottom={4}
                >
                  <Text fontSize={38} color="rgba(200, 200, 200, 1)" textAlign="center">
                    Server: {serverAddress}
                  </Text>
                  <Text fontSize={38} color="rgba(200, 200, 200, 1)" textAlign="center">
                    Status: {sessionStatus}
                  </Text>
                </Container>

                {/* Countdown Config Row */}
                <Container
                  flexDirection="row"
                  gap={16}
                  alignItems="center"
                  justifyContent="center"
                  marginTop={12}
                >
                  <Text fontSize={36} color="white">
                    Countdown
                  </Text>
                  <Button
                    onClick={onCountdownDecrease}
                    variant="default"
                    width={90}
                    height={90}
                    borderRadius={45}
                    backgroundColor="rgba(220, 220, 220, 0.9)"
                    disabled={countdownDisabled}
                  >
                    <Text fontSize={44} color="black" fontWeight="bold">
                      -
                    </Text>
                  </Button>
                  <Container
                    width={140}
                    height={90}
                    alignItems="center"
                    justifyContent="center"
                    backgroundColor="rgba(255,255,255,0.9)"
                    borderRadius={12}
                  >
                    <Text fontSize={48} color="black" fontWeight="bold">
                      {countdownSeconds}s
                    </Text>
                  </Container>
                  <Button
                    onClick={onCountdownIncrease}
                    variant="default"
                    width={90}
                    height={90}
                    borderRadius={45}
                    backgroundColor="rgba(220, 220, 220, 0.9)"
                    disabled={countdownDisabled}
                  >
                    <Text fontSize={44} color="black" fontWeight="bold">
                      +
                    </Text>
                  </Button>
                </Container>

                {/* Button Grid */}
                <Container
                  flexDirection="column"
                  gap={20}
                  alignItems="center"
                  justifyContent="center"
                  width="100%"
                  marginTop={16}
                >
                  {/* Start/reset row*/}
                  <Container flexDirection="row" gap={24} justifyContent="center">
                    <Button
                      onClick={onStartTeleop}
                      variant="default"
                      width={420}
                      height={100}
                      borderRadius={32}
                      backgroundColor="rgba(220, 220, 220, 0.9)"
                      hover={{
                        backgroundColor: 'rgba(100, 150, 255, 1)',
                        borderColor: 'white',
                        borderWidth: 2,
                      }}
                      disabled={playInProgress}
                    >
                      <Container flexDirection="row" alignItems="center" gap={10}>
                        {playLabel === 'Play' && (
                          <Image src="./play-circle.svg" width={50} height={50} />
                        )}
                        <Text fontSize={42} color="black" fontWeight="medium">
                          {playLabel}
                        </Text>
                      </Container>
                    </Button>

                    <Button
                      onClick={onResetTeleop}
                      variant="default"
                      width={420}
                      height={100}
                      borderRadius={32}
                      backgroundColor="rgba(220, 220, 220, 0.9)"
                      hover={{
                        backgroundColor: 'rgba(100, 150, 255, 1)',
                        borderColor: 'white',
                        borderWidth: 2,
                      }}
                    >
                      <Container flexDirection="row" alignItems="center" gap={10}>
                        <Image src="./arrow-uturn-left.svg" width={50} height={50} />
                        <Text fontSize={42} color="black" fontWeight="medium">
                          Reset
                        </Text>
                      </Container>
                    </Button>
                  </Container>

                  {/* Bottom Row */}
                  <Container flexDirection="row" justifyContent="center">
                    <Button
                      onClick={onDisconnect}
                      variant="destructive"
                      width={320}
                      height={90}
                      borderRadius={28}
                      backgroundColor="rgba(255, 150, 150, 0.9)"
                      hover={{
                        backgroundColor: 'rgba(255, 50, 50, 1)',
                        borderColor: 'white',
                        borderWidth: 2,
                      }}
                    >
                      <Container flexDirection="row" alignItems="center" gap={10}>
                        <Image src="./arrow-left-start-on-rectangle.svg" width={50} height={50} />
                        <Text fontSize={38} color="black" fontWeight="medium">
                          Disconnect
                        </Text>
                      </Container>
                    </Button>
                  </Container>
                </Container>
              </Container>
            </Container>
          )}
        </Container>
      </group>
    </HandleTarget>
  );
}
