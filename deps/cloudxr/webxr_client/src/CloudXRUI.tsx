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
 * - Panel depth: full control panel, compact (when "minimize on play" and teleop active), or hidden
 *   (semi-transparent Show + slim drag handle).
 *
 * The UI is positioned in 3D space and designed for VR/AR interaction with
 * visual feedback and clear button labeling. All interactions are passed
 * back to the parent component through callback props.
 */

import arrowLeftStartOnRectangleSvg from "./icons/arrow-left-start-on-rectangle.svg";
import arrowUturnLeftSvg from "./icons/arrow-uturn-left.svg";
import playCircleSvg from "./icons/play-circle.svg";
import { PerformanceCanvasImage } from "@helpers/react/PerformanceCanvasImage";
import { useXRButton } from "@helpers/react/useXRButton";
import { ReadonlySignal } from "@preact/signals-react";
import { useFrame } from "@react-three/fiber";
import { Handle, HandleTarget, HandleState } from "@react-three/handle";
import { Container, Text, Image } from "@react-three/uikit";
import { Button } from "@react-three/uikit-default";
import React, { useRef, useState, useEffect } from "react";
import {
  Color,
  Group,
  Mesh,
  MeshStandardMaterial,
  Object3D,
  Vector3,
} from "three";
import { damp } from "three/src/math/MathUtils.js";

// Face-camera rotation constants
const FACE_CAMERA_DAMPING = 10; // Higher = faster rotation toward camera

/** Display size for the Performance metrics slot (width and height passed to PerformanceCanvasImage and its container). */
const METRIC_SLOT_WIDTH = 512;
const METRIC_SLOT_HEIGHT = 250;

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
  /** From settings: hide control panel when immersive XR begins. */
  panelHiddenAtStart?: boolean;
  /** Immersive XR active; used to apply panelHiddenAtStart on session enter. */
  isXRMode?: boolean;
  /** Show recording controls (Record/Replay/Save) — enabled via Troubleshooting settings. */
  showRecordingControls?: boolean;
  recorderMode?: "idle" | "recording" | "replaying";
  hasSavedRecording?: boolean;
  recordedFrameCount?: number;
  onStartRecord?: () => void;
  onStopRecord?: () => void;
  onStartReplay?: () => void;
  onStopReplay?: () => void;
  onSaveRecording?: () => void;
  /** Show/hide rolling path trace for hands/controllers. Driven by the 2D settings panel. */
  showTrace?: boolean;
}

// Reusable objects for face-camera rotation (avoid allocations in render loop)
const cameraPositionHelper = new Vector3();
const uiPositionHelper = new Vector3();

// Handle hover colors (module-level to avoid per-render allocations)
const HANDLE_COLOR_DEFAULT = new Color("#666666");
const HANDLE_COLOR_HOVER = new Color("#aaaaaa");

// Workaround for @pmndrs/handle defaultApply behavior: defaultApply copies
// state.current.quaternion to the target on every drag frame AND on drag release.
// With rotate={false}, state.current.quaternion is always the drag-start quaternion,
// so it resets our face-camera rotation on every frame (priority -1 runs before
// face-camera priority 0) and wipes it entirely on drag release.
// By providing a custom apply that skips quaternion, face-camera owns rotation fully.
// Scale is intentionally omitted too: scale={false} keeps it constant, so copying
// it would be a no-op. If scale is ever enabled on this Handle, add it back here.
function applyPositionSkipRotation(
  state: HandleState<unknown>,
  target: Object3D,
): void {
  target.position.copy(state.current.position);
}

