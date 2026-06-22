// src/App.tsx
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { v4 as uuidv4 } from 'uuid';

import type { Chat, EChartsOption, Message, ThinkingStep } from './types';
import { runPipeline, uploadCSV } from './api';

import Sidebar from './components/Sidebar';
import UploadZone from './components/UploadZone';
import MessageBubble from './components/MessageBubble';
import ChatInput from './components/ChatInput';

// ── UUID shim (uuid package may not be installed, fallback) ──────────────────
function uid() {
  return Math.random().toString(36).slice(2) + Date.now().toString(36);
}

// ── App ───────────────────────────────────────────────────────────────────────
export default function App() {
  const [chats, setChats] = useState<Chat[]>([]);
  const [activeChatId, setActiveChatId] = useState<string | null>(null);
  const [isUploading, setIsUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [isStreaming, setIsStreaming] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const activeChat = chats.find((c) => c.id === activeChatId) ?? null;

  // Auto-scroll
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [activeChat?.messages]);

  // ── Helpers ────────────────────────────────────────────────────────────────

  const updateChat = useCallback((id: string, updater: (c: Chat) => Chat) => {
    setChats((prev) => prev.map((c) => (c.id === id ? updater(c) : c)));
  }, []);

  const updateMessage = useCallback(
    (chatId: string, msgId: string, updater: (m: Message) => Message) => {
      updateChat(chatId, (chat) => ({
        ...chat,
        messages: chat.messages.map((m) => (m.id === msgId ? updater(m) : m)),
      }));
    },
    [updateChat],
  );

  // ── New Chat ────────────────────────────────────────────────────────────────

  const handleNewChat = () => {
    const id = uid();
    const newChat: Chat = {
      id,
      title: 'New Chat',
      messages: [],
      csvFile: null,
      csvName: null,
      createdAt: Date.now(),
    };
    setChats((prev) => [newChat, ...prev]);
    setActiveChatId(id);
    setUploadError(null);
  };

  // ── CSV Upload ──────────────────────────────────────────────────────────────

  const handleFileSelected = async (file: File) => {
    if (!activeChatId) return;
    setIsUploading(true);
    setUploadError(null);
    try {
      const filePath = await uploadCSV(file);
      updateChat(activeChatId, (c) => ({
        ...c,
        csvFile: file,
        csvName: file.name,
        title: file.name.replace('.csv', ''),
        // Store file path in a hidden field
        messages: [
          ...c.messages,
          {
            id: uid(),
            role: 'assistant',
            content: `✅ **${file.name}** uploaded successfully. You can now ask questions about your data.`,
            timestamp: Date.now(),
            // Stash the path for later use
          } as Message,
        ],
      }));
      // Stash path on the chat object for later
      setChats((prev) =>
        prev.map((c) =>
          c.id === activeChatId
            ? { ...c, csvFile: { ...file, path: filePath } as unknown as File }
            : c,
        ),
      );
    } catch (e: unknown) {
      setUploadError(e instanceof Error ? e.message : 'Upload failed');
    } finally {
      setIsUploading(false);
    }
  };

  // Fallback: if no backend, use local file path
  const getFilePath = (chat: Chat): string => {
    const f = chat.csvFile as unknown as (File & { path?: string });
    return f?.path ?? f?.name ?? '';
  };

  // ── Send Message ────────────────────────────────────────────────────────────

  const handleSend = async (text: string) => {
    if (!activeChat || isStreaming) return;

    const chatId = activeChat.id;
    const filePath = getFilePath(activeChat);

    // Add user message
    const userMsg: Message = { id: uid(), role: 'user', content: text, timestamp: Date.now() };
    // Add blank assistant message
    const assistantId = uid();
    const assistantMsg: Message = {
      id: assistantId,
      role: 'assistant',
      content: '',
      thinking: [],
      isStreaming: true,
      timestamp: Date.now(),
    };

    updateChat(chatId, (c) => {
      const title = c.messages.filter((m) => m.role === 'user').length === 0
        ? text.slice(0, 40)
        : c.title;
      return { ...c, title, messages: [...c.messages, userMsg, assistantMsg] };
    });

    setIsStreaming(true);

    try {
      const generator = runPipeline(text, filePath);

      for await (const chunk of generator) {
        if (chunk.type === 'thinking') {
          updateMessage(chatId, assistantId, (m) => ({
            ...m,
            thinking: [
              ...(m.thinking ?? []).map((s, i) =>
                i < (m.thinking ?? []).length - 1 ? { ...s, done: true } : s,
              ),
              { stage: chunk.stage!, content: chunk.text!, done: false } as ThinkingStep,
            ],
          }));
        } else if (chunk.type === 'content') {
          updateMessage(chatId, assistantId, (m) => ({
            ...m,
            content: chunk.text!,
            // Mark last thinking step as done when content starts
            thinking: (m.thinking ?? []).map((s) => ({ ...s, done: true })),
          }));
        } else if (chunk.type === 'charts') {
          updateMessage(chatId, assistantId, (m) => ({
            ...m,
            charts: chunk.charts as Record<string, EChartsOption>,
          }));
        } else if (chunk.type === 'insights') {
          updateMessage(chatId, assistantId, (m) => ({
            ...m,
            insights: chunk.insights,
          }));
        } else if (chunk.type === 'error') {
          updateMessage(chatId, assistantId, (m) => ({
            ...m,
            content: `⚠️ ${chunk.error}`,
            isStreaming: false,
          }));
        } else if (chunk.type === 'done') {
          updateMessage(chatId, assistantId, (m) => ({ ...m, isStreaming: false }));
        }
      }
    } catch (e) {
      updateMessage(chatId, assistantId, (m) => ({
        ...m,
        content: '⚠️ Something went wrong. Please try again.',
        isStreaming: false,
      }));
    } finally {
      setIsStreaming(false);
    }
  };

  // ── Render ─────────────────────────────────────────────────────────────────

  const showUpload = activeChat && !activeChat.csvName;
  const showChat = activeChat && activeChat.csvName;

  return (
    <div className="flex h-screen overflow-hidden" style={{ backgroundColor: 'var(--bg-primary)' }}>

      {/* Sidebar */}
      <Sidebar
        chats={chats}
        activeChatId={activeChatId}
        onSelectChat={setActiveChatId}
        onNewChat={handleNewChat}
      />

      {/* Main area */}
      <main className="flex flex-col flex-1 min-w-0 h-full">

        {/* Empty state — no chat selected */}
        {!activeChat && (
          <div className="flex flex-col items-center justify-center flex-1 text-center px-6">
            <div className="mb-8 w-20 h-20 rounded-full flex items-center justify-center"
              style={{ background: 'linear-gradient(135deg, rgba(66,133,244,0.15), rgba(161,66,244,0.15))', border: '1px solid rgba(138,180,248,0.2)' }}>
              <svg className="w-10 h-10" fill="none" stroke="currentColor" viewBox="0 0 24 24"
                style={{ color: 'var(--accent)' }}>
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
                  d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
              </svg>
            </div>
            <h2 className="text-2xl font-semibold mb-3"
              style={{ color: 'var(--text-primary)' }}>
              BI Visualization Assistant
            </h2>
            <p className="text-base mb-8 max-w-sm" style={{ color: 'var(--text-secondary)' }}>
              Start a new chat, upload your CSV, and ask questions in plain English.
            </p>
            <button
              onClick={handleNewChat}
              className="flex items-center gap-2 px-6 py-3 rounded-xl font-medium text-sm transition-all duration-200 hover:scale-105 active:scale-100"
              style={{
                background: 'linear-gradient(135deg, #1a3a6b, #2d1b5e)',
                color: 'var(--accent)',
                border: '1px solid rgba(138,180,248,0.3)',
              }}>
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
              </svg>
              New Chat
            </button>
          </div>
        )}

        {/* Upload zone */}
        {showUpload && (
          <UploadZone
            onFileSelected={handleFileSelected}
            isUploading={isUploading}
            uploadError={uploadError}
          />
        )}

        {/* Chat view */}
        {showChat && (
          <>
            {/* Header */}
            <div className="flex items-center justify-between px-6 py-3 border-b shrink-0"
              style={{ borderColor: 'var(--border)', backgroundColor: 'var(--bg-primary)' }}>
              <div className="flex items-center gap-2">
                <span className="text-sm font-medium" style={{ color: 'var(--text-primary)' }}>
                  {activeChat.title}
                </span>
                <span className="text-xs px-2 py-0.5 rounded-full"
                  style={{ backgroundColor: 'rgba(52,168,83,0.12)', color: '#34a853' }}>
                  {activeChat.csvName}
                </span>
              </div>
              {isStreaming && (
                <div className="flex items-center gap-1.5 text-xs" style={{ color: 'var(--text-muted)' }}>
                  <div className="flex gap-1">
                    {[0, 1, 2].map((i) => (
                      <div key={i} className="w-1.5 h-1.5 rounded-full thinking-dot"
                        style={{ backgroundColor: 'var(--accent)', animationDelay: `${i * 0.2}s` }} />
                    ))}
                  </div>
                  Generating…
                </div>
              )}
            </div>

            {/* Messages */}
            <div className="flex-1 overflow-y-auto px-6 py-6 space-y-1" id="messages-container">
              <div className="max-w-3xl mx-auto w-full">
                {activeChat.messages.map((msg) => (
                  <MessageBubble key={msg.id} message={msg} />
                ))}
                <div ref={messagesEndRef} />
              </div>
            </div>

            {/* Input */}
            <div className="max-w-3xl w-full mx-auto px-2">
              <ChatInput
                onSend={handleSend}
                disabled={isStreaming}
                csvName={activeChat.csvName}
                onChangeCSV={() =>
                  updateChat(activeChat.id, (c) => ({
                    ...c,
                    csvFile: null,
                    csvName: null,
                    messages: [],
                  }))
                }
              />
            </div>
          </>
        )}
      </main>
    </div>
  );
}
