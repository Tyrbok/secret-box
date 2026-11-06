# Upload tokens per device

Assign a different upload token to each device so a compromised machine can be revoked without changing the others. These are authorization credentials, separate from age encryption keys and transfer passphrases. Every active token can upload and delete transfers by known ID. Downloads still require only the unguessable transfer ID.

## Existing shared-hosting installation

Upload the new server code with **make server/sync**. Over SSH, change to the application's server directory and run:

```sh
php bin/tokens.php migrate
php bin/tokens.php add laptop
php bin/tokens.php add desktop
php bin/tokens.php list
```

Use PHP 8.1 or later; if the default SSH executable is older, select the host's supported PHP executable. Do not rerun the one-time configurator or delete the existing private JSON or pointer.

The migration explicitly upgrades server JSON versions 0 (missing schema_version) and 1 to version 2. It hashes the current token and preserves it under the name **legacy**, so existing clients keep working. Migration is idempotent. Each **add** command generates a new 32-byte random token and prints it once; **list** shows names and creation dates without secrets or hashes. Up to 100 active tokens are supported. Names are case sensitive, start with a letter and contain up to 64 letters, digits, hyphens, or underscores.

On each device, run **sb configure**, keep the same HTTPS server URL, and enter that device's new token. The client configuration format stays at version 1; existing client binaries accept the new token format.

Once every authorized device has its own token and has successfully uploaded, revoke the old shared token:

```sh
php bin/tokens.php revoke legacy
```

For a lost or compromised device:

```sh
php bin/tokens.php revoke laptop
```

Revocation applies to subsequent authorization checks; it does not cancel an upload already authorized. Other tokens continue working. A revoked token no longer uploads or deletes, but revocation does not invalidate download IDs, previously downloaded files, or copied age identities. There is no remotely accessible token-administration API. Access over SSH is required, including recovery if the last token is revoked.

## New shared-hosting installation

Run **php bin/configure.php** once. It creates server JSON version 2 outside the application directory and prints an initial token named **default**. Give that token to the first device, then use **php bin/tokens.php add laptop** for additional devices.

## Docker

For a new installation, retain the private registry path from **deploy/.env.example** and leave **SECRETBOX_UPLOAD_TOKEN** empty. Start the containers, then run commands as the PHP worker user:

```sh
docker compose --env-file deploy/.env -f deploy/compose.yaml exec --user www-data php php bin/tokens.php init desktop
docker compose --env-file deploy/.env -f deploy/compose.yaml exec --user www-data php php bin/tokens.php add laptop
docker compose --env-file deploy/.env -f deploy/compose.yaml exec --user www-data php php bin/tokens.php list
docker compose --env-file deploy/.env -f deploy/compose.yaml exec --user www-data php php bin/tokens.php revoke laptop
```

To migrate an existing environment-token installation, add **SECRETBOX_UPLOAD_TOKEN_FILE=/var/lib/secretbox/config/server.json** to its private **deploy/.env**, retain its existing **SECRETBOX_UPLOAD_TOKEN** temporarily, rebuild/recreate the containers, and run **bin/tokens.php migrate** using the same Compose command prefix. While that configured file is missing the API fails closed; migration imports the environment token as **legacy**. Then remove the plaintext environment token from **deploy/.env** and recreate the PHP container. Transfer storage paths and existing transfer IDs do not change.

Caddy performs a bodyless internal FastCGI authorization check against the live registry before forwarding writes. It does not hold a separate copy of the tokens, so no proxy restart is needed after add/revoke. Redeploy the updated Caddyfile when upgrading from the previous single-token proxy configuration.

## Storage and compatibility

Server JSON version 2 stores **upload_tokens** as an object keyed by device name. Each record contains **sha256** (the hexadecimal SHA-256 hash of a high-entropy token) and **created_at** (UTC timestamp). Raw generated tokens are never saved on the server by these commands. SHA-256 is appropriate here because tokens contain 256 random bits; do not substitute passwords or memorable strings. Migration preserves the entropy of the old token and does not strengthen a weak legacy credential.

The configuration directory must be private (mode 0700); management refuses a shared parent directory instead of changing its permissions. Administrative writes hold a separate private lock across read/modify/write and atomically publish mode-0600 JSON in a mode-0700 directory. Back up private configuration outside the application and protect backups equally. A configured token file or pointer is authoritative: read errors, invalid schemas, an empty registry, or a deleted file never reactivate a legacy environment token. Without a configured file/pointer, **SECRETBOX_UPLOAD_TOKEN** remains supported for legacy single-token deployments.

Only server JSON moves to version 2. Client JSON, the HTTP API paths, age payloads, environment-variable conventions, and the external **.sisy.json** schema retain their existing formats. Keep the real configuration and its pointer excluded from Git and synchronization as described in [Operations](operations.md).