export default function CloudXR3DUI({
  onStartTeleop,
  onDisconnect,
  onResetTeleop,
  serverAddress = "127.0.0.1",
  sessionStatus = "Disconnected",
  playLabel = "Play",
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
  panelHiddenAtStart = false,
  isXRMode = false,
  showRecordingControls = false,
  recorderMode = "idle",
  hasSavedRecording = false,
  recordedFrameCount = 0,
  onStartRecord,
  onStopRecord,
  onStartReplay,
  onStopReplay,
  onSaveRecording,
  showTrace = false,
}: CloudXRUIProps) {
  const MINIMIZE_ON_PLAY_KEY = "cxr.isaac.minimizeOnPlay";

  const groupRef = useRef<Group>(null);
  const handleRef = useRef<Mesh>(null);
  const xrButton = useXRButton();
  // useState(initializer): React calls the fn once on mount to get the initial value; it returns [value, setter]. Setter used in onClick below.
  const [minimizeOnPlay, setMinimizeOnPlay] = useState(() => {
    try {
      const saved = localStorage.getItem(MINIMIZE_ON_PLAY_KEY);
      return saved === "true";
    } catch {
      return false;
    }
  });

  /** Control panel hidden: small Show control (see settings to hide control panel on XR enter). */
  const [panelHidden, setPanelHidden] = useState(false);
  const prevXRMode = useRef(false);

  useEffect(() => {
    if (isXRMode && !prevXRMode.current) {
      setPanelHidden(panelHiddenAtStart);
    }
    prevXRMode.current = isXRMode;
  }, [isXRMode, panelHiddenAtStart]);

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

  const isCompact = minimizeOnPlay && playInProgress;
  const isMinimizedLayout = isCompact || panelHidden;
  const handleWidth = panelHidden ? 0.12 : isCompact ? 0.28 : 1.0;
  const handleY = panelHidden ? -0.065 : isCompact ? -0.15 : -0.42;

  // Face-camera rotation: smoothly rotate UI to face the user (Y-axis only)
  useFrame((state, dt) => {
    if (groupRef.current == null) {
      return;
    }
    state.camera.getWorldPosition(cameraPositionHelper);
    groupRef.current.getWorldPosition(uiPositionHelper);

    // Project onto the horizontal plane (XZ) to get a pure yaw angle.
    // Using atan2 avoids the 3D-quaternion→Euler extraction that can give wrong
    // yaw when the camera has significant height offset relative to the panel.
    const dx = cameraPositionHelper.x - uiPositionHelper.x;
    const dz = cameraPositionHelper.z - uiPositionHelper.z;
    let targetY = Math.atan2(dx, dz);

    // Wrap the angular difference to [-π, π] so damp() always takes the
    // shortest path.  Without this, when the target crosses the ±π boundary
    // (camera near the side/behind the panel), damp interpolates the long way
    // around and the panel snaps to face away from the user.
    const currentY = groupRef.current.rotation.y;
    let diff = targetY - currentY;
    diff = diff - Math.round(diff / (2 * Math.PI)) * (2 * Math.PI);
    targetY = currentY + diff;

    groupRef.current.rotation.y = damp(
      currentY,
      targetY,
      FACE_CAMERA_DAMPING,
      dt,
    );
  });

  return (
    <HandleTarget>
      <group
        ref={groupRef}
        position={position}
        rotation={rotation}
        pointerEventsType={{ deny: "grab" }}
      >
        {/* Drag Handle Bar - grab to reposition the panel */}
        <Handle
          handleRef={handleRef}
          targetRef={groupRef}
          scale={false}
          multitouch={false}
          rotate={false}
          apply={applyPositionSkipRotation}
        >
          <mesh
            ref={handleRef}
            position={[0, handleY, 0.01]}
            onPointerEnter={() => {
              const mat = handleRef.current?.material as
                | MeshStandardMaterial
                | undefined;
              if (mat) {
                mat.color.copy(HANDLE_COLOR_HOVER);
                mat.opacity = panelHidden ? 0.55 : 0.9;
              }
            }}
            onPointerLeave={() => {
              const mat = handleRef.current?.material as
                | MeshStandardMaterial
                | undefined;
              if (mat) {
                mat.color.copy(HANDLE_COLOR_DEFAULT);
                mat.opacity = panelHidden ? 0.35 : 0.6;
              }
            }}
          >
            <boxGeometry
              args={[handleWidth, panelHidden ? 0.035 : 0.05, 0.02]}
            />
            <meshStandardMaterial
              color="#666666"
              transparent
              opacity={panelHidden ? 0.35 : 0.6}
              roughness={0.5}
            />
          </mesh>
        </Handle>

        <Container
          pixelSize={0.001}
          width={panelHidden ? 128 : isCompact ? 520 : 2000}
          height={panelHidden ? 128 : isCompact ? 320 : 1400}
          alignItems="center"
          justifyContent="center"
          pointerEvents="auto"
          padding={panelHidden ? 0 : isCompact ? 24 : 40}
          sizeX={panelHidden ? 0.2 : isCompact ? 0.87 : 3.33}
          sizeY={panelHidden ? 0.2 : isCompact ? 0.53 : 2.33}
          flexDirection="column"
        >
          {panelHidden ? (
            <Button
              {...xrButton("show-panel", () => setPanelHidden(false))}
              variant="default"
              width={112}
              height={112}
              borderRadius={56}
              backgroundColor="rgba(90, 130, 210, 0.42)"
              hover={{
                backgroundColor: "rgba(90, 130, 210, 0.72)",
                borderColor: "rgba(255, 255, 255, 0.6)",
                borderWidth: 2,
              }}
            >
              <Text
                fontSize={26}
                color="rgba(255, 255, 255, 0.95)"
                fontWeight="bold"
              >
                Show
              </Text>
            </Button>
          ) : isCompact ? (
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
                {...xrButton("start-min", onStartTeleop)}
                variant="default"
                width={400}
                height={80}
                borderRadius={24}
                backgroundColor="rgba(220, 220, 220, 0.9)"
                hover={{
                  backgroundColor: "rgba(100, 150, 255, 1)",
                  borderColor: "white",
                  borderWidth: 2,
                }}
                disabled={playInProgress}
              >
                <Container flexDirection="row" alignItems="center" gap={8}>
                  {playLabel === "Play" && (
                    <Image src={playCircleSvg} width={40} height={40} />
                  )}
                  <Text fontSize={36} color="black" fontWeight="medium">
                    {playLabel}
                  </Text>
                </Container>
              </Button>
              <Container
                flexDirection="row"
                gap={14}
                alignItems="center"
                justifyContent="center"
                width="100%"
              >
                <Button
                  {...xrButton("reset-min", onResetTeleop)}
                  variant="default"
                  width={292}
                  height={80}
                  borderRadius={24}
                  backgroundColor="rgba(220, 220, 220, 0.9)"
                  hover={{
                    backgroundColor: "rgba(100, 150, 255, 1)",
                    borderColor: "white",
                    borderWidth: 2,
                  }}
                >
                  <Container flexDirection="row" alignItems="center" gap={8}>
                    <Image src={arrowUturnLeftSvg} width={40} height={40} />
                    <Text fontSize={36} color="black" fontWeight="medium">
                      Reset
                    </Text>
                  </Container>
                </Button>
                <Button
                  {...xrButton("hide-panel-compact", () =>
                    setPanelHidden(true),
                  )}
                  variant="default"
                  width={94}
                  height={80}
                  borderRadius={20}
                  backgroundColor="rgba(70, 75, 90, 0.55)"
                  hover={{
                    backgroundColor: "rgba(90, 95, 115, 0.85)",
                    borderColor: "rgba(255, 255, 255, 0.5)",
                    borderWidth: 2,
                  }}
                >
                  <Text
                    fontSize={26}
                    color="rgba(255, 255, 255, 0.92)"
                    fontWeight="medium"
                  >
                    Hide
                  </Text>
                </Button>
              </Container>
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
                    width={METRIC_SLOT_WIDTH}
                    height={METRIC_SLOT_HEIGHT}
                    alignItems="center"
                    justifyContent="center"
                  >
                    <PerformanceCanvasImage
                      width={METRIC_SLOT_WIDTH}
                      height={METRIC_SLOT_HEIGHT}
                      renderFpsText={renderFpsText}
                      streamingFpsText={streamingFpsText}
                      poseToRenderText={poseToRenderText}
                    />
                  </Container>
                </Container>

                <Container
                  flexDirection="row"
                  alignItems="center"
                  justifyContent="center"
                  gap={14}
                  marginTop={20}
                  cursor="pointer"
                  {...xrButton("minimize", () => setMinimizeOnPlay((v) => !v))}
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
                    Minimize on play (compact controls)
                  </Text>
                </Container>

                {/* Recording controls — shown only when enabled in Troubleshooting settings */}
                {showRecordingControls && (
                  <Container
                    width="100%"
                    flexDirection="column"
                    gap={12}
                    alignItems="center"
                    marginTop={16}
                    backgroundColor="rgba(20, 20, 20, 0.5)"
                    borderRadius={16}
                    padding={20}
                  >
                    <Text
                      fontSize={36}
                      fontWeight="bold"
                      color="rgba(220, 220, 220, 1)"
                    >
                      Recording
                    </Text>
                    {recorderMode !== "idle" && (
                      <Text fontSize={26} color="rgba(180, 220, 180, 1)">
                        {recorderMode === "recording"
                          ? `● REC ${recordedFrameCount} frames`
                          : `▶ Replaying`}
                      </Text>
                    )}
                    <Container
                      flexDirection="row"
                      gap={12}
                      alignItems="center"
                      justifyContent="center"
                    >
                      {/* Record / Stop Record */}
                      {recorderMode !== "replaying" && (
                        <Button
                          {...xrButton(
                            "rec",
                            recorderMode === "recording"
                              ? onStopRecord
                              : onStartRecord,
                          )}
                          variant="default"
                          width={160}
                          height={72}
                          borderRadius={20}
                          backgroundColor={
                            recorderMode === "recording"
                              ? "rgba(220, 60, 60, 0.9)"
                              : "rgba(220, 220, 220, 0.9)"
                          }
                          hover={{
                            backgroundColor: "rgba(255, 100, 100, 1)",
                            borderColor: "white",
                            borderWidth: 2,
                          }}
                        >
                          <Text fontSize={30} color="black" fontWeight="medium">
                            {recorderMode === "recording" ? "Stop" : "● Rec"}
                          </Text>
                        </Button>
                      )}
                      {/* Replay / Stop Replay */}
                      {recorderMode !== "recording" && (
                        <Button
                          {...xrButton(
                            "replay",
                            recorderMode === "replaying"
                              ? onStopReplay
                              : onStartReplay,
                          )}
                          variant="default"
                          width={160}
                          height={72}
                          borderRadius={20}
                          backgroundColor="rgba(220, 220, 220, 0.9)"
                          hover={{
                            backgroundColor: "rgba(100, 150, 255, 1)",
                            borderColor: "white",
                            borderWidth: 2,
                          }}
                          disabled={
                            recorderMode === "idle" && !hasSavedRecording
                          }
                        >
                          <Text fontSize={30} color="black" fontWeight="medium">
                            {recorderMode === "replaying" ? "Stop" : "▶ Play"}
                          </Text>
                        </Button>
                      )}
                      {/* Save / Load — only when idle */}
                      {recorderMode === "idle" && hasSavedRecording && (
                        <Button
                          {...xrButton("save-rec", onSaveRecording)}
                          variant="default"
                          width={120}
                          height={72}
                          borderRadius={20}
                          backgroundColor="rgba(220, 220, 220, 0.9)"
                          hover={{
                            backgroundColor: "rgba(100, 200, 100, 1)",
                            borderColor: "white",
                            borderWidth: 2,
                          }}
                        >
                          <Text fontSize={30} color="black" fontWeight="medium">
                            Save
                          </Text>
                        </Button>
                      )}
                    </Container>
                  </Container>
                )}
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
                <Text
                  fontSize={72}
                  fontWeight="bold"
                  color="white"
                  textAlign="center"
                >
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
                  <Text
                    fontSize={38}
                    color="rgba(200, 200, 200, 1)"
                    textAlign="center"
                  >
                    Server: {serverAddress}
                  </Text>
                  <Text
                    fontSize={38}
                    color="rgba(200, 200, 200, 1)"
                    textAlign="center"
                  >
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
                    {...xrButton("countdown-dec", onCountdownDecrease)}
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
                    {...xrButton("countdown-inc", onCountdownIncrease)}
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
                  <Container
                    flexDirection="row"
                    gap={24}
                    justifyContent="center"
                  >
                    <Button
                      {...xrButton("start", onStartTeleop)}
                      variant="default"
                      width={420}
                      height={100}
                      borderRadius={32}
                      backgroundColor="rgba(220, 220, 220, 0.9)"
                      hover={{
                        backgroundColor: "rgba(100, 150, 255, 1)",
                        borderColor: "white",
                        borderWidth: 2,
                      }}
                      disabled={playInProgress}
                    >
                      <Container
                        flexDirection="row"
                        alignItems="center"
                        gap={10}
                      >
                        {playLabel === "Play" && (
                          <Image src={playCircleSvg} width={50} height={50} />
                        )}
                        <Text fontSize={42} color="black" fontWeight="medium">
                          {playLabel}
                        </Text>
                      </Container>
                    </Button>

                    <Button
                      {...xrButton("reset", onResetTeleop)}
                      variant="default"
                      width={420}
                      height={100}
                      borderRadius={32}
                      backgroundColor="rgba(220, 220, 220, 0.9)"
                      hover={{
                        backgroundColor: "rgba(100, 150, 255, 1)",
                        borderColor: "white",
                        borderWidth: 2,
                      }}
                    >
                      <Container
                        flexDirection="row"
                        alignItems="center"
                        gap={10}
                      >
                        <Image src={arrowUturnLeftSvg} width={50} height={50} />
                        <Text fontSize={42} color="black" fontWeight="medium">
                          Reset
                        </Text>
                      </Container>
                    </Button>
                  </Container>

                  {/* Bottom Row */}
                  <Container
                    flexDirection="row"
                    justifyContent="center"
                    alignItems="center"
                    gap={18}
                  >
                    <Button
                      {...xrButton("disconnect", onDisconnect)}
                      variant="destructive"
                      width={320}
                      height={90}
                      borderRadius={28}
                      backgroundColor="rgba(255, 150, 150, 0.9)"
                      hover={{
                        backgroundColor: "rgba(255, 50, 50, 1)",
                        borderColor: "white",
                        borderWidth: 2,
                      }}
                    >
                      <Container
                        flexDirection="row"
                        alignItems="center"
                        gap={10}
                      >
                        <Image
                          src={arrowLeftStartOnRectangleSvg}
                          width={50}
                          height={50}
                        />
                        <Text fontSize={38} color="black" fontWeight="medium">
                          Disconnect
                        </Text>
                      </Container>
                    </Button>
                    <Button
                      {...xrButton("hide-panel-full", () =>
                        setPanelHidden(true),
                      )}
                      variant="default"
                      width={100}
                      height={90}
                      borderRadius={22}
                      backgroundColor="rgba(70, 75, 90, 0.55)"
                      hover={{
                        backgroundColor: "rgba(90, 95, 115, 0.88)",
                        borderColor: "rgba(255, 255, 255, 0.5)",
                        borderWidth: 2,
                      }}
                    >
                      <Text
                        fontSize={28}
                        color="rgba(255, 255, 255, 0.92)"
                        fontWeight="medium"
                      >
                        Hide
                      </Text>
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
