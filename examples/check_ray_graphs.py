"""Check that each stored graph realizes the ray at the same list position."""

from hec.checks import check_stored_graphs, run_check

if __name__ == "__main__":
    run_check(check_stored_graphs())
