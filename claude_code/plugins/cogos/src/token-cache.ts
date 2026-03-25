/**
 * Token cache — stores CogOS API tokens in ~/.cogos/tokens.yml
 */

import { readFileSync, writeFileSync, mkdirSync } from "fs";
import { homedir } from "os";
import { join } from "path";
import YAML from "yaml";

interface TokenEntry {
  token: string;
  cogent_name: string;
  cached_at: string;
}

interface TokenCache {
  tokens: Record<string, TokenEntry>;
  dashboard_keys?: Record<string, string>;
}

const CACHE_DIR = join(homedir(), ".cogos");
const CACHE_FILE = join(CACHE_DIR, "tokens.yml");

function loadCache(): TokenCache {
  try {
    const content = readFileSync(CACHE_FILE, "utf-8");
    const parsed = YAML.parse(content) as TokenCache | null;
    return parsed && parsed.tokens ? parsed : { tokens: {} };
  } catch {
    return { tokens: {} };
  }
}

function saveCache(cache: TokenCache): void {
  mkdirSync(CACHE_DIR, { recursive: true });
  writeFileSync(CACHE_FILE, YAML.stringify(cache), "utf-8");
}

export function getCachedToken(address: string): string | null {
  const cache = loadCache();
  const entry = cache.tokens[address];
  return entry?.token ?? null;
}

export function cacheToken(
  address: string,
  token: string,
  cogentName: string,
): void {
  const cache = loadCache();
  cache.tokens[address] = {
    token,
    cogent_name: cogentName,
    cached_at: new Date().toISOString(),
  };
  saveCache(cache);
}

export function removeCachedToken(address: string): void {
  const cache = loadCache();
  delete cache.tokens[address];
  saveCache(cache);
}

export function getCachedDashboardKey(host: string): string | null {
  const cache = loadCache();
  return cache.dashboard_keys?.[host] ?? null;
}

export function cacheDashboardKey(host: string, key: string): void {
  const cache = loadCache();
  if (!cache.dashboard_keys) cache.dashboard_keys = {};
  cache.dashboard_keys[host] = key;
  saveCache(cache);
}
