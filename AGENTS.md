# Repository guide for coding agents and contributors

This file records the project's architecture and the constraints that changes must preserve. The repository has been developed with assistance from OpenAI Codex.

## Project structure

- **client/** is the Python CLI package. Keep the package dependency-light and install it with uv.
- **server/** is the PHP API. It has no Composer dependencies and supports PHP 8.1 or later at runtime.
- **contracts/openapi.yaml** describes the public HTTP API.
- **deploy/** contains the Docker Compose and Caddy deployment.
- **docs/** contains architecture, operations, and threat model documentation.

## Architecture and security invariants

- Use age for encryption. Do not add a custom cryptographic format or send passphrases/private identities to the server.
- The client bundles input locally, encrypts it, and uploads only ciphertext over HTTPS.
- The server stores ciphertext plus minimal expiry metadata outside the web root where the host permits it. It does not parse age payloads.
- The current server has one instance upload token shared by authorized clients. Upload and delete require this token; download uses the unguessable transfer ID. Do not document per-device tokens or revocation as implemented.
- Validate transfer IDs and archive paths. Reject traversal, absolute paths, symbolic links, special files, and extraction outside the selected destination.
- Keep the root response generic and free of service or API details; it may expose only a generic readiness boolean. Detailed health information belongs at /healthz.
- Keep storage size and expiry limits enforced on the server.
- Keep the client and private server JSON configuration schemas versioned independently. Treat missing schema_version as legacy version 0, accept only explicitly supported versions, and add an explicit migration before introducing an incompatible format.

## Deployment files and secrets

- Never commit real .env files, server/.sisy.json, server/.htaccess, .secretbox-config-path, upload tokens, private age identities, or transfer data.
- Keep sanitized templates such as server/.sisy.example.json and server/.htaccess.example versioned.
- The personal ss upload command uses rsync with deletion. Preserve its exclusions for secrets, local state, the real .sisy.json, .htaccess, and .secretbox-config-path.
- The actual .htaccess is generated or host-maintained. Do not replace it during sync with the example file.
- Do not add deployment credentials, hostnames, or personal server paths to documentation or examples.

## Language and documentation

- Write README files, comments, CLI output, API errors, and maintained documentation in English.
- Keep examples generic and safe to publish. Use placeholders rather than real tokens, hostnames, or private paths.
- Update the OpenAPI contract and relevant documentation whenever API behavior changes.
- Do not add schema_version to environment variables or the external ss .sisy.json format; document those settings according to their owners' conventions.
