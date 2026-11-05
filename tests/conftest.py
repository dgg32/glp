"""pytest collects only the pytest-style tests here.

The other test_*.py files are scripts that do their work at import time, and several of them talk to the live
Stardog instance (test_load_gate.py even writes in a transaction it rolls back). Run those by hand, after a
release, never by collecting the whole folder: `.venv/bin/python tests/test_load_gate.py`.
"""
collect_ignore = [
    "test_load_gate.py",
    "test_mcp_server.py",
    "test_ontology_reasoning.py",
    "test_shapes_reasoning.py",
    "test_shapes_stardog.py",
    "test_snowflake_mcp_server.py",
]
collect_ignore_glob = ["stardog_smoke/*"]
