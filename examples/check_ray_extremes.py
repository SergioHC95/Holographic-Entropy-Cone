"""Check that each stored ray is full-rank extreme."""

from hec.checks import check_stored_rays, run_check

if __name__ == "__main__":
    run_check(check_stored_rays())
