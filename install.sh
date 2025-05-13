#!/bin/bash

# Telegram Bot Installer for Ubuntu
# Installs Python, dependencies, sets up the bot environment, generates config.py, and initializes business connection
# Optionally configures a systemd service for auto-start

# Exit on any error
set -e

# Bot installation directory
INSTALL_DIR="/opt/telegram-bot"
MEDIA_DIR_DEFAULT="media_archive"
BOT_USER="botuser"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to print messages
print_msg() {
    echo -e "${2:-$GREEN}[*] $1${NC}"
}

print_error() {
    echo -e "${RED}[!] Error: $1${NC}" >&2
    exit 1
}

# Function to read input with default value
read_with_default() {
    local prompt="$1"
    local default="$2"
    local var_name="$3"
    echo -n "$prompt [$default]: "
    read input
    eval $var_name="${input:-$default}"
}

# Check if running as root or with sudo
if [ "$EUID" -ne 0 ]; then
    print_error "This script must be run as root (use sudo)"
fi

# Check Ubuntu version
if ! lsb_release -d | grep -qi "Ubuntu"; then
    print_error "This script is designed for Ubuntu"
fi

# Step 1: Install Python and pip
print_msg "Checking for Python3 and pip..."
if ! command -v python3 &>/dev/null; then
    print_msg "Installing Python3..." "$YELLOW"
    apt update
    apt install -y python3
fi

if ! command -v pip3 &>/dev/null; then
    print_msg "Installing pip3..." "$YELLOW"
    apt install -y python3-pip
fi

# Ensure Python version is 3.8 or higher
PYTHON_VERSION=$(python3 --version | cut -d' ' -f2)
PYTHON_MAJOR=$(echo "$PYTHON_VERSION" | cut -d'.' -f1)
PYTHON_MINOR=$(echo "$PYTHON_VERSION" | cut -d'.' -f2)
if [ "$PYTHON_MAJOR" -lt 3 ] || { [ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -lt 8 ]; }; then
    print_error "Python 3.8 or higher is required (found $PYTHON_VERSION)"
fi

# Step 2: Install Python dependencies
print_msg "Installing Python dependencies..."
pip3 install requests schedule

# Step 3: Create bot user (non-login, for running the bot)
if ! id "$BOT_USER" &>/dev/null; then
    print_msg "Creating bot user '$BOT_USER'..." "$YELLOW"
    useradd -r -s /bin/false "$BOT_USER"
fi

# Step 4: Collect configuration parameters
print_msg "Please provide configuration parameters for the bot:"
read -p "Enter Telegram Bot Token: " TOKEN
if [ -z "$TOKEN" ]; then
    print_error "Token is required"
fi

read_with_default "Enter Spam Threshold (max photos per minute)" "10" SPAM_THRESHOLD
read_with_default "Enter Spam Window (seconds)" "60" SPAM_WINDOW
read_with_default "Enter Spam Block Duration (seconds)" "3600" SPAM_BLOCK_DURATION
read_with_default "Enter Max File Size (MB)" "50" MAX_FILE_SIZE
read_with_default "Enter Cleanup Days (days to keep messages)" "5" CLEANUP_DAYS
read_with_default "Enter Media Directory (relative to $INSTALL_DIR)" "$MEDIA_DIR_DEFAULT" MEDIA_DIR

# Convert MAX_FILE_SIZE to bytes
MAX_FILE_SIZE_BYTES=$((MAX_FILE_SIZE * 1024 * 1024))

# Step 5: Create installation directory and copy files
print_msg "Setting up installation directory at $INSTALL_DIR..."
mkdir -p "$INSTALL_DIR" "$INSTALL_DIR/$MEDIA_DIR"

# Copy as.py and init_bot.py (assuming they are in the current directory)
if [ -f "as.py" ] && [ -f "init_bot.py" ]; then
    cp as.py init_bot.py "$INSTALL_DIR/"
else
    print_error "as.py and init_bot.py must be in the current directory"
fi

# Generate config.py
print_msg "Generating config.py..."
cat > "$INSTALL_DIR/config.py" << EOF
# Telegram bot configuration
TOKEN = '$TOKEN'
ADMIN_ID = 0  # Will be automatically filled by init_bot.py with the ID of the user setting up the business connection
ALLOWED_BUSINESS_ID = ''  # Will be automatically filled by init_bot.py after setting up business connection
SENDER_USERNAME = ''  # Will be automatically filled by init_bot.py with the bot's username (e.g., 'BotName')
BASE_URL = f'https://api.telegram.org/bot{TOKEN}'

