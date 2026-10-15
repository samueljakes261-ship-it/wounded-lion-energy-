"""Sanitized Kenyan multi-sport payload summaries. No secrets, no raw dumps."""
from __future__ import annotations

import json
from collections import Counter

from kenyan.http_utils import fetch_json


def _safe(obj, depth=0):
    if depth > 3:
        return type(obj).__name__
    if isinstance(obj, dict):
        return {k: _safe(v, depth + 1) for k, v in list(obj.items())[:20]}
    if isinstance(obj, list):
        return [_safe(obj[0], depth + 1)] if obj else []
    if isinstance(obj, (int, float, bool)) or obj is None:
        return obj
    text = str(obj)
    return text[:80]


def summarize(label, url, kind):
    result = fetch_json(url, timeout=20)
    out = {
        "label": label,
        "host_path": url.split("?")[0],
        "ok": result.ok,
        "http": result.status_code,
        "bytes": result.response_size_bytes,
        "error": result.error,
        "json_type": type(result.json_body).__name__ if result.json_body is not None else None,
    }
    body = result.json_body
    if not result.ok or body is None:
        print(json.dumps(out, ensure_ascii=True))
        return out

    if kind == "betika":
        rows = (body or {}).get("data") or []
        sports = Counter((r.get("sport_id"), r.get("sport_name")) for r in rows if isinstance(r, dict))
        markets = Counter()
        sample_markets = []
        for row in rows:
            for market in row.get("odds") or []:
                if not isinstance(market, dict):
                    continue
                key = (str(market.get("sub_type_id")), market.get("name"))
                markets[key] += 1
                if len(sample_markets) < 8:
                    outcomes = market.get("odds") or []
                    sample_markets.append({
                        "sub_type_id": market.get("sub_type_id"),
                        "name": market.get("name"),
                        "outcome_ids": [o.get("outcome_id") for o in outcomes if isinstance(o, dict)][:6],
                        "odd_keys": [o.get("odd_key") for o in outcomes if isinstance(o, dict)][:6],
                        "display": [o.get("display") or o.get("outcome_name") for o in outcomes if isinstance(o, dict)][:6],
                        "keys": sorted(market.keys()),
                        "outcome_keys": sorted(outcomes[0].keys()) if outcomes and isinstance(outcomes[0], dict) else [],
                    })
        meta = body.get("meta") or {}
        out.update({
            "events": len(rows),
            "sports": {f"{k[0]}:{k[1]}": n for k, n in sports.items()},
            "markets": {f"{k[0]}:{k[1]}": n for k, n in markets.most_common(20)},
            "meta_total": meta.get("total"),
            "meta_limit": meta.get("limit") or meta.get("per_page"),
            "sample_markets": sample_markets,
            "event_keys": sorted(rows[0].keys()) if rows else [],
        })
    elif kind == "1x":
        events = body if isinstance(body, list) else (body.get("Value") if isinstance(body, dict) else [])
        events = events if isinstance(events, list) else []
        sports = Counter()
        groups = Counter()
        types = Counter()
        sample = None
        for event in events:
            if not isinstance(event, dict):
                continue
            if "eventGroups" in event:
                sid = (event.get("sport") or {}).get("id")
                sname = (event.get("sport") or {}).get("name")
                sports[(sid, sname)] += 1
                for group in event.get("eventGroups") or []:
                    groups[group.get("groupId")] += 1
                    for wrapper in group.get("events") or []:
                        for item in wrapper if isinstance(wrapper, list) else []:
                            if isinstance(item, dict):
                                types[(group.get("groupId"), item.get("type"), item.get("param"), item.get("name"))] += 1
                if sample is None:
                    sample = {
                        "id": event.get("id"),
                        "sport": event.get("sport"),
                        "home": (event.get("opponent1") or {}).get("fullName"),
                        "away": (event.get("opponent2") or {}).get("fullName"),
                        "periodName": event.get("periodName"),
                        "groupIds": [g.get("groupId") for g in (event.get("eventGroups") or []) if isinstance(g, dict)],
                    }
            else:
                sid = event.get("SI")
                sname = event.get("SN")
                sports[(sid, sname)] += 1
                for item in event.get("E") or []:
                    if isinstance(item, dict):
                        groups[item.get("G")] += 1
                        types[(item.get("G"), item.get("T"), item.get("P"), item.get("N"))] += 1
                if sample is None:
                    sample = {
                        "I": event.get("I"),
                        "SI": sid,
                        "SN": sname,
                        "O1": event.get("O1"),
                        "O2": event.get("O2"),
                        "groups": sorted({e.get("G") for e in (event.get("E") or []) if isinstance(e, dict)}),
                    }
        out.update({
            "events": len(events),
            "sports": {f"{k[0]}:{k[1]}": n for k, n in sports.items()},
            "groups": dict(groups.most_common(15)),
            "type_samples": [
                {"G": a, "T": b, "P": c, "N": d, "n": n}
                for (a, b, c, d), n in types.most_common(25)
            ],
            "sample": sample,
        })
    elif kind == "22zip":
        values = (body or {}).get("Value") if isinstance(body, dict) else []
        values = values if isinstance(values, list) else []
        if values and isinstance(values[0], dict) and "E" not in values[0] and "O1" not in values[0]:
            out.update({
                "nav_only": True,
                "value_len": len(values),
                "sample": {k: values[0].get(k) for k in ("I", "N", "C") if k in values[0]},
                "names": [(v.get("I"), v.get("N")) for v in values[:20] if isinstance(v, dict)],
            })
        else:
            return summarize(label, url, "1x")
    print(json.dumps(out, ensure_ascii=True, default=str))
    return out


