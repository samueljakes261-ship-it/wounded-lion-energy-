import json
import os
from copy import deepcopy

from parsers.onwin.browser import OnwinBrowser

TARGET = "find_event_snapshots.erisgaming"
OUTPUT_FILE = "output/onwin_update_analysis.json"

browser = OnwinBrowser()
page = browser.page()

responses = []
previous_data = None


def extract_event_summary(data):
    """
    Extract a compact representation of the event/market/outcome
    structure so successive responses can be compared.
    """

    summary = {}

    try:
        sports = data.get("sports", {})

        for sport_id, sport in sports.items():
            categories = sport.get("categories", {})

            for category_id, category in categories.items():
                tournaments = category.get("tournaments", {})

                for tournament_id, tournament in tournaments.items():
                    events = tournament.get("events", {})

                    for event_id, event in events.items():
                        event_summary = {
                            "status": event.get("diff", {}).get("status"),
                            "startTime": event.get("diff", {}).get("startTime"),
                            "participants": {},
                            "markets": {},
                        }

                        participants = (
                            event.get("diff", {})
                            .get("participants", {})
                        )

                        for participant_key, participant in participants.items():
                            event_summary["participants"][participant_key] = {
                                "name": participant.get("name"),
                                "teamId": participant.get("teamId"),
                            }

                        scopes = event.get("scopes", {})

                        for scope_id, scope in scopes.items():
                            markets = scope.get("markets", {})

                            for market_id, market in markets.items():

                                outcomes = market.get("outcomes", {})

                                market_summary = {}

                                for outcome_id, outcome in outcomes.items():
                                    market_summary[outcome_id] = {
                                        "coefficient": outcome.get("coefficient"),
                                        "locked": outcome.get("locked"),
                                        "updatedAt": outcome.get("updatedAt"),
                                    }

                                event_summary["markets"][
                                    f"{scope_id}|{market_id}"
                                ] = market_summary

                        summary[event_id] = event_summary

    except Exception as e:
        print(
            "Could not extract event summary:",
            type(e).__name__,
            e,
        )

    return summary


def compare_summaries(old, new):
    """
    Compare two extracted event summaries and report
    newly created, removed, and changed events/outcomes.
    """

    changes = {
        "new_events": [],
        "removed_events": [],
        "changed_events": [],
        "changed_outcomes": [],
    }

    old_events = set(old.keys())
    new_events = set(new.keys())

    changes["new_events"] = sorted(new_events - old_events)
    changes["removed_events"] = sorted(old_events - new_events)

    common_events = old_events & new_events

    for event_id in sorted(common_events):

        old_event = old[event_id]
        new_event = new[event_id]

        if old_event != new_event:
            changes["changed_events"].append(event_id)

        old_markets = old_event.get("markets", {})
        new_markets = new_event.get("markets", {})

        common_markets = set(old_markets) & set(new_markets)

        for market_id in common_markets:

            old_outcomes = old_markets[market_id]
            new_outcomes = new_markets[market_id]

            common_outcomes = (
                set(old_outcomes) & set(new_outcomes)
            )

            for outcome_id in common_outcomes:

                old_outcome = old_outcomes[outcome_id]
                new_outcome = new_outcomes[outcome_id]

                if old_outcome != new_outcome:
                    changes["changed_outcomes"].append(
                        {
                            "event_id": event_id,
                            "market": market_id,
                            "outcome": outcome_id,
                            "old": old_outcome,
                            "new": new_outcome,
                        }
                    )

    return changes


def handle_response(response):

    global previous_data

    if TARGET not in response.url:
        return

    print("\n" + "=" * 90)
    print("ONWIN UPDATE RESPONSE")
    print("=" * 90)

    print("\nSTATUS:")
    print(response.status)

    try:

        body = response.body()

        print("\nRESPONSE SIZE:")
        print(len(body), "bytes")

        if not body:
            print("\nEmpty response.")
            return

        text = body.decode(
            "utf-8",
            errors="replace",
        )

        try:
            data = json.loads(text)

        except json.JSONDecodeError as e:

            print("\nResponse is not JSON:")
            print(e)

            return

        version = data.get("versions")

        print("\nVERSION:")
        print(version)

        current_summary = extract_event_summary(data)

        print("\nEVENTS IN RESPONSE:")
        print(len(current_summary))

        if previous_data is None:

            print("\nBASELINE RESPONSE CAPTURED.")

            previous_data = deepcopy(current_summary)

        else:

            changes = compare_summaries(
                previous_data,
                current_summary,
            )

            print("\nCHANGES DETECTED:")

            print(
                "New events:",
                len(changes["new_events"]),
            )

            print(
                "Removed events:",
                len(changes["removed_events"]),
            )

            print(
                "Changed events:",
                len(changes["changed_events"]),
            )

            print(
                "Changed outcomes:",
                len(changes["changed_outcomes"]),
            )

            if changes["changed_outcomes"]:

                print("\nODDS CHANGES:")

                for change in changes["changed_outcomes"][:20]:

                    print(
                        f"\nEvent: {change['event_id']}"
                    )

                    print(
                        f"Market: {change['market']}"
                    )

                    print(
                        f"Outcome: {change['outcome']}"
                    )

                    print(
                        f"OLD: {change['old']}"
                    )

                    print(
                        f"NEW: {change['new']}"
                    )

            previous_data = deepcopy(current_summary)

        responses.append(
            {
                "version": version,
                "response_size": len(body),
                "event_count": len(current_summary),
            }
        )

        os.makedirs(
            os.path.dirname(OUTPUT_FILE),
            exist_ok=True,
        )

        with open(
            OUTPUT_FILE,
            "w",
            encoding="utf-8",
        ) as f:

            json.dump(
                responses,
                f,
                indent=2,
                ensure_ascii=False,
            )

        print("\nANALYSIS SAVED TO:")
        print(OUTPUT_FILE)

    except Exception as e:

        print(
            "\nCould not process response:",
            type(e).__name__,
            e,
        )


page.on(
    "response",
    handle_response,
)


print("\n" + "=" * 90)
print("OPENING ONWIN")
print("=" * 90)

try:

    page.goto(
        "https://onwin4505.com/sportsbook/live/main-line/soccer",
        wait_until="domcontentloaded",
        timeout=30000,
    )

except Exception as e:

    print(
        "\nNavigation finished with:",
        type(e).__name__,
        e,
    )


print("\nPAGE LOADED:")
print(page.url)

print("\nLISTENING FOR:")
print(TARGET)

print("\nLeave this running for about 5 minutes.")
print("Do NOT close the browser.")

try:

    for i in range(300):

        if page.is_closed():

            print("\nPage was closed.")
            break

        page.wait_for_timeout(1000)

        if i % 10 == 0:

            print(
                f"Listening... {i} seconds"
            )

except KeyboardInterrupt:

    print("\nStopped manually.")

finally:

    print("\nStopping test...")

    try:

        page.remove_listener(
            "response",
            handle_response,
        )

    except Exception:
        pass