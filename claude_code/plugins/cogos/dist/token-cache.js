/**
 * Token cache — stores CogOS API tokens in ~/.cogos/tokens.yml
 */
import { readFileSync, writeFileSync, mkdirSync } from "fs";
import { homedir } from "os";
import { join } from "path";
import YAML from "yaml";
const CACHE_DIR = join(homedir(), ".cogos");
const CACHE_FILE = join(CACHE_DIR, "tokens.yml");
function loadCache() {
    try {
        const content = readFileSync(CACHE_FILE, "utf-8");
        const parsed = YAML.parse(content);
        return parsed && parsed.tokens ? parsed : { tokens: {} };
    }
    catch {
        return { tokens: {} };
    }
}
function saveCache(cache) {
    mkdirSync(CACHE_DIR, { recursive: true });
    writeFileSync(CACHE_FILE, YAML.stringify(cache), "utf-8");
}
export function getCachedToken(address) {
    const cache = loadCache();
    const entry = cache.tokens[address];
    return entry?.token ?? null;
}
export function cacheToken(address, token, cogentName) {
    const cache = loadCache();
    cache.tokens[address] = {
        token,
        cogent_name: cogentName,
        cached_at: new Date().toISOString(),
    };
    saveCache(cache);
}
export function removeCachedToken(address) {
    const cache = loadCache();
    delete cache.tokens[address];
    saveCache(cache);
}
