/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

import React from 'react';

import type { FlowStep } from '../types';

const STEPS: Array<{ id: FlowStep; label: string }> = [
  { id: 'configure', label: 'Configure' },
  { id: 'join', label: 'Join / Connect' },
  { id: 'preflight', label: 'Pre-flight' },
  { id: 'live', label: 'Live' },
];

interface StepperProps {
  activeStep: FlowStep;
  status: Record<FlowStep, 'done' | 'current' | 'pending'>;
  onSelect: (step: FlowStep) => void;
}

export function Stepper({ activeStep, status, onSelect }: StepperProps) {
  return (
    <nav className="stepper" aria-label="Teleop flow">
      {STEPS.map((item, index) => (
        <button
          key={item.id}
          className={`stepper-item ${activeStep === item.id ? 'active' : ''} ${status[item.id]}`}
          type="button"
          onClick={() => onSelect(item.id)}
        >
          <span>{status[item.id] === 'done' ? '✓' : index + 1}</span>
          {item.label}
        </button>
      ))}
    </nav>
  );
}
