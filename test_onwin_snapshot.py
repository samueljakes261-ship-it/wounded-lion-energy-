import json


SNAPSHOT_FILE = "output/onwin_main_line.json"


def extract_live_1x2_events(data):
    results = []

    sports = data.get("sports", {})

    for sport_id, sport_data in sports.items():

        categories = sport_data.get("categories", {})

        for category_id, category_data in categories.items():

            category_diff = category_data.get("diff", {})
            category_name = category_diff.get("name")

            tournaments = category_data.get("tournaments", {})

            for tournament_id, tournament_data in tournaments.items():

                tournament_diff = tournament_data.get("diff", {})

                tournament_name = tournament_diff.get(
                    "name",
                    tournament_diff.get("slug", "Unknown")
                )

                events = tournament_data.get("events", {})

                for event_id, event_data in events.items():

                    event_diff = event_data.get("diff", {})

                    # We only want live/in-progress events.
                    if event_diff.get("status") != "in_progress":
                        continue

                    participants = event_diff.get(
                        "participants",
                        {}
                    )

                    team1 = participants.get("team1", {})
                    team2 = participants.get("team2", {})

                    team1_name = team1.get("name")
                    team2_name = team2.get("name")

                    if not team1_name or not team2_name:
                        continue

                    scopes = event_data.get("scopes", {})

                    odds = {}
                    scores = {}

                    for scope_id, scope_data in scopes.items():

                        scope_diff = scope_data.get("diff", {})

                        # We want the normal-time 1X2 market.
                        if scope_diff.get("type") != "normal_time":
                            continue

                        markets = scope_data.get("markets", {})

                        market = markets.get("score_1x2--nil")

                        if not market:
                            continue

                        outcomes = market.get("outcomes", {})

                        for outcome_key, outcome_data in outcomes.items():

                            coefficient = outcome_data.get(
                                "coefficient"
                            )

                            parameters = outcome_data.get(
                                "parameters",
                                {}
                            )

                            outcome = parameters.get("outcome")

                            if outcome and coefficient is not None:
                                odds[outcome] = coefficient

                        # Scores may be in the same scope.
                        scope_scores = scope_data.get("scores", {})

                        for score_key, score_data in scope_scores.items():

                            team_id = score_data.get("teamId")
                            value = score_data.get("value")

                            if team_id and value is not None:
                                scores[team_id] = value

                    # We only keep events where we actually found 1X2 odds.
                    if not odds:
                        continue

                    results.append(
                        {
                            "sport_id": sport_id,
                            "category_id": category_id,
                            "category": category_name,
                            "tournament_id": tournament_id,
                            "tournament": tournament_name,
                            "event_id": event_id,

                            "team1": {
                                "name": team1_name,
                                "short_id": team1.get("shortId"),
                                "team_id": team1.get("teamId"),
                            },

                            "team2": {
                                "name": team2_name,
                                "short_id": team2.get("shortId"),
                                "team_id": team2.get("teamId"),
                            },

                            "odds": odds,
                            "scores": scores,
                        }
                    )

    return results


def main():

    print("\nLoading Onwin snapshot...")

    with open(
        SNAPSHOT_FILE,
        "r",
        encoding="utf-8"
    ) as f:

        data = json.load(f)

    print("Snapshot loaded.")

    events = extract_live_1x2_events(data)

    print("\n" + "=" * 80)
    print("LIVE 1X2 EVENTS FOUND:", len(events))
    print("=" * 80)

    for index, event in enumerate(events, start=1):

        print("\n" + "-" * 80)

        print(f"EVENT #{index}")

        print(
            f"{event['team1']['name']} "
            f"vs "
            f"{event['team2']['name']}"
        )

        print(
            f"Category: {event['category']}"
        )

        print(
            f"Tournament: {event['tournament']}"
        )

        print(
            f"Event ID: {event['event_id']}"
        )

        print(
            f"Team 1 ID: {event['team1']['team_id']}"
        )

        print(
            f"Team 2 ID: {event['team2']['team_id']}"
        )

        print(
            f"Odds: {event['odds']}"
        )

        print(
            f"Scores: {event['scores']}"
        )


if __name__ == "__main__":
    main()