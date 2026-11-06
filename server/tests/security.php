<?php
declare(strict_types=1);

require __DIR__ . '/../src/TransferStore.php';

function check(bool $condition, string $message): void {
    if (!$condition) {
        throw new RuntimeException($message);
    }
}
function upload(SecretBox\TransferStore $store, int $bytes = 8): array {
    $input = fopen('php://temp', 'w+');
    fwrite($input, str_repeat('x', $bytes));
    rewind($input);
    try {
        return $store->create($input);
    } finally {
        fclose($input);
    }
}
function rejects(callable $operation, string $class): void {
    try {
        $operation();
    } catch (Throwable $exception) {
        check($exception instanceof $class, 'Unexpected exception: ' . get_class($exception));
        return;
    }
    throw new RuntimeException('Expected ' . $class);
}

$directory = sys_get_temp_dir() . '/secretbox-test-' . bin2hex(random_bytes(8));
mkdir($directory, 0700);
putenv('SECRETBOX_STORAGE_DIR=' . $directory);
putenv('SECRETBOX_MAX_BYTES=64');
putenv('SECRETBOX_MAX_TOTAL_BYTES=8192');
putenv('SECRETBOX_MAX_TRANSFERS=1');
putenv('SECRETBOX_TTL_SECONDS=60');
try {
    $store = SecretBox\TransferStore::fromEnvironment();
    $first = upload($store);
    rejects(fn() => upload($store), SecretBox\StorageQuotaException::class);
    $metadataPath = $directory . '/' . $first['id'] . '.json';
    $metadata = json_decode(file_get_contents($metadataPath), true);
    $metadata['expires_epoch'] = 0;
    file_put_contents($metadataPath, json_encode($metadata));
    file_put_contents($directory . '/.upload-abandoned', 'partial');
    $second = upload($store);
    check(!file_exists($metadataPath), 'Expired transfer was not collected');
    check(!file_exists($directory . '/.upload-abandoned'), 'Incomplete upload was not collected');
    $lock = fopen($directory . '/.upload.lock', 'c');
    flock($lock, LOCK_EX);
    rejects(fn() => upload($store), SecretBox\StorageBusyException::class);
    fclose($lock);
    $store->delete($second['id']);
    rejects(fn() => upload($store, 65), LengthException::class);
    putenv('SECRETBOX_MAX_TOTAL_BYTES=4096');
    $small = SecretBox\TransferStore::fromEnvironment();
    rejects(fn() => upload($small), SecretBox\StorageQuotaException::class);
    putenv('SECRETBOX_MAX_BYTES=4096');
    putenv('SECRETBOX_MAX_TOTAL_BYTES=9000');
    putenv('SECRETBOX_MAX_TRANSFERS=100');
    $aggregate = SecretBox\TransferStore::fromEnvironment();
    upload($aggregate, 4096);
    rejects(fn() => upload($aggregate, 4096), SecretBox\StorageQuotaException::class);
    check(count(glob($directory . '/.upload-*')) === 0, 'Failed upload leaked a temporary file');
    echo "Storage quota, expiry collection, upload locking and failure cleanup passed.\n";
} finally {
    foreach (new DirectoryIterator($directory) as $entry) {
        if (!$entry->isDot()) {
            unlink($entry->getPathname());
        }
    }
    rmdir($directory);
}
