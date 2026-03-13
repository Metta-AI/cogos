"use client";

import { useState, useMemo, useCallback, useEffect, useRef } from "react";
import type { CSSProperties } from "react";

const FILE_REFERENCE_TRIGGER = "@{";

function extractReferencedFiles(content: string, excludeKey?: string) {
  const seen = new Set<string>();
  const refs: string[] = [];
  for (const match of content.matchAll(/@\{([^}\r\n]+)\}/g)) {
    const key = match[1]?.trim();
    if (!key || key === excludeKey || seen.has(key)) continue;
    seen.add(key);
    refs.push(key);
  }
  return refs;
}

function getActiveReference(
  value: string,
  caret: number,
): { start: number; end: number; query: string } | null {
  const triggerStart = value.lastIndexOf(FILE_REFERENCE_TRIGGER, caret);
  if (triggerStart === -1) return null;

  const between = value.slice(triggerStart + FILE_REFERENCE_TRIGGER.length, caret);
  if (!between && value.slice(triggerStart, caret) !== FILE_REFERENCE_TRIGGER) {
    return null;
  }
  if (between.includes("}") || /\s/.test(between)) return null;

  const closingIndex = value.indexOf("}", triggerStart + FILE_REFERENCE_TRIGGER.length);
  if (closingIndex !== -1 && closingIndex < caret) return null;

  return {
    start: triggerStart,
    end: closingIndex === -1 ? caret : closingIndex + 1,
    query: between,
  };
}

interface FileReferenceTextareaProps {
  value: string;
  onChange: (value: string) => void;
  suggestions: string[];
  currentKey?: string;
  placeholder?: string;
  rows?: number;
  className?: string;
  style?: CSSProperties;
  helperText?: string;
  showReferences?: boolean;
}

export function FileReferenceTextarea({
  value,
  onChange,
  suggestions,
  currentKey,
  placeholder,
  rows = 4,
  className = "w-full px-2 py-1.5 text-[12px] rounded border resize-y",
  style,
  helperText = "Type @{ to reference another file.",
  showReferences = true,
}: FileReferenceTextareaProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const [activeReference, setActiveReference] = useState<{ start: number; end: number; query: string } | null>(null);
  const [highlightedIndex, setHighlightedIndex] = useState(0);

  const referencedFiles = useMemo(
    () => extractReferencedFiles(value, currentKey),
    [value, currentKey],
  );

  const filteredSuggestions = useMemo(() => {
    if (!activeReference) return [];
    const query = activeReference.query.trim().toLowerCase();
    return suggestions
      .filter((key) => key !== currentKey)
      .filter((key) => !query || key.toLowerCase().includes(query))
      .slice(0, 8);
  }, [activeReference, currentKey, suggestions]);

  const refreshActiveReference = useCallback(() => {
    const textarea = textareaRef.current;
    if (!textarea || textarea.selectionStart !== textarea.selectionEnd) {
      setActiveReference(null);
      return;
    }
    setActiveReference(getActiveReference(textarea.value, textarea.selectionStart));
  }, []);

  const applySuggestion = useCallback((suggestion: string) => {
    const textarea = textareaRef.current;
    if (!textarea) return;

    const currentValue = textarea.value;
    const nextActive = getActiveReference(currentValue, textarea.selectionStart);
    if (!nextActive) return;

    const nextValue = `${currentValue.slice(0, nextActive.start)}@{${suggestion}}${currentValue.slice(nextActive.end)}`;
    const nextCaret = nextActive.start + suggestion.length + 3;
    onChange(nextValue);

    requestAnimationFrame(() => {
      const nextTextarea = textareaRef.current;
      if (!nextTextarea) return;
      nextTextarea.focus();
      nextTextarea.setSelectionRange(nextCaret, nextCaret);
      setActiveReference(getActiveReference(nextValue, nextCaret));
    });
  }, [onChange]);

  useEffect(() => {
    setHighlightedIndex(0);
  }, [filteredSuggestions]);

  return (
    <div className="relative">
      <textarea
        ref={textareaRef}
        value={value}
        onChange={(e) => {
          onChange(e.target.value);
          requestAnimationFrame(refreshActiveReference);
        }}
        onClick={refreshActiveReference}
        onFocus={refreshActiveReference}
        onKeyUp={refreshActiveReference}
        onSelect={refreshActiveReference}
        onBlur={() => {
          setTimeout(() => setActiveReference(null), 0);
        }}
        onKeyDown={(e) => {
          if (!activeReference || filteredSuggestions.length === 0) return;

          if (e.key === "ArrowDown") {
            e.preventDefault();
            setHighlightedIndex((idx) => (idx + 1) % filteredSuggestions.length);
            return;
          }
          if (e.key === "ArrowUp") {
            e.preventDefault();
            setHighlightedIndex((idx) => (idx - 1 + filteredSuggestions.length) % filteredSuggestions.length);
            return;
          }
          if (e.key === "Enter" || e.key === "Tab") {
            e.preventDefault();
            applySuggestion(filteredSuggestions[highlightedIndex] ?? filteredSuggestions[0]);
            return;
          }
          if (e.key === "Escape") {
            setActiveReference(null);
          }
        }}
        placeholder={placeholder}
        rows={rows}
        className={className}
        style={style}
      />
      {activeReference && filteredSuggestions.length > 0 && (
        <div
          className="absolute left-0 right-0 mt-1 rounded-md overflow-hidden z-30"
          style={{
            background: "var(--bg-elevated)",
            border: "1px solid var(--border)",
            boxShadow: "0 10px 30px rgba(0,0,0,0.18)",
            maxHeight: "180px",
            overflowY: "auto",
          }}
        >
          {filteredSuggestions.map((suggestion, index) => (
            <button
              key={suggestion}
              type="button"
              onMouseDown={(e) => {
                e.preventDefault();
                applySuggestion(suggestion);
              }}
              className="w-full text-left px-2 py-1.5 border-0 font-mono text-[11px] cursor-pointer"
              style={{
                background: index === highlightedIndex ? "var(--bg-hover)" : "transparent",
                color: index === highlightedIndex ? "var(--accent)" : "var(--text-secondary)",
              }}
            >
              {suggestion}
            </button>
          ))}
        </div>
      )}
      {(helperText || (showReferences && referencedFiles.length > 0)) && (
        <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[9px] text-[var(--text-muted)]">
          {helperText && <span>{helperText}</span>}
          {showReferences && referencedFiles.length > 0 && (
            <span className="font-mono">
              refs: {referencedFiles.join(", ")}
            </span>
          )}
        </div>
      )}
    </div>
  );
}
