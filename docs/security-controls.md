# Security controls and deployment updates

## Client boundaries

- HTTPS is mandatory. The development-only **SECRETBOX_ALLOW_HTTP_LOOPBACK=1** exception allows HTTP only to literal loopback addresses or localhost. It does not allow remote HTTP hosts.
- A saved upload token is bound to the configured scheme, hostname, effective port, and path prefix. A different **--server** or **SECRETBOX_SERVER** cannot inherit it. An explicitly supplied **SECRETBOX_TOKEN** is a credential for the selected destination.
- Ciphertext is limited to 100 MiB; decrypted compressed bundles to 128 MiB; extracted file contents to 2 GiB and 100,000 archive entries; text to 16 MiB. Download and decryption each have a five-minute deadline, including passphrase entry during decryption. Larger transfers must be split. The client rejects oversized or truncated responses and counts bytes even without Content-Length.
- Extraction uses a private staging directory on the destination filesystem, so saving to another disk never copies plaintext through a file with default permissions. Files have mode 0600 and extracted directories have mode 0700. The destination parent must be trusted. Filesystems that do not support private permissions or hard links are not supported for secure publication.

## Server quotas

The following settings are environment variables, not fields in the private server JSON:

| Setting | Default | Meaning |
| --- | --- | --- |
| SECRETBOX_MAX_BYTES | 104857600 | Maximum ciphertext bytes per transfer |
| SECRETBOX_MAX_TOTAL_BYTES | 1073741824 | Maximum storage bytes, including metadata |
| SECRETBOX_MAX_TRANSFERS | 1000 | Maximum stored transfer count |
| SECRETBOX_TTL_SECONDS | 86400 | Transfer lifetime |

Uploads reserve 4 KiB for metadata and are serialized across PHP workers with a filesystem lock. A busy upload returns 429 with Retry-After; exhausted quotas return 507. Expired and incomplete uploads are collected before accepting a new upload. Continue scheduling **bin/cleanup.php** so expired data is removed during idle periods. Use a local filesystem with working flock semantics.

Storage must be outside the application directory. Quotas do not include PHP's upload temporary directory, proxy buffers, unrelated applications, or filesystem overhead. Set host-level disk limits and leave free space for these uses. Raising the server's per-transfer limit does not raise the client's independent 100 MiB ceiling.

## Update existing shared hosting

1. Install the updated client with **make client/install**, and upload server code with **make server/sync**.
2. Merge the managed rules from **server/.htaccess.example** into the remote **.htaccess**. They include a 104873984-byte request-body limit, routing, Authorization forwarding, and rejection of absent or malformed write credentials. Preserve host-specific rules. Do not put the token in this file.
3. Copy **server/.user.ini.example** to the remote **.user.ini**, or merge its settings into the host's existing file. PHP/FastCGI can cache these settings; confirm the effective values through the hosting control panel. Some providers restrict these directives.
4. Add **.user.ini** and **.user.ini.example** to the real **server/.sisy.json** exclusions. This preserves host-maintained settings during rsync with deletion. Keep the existing exclusions for **.htaccess**, **.secretbox-config-path**, credentials, and transfer data.
5. Confirm provider-level limits for request size, input time, concurrent requests, and request rates. Configure a periodic cleanup job as described in [Operations](operations.md).

New installations generate **.user.ini** during **php bin/configure.php**. Legacy JSON configurations remain readable; enable named tokens with the explicit migration in [Upload tokens](upload-tokens.md). The real **.htaccess**, **.user.ini**, and **.sisy.json** remain ignored and are never replaced during sync.

PHP processes multipart uploads before the application can compare the complete token. The Apache example rejects missing/malformed credentials early, but a syntactically valid wrong token can still cause PHP to receive a bounded upload. Full pre-upload authentication and connection/rate limits require a trusted proxy or hosting-provider controls. PHP source changes alone cannot eliminate this limitation on shared hosting. See the [PHP upload configuration reference](https://www.php.net/manual/en/ini.core.php#ini.sect.file-uploads).

## Docker deployment

The included Caddy configuration makes a bodyless FastCGI GET to **bin/authorize.php** before forwarding write requests. This internal script is outside the public document root and uses the same live token registry as the API. Revocations take effect on subsequent checks without restarting Caddy. The proxy also applies a 104873984-byte body limit and limits request duration. The development HTTP port is bound to 127.0.0.1 only. Request size and timeout controls are described in the [Caddy documentation](https://caddyserver.com/docs/caddyfile/directives/request_body).

## Regression checks

Run from the repository root:

```sh
PYTHONPATH=client/src python3 -m unittest discover -s client/tests -v
php server/tests/security.php
python3 -m unittest discover -s server/tests -v
```

The client tests include a real age round trip when age and age-keygen are installed. All fixtures are generated in temporary directories and use dummy data.
