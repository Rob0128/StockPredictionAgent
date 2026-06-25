"""Data clients for public market inputs.

All clients are written to *degrade gracefully*: if an API key is missing,
the network is unavailable, or cache-only mode is set, they return empty/neutral
data and append a warning rather than raising. This keeps the daily workflow
robust and makes offline dry-runs possible.
"""
