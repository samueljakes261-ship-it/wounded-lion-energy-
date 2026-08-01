import json

INPUT_FILE = "decrypted_output.json"


def find_keys(obj, path=""):
    """
    Recursively print every key path in the JSON.
    Useful for locating where odds/markets are stored.
    """
    if isinstance(obj, dict):
        for k, v in obj.items():
            print(path + "/" + k)
            find_keys(v, path + "/" + k)
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            find_keys(item, path + f"[{i}]")


def main():
    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    print("=" * 80)
    print(f"Total events: {len(data)}")
    print("=" * 80)

    first = data[0]

    # Save the first event so you can upload it here
    with open("first_event.json", "w", encoding="utf-8") as f:
        json.dump(first, f, indent=2, ensure_ascii=False)

    print("✓ Saved first event to first_event.json\n")

    print("=" * 80)
    print("TOP LEVEL KEYS")
    print("=" * 80)

    for key in first.keys():
        print(key)

    print("\n" + "=" * 80)
    print("FULL KEY STRUCTURE")
    print("=" * 80)

    find_keys(first)

    print("\nDone.")


if __name__ == "__main__":
    main()