def main():
    jobs = [
        ("1x_tennis_pre", "https://1xbet.co.ke/service-api/main-line-feed/v3/games1x2?cfView=3&count=40&fcountry=87&gr=656&grMode=4&lng=en&ref=61&selectedMs=1.4,2.4,10.4", "1x"),
        ("1x_bball_live", "https://1xbet.co.ke/service-api/main-live-feed/v3/games1x2?cfView=3&count=40&fcountry=87&gr=656&grMode=4&lng=en&ref=61&selectedMs=1.3,2.3,10.3", "1x"),
        ("1x_bball_pre", "https://1xbet.co.ke/service-api/main-line-feed/v3/games1x2?cfView=3&count=40&fcountry=87&gr=656&grMode=4&lng=en&ref=61&selectedMs=2.3,2.6", "1x"),
        ("1x_volley_live", "https://1xbet.co.ke/service-api/main-live-feed/v3/games1x2?cfView=3&count=40&fcountry=87&gr=656&grMode=4&lng=en&ref=61&selectedMs=2.6", "1x"),
        ("1x_volley_pre", "https://1xbet.co.ke/service-api/main-line-feed/v3/games1x2?cfView=3&count=40&fcountry=87&gr=656&grMode=4&lng=en&ref=61&selectedMs=2.6", "1x"),
        ("1x_tennis_live_games", "https://1xbet.co.ke/service-api/main-live-feed/v3/games1x2?cfView=3&count=40&fcountry=87&gr=656&grMode=4&lng=en&ref=61&selectedMs=1.4,2.4,10.4", "1x"),
        ("betika_tennis", "https://api.betika.com/v1/uo/matches?page=1&limit=10&tab=&sub_type_id=1,186,340&sport_id=28&sort_id=1&period_id=-1&esports=false", "betika"),
        ("betika_bball", "https://api.betika.com/v1/uo/matches?page=1&limit=10&tab=&sub_type_id=1,186,340&sport_id=30&sort_id=1&period_id=-1&esports=false", "betika"),
        ("betika_volley", "https://api.betika.com/v1/uo/matches?page=1&limit=10&tab=&sub_type_id=1,186,340&sport_id=35&sort_id=1&period_id=-1&esports=false", "betika"),
        ("betika_fb_pre", "https://api.betika.com/v1/uo/matches?page=1&limit=5&sub_type_id=1,186,340&sport=1", "betika"),
        ("22_sports", "https://22bet.co.ke/service-api/LineFeed/GetSportsShortZip?lng=en&virtualSports=true", "22zip"),
        ("22_tennis", "https://22bet.co.ke/service-api/LineFeed/Get1x2_VZip?sports=4&count=50&lng=en_GB&tz=3&mode=4&country=87&partner=151&getEmpty=true&gr=216", "1x"),
        ("22_bball", "https://22bet.co.ke/service-api/LineFeed/Get1x2_VZip?sports=3&count=50&lng=en_GB&tz=3&mode=4&country=87&partner=151&getEmpty=true&gr=216", "1x"),
        ("22_volley", "https://22bet.co.ke/service-api/LineFeed/Get1x2_VZip?sports=6&count=50&lng=en_GB&tz=3&mode=4&country=87&partner=151&getEmpty=true&gr=216", "1x"),
        ("22_tennis_live", "https://22bet.co.ke/service-api/LiveFeed/Get1x2_VZip?sports=4&count=50&lng=en_GB&gr=216&mode=4&country=87&partner=151&getEmpty=true", "1x"),
    ]
    for label, url, kind in jobs:
        try:
            summarize(label, url, kind)
        except Exception as exc:  # noqa: BLE001
            print(json.dumps({"label": label, "error": f"{type(exc).__name__}: {exc}"}))


if __name__ == "__main__":
    main()
