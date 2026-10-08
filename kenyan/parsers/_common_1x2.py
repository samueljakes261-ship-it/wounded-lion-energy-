"""
Shared "type-numbered 1X2" extraction logic for 1xBet and 22Bet.

Both bookmakers are built on the same underlying odds-provider
platform (1xCorp/Melbet family) and use the SAME numeric market/outcome
convention, confirmed by live inspection (see kenyan/README-style notes
in onexbet_parser.py / bet22_parser.py):

    outcome type 1 = HOME
    outcome type 2 = DRAW
    outcome type 3 = AWAY
    group id 1     = the main full-match 1X2 market

Two different payload shapes were observed carrying this same
convention:

  1. "flat" shape -- a single `E` (or nested `AE`) list of
     `{"T": <type>, "C": <price>, "G": <group>, "B": <blocked?>}` dicts.
     Seen on: 1xBet prematch fallback, 22Bet live, 22Bet prematch.

  2. "grouped" shape -- an `eventGroups` list of
     `{"groupId": <group>, "events": [[{...}], [{...}], [{...}]]}`,
     where each of the 3 inner single-item lists holds one outcome.
     Seen on: 1xBet live.

Cluster rule: HOME/DRAW/AWAY of a single KenyanMatchOdds record must
come from ONE groupId==1 cluster. A later type-1/2/3 row in the same
payload is a different cluster and must not overwrite the first
complete 1X2 triple (the previous last-write-wins behaviour mixed
full-match prices with period/special 1X2 prices).
"""
from kenyan.odds import parse_decimal_odds

MAIN_1X2_GROUP_ID = 1
OUTCOME_TYPES = (1, 2, 3)


def _cluster_record(prices, *, group_id, cluster_index):
    return {
        "prices": dict(prices),
        "group_id": group_id,
        "cluster_index": cluster_index,
        "cluster_id": f"g{group_id}:c{cluster_index}",
        "market_id": str(group_id),
    }


def is_complete_1x2(prices: dict) -> bool:
    return all(outcome in prices for outcome in OUTCOME_TYPES)


def extract_1x2_clusters_from_flat_events(events) -> list:
    """
    Walk the raw `E` list in order. Each complete G==1 type 1/2/3
    triple is one cluster. A repeated type starts a new cluster rather
    than overwriting the previous price.
    """
    clusters = []
    current = {}
    cluster_index = 0

    if not isinstance(events, list):
        return clusters

    for item in events:
        if not isinstance(item, dict):
            continue
        if item.get("G") != MAIN_1X2_GROUP_ID:
            continue
        outcome_type = item.get("T")
        if outcome_type not in OUTCOME_TYPES:
            continue
        if item.get("B"):
            continue
        price = parse_decimal_odds(item.get("C"))
        if price is None:
            continue
        if outcome_type in current:
            if is_complete_1x2(current):
                clusters.append(
                    _cluster_record(
                        current,
                        group_id=MAIN_1X2_GROUP_ID,
                        cluster_index=cluster_index,
                    )
                )
                cluster_index += 1
            current = {}
        current[outcome_type] = price

    if is_complete_1x2(current):
        clusters.append(
            _cluster_record(
                current,
                group_id=MAIN_1X2_GROUP_ID,
                cluster_index=cluster_index,
            )
        )
    return clusters


def extract_1x2_from_flat_events(events) -> dict:
    """First complete G==1 1X2 cluster only. Empty dict if none."""
    clusters = extract_1x2_clusters_from_flat_events(events)
    return dict(clusters[0]["prices"]) if clusters else {}


def _price_from_grouped_item(item):
    if not isinstance(item, dict):
        return None
    if item.get("blocked"):
        return None
    outcome_type = item.get("type")
    if outcome_type not in OUTCOME_TYPES:
        return None
    price = parse_decimal_odds(item.get("cf"))
    if price is None:
        return None
    return outcome_type, price


def _clusters_from_aligned_wrappers(wrappers, group_id):
    """
    When the first three inner lists are HOME/DRAW/AWAY (any order)
    and share a length, index i across those lists is one cluster.
    """
    type_to_wrapper = {}
    for wrapper in wrappers[:3]:
        first = None
        for item in wrapper:
            parsed = _price_from_grouped_item(item)
            if parsed is None:
                continue
            first = parsed
            break
        if first is None:
            return []
        outcome_type, _price = first
        if outcome_type in type_to_wrapper:
            return []
        type_to_wrapper[outcome_type] = wrapper

    if set(type_to_wrapper) != set(OUTCOME_TYPES):
        return []

    lengths = [len(type_to_wrapper[outcome]) for outcome in OUTCOME_TYPES]
    if min(lengths) < 1:
        return []

    clusters = []
    for index in range(min(lengths)):
        prices = {}
        for outcome_type in OUTCOME_TYPES:
            parsed = _price_from_grouped_item(type_to_wrapper[outcome_type][index])
            if parsed is None:
                prices = {}
                break
            parsed_type, price = parsed
            if parsed_type != outcome_type:
                prices = {}
                break
            prices[outcome_type] = price
        if is_complete_1x2(prices):
            clusters.append(
                _cluster_record(prices, group_id=group_id, cluster_index=index)
            )
    return clusters


def _clusters_from_sequential_wrappers(wrappers, group_id):
    clusters = []
    current = {}
    cluster_index = 0
    for wrapper in wrappers:
        if not isinstance(wrapper, list):
            continue
        for item in wrapper:
            parsed = _price_from_grouped_item(item)
            if parsed is None:
                continue
            outcome_type, price = parsed
            if outcome_type in current:
                if is_complete_1x2(current):
                    clusters.append(
                        _cluster_record(
                            current,
                            group_id=group_id,
                            cluster_index=cluster_index,
                        )
                    )
                    cluster_index += 1
                current = {}
            current[outcome_type] = price
    if is_complete_1x2(current):
        clusters.append(
            _cluster_record(
                current,
                group_id=group_id,
                cluster_index=cluster_index,
            )
        )
    return clusters


def extract_1x2_clusters_from_event_groups(event_groups) -> list:
    """
    Return complete groupId==1 clusters in payload order. Only the
    first groupId==1 block is considered (that is the main 1X2 market
    on observed 1xBet live payloads).
    """
    if not isinstance(event_groups, list):
        return []

    for group in event_groups:
        if not isinstance(group, dict) or group.get("groupId") != MAIN_1X2_GROUP_ID:
            continue
        wrappers = [
            wrapper
            for wrapper in (group.get("events") or [])
            if isinstance(wrapper, list)
        ]
        aligned = _clusters_from_aligned_wrappers(wrappers, MAIN_1X2_GROUP_ID)
        # Parallel HOME/DRAW/AWAY lists are the 3-wrapper shape. Extra
        # wrappers after that are additional sequential clusters and
        # must not be silently dropped by the aligned path.
        if aligned and len(wrappers) <= 3:
            return aligned
        sequential = _clusters_from_sequential_wrappers(wrappers, MAIN_1X2_GROUP_ID)
        if sequential:
            return sequential
        return aligned

    return []


def extract_1x2_from_event_groups(event_groups) -> dict:
    """First complete groupId==1 1X2 cluster only. Empty dict if none."""
    clusters = extract_1x2_clusters_from_event_groups(event_groups)
    return dict(clusters[0]["prices"]) if clusters else {}
