import { describe, expect, it } from "vitest";
import { isAllowedExternalUrl } from "../electron/urls";

describe("isAllowedExternalUrl", () => {
  it("allows official Coinbase https pages", () => {
    expect(isAllowedExternalUrl("https://portal.cdp.coinbase.com/api-keys/secret")).toBe(true);
    expect(isAllowedExternalUrl("https://docs.cdp.coinbase.com/coinbase-app/get-started")).toBe(true);
    expect(isAllowedExternalUrl("https://www.coinbase.com/signin")).toBe(true);
  });

  it("rejects non-https schemes outright", () => {
    expect(isAllowedExternalUrl("http://portal.cdp.coinbase.com/api-keys/secret")).toBe(false);
    expect(isAllowedExternalUrl("javascript:alert(1)")).toBe(false);
    expect(isAllowedExternalUrl("file:///C:/Windows/System32")).toBe(false);
  });

  it("rejects lookalike and arbitrary hosts", () => {
    expect(isAllowedExternalUrl("https://portal.cdp.coinbase.com.evil.example/keys")).toBe(false);
    expect(isAllowedExternalUrl("https://example.com/coinbase")).toBe(false);
  });

  it("rejects garbage input", () => {
    expect(isAllowedExternalUrl("")).toBe(false);
    expect(isAllowedExternalUrl("not a url")).toBe(false);
  });
});
