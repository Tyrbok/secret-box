# Threat model

## What SecretBox protects

- Content confidentiality from the server operator, hosting provider, or anyone who obtains only a copy of server storage.
- Ciphertext integrity in storage and transit through age and HTTPS.
- Casual download access to unlisted transfers through random, hard-to-guess transfer IDs. Explicitly listable transfers publish their IDs, ciphertext sizes, and timestamps without authentication. Their content still requires age decryption.

## What SecretBox does not protect

- A compromised sending or receiving device, malware, screenshots, or a copied private identity.
- A weak passphrase or a passphrase shared through the same channel as the transfer ID. Use age's generated passphrase or a recipient public key.
- Availability. The server can go offline, delete a transfer, or enforce storage limits.
- Network metadata privacy. The server and proxy can see IP addresses, time, approximate size, and expiry.
- Sender identity. A shared passphrase does not identify which participant created a transfer.

## Operational guidance

- Serve the API over HTTPS. Do not expose PHP-FPM directly to the Internet.
- Generate an independent 32-byte random upload token for each device with the server CLI. Keep its hash on the server and its plaintext value in the private configuration of that device.
- Keep transfer storage outside the web root and restrict access to the PHP runtime user.
- Do not log tokens. Treat unlisted transfer IDs as bearer download links and limit proxy log retention.
- Decryption and extraction happen locally. The CLI rejects unsafe archive paths and symbolic links in received bundles.
- The CLI temporarily stores ciphertext and decrypted bundles in a private temporary directory and removes them when finished. File deletion does not guarantee physical erasure from SSDs, snapshots, or backups.

## Resource and hosting boundaries

Client size/time limits and server quotas bound individual operations; they do not provide full network denial-of-service protection. PHP may buffer multipart uploads before application authentication. The supplied Caddy configuration checks write credentials before forwarding to PHP and bounds request bodies and time. Shared hosting also needs provider-level request/concurrency controls; **.htaccess** and **.user.ini** only supply part of that protection.

Other applications running as the same Unix user can read that user's private files. File permissions do not isolate applications sharing an account. Use a separate hosting user or service account when isolation is required. Revoking one device token blocks future uploads and deletes with that credential. It does not invalidate existing downloads by ID, remove already downloaded data, or revoke age identities. All active tokens have the same upload/delete privileges; they do not establish isolated tenants or prove sender identity.
