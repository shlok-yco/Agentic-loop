// src/components/ChatInput.tsx
import React, { useRef, useEffect, useState } from 'react';

interface Props {
  onSend: (text: string) => void;
  disabled: boolean;
  csvName: string | null;
  onChangeCSV: () => void;
  placeholder?: string;
}

export default function ChatInput({ onSend, disabled, csvName, onChangeCSV, placeholder }: Props) {
  const [text, setText] = useState('');
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Auto-resize textarea
  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = Math.min(el.scrollHeight, 160) + 'px';
  }, [text]);

  const submit = () => {
    const trimmed = text.trim();
    if (!trimmed || disabled) return;
    onSend(trimmed);
    setText('');
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  };

  return (
    <div className="shrink-0 px-4 pb-4 pt-2"
      style={{ backgroundColor: 'var(--bg-primary)' }}>

      {/* CSV badge */}
      {csvName && (
        <div className="flex items-center gap-2 mb-2 px-1">
          <span className="flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-full"
            style={{ backgroundColor: 'rgba(138,180,248,0.12)', color: 'var(--accent)', border: '1px solid rgba(138,180,248,0.2)' }}>
            <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
            </svg>
            {csvName}
          </span>
          <button
            onClick={onChangeCSV}
            className="text-xs transition-colors"
            style={{ color: 'var(--text-muted)' }}
            title="Change CSV">
            Change
          </button>
        </div>
      )}

      {/* Input box */}
      <div className="flex items-end gap-3 rounded-2xl px-4 py-3 transition-all"
        style={{
          backgroundColor: 'var(--bg-surface)',
          border: '1px solid var(--border)',
          boxShadow: '0 0 0 0 transparent',
        }}
        onFocusCapture={(e) => {
          (e.currentTarget as HTMLDivElement).style.borderColor = 'rgba(138,180,248,0.5)';
          (e.currentTarget as HTMLDivElement).style.boxShadow = '0 0 0 3px rgba(138,180,248,0.08)';
        }}
        onBlurCapture={(e) => {
          (e.currentTarget as HTMLDivElement).style.borderColor = 'var(--border)';
          (e.currentTarget as HTMLDivElement).style.boxShadow = 'none';
        }}>

        <textarea
          ref={textareaRef}
          rows={1}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={onKeyDown}
          disabled={disabled}
          placeholder={placeholder ?? 'Ask anything about your data…'}
          className="flex-1 resize-none bg-transparent text-sm outline-none leading-6 min-h-[24px]"
          style={{
            color: 'var(--text-primary)',
            caretColor: 'var(--accent)',
          }}
        />

        {/* Send button */}
        <button
          onClick={submit}
          disabled={!text.trim() || disabled}
          className="flex items-center justify-center w-8 h-8 rounded-full transition-all duration-200 shrink-0 mb-0.5"
          style={{
            backgroundColor: !text.trim() || disabled ? 'var(--bg-hover)' : 'var(--accent)',
            color: !text.trim() || disabled ? 'var(--text-muted)' : '#0f0f10',
            cursor: !text.trim() || disabled ? 'not-allowed' : 'pointer',
          }}>
          {disabled ? (
            <div className="w-3.5 h-3.5 rounded-full border-2 border-current border-t-transparent animate-spin" />
          ) : (
            <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 24 24">
              <path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z" />
            </svg>
          )}
        </button>
      </div>

      <p className="text-center text-xs mt-2" style={{ color: 'var(--text-muted)' }}>
        BI Assistant can make mistakes. Verify important results.
      </p>
    </div>
  );
}
