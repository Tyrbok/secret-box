<?php
declare(strict_types=1);

use SecretBox\TransferStore;

ini_set('display_errors', '0');
header('X-Content-Type-Options: nosniff');

require_once __DIR__ . '/../src/TransferStore.php';

function respond(int $status, array $body = []): void
{
    http_response_code($status);
    header('Cache-Control: no-store');
    if ($status !== 204) {
        header('Content-Type: application/json; charset=utf-8');
        echo json_encode($body, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
    }
    exit;
}

function configured_upload_token(): string
{
    $token = getenv('SECRETBOX_UPLOAD_TOKEN');
    if (is_string($token) && $token !== '') {
        return $token;
    }

    $configPath = getenv('SECRETBOX_UPLOAD_TOKEN_FILE') ?: '';
    if ($configPath === '') {
        $pointerPath = dirname(__DIR__) . '/.secretbox-config-path';
        if (!is_file($pointerPath) || !is_readable($pointerPath)) {
            return '';
        }
        $configPath = trim((string) file_get_contents($pointerPath));
    }
    $resolvedConfigPath = realpath($configPath);
    $siteRoot = realpath(dirname(__DIR__));
    if ($resolvedConfigPath === false || $siteRoot === false
        || !is_file($resolvedConfigPath) || !is_readable($resolvedConfigPath)) {
        return '';
    }
    $sitePrefix = rtrim($siteRoot, DIRECTORY_SEPARATOR) . DIRECTORY_SEPARATOR;
    if ($resolvedConfigPath === $siteRoot || strncmp($resolvedConfigPath, $sitePrefix, strlen($sitePrefix)) === 0) {
        return '';
    }
    $contents = file_get_contents($resolvedConfigPath);
    if ($contents === false) {
        return '';
    }
    $config = json_decode($contents, true);
    if (!is_array($config)) {
        return '';
    }
    // Missing schema_version identifies the legacy version 0 format.
    $schemaVersion = array_key_exists('schema_version', $config)
        ? $config['schema_version']
        : 0;
    if (!is_int($schemaVersion) || !in_array($schemaVersion, [0, 1], true)) {
        return '';
    }
    $token = $config['upload_token'] ?? '';
    return is_string($token) ? $token : '';
}

function require_instance_token(): void
{
    $expected = configured_upload_token();
    if (strlen($expected) < 32 || $expected === 'CHANGE_ME') {
        respond(503, ['error' => 'Server is not configured']);
    }
    $header = $_SERVER['HTTP_AUTHORIZATION'] ?? $_SERVER['REDIRECT_HTTP_AUTHORIZATION'] ?? '';
    if (!preg_match('/^Bearer\s+(.+)$/i', $header, $matches)
        || !hash_equals($expected, trim($matches[1]))) {
        respond(401, ['error' => 'Unauthorized']);
    }
}

$method = $_SERVER['REQUEST_METHOD'] ?? 'GET';
$requestPath = parse_url($_SERVER['REQUEST_URI'] ?? '/', PHP_URL_PATH) ?: '/';
$scriptName = $_SERVER['SCRIPT_NAME'] ?? '';
$basePath = rtrim(dirname($scriptName), '/');
if ($basePath !== '' && $basePath !== '.') {
    if ($requestPath === $basePath) {
        $requestPath = '/';
    } else {
        $basePrefix = $basePath . '/';
        if (strncmp($requestPath, $basePrefix, strlen($basePrefix)) === 0) {
            $requestPath = substr($requestPath, strlen($basePath));
        }
    }
}

if ($method === 'GET' && $requestPath === '/') {
    $token = configured_upload_token();
    respond(200, ['ok' => strlen($token) >= 32 && $token !== 'CHANGE_ME']);
}

if ($method === 'GET' && $requestPath === '/healthz') {
    respond(200, ['status' => 'ok']);
}

if ($method === 'POST' && $requestPath === '/api/v1/transfers') {
    require_instance_token();
    try {
        $contentType = strtolower($_SERVER['CONTENT_TYPE'] ?? '');
        if (strpos($contentType, 'multipart/form-data') === 0) {
            $upload = $_FILES['ciphertext'] ?? null;
            $uploadError = is_array($upload)
                ? ($upload['error'] ?? UPLOAD_ERR_NO_FILE)
                : UPLOAD_ERR_NO_FILE;
            if ($uploadError === UPLOAD_ERR_INI_SIZE || $uploadError === UPLOAD_ERR_FORM_SIZE) {
                respond(413, ['error' => 'Upload exceeds the limit allowed by PHP']);
            }
            if ($uploadError !== UPLOAD_ERR_OK) {
                respond(400, ['error' => 'No valid encrypted file was received']);
            }
            $temporary = $upload['tmp_name'] ?? null;
            if (!is_string($temporary) || !is_uploaded_file($temporary)) {
                respond(400, ['error' => 'No valid encrypted file was received']);
            }
            $input = fopen($temporary, 'rb');
        } else {
            $input = fopen('php://input', 'rb');
        }
        if ($input === false) {
            throw new RuntimeException('Could not read the uploaded content');
        }
        try {
            $store = TransferStore::fromEnvironment();
            $result = $store->create($input);
        } finally {
            fclose($input);
        }
        http_response_code(201);
        header('Cache-Control: no-store');
        header('Content-Type: application/json; charset=utf-8');
        echo json_encode($result, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
        exit;
    } catch (LengthException $exception) {
        respond(413, ['error' => $exception->getMessage()]);
    } catch (Throwable $exception) {
        error_log('secretbox upload failed: ' . $exception->getMessage());
        respond(500, ['error' => 'Could not store the transfer']);
    }
}

if (preg_match('#^/api/v1/transfers/([A-Za-z0-9_-]{32})$#', $requestPath, $matches)) {
    $id = $matches[1];
    try {
        if ($method === 'DELETE') {
            require_instance_token();
        }
        $store = TransferStore::fromEnvironment();
        if ($method === 'GET') {
            $file = $store->pathForDownload($id);
            if ($file === null) {
                respond(404, ['error' => 'Transfer not found or expired']);
            }
            header('Cache-Control: no-store, private');
            header('Content-Type: application/octet-stream');
            header('Content-Length: ' . filesize($file));
            header('Content-Disposition: attachment; filename="secretbox.age"');
            readfile($file);
            exit;
        }
        if ($method === 'DELETE') {
            if (!$store->delete($id)) {
                respond(404, ['error' => 'Transfer not found']);
            }
            respond(204);
        }
    } catch (Throwable $exception) {
        error_log('secretbox transfer request failed: ' . $exception->getMessage());
        respond(500, ['error' => 'Internal server error']);
    }
}

respond(404, ['error' => 'Route not found']);

