# Hermes Memory

Production-ready memory layer for Hermes Agent. Persistent, score-ranked, graph-aware, Git-backed memory for multi-user AI assistants.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Hermes Agent Runtime                          │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────────┐   │
│  │   Memory     │  │   Retrieval  │  │      Knowledge Graph     │   │
│  │   Layer      │  │   Pipeline   │  │         Layer            │   │
│  └──────┬───────┘  └──────┬───────┘  └────────────┬─────────────┘   │
│         │                 │                      │                  │
│  ┌──────▼────────────────▼──────────────────────▼─────────────┐   │
│  │                       Persistence Layer                      │   │
│  │  ┌────────────────┐  ┌────────────────┐  ┌───────────────┐  │   │
│  │  │ JSON Storage   │  │   Scoring      │  │ Git Workflow  │  │   │
│  │  │ (Indexed)      │  │   Engine       │  │ (history +   │  │   │
│  │  │                │  │                │  │  rollback)    │  │   │
│  │  └────────────────┘  └────────────────┘  └───────────────┘  │   │
│  └─────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
```

### Core Concepts

- **Memory Events**: Every interaction creates scored, versioned memory entries.
- **Knowledge Graph**: Entities and relationships with ontology-driven typing.
- **Retrieval**: Multi-signal ranking (recency, importance, confidence, tags, graph proximity).
- **Git-backed**: Every write commit to Git for audit trail and rollback.
- **Multi-user**: Isolated per-user memory with cross-user relationship indexing.

## Folder Structure

```
hermes-memory/
├── README.md                 # This file
├── LICENSE                   # MIT License
├── .gitignore                # Git ignore rules
├── config/                   # Global configuration and rules
│   ├── memory_config.json    # System settings, retention, limits
│   ├── graph_rules.json      # Relationship types and edge constraints
│   ├── scoring.json          # Ranking weights and thresholds
│   └── retrieval.json        # Retrieval pipeline behavior
├── users/                    # Per-user memory data
│   └── {user_id}/            # e.g., u_default / u_alice
│       ├── profile.json      # User preferences and metadata
│       ├── facts.json        # Extracted facts about the user
│       ├── preferences.json  # Learned preferences
│       ├── goals.json        # User goals with optional deadlines
│       ├── projects.json     # Active and backlog projects
│       ├── sessions.json     # Conversation sessions
│       ├── summaries.json    # Session and daily summaries
│       └── relationships.json # User-specific relationship links
├── graph/                    # Global knowledge graph
│   ├── nodes.json            # Entity nodes (users, topics, objects)
│   ├── edges.json            # Relationship edges
│   └── ontology.json         # Type definitions and inference rules
├── index/                    # Search and retrieval indexes
│   ├── keyword_index.json    # Full-text keyword lookup
│   ├── tag_index.json        # Tag-to-memory mapping
│   ├── entity_index.json     # Entity-to-memory mapping
│   └── relationship_index.json # Relationship query index
├── logs/                     # Append-only event logs
│   ├── interactions.json     # Raw Hermes interaction log
│   └── memory_events.json    # Memory CRUD and lifecycle events
├── src/                      # Source modules
│   ├── memory/               # Memory core operations
│   ├── graph/                # Graph management
│   ├── retrieval/            # Query and ranking
│   ├── scoring/              # Score computation
│   ├── summarizer/           # Session and batch summarization
│   ├── storage/              # JSON persistence layer
│   ├── git/                  # Git workflow integration
│   └── utils/                # Shared utilities
├── tests/                    # Unit and integration tests
└── examples/                 # Example scripts and usage samples
```

## Memory Schema

All memory records share a common core schema:

```json
{
  "id": "mem_20250101_000001",
  "timestamp": "2025-01-01T12:00:00Z",
  "last_updated": "2025-01-01T12:00:00Z",
  "importance": 0.85,
  "confidence": 0.92,
  "tags": ["project", "deadline", "alpha"],
  "source": "user_statement",
  "type": "fact",
  "status": "active",
  "version": 1,
  "payload": { ... }
}
```

### Record Fields

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Unique identifier (prefix indicates type: `mem_`, `fact_`, `rel_`, `evt_`) |
| `timestamp` | ISO 8601 | When the memory was first created |
| `last_updated` | ISO 8601 | When the memory was last modified |
| `importance` | float 0.0 - 1.0 | Intrinsic priority (user-declared or inferred) |
| `confidence` | float 0.0 - 1.0 | Certainty level (source reliability, corroboration) |
| `tags` | array[string] | Categorical labels for filtering |
| `source` | string | Origin: `user_statement`, `inferred`, `system`, `external_api` |
| `type` | string | `fact`, `preference`, `session`, `summary`, `relationship`, `event` |
| `status` | string | `active`, `archived`, `pending`, `superseded` |
| `version` | int | Monotonically increasing revision number |
| `payload` | object | Type-specific data |

### Common Types

- **fact**: User-declared or inferred facts (name, birthday, job).
- **preference**: Learned or stated preferences (format, tone, schedule).
- **session**: Conversation session metadata and turns.
- **summary**: Condensed representations of sessions or time windows.
- **relationship**: Entity-entity connections from the graph layer.
- **event**: System or lifecycle events (mem_created, mem_updated, summary_triggered).

## Knowledge Graph

### Nodes

```json
{
  "id": "node_001",
  "type": "user|topic|object|event|location",
  "label": "Alice",
  "properties": {},
  "created_at": "...",
  "last_seen": "..."
}
```

### Edges

```json
{
  "id": "edge_001",
  "source": "node_001",
  "target": "node_002",
  "type": "knows|works_at|likes|mentions|located_in",
  "weight": 0.9,
  "confidence": 0.8,
  "since": "...",
  "properties": {}
}
```

### Ontology

`graph/ontology.json` defines:
- Valid node and edge types
- Property schemas
- Inference rules (e.g., `friend_of` suggests `knows`)
- Symmetric/asymmetric relationship flags
- Transitivity rules

Edges violating `graph_rules.json` are rejected at write time.

## Retrieval Pipeline

Retrieval runs in multiple stages:

1. **Candidate Generation**: Match keywords, tags, entities from query.
2. **Graph Expansion**: Include related nodes/edges from knowledge graph.
3. **Scoring**: Blend recency, importance, confidence, and tag match scores using weights from `config/retrieval.json`.
4. **Cutoff**: Enforce per-query and per-user limits from `config/memory_config.json`.
5. **Ranking**: Sort by final score, return top-k results.

Query inputs:
- Natural language query string
- Optional filter dict: `{ "status": "active", "source": "user_statement" }`
- Optional tag list
- Optional entity IDs for graph traversal

## Git Workflow

- Every memory mutation triggers a Git commit.
- Branches: `main` for committed state; ephemeral branches for bulk rebuilds.
- Commit messages follow: `memory: <action> <type> <id> [user:<user_id>]`
  - Example: `memory: create fact mem_20250101_000001 [user:u_alice]`
- Old legacy `core.py` is intentionally excluded from this scaffolding. Do not delete without explicit instruction.
- Batch commits are throttled to avoid noisy history; prefer bundling related writes before committing.

## Coding Standards

- **Python**: PEP 8, type hints, docstrings.
- **JSON**: Validated against inline schemas; no trailing commas.
- **Naming**: snake_case for modules, camelCase avoided in JSON.
- **Immutability**: Do not mutate records in place; create new versions.
- **Idempotency**: Retry-safe writes using deterministic IDs.
- **Testing**: Unit tests for scoring and retrieval in `tests/`.

## Examples

See `examples/` for:
- Adding a memory entry
- Searching with filters
- Graph relationship creation
- Scoring weight adjustment

## Future Hermes Agent Usage

1. Read `config/memory_config.json` for runtime limits.
2. Write records using the schemas above (never invent new fields).
3. Query through `src/retrieval/`; do not read index files directly.
4. Commit via `src/git/` after every write batch.
5. Validate JSON with provided schemas before staging.
6. Log every interaction to `logs/interactions.json` and `logs/memory_events.json`.

This repository is the source of truth for Hermes persistent memory.
