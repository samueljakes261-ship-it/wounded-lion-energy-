from engine.normalizer import TeamNameNormalizer

normalizer = TeamNameNormalizer()

TEST_CASES = {

    # ----------------------------------------------------
    # ENGLISH
    # ----------------------------------------------------

    "manchester united": [

        "Manchester United",
        "Manchester United FC",
        "Man Utd",
        "Man United",
        "Manchester Utd",

    ],

    "manchester city": [

        "Manchester City",
        "Manchester City FC",
        "Man City",

    ],

    "tottenham hotspur": [

        "Tottenham",
        "Tottenham Hotspur",
        "Spurs",

    ],

    "liverpool": [

        "Liverpool",
        "Liverpool FC",
        "LIVERPOOL",

    ],

    # ----------------------------------------------------
    # FRANCE
    # ----------------------------------------------------

    "paris saint germain": [

        "PSG",
        "Paris SG",
        "Paris-Saint-Germain",

    ],

    # ----------------------------------------------------
    # ITALY
    # ----------------------------------------------------

    "inter milan": [

        "Inter",
        "Internazionale",
        "Inter Milan",

    ],

    # ----------------------------------------------------
    # GERMANY
    # ----------------------------------------------------

    "bayern munich": [

        "Bayern",
        "FC Bayern",
        "Bayern Munich",

    ],

    # ----------------------------------------------------
    # SPAIN
    # ----------------------------------------------------

    "atletico madrid": [

        "Atlético Madrid",
        "Atletico Madrid",

    ],

    # ----------------------------------------------------
    # PORTUGAL
    # ----------------------------------------------------

    "sporting cp": [

        "Sporting",
        "Sporting CP",

    ],

    # ----------------------------------------------------
    # TURKEY
    # ----------------------------------------------------

    "galatasaray": [

        "Galatasaray",
        "Gala",

    ],

    "fenerbahce": [

        "Fenerbahçe",
        "Fener",
        "Fenerbahce",

    ],

    "besiktas": [

        "Beşiktaş",
        "Besiktas JK",
        "Besiktas",

    ],

}

passed = 0
failed = 0

print("\n")
print("=" * 75)
print("           TEAM NORMALIZATION VALIDATION SUITE")
print("=" * 75)

for expected, variations in TEST_CASES.items():

    for variation in variations:

        result = normalizer.normalize(variation)

        if result == expected:

            print(f"✓ {variation:<30} -> {result}")
            passed += 1

        else:

            print(f"✗ {variation:<30} -> {result}")
            print(f"    Expected: {expected}")
            failed += 1

print("\n" + "=" * 75)

total = passed + failed

accuracy = (passed / total) * 100 if total else 0

print(f"Total Tests : {total}")
print(f"Passed      : {passed}")
print(f"Failed      : {failed}")
print(f"Accuracy    : {accuracy:.2f}%")

print("=" * 75)
