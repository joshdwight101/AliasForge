# Alias Forge

<img src="./io.github.aliasforge.Manager.svg" alt="Alias Forge icon" width="96">

A GTK desktop editor for the Bash aliases and functions in `~/.bash_aliases`. Edit individual commands, check Bash syntax, and keep backups you can restore from the app.

**Version 1.0.1 · Joshua Dwight**

## Install on Ubuntu

Run the installer from the directory containing this README.

```bash
bash install.sh
```

The installer uses `sudo` to install Python 3, GTK 4, libadwaita, and GtkSourceView dependencies. It installs Alias Forge and its launcher for your user account. Open **Alias Forge** from Ubuntu’s application menu. Run the app as your regular user so it edits that account’s Bash configuration.

## Add your first alias

1. Click **+ Alias** and enter a name such as `ll`.
2. Enter the command `ls -alF` and click **Add Command** to stage it.
3. Click **Validate** to check Bash syntax, then **Apply Changes** to save.
4. Open a new Bash terminal or run the following command in an existing terminal.

   ```bash
   source ~/.bash_aliases
   ```

Use **+ Function** for a reusable Bash function. Enter its name and body and Alias Forge adds the declaration and braces. Use the **Commands** list to find or edit an existing managed command. **Raw file** opens the entire aliases file, including commands written outside Alias Forge. Keep the managed block markers intact to retain those commands in the list.

## Back up and restore

- **File → Backup…** copies the saved aliases file. Keep the suggested timestamped filename and folder, or choose your own. The default folder is `~/.local/share/alias-forge/backups`.
- **File → Restore Backup…** validates the selected file before asking you to confirm. Choose **All files** if the backup has a custom name. Restoring saves a safety copy of the current aliases file when one exists, replaces it, and discards edits staged in the editor.
- **File → Refresh from Disk** reloads the aliases file. If Alias Forge warns that the file changed externally, copy any draft edits you want to keep before refreshing.

**Apply Changes** creates a safety backup before replacing an existing aliases file and adds a loader to `~/.bashrc` when needed. Bash syntax validation catches syntax errors. Loading an aliases file can execute top-level commands, so review files from other sources before applying or sourcing them.

## Launchers and help

**File → Install in Application Menu** creates or refreshes the Ubuntu application menu entry. **File → Install Desktop Shortcut** creates or replaces the desktop launcher.

Open **Help → User Guide** for a full walkthrough or **Help → About** for version information. [User guide](./USER-GUIDE.txt) · [Changelog](./changelog.md)
