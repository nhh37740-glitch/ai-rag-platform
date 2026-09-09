# INTERFACE

- `Storage.memory_write/get/search/forget(ctx, namespace, ...)`
- `Storage.add_documents(source_id, chunks, embeddings)` / `search_documents(query_embedding, top_k)`
- `Storage.save_eval(run_id, payload)` / `load_eval(run_id)`
- `make_storage(db_path, memory_store, vector_store)`
