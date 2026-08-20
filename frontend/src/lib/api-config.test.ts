import { describe, expect, it } from "vitest"
import { LOCAL_DEV_FALLBACK_API_URL, resolveApiConfig } from "./api-config"

describe("resolveApiConfig", () => {
  it("uses VITE_API_URL for local development configuration", () => {
    const config = resolveApiConfig({ VITE_API_URL: "http://localhost:8000" })

    expect(config.apiUrl).toBe("http://localhost:8000/opportunities")
    expect(config.statusUrl).toBe("http://localhost:8000/status")
    expect(config.usedLocalDevFallback).toBe(false)
  })

  it("uses VITE_API_URL for production configuration (a real deployed backend)", () => {
    const config = resolveApiConfig({
      VITE_API_URL: "https://arbscanner-backend.example.com",
    })

    expect(config.apiUrl).toBe("https://arbscanner-backend.example.com/opportunities")
    expect(config.statusUrl).toBe("https://arbscanner-backend.example.com/status")
    expect(config.usedLocalDevFallback).toBe(false)
  })

  it("tolerates a VITE_API_URL that already includes /opportunities", () => {
    const config = resolveApiConfig({
      VITE_API_URL: "https://arbscanner-backend.example.com/opportunities",
    })

    expect(config.apiUrl).toBe("https://arbscanner-backend.example.com/opportunities")
    expect(config.statusUrl).toBe("https://arbscanner-backend.example.com/status")
  })

  it("tolerates a trailing slash on VITE_API_URL", () => {
    const config = resolveApiConfig({
      VITE_API_URL: "https://arbscanner-backend.example.com/",
    })

    expect(config.apiUrl).toBe("https://arbscanner-backend.example.com/opportunities")
  })

  it("falls back to a LOCAL-ONLY development URL when VITE_API_URL is unset -- never a production/tunnel URL", () => {
    const config = resolveApiConfig({})

    expect(config.apiUrl).toBe(`${LOCAL_DEV_FALLBACK_API_URL}/opportunities`)
    expect(config.usedLocalDevFallback).toBe(true)
    // The fallback host must be localhost -- a missing VITE_API_URL in
    // production must never silently resolve to some other developer's
    // machine or a stale tunnel.
    expect(new URL(config.apiUrl).hostname).toBe("localhost")
  })

  it("never resolves to a hardcoded ngrok URL under any input", () => {
    const withEnv = resolveApiConfig({ VITE_API_URL: "https://real-backend.example.com" })
    const withoutEnv = resolveApiConfig({})

    expect(withEnv.apiUrl).not.toMatch(/ngrok/i)
    expect(withoutEnv.apiUrl).not.toMatch(/ngrok/i)
    expect(withEnv.statusUrl).not.toMatch(/ngrok/i)
    expect(withoutEnv.statusUrl).not.toMatch(/ngrok/i)
  })

  it("flags usedLocalDevFallback so callers can warn loudly in production instead of silently failing", () => {
    expect(resolveApiConfig({}).usedLocalDevFallback).toBe(true)
    expect(
      resolveApiConfig({ VITE_API_URL: "https://real-backend.example.com" })
        .usedLocalDevFallback
    ).toBe(false)
  })
})
