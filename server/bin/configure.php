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
    stop('No pude determinar la raíz del sitio o el directorio HOME.');
}
if ((getenv('SECRETBOX_UPLOAD_TOKEN') ?: '') !== ''
    || (getenv('SECRETBOX_UPLOAD_TOKEN_FILE') ?: '') !== '') {
    stop('Ya hay una variable de entorno de configuración activa. No la sobrescribo.');
}

$configDirectory = $home . '/.config/secretbox';
$configPath = $configDirectory . '/server.json';
$pointerPath = $siteRoot . '/.secretbox-config-path';
$htaccessPath = $siteRoot . '/.htaccess';
if (file_exists($configPath) || is_link($configPath)
    || file_exists($pointerPath) || is_link($pointerPath)) {
    stop('Ya existe una configuración. No la sobrescribo.');
}
$existingHtaccess = null;
if (is_file($htaccessPath)) {
    if (!is_readable($htaccessPath) || !is_writable($htaccessPath)) {
        stop('El .htaccess del sitio debe poder leerse y modificarse por este usuario.');
    }
    $existingHtaccess = file_get_contents($htaccessPath);
    if ($existingHtaccess === false) {
        stop('No pude leer el .htaccess existente.');
    }
    if (preg_match('/^[ \t]*SetEnv[ \t]+SECRETBOX_UPLOAD_TOKEN(?:_FILE)?[ \t]+/mi', $existingHtaccess)) {
        stop('El .htaccess ya define el token. Retira esa directiva antes de usar este configurador.');
    }
}

$oldUmask = umask(0077);
if (!is_dir($configDirectory) && !mkdir($configDirectory, 0700, true) && !is_dir($configDirectory)) {
    umask($oldUmask);
    stop('No pude crear ~/.config/secretbox.');
}
umask($oldUmask);
$configDirectory = realpath($configDirectory);
if ($configDirectory === false) {
    stop('No pude resolver el directorio privado.');
}
$sitePrefix = rtrim($siteRoot, DIRECTORY_SEPARATOR) . DIRECTORY_SEPARATOR;
if ($configDirectory === $siteRoot || strncmp($configDirectory, $sitePrefix, strlen($sitePrefix)) === 0) {
    stop('El archivo de secretos debe quedar fuera del webroot.');
}
if (!chmod($configDirectory, 0700)) {
    stop('No pude restringir los permisos del directorio privado.');
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
            stop('No pude añadir las reglas de seguridad y rutas al .htaccess.');
        }
    }
} else {
    if (file_put_contents($htaccessPath, $managedRules . "\n", LOCK_EX) === false) {
        stop('No pude crear el .htaccess del sitio.');
    }
}

try {
    $token = bin2hex(random_bytes(32));
} catch (Throwable $exception) {
    stop('No pude generar un token aleatorio seguro.');
}
$configContents = json_encode(['upload_token' => $token], JSON_UNESCAPED_SLASHES) . "\n";
$pointerContents = $configPath . "\n";

$oldUmask = umask(0077);
$configHandle = fopen($configPath, 'x');
if ($configHandle === false) {
    umask($oldUmask);
    stop('No pude crear el archivo privado server.json.');
}
$pointerHandle = fopen($pointerPath, 'x');
if ($pointerHandle === false) {
    fclose($configHandle);
    @unlink($configPath);
    umask($oldUmask);
    stop('No pude crear el puntero de configuración del sitio.');
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
    stop('No pude escribir la configuración completa; eliminé los archivos parciales.');
}

fwrite(STDOUT, "Configuración creada fuera del webroot: {$configPath}\n");
fwrite(STDOUT, "Copia este token a `sb configure` en los clientes autorizados:\n\n");
fwrite(STDOUT, $token . "\n");
fwrite(STDOUT, "Guárdalo ahora: el script no lo volverá a mostrar ni sobrescribirá la configuración.\n");

