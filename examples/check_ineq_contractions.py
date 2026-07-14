"""Check that each stored contraction proves the inequality at the same list position."""

import argparse

from hec.checks import check_stored_contractions, run_check


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n", type=int, help="check only data for this number of parties")
    args = parser.parse_args()
    run_check(check_stored_contractions(n=args.n))


if __name__ == "__main__":
    main()
