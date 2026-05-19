"""IATI Corpus Access Probe (Layer 1).

A measurement probe: it samples IATI publisher document links, crawls them
politely, and reports how many resolve and are readable. It does NOT retain
documents and is NOT the corpus build (the retention boundary) and does NOT
assess document content (Layer 2). See README.md and the SIGNAL files.
"""

__all__: list[str] = []
