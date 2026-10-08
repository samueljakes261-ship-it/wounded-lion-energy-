import { describe, expect, it } from "vitest";
import { resolveKenyanApiBase } from "./kenyan-api-config";

describe("resolveKenyanApiBase", () => {
  it("uses a RELATIVE path when VITE_API_URL is unset, for the dev-server proxy", () => {
    // See vite.config.ts's server.proxy entry for "^/kenyan/(auth|opportunities|status)":
    // an absolute "http://localhost:8000" URL baked into the browser
    // bundle only resolves when the browser and backend share the
    // same machine -- it breaks the moment the dev server is reached
    // through a forwarded/tunneled URL (a different machine's
    // "localhost" is not this one's). A relative path always
    // resolves against whatever origin actually served the page.
    expect(resolveKenyanApiBase({})).toBe("/kenyan");
  });

  it("uses the absolute VITE_API_URL when explicitly set (production, real backend)", () => {
    expect(resolveKenyanApiBase({ VITE_API_URL: "https://arbscanner-backend.example.com" })).toBe(
      "https://arbscanner-backend.example.com/kenyan",
    );
  });

  it("tolerates a trailing slash on VITE_API_URL", () => {
    expect(resolveKenyanApiBase({ VITE_API_URL: "https://arbscanner-backend.example.com/" })).toBe(
      "https://arbscanner-backend.example.com/kenyan",
    );
  });

  it("never resolves to a hardcoded ngrok URL under any input", () => {
    expect(resolveKenyanApiBase({})).not.toMatch(/ngrok/i);
    expect(resolveKenyanApiBase({ VITE_API_URL: "https://real-backend.example.com" })).not.toMatch(
      /ngrok/i,
    );
  });
});
