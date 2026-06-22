// src/components/UploadZone.tsx
import React, { useCallback, useRef, useState } from 'react';

interface Props {
  onFileSelected: (file: File) => void;
  isUploading: boolean;
  uploadError: string | null;
}

export default function UploadZone({ onFileSelected, isUploading, uploadError }: Props) {
  const [isDragging, setIsDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const handleFile = (file: File) => {
    if (!file.name.endsWith('.csv')) return;
    onFileSelected(file);
  };

  const onDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    const file = e.dataTransfer.files[0];
    if (file) handleFile(file);
  }, []);

  const onDragOver = (e: React.DragEvent) => { e.preventDefault(); setIsDragging(true); };
  const onDragLeave = () => setIsDragging(false);

  return (
    <div className="flex flex-col items-center justify-center flex-1 px-6 select-none">

      {/* Greeting */}
      <div className="mb-10 text-center">
        <h1 className="text-4xl font-semibold mb-3"
          style={{ background: 'linear-gradient(135deg, #8ab4f8, #c084fc)', WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent' }}>
          Hello, Analyst
        </h1>
        <p className="text-lg" style={{ color: 'var(--text-secondary)' }}>
          Upload a CSV to start exploring your data
        </p>
      </div>

      {/* Drop zone */}
      <div
        onDrop={onDrop}
        onDragOver={onDragOver}
        onDragLeave={onDragLeave}
        onClick={() => inputRef.current?.click()}
        className={`relative flex flex-col items-center justify-center w-full max-w-lg rounded-2xl border-2 border-dashed cursor-pointer transition-all duration-200 p-12
          ${isDragging ? 'drop-zone-active scale-[1.02]' : ''}`}
        style={{
          borderColor: isDragging ? 'var(--accent)' : 'var(--border)',
          backgroundColor: isDragging ? 'var(--accent-glow)' : 'var(--bg-surface)',
        }}>

        <input
          ref={inputRef}
          type="file"
          accept=".csv"
          className="hidden"
          onChange={(e) => { const f = e.target.files?.[0]; if (f) handleFile(f); }}
        />

        {isUploading ? (
          <>
            <div className="flex gap-2 mb-4">
              {[0, 1, 2].map((i) => (
                <div key={i} className="w-2.5 h-2.5 rounded-full thinking-dot"
                  style={{ backgroundColor: 'var(--accent)', animationDelay: `${i * 0.2}s` }} />
              ))}
            </div>
            <p style={{ color: 'var(--text-secondary)' }}>Uploading…</p>
          </>
        ) : (
          <>
            <div className="mb-5 p-4 rounded-full" style={{ backgroundColor: 'rgba(138,180,248,0.1)' }}>
              <svg className="w-10 h-10" fill="none" stroke="currentColor" viewBox="0 0 24 24"
                style={{ color: 'var(--accent)' }}>
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
                  d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
              </svg>
            </div>
            <p className="text-base font-medium mb-1" style={{ color: 'var(--text-primary)' }}>
              Drop your CSV here
            </p>
            <p className="text-sm" style={{ color: 'var(--text-muted)' }}>
              or click to browse — CSV files only
            </p>
          </>
        )}
      </div>

      {/* Error */}
      {uploadError && (
        <p className="mt-4 text-sm px-4 py-2 rounded-lg fade-slide-in"
          style={{ backgroundColor: 'rgba(234,67,53,0.1)', color: '#ea4335', border: '1px solid rgba(234,67,53,0.3)' }}>
          ⚠️ {uploadError}
        </p>
      )}

      {/* Feature chips */}
      <div className="flex flex-wrap gap-2 mt-10 justify-center max-w-md">
        {['📊 EDA & Distributions', '📈 Smart Charts', '🧠 AI Insights', '🔬 ML Predictions'].map((f) => (
          <span key={f} className="text-xs px-3 py-1.5 rounded-full"
            style={{ backgroundColor: 'var(--bg-surface)', color: 'var(--text-secondary)', border: '1px solid var(--border)' }}>
            {f}
          </span>
        ))}
      </div>
    </div>
  );
}
