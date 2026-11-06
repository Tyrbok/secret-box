FROM php:8.3-fpm-alpine

WORKDIR /var/www/html
COPY public/ ./public/
COPY src/ ./src/
COPY bin/ ./bin/
COPY .user.ini.example /usr/local/etc/php/conf.d/secretbox.ini
RUN mkdir -p /var/lib/secretbox \
    && chown -R www-data:www-data /var/lib/secretbox /var/www/html

