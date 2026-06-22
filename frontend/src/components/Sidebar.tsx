// src/components/Sidebar.tsx
import React from 'react';
import type { Chat } from '../types';

interface Props {
  chats: Chat[];
  activeChatId: string | null;
  onSelectChat: (id: string) => void;
  onNewChat: () => void;
}

export default function Sidebar({ chats, activeChatId, onSelectChat, onNewChat }: Props) {
  return (
    <aside className="flex flex-col w-64 shrink-0 h-full border-r"
      style={{ backgroundColor: 'var(--bg-secondary)', borderColor: 'var(--border)' }}>

      {/* Logo */}
      <div className="flex items-center gap-3 px-4 py-5">
        <div className="w-8 h-8 rounded-full flex items-center justify-center"
          style={{ background: 'linear-gradient(135deg, #4285f4, #a142f4)' }}>
          <span className="text-white text-sm font-bold">B</span>
        </div>
        <span className="font-semibold text-base tracking-tight" style={{ color: 'var(--text-primary)' }}>
          BI Assistant
        </span>
      </div>

      {/* New Chat button */}
      <div className="px-3 mb-4">
        <button
          onClick={onNewChat}
          className="flex items-center gap-2 w-full px-4 py-2.5 rounded-xl text-sm font-medium transition-all duration-200 hover:scale-[1.02]"
          style={{
            background: 'linear-gradient(135deg, #1a3a6b, #2d1b5e)',
            color: 'var(--accent)',
            border: '1px solid rgba(138,180,248,0.25)',
          }}>
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
          </svg>
          New Chat
        </button>
      </div>

      {/* Chat history */}
      <div className="flex-1 overflow-y-auto px-2 space-y-0.5">
        {chats.length === 0 && (
          <p className="text-xs px-3 py-2" style={{ color: 'var(--text-muted)' }}>
            No chats yet
          </p>
        )}
        {chats.map((chat) => (
          <button
            key={chat.id}
            onClick={() => onSelectChat(chat.id)}
            className="w-full text-left px-3 py-2.5 rounded-lg text-sm transition-colors duration-150 truncate"
            style={{
              backgroundColor: activeChatId === chat.id ? 'var(--bg-hover)' : 'transparent',
              color: activeChatId === chat.id ? 'var(--text-primary)' : 'var(--text-secondary)',
            }}>
            <div className="flex items-center gap-2">
              {chat.csvName && (
                <span className="text-xs px-1.5 py-0.5 rounded shrink-0"
                  style={{ backgroundColor: 'rgba(138,180,248,0.15)', color: 'var(--accent)' }}>
                  CSV
                </span>
              )}
              <span className="truncate">{chat.title}</span>
            </div>
          </button>
        ))}
      </div>

      {/* Footer */}
      <div className="px-4 py-3 border-t text-xs" style={{ borderColor: 'var(--border)', color: 'var(--text-muted)' }}>
        BI Visualization Tool v0.1
      </div>
    </aside>
  );
}
