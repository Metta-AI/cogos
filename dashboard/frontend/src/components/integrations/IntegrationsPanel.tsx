"use client";

import { useState, useEffect, useCallback } from "react";
import {
  getIntegrations,
  updateIntegration,
  deleteIntegration,
  type IntegrationInfo,
  type IntegrationField,
} from "@/lib/api";

interface IntegrationsPanelProps {
  cogentName: string;
}

export function IntegrationsPanel({ cogentName }: IntegrationsPanelProps) {
  const [integrations, setIntegrations] = useState<IntegrationInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await getIntegrations(cogentName);
      setIntegrations(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load integrations");
    } finally {
      setLoading(false);
    }
  }, [cogentName]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  if (loading && integrations.length === 0) {
    return <div style={{ color: "var(--text-muted)", padding: "2rem" }}>Loading integrations...</div>;
  }

  if (error) {
    return <div style={{ color: "var(--error)", padding: "2rem" }}>{error}</div>;
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "1.5rem" }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <h2 style={{ fontSize: "1.25rem", fontWeight: 600, color: "var(--text-primary)", margin: 0 }}>
          Integrations
        </h2>
        <button
          onClick={fetchData}
          disabled={loading}
          style={{
            padding: "6px 14px",
            borderRadius: 6,
            border: "1px solid var(--border)",
            background: "var(--bg-surface)",
            color: "var(--text-secondary)",
            cursor: "pointer",
            fontSize: "0.8rem",
          }}
        >
          {loading ? "Refreshing..." : "Refresh"}
        </button>
      </div>

      {integrations.map((integration) => (
        <IntegrationSection
          key={integration.name}
          integration={integration}
          cogentName={cogentName}
          onUpdate={fetchData}
        />
      ))}
    </div>
  );
}

// ── Per-integration section ──────────────────────────────────────────────────

