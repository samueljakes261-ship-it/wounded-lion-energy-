const API_BASE = "https://wounded-lion-energy.onrender.com";

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