# File and storage settings
MEDIA_DIR = '$MEDIA_DIR'  # Folder for media storage
MAX_FILE_SIZE = $MAX_FILE_SIZE_BYTES  # $MAX_FILE_SIZE MB in bytes
CLEANUP_DAYS = $CLEANUP_DAYS  # Cleanup period for old messages and media

# Spam protection settings
SPAM_THRESHOLD = $SPAM_THRESHOLD  # Max photos allowed in 1 minute
SPAM_WINDOW = $SPAM_WINDOW  # Time window for spam detection (seconds)
SPAM_BLOCK_DURATION = $SPAM_BLOCK_DURATION  # Block media for 1 hour (seconds)
EOF

# Set permissions
chown -R "$BOT_USER:$BOT_USER" "$INSTALL_DIR"
chmod -R 755 "$INSTALL_DIR"
chmod 644 "$INSTALL_DIR/as.py" "$INSTALL_DIR/config.py" "$INSTALL_DIR/init_bot.py"

# Step 6: Initialize database (will be created by bot if needed)
print_msg "Database will be initialized by the bot at first run ($INSTALL_DIR/messages.db)"

# Step 7: Run initialization bot to set up business connection
print_msg "Do you want to initialize the business connection now? (y/n)" "$YELLOW"
read -r INIT_BOT
if [ "$INIT_BOT" = "y" ] || [ "$INIT_BOT" = "Y" ]; then
    print_msg "Running init_bot.py to set up business connection..."
    cd "$INSTALL_DIR"
    python3 init_bot.py
    cd -
else
    print_msg "Skipping business connection initialization" "$YELLOW"
    print_msg "To initialize later, run: cd $INSTALL_DIR && python3 init_bot.py" "$YELLOW"
fi

# Step 8: Ask about systemd service
print_msg "Do you want to set up a systemd service for auto-start? (y/n)" "$YELLOW"
read -r SETUP_SERVICE
if [ "$SETUP_SERVICE" = "y" ] || [ "$SETUP_SERVICE" = "Y" ]; then
    print_msg "Setting up systemd service..."
    
    # Create systemd service file
    cat > /etc/systemd/system/telegram-bot.service << EOF
[Unit]
Description=Telegram Archive Bot
After=network.target

[Service]
User=$BOT_USER
WorkingDirectory=$INSTALL_DIR
ExecStart=/usr/bin/python3 $INSTALL_DIR/as.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

    # Reload systemd and enable service
    systemctl daemon-reload
    systemctl enable telegram-bot.service
    systemctl start telegram-bot.service
    
    print_msg "Systemd service 'telegram-bot' created and started"
else
    print_msg "Skipping systemd service setup" "$YELLOW"
fi

# Step 9: Print instructions
print_msg "Installation complete!" "$GREEN"
echo -e "${YELLOW}Next steps:${NC}"
if [ "$INIT_BOT" = "y" ] || [ "$INIT_BOT" = "Y" ]; then
    echo "1. Business connection ID, Admin ID, and Sender Username have been set in $INSTALL_DIR/config.py"
    echo "2. Verify settings in $INSTALL_DIR/config.py (e.g., TOKEN)"
else
    echo "1. Run the initialization bot to set up the business connection and configure IDs:"
    echo "   cd $INSTALL_DIR && python3 init_bot.py"
    echo "2. Verify settings in $INSTALL_DIR/config.py (e.g., TOKEN)"
fi
if [ "$SETUP_SERVICE" = "y" ] || [ "$SETUP_SERVICE" = "Y" ]; then
    echo "3. Bot is running as a service. Check status with: sudo systemctl status telegram-bot"
    echo "4. To stop/restart: sudo systemctl stop telegram-bot | sudo systemctl restart telegram-bot"
else
    echo "3. Run the bot manually: cd $INSTALL_DIR && python3 as.py"
fi
echo "5. Logs are printed to console or systemd journal (journalctl -u telegram-bot)"
echo "6. Media files are stored in $INSTALL_DIR/$MEDIA_DIR"
echo "7. Database is at $INSTALL_DIR/messages.db"
echo "8. Spam tracker is at $INSTALL_DIR/spam_tracker.json"