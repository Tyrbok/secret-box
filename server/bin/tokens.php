<?php
declare(strict_types=1);

if (PHP_SAPI !== 'cli') {
    http_response_code(404);
    exit(1);
}
if (PHP_VERSION_ID < 80100) {
    fwrite(STDERR, "Token management requires PHP 8.1 or later.\n");
    exit(1);
}
require __DIR__ . '/../src/UploadTokens.php';

use SecretBox\UploadTokens;

try {
    $command = $argv[1] ?? '';
    $name = $argv[2] ?? '';
    if (!in_array($command, ['init', 'migrate', 'add', 'list', 'revoke'], true)
        || count($argv) > 3 || (in_array($command, ['migrate', 'list'], true) && $name !== '')) {
        throw new RuntimeException('Usage: php bin/tokens.php init [name] | migrate | add <name> | list | revoke <name>');
    }
    if ($command === 'init' && $name === '') {
        $name = 'default';
    }
    if (in_array($command, ['init', 'add', 'revoke'], true) && !UploadTokens::validName($name)) {
        throw new RuntimeException('Token name must contain 1-64 letters, digits, hyphens or underscores and start with a letter');
    }
    $path = UploadTokens::configurationPath();
    if ($path === null) {
        throw new RuntimeException('Run bin/configure.php first, or set SECRETBOX_UPLOAD_TOKEN_FILE to a private path');
    }
    if (!is_dir(dirname($path)) && !mkdir(dirname($path), 0700, true) && !is_dir(dirname($path))) {
        throw new RuntimeException('Could not create private configuration directory');
    }
    UploadTokens::validatePath($path);
    $permissions = fileperms(dirname($path));
    if ($permissions === false || ($permissions & 0077) !== 0) {
        throw new RuntimeException('Configuration directory must be private (mode 0700); use a dedicated directory');
    }
    if (is_link($path . '.lock')) {
        throw new RuntimeException('Refusing a symbolic link for the configuration lock');
    }
    $lock = fopen($path . '.lock', 'c');
    if ($lock === false) {
        throw new RuntimeException('Could not open configuration lock');
    }
    try {
        if (!chmod($path . '.lock', 0600) || !flock($lock, LOCK_EX)) {
            throw new RuntimeException('Could not lock configuration');
        }
        if ($command === 'init') {
            if (file_exists($path)) {
                throw new RuntimeException('Configuration already exists; refusing to overwrite it');
            }
            $config = ['schema_version' => 2, 'upload_tokens' => []];
        } elseif ($command === 'migrate' && !file_exists($path)) {
            $config = ['upload_token' => getenv('SECRETBOX_UPLOAD_TOKEN') ?: ''];
        } else {
            $config = UploadTokens::read($path);
        }
        if ($command === 'migrate') {
            UploadTokens::write($path, UploadTokens::migrate($config));
            fwrite(STDOUT, "Server configuration is version 2. Existing credentials were preserved.\n");
        } else {
            if (($config['schema_version'] ?? 0) !== 2) {
                throw new RuntimeException('Run php bin/tokens.php migrate before managing legacy tokens');
            }
            if ($command === 'list') {
                fwrite(STDOUT, "NAME\tCREATED_AT\n");
                foreach ($config['upload_tokens'] as $label => $record) {
                    fwrite(STDOUT, $label . "\t" . $record['created_at'] . "\n");
                }
            } elseif ($command === 'revoke') {
                if (!array_key_exists($name, $config['upload_tokens'])) {
                    throw new RuntimeException('Unknown token name');
                }
                unset($config['upload_tokens'][$name]);
                UploadTokens::write($path, $config);
                fwrite(STDOUT, "Revoked token: {$name}\n");
            } else {
                if (array_key_exists($name, $config['upload_tokens']) || count($config['upload_tokens']) >= UploadTokens::MAX_TOKENS) {
                    throw new RuntimeException('Token name already exists or the 100-token limit has been reached');
                }
                $token = bin2hex(random_bytes(32));
                $config['upload_tokens'][$name] = ['sha256' => hash('sha256', $token), 'created_at' => gmdate(DATE_ATOM)];
                UploadTokens::write($path, $config);
                fwrite(STDOUT, "Token for {$name}; save it now and enter it with sb configure:\n{$token}\n");
            }
        }
    } finally {
        fclose($lock);
    }
} catch (Throwable $exception) {
    fwrite(STDERR, 'secretbox tokens: ' . $exception->getMessage() . "\n");
    exit(1);
}