function IntegrationSection({
  integration,
  cogentName,
  onUpdate,
}: {
  integration: IntegrationInfo;
  cogentName: string;
  onUpdate: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [formValues, setFormValues] = useState<Record<string, string>>({});
  const [saveError, setSaveError] = useState<string | null>(null);

  const startEditing = () => {
    // Pre-fill form with current config (masked values will show as placeholders)
    const values: Record<string, string> = {};
    for (const field of integration.fields) {
      values[field.name] = "";
    }
    setFormValues(values);
    setSaveError(null);
    setEditing(true);
  };

  const handleSave = async () => {
    setSaving(true);
    setSaveError(null);
    try {
      // Only send non-empty fields
      const config: Record<string, string> = {};
      for (const [k, v] of Object.entries(formValues)) {
        if (v.trim()) config[k] = v.trim();
      }
      if (Object.keys(config).length === 0) {
        setSaveError("At least one field must be provided.");
        setSaving(false);
        return;
      }
      await updateIntegration(cogentName, integration.name, config);
      setEditing(false);
      onUpdate();
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : "Failed to save");
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    if (!confirm(`Remove ${integration.display_name} configuration? This will delete all stored secrets.`)) return;
    setDeleting(true);
    try {
      await deleteIntegration(cogentName, integration.name);
      onUpdate();
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : "Failed to delete");
    } finally {
      setDeleting(false);
    }
  };

  const isConfigured = integration.status.configured;

  return (
    <div
      style={{
        border: "1px solid var(--border)",
        borderRadius: 8,
        background: "var(--bg-surface)",
        overflow: "hidden",
      }}
    >
      {/* Header */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "14px 18px",
          borderBottom: editing ? "1px solid var(--border)" : "none",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <IntegrationIcon name={integration.name} />
          <div>
            <div style={{ fontWeight: 600, color: "var(--text-primary)", fontSize: "0.95rem" }}>
              {integration.display_name}
            </div>
            <div style={{ fontSize: "0.8rem", color: "var(--text-muted)", marginTop: 2 }}>
              {integration.description}
            </div>
          </div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span
            style={{
              display: "inline-block",
              padding: "2px 10px",
              borderRadius: 12,
              fontSize: "0.75rem",
              fontWeight: 500,
              background: isConfigured ? "rgba(34,197,94,0.12)" : "rgba(250,204,21,0.12)",
              color: isConfigured ? "var(--success, #22c55e)" : "var(--warning, #eab308)",
            }}
          >
            {isConfigured ? "Connected" : "Not configured"}
          </span>
          {!editing && (
            <button
              onClick={startEditing}
              style={{
                padding: "5px 12px",
                borderRadius: 6,
                border: "1px solid var(--border)",
                background: "transparent",
                color: "var(--text-secondary)",
                cursor: "pointer",
                fontSize: "0.8rem",
              }}
            >
              Configure
            </button>
          )}
        </div>
      </div>

      {/* Current config display (when not editing) */}
      {!editing && isConfigured && (
        <div style={{ padding: "12px 18px", borderTop: "1px solid var(--border)" }}>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))", gap: "8px 16px" }}>
            {integration.fields.map((field) => {
              const val = integration.config[field.name];
              if (!val) return null;
              return (
                <div key={field.name} style={{ fontSize: "0.8rem" }}>
                  <span style={{ color: "var(--text-muted)" }}>{field.label}: </span>
                  <span style={{ color: "var(--text-secondary)", fontFamily: "var(--font-mono, monospace)" }}>{val}</span>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Edit form */}
      {editing && (
        <div style={{ padding: "16px 18px" }}>
          <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
            {integration.fields.map((field) => (
              <FieldInput
                key={field.name}
                field={field}
                value={formValues[field.name] ?? ""}
                currentValue={integration.config[field.name] ?? ""}
                onChange={(v) => setFormValues((prev) => ({ ...prev, [field.name]: v }))}
              />
            ))}
          </div>

          {saveError && (
            <div style={{ color: "var(--error)", fontSize: "0.8rem", marginTop: 10 }}>{saveError}</div>
          )}

          <div style={{ display: "flex", gap: 8, marginTop: 16, justifyContent: "space-between" }}>
            <div>
              {isConfigured && (
                <button
                  onClick={handleDelete}
                  disabled={deleting}
                  style={{
                    padding: "6px 14px",
                    borderRadius: 6,
                    border: "1px solid var(--error, #ef4444)",
                    background: "transparent",
                    color: "var(--error, #ef4444)",
                    cursor: "pointer",
                    fontSize: "0.8rem",
                    opacity: deleting ? 0.5 : 1,
                  }}
                >
                  {deleting ? "Removing..." : "Remove"}
                </button>
              )}
            </div>
            <div style={{ display: "flex", gap: 8 }}>
              <button
                onClick={() => setEditing(false)}
                style={{
                  padding: "6px 14px",
                  borderRadius: 6,
                  border: "1px solid var(--border)",
                  background: "transparent",
                  color: "var(--text-secondary)",
                  cursor: "pointer",
                  fontSize: "0.8rem",
                }}
              >
                Cancel
              </button>
              <button
                onClick={handleSave}
                disabled={saving}
                style={{
                  padding: "6px 14px",
                  borderRadius: 6,
                  border: "none",
                  background: "var(--accent)",
                  color: "white",
                  cursor: "pointer",
                  fontSize: "0.8rem",
                  opacity: saving ? 0.6 : 1,
                }}
              >
                {saving ? "Saving..." : "Save"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Field input ──────────────────────────────────────────────────────────────

function FieldInput({
  field,
  value,
  currentValue,
  onChange,
}: {
  field: IntegrationField;
  value: string;
  currentValue: string;
  onChange: (v: string) => void;
}) {
  const inputType = field.type === "secret" ? "password" : field.type === "email" ? "email" : field.type === "url" ? "url" : "text";
  const placeholder = currentValue
    ? `Current: ${currentValue}`
    : field.placeholder || field.label;

  return (
    <div>
      <label style={{ display: "block", fontSize: "0.8rem", fontWeight: 500, color: "var(--text-secondary)", marginBottom: 4 }}>
        {field.label}
        {field.required && <span style={{ color: "var(--error, #ef4444)", marginLeft: 2 }}>*</span>}
      </label>
      {field.type === "textarea" ? (
        <textarea
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          rows={4}
          style={{
            width: "100%",
            padding: "8px 10px",
            borderRadius: 6,
            border: "1px solid var(--border)",
            background: "var(--bg-base)",
            color: "var(--text-primary)",
            fontSize: "0.85rem",
            fontFamily: "var(--font-mono, monospace)",
            resize: "vertical",
          }}
        />
      ) : (
        <input
          type={inputType}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          style={{
            width: "100%",
            padding: "8px 10px",
            borderRadius: 6,
            border: "1px solid var(--border)",
            background: "var(--bg-base)",
            color: "var(--text-primary)",
            fontSize: "0.85rem",
            fontFamily: inputType === "password" ? "inherit" : "var(--font-mono, monospace)",
            boxSizing: "border-box",
          }}
        />
      )}
      {field.help_text && (
        <div style={{ fontSize: "0.7rem", color: "var(--text-muted)", marginTop: 3 }}>{field.help_text}</div>
      )}
    </div>
  );
}

// ── Icons ────────────────────────────────────────────────────────────────────

function IntegrationIcon({ name }: { name: string }) {
  const size = 28;
  const style = {
    width: size,
    height: size,
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    borderRadius: 6,
    flexShrink: 0,
  } as const;

  switch (name) {
    case "discord":
      return (
        <div style={{ ...style, background: "rgba(88,101,242,0.15)", color: "#5865f2" }}>
          <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor">
            <path d="M20.317 4.37a19.791 19.791 0 00-4.885-1.515.074.074 0 00-.079.037c-.21.375-.444.864-.608 1.25a18.27 18.27 0 00-5.487 0 12.64 12.64 0 00-.617-1.25.077.077 0 00-.079-.037A19.736 19.736 0 003.677 4.37a.07.07 0 00-.032.027C.533 9.046-.32 13.58.099 18.057a.082.082 0 00.031.057 19.9 19.9 0 005.993 3.03.078.078 0 00.084-.028c.462-.63.874-1.295 1.226-1.994a.076.076 0 00-.041-.106 13.107 13.107 0 01-1.872-.892.077.077 0 01-.008-.128 10.2 10.2 0 00.372-.292.074.074 0 01.077-.01c3.928 1.793 8.18 1.793 12.062 0a.074.074 0 01.078.01c.12.098.246.198.373.292a.077.077 0 01-.006.127 12.299 12.299 0 01-1.873.892.077.077 0 00-.041.107c.36.698.772 1.362 1.225 1.993a.076.076 0 00.084.028 19.839 19.839 0 006.002-3.03.077.077 0 00.032-.054c.5-5.177-.838-9.674-3.549-13.66a.061.061 0 00-.031-.03zM8.02 15.33c-1.183 0-2.157-1.085-2.157-2.419 0-1.333.956-2.419 2.157-2.419 1.21 0 2.176 1.096 2.157 2.42 0 1.333-.956 2.418-2.157 2.418zm7.975 0c-1.183 0-2.157-1.085-2.157-2.419 0-1.333.955-2.419 2.157-2.419 1.21 0 2.176 1.096 2.157 2.42 0 1.333-.946 2.418-2.157 2.418z" />
          </svg>
        </div>
      );
    case "github":
      return (
        <div style={{ ...style, background: "rgba(255,255,255,0.1)", color: "var(--text-primary)" }}>
          <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor">
            <path d="M12 0C5.374 0 0 5.373 0 12c0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23A11.509 11.509 0 0112 5.803c1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576C20.566 21.797 24 17.3 24 12c0-6.627-5.373-12-12-12z" />
          </svg>
        </div>
      );
    case "asana":
      return (
        <div style={{ ...style, background: "rgba(246,116,99,0.15)", color: "#f67463" }}>
          <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor">
            <path d="M18.78 12.653c-2.882 0-5.22 2.337-5.22 5.218S15.898 23.09 18.78 23.09 24 20.752 24 17.871s-2.338-5.218-5.22-5.218zM5.22 12.653C2.338 12.653 0 14.99 0 17.871s2.338 5.218 5.22 5.218 5.22-2.337 5.22-5.218-2.338-5.218-5.22-5.218zM12 .91c-2.882 0-5.22 2.337-5.22 5.218S9.118 11.346 12 11.346s5.22-2.337 5.22-5.218S14.882.91 12 .91z" />
          </svg>
        </div>
      );
    case "email":
      return (
        <div style={{ ...style, background: "rgba(59,130,246,0.15)", color: "#3b82f6" }}>
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <rect x="2" y="4" width="20" height="16" rx="2" />
            <path d="M22 7l-10 7L2 7" />
          </svg>
        </div>
      );
    default:
      return (
        <div style={{ ...style, background: "rgba(148,163,184,0.15)", color: "var(--text-muted)" }}>
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M12 2L2 7l10 5 10-5-10-5z" />
            <path d="M2 17l10 5 10-5" />
            <path d="M2 12l10 5 10-5" />
          </svg>
        </div>
      );
  }
}
