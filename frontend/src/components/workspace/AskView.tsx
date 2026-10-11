"use client";

import { useCallback, useRef, useState } from "react";
import { CircleAlert, FileText, MessageSquareText } from "lucide-react";
import { composePrompts } from "@/lib/api";
import { SCOPES } from "@/lib/ask";
import { useWorkspace } from "./context";
import { AnswerBlock, AskComposer } from "./AskParts";
import { AskHistory, type AskHistoryEntry } from "./AskHistory";
import { useAsk } from "./useAsk";

export function AskView() {
  const { selectNote } = useWorkspace();
  const ask = useAsk();
  const { answer, loading, error, run, show, scope } = ask;
  const [historyVersion, setHistoryVersion] = useState(0);
  const [activeHistoryId, setActiveHistoryId] = useState<string | null>(null);
  const [nowMs, setNowMs] = useState(() => Date.now());
  const inputRef = useRef<HTMLInputElement>(null);

  const askNow = useCallback(
    async (override?: Parameters<typeof run>[0]) => {
      setActiveHistoryId(null);
      await run(override);
      setNowMs(Date.now());
      setHistoryVersion((v) => v + 1);
    },
    [run],
  );

  const showSaved = useCallback(
    (entry: AskHistoryEntry) => {
      setActiveHistoryId(entry.id);
      setNowMs(Date.now());
      show(entry);
    },
    [show],
  );

  const askAgain = useCallback(
    (entry: AskHistoryEntry) => {
      ask.setQuery(entry.question);
      ask.setScope(entry.scope);
      void askNow({ query: entry.question, scope: entry.scope });
    },
    [ask, askNow],
  );

  const hint = SCOPES.find((s) => s.id === scope)?.hint;

  return (
    <div className="min-h-0 w-full flex-1 overflow-y-auto">
      <div className="mx-auto flex w-full max-w-3xl flex-col gap-5 px-5 py-6">
        <header>
          <h1 className="m-0 text-[20px] font-semibold tracking-[-0.015em]">Ask</h1>
          <p className="mono mt-1 mb-0 text-muted">Search in: {hint}</p>
        </header>

        <section className="dock" aria-label="Ask the vault">
          {error && (
            <div className="answer" role="alert">
              <p className="dock-head mono">
                <CircleAlert className="icon" aria-hidden strokeWidth={2} style={{ color: "var(--danger)" }} />
                Ask did not finish
              </p>
              <p className="answer-text quiet">{error}</p>
            </div>
          )}
          {!error && answer && (
            <AnswerBlock
              answer={answer}
              heading={loading ? "Answering" : activeHistoryId ? "Saved answer" : "Answer"}
              idPrefix="ask"
              writing={loading}
              nowMs={Math.max(nowMs, (answer.askedAt ?? 0) * 1000)}
              sourceAction={(s) =>
                s.source ? (
                  <button type="button" className="btn" onClick={() => selectNote(s.source, { view: "notes" })}>
                    <FileText className="icon" aria-hidden strokeWidth={2} />
                    Open note
                  </button>
                ) : null
              }
            />
          )}
          {!error && !answer && loading && (
            <div className="answer" aria-busy="true">
              <p className="dock-head mono">
                <MessageSquareText className="icon" aria-hidden strokeWidth={2} />
                Looking through your notes…
              </p>
              <span className="sk" style={{ width: "95%", marginTop: 14 }} />
              <span className="sk" style={{ width: "60%", margin: "8px 0 14px" }} />
            </div>
          )}
          <AskComposer
            inputId="ask-q"
            inputRef={inputRef}
            query={ask.query}
            onQuery={ask.setQuery}
            scope={scope}
            onScope={ask.setScope}
            loading={loading}
            onAsk={() => void askNow()}
            first={!error && !answer && !loading}
          />
        </section>

        <AskHistory
          version={historyVersion}
          activeId={activeHistoryId}
          nowMs={nowMs}
          onSelect={showSaved}
          onRerun={askAgain}
        />

        <div className="dock">
          <div className="cmds" style={{ borderTop: 0 }}>
            <p className="cmds-label mono">Try asking</p>
            <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
              {composePrompts.map((p) => (
                <li key={p}>
                  <button
                    type="button"
                    className="cmd"
                    onClick={() => {
                      ask.setQuery(p);
                      inputRef.current?.focus();
                    }}
                  >
                    <MessageSquareText className="icon" aria-hidden strokeWidth={2} />
                    {p}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        </div>
      </div>
    </div>
  );
}
