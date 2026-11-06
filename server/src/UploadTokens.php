<?php
declare(strict_types=1);

namespace SecretBox;

use RuntimeException;

/** Shared credential reader for API requests, proxy checks, and SSH management. */
final class UploadTokens
{
    public const SCHEMA_VERSION = 2;
    public const MAX_TOKENS = 100;

    public static function configurationPath(): ?string
    {
        $path = getenv('SECRETBOX_UPLOAD_TOKEN_FILE') ?: '';
        if ($path === '') {
            $pointer = dirname(__DIR__) . '/.secretbox-config-path';
            if (is_file($pointer) && is_readable($pointer)) {
                $path = trim((string) file_get_contents($pointer));
            }
        }
        return $path === '' ? null : $path;
    }

    public static function validatePath(string $path): void
    {
        $parent = realpath(dirname($path));
        $root = realpath(dirname(__DIR__));
        if ($parent === false || $root === false || is_link($path)
            || $parent === $root || str_starts_with($parent, $root . DIRECTORY_SEPARATOR)) {
            throw new RuntimeException('Token configuration must be a regular file outside the application directory');
        }
    }

    public static function read(string $path): array
    {
        self::validatePath($path);
        if (!is_file($path) || !is_readable($path) || filesize($path) > 65536) {
            throw new RuntimeException('Token configuration is missing, unreadable, or too large');
        }
        $contents = file_get_contents($path);
        $config = $contents === false ? null : json_decode($contents, true);
        if (!is_array($config)) {
            throw new RuntimeException('Token configuration must be a JSON object');
        }
        self::hashes($config); // Validate the entire document before using any token.
        return $config;
    }

    public static function load(): array
    {
        $path = self::configurationPath();
        if ($path !== null) {
            // A configured file is authoritative. Never fall back to a legacy
            // environment credential after revocation or a read/config error.
            return self::read($path);
        }
        $config = ['upload_token' => getenv('SECRETBOX_UPLOAD_TOKEN') ?: ''];
        self::hashes($config);
        return $config;
    }

    public static function validLegacyToken(mixed $token): bool
    {
        return is_string($token) && strlen($token) >= 32 && strlen($token) <= 4096
            && $token !== 'CHANGE_ME';
    }

    public static function validName(string $name): bool
    {
        return preg_match('/^[A-Za-z][A-Za-z0-9_-]{0,63}$/D', $name) === 1;
    }

    /** @return list<string> */
    private static function hashes(array $config): array
    {
        $version = array_key_exists('schema_version', $config) ? $config['schema_version'] : 0;
        if (!is_int($version) || !in_array($version, [0, 1, self::SCHEMA_VERSION], true)) {
            throw new RuntimeException('Unsupported server configuration schema version');
        }
        if ($version < self::SCHEMA_VERSION) {
            $token = $config['upload_token'] ?? '';
            return self::validLegacyToken($token) ? [hash('sha256', $token)] : [];
        }
        $tokens = $config['upload_tokens'] ?? null;
        if (!is_array($tokens) || count($tokens) > self::MAX_TOKENS || array_key_exists('upload_token', $config)) {
            throw new RuntimeException('Invalid version 2 token registry');
        }
        $hashes = [];
        foreach ($tokens as $name => $record) {
            if (!is_string($name) || !self::validName($name) || !is_array($record)
                || !is_string($record['sha256'] ?? null)
                || !preg_match('/^[a-f0-9]{64}$/D', $record['sha256'])
                || !is_string($record['created_at'] ?? null)) {
                throw new RuntimeException('Invalid token record');
            }
            $hashes[] = $record['sha256'];
        }
        return $hashes;
    }

    public static function configured(array $config): bool
    {
        return self::hashes($config) !== [];
    }

    public static function accepts(array $config, string $authorization): bool
    {
        if (strlen($authorization) > 8192 || !preg_match('/^Bearer\s+(\S+)$/iD', $authorization, $matches)) {
            return false;
        }
        $candidate = hash('sha256', $matches[1]);
        $accepted = false;
        foreach (self::hashes($config) as $expected) {
            $accepted = hash_equals($expected, $candidate) || $accepted;
        }
        return $accepted;
    }

    public static function migrate(array $config): array
    {
        self::hashes($config);
        if (($config['schema_version'] ?? 0) === self::SCHEMA_VERSION) {
            return $config;
        }
        $token = $config['upload_token'] ?? '';
        if (!self::validLegacyToken($token)) {
            throw new RuntimeException('Legacy configuration does not contain a valid token');
        }
        unset($config['upload_token']);
        $config['schema_version'] = self::SCHEMA_VERSION;
        $config['upload_tokens'] = ['legacy' => [
            'sha256' => hash('sha256', $token), 'created_at' => gmdate(DATE_ATOM),
        ]];
        return $config;
    }

    /** Caller holds the separate .lock file across read, modify, and rename. */
    public static function write(string $path, array $config): void
    {
        self::validatePath($path);
        self::hashes($config);
        if (($config['schema_version'] ?? 0) === self::SCHEMA_VERSION) {
            $config['upload_tokens'] = (object) $config['upload_tokens'];
        }
        $contents = json_encode($config, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES | JSON_THROW_ON_ERROR) . "\n";
        if (strlen($contents) > 65536) {
            throw new RuntimeException('Token configuration exceeds the size limit');
        }
        $temporary = tempnam(dirname($path), '.tokens-');
        if ($temporary === false) {
            throw new RuntimeException('Could not create private token configuration');
        }
        try {
            if (!chmod($temporary, 0600) || file_put_contents($temporary, $contents) !== strlen($contents)
                || !rename($temporary, $path)) {
                throw new RuntimeException('Could not publish token configuration');
            }
        } finally {
            if (is_file($temporary)) {
                unlink($temporary);
            }
        }
    }
}
