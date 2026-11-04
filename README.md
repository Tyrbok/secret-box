# secret-box

Sistema personal para enviar texto, archivos y carpetas entre máquinas. El CLI cifra el paquete con [`age`](https://age-encryption.org/) antes de subirlo. El servidor PHP almacena y sirve el archivo cifrado; no recibe la passphrase ni la clave privada.

## Componentes

- `client/`: CLI en Python. Usa la herramienta `age` instalada en el sistema.
- `server/`: API HTTP en PHP, sin dependencias de Composer.
- `contracts/`: contrato de la API.
- `docs/`: arquitectura, amenazas y operación.
- `deploy/`: Docker Compose y Caddy para desplegar el servidor.

## Requisitos del CLI

- Python 3.11 o posterior.
- [`uv`](https://docs.astral.sh/uv/) para instalar el CLI en un entorno aislado.
- `age` y `age-keygen` disponibles en `PATH`.
- PHP 8.1 o posterior en el servidor.

Instala age siguiendo las [instrucciones oficiales](https://age-encryption.org/install).

Instala el CLI desde la raíz del repositorio:

```sh
make client/install
sb configure
```

El comando instalado es `sb`.

Los targets `client/install` y `dev/setup` usan `uv tool install`, que mantiene el CLI en un entorno aislado del Python de Homebrew. `dev/setup` instala el checkout en modo editable.

`sb configure` pide la URL del servidor y el token de subida ya configurado allí. El token debe ser idéntico en el servidor y en cada CLI autorizado para subir o borrar envíos. La configuración local queda en `~/.config/secretbox/config.json` con permisos privados.

## Desplegar el servidor

```sh
cp deploy/.env.example deploy/.env
```

Edita `deploy/.env` y establece `SECRETBOX_UPLOAD_TOKEN`. Puedes generarlo con:

```sh
openssl rand -hex 32
```

Genera el token con `openssl rand -hex 32` y guárdalo en `deploy/.env`. Después introduce ese mismo valor al ejecutar `sb configure` en cada cliente autorizado.

Para desarrollo local, deja `SECRETBOX_DOMAIN=:8080`. Para producción, pon un dominio público y apunta sus registros DNS a este servidor. Caddy termina HTTPS automáticamente cuando se usa un dominio válido.

```sh
docker compose --env-file deploy/.env -f deploy/compose.yaml up --build -d
```

El volumen `secretbox-data` conserva los envíos. Elimina los caducados con:

```sh
docker compose --env-file deploy/.env -f deploy/compose.yaml exec php php /var/www/html/bin/cleanup.php
```

Programa ese comando con cron o un temporizador del sistema. Consulta [operación y despliegue](docs/operations.md).

## Uso

Envío protegido por passphrase aleatoria generada por age:

```sh
sb send ./informe.pdf
sb send ./carpeta
sb send --text
```

`sb send --text` lee de la entrada estándar. Puedes pegar varias líneas y finalizar con `Ctrl-D`:

```sh
sb send --text < mensaje.txt
```

Age mostrará una passphrase generada. Compártela por un canal distinto al identificador del envío. Después, envía el identificador que imprime `sb`.

Recepción:

```sh
sb receive IDENTIFICADOR
```

Para guardar texto en un archivo o cambiar el destino de un archivo/carpeta:

```sh
sb receive IDENTIFICADOR --output ./destino
```

Para tus propios dispositivos, genera una identidad en cada equipo receptor:

```sh
sb keygen --name portatil
```

Guarda la clave privada en el equipo que descifrará el envío y comparte la clave pública `age1...` con los emisores. Envía cifrando para esa clave:

```sh
sb send --recipient age1... ./informe.pdf
sb receive IDENTIFICADOR --identity ~/.config/secretbox/identities/portatil.txt
```

Borra un envío antes de que caduque:

```sh
sb delete IDENTIFICADOR
```

El formato de transferencia y sus límites están descritos en [la arquitectura](docs/architecture.md) y [el modelo de amenazas](docs/threat-model.md).

Para sincronizar `server/` con el script personal `ss`, configura `server/.sisy.json` a partir de `server/.sisy.example.json` y ejecuta `make server/sync`. La configuración real está ignorada por Git; su lista `exclude` evita subir credenciales, datos locales, archivos de desarrollo y utilidades no destinadas al webroot. El target ejecuta el modo de subida de `ss`, que sincroniza con `rsync --delete`.

### DreamHost Shared

Después de configurar `server/.sisy.json`, sincroniza el servidor desde tu Mac:

```sh
make server/sync
```

Entra por SSH, cambia al directorio webroot al que sincroniza `ss` y ejecuta el configurador una sola vez:

```sh
php bin/configure.php
```

El script genera un token aleatorio de 32 bytes y lo guarda en `~/.config/secretbox/server.json`, fuera del webroot, con permisos `600` (el directorio queda en `700`). Imprime el token una vez para que lo introduzcas al ejecutar `sb configure` en cada cliente autorizado. También crea `.secretbox-config-path`, que solo contiene la ruta al JSON privado, y añade reglas de Apache para enrutar la API y bloquear el acceso web a los archivos ocultos, `src/` y `bin/`. El `.htaccess` y el puntero quedan excluidos de `ss`, así que futuras sincronizaciones no los reemplazan ni eliminan. Las transferencias también se guardan fuera del webroot, junto a la configuración privada.

El configurador solo funciona desde CLI y se detiene si ya existe el archivo de configuración, su puntero o una directiva `SetEnv` para el token en `.htaccess`. Si habías añadido esa directiva siguiendo una configuración manual anterior, quítala antes de ejecutar el script. El PHP de SSH puede ser distinto del que usa el sitio web: el configurador admite PHP 7.1 o posterior, pero la aplicación web necesita PHP 8.1 o posterior. Para otra instalación, ejecuta el script en el webroot de esa instalación.

