// src/api.ts
// Handles communication with the FastAPI backend.
// Simulates streaming via SSE-style polling on top of the /run endpoint.

import type { EChartsOption, RunResponse, StreamChunk, ThinkingStep } from './types';

const BASE = '/api';

// ── Upload CSV ──────────────────────────────────────────────────────────────

export async function uploadCSV(file: File): Promise<string> {
  const form = new FormData();
  form.append('file', file);

  const res = await fetch(`${BASE}/upload`, { method: 'POST', body: form });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Upload failed' }));
    throw new Error(err.detail ?? 'Upload failed');
  }
  const data = await res.json();
  return data.file_path as string;
}

// ── Run pipeline with simulated streaming ────────────────────────────────────
//
// The FastAPI /run endpoint is synchronous. We simulate a "thinking + streaming"
// UX by:
//  1. Emitting staged thinking steps locally as the request is in-flight.
//  2. When the response arrives, streaming the text content word-by-word.

// No longer needed, polling real backend status.

async function sleep(ms: number) {
  return new Promise((r) => setTimeout(r, ms));
}

export async function* runPipeline(
  userQuery: string,
  filePath: string,
): AsyncGenerator<StreamChunk> {
  const runId = `RUN-${Math.random().toString(36).substring(2, 10).toUpperCase()}`;

  // 1. Emit thinking stages while request is in-flight
  const thinkingPromise = fetch(`${BASE}/run`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ user_query: userQuery, data_path: filePath, run_id: runId }),
  });

  let isDone = false;
  let response: Response | undefined;

  thinkingPromise.then((res) => {
    isDone = true;
    response = res;
  }).catch(() => {
    isDone = true;
  });

  let lastLogCount = 0;

  while (!isDone) {
    await sleep(800);
    try {
      const statusRes = await fetch(`${BASE}/status/${runId}`);
      if (statusRes.ok) {
        const status = await statusRes.json();
        const logs = status.project_log || [];
        if (logs.length > lastLogCount) {
          for (let i = lastLogCount; i < logs.length; i++) {
            const log = logs[i];
            const division = log.division?.toUpperCase() || 'SYSTEM';
            const event = log.event_type || log.event || 'UPDATE';
            yield {
              type: 'thinking',
              stage: `[${division}] ${event}`,
              text: log.summary || log.notes || 'Processing...',
            };
          }
          lastLogCount = logs.length;
        }
      }
    } catch (e) {
      // Ignore polling errors
    }
  }

  if (!response) {
    yield { type: 'error', error: 'Failed to reach the backend. Is FastAPI running?' };
    return;
  }

  if (!response.ok) {
    const err = await response.json().catch(() => ({ detail: 'Pipeline error' }));
    yield { type: 'error', error: err.detail ?? 'Pipeline error' };
    return;
  }

  const data: RunResponse = await response.json();

  // 3. Stream answer text word-by-word
  const fullText = buildAnswerText(data);
  const words = fullText.split(' ');
  let accumulated = '';

  for (const word of words) {
    accumulated += (accumulated ? ' ' : '') + word;
    yield { type: 'content', text: accumulated };
    await sleep(28);
  }

  // 4. Emit charts and insights
  if (Object.keys(data.echarts_options ?? {}).length > 0) {
    yield { type: 'charts', charts: data.echarts_options };
  }
  if ((data.insights ?? []).length > 0) {
    yield { type: 'insights', insights: data.insights };
  }

  yield { type: 'done' };
}

function buildAnswerText(data: RunResponse): string {
  if (data.error) return `⚠️ ${data.error}`;
  if (data.user_message) return data.user_message;

  const stage = data.pipeline_stage ?? 'COMPLETE';
  const intent = data.intent_class ?? 'EXPLORATORY';
  const chartCount = Object.keys(data.echarts_options ?? {}).length;
  const artifactCount = Object.keys(data.artifact_paths ?? {}).length;

  let text = `Pipeline completed successfully. Intent classified as **${intent}**.`;
  if (artifactCount > 0) text += ` ${artifactCount} artifact(s) produced.`;
  if (chartCount > 0) text += ` Generated **${chartCount} chart(s)** from your data — see below.`;
  if (stage === 'REQUEST_CLARIFICATION' || stage === 'HITL_PAUSE') {
    text = data.user_message ?? 'The pipeline needs your input to continue.';
  }
  return text;
}

// ── Health check ─────────────────────────────────────────────────────────────

export async function healthCheck(): Promise<boolean> {
  try {
    const res = await fetch(`${BASE}/health`, { signal: AbortSignal.timeout(3000) });
    return res.ok;
  } catch {
    return false;
  }
}
