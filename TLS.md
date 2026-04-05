# TLS/HTTPS Setup

This setup uses Caddy as a reverse proxy with self-signed certificates for HTTPS.

## Initial Setup

Run the automated setup script:
```bash
./setup-tls.sh
```

This will:
- Start Caddy and wait for it to generate the CA certificate
- Extract the CA certificate to `caddy-ca.crt`
- Restart the runner to trust the new certificate

## Manual Setup

If you prefer to do it manually:

1. Start the containers:
   ```bash
   docker compose up -d
   ```

2. Extract the Caddy CA certificate:
   ```bash
   docker exec forgejo-caddy cat /data/caddy/pki/authorities/local/root.crt > caddy-ca.crt
   ```

3. Restart the runner to load the CA certificate:
   ```bash
   docker compose restart runner
   ```

## Trusting the Certificate

### On Clients (Browsers)

The self-signed certificate will show security warnings in browsers. To trust it:

1. Copy `caddy-ca.crt` from the server
2. Import it into your browser's certificate authorities

### On Linux Systems

```bash
sudo cp caddy-ca.crt /usr/local/share/ca-certificates/
sudo update-ca-certificates
```

### On macOS

```bash
sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain caddy-ca.crt
```

## Notes

- Port 3000 (Forgejo direct access) is now internal only
- Access Forgejo at `https://kalameet`
- SSH Git access uses port 2222

### SSH Config

To make SSH Git access easier, add to `~/.ssh/config`:

```
Host kalameet
    HostName kalameet
    Port 2222
    User git
    IdentityFile ~/.ssh/id_ed25519
```
