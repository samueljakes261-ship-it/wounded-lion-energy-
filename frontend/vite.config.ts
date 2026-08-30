// @lovable.dev/vite-tanstack-config already includes the following — do NOT add them manually
// or the app will break with duplicate plugins:
//   - TanStack devtools (dev-only, first), tanstackStart, viteReact, tailwindcss, tsConfigPaths,
//     nitro (build-only using cloudflare as a default target), VITE_* env injection, @ path alias,
//     React/TanStack dedupe, error logger plugins, and sandbox detection (port/host/strictPort).
// You can pass additional config via defineConfig({ vite: { ... }, etc... }) if needed.
import { defineConfig } from "@lovable.dev/vite-tanstack-config";

export default defineConfig({
  tanstackStart: {
    // Redirect TanStack Start's bundled server entry to src/server.ts (our SSR error wrapper).
    // nitro/vite builds from this
    server: { entry: "server" },
  },
  // Dev-only proxy for the isolated Kenyan Bookmakers section (see
  // src/lib/kenyan-api-config.ts). Forwards /kenyan/* requests from
  // the Vite dev server to the local Kenyan-enabled FastAPI backend
  // (api.py, default port 8000) SERVER-SIDE, so the browser only ever
  // talks to whatever origin actually served this page -- this is
  // what makes the Kenyan access gate work when the dev server is
  // reached through a forwarded/tunneled URL rather than directly on
  // localhost (an absolute "http://localhost:8000" URL baked into the
  // browser bundle would otherwise try to reach port 8000 on the
  // VIEWER's own machine, not this one, causing "Could not reach the
  // Kenyan bookmakers service"). Does not affect the existing
  // Turkish/client-facing /opportunities or /status calls, which
  // still use lib/api-config.ts's own VITE_API_URL-based absolute
  // URL unchanged. Has no effect in a production build (no dev
  // server there) or when VITE_API_URL is explicitly set.
  vite: {
    server: {
      // Allows this dev server to be reached through a temporary
      // public tunnel (e.g. serveo.net/ngrok) for manual testing from
      // outside this VM -- Vite's Host-header check otherwise blocks
      // any hostname not explicitly listed (anti DNS-rebinding
      // protection). Dev-only; has no effect on a production build or
      // on the existing Turkish/client-facing behavior.
      allowedHosts: true,
      proxy: {
        // Matches the Kenyan backend's actual sub-routes
        // (/kenyan/auth, /kenyan/opportunities, /kenyan/status) but
        // deliberately NOT the bare "/kenyan" path itself, which is
        // this frontend's own page route (src/routes/kenyan.tsx) and
        // must keep being served by Vite/TanStack Start, not proxied
        // to the backend (which has no route for it and would 404).
        "^/kenyan/(auth|opportunities|status)": {
          target: process.env.KENYAN_API_PROXY_TARGET ?? "http://localhost:8000",
          changeOrigin: true,
        },
      },
    },
  },
});
