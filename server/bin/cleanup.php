<?php
declare(strict_types=1);

if (PHP_SAPI !== 'cli') {
    http_response_code(404);
    exit(1);
}

require_once __DIR__ . '/../src/TransferStore.php';

$store = SecretBox\TransferStore::fromEnvironment();
$deleted = 0;
foreach ($store->expiredIds() as $id) {
    if ($store->delete($id)) {
        $deleted++;
    }
}
fwrite(STDOUT, "Deleted {$deleted} expired transfers.\n");

