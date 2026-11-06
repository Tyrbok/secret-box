# SecretBox

SecretBox is a small, self-hosted tool for sending text, files, and folders between your own devices. The Python CLI encrypts each transfer with [age](https://age-encryption.org/) before upload. The PHP server stores and serves ciphertext; it never receives the passphrase or recipient private key.

The project is designed for a single, self-managed server installation. The server supports a separate upload token for each device, with independent revocation from SSH. Tokens authorize uploads and deletion; age identities and passphrases protect content.

## Components

- **client/**: Python command-line client.
- **server/**: PHP HTTP API with no Composer dependencies.
- **contracts/**: OpenAPI description of the API.
- **deploy/**: Docker Compose and Caddy configuration.
- **docs/**: architecture, operations, and threat model.

## Requirements

- Python 3.11 or later and [uv](https://docs.astral.sh/uv/) for the CLI.
- **age** and **age-keygen** on **PATH**.
- PHP 8.1 or later for the web application.
- Docker Compose for the included container deployment.

Install age using the [official instructions](https://age-encryption.org/install).

## Install and configure the CLI

From the repository root:

~~~sh
make client/install
sb configure
~~~

The installed command is **sb**. The installer uses **uv tool install**, which keeps the CLI in an isolated environment. For a development checkout, use **make dev/setup**.

The configure command asks for the server URL and an optional upload token. Leave the token blank to use **sb list** and **sb receive** without upload credentials; doing so also removes any previously saved token. **sb send** and **sb delete** require an active token, saved with **sb configure** or supplied through **SECRETBOX_TOKEN**. Give each CLI that sends or deletes transfers its own active token from the server. The CLI stores its configuration at **~/.config/secretbox/config.json** with private file permissions.

SecretBox-owned JSON configuration files carry an independent **schema_version**. Existing client and server configurations without this field remain readable as legacy version 0; new client configuration writes use version 1 and new server configurations use version 2. Legacy server configurations continue to work; use the explicit migration in [Upload tokens](docs/upload-tokens.md) to enable independent device tokens.

## Set up the server

### Docker Compose

Copy the example environment file:

~~~sh
cp deploy/.env.example deploy/.env
~~~

Keep **SECRETBOX_UPLOAD_TOKEN** empty and retain the private registry path in **SECRETBOX_UPLOAD_TOKEN_FILE**. For local development, set **SECRETBOX_DOMAIN=:8080**. For production, set a domain whose DNS points to the server; Caddy will provision HTTPS for a valid public domain.

~~~sh
docker compose --env-file deploy/.env -f deploy/compose.yaml up --build -d
docker compose --env-file deploy/.env -f deploy/compose.yaml exec --user www-data php php bin/tokens.php init desktop
~~~

The **secretbox-data** volume stores encrypted transfers. Remove expired transfers with:

~~~sh
docker compose --env-file deploy/.env -f deploy/compose.yaml exec php php /var/www/html/bin/cleanup.php
~~~

Schedule cleanup periodically with cron or a system timer. See [Operations](docs/operations.md).

### Shared PHP hosting

The server can also run on shared hosting with PHP 8.1 or later. Upload the **server/** files to the web root, then run **php bin/configure.php** over SSH once. It creates an initial random token named **default** and stores its hash outside the web root. Create additional device tokens with **php bin/tokens.php add laptop**. See the [shared hosting instructions](docs/operations.md#shared-php-hosting).

## Usage

### Send a file or folder

By default, age prompts for a passphrase for this transfer:

~~~sh
sb send ./report.pdf
sb send ./folder
~~~

To send text, use **--text**. The CLI reads standard input; when run interactively, paste the text and press **Ctrl-D** to finish:

~~~sh
sb send --text
sb send --text < message.txt
~~~

Share the transfer ID printed by **sb**. Share the passphrase through a different channel.

### List transfers

Transfers are unlisted by default. To publish an encrypted transfer in the public listing:

~~~sh
sb send --listable ./report.pdf
sb send --listable --text < message.txt
sb list
sb list --server https://secretbox.example.com
~~~

The listing requires no token and shows transfer IDs, ciphertext sizes in bytes, creation times, and expiry times. Original filenames and content remain encrypted. Anyone can discover and download listed ciphertext; decryption still requires the passphrase or recipient identity. Unlisted transfers can only be downloaded by someone who knows their ID. Existing transfers remain unlisted.

Each page contains at most 100 transfers ordered by ID. When more are available, the CLI prints a cursor for **sb list --after TRANSFER_ID**; retain **--server** if you used an override. Expired and deleted transfers disappear from the listing. Visibility is chosen at upload time.

### Receive a transfer

~~~sh
sb receive TRANSFER_ID
~~~

Use **--output** to choose a destination path. Text is written to standard output when no destination is specified:

~~~sh
sb receive TRANSFER_ID --output ./destination
~~~

### Use recipient keys

Create an age identity on each receiving device:

~~~sh
sb keygen --name laptop
~~~

Keep the private identity on the device that will decrypt transfers. Share its **age1...** public key with senders:

~~~sh
sb send --recipient age1... ./report.pdf
sb receive TRANSFER_ID --identity ~/.config/secretbox/identities/laptop.txt
~~~

Delete a transfer before it expires:

~~~sh
sb delete TRANSFER_ID
~~~

## Server deployment with ss

The repository includes an example configuration for the personal **ss** synchronization script. That script is not included in this project.

1. Copy **server/.sisy.example.json** to **server/.sisy.json** and configure the target for your own server.
2. Review its **exclude** list. It intentionally excludes credentials, environment files, local data, the real **.sisy.json**, and the host-specific **.htaccess**.
3. Run **make server/sync**. This target calls **ss -u** from **server/**. The uploader uses **rsync --delete**, so review the target and exclusions before syncing.

The real **server/.sisy.json** and **server/.htaccess** are ignored by Git. Only **server/.sisy.example.json** and **server/.htaccess.example** belong in the repository. The generated **.htaccess** contains host-specific routing and access rules; the sync exclusions preserve it and **.secretbox-config-path** on the remote server, even when rsync uses **--delete**. Keep these exclusions if you customize the sample.

## Security

The server stores encrypted content and minimal transfer metadata. It cannot decrypt a transfer, but it can observe network metadata, delete ciphertext, or deny service. Downloads use a random transfer ID and do not require the upload token, so treat an unlisted transfer ID as a secret link. Using **--listable** publishes that ID and its size and timestamps to everyone. Every active upload token authorizes uploads and deletion of known IDs. Revoke a compromised device token with **php bin/tokens.php revoke laptop**; other device tokens remain valid. See [Upload tokens](docs/upload-tokens.md).

Read the [architecture](docs/architecture.md), [threat model](docs/threat-model.md), and [security reporting guide](SECURITY.md) before exposing an instance publicly.

## Transfer security limits

The CLI requires HTTPS. For local development only, set **SECRETBOX_ALLOW_HTTP_LOOPBACK=1** to allow HTTP to **localhost**, **127.0.0.1**, or **::1**. Saved upload tokens are bound to the configured server URL, including its path and port. Changing **--server** or **SECRETBOX_SERVER** cannot reuse that token for another endpoint; run **sb configure** or explicitly provide a destination-specific **SECRETBOX_TOKEN**. Downloads do not send an upload token.

The client limits ciphertext to 100 MiB, decrypted compressed bundles to 128 MiB, extracted files to 2 GiB in total, and text to 16 MiB. Download and decryption each have a five-minute deadline. The server defaults to a 1 GiB storage quota and 1,000 transfers, and accepts one upload at a time. See [security controls and deployment updates](docs/security-controls.md).

## Acknowledgements

This project was developed with assistance from OpenAI Codex. The maintainer reviews and takes responsibility for the published code and security decisions.

## License

Distributed under the MIT License. See [LICENSE](LICENSE).
