"""
db/base.py
----------
Declarative base for all SQLAlchemy ORM models.
Import Base here and subclass it in every model file.
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Shared declarative base. All ORM models inherit from this."""
    pass
