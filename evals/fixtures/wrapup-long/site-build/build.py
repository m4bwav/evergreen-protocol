"""Fixture build script for the evergreen eval suite (case action-6). Builds nothing; prints what a build would."""
import argparse

p = argparse.ArgumentParser(description="Build the docs site and check its links.")
g = p.add_mutually_exclusive_group(required=True)
g.add_argument("--all", action="store_true", help="rebuild every page (about 4 minutes)")
g.add_argument("--changed", action="store_true", help="rebuild only pages changed since the last build, plus pages linking to them (seconds)")
a = p.parse_args()
print("built 120 pages in 236 s" if a.all else "built 3 changed pages in 2 s")
print("link check: 0 broken links left")
