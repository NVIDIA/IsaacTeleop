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
 * RecorderContext.tsx - React context for XRInputRecorder state.
 *
 * Owns the recorder instance and React-visible state. Heavy per-frame work runs in
 * RecorderComponent via useFrame; this context provides actions and state
 * to descendant components.
 */

import React, {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
} from "react";

import {
  XRInputRecorder,
  type Recording,
  type ReplayPacing,
} from "./xrInputRecorder";

export interface RecorderContextValue {
  recorder: XRInputRecorder;
  mode: "idle" | "recording" | "replaying";
  savedRecording: Recording | null;
  recordedFrameCount: number;
  replayPacing: ReplayPacing;
  startRecord: () => void;
  stopRecord: () => void;
  startReplay: () => void;
  stopReplay: () => void;
  setReplayPacing: (pacing: ReplayPacing) => void;
  onSaveRecording: () => void;
  onLoadRecording: () => void;
  onFrameRecord: (count: number) => void;
}

const RecorderContext = createContext<RecorderContextValue | null>(null);

export function RecorderProvider({ children }: { children: React.ReactNode }) {
  const recorder = useMemo(() => new XRInputRecorder(), []);
  const [mode, setMode] = useState<"idle" | "recording" | "replaying">("idle");
  const [savedRecording, setSavedRecordingState] = useState<Recording | null>(
    null,
  );
  const [recordedFrameCount, setRecordedFrameCount] = useState(0);
  const [replayPacing, setReplayPacingState] = useState<ReplayPacing>("time");
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const startRecord = useCallback(() => {
    if (recorder.mode !== "idle") return;
    recorder.startRecording();
    setMode("recording");
    setRecordedFrameCount(0);
  }, [recorder]);

  const stopRecord = useCallback(() => {
    if (recorder.mode !== "recording") return;
    recorder.stopRecording();
    const rec = recorder.getRecording();
    setSavedRecordingState(rec);
    setRecordedFrameCount(rec.frames.length);
    setMode("idle");
  }, [recorder]);

  const startReplay = useCallback(() => {
    if (recorder.mode !== "idle" || !savedRecording) return;
    recorder.startReplay(savedRecording, true, replayPacing);
    setMode("replaying");
  }, [recorder, replayPacing, savedRecording]);

  const stopReplay = useCallback(() => {
    if (recorder.mode !== "replaying") return;
    recorder.stopReplay();
    setMode("idle");
  }, [recorder]);

  const setReplayPacing = useCallback((pacing: ReplayPacing) => {
    setReplayPacingState(pacing);
  }, []);

  const onSaveRecording = useCallback(() => {
    if (!savedRecording) return;
    const blob = new Blob([JSON.stringify(savedRecording)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "isaacteleop-input-recording.json";
    a.click();
    URL.revokeObjectURL(url);
  }, [savedRecording]);

  const acceptRecording = useCallback((r: Recording) => {
    setSavedRecordingState(r);
    setRecordedFrameCount(r.frames.length);
  }, []);

  const onFileChange = useCallback(async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;
    try {
      acceptRecording(XRInputRecorder.importJSON(await file.text()));
    } catch (error) {
      console.error("[Recorder] Failed to load recording:", error);
    } finally {
      event.target.value = "";
    }
  }, [acceptRecording]);

  const onLoadRecording = useCallback(() => {
    fileInputRef.current?.click();
  }, []);

  const onFrameRecord = useCallback((count: number) => {
    setRecordedFrameCount(count);
  }, []);

  const value: RecorderContextValue = {
    recorder,
    mode,
    savedRecording,
    recordedFrameCount,
    replayPacing,
    startRecord,
    stopRecord,
    startReplay,
    stopReplay,
    setReplayPacing,
    onSaveRecording,
    onLoadRecording,
    onFrameRecord,
  };

  return (
    <RecorderContext.Provider value={value}>
      {children}
      <input
        ref={fileInputRef}
        type="file"
        accept=".json,application/json"
        hidden
        onChange={onFileChange}
      />
    </RecorderContext.Provider>
  );
}

export function useRecorder(): RecorderContextValue {
  const ctx = useContext(RecorderContext);
  if (!ctx) throw new Error("useRecorder must be used inside RecorderProvider");
  return ctx;
}
