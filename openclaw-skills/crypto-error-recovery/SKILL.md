---
name: crypto-error-recovery
description: Recover temporary Monatise cryptocurrency provider and workflow failures with bounded retries, backoff, deduplication, incident logs, and dead-letter handling.
---
# Crypto Error Recovery
Retry transient failures with exponential backoff and rate-limit respect. Do not retry authentication or subscription errors indefinitely. Preserve IDs, prevent duplicates, and return NO_TRADE rather than a directional signal when recovery fails.

