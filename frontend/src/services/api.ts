const API_BASE = "http://127.0.0.1:8000";

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