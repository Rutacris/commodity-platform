#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# Generate a self-signed SSL certificate for local use.
# Run once from the project root: bash nginx/generate-ssl.sh
# ─────────────────────────────────────────────────────────────────────────────

set -e

SSL_DIR="$(dirname "$0")/ssl"
mkdir -p "$SSL_DIR"

# Read server IP from .env if present, otherwise use a default
SERVER_IP=$(grep DOMAIN .env 2>/dev/null | cut -d= -f2 | tr -d ' ')
SERVER_IP=${SERVER_IP:-192.168.0.100}

echo "Generating self-signed certificate for: $SERVER_IP"

openssl req -x509 -nodes -days 3650 \
  -newkey rsa:2048 \
  -keyout "$SSL_DIR/self-signed.key" \
  -out    "$SSL_DIR/self-signed.crt" \
  -subj   "/C=RW/ST=Kigali/L=Kigali/O=CommodityPlatform/CN=$SERVER_IP" \
  -addext "subjectAltName=IP:$SERVER_IP,IP:127.0.0.1"

chmod 600 "$SSL_DIR/self-signed.key"
chmod 644 "$SSL_DIR/self-signed.crt"

echo ""
echo "✅ Certificate generated:"
echo "   $SSL_DIR/self-signed.crt"
echo "   $SSL_DIR/self-signed.key"
echo ""
echo "Valid for 10 years. To inspect:"
echo "   openssl x509 -in $SSL_DIR/self-signed.crt -text -noout"
