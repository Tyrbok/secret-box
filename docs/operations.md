# Operación

## Requisitos del servidor

- Docker Compose.
- PHP 8.1 o posterior para el servidor.
- Un dominio con DNS apuntando al servidor para producción, y los puertos 80/443 accesibles para Caddy.
- Un volumen persistente para `secretbox-data` y espacio libre suficiente.

## Configuración

Copia `deploy/.env.example` a `deploy/.env`, establece `SECRETBOX_UPLOAD_TOKEN` y configura el dominio. Genera el token con `openssl rand -hex 32` y usa el mismo valor en el servidor y en cada CLI autorizado para subir o borrar. El archivo `.env` está excluido de Git.

La configuración del CLI se guarda en `~/.config/secretbox/config.json` con permisos `0600`. Las identidades age creadas con `sb keygen` se guardan en `~/.config/secretbox/identities/` con permisos `0600`.

## DreamHost Shared

Después de sincronizar `server/` con `make server/sync`, entra por SSH al webroot y ejecuta `php bin/configure.php`. El script es solo CLI y de un solo uso: genera un token de 32 bytes, crea `~/.config/secretbox/server.json` fuera del webroot con permisos `600`, crea el directorio privado con permisos `700`, y guarda una referencia sin el secreto en `.secretbox-config-path`. Añade reglas de Apache para las rutas de la API y para impedir el acceso web a archivos ocultos, `src/` y `bin/`. Si aún tienes una directiva `SetEnv` para el token en `.htaccess` de una configuración manual previa, quítala antes de ejecutar el script. Si ya configuraste el servidor antes del reenvío de Authorization, añade las reglas de reescritura del ejemplo al `.htaccess` remoto, justo después de `RewriteEngine On`; ese archivo se excluye de `ss` y no se actualiza con la sincronización.

Copia el token que imprime el script y úsalo al configurar cada cliente autorizado con `sb configure`. Las transferencias se guardan fuera del webroot, en el directorio privado de configuración. Las exclusiones de `server/.sisy.json` conservan `.htaccess` y `.secretbox-config-path` durante la sincronización con `rsync --delete`, y dejan fuera el propio `.sisy.json` y su ejemplo.

## Caducidad

El servidor rechaza descargas caducadas y elimina esos archivos al intentar descargarlos. También ofrece `bin/cleanup.php` para borrar transferencias caducadas sin esperar una descarga. Programa su ejecución periódica:

```cron
*/15 * * * * docker compose --env-file /ruta/secret-box/deploy/.env -f /ruta/secret-box/deploy/compose.yaml exec -T php php /var/www/html/bin/cleanup.php
```

## Copias de seguridad

El volumen solo contiene ciphertext y metadatos de transferencia. Una copia permite restaurar envíos aún vigentes, pero no sustituye las claves privadas ni las passphrases de los usuarios.

## Desarrollo local del servidor

Desde la raíz, define un token solo para desarrollo y arranca el servidor integrado de PHP:

```sh
export SECRETBOX_UPLOAD_TOKEN="$(openssl rand -hex 32)"
export SECRETBOX_STORAGE_DIR="/tmp/secretbox-data"
php -S 127.0.0.1:8080 -t server/public server/public/index.php
```

Configura el CLI con `http://127.0.0.1:8080`. No uses HTTP en una red pública.

