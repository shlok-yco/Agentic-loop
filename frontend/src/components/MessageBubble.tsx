// src/components/MessageBubble.tsx
import React from 'react';
import type { Message } from '../types';
import ThinkingBlock from './ThinkingBlock';
import ChartPanel from './ChartPanel';

interface Props {
  message: Message;
}

// Simple markdown-lite renderer (bold, inline code)
function renderText(text: string) {
  const parts = text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g);
  return parts.map((part, i) => {
    if (part.startsWith('**') && part.endsWith('**')) {
      return <strong key={i}>{part.slice(2, -2)}</strong>;
    }
    if (part.startsWith('`') && part.endsWith('`')) {
      return (
        <code key={i} className="px-1 py-0.5 rounded text-xs font-mono"
          style={{ backgroundColor: 'rgba(138,180,248,0.12)', color: 'var(--accent)' }}>
          {part.slice(1, -1)}
        </code>
      );
    }
    return part;
  });
}

export default function MessageBubble({ message }: Props) {
  const isUser = message.role === 'user';

  if (isUser) {
    return (
      <div className="flex justify-end mb-4 fade-slide-in">
        <div className="max-w-[70%] px-4 py-3 rounded-2xl rounded-tr-sm text-sm leading-relaxed"
          style={{ backgroundColor: 'var(--user-bubble)', color: 'var(--text-primary)' }}>
          {message.content}
        </div>
      </div>
    );
  }

  // Assistant
  return (
    <div className="flex gap-3 mb-6 fade-slide-in">
      {/* Avatar */}
      <div className="shrink-0 mt-1 w-8 h-8 rounded-full flex items-center justify-center"
        style={{ background: 'linear-gradient(135deg, #4285f4, #a142f4)' }}>
        <span className="text-white text-xs font-bold">B</span>
      </div>

      <div className="flex-1 min-w-0">
        {/* Thinking block */}
        {(message.thinking ?? []).length > 0 && (
          <ThinkingBlock
            steps={message.thinking!}
            isStreaming={!!message.isStreaming}
          />
        )}

        {/* Skeleton while waiting for first token */}
        {message.isStreaming && !message.content && (
          <div className="space-y-2 mt-1">
            <div className="shimmer-bg h-4 rounded w-3/4" />
            <div className="shimmer-bg h-4 rounded w-1/2" />
          </div>
        )}

        {/* Main content */}
        {message.content && (
          <p className={`text-sm leading-7 ${message.isStreaming ? 'streaming-cursor' : ''}`}
            style={{ color: 'var(--text-primary)' }}>
            {renderText(message.content)}
          </p>
        )}

        {/* Insights */}
        {(message.insights ?? []).length > 0 && (
          <div className="mt-3 p-3 rounded-xl fade-slide-in"
            style={{ backgroundColor: 'rgba(52,168,83,0.07)', border: '1px solid rgba(52,168,83,0.2)' }}>
            <p className="text-xs font-semibold mb-2" style={{ color: '#34a853' }}>Key Insights</p>
            <ul className="space-y-1">
              {message.insights!.map((ins, i) => (
                <li key={i} className="flex gap-2 text-sm" style={{ color: 'var(--text-secondary)' }}>
                  <span style={{ color: '#34a853' }}>•</span>
                  {ins}
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* Charts */}
        {message.charts && Object.keys(message.charts).length > 0 && (
          <ChartPanel charts={message.charts} />
        )}

        {/* Timestamp */}
        <p className="text-xs mt-2" style={{ color: 'var(--text-muted)' }}>
          {new Date(message.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
        </p>
      </div>
    </div>
  );
}
