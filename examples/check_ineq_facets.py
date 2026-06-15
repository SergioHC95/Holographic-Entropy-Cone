"""Check that each stored inequality is a full-rank facet."""

from hec.checks import check_stored_facets, run_check

if __name__ == "__main__":
    run_check(check_stored_facets())
