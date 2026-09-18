"""Single source of truth for the SDK's own version string.

Kept in its own module (rather than directly on `courtmesh/__init__.py`) so
that `_http.py` can import it for the `User-Agent` header without a circular
import: `courtmesh/__init__.py` imports `client.py`, which imports `_http.py`
before `__init__.py` has finished executing, so `_http.py` cannot import
`__version__` back from the partially initialized `courtmesh` package.
"""
__version__ = "0.4.0"
