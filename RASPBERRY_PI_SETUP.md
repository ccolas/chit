# Raspberry Pi Setup for Chit

Guide to setting up Chit on a Raspberry Pi 3 Model B (also works for Pi 4).

---

## Hardware Requirements

- Raspberry Pi 3B/3B+/4
- MicroSD card (16GB minimum, 32GB recommended)
- USB microphone
- 58mm USB thermal printer (e.g., Excelvan ZJ-589)

---

## 1. Flash Raspberry Pi OS

1. Download [Raspberry Pi Imager](https://www.raspberrypi.com/software/) for your computer
2. Insert MicroSD card
3. Open Raspberry Pi Imager:
   - **Choose Device**: Raspberry Pi 3 (or your model)
   - **Choose OS**: Raspberry Pi OS (64-bit) — use 32-bit if 64-bit unavailable
   - **Choose Storage**: Select your SD card
4. Click **Next**, then **Edit Settings**:
   - Set hostname (e.g., `chit`)
   - Set username and password
   - Configure WiFi (SSID and password)
   - Enable SSH (Services tab) with password authentication
5. Write the image

---

## 2. Network Connection

### Option A: Ethernet (Recommended)
Plug an Ethernet cable from the Pi to your router. This avoids WiFi isolation issues.

### Option B: WiFi with Tailscale
Many routers have AP isolation enabled, preventing WiFi devices from communicating. Tailscale bypasses this.

**On the Pi** (connect keyboard/monitor first):
```bash
sudo apt update && sudo apt install -y tailscale
sudo tailscale up
```

Open the URL it provides and sign in.

**On your computer:**
Install Tailscale from https://tailscale.com/download and sign in with the same account.

Get the Pi's Tailscale IP:
```bash
tailscale ip
```

SSH using the `100.x.x.x` IP.

### Troubleshooting WiFi Issues

**Pi 3 only supports 2.4GHz** — if your computer is on 5GHz, devices may not see each other. Split your router's bands and connect both to 2.4GHz.

**Check for AP isolation** in your router settings:
- Look for "AP Isolation", "Client Isolation", or "Guest Mode"
- Disable if found

---

## 3. SSH Connection

```bash
ssh username@chit.local
# or with Tailscale:
ssh username@100.x.x.x
```

### If SSH key auth fails

Enable password authentication on the Pi:
```bash
sudo nano /etc/ssh/sshd_config
```

Ensure this line exists (uncommented):
```
PasswordAuthentication yes
```

Also check for override files:
```bash
cat /etc/ssh/sshd_config.d/*
```

Change any `PasswordAuthentication no` to `yes`.

Then:
```bash
sudo systemctl restart ssh
passwd  # set a password if you haven't
```

---

## 4. Install Dependencies

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3-pip python3-venv libportaudio2 portaudio19-dev \
    libusb-1.0-0-dev libudev-dev git
```

Fix locale warnings (optional):
```bash
sudo apt install -y locales-all
sudo touch /var/lib/cloud/instance/locale-check.skip
```

---

## 5. USB Printer Permissions

```bash
sudo tee /etc/udev/rules.d/99-escpos.rules << 'EOF'
SUBSYSTEM=="usb", ATTR{idVendor}=="0416", ATTR{idProduct}=="5011", MODE="0666", GROUP="plugdev"
EOF

sudo udevadm control --reload-rules
sudo udevadm trigger
sudo usermod -a -G plugdev $USER
```

Log out and back in for group changes to take effect.

---

## 6. Install Chit

```bash
git clone <your-repo-url> ~/chit
cd ~/chit

python3 -m venv venv
source venv/bin/activate

pip install -r requirements.txt
pip install RPi.GPIO
```

---

## 7. Configure API Key

```bash
# Option A: Create a file
echo "your-openrouter-key" > ~/chit/.api_openrouter

# Option B: Environment variable
echo 'export OPENROUTER_API_KEY="your-key"' >> ~/.bashrc
source ~/.bashrc
```

---

## 8. Run Chit

```bash
cd ~/chit
source venv/bin/activate

# Raspberry Pi mode with GPIO buttons
python main.py --backend raspberry

# Hands-free mode (wake word: "Hey Jarvis")
python main.py --backend raspberry --hands-free

# Text mode (type instead of speak)
python main.py --backend raspberry --text

# Smaller Whisper model for better performance
python main.py --backend raspberry --whisper-model base
```

---

## 9. Run on Boot (Optional)

```bash
sudo tee /etc/systemd/system/chit.service << 'EOF'
[Unit]
Description=Chit Receipt Printer
After=network.target

[Service]
User=cedric
WorkingDirectory=/home/cedric/chit
Environment="OPENROUTER_API_KEY=your-key"
ExecStart=/home/cedric/chit/venv/bin/python main.py --backend raspberry --hands-free
Restart=always

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl enable chit
sudo systemctl start chit
```

---

## Performance Tips

- Use `--whisper-model base` for faster transcription on Pi 3
- Consider `--whisper openai` to offload transcription to the cloud
- Pi 4 with 4GB+ RAM handles local Whisper better than Pi 3