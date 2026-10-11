# storage

SQLite persistence for the six-table database domain. DataService owns one connection and injects it into stores. Vectors and state use `documents` and `agent_data`; notebook data uses the users/notebooks/member tables. Embeddings are JSON and ranked by a finite-vector dot product. Existing databases with any other table layout or constraints are rejected without migration.
