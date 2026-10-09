# Changelog

## [0.1.0]
- Add DataService database domain composition through shared ports.
- Lazily create and reuse memory/vector/state stores with persistent SQLite defaults.
- Release all owned connections on close, guard use after close and clean up failed initialization.
