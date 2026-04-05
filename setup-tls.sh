#!/bin/bash
set -e

echo "Setting up TLS for Forgejo..."

# Wait for Caddy to start and generate certificates
echo "Waiting for Caddy to generate CA certificate..."
until docker exec forgejo-caddy cat /data/caddy/pki/authorities/local/root.crt > /dev/null 2>&1; do
    echo "Caddy not ready, waiting..."
    sleep 2
done

# Extract the CA certificate
echo "Extracting Caddy CA certificate..."
docker exec forgejo-caddy cat /data/caddy/pki/authorities/local/root.crt > caddy-ca.crt

echo "CA certificate saved to caddy-ca.crt"

# Restart the runner to load the new certificate
echo "Restarting runner to load CA certificate..."
docker compose restart runner

echo "TLS setup complete!"
echo ""
echo "To trust the certificate on your client:"
echo "  Linux:   sudo cp caddy-ca.crt /usr/local/share/ca-certificates/ && sudo update-ca-certificates"
echo "  macOS:   sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain caddy-ca.crt"
echo ""
echo "Access Forgejo at: https://kalameet"
