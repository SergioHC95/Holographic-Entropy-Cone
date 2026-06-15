"""Check that each stored contraction proves the inequality at the same list position."""

from hec.checks import check_stored_contractions, run_check

if __name__ == "__main__":
    run_check(check_stored_contractions())
