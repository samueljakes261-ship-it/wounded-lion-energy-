from simulator.profiles.orbit_profile import (
    TEAM_ALIASES as ORBIT_TEAMS,
    COMPETITION_ALIASES as ORBIT_COMPETITIONS,
)

from simulator.profiles.betfair_profile import (
    TEAM_ALIASES as BETFAIR_TEAMS,
    COMPETITION_ALIASES as BETFAIR_COMPETITIONS,
)


class ProfileManager:

    PROFILES = {

        "Orbit": {
            "teams": ORBIT_TEAMS,
            "competitions": ORBIT_COMPETITIONS
        },

        "Betfair": {
            "teams": BETFAIR_TEAMS,
            "competitions": BETFAIR_COMPETITIONS
        }

    }

    @classmethod
    def get_profile(cls, bookmaker):

        return cls.PROFILES[bookmaker]