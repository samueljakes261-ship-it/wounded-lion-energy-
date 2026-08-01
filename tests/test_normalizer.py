from engine.normalizer import TeamNameNormalizer

normalizer = TeamNameNormalizer()

examples = [

    "Liverpool FC",
    "Paris-Saint-Germain",
    "PSG",
    "Man Utd",
    "Internazionale",
    "FC Bayern München",
    "Atlético Madrid",
    "Sporting",
    "Besiktas JK",
]

for team in examples:

    print("=" * 70)

    normalizer.normalize(team, debug=True)

    print("=" * 70)