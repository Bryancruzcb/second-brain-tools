'use client';

import type { RefObject } from 'react';
import { ArrowUpRight, Loader2, Search, Sparkles } from 'lucide-react';
import type { SearchResult } from '../types';

interface CommandSearchProps {
  inputRef: RefObject<HTMLInputElement | null>;
  query: string;
  results: SearchResult[];
  isSearching: boolean;
  isOpen: boolean;
  onQueryChange: (query: string) => void;
  onFocus: () => void;
  onBlur: () => void;
  onAsk: (query: string) => void;
  onSelect: (result: SearchResult) => void;
}

export default function CommandSearch({
  inputRef,
  query,
  results,
  isSearching,
  isOpen,
  onQueryChange,
  onFocus,
  onBlur,
  onAsk,
  onSelect,
}: CommandSearchProps) {
  const showMenu = isOpen && query.trim().length > 0;

  return (
    <div className="command-search">
      <div className="command-search-field">
        {isSearching ? <Loader2 className="spin" size={17} /> : <Search size={17} />}
        <input
          ref={inputRef}
          type="search"
          role="combobox"
          aria-autocomplete="list"
          value={query}
          onChange={(event) => onQueryChange(event.target.value)}
          onFocus={onFocus}
          onBlur={onBlur}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && query.trim()) onAsk(query.trim());
          }}
          placeholder="Find a note or ask your brain…"
          aria-label="Search your vault"
          aria-expanded={showMenu}
          aria-controls="command-search-results"
        />
        <kbd>⌘ K</kbd>
      </div>

      {showMenu && (
        <div className="command-search-menu" id="command-search-results" role="listbox">
          {results.map((result) => (
            <button
              type="button"
              className="command-result"
              key={result.id}
              onMouseDown={(event) => event.preventDefault()}
              onClick={() => onSelect(result)}
              role="option"
              aria-selected="false"
            >
              <span className="command-result-icon"><ArrowUpRight size={15} /></span>
              <span className="command-result-copy">
                <strong>{result.title}</strong>
                <small>{result.snippet || 'Open this note in the graph workspace'}</small>
              </span>
            </button>
          ))}

          {!isSearching && results.length === 0 && (
            <div className="command-empty">No matching note titles found.</div>
          )}

          <button
            type="button"
            className="command-ask"
            onMouseDown={(event) => event.preventDefault()}
            onClick={() => onAsk(query.trim())}
          >
            <Sparkles size={15} />
            Ask Qwen “{query.trim()}”
          </button>
        </div>
      )}
    </div>
  );
}
