# Arquitectura

## Flujo

1. El CLI crea un paquete `tar.gz` con un manifiesto cifrable. El paquete identifica el tipo de contenido y guarda el nombre original dentro del cifrado.
2. `age` cifra el paquete. Se puede usar una passphrase para un envío puntual o la clave pública age de un dispositivo receptor.
3. El CLI sube el archivo age por HTTPS con un token de instancia. La API devuelve un identificador aleatorio y una fecha de caducidad.
4. El receptor descarga el ciphertext con el identificador y lo descifra localmente con `age`.
5. El CLI valida el paquete y extrae archivos y carpetas en una ubicación nueva, sin seguir enlaces simbólicos ni rutas que salgan del destino. En v1 el envío falla si la carpeta de origen contiene enlaces simbólicos o archivos especiales.

El servidor no interpreta el formato age ni el manifiesto. No se almacena una clave de descifrado en el servidor.

## Cifrado y claves

- Se usa el formato age existente, no un formato criptográfico propio.
- La passphrase por defecto se genera interactivamente por age. Hay que compartirla por un canal distinto al identificador.
- Para dispositivos propios, cada receptor puede tener una identidad age y publicar su clave pública. La clave privada permanece en el equipo receptor.
- El contenido incluye integridad autenticada. Una modificación del ciphertext hace que age falle al descifrar.
- No se añade una firma de remitente. Cualquiera que posea la passphrase o una clave destinataria puede crear un ciphertext válido. Si se necesita acreditar quién envió algo, habrá que añadir una firma de clave pública con un flujo separado.

## API v1

- `POST /api/v1/transfers`: requiere `Authorization: Bearer <token>`, recibe el ciphertext como archivo en una petición multipart/form-data y devuelve `{ "id", "size", "created_at", "expires_at" }`.
- `GET /api/v1/transfers/{id}`: devuelve el ciphertext. El ID es una capacidad aleatoria de descarga; no hay listado público.
- `DELETE /api/v1/transfers/{id}`: requiere el token de instancia y elimina el contenido.
- `GET /healthz`: estado básico, sin datos de transferencias.
- La API admite instalación bajo una subruta, como `/sites/secret-box`; el servidor elimina ese prefijo antes de enrutar.

Los IDs se generan con 24 bytes aleatorios y se codifican en Base64 URL-safe sin padding. El servidor guarda el ciphertext y un sidecar JSON con tamaño y caducidad. El almacenamiento está fuera del directorio público.

## Límites iniciales

- Límite de subida configurable; por defecto 100 MiB.
- Caducidad configurable; por defecto 24 horas.
- El GET no requiere token para permitir que otro equipo descargue el ciphertext. El ID debe tratarse como secreto, aunque por sí solo no permite descifrar.
- No hay panel web, cuentas, listado, firma del remitente ni descarga de un solo uso en v1.
- El servidor puede ver IP, hora, tamaño y frecuencia de las transferencias; puede borrar o retener ciphertext. No puede recuperar el contenido si las claves y passphrases se mantienen fuera del servidor.

