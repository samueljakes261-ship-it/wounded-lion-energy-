from typing import List


def parse_json(data) -> List[dict]:

    matches = []

    # Sport
    for country in data.get("CNT", []):

        # Competition
        for competition in country.get("CL", []):

            # Events
            for event in competition.get("E", []):

                home = event.get("EHT") or event.get("HT")
                away = event.get("EAT") or event.get("AT")

                kickoff = event.get("D")

                home_price = None
                draw_price = None
                away_price = None

                for market in event.get("StakeTypes", []):

                    # Match Odds market
                    if market.get("Id") != 1:
                        continue

                    for stake in market.get("Stakes", []):

                        selection = stake.get("SN")
                        price = stake.get("F")

                        if selection == "1":
                            home_price = price

                        elif selection == "X":
                            draw_price = price

                        elif selection in ("2", "Kazanan2"):
                            away_price = price

                if (
                    home_price is not None
                    and draw_price is not None
                    and away_price is not None
                ):

                    matches.append(
                        {
                            "event_id": event.get("Id"),
                            "competition": competition.get("EGN")
                            or competition.get("N"),
                            "sport": data.get("EGN")
                            or data.get("N"),
                            "home": home,
                            "away": away,
                            "kickoff": kickoff,
                            "home_odds": float(home_price),
                            "draw_odds": float(draw_price),
                            "away_odds": float(away_price),
                        }
                    )

    return matches