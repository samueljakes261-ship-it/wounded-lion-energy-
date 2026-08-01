from datetime import datetime

from engine.match_finder import MatchFinder
from models.match import MatchOdds

finder = MatchFinder()

orbit_matches = [

    MatchOdds(
        bookmaker="Orbit",
        competition="Premier League",
        sport="Football",
        market="1X2",
        home_team="Liverpool",
        away_team="Chelsea",
        home_odds=2.15,
        draw_odds=3.40,
        away_odds=3.60,
        start_time=datetime.now(),
        collected_at=datetime.now(),
    ),

    MatchOdds(
        bookmaker="Orbit",
        competition="Premier League",
        sport="Football",
        market="1X2",
        home_team="Arsenal",
        away_team="Tottenham",
        home_odds=2.10,
        draw_odds=3.20,
        away_odds=3.70,
        start_time=datetime.now(),
        collected_at=datetime.now(),
    ),

]

betfair_matches = [

    MatchOdds(
        bookmaker="Betfair",
        competition="Premier League",
        sport="Football",
        market="1X2",
        home_team="Liverpool FC",
        away_team="Chelsea FC",
        home_odds=2.20,
        draw_odds=3.45,
        away_odds=3.55,
        start_time=datetime.now(),
        collected_at=datetime.now(),
    ),

    MatchOdds(
        bookmaker="Betfair",
        competition="Bundesliga",
        sport="Football",
        market="1X2",
        home_team="Bayern",
        away_team="Dortmund",
        home_odds=1.90,
        draw_odds=3.80,
        away_odds=4.20,
        start_time=datetime.now(),
        collected_at=datetime.now(),
    ),

]

matches = finder.find_matches(
    orbit_matches,
    betfair_matches
)

print("\nMatched Events\n")

for event in matches:

    print(f"Sport       : {event.sport}")
    print(f"Competition : {event.competition}")
    print(f"Market      : {event.market}")
    print(f"Event       : {event.home_team} vs {event.away_team}")

    print("\nBookmakers:")

    for match in event.matches:

        print(
            f"  • {match.bookmaker}"
        )

        print(
            f"    Odds: "
            f"{match.home_odds} | "
            f"{match.draw_odds} | "
            f"{match.away_odds}"
        )

    print("-" * 60)