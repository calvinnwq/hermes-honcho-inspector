"""Read-only backend namespace for Honcho Inspector.

Slice 0 intentionally registers no routes and performs no network access.
"""

from fastapi import APIRouter

router = APIRouter()
