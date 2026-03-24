/**
 * Token cache — stores CogOS API tokens in ~/.cogos/tokens.yml
 */
export declare function getCachedToken(address: string): string | null;
export declare function cacheToken(address: string, token: string, cogentName: string): void;
export declare function removeCachedToken(address: string): void;
