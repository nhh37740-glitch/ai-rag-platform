# data-facade

Database-domain composition root. `DataService(database_path)` creates and owns one SQLite connection and passes it with one shared lock to storage and memory implementations. It exposes account, quota, conversation, notebook/member and agent-data operations; all persisted state uses exactly six tables. Incompatible databases are rejected, and no prior data is migrated.
