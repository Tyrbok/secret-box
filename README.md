# SecretBox

SecretBox is a small, self-hosted tool for sending text, files, and folders between your own devices. The Python CLI encrypts each transfer with [age](https://age-encryption.org/) before upload. The PHP server stores and serves ciphertext; it never receives the passphrase or recipient private key.

The project is designed for a single, self-managed server installation. The current server uses one upload token shared by authorized clients. Per-device upload tokens and individual revocation are not implemented.

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

The configure command asks for the server URL and the upload token already configured on that server. The token must match on the server and every CLI allowed to upload or delete transfers. The CLI stores its configuration at **~/.config/secretbox/config.json** with private file permissions.

SecretBox-owned JSON configuration files carry an independent **schema_version**. Existing client and server configurations without this field remain readable as legacy version 0; new client configuration writes use version 1. You do not need to reconfigure an existing server.

## Set up the server

### Docker Compose

Copy the example environment file and generate a strong random upload token:

~~~sh
cp deploy/.env.example deploy/.env
openssl rand -hex 32
~~~

Put the generated token in **deploy/.env** as **SECRETBOX_UPLOAD_TOKEN**. For local development, set **SECRETBOX_DOMAIN=:8080**. For production, set a domain whose DNS points to the server; Caddy will provision HTTPS for a valid public domain.

~~~sh
docker compose --env-file deploy/.env -f deploy/compose.yaml up --build -d
~~~

The **secretbox-data** volume stores encrypted transfers. Remove expired transfers with:

~~~sh
docker compose --env-file deploy/.env -f deploy/compose.yaml exec php php /var/www/html/bin/cleanup.php
~~~

Schedule cleanup periodically with cron or a system timer. See [Operations](docs/operations.md).

### Shared PHP hosting

The server can also run on shared hosting with PHP 8.1 or later. Upload the **server/** files to the web root, then run **php bin/configure.php** over SSH once. It creates a random upload token and stores it outside the web root. See the [shared hosting instructions](docs/operations.md#shared-php-hosting).

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

The server stores encrypted content and minimal transfer metadata. It cannot decrypt a transfer, but it can observe network metadata, delete ciphertext, or deny service. Downloads use a random transfer ID and do not require the upload token, so treat the ID as a secret link. The current shared upload token authorizes uploads and deletion for every client that has it.

Read the [architecture](docs/architecture.md), [threat model](docs/threat-model.md), and [security reporting guide](SECURITY.md) before exposing an instance publicly.

## Acknowledgements

This project was developed with assistance from OpenAI Codex. The maintainer reviews and takes responsibility for the published code and security decisions.

## License

Distributed under the MIT License. See [LICENSE](LICENSE).
