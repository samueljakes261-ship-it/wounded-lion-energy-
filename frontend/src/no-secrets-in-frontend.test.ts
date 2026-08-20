// Structural safety net: no backend secret name/value should ever
// appear anywhere under frontend/src, since every VITE_* variable is
// inlined into the public browser bundle at build time. This does not
// (and cannot) prove a *real* secret value was never pasted in, but it
// does catch the specific, known secret identifiers this project uses
// if someone were to reference them from a VITE_* variable or import
// them directly.
import { readdirSync, readFileSync, statSync } from "node:fs"
import { dirname, join } from "node:path"
import { fileURLToPath } from "node:url"
import { describe, expect, it } from "vitest"

const SRC_DIR = dirname(fileURLToPath(import.meta.url))

const FORBIDDEN_PATTERNS: RegExp[] = [
  /ZENROWS_BROWSER_WS/,
  /ZENROWS_API_KEY/i,
  /MASTER_CREDENTIAL_KEY/,
  /SCRAPFLY_API_KEY/,
  /BRIGHTDATA_PASSWORD/,
  /credentials\.json/,
  /apikey=[a-z0-9]{10,}/i, // an actual embedded ZenRows-style API key
]

function collectSourceFiles(dir: string): string[] {
  const files: string[] = []
  for (const entry of readdirSync(dir)) {
    const fullPath = join(dir, entry)
    const stats = statSync(fullPath)
    if (stats.isDirectory()) {
      files.push(...collectSourceFiles(fullPath))
    } else if (/\.(ts|tsx|js|jsx)$/.test(entry) && !entry.endsWith(".test.ts") && !entry.endsWith(".test.tsx")) {
      files.push(fullPath)
    }
  }
  return files
}

describe("no backend secrets referenced from frontend source", () => {
  const files = collectSourceFiles(SRC_DIR)

  it("scans at least the expected frontend source files", () => {
    expect(files.length).toBeGreaterThan(5)
  })

  for (const file of files) {
    it(`${file.replace(SRC_DIR, "src")} contains no forbidden secret identifiers`, () => {
      const content = readFileSync(file, "utf-8")
      for (const pattern of FORBIDDEN_PATTERNS) {
        expect(content).not.toMatch(pattern)
      }
    })
  }
})
