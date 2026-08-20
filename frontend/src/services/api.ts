// NOTE: this module is not currently imported anywhere -- the live
// dashboard (frontend/src/routes/index.tsx) fetches directly. Kept
// for backward compatibility with anything that may import it, but
// aligned to the same rule as routes/index.tsx: the backend URL comes
// exclusively from VITE_API_URL (see frontend/.env.example), never a
// hardcoded production/tunnel URL baked into source.
const API_BASE = (import.meta.env.VITE_API_URL ?? "http://localhost:8000").replace(
    /\/opportunities\/?$/,
    ""
);

export async function getOpportunities() {
    const response = await fetch(
        `${API_BASE}/opportunities`
    );

    if (!response.ok) {
        throw new Error(
            "Unable to load arbitrage opportunities."
        );
    }

    return await response.json();
}
