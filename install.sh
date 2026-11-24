#!/usr/bin/env bash
set -euo pipefail
sudo apt-get update
sudo apt-get install -y python3 python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 gir1.2-gtksource-5
install -d "$HOME/.local/share/alias-forge" "$HOME/.local/share/applications"
source_dir="$(dirname "$(realpath "$0")")"
install -m 755 "$source_dir/alias_forge.py" "$HOME/.local/share/alias-forge/alias_forge.py"
install -m 644 "$source_dir/USER-GUIDE.txt" "$source_dir/changelog.md" "$HOME/.local/share/alias-forge/"
install -Dm644 "$source_dir/io.github.aliasforge.Manager.svg" \
    "$HOME/.local/share/icons/hicolor/scalable/apps/io.github.aliasforge.Manager.svg"
if command -v gtk-update-icon-cache >/dev/null; then
    gtk-update-icon-cache -ft "$HOME/.local/share/icons/hicolor"
fi
cat > "$HOME/.local/share/applications/alias-forge.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Alias Forge
Comment=Manage Bash aliases and functions
Exec=/usr/bin/python3 $HOME/.local/share/alias-forge/alias_forge.py
Icon=io.github.aliasforge.Manager
StartupWMClass=io.github.aliasforge.Manager
Terminal=false
Categories=Development;Utility;
StartupNotify=true
EOF
chmod 644 "$HOME/.local/share/applications/alias-forge.desktop"
printf 'Alias Forge installed. Find it in your application menu or run:\npython3 ~/.local/share/alias-forge/alias_forge.py\n'
