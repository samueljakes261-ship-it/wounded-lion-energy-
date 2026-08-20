from typing import List

from debug import odds_trace


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

                    home_odds = float(home_price)
                    draw_odds = float(draw_price)
                    away_odds = float(away_price)

                    # RAW == the exact value BetKanyon's own JSON
                    # carried (a string or number, e.g. "F": "2.15");
                    # PARSED == that same value cast to float. Traced
                    # together so a discrepancy introduced by the
                    # float() cast itself (there should never be one)
                    # is visible, not assumed away.
                    odds_trace.record(
                        "PARSED",
                        "Betkanyon",
                        home,
                        away,
                        "Match Odds",
                        None,
                        home_odds,
                        draw_odds,
                        away_odds,
                        raw={
                            "home": home_price,
                            "draw": draw_price,
                            "away": away_price,
                        },
                    )

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
                            "home_odds": home_odds,
                            "draw_odds": draw_odds,
                            "away_odds": away_odds,
                        }
                    )

    return matches