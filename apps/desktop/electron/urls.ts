/**
 * Allowlist for URLs the shell may open in the user's browser.
 *
 * The renderer can only open links on official Coinbase domains, over
 * https. Everything else (javascript:, file:, arbitrary hosts) is rejected
 * before shell.openExternal is ever called.
 */

const ALLOWED_EXTERNAL_PREFIXES = [
  "https://portal.cdp.coinbase.com/",
  "https://docs.cdp.coinbase.com/",
  "https://www.coinbase.com/",
];

export function isAllowedExternalUrl(url: string): boolean {
  try {
    const parsed = new URL(url);
    if (parsed.protocol !== "https:") {
      return false;
    }
    return ALLOWED_EXTERNAL_PREFIXES.some((prefix) => url.startsWith(prefix));
  } catch {
    return false;
  }
}
