import { useState, useRef, useEffect } from "react";

const ENDPOINT = "http://localhost:8000/query"; // change to your FastAPI URL

const SUGGESTIONS = [
  "Explain the architecture of this service",
  "What are the main configuration options?",
  "How does error handling work?",
  "Summarize recent changes",
];

function TokenPill({ label, value, color = "slate" }) {
  const colors = {
    sky: "text-sky-400 border-sky-500/30 bg-sky-500/10",
    violet: "text-violet-400 border-violet-500/30 bg-violet-500/10",
    emerald: "text-emerald-400 border-emerald-500/30 bg-emerald-500/10",
    slate: "text-slate-400 border-slate-600 bg-slate-800",
  };
  return (
    <span className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded border text-xs font-mono ${colors[color]}`}>
      <span className="text-slate-500">{label}</span>
      <span className="font-semibold">{value}</span>
    </span>
  );
}

function ReasoningBlock({ text }) {
  const [open, setOpen] = useState(false);
  if (!text) return null;
  return (
    <div className="mt-3 border border-slate-700/60 rounded-lg overflow-hidden">
      <button
        onClick={() => setOpen(v => !v)}
        className="w-full flex items-center justify-between px-3 py-2 text-xs text-slate-500 hover:text-slate-300 hover:bg-slate-800/50 transition-colors"
      >
        <span className="flex items-center gap-2 font-mono">
          <span className="text-violet-400">◈</span> reasoning chain
        </span>
        <span className="text-slate-600">{open ? "▴" : "▾"}</span>
      </button>
      {open && (
        <div className="px-4 py-3 text-xs text-slate-400 font-mono leading-relaxed bg-slate-900/50 border-t border-slate-700/60 whitespace-pre-wrap">
          {text}
        </div>
      )}
    </div>
  );
}

function MetaBadges({ metadata }) {
  if (!metadata) return null;
  const { role, model, usage } = metadata;
  return (
    <div className="flex flex-wrap gap-2 mt-4 pt-3 border-t border-slate-800">
      {role && <TokenPill label="role" value={role} color="slate" />}
      {model && <TokenPill label="model" value={model} color="sky" />}
      {usage?.prompt_tokens != null && <TokenPill label="prompt" value={`${usage.prompt_tokens}t`} color="violet" />}
      {usage?.query_tokens != null && <TokenPill label="query" value={`${usage.query_tokens}t`} color="violet" />}
      {usage?.total_tokens != null && <TokenPill label="total" value={`${usage.total_tokens}t`} color="emerald" />}
    </div>
  );
}

function MessageBubble({ entry }) {
  if (entry.type === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[75%] px-4 py-2.5 rounded-2xl rounded-tr-sm bg-sky-600/20 border border-sky-500/25 text-sm text-slate-100 leading-relaxed">
          {entry.text}
        </div>
      </div>
    );
  }

  if (entry.type === "error") {
    return (
      <div className="flex justify-start">
        <div className="max-w-[85%] px-4 py-3 rounded-2xl rounded-tl-sm bg-red-500/10 border border-red-500/25 text-sm text-red-300 font-mono">
          ✗ {entry.text}
        </div>
      </div>
    );
  }

  // type === "answer"
  const { answer } = entry;
  const msg = answer?.message;
  const meta = answer?.metadata;

  return (
    <div className="flex justify-start">
      <div className="max-w-[85%] space-y-1">
        {/* Avatar */}
        <div className="flex items-center gap-2 mb-2">
          <span className="w-5 h-5 rounded-full bg-gradient-to-br from-sky-500 to-violet-600 flex items-center justify-center text-[10px] font-bold text-white">R</span>
          <span className="text-xs text-slate-500 font-mono">rag</span>
        </div>

        <div className="px-4 py-3 rounded-2xl rounded-tl-sm bg-slate-800/70 border border-slate-700/50">
          {/* Response */}
          {msg?.response && (
            <p className="text-sm text-slate-100 leading-relaxed whitespace-pre-wrap">{msg.response}</p>
          )}

          {/* Reasoning */}
          <ReasoningBlock text={msg?.reasoning} />

          {/* Meta */}
          <MetaBadges metadata={meta} />
        </div>
      </div>
    </div>
  );
}

function TypingIndicator() {
  return (
    <div className="flex justify-start">
      <div className="px-4 py-3 rounded-2xl rounded-tl-sm bg-slate-800/70 border border-slate-700/50">
        <div className="flex items-center gap-1.5">
          {[0, 1, 2].map(i => (
            <span
              key={i}
              className="w-1.5 h-1.5 rounded-full bg-sky-400"
              style={{ animation: `pulse 1.2s ease-in-out ${i * 0.2}s infinite` }}
            />
          ))}
        </div>
      </div>
    </div>
  );
}

export default function App() {
  const [question, setQuestion] = useState("");
  const [history, setHistory] = useState([]);
  const [loading, setLoading] = useState(false);
  const [endpoint, setEndpoint] = useState(ENDPOINT);
  const [showConfig, setShowConfig] = useState(false);
  const bottomRef = useRef(null);
  const inputRef = useRef(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [history, loading]);

  async function submit(q) {
    const text = (q ?? question).trim();
    if (!text || loading) return;
    setQuestion("");
    setLoading(true);
    setHistory(h => [...h, { type: "user", text }]);

    try {
      const res = await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: text }),
      });

      if (!res.ok) throw new Error(`HTTP ${res.status} — ${res.statusText}`);

      const answer = await res.json();
      setHistory(h => [...h, { type: "answer", answer }]);
    } catch (e) {
      setHistory(h => [...h, { type: "error", text: e.message }]);
    } finally {
      setLoading(false);
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  }

  const empty = history.length === 0;

  return (
    <div
      className="min-h-screen bg-slate-950 text-slate-100 flex flex-col"
      style={{ fontFamily: "'Inter', 'SF Pro Text', system-ui, sans-serif" }}
    >
      {/* Header */}
      <header className="sticky top-0 z-10 flex items-center justify-between px-5 py-3 border-b border-slate-800/80 bg-slate-950/90 backdrop-blur">
        <div className="flex items-center gap-3">
          <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-sky-500 to-violet-600 flex items-center justify-center">
            <span className="text-xs font-black text-white">R</span>
          </div>
          <span className="text-sm font-semibold text-slate-100 tracking-tight">RAG Console</span>
          <span className="hidden sm:inline text-xs text-slate-600 font-mono border border-slate-800 px-2 py-0.5 rounded">
            {endpoint.split("//")[1]?.split("/")[0]}
          </span>
        </div>
        <button
          onClick={() => setShowConfig(v => !v)}
          className="text-xs text-slate-500 hover:text-slate-300 font-mono px-3 py-1.5 rounded border border-slate-800 hover:border-slate-600 transition-colors"
        >
          config
        </button>
      </header>

      {/* Config panel */}
      {showConfig && (
        <div className="px-5 py-3 border-b border-slate-800 bg-slate-900/60">
          <label className="block text-xs text-slate-500 font-mono mb-1.5">endpoint URL</label>
          <input
            className="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-xs font-mono text-sky-300 focus:outline-none focus:border-sky-500/60"
            value={endpoint}
            onChange={e => setEndpoint(e.target.value)}
            placeholder="http://localhost:8000/query"
            spellCheck={false}
          />
        </div>
      )}

      {/* Body */}
      <div className="flex-1 overflow-y-auto px-4 sm:px-6 py-6 max-w-3xl w-full mx-auto">
        {empty ? (
          <div className="flex flex-col items-center justify-center min-h-[60vh] text-center gap-6">
            <div>
              <div className="w-12 h-12 rounded-2xl bg-gradient-to-br from-sky-500/20 to-violet-600/20 border border-sky-500/20 flex items-center justify-center mx-auto mb-4">
                <span className="text-2xl">⬡</span>
              </div>
              <h1 className="text-lg font-semibold text-slate-200 mb-1">Ask your knowledge base</h1>
              <p className="text-sm text-slate-500">Connected to your FastAPI RAG endpoint</p>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 w-full max-w-lg">
              {SUGGESTIONS.map((s, i) => (
                <button
                  key={i}
                  onClick={() => submit(s)}
                  className="text-left px-3 py-2.5 rounded-xl border border-slate-800 bg-slate-900/40 hover:bg-slate-800/60 hover:border-slate-700 transition-all text-xs text-slate-400 hover:text-slate-200"
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <div className="space-y-5">
            {history.map((entry, i) => (
              <MessageBubble key={i} entry={entry} />
            ))}
            {loading && <TypingIndicator />}
            <div ref={bottomRef} />
          </div>
        )}
      </div>

      {/* Input bar */}
      <div className="sticky bottom-0 border-t border-slate-800/80 bg-slate-950/95 backdrop-blur px-4 sm:px-6 py-4">
        <div className="max-w-3xl mx-auto">
          <div className="flex items-end gap-3 bg-slate-900 border border-slate-700/70 rounded-2xl px-4 py-3 focus-within:border-sky-500/40 transition-colors">
            <textarea
              ref={inputRef}
              rows={1}
              className="flex-1 bg-transparent text-sm text-slate-100 placeholder-slate-600 resize-none focus:outline-none leading-relaxed"
              placeholder="Ask anything…"
              value={question}
              onChange={e => {
                setQuestion(e.target.value);
                e.target.style.height = "auto";
                e.target.style.height = Math.min(e.target.scrollHeight, 120) + "px";
              }}
              onKeyDown={e => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  submit();
                }
              }}
              disabled={loading}
            />
            <button
              onClick={() => submit()}
              disabled={!question.trim() || loading}
              className="shrink-0 w-8 h-8 rounded-xl bg-sky-600 hover:bg-sky-500 disabled:bg-slate-800 disabled:text-slate-600 text-white flex items-center justify-center transition-colors"
            >
              {loading ? (
                <span className="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
              ) : (
                <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M6 12L3.269 3.126A59.768 59.768 0 0121.485 12 59.77 59.77 0 013.27 20.876L5.999 12zm0 0h7.5" />
                </svg>
              )}
            </button>
          </div>
          <p className="text-center text-xs text-slate-700 mt-2 font-mono">enter ↵ to send · shift+enter for newline</p>
        </div>
      </div>

      <style>{`
        @keyframes pulse {
          0%, 100% { opacity: 0.3; transform: scale(0.8); }
          50% { opacity: 1; transform: scale(1.1); }
        }
      `}</style>
    </div>
  );
}
