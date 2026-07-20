'use client';

import { useEffect, useRef, useState } from 'react';
import { Brain, FileText, Send, ShieldCheck, Sparkles, Trash2 } from 'lucide-react';
import Markdown from 'react-markdown';
import type { ChatMessage, GraphNode, QueryResponse } from '../types';
import { API_BASE } from '../types';

interface ChatPanelProps {
  presetQuery?: string;
  contextNodes?: GraphNode[];
}

const suggestions = [
  'What themes have I been returning to lately?',
  'Connect ideas across my coding and school notes.',
  '💡 Brainstorm project ideas from my past chats',
  'Summarize how my Second Brain is organized.',
];

function readErrorMessage(status: number, detail?: string) {
  if (status === 503) return 'The embedding model is still loading. Wait a moment, then try again.';
  if (status >= 500) return 'Qwen could not answer. Make sure Ollama is running and the model is available.';
  return detail || 'The request could not be completed.';
}

export default function ChatPanel({ presetQuery, contextNodes = [] }: ChatPanelProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [scope, setScope] = useState<'notes' | 'chats' | 'all'>('notes');
  const [isLoading, setIsLoading] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const frame = window.requestAnimationFrame(() => {
      const saved = window.localStorage.getItem('second_brain_chat_history');
      if (!saved) return;
      try {
        setMessages(JSON.parse(saved));
      } catch {
        window.localStorage.removeItem('second_brain_chat_history');
      }
    });
    return () => window.cancelAnimationFrame(frame);
  }, []);

  useEffect(() => {
    if (messages.length > 0) {
      window.localStorage.setItem('second_brain_chat_history', JSON.stringify(messages));
    } else {
      window.localStorage.removeItem('second_brain_chat_history');
    }
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }, [messages]);

  useEffect(() => {
    if (!presetQuery?.trim()) return;
    const frame = window.requestAnimationFrame(() => {
      setInput(presetQuery);
      textareaRef.current?.focus();
    });
    return () => window.cancelAnimationFrame(frame);
  }, [presetQuery]);

  useEffect(() => {
    const textarea = textareaRef.current;
    if (!textarea) return;
    textarea.style.height = 'auto';
    textarea.style.height = `${Math.min(textarea.scrollHeight, 144)}px`;
  }, [input]);

  const sendMessage = async () => {
    const query = input.trim();
    if (!query || isLoading) return;

    const userMessage: ChatMessage = {
      id: crypto.randomUUID(),
      role: 'user',
      content: query,
      timestamp: new Date(),
    };

    setMessages((current) => [...current, userMessage]);
    setInput('');
    setIsLoading(true);

    try {
      const response = await fetch(`${API_BASE}/api/query`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          query,
          context_nodes: contextNodes.length > 0 ? contextNodes.map((node) => node.id) : undefined,
          scope,
        }),
      });

      if (!response.ok) {
        const error = await response.json().catch(() => null);
        throw new Error(readErrorMessage(response.status, error?.detail));
      }

      const result: QueryResponse = await response.json();
      setMessages((current) => [...current, {
        id: crypto.randomUUID(),
        role: 'assistant',
        content: result.answer,
        sources: result.sources,
        timestamp: new Date(),
      }]);
    } catch (error) {
      setMessages((current) => [...current, {
        id: crypto.randomUUID(),
        role: 'assistant',
        content: `**I couldn't complete that request.**\n\n${error instanceof Error ? error.message : 'Check the local backend and try again.'}`,
        timestamp: new Date(),
      }]);
    } finally {
      setIsLoading(false);
    }
  };

  const handleSuggestionClick = (suggestion: string) => {
    if (suggestion.includes('past chats') || suggestion.includes('project ideas')) {
      setScope('chats');
    } else {
      setScope('notes');
    }
    setInput(suggestion);
    textareaRef.current?.focus();
  };

  const clearHistory = () => {
    setMessages([]);
    window.localStorage.removeItem('second_brain_chat_history');
    textareaRef.current?.focus();
  };

  return (
    <section className="chat-container" aria-label="Qwen chat">
      <header className="chat-toolbar">
        <div className="chat-toolbar-status">
          <span className="assistant-avatar"><Brain size={16} /></span>
          <div><strong>Qwen copilot</strong><span><ShieldCheck size={11} /> Runs locally with your notes</span></div>
        </div>
        
        <div className="chat-scope-selector" style={{ marginRight: '10px' }}>
          <button
            type="button"
            className={`scope-button ${scope === 'notes' ? 'active' : ''}`}
            onClick={() => setScope('notes')}
            title="Search knowledge notes only"
          >
            Notes
          </button>
          <button
            type="button"
            className={`scope-button ${scope === 'chats' ? 'active' : ''}`}
            onClick={() => setScope('chats')}
            title="Search archived AI chats only"
          >
            Chats
          </button>
          <button
            type="button"
            className={`scope-button ${scope === 'all' ? 'active' : ''}`}
            onClick={() => setScope('all')}
            title="Search notes and chats"
          >
            All
          </button>
        </div>

        {messages.length > 0 && (
          <button type="button" className="icon-button" onClick={clearHistory} aria-label="Clear chat history" title="Clear history">
            <Trash2 size={16} />
          </button>
        )}
      </header>

      <div className="chat-messages" aria-live="polite">
        {messages.length === 0 && (
          <div className="chat-welcome">
            <span className="welcome-mark"><Sparkles size={20} /></span>
            <h2>Ask across everything you know.</h2>
            <p>Qwen retrieves relevant passages from your indexed Obsidian notes, then builds a grounded answer with sources.</p>
            <div className="chat-suggestions">
              {suggestions.map((suggestion) => (
                <button type="button" key={suggestion} onClick={() => handleSuggestionClick(suggestion)}>
                  <span>{suggestion}</span><Send size={13} />
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((message) => (
          <article className={`chat-message ${message.role}`} key={message.id}>
            <div className="message-label">
              <span>{message.role === 'assistant' ? <Brain size={13} /> : 'You'}</span>
              <span>{message.role === 'assistant' ? 'Qwen' : ''}</span>
            </div>
            <div className="message-content">
              {message.role === 'assistant' ? <Markdown>{message.content}</Markdown> : <p>{message.content}</p>}
            </div>
            {message.sources && message.sources.length > 0 && (
              <div className="chat-sources" aria-label="Answer sources">
                <span>Sources</span>
                <div>
                  {message.sources.map((source) => (
                    <a
                      key={`${message.id}-${source.source || source.title}`}
                      href={`obsidian://open?vault=Obsidian%20Vault&file=${encodeURIComponent((source.source || source.title).replace(/\.md$/i, ''))}`}
                      title={source.snippet}
                    >
                      <FileText size={13} /><span>{source.title}</span>
                    </a>
                  ))}
                </div>
              </div>
            )}
          </article>
        ))}

        {isLoading && (
          <div className="chat-thinking" role="status">
            <span className="assistant-avatar"><Brain size={14} /></span>
            <div><i /><i /><i /></div>
            <span>Searching your {scope === 'notes' ? 'notes' : scope === 'chats' ? 'chats' : 'vault'}</span>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      <div className="chat-composer-wrap">
        {contextNodes.length > 0 && <span className="composer-context">Using {contextNodes.length} selected note{contextNodes.length === 1 ? '' : 's'}</span>}
        <div className="chat-composer">
          <textarea
            ref={textareaRef}
            value={input}
            onChange={(event) => setInput(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault();
                void sendMessage();
              }
            }}
            placeholder={`Ask a question about your ${scope === 'notes' ? 'notes' : scope === 'chats' ? 'chats' : 'vault'}…`}
            aria-label="Message Qwen"
            rows={1}
          />
          <button type="button" className="chat-send" onClick={() => void sendMessage()} disabled={!input.trim() || isLoading} aria-label="Send message">
            <Send size={17} />
          </button>
        </div>
        <span className="composer-hint">Enter to send · Shift + Enter for a new line</span>
      </div>
    </section>
  );
}
