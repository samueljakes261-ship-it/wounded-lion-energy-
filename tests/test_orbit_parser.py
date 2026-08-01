from pathlib import Path

from parsers.orbit_parser import OrbitParser


def main():

    json_file = Path("simulator/output/orbit.json")

    raw_json = json_file.read_text(encoding="utf-8")

    parser = OrbitParser()

    matches = parser.parse(raw_json)

    print()

    print("=" * 60)

    print("ORBIT PARSER TEST")

    print("=" * 60)

    print()

    print(f"Matches Parsed: {len(matches)}")

    print()

    for match in matches:

        print(match)

        print()

    print("=" * 60)


if __name__ == "__main__":

    main()