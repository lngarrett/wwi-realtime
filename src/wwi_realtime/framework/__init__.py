"""Framework module for arc hierarchy, events, and sources."""

from wwi_realtime.framework.schema import (
    create_schema,
    get_connection,
    SCHEMA_VERSION,
)

__all__ = ["create_schema", "get_connection", "SCHEMA_VERSION"]
