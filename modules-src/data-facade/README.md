# data-facade

Database intermediate module. Consumers import only DataService and the shared specifications.
It composes memory.MemoryStore and storage.SqliteVectorStore/StateStore, owns their connections,
and exposes shared interfaces. Build delivery is a Cython .pyd/.so.

Source and compiled D01-D05 tests are replayed by scripts/run_tests.py --group facade.

0.2.0: notebook directory business and relational NotebookStore lifecycle; imports only shared ports and memory/storage, never auth business implementations.
