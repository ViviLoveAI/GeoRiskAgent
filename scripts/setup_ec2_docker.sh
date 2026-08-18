#!/usr/bin/env bash
set -euo pipefail

sudo apt update
sudo apt install -y git curl ca-certificates gnupg

curl -fsSL https://get.docker.com | sh

sudo usermod -aG docker ubuntu

echo "Docker installation complete."
echo "Log out and SSH back in so the ubuntu user can run docker without sudo."
