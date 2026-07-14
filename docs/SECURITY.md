# Security model

Generated CAD code is untrusted input. The local Docker engine is the default even when OpenSCAD is installed on the host.

## Engine sandbox

The Docker invocation must use all of the following controls:

- no network;
- read-only root filesystem;
- all Linux capabilities dropped;
- `no-new-privileges`;
- non-root user;
- bounded wall time, CPU, memory, PIDs, and output size;
- one writable job directory with normalized paths;
- the vendored NopSCADlib tree mounted read-only;
- no Docker socket, home directory, SSH agent, environment secrets, or arbitrary host paths.

The local executor exists only as a private class in the dedicated worker module, and `auto` considers Docker only. The public settings schema has no local mode, so the host/application cannot select a local binary through configuration even when one is installed.

## Compose worker boundary

The root application image defaults to remote-worker mode. Compose explicitly enables local OpenSCAD only in the dedicated `worker` service. That service:

- communicates only through a fixed, owner-checked Unix-domain socket under `/run/seecad`;
- has `network_mode: none` and receives no `OPENAI_API_KEY`;
- runs as UID/GID 10001 with a read-only root, all capabilities dropped, `no-new-privileges`, and bounded CPU, memory, PIDs, file size, open files, wall time, and tmpfs space;
- mounts the socket volume read-write while the API mounts it read-only;
- admits one compile at a time and fails concurrent work busy;
- accepts no command, path, include, environment, or mount parameters over the protocol.
- is the only service given the worker-local execution capability; the API receives neither that value nor a local execution path.

The worker verifies the vendored NopSCADlib commit metadata and recomputes the complete tree digest at startup and immediately before every compile. The API independently revalidates its live tree before every compile and rejects a response whose protocol version, worker build ID, OpenSCAD version syntax, Nop revision/tree digest, source digest, artifact digest, byte size, format, or duration envelope does not match. This prevents a bind-mounted library mutation from being accepted under stale provenance. Response bytes are streamed and bounded even if a peer omits or lies about `Content-Length`. Worker error bodies and paths are not propagated into public domain errors.

The worker build ID is a content-derived SHA-256 identity over the Dockerfile, locked Python dependency inputs, runtime Python sources, and an explicit build seed. The immutable image file is the default authority; any configured override must use the same strict `sha256-<64 lowercase hex>` form. The API persists the verified identity in compile provenance.

`/health` remains a liveness and structured dependency-status endpoint. `/ready` returns `503` unless storage is writable and the bounded UDS worker probe succeeds. Compose uses `/ready` for API health, so a merely reachable but degraded API does not release the web dependency.

## API boundary

- Pydantic validates all design and constraint inputs.
- Nginx and the API enforce the same 50 MiB request cap; the API applies it while consuming ASGI body chunks as well as from `Content-Length`, while four maximum-size image-evidence data URLs remain admissible under the model and transport limits.
- Artifact identifiers are digests, not filesystem paths.
- Project and revision identifiers are generated server-side.
- Error responses omit environment values, absolute host paths, and source from other projects.
- Compile logs are size-limited and stored as artifacts.
- Analysis cache hits require the canonical print-profile digest and mesh digest to match; approvals require a complete, internally consistent compile and analysis evidence chain.
- Browser origins are explicit configuration; wildcard credentialed CORS is forbidden.

## Model boundary

Model output is parsed into the same strict design schema used by humans and MCP clients. A model cannot supply engine flags, mount paths, process commands, or artifact paths. Generated designs require deterministic compilation and checks before review. Multimodal findings are advisory and always labelled heuristic.

## Secrets

SeeCAD reads `OPENAI_API_KEY` from the process environment. `.envrc` and local env files are ignored. Keys are never persisted to SQLite, manifests, logs, exported bundles, or browser responses.
