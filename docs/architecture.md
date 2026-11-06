# Architecture

## Transfer flow

1. The CLI creates a tar.gz bundle with a manifest. The manifest records the content type and original name inside the encrypted bundle.
2. The CLI encrypts the bundle with age. A transfer can use an age-generated passphrase or a recipient device's public key.
3. The CLI uploads the age ciphertext over HTTPS using an active device upload token. The API returns a random transfer ID and expiry time.
4. The receiving device downloads the ciphertext by ID and decrypts it locally with age.
5. The CLI validates the bundle and extracts files and folders into a new destination. It rejects symbolic links, special files, and paths that escape the destination. Sending a folder that contains symbolic links or special files also fails.

The server does not inspect the age format or the encrypted manifest. No decryption key is stored on the server.

## Encryption and keys

- SecretBox uses the existing age format rather than a custom cryptographic format.
- By default, age generates a passphrase interactively for each transfer. Share it through a channel separate from the transfer ID.
- A receiving device can create an age identity and share its public key. Its private key stays on that device.
- age provides authenticated encryption. Modifying ciphertext causes decryption to fail.
- SecretBox does not sign senders. Anyone with the passphrase or a recipient public key can create a valid ciphertext. Sender attribution would require a separate public-key signature flow.

## Configuration schema versions

The client configuration and private server JSON configuration each use an independent top-level **schema_version**. The client format is version 1; the private server format is version 2. An absent field is treated as legacy version 0, which has the same settings but predates the marker. Client readers accept versions 0 and 1; server readers accept versions 0, 1, and 2. Unknown or invalid versions fail closed. Version 2 replaces the plaintext server upload_token with an upload_tokens map of names to SHA-256 hashes and creation timestamps. Tokens are random 32-byte credentials, not passwords.

The CLI writes version 1 the next time **sb configure** saves its configuration. The server configurator writes version 2 for new installations. Legacy server files remain supported for authentication; php bin/tokens.php migrate explicitly converts them and preserves the old credential as legacy. Management writes use a separate lock and atomic replacement with mode 0600. See [Upload tokens](upload-tokens.md).

Configuration versions are independent of the API version, age bundle manifest version, and each other. Environment variables remain individually named settings rather than a versioned document. The personal **ss** tool owns the **.sisy.json** schema; SecretBox must not add fields to or impose a version on that external format.

## API v1

- **GET /** returns a generic JSON object with an **ok** boolean. It is true when at least one valid token record is configured. It does not expose the token or identify the service, and it does not check storage permissions.
- **POST /api/v1/transfers** requires **Authorization: Bearer <token>**, receives ciphertext as a multipart/form-data file, and accepts an optional multipart **listable** text field (**true** or **false**, default **false**). It returns **{ "id", "size", "created_at", "expires_at", "listable" }**. Raw ciphertext uploads remain supported and unlisted.
- **GET /api/v1/transfers** is public and returns **{ "transfers": [...], "next_cursor": null | "ID" }**. Only explicitly listable, unexpired transfers with available ciphertext appear. Pages contain at most 100 entries ordered by ID; pass **?after=ID** for the next page. Invalid cursors return **400**. Concurrent uploads may require a fresh traversal.
- **GET /api/v1/transfers/{id}** returns ciphertext. The random ID acts as a download capability for both listed and unlisted transfers.
- **DELETE /api/v1/transfers/{id}** requires an active upload token and deletes the transfer.
- **GET /healthz** returns basic status without transfer data.
- The API supports installation under a path prefix such as **/sites/secret-box**.

The server generates IDs from 24 random bytes encoded as URL-safe Base64 without padding. It stores the ciphertext and a JSON sidecar with size, expiry, and a boolean **listable** flag. A missing flag means unlisted, preserving legacy sidecars without a migration. This additive metadata field does not change either configuration schema. Original filenames remain in the encrypted bundle. Storage is outside the public directory when the hosting environment supports it.

## Initial limits

- Upload size is configurable and defaults to 100 MiB.
- Transfer expiry is configurable and defaults to 24 hours.
- Downloads do not require the upload token, allowing another device to fetch ciphertext. Treat unlisted IDs as secret; by itself, it cannot decrypt the transfer.
- Version 1 has no web panel, accounts, sender signatures, or one-time downloads.
- The server can observe IP addresses, time, size, and transfer frequency. It can delete or retain ciphertext. It cannot recover content if passphrases and private identities remain off the server.

## Resource boundaries

Uploads are serialized with a nonblocking filesystem lock. A concurrent upload returns **429** with **Retry-After: 1**. Under the same lock, the server removes expired transfers and incomplete publications left by interrupted workers, measures disk usage, and enforces a byte quota and transfer-count limit. Quota exhaustion returns **507**. The byte quota includes transfer metadata and reserves an additional 4 KiB before accepting each upload. These controls cover the private transfer directory, not PHP/proxy temporary storage or other applications on the host.

Receiving clients enforce independent size and time limits even if the server is compromised. File extraction is staged in a private directory on the destination filesystem. Files are published by an exclusive hard link, and folders by a rename, without a cross-filesystem plaintext copy. The destination parent must be trusted and not writable by hostile local users. See [Security controls](security-controls.md).
