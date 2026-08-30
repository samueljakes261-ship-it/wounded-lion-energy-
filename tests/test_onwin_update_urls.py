"""
OnWin live-update URL matching.

The worker must treat both historically observed update endpoints as
live odds traffic. Matching only find_event_snapshots left the
collector frozen on the initial snapshot when the site posted
get_main_line_gap instead.
"""
from parsers.onwin.feed import OnwinFeed


def test_find_event_snapshots_is_an_update_url():
    assert OnwinFeed.is_update_url(
        "https://api.example/frontserver-erisgaming__api/rpc/"
        "sumstats.frontserver.command.find_event_snapshots.erisgaming"
    )


def test_get_main_line_gap_is_an_update_url():
    assert OnwinFeed.is_update_url(
        "https://api.example/frontserver-erisgaming__api/rpc/"
        "sumstats.frontserver.command.get_main_line_gap.erisgaming"
    )


def test_initial_get_main_line_is_not_an_update_url():
    assert not OnwinFeed.is_update_url(
        "https://api.example/frontserver-erisgaming__api/rpc/"
        "sumstats.frontserver.command.get_main_line.erisgaming"
    )


def test_unrelated_erisgaming_rpc_is_not_an_update_url():
    assert not OnwinFeed.is_update_url(
        "https://api.example/frontserver-erisgaming__api/rpc/"
        "sumstats.frontserver.command.translates.get_current_translates"
    )


def test_safe_url_path_strips_query_string():
    path = OnwinFeed.safe_url_path(
        "https://api.example/frontserver-erisgaming__api/rpc/"
        "sumstats.frontserver.command.get_main_line_gap.erisgaming"
        "?apikey=should-never-appear"
    )
    assert path.endswith("get_main_line_gap.erisgaming")
    assert "apikey" not in path
    assert "should-never-appear" not in path
