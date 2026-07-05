# hermes-memory

Scaffolded memory storage layout for Hermes, containing user profiles, facts, session indexing, global rules, and raw append-only logs.

## Layout

```
hermes-memory/
├── users/{user_id}/
│   ├── profile.json
│   ├── facts.json
│   └── sessions.json
├── system/
│   ├── summaries.json
│   └── global_rules.json
├── index/
│   ├── keywords.json
│   └── tags.json
├── logs/
│   └── raw.json
└── README.md
```

## File Contract

- `users/{user_id}/profile.json`: user identity, preferences, version
- `users/{user_id}/facts.json`: durable user facts with confidence and expiry
- `users/{user_id}/sessions.json`: lightweight session ledger with topic, status, and summary pointer
- `system/summaries.json`: generated session summaries with keywords and tags
- `system/global_rules.json`: prioritized rule set for indexing and retrieval
- `index/keywords.json`: optional inverted keyword index
- `index/tags.json`: tag-to-session mapping
- `logs/raw.json`: append-only raw ingest/error log

## Usage Notes

- `{user_id}` should be replaced by an actual identifier before use.
- Each JSON file includes a JSON Schema draft-07 `$schema` block for structure validation.
- This repo is intentionally behavior-free for now. Implement read/write logic in JS/Python later.
