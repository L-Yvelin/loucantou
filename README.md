# loucantou

A B&B website for a French B&B business!

## Lighthouse score

![image](https://github.com/user-attachments/assets/d3c5383b-c0f4-4e42-8033-c9ee3861fa95)

## Apache conf

```apache
<IfModule mod_ssl.c>
<VirtualHost *:443>
Protocols h2 http/1.1
DocumentRoot /var/www/html/loucantou.yvelin.net/
ServerName loucantou.yvelin.net
ServerAlias www.loucantou.yvelin.net

<Directory /var/www/html/loucantou.yvelin.net/>
    Options -Indexes
    AllowOverride None
    Require all granted

    # Caching rules for different file types
    <FilesMatch "\.(jpg|jpeg|png|gif|webp|svg|ico)$">
        ExpiresActive On
        ExpiresDefault "access plus 1 year"
        Header set Cache-Control "public, max-age=31536000, immutable"
    </FilesMatch>

    <FilesMatch "\.html$">
        ExpiresActive On
        ExpiresDefault "access plus 0 seconds"
        Header set Cache-Control "no-cache, no-store, must-revalidate"
        Header set Pragma "no-cache"
        Header set Expires 0
    </FilesMatch>

    <FilesMatch "\.(js|css)$">
        ExpiresActive On
        ExpiresDefault "access plus 1 week"
        Header set Cache-Control "public, max-age=604800"
    </FilesMatch>

    <FilesMatch "\.webmanifest$">
        ExpiresActive On
        ExpiresDefault "access plus 1 week"
        Header set Cache-Control "public, max-age=604800"
    </FilesMatch>

    <FilesMatch "\.(woff|woff2|ttf|otf|eot)$">
        ExpiresActive On
        ExpiresDefault "access plus 1 year"
        Header set Cache-Control "public, max-age=31536000, immutable"
    </FilesMatch>
</Directory>

<Location /logs/>
    RewriteEngine On
    RewriteCond %{QUERY_STRING} !(^|&)api_key=YOUR_API_KEY(&|$) [NC]
    RewriteRule ^ - [F]
</Location>

Include /etc/letsencrypt/options-ssl-apache.conf

CustomLog /var/www/html/loucantou.yvelin.net/logs/loucantou-access.log combined
ErrorLog /var/www/html/loucantou.yvelin.net/logs/loucantou-error.log
SSLCertificateFile /etc/letsencrypt/live/yvelin.net/fullchain.pem
SSLCertificateKeyFile /etc/letsencrypt/live/yvelin.net/privkey.pem
</VirtualHost>
</IfModule>
```
