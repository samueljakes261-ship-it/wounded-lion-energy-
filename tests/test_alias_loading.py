from resources.aliases import TEAM_ALIASES

print("=" * 60)
print("ALIAS LOADING TEST")
print("=" * 60)

print(f"Total aliases loaded: {len(TEAM_ALIASES)}")
print()

for key in [
    "bayern",
    "fc bayern",
    "gala",
    "fener",
    "besiktas jk",
    "psg",
    "inter",
]:
    print(f"{key:<20} -> {TEAM_ALIASES.get(key)}")