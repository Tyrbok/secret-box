<?php
declare(strict_types=1);

// Internal FastCGI preflight. This file is outside Caddy's document root.
if (PHP_SAPI !== 'fpm-fcgi') {
    http_response_code(404);
    exit;
}
ini_set('display_errors', '0');
header('Cache-Control: no-store');
require __DIR__ . '/../src/UploadTokens.php';
try {
    $config = SecretBox\UploadTokens::load();
    $header = $_SERVER['HTTP_AUTHORIZATION'] ?? '';
    http_response_code(!SecretBox\UploadTokens::configured($config) ? 503
        : (SecretBox\UploadTokens::accepts($config, $header) ? 204 : 401));
} catch (Throwable $exception) {
    http_response_code(503);
}
