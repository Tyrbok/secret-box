<?php
declare(strict_types=1);

namespace SecretBox;

use LengthException;
use RuntimeException;

final class TransferStore
{
    private function __construct(
        private readonly string $directory,
        private readonly int $maxBytes,
        private readonly int $ttlSeconds,
    ) {
    }

    private static function defaultDirectory(): string
    {
        $serverRoot = dirname(__DIR__);
        $siteRoot = realpath($serverRoot);
        $configPath = getenv('SECRETBOX_UPLOAD_TOKEN_FILE') ?: '';
        if ($configPath === '') {
            $pointerPath = $serverRoot . '/.secretbox-config-path';
            if (is_file($pointerPath) && is_readable($pointerPath)) {
                $configPath = trim((string) file_get_contents($pointerPath));
            }
        }
        $resolvedConfigPath = realpath($configPath);
        if ($siteRoot !== false && $resolvedConfigPath !== false && is_file($resolvedConfigPath)) {
            $privateDirectory = dirname($resolvedConfigPath);
            $sitePrefix = rtrim($siteRoot, DIRECTORY_SEPARATOR) . DIRECTORY_SEPARATOR;
            if ($privateDirectory !== $siteRoot
                && strncmp($privateDirectory, $sitePrefix, strlen($sitePrefix)) !== 0) {
                return $privateDirectory . '/transfers';
            }
        }

        $home = getenv('HOME') ?: '';
        if ($home !== '') {
            return rtrim($home, DIRECTORY_SEPARATOR) . '/.local/share/secretbox/transfers';
        }
        return '/var/lib/secretbox';
    }

    public static function fromEnvironment(): self
    {
        $directory = getenv('SECRETBOX_STORAGE_DIR') ?: self::defaultDirectory();
        $maxBytes = filter_var(getenv('SECRETBOX_MAX_BYTES') ?: '104857600', FILTER_VALIDATE_INT);
        $ttlSeconds = filter_var(getenv('SECRETBOX_TTL_SECONDS') ?: '86400', FILTER_VALIDATE_INT);
        if ($maxBytes === false || $maxBytes < 1 || $ttlSeconds === false || $ttlSeconds < 60) {
            throw new RuntimeException('Invalid size or expiry configuration');
        }
        if (!is_dir($directory) && !mkdir($directory, 0700, true) && !is_dir($directory)) {
            throw new RuntimeException('Could not create the storage directory');
        }
        if (!chmod($directory, 0700)) {
            throw new RuntimeException('Could not restrict storage directory permissions');
        }
        if (!is_writable($directory)) {
            throw new RuntimeException('Storage directory is not writable');
        }
        return new self($directory, $maxBytes, $ttlSeconds);
    }

