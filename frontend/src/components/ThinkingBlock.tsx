// src/components/ThinkingBlock.tsx
// Collapsible "thinking / reasoning" section shown during + after streaming.
import React, { useState } from 'react';
import type { ThinkingStep } from '../types';

interface Props {
  steps: ThinkingStep[];
  isStreaming: boolean;
}

export default function ThinkingBlock({ steps, isStreaming }: Props) {
  const [open, setOpen] = useState(true);

  if (steps.length === 0) return null;

  return (
    <div className="mb-3 rounded-xl overflow-hidden fade-slide-in"
      style={{ backgroundColor: 'rgba(138,180,248,0.06)', border: '1px solid rgba(138,180,248,0.15)' }}>

      {/* Header */}
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex items-center justify-between w-full px-4 py-2.5 text-sm"
        style={{ color: 'var(--accent)' }}>
        <div className="flex items-center gap-2">
          {isStreaming ? (
            <div className="flex gap-1">
              {[0, 1, 2].map((i) => (
                <div key={i} className="w-1.5 h-1.5 rounded-full thinking-dot"
                  style={{ backgroundColor: 'var(--accent)', animationDelay: `${i * 0.2}s` }} />
              ))}
            </div>
          ) : (
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
            </svg>
          )}
          <span className="font-medium">
            {isStreaming ? 'Thinking…' : `Reasoning (${steps.length} steps)`}
          </span>
        </div>
        <svg
          className={`w-4 h-4 transition-transform duration-200 ${open ? 'rotate-180' : ''}`}
          fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {/* Steps */}
      {open && (
        <div className="px-4 pb-3 space-y-2 thinking-content">
          {steps.map((step, i) => (
            <div key={i} className="flex gap-3 fade-slide-in">
              {/* Step indicator */}
              <div className="flex flex-col items-center mt-1 shrink-0">
                <div className="w-5 h-5 rounded-full flex items-center justify-center text-xs font-bold"
                  style={{
                    backgroundColor: step.done ? 'rgba(52,168,83,0.2)' : 'rgba(138,180,248,0.15)',
                    color: step.done ? '#34a853' : 'var(--accent)',
                    border: `1px solid ${step.done ? 'rgba(52,168,83,0.4)' : 'rgba(138,180,248,0.3)'}`,
                  }}>
                  {step.done ? '✓' : i + 1}
                </div>
                {i < steps.length - 1 && (
                  <div className="w-px flex-1 mt-1" style={{ backgroundColor: 'var(--border)' }} />
                )}
              </div>

              {/* Content */}
              <div className="pb-2 min-w-0">
                <p className="text-xs font-semibold mb-0.5" style={{ color: 'var(--accent)' }}>
                  {step.stage}
                </p>
                <p className="text-sm" style={{ color: 'var(--text-secondary)' }}>
                  {step.content}
                  {!step.done && isStreaming && i === steps.length - 1 && (
                    <span className="streaming-cursor" />
                  )}
                </p>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
