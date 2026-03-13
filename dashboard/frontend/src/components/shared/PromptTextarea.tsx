"use client";

import { useMemo, useRef, useState } from "react";
import type { CSSProperties, KeyboardEvent } from "react";

interface ActiveInclude {
  start: number;
  end: number;
  query: string;
}

interface PromptTextareaProps {
  value: string;
  onChange: (value: string) => void;
  suggestions: string[];
  rows?: number;
  placeholder?: string;
  className?: string;
  style?: CSSProperties;
}

function getActiveInclude(value: string, caret: number): ActiveInclude | null {
  const beforeCaret = value.slice(0, caret);
  const start = beforeCaret.lastIndexOf("@{");
  if (start === -1) return null;

  const query = beforeCaret.slice(start + 2);
  if (query.includes("}") || query.includes("\n")) return null;
  return { start, end: caret, query };
}

export function PromptTextarea({
  value,
  onChange,
  suggestions,
  rows = 5,
  placeholder,
  className,
  style,
}: PromptTextareaProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const [activeInclude, setActiveInclude] = useState<ActiveInclude | null>(null);
  const [selectedIndex, setSelectedIndex] = useState(0);

  const filteredSuggestions = useMemo(() => {
    if (!activeInclude) return [];
    const query = activeInclude.query.trim().toLowerCase();
    const items = suggestions.filter((suggestion) => {
      if (!query) return true;
      return suggestion.toLowerCase().includes(query);
    });
    items.sort((a, b) => {
      const aStarts = query ? a.toLowerCase().startsWith(query) : false;
      const bStarts = query ? b.toLowerCase().startsWith(query) : false;
      if (aStarts !== bStarts) return aStarts ? -1 : 1;
      return a.localeCompare(b);
    });
    return items.slice(0, 8);
  }, [activeInclude, suggestions]);

  const updateIncludeState = (nextValue: string, caret: number | null) => {
    const nextInclude = caret == null ? null : getActiveInclude(nextValue, caret);
    setActiveInclude(nextInclude);
    setSelectedIndex(0);
  };

  const insertSuggestion = (suggestion: string) => {
    if (!activeInclude) return;
    const nextValue =
      `${value.slice(0, activeInclude.start)}@{${suggestion}}${value.slice(activeInclude.end)}`;
    const nextCaret = activeInclude.start + suggestion.length + 3;
    onChange(nextValue);
    setActiveInclude(null);
    setSelectedIndex(0);
    requestAnimationFrame(() => {
      textareaRef.current?.focus();
      textareaRef.current?.setSelectionRange(nextCaret, nextCaret);
    });
  };

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (!activeInclude || filteredSuggestions.length === 0) return;
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setSelectedIndex((current) => (current + 1) % filteredSuggestions.length);
      return;
    }
    if (event.key === "ArrowUp") {
      event.preventDefault();
      setSelectedIndex((current) => (current - 1 + filteredSuggestions.length) % filteredSuggestions.length);
      return;
    }
    if (event.key === "Enter" || event.key === "Tab") {
      event.preventDefault();
      insertSuggestion(filteredSuggestions[selectedIndex] ?? filteredSuggestions[0]);
      return;
    }
    if (event.key === "Escape") {
      event.preventDefault();
      setActiveInclude(null);
    }
  };

  return (
    <div className="relative">
      <textarea
        ref={textareaRef}
        value={value}
        rows={rows}
        placeholder={placeholder}
        className={className}
        style={style}
        onChange={(event) => {
          const nextValue = event.target.value;
          onChange(nextValue);
          updateIncludeState(nextValue, event.target.selectionStart);
        }}
        onKeyDown={onKeyDown}
        onSelect={(event) => updateIncludeState(value, event.currentTarget.selectionStart)}
        onClick={(event) => updateIncludeState(value, event.currentTarget.selectionStart)}
        onBlur={() => setActiveInclude(null)}
      />
      {activeInclude && filteredSuggestions.length > 0 && (
        <div
          className="absolute left-0 right-0 mt-1 z-50 rounded overflow-hidden shadow-lg"
          style={{ background: "var(--bg-elevated)", border: "1px solid var(--border)" }}
        >
          {filteredSuggestions.map((suggestion, index) => {
            const isSelected = index === selectedIndex;
            return (
              <button
                key={suggestion}
                type="button"
                className="w-full text-left px-2 py-1 text-[11px] font-mono border-0 cursor-pointer"
                style={{
                  background: isSelected ? "var(--bg-hover)" : "transparent",
                  color: isSelected ? "var(--accent)" : "var(--text-secondary)",
                }}
                onMouseDown={(event) => {
                  event.preventDefault();
                  insertSuggestion(suggestion);
                }}
              >
                {`@{${suggestion}}`}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
