<?php
declare(strict_types=1);

if (PHP_SAPI !== 'cli') {
    http_response_code(404);
    exit(1);
}

function stop(string $message): void
{
    fwrite(STDERR, "secret-box setup: {$message}\n");
    exit(1);
}

$siteRoot = realpath(dirname(__DIR__));
$home = getenv('HOME') ?: '';
$home = $home !== '' ? realpath($home) : false;
if ($siteRoot === false || $home === false) {
    stop('Could not determine the site root or HOME directory.');
}
if ((getenv('SECRETBOX_UPLOAD_TOKEN') ?: '') !== ''
    || (getenv('SECRETBOX_UPLOAD_TOKEN_FILE') ?: '') !== '') {
    stop('An active configuration environment variable already exists; refusing to overwrite it.');
}

$configDirectory = $home . '/.config/secretbox';
$configPath = $configDirectory . '/server.json';
$pointerPath = $siteRoot . '/.secretbox-config-path';
$htaccessPath = $siteRoot . '/.htaccess';
if (file_exists($configPath) || is_link($configPath)
    || file_exists($pointerPath) || is_link($pointerPath)) {
    stop('Configuration already exists; refusing to overwrite it.');
}
$existingHtaccess = null;
if (is_file($htaccessPath)) {
    if (!is_readable($htaccessPath) || !is_writable($htaccessPath)) {
        stop('The site .htaccess must be readable and writable by this user.');
    }
    $existingHtaccess = file_get_contents($htaccessPath);
    if ($existingHtaccess === false) {
        stop('Could not read the existing .htaccess.');
    }
    if (preg_match('/^[ \t]*SetEnv[ \t]+SECRETBOX_UPLOAD_TOKEN(?:_FILE)?[ \t]+/mi', $existingHtaccess)) {
        stop('.htaccess already defines the token. Remove that directive before using this configurator.');
    }
}

$oldUmask = umask(0077);
if (!is_dir($configDirectory) && !mkdir($configDirectory, 0700, true) && !is_dir($configDirectory)) {
    umask($oldUmask);
    stop('Could not create ~/.config/secretbox.');
}
umask($oldUmask);
$configDirectory = realpath($configDirectory);
if ($configDirectory === false) {
    stop('Could not resolve the private directory.');
}
$sitePrefix = rtrim($siteRoot, DIRECTORY_SEPARATOR) . DIRECTORY_SEPARATOR;
if ($configDirectory === $siteRoot || strncmp($configDirectory, $sitePrefix, strlen($sitePrefix)) === 0) {
    stop('The secrets file must be outside the web root.');
}
if (!chmod($configDirectory, 0700)) {
    stop('Could not restrict permissions on the private directory.');
}

$configPath = $configDirectory . '/server.json';

$managedRules = <<<'HTACCESS'
# BEGIN secretbox bootstrap rules
Options -Indexes
<IfModule mod_rewrite.c>
    RewriteEngine On
    RewriteCond %{HTTP:Authorization} .
    RewriteRule .* - [E=HTTP_AUTHORIZATION:%{HTTP:Authorization}]
    RewriteRule ^(src|bin)(/|$) - [F,L]
    RewriteCond %{REQUEST_FILENAME} !-f
    RewriteCond %{REQUEST_FILENAME} !-d
    RewriteRule ^ index.php [QSA,L]
</IfModule>
<FilesMatch "^\.">
    Require all denied
</FilesMatch>
# END secretbox bootstrap rules
HTACCESS;

if ($existingHtaccess !== null) {
    $htaccess = $existingHtaccess;
    if (strpos($htaccess, '# BEGIN secretbox bootstrap rules') === false) {
        $htaccess = rtrim($htaccess) . "\n\n" . $managedRules . "\n";
        if (file_put_contents($htaccessPath, $htaccess, LOCK_EX) === false) {
            stop('Could not add the security and routing rules to .htaccess.');
        }
    }
} else {
    if (file_put_contents($htaccessPath, $managedRules . "\n", LOCK_EX) === false) {
        stop('Could not create the site .htaccess.');
    }
}

try {
    $token = bin2hex(random_bytes(32));
} catch (Throwable $exception) {
    stop('Could not generate a secure random token.');
}
$configContents = json_encode(
    ['schema_version' => 1, 'upload_token' => $token],
    JSON_UNESCAPED_SLASHES
) . "\n";
$pointerContents = $configPath . "\n";

$oldUmask = umask(0077);
$configHandle = fopen($configPath, 'x');
if ($configHandle === false) {
    umask($oldUmask);
    stop('Could not create the private server.json file.');
}
$pointerHandle = fopen($pointerPath, 'x');
if ($pointerHandle === false) {
    fclose($configHandle);
    @unlink($configPath);
    umask($oldUmask);
    stop('Could not create the site configuration pointer.');
}
$configWritten = fwrite($configHandle, $configContents) === strlen($configContents);
$pointerWritten = fwrite($pointerHandle, $pointerContents) === strlen($pointerContents);
fclose($configHandle);
fclose($pointerHandle);
chmod($configPath, 0600);
chmod($pointerPath, 0600);
umask($oldUmask);

if (!$configWritten || !$pointerWritten
    || fileperms($configPath) === false || (fileperms($configPath) & 0777) !== 0600
    || fileperms($pointerPath) === false || (fileperms($pointerPath) & 0777) !== 0600) {
    @unlink($configPath);
    @unlink($pointerPath);
    stop('Could not write the complete configuration; partial files were removed.');
}

fwrite(STDOUT, "Configuration created outside the web root: {$configPath}\n");
fwrite(STDOUT, "Enter this token with sb configure on authorized clients:\n\n");
fwrite(STDOUT, $token . "\n");
fwrite(STDOUT, "Save it now: the script will not show it again or overwrite the configuration.\n");

