"""
api/dependencies.py
-------------------
Shared FastAPI dependencies injected via Depends().
"""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from db.session import get_db

# Convenience type alias for route function signatures
DbSession = Annotated[Session, Depends(get_db)]
