<?php
declare(strict_types=1);

use SecretBox\TransferStore;

ini_set('display_errors', '0');
header('X-Content-Type-Options: nosniff');

require_once __DIR__ . '/../src/TransferStore.php';
require_once __DIR__ . '/../src/UploadTokens.php';

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

function require_instance_token(): void
{
    try {
        $config = SecretBox\UploadTokens::load();
        if (!SecretBox\UploadTokens::configured($config)) {
            respond(503, ['error' => 'Server is not configured']);
        }
    } catch (Throwable $exception) {
        respond(503, ['error' => 'Server is not configured']);
    }
    $header = $_SERVER['HTTP_AUTHORIZATION'] ?? $_SERVER['REDIRECT_HTTP_AUTHORIZATION'] ?? '';
    if (!SecretBox\UploadTokens::accepts($config, $header)) {
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
    try {
        $ready = SecretBox\UploadTokens::configured(SecretBox\UploadTokens::load());
    } catch (Throwable $exception) {
        $ready = false;
    }
    respond(200, ['ok' => $ready]);
}

if ($method === 'GET' && $requestPath === '/healthz') {
    respond(200, ['status' => 'ok']);
}

if ($method === 'GET' && $requestPath === '/api/v1/transfers') {
    $after = $_GET['after'] ?? '';
    if (!is_string($after) || ($after !== '' && !preg_match('/^[A-Za-z0-9_-]{32}$/D', $after))) {
        respond(400, ['error' => 'Invalid listing cursor']);
    }
    try {
        respond(200, TransferStore::fromEnvironment()->listing($after));
    } catch (Throwable $exception) {
        error_log('secretbox listing failed: ' . $exception->getMessage());
        respond(500, ['error' => 'Could not list transfers']);
    }
}

if ($method === 'POST' && $requestPath === '/api/v1/transfers') {
    require_instance_token();
    try {
        $listable = $_POST['listable'] ?? 'false';
        if (!is_string($listable) || !in_array($listable, ['true', 'false'], true)) {
            respond(400, ['error' => 'listable must be true or false']);
        }
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
            $result = $store->create($input, $listable === 'true');
        } finally {
            fclose($input);
        }
        http_response_code(201);
        header('Cache-Control: no-store');
        header('Content-Type: application/json; charset=utf-8');
        echo json_encode($result, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
        exit;
    } catch (\SecretBox\StorageBusyException $exception) {
        header('Retry-After: 1');
        respond(429, ['error' => $exception->getMessage()]);
    } catch (\SecretBox\StorageQuotaException $exception) {
        respond(507, ['error' => $exception->getMessage()]);
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

