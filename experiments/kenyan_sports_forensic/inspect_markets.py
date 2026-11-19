"""Sanitized market-field inspection. No secrets."""
from __future__ import annotations

import json

from kenyan.http_utils import fetch_json


def _item_keys(item):
    if not isinstance(item, dict):
        return None
    return {
        k: item.get(k)
        for k in item
        if k in (
            "type",
            "T",
            "param",
            "P",
            "name",
            "N",
            "cf",
            "C",
            "blocked",
            "B",
            "id",
            "I",
            "pt",
            "PT",
            "p",
            "parameter",
            "groupId",
            "G",
        )
    }


def inspect_1x(label, url):
    result = fetch_json(url, timeout=25)
    body = result.json_body
    events = body if isinstance(body, list) else (body.get("Value") if isinstance(body, dict) else [])
    events = events if isinstance(events, list) else []
    out = {"label": label, "ok": result.ok, "http": result.status_code, "events": len(events)}
    samples = []
    for event in events[:6]:
        if not isinstance(event, dict):
            continue
        if "eventGroups" in event:
            groups = []
            for group in event.get("eventGroups") or []:
                items = []
                for wrapper in group.get("events") or []:
                    for item in wrapper if isinstance(wrapper, list) else []:
                        keys = _item_keys(item)
                        if keys:
                            items.append(keys)
                groups.append(
                    {
                        "groupId": group.get("groupId"),
                        "name": group.get("name") or group.get("groupName"),
                        "keys": sorted(group.keys()),
                        "items": items[:8],
                    }
                )
            samples.append(
                {
                    "shape": "grouped",
                    "sport": (event.get("sport") or {}).get("name"),
                    "home": (event.get("opponent1") or {}).get("fullName"),
                    "away": (event.get("opponent2") or {}).get("fullName"),
                    "periodName": event.get("periodName"),
                    "event_keys": sorted(event.keys())[:40],
                    "groups": groups,
                }
            )
        else:
            samples.append(
                {
                    "shape": "flat",
                    "sport": event.get("SN"),
                    "home": event.get("O1"),
                    "away": event.get("O2"),
                    "event_keys": sorted(event.keys())[:40],
                    "items": [_item_keys(i) for i in (event.get("E") or [])[:20] if isinstance(i, dict)],
                }
            )
    out["samples"] = samples
    print(json.dumps(out, ensure_ascii=True, default=str)[:12000])
    return out


def inspect_betika(label, url):
    result = fetch_json(url, timeout=25)
    body = result.json_body or {}
    rows = body.get("data") or []
    markets = []
    for row in rows:
        for market in row.get("odds") or []:
            outcomes = market.get("odds") or []
            markets.append(
                {
                    "sport": row.get("sport_name"),
                    "home": row.get("home_team"),
                    "away": row.get("away_team"),
                    "sub_type_id": market.get("sub_type_id"),
                    "name": market.get("name"),
                    "market_keys": sorted(market.keys()),
                    "outcomes": [
                        {
                            "id": o.get("outcome_id"),
                            "key": o.get("odd_key"),
                            "display": o.get("display"),
                            "special": o.get("special_bet_value"),
                            "parsed": o.get("parsed_special_bet_value"),
                            "odd": o.get("odd_value"),
                        }
                        for o in outcomes[:6]
                        if isinstance(o, dict)
                    ],
                }
            )
    out = {
        "label": label,
        "ok": result.ok,
        "http": result.status_code,
        "events": len(rows),
        "meta": body.get("meta"),
        "side_bet_sample": (rows[0].get("side_bets") if rows else None),
        "markets": markets[:20],
    }
    print(json.dumps(out, ensure_ascii=True, default=str)[:12000])
    return out


def main():
    inspect_1x(
        "1x_tennis_pre",
        "https://1xbet.co.ke/service-api/main-line-feed/v3/games1x2?cfView=3&count=3&fcountry=87&gr=656&grMode=4&lng=en&ref=61&selectedMs=1.4,2.4,10.4",
    )
    inspect_1x(
        "1x_bball_pre",
        "https://1xbet.co.ke/service-api/main-line-feed/v3/games1x2?cfView=3&count=3&fcountry=87&gr=656&grMode=4&lng=en&ref=61&selectedMs=2.3,2.6",
    )
    inspect_1x(
        "1x_volley_pre",
        "https://1xbet.co.ke/service-api/main-line-feed/v3/games1x2?cfView=3&count=3&fcountry=87&gr=656&grMode=4&lng=en&ref=61&selectedMs=2.6",
    )
    inspect_1x(
        "1x_fb_live",
        "https://1xbet.co.ke/service-api/main-live-feed/v3/games1x2?cfView=3&count=3&fcountry=87&gr=656&grMode=4&lng=en&ref=61&selectedMs=2.1",
    )
    inspect_betika(
        "betika_tennis",
        "https://api.betika.com/v1/uo/matches?page=1&limit=3&tab=&sub_type_id=1,186,340&sport_id=28&sort_id=1&period_id=-1&esports=false",
    )
    inspect_betika(
        "betika_bball",
        "https://api.betika.com/v1/uo/matches?page=1&limit=3&tab=&sub_type_id=1,186,340&sport_id=30&sort_id=1&period_id=-1&esports=false",
    )
    inspect_betika(
        "betika_fb",
        "https://api.betika.com/v1/uo/matches?page=1&limit=8&sub_type_id=1,186,340&sport=1",
    )
    inspect_1x(
        "22_tennis_live",
        "https://22bet.co.ke/service-api/LiveFeed/Get1x2_VZip?sports=4&count=5&lng=en_GB&gr=216&mode=4&country=87&partner=151&getEmpty=true",
    )
    inspect_1x(
        "22_bball_live",
        "https://22bet.co.ke/service-api/LiveFeed/Get1x2_VZip?sports=3&count=5&lng=en_GB&gr=216&mode=4&country=87&partner=151&getEmpty=true",
    )
    inspect_1x(
        "22_volley_live",
        "https://22bet.co.ke/service-api/LiveFeed/Get1x2_VZip?sports=6&count=5&lng=en_GB&gr=216&mode=4&country=87&partner=151&getEmpty=true",
    )


if __name__ == "__main__":
    main()
