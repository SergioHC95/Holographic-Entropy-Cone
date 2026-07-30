"""Check the database-wide facet and contraction representation contract."""

from hec.checks import (
    check_stored_facet_database_format,
    run_check,
)

if __name__ == "__main__":
    run_check(check_stored_facet_database_format())
