// src/types.ts

export type MessageRole = 'user' | 'assistant';

export interface ThinkingStep {
  stage: string;        // e.g. "Engineering", "Analytics"
  content: string;
  done: boolean;
}

export interface EChartsOption {
  [key: string]: unknown;
}

export interface Message {
  id: string;
  role: MessageRole;
  content: string;
  thinking?: ThinkingStep[];
  thinkingExpanded?: boolean;
  charts?: Record<string, EChartsOption>;
  insights?: string[];
  isStreaming?: boolean;
  timestamp: number;
}

export interface Chat {
  id: string;
  title: string;
  messages: Message[];
  csvFile: File | null;
  csvName: string | null;
  createdAt: number;
}

export interface RunResponse {
  run_id: string;
  pipeline_stage: string;
  active_division: string | null;
  intent_class: string | null;
  artifact_paths: Record<string, string>;
  echarts_options: Record<string, EChartsOption>;
  insights: string[];
  user_message: string | null;
  error: string | null;
  project_log?: any[];
}

export interface StreamChunk {
  type: 'thinking' | 'content' | 'charts' | 'insights' | 'done' | 'error' | 'log';
  stage?: string;
  text?: string;
  charts?: Record<string, EChartsOption>;
  insights?: string[];
  error?: string;
  log?: any[];
}
