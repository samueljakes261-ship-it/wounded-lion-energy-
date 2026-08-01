import random


class PriceEngine:
    """
    Generates realistic bookmaker prices from true probabilities.

    Every bookmaker has a slight pricing personality.

    Orbit      -> slightly stronger Home prices
    Betfair    -> slightly stronger Draw prices
    Kolay90    -> slightly stronger Away prices
    Novel34    -> balanced
    BetKanyon  -> balanced
    OnWin      -> balanced
    """

    def generate_prices(

        self,

        home_probability,
        draw_probability,
        away_probability,

        margin=0.05,
        variance=0.02,

        bookmaker=None,

    ):

        probabilities = [

            home_probability,
            draw_probability,
            away_probability,

        ]

        odds = []

        for probability in probabilities:

            adjusted_probability = probability * (1 + margin)

            price = 1 / adjusted_probability

            factor = random.uniform(

                1 - variance,
                1 + variance

            )

            price *= factor

            odds.append(price)

        #
        # Bookmaker personalities
        #

        if bookmaker == "Orbit":

            odds[0] *= 1.03

        elif bookmaker == "Betfair":

            odds[1] *= 1.03

        elif bookmaker == "Kolay90":

            odds[2] *= 1.03

        elif bookmaker == "Novel34":

            odds[0] *= 1.01
            odds[2] *= 1.01

        elif bookmaker == "BetKanyon":

            odds[1] *= 1.01

        elif bookmaker == "OnWin":

            odds[0] *= 1.015

        return (

            round(odds[0], 2),
            round(odds[1], 2),
            round(odds[2], 2),

        )