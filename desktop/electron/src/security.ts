import type { UiLocale } from "./shared.js";

const EXTERNAL_HOSTS = new Set([
  "github.com",
  "huggingface.co",
  "ai.google.dev",
  "raw.githubusercontent.com",
]);

export function preferredUiLocale(languages: readonly string[]): UiLocale {
  for (const raw of languages) {
    const language = raw.toLowerCase().split(/[-_]/, 1)[0];
    if (language === "ru") return "ru";
    if (language === "en") return "en";
  }
  return "en";
}

export function preferredTargetLanguage(languages: readonly string[], supported: ReadonlySet<string>): string {
  for (const raw of languages) {
    const normalized = raw.toLowerCase();
    if (supported.has(normalized)) return normalized;
    const base = normalized.split(/[-_]/, 1)[0];
    if (supported.has(base)) return base;
  }
  return supported.has("en") ? "en" : [...supported][0] ?? "en";
}

export function allowedExternalUrl(raw: string): URL | null {
  try {
    const value = new URL(raw);
    if (value.protocol !== "https:" || value.username || value.password || !EXTERNAL_HOSTS.has(value.hostname)) {
      return null;
    }
    return value;
  } catch {
    return null;
  }
}

export function allowedBackendUrl(raw: string): URL | null {
  try {
    const value = new URL(raw);
    if (value.protocol !== "http:" || value.hostname !== "127.0.0.1" || !value.port) return null;
    if (!/^\/[A-Za-z0-9_-]{32,64}\/live\/$/.test(value.pathname)) return null;
    if (value.search || value.hash || value.username || value.password) return null;
    return value;
  } catch {
    return null;
  }
}
