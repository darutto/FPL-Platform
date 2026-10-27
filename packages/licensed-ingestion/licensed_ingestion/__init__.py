"""Production Sportmonks Starter ingestion job (football-intelligence PROD_INGESTION.md).

The only package that imports both ``sportmonks_client`` (network) and ``football_intelligence`` (derive,
crosswalk, store, distribution): the client stays lean and football-intelligence stays network-free. Nothing
in either imports this package (``tests/test_boundaries.py``).
"""
