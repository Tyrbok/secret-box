# Threat model

## What SecretBox protects

- Content confidentiality from the server operator, hosting provider, or anyone who obtains only a copy of server storage.
- Ciphertext integrity in storage and transit through age and HTTPS.
- Casual download access through random, hard-to-guess transfer IDs.

## What SecretBox does not protect

- A compromised sending or receiving device, malware, screenshots, or a copied private identity.
- A weak passphrase or a passphrase shared through the same channel as the transfer ID. Use age's generated passphrase or a recipient public key.
- Availability. The server can go offline, delete a transfer, or enforce storage limits.
- Network metadata privacy. The server and proxy can see IP addresses, time, approximate size, and expiry.
- Sender identity. A shared passphrase does not identify which participant created a transfer.

## Operational guidance

- Serve the API over HTTPS. Do not expose PHP-FPM directly to the Internet.
- Generate an instance upload token with at least 32 random bytes. Store it on the server and in the private configuration of each CLI authorized to upload or delete.
- Keep transfer storage outside the web root and restrict access to the PHP runtime user.
- Do not log tokens. Treat transfer IDs as bearer download links and limit proxy log retention.
- Decryption and extraction happen locally. The CLI rejects unsafe archive paths and symbolic links in received bundles.
- The CLI temporarily stores ciphertext and decrypted bundles in a private temporary directory and removes them when finished. File deletion does not guarantee physical erasure from SSDs, snapshots, or backups.
