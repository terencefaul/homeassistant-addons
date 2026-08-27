"""Portable core for Gate PIN.

Nothing in this package may import FastAPI, or anything that assumes the
Home Assistant Supervisor is present. That constraint is what makes a future
custom-integration wrapper a packaging job rather than a rewrite, and it is
enforced by tests/test_portability.py.
"""
