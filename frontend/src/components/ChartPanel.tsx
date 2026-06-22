// src/components/ChartPanel.tsx
// Renders ECharts options returned from the backend.
import React, { useState } from 'react';
import ReactECharts from 'echarts-for-react';
import type { EChartsOption } from '../types';

interface Props {
  charts: Record<string, EChartsOption>;
}

export default function ChartPanel({ charts }: Props) {
  const entries = Object.entries(charts);
  const [activeIdx, setActiveIdx] = useState(0);

  if (entries.length === 0) return null;

  const darkTheme: Partial<EChartsOption> = {
    backgroundColor: 'transparent',
    textStyle: { color: '#9aa0a6' },
  };

  return (
    <div className="mt-3 rounded-2xl overflow-hidden fade-slide-in"
      style={{ backgroundColor: 'var(--bg-surface)', border: '1px solid var(--border)' }}>

      {/* Tab bar (if multiple charts) */}
      {entries.length > 1 && (
        <div className="flex gap-1 px-4 pt-3 border-b" style={{ borderColor: 'var(--border)' }}>
          {entries.map(([name], i) => (
            <button
              key={name}
              onClick={() => setActiveIdx(i)}
              className="px-3 py-1.5 text-xs rounded-t-lg capitalize transition-colors"
              style={{
                backgroundColor: activeIdx === i ? 'var(--bg-hover)' : 'transparent',
                color: activeIdx === i ? 'var(--text-primary)' : 'var(--text-muted)',
                borderBottom: activeIdx === i ? `2px solid var(--accent)` : '2px solid transparent',
              }}>
              {name.replace(/_/g, ' ')}
            </button>
          ))}
        </div>
      )}

      {/* Chart */}
      <div className="p-4 echarts-wrapper">
        <ReactECharts
          option={{ ...darkTheme, ...entries[activeIdx][1] } as Record<string, unknown>}
          style={{ height: 320, width: '100%' }}
          theme="dark"
          opts={{ renderer: 'canvas' }}
        />
      </div>
    </div>
  );
}
