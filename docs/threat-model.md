# Modelo de amenazas

## Protege

- La confidencialidad del contenido frente al operador del servidor, al proveedor de hosting y a quien obtenga solo una copia del almacenamiento.
- La integridad del ciphertext durante almacenamiento y transporte, mediante age y HTTPS.
- El acceso casual a descargas, mediante IDs aleatorios difíciles de adivinar.

## No protege

- Un equipo emisor o receptor comprometido, malware, capturas de pantalla o una clave privada copiada.
- Una passphrase débil o compartida junto al ID por el mismo canal. Usa la passphrase aleatoria de age o una clave pública de destinatario.
- La disponibilidad. El servidor puede estar apagado, borrar un envío o aplicar sus límites de almacenamiento.
- La privacidad de metadatos de red. El servidor y el proxy ven IP, hora, tamaño aproximado y caducidad.
- La identidad del remitente. La passphrase compartida no permite distinguir qué participante creó un envío.

## Decisiones operativas

- Publica la API detrás de HTTPS. No expongas PHP-FPM directamente a Internet.
- Genera un token de instancia aleatorio de al menos 32 bytes y guárdalo en el servidor y en la configuración privada de cada CLI que pueda subir o borrar.
- Mantén el almacenamiento fuera del webroot y con permisos restringidos al usuario PHP.
- No registres tokens en logs. Trata los IDs como enlaces de capacidad y limita la retención de logs del proxy.
- El descifrado y la extracción ocurren localmente. El CLI rechaza rutas de archivo peligrosas y enlaces simbólicos en paquetes recibidos.
- El CLI guarda temporalmente el ciphertext y el paquete descifrado bajo un directorio temporal privado y los elimina al terminar. El borrado de archivos no garantiza saneamiento físico en SSD, snapshots o copias de seguridad.

