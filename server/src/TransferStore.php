<?php
declare(strict_types=1);

namespace SecretBox;

use LengthException;
use RuntimeException;

final class StorageQuotaException extends RuntimeException {}
final class StorageBusyException extends RuntimeException {}

final class TransferStore
{
    private function __construct(
        private readonly string $directory,
        private readonly int $maxBytes,
        private readonly int $ttlSeconds,
        private readonly int $maxTotalBytes,
        private readonly int $maxTransfers,
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
        $maxTotalBytes = filter_var(getenv('SECRETBOX_MAX_TOTAL_BYTES') ?: '1073741824', FILTER_VALIDATE_INT);
        $maxTransfers = filter_var(getenv('SECRETBOX_MAX_TRANSFERS') ?: '1000', FILTER_VALIDATE_INT);
        if ($maxBytes === false || $maxBytes < 1 || $ttlSeconds === false || $ttlSeconds < 60
            || $maxTotalBytes === false || $maxTotalBytes < 1 || $maxTransfers === false || $maxTransfers < 1) {
            throw new RuntimeException('Invalid size or expiry configuration');
        }
        if (!is_dir($directory) && !mkdir($directory, 0700, true) && !is_dir($directory)) {
            throw new RuntimeException('Could not create the storage directory');
        }
        $directory = realpath($directory);
        $siteRoot = realpath(dirname(__DIR__));
        if ($directory === false || $siteRoot === false || $directory === $siteRoot
            || strncmp($directory, $siteRoot . DIRECTORY_SEPARATOR, strlen($siteRoot) + 1) === 0) {
            throw new RuntimeException('Storage must be outside the application directory');
        }
        if (!chmod($directory, 0700)) {
            throw new RuntimeException('Could not restrict storage directory permissions');
        }
        if (!is_writable($directory)) {
            throw new RuntimeException('Storage directory is not writable');
        }
        return new self($directory, $maxBytes, $ttlSeconds, $maxTotalBytes, $maxTransfers);
    }

    /** @param resource $input */
    public function create($input, bool $listable = false): array
    {
        $lock = fopen($this->directory . '/.upload.lock', 'c');
        if ($lock === false) {
            throw new RuntimeException('Could not open the upload lock');
        }
        chmod($this->directory . '/.upload.lock', 0600);
        try {
            if (!flock($lock, LOCK_EX | LOCK_NB)) {
                throw new StorageBusyException('Another upload is in progress; retry later');
            }
            foreach ($this->expiredIds() as $id) {
                $this->delete($id);
            }
            // No other upload can be writing while this lock is held. Remove
            // incomplete publications left behind by a terminated PHP worker.
            $used = 0;
            $count = 0;
            foreach (new \DirectoryIterator($this->directory) as $entry) {
                if (!$entry->isFile() || $entry->getFilename() === '.upload.lock') {
                    continue;
                }
                $name = $entry->getFilename();
                if (str_starts_with($name, '.upload-') || str_contains($name, '.json.tmp-')
                    || (preg_match('/^([A-Za-z0-9_-]{32})\.age$/', $name, $matches)
                        && !is_file($this->metadataPath($matches[1])))) {
                    if (unlink($entry->getPathname())) {
                        continue;
                    }
                }
                $used += $entry->getSize();
                if (preg_match('/^[A-Za-z0-9_-]{32}\.age$/', $name)) {
                    $count++;
                }
            }
            if ($count >= $this->maxTransfers || $used >= $this->maxTotalBytes) {
                throw new StorageQuotaException('Storage quota exceeded');
            }
            return $this->createUnlocked($input, $this->maxTotalBytes - $used, $listable);
        } finally {
            fclose($lock);
        }
    }

    /** @param resource $input */
    private function createUnlocked($input, int $available, bool $listable): array
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
                // Reserve space for the metadata as well as the ciphertext.
                if ($size + 4096 > $available) {
                    throw new StorageQuotaException('Storage quota exceeded');
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
            'listable' => $listable,
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
            'listable' => $listable,
        ];
    }

    /** Return at most 100 discoverable transfers, ordered by ID. */
    public function listing(string $after = ''): array
    {
        $transfers = [];
        $now = time();
        $paths = glob($this->directory . '/*.json') ?: [];
        sort($paths, SORT_STRING);
        foreach ($paths as $path) {
            $id = basename($path, '.json');
            if (!preg_match('/^[A-Za-z0-9_-]{32}$/D', $id) || strcmp($id, $after) <= 0) {
                continue;
            }
            $metadata = $this->readMetadata($id);
            // Legacy transfers have no visibility flag and stay undiscoverable.
            if ($metadata === null || ($metadata['listable'] ?? false) !== true
                || ($metadata['expires_epoch'] ?? 0) <= $now || !is_file($this->dataPath($id))) {
                continue;
            }
            if (count($transfers) === 100) {
                return ['transfers' => $transfers, 'next_cursor' => $transfers[99]['id']];
            }
            $transfers[] = [
                'id' => $id,
                'size' => $metadata['size'],
                'created_at' => $metadata['created_at'],
                'expires_at' => $metadata['expires_at'],
                'listable' => true,
            ];
        }
        return ['transfers' => $transfers, 'next_cursor' => null];
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

