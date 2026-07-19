"""Backward-compatible import surface for older modules."""
from core.ai_client import AIClient, get_client, reset_client

__all__ = ["AIClient", "get_client", "reset_client"]
