#!/bin/bash

# 1. Update dan install package sistem
sudo apt-get update
sudo apt-get install -y aria2 ffmpeg

# 2. Install library Python
pip install -r requirements.txt

# 3. Download dan setup cloudflared
wget -q https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64
chmod +x cloudflared-linux-amd64
sudo mv cloudflared-linux-amd64 /usr/local/bin/cloudflared

echo "Setup selesai!"
