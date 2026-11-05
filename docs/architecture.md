# Architecture

## Transfer flow

1. The CLI creates a tar.gz bundle with a manifest. The manifest records the content type and original name inside the encrypted bundle.
2. The CLI encrypts the bundle with age. A transfer can use an age-generated passphrase or a recipient device's public key.
3. The CLI uploads the age ciphertext over HTTPS using the instance upload token. The API returns a random transfer ID and expiry time.
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

The client configuration and private server JSON configuration each use an independent top-level **schema_version**. Version 1 is the current format. An absent field is treated as legacy version 0, which has the same settings but predates the marker. Readers accept versions 0 and 1 and reject unknown or invalid versions rather than silently interpreting them.

The CLI writes version 1 the next time **sb configure** saves its configuration. The server configurator writes version 1 for new installations. Existing unversioned server files remain supported, so they do not need to be regenerated.

Configuration versions are independent of the API version, age bundle manifest version, and each other. Environment variables remain individually named settings rather than a versioned document. The personal **ss** tool owns the **.sisy.json** schema; SecretBox must not add fields to or impose a version on that external format.

## API v1

- **GET /** returns a generic JSON object with an **ok** boolean. It is true when the upload token is present, at least 32 characters long, and not the placeholder value. It does not expose the token or identify the service, and it does not check storage permissions.
- **POST /api/v1/transfers** requires **Authorization: Bearer <token>**, receives ciphertext as a multipart/form-data file, and returns **{ "id", "size", "created_at", "expires_at" }**.
- **GET /api/v1/transfers/{id}** returns ciphertext. The random ID acts as a download capability; there is no public listing.
- **DELETE /api/v1/transfers/{id}** requires the instance token and deletes the transfer.
- **GET /healthz** returns basic status without transfer data.
- The API supports installation under a path prefix such as **/sites/secret-box**.

The server generates IDs from 24 random bytes encoded as URL-safe Base64 without padding. It stores the ciphertext and a JSON sidecar with size and expiry metadata. Storage is outside the public directory when the hosting environment supports it.

## Initial limits

- Upload size is configurable and defaults to 100 MiB.
- Transfer expiry is configurable and defaults to 24 hours.
- Downloads do not require the upload token, allowing another device to fetch ciphertext. Treat the ID as secret; by itself, it cannot decrypt the transfer.
- Version 1 has no web panel, accounts, public listing, sender signatures, or one-time downloads.
- The server can observe IP addresses, time, size, and transfer frequency. It can delete or retain ciphertext. It cannot recover content if passphrases and private identities remain off the server.
