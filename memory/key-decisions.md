# Key Decisions

## [2026-04-21] D-001: Qdrant Is The Only Vector Backend
- Plan: v5.0
- Context: The migration goal is to move RAG data out of SQLite without preserving legacy sqlite-vec compatibility.
- Options considered:
  - Keep sqlite-vec as a fallback backend behind a shared interface.
  - Make Qdrant the only vector backend and provide explicit migration/reindex commands for existing projects.
- Decision: Make Qdrant the only vector backend.
- Rationale: A single backend keeps the code easier to reason about and avoids fitting the new architecture to the old API.
- Consequences: Existing projects must reindex graph nodes into Qdrant before semantic retrieval is complete.

## [2026-04-21] D-002: Pin Qdrant Client To 1.12.0
- Plan: v5.0
- Context: `qdrant-client==1.17.1` requires NumPy 2.1+, while this project pins NumPy 1.26.4.
- Options considered:
  - Upgrade NumPy and risk the Transformers/Torch compatibility surface.
  - Use an older Qdrant client release that supports local mode and the existing NumPy pin.
- Decision: Pin `qdrant-client==1.12.0`.
- Rationale: It keeps the migration focused on vector storage without forcing a broader ML dependency upgrade.
- Consequences: Future work can revisit the client pin when the project is ready to move to NumPy 2.x.