    /** @param resource $input */
    public function create($input): array
    {
        if (!is_resource($input)) {
            throw new RuntimeException('Could not read the request body');
        }
        $declared = $_SERVER['CONTENT_LENGTH'] ?? null;
        $contentType = strtolower($_SERVER['CONTENT_TYPE'] ?? '');
        $multipartOverhead = strpos($contentType, 'multipart/form-data') === 0 ? 16384 : 0;
        if (is_string($declared) && ctype_digit($declared)
            && (int) $declared > $this->maxBytes + $multipartOverhead) {
            throw new LengthException('Ciphertext exceeds the maximum size');
        }

        $temporary = tempnam($this->directory, '.upload-');
        if ($temporary === false) {
            throw new RuntimeException('Could not create a temporary file');
        }
        @chmod($temporary, 0600);
        $output = fopen($temporary, 'wb');
        if ($output === false) {
            @unlink($temporary);
            throw new RuntimeException('Could not open the temporary file');
        }
        $size = 0;
        try {
            while (!feof($input)) {
                $chunk = fread($input, 65536);
                if ($chunk === false) {
                    throw new RuntimeException('Error reading the request');
                }
                if ($chunk === '') {
                    continue;
                }
                $size += strlen($chunk);
                if ($size > $this->maxBytes) {
                    throw new LengthException('Ciphertext exceeds the maximum size');
                }
                if (fwrite($output, $chunk) !== strlen($chunk)) {
                    throw new RuntimeException('Error saving ciphertext');
                }
            }
        } catch (\Throwable $exception) {
            fclose($output);
            @unlink($temporary);
            throw $exception;
        }
        fclose($output);
        if ($size === 0) {
            @unlink($temporary);
            throw new RuntimeException('Transfer body is empty');
        }

        $id = rtrim(strtr(base64_encode(random_bytes(24)), '+/', '-_'), '=');
        $created = time();
        $expires = $created + $this->ttlSeconds;
        $dataPath = $this->dataPath($id);
        $metadataPath = $this->metadataPath($id);
        $metadataTemporary = $metadataPath . '.tmp-' . bin2hex(random_bytes(8));
        $metadata = [
            'id' => $id,
            'size' => $size,
            'created_at' => gmdate(DATE_ATOM, $created),
            'expires_at' => gmdate(DATE_ATOM, $expires),
            'expires_epoch' => $expires,
        ];
        $encoded = json_encode($metadata, JSON_UNESCAPED_SLASHES);
        if ($encoded === false || file_put_contents($metadataTemporary, $encoded, LOCK_EX) === false) {
            @unlink($temporary);
            @unlink($metadataTemporary);
            throw new RuntimeException('Could not save transfer metadata');
        }
        @chmod($metadataTemporary, 0600);
        if (!rename($temporary, $dataPath)) {
            @unlink($temporary);
            @unlink($metadataTemporary);
            throw new RuntimeException('Could not publish ciphertext');
        }
        if (!rename($metadataTemporary, $metadataPath)) {
            @unlink($dataPath);
            @unlink($metadataTemporary);
            throw new RuntimeException('Could not publish transfer metadata');
        }
        return [
            'id' => $id,
            'size' => $size,
            'created_at' => $metadata['created_at'],
            'expires_at' => $metadata['expires_at'],
        ];
    }

    public function pathForDownload(string $id): ?string
    {
        $metadata = $this->readMetadata($id);
        if ($metadata === null) {
            return null;
        }
        if (($metadata['expires_epoch'] ?? 0) < time()) {
            $this->delete($id);
            return null;
        }
        $path = $this->dataPath($id);
        return is_file($path) ? $path : null;
    }

    public function delete(string $id): bool
    {
        $dataPath = $this->dataPath($id);
        $metadataPath = $this->metadataPath($id);
        $exists = is_file($dataPath) || is_file($metadataPath);
        if (is_file($dataPath)) {
            @unlink($dataPath);
        }
        if (is_file($metadataPath)) {
            @unlink($metadataPath);
        }
        return $exists;
    }

    /** @return list<string> */
    public function expiredIds(): array
    {
        $ids = [];
        foreach (glob($this->directory . '/*.json') ?: [] as $path) {
            $id = basename($path, '.json');
            if (!preg_match('/^[A-Za-z0-9_-]{32}$/', $id)) {
                continue;
            }
            $metadata = $this->readMetadata($id);
            if ($metadata !== null && ($metadata['expires_epoch'] ?? PHP_INT_MAX) < time()) {
                $ids[] = $id;
            }
        }
        return $ids;
    }

    private function readMetadata(string $id): ?array
    {
        $path = $this->metadataPath($id);
        if (!is_file($path)) {
            return null;
        }
        $decoded = json_decode((string) file_get_contents($path), true);
        return is_array($decoded) ? $decoded : null;
    }

    private function dataPath(string $id): string
    {
        return $this->directory . '/' . $id . '.age';
    }

    private function metadataPath(string $id): string
    {
        return $this->directory . '/' . $id . '.json';
    }
}

