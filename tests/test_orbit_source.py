from sources.orbit_source import OrbitSource


def main():

    source = OrbitSource()

    raw_json = source.load()

    print()

    print("=" * 60)

    print("ORBIT SOURCE TEST")

    print("=" * 60)

    print()

    print(raw_json[:500])

    print()

    print("=" * 60)


if __name__ == "__main__":

    main()