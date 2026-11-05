# Operations

## Server requirements

- Docker Compose for the container deployment, or PHP 8.1 or later for a direct PHP deployment.
- For production HTTPS with Caddy: a domain pointed at the server and inbound ports 80 and 443 available.
- Persistent storage for transfer ciphertext and enough free disk space.

## Configure the Docker deployment

Copy **deploy/.env.example** to **deploy/.env**, set **SECRETBOX_UPLOAD_TOKEN**, and choose a domain. Generate a token with:

~~~sh
openssl rand -hex 32
~~~

Use the same token on the server and in every CLI allowed to upload or delete transfers. The **.env** file is excluded from Git.

The CLI configuration is stored at **~/.config/secretbox/config.json** with mode **0600**. Identities created by **sb keygen** are stored under **~/.config/secretbox/identities/** with mode **0600**.

The client JSON file has a **schema_version** field. Older client files without it are treated as version 0 and continue to work; running **sb configure** writes version 1. The server's private **server.json** also accepts legacy unversioned files, so existing hosting setups do not need reconfiguration. New files created by **bin/configure.php** include version 1.

## Shared PHP hosting

On shared hosting, upload the contents of **server/** to the web root. Run **php bin/configure.php** over SSH from that web root, once. The script is CLI-only and refuses to overwrite existing configuration. It generates a 32-byte random upload token, writes **~/.config/secretbox/server.json** outside the web root with mode **0600**, creates the private directory with mode **0700**, and stores a pointer to the JSON file in **.secretbox-config-path**. The pointer contains the path, not the token.

The configurator adds Apache rules to route API requests and deny web access to hidden files, **src/**, and **bin/**. It also forwards the Authorization header for PHP/FastCGI. If you previously set **SECRETBOX_UPLOAD_TOKEN** in **.htaccess**, remove that directive before running the configurator. For an existing installation created before Authorization forwarding was added, add the rewrite rules from **server/.htaccess.example** immediately after **RewriteEngine On** in the remote **.htaccess**.

The web application's runtime needs PHP 8.1 or later. The one-time configurator itself supports PHP 7.1 or later, so the SSH CLI version may differ from the web runtime version.

The script prints the generated token once. Enter that same value with **sb configure** on each authorized client. Transfers are stored outside the web root next to the private configuration file.

### Synchronizing with the personal ss script

The project does not include the personal **ss** synchronization utility. To use it:

1. Copy **server/.sisy.example.json** to **server/.sisy.json** and set the site and build path for your own account.
2. Review every entry in **exclude** before deployment. The sample excludes secrets, environment files, local storage, development files, the real **.sisy.json**, and **.htaccess**.
3. From the repository root, run **make server/sync**. It invokes **ss -u** from **server/**.

The sync utility uploads with **rsync --delete**. The exclusion list is therefore essential: it preserves remote **.htaccess** and **.secretbox-config-path** and prevents private local files from being uploaded. Keep **.sisy.json**, the real **.htaccess**, and credentials out of Git. Only the sanitized **.sisy.example.json** and **.htaccess.example** should be versioned. If you need to update host rules, edit the remote **.htaccess** deliberately; syncing does not replace the host-specific file.

## Expiry and cleanup

The server rejects expired downloads and deletes expired files when a download is attempted. The **bin/cleanup.php** script can delete expired transfers without waiting for a download. Schedule it periodically:

~~~cron
*/15 * * * * docker compose --env-file /path/to/secret-box/deploy/.env -f /path/to/secret-box/deploy/compose.yaml exec -T php php /var/www/html/bin/cleanup.php
~~~

## Backups

The data volume contains ciphertext and transfer metadata. A backup can restore transfers that have not expired, but it does not replace recipients' private identities or passphrases.

## Local server development

Set a development-only token and start PHP's built-in server:

~~~sh
export SECRETBOX_UPLOAD_TOKEN="$(openssl rand -hex 32)"
export SECRETBOX_STORAGE_DIR="/tmp/secretbox-data"
php -S 127.0.0.1:8080 -t server/public server/public/index.php
~~~

Configure the CLI with **http://127.0.0.1:8080**. Do not use HTTP over a public network.
