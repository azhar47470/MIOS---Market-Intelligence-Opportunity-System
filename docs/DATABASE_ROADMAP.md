# Database Roadmap

Current repositories use JSON files only as development adapters behind application ports.

Production storage should move to:

- PostgreSQL for decision journals, engine outputs, configuration metadata, and audit records.
- Redis for current snapshot, health state, and short-lived cache entries.
- Time-series storage for candles, macro observations, and derived features.
- Object storage for generated reports and research artifacts.
- Graph storage for entity relationships and market-memory links.

Business logic must continue depending on repository interfaces, not storage engines.

