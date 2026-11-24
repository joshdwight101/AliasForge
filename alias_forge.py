#!/usr/bin/env python3
"""Alias Forge: a GTK4/libadwaita manager for ~/.bash_aliases."""
import os
import re
import sys
import stat
import shutil
import tempfile
import hashlib
import subprocess
from datetime import datetime
from pathlib import Path

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
gi.require_version('GtkSource', '5')
from gi.repository import Gtk, Adw, Gio, GLib, Gdk, GtkSource

HOME = Path.home()
ALIAS_FILE = HOME / '.bash_aliases'
BASHRC = HOME / '.bashrc'
BACKUPS = HOME / '.local' / 'share' / 'alias-forge' / 'backups'
NAME_RE = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')
BLOCK_RE = re.compile(r'(?ms)^# >>> Alias Forge: (function|alias) ([A-Za-z_][A-Za-z0-9_]*) >>>\n(.*?)^# <<< Alias Forge: \1 \2 <<<\n?')
CSS = b'''
.hero { padding: 15px 20px; }
.muted { opacity: 0.70; }
.title-big { font-size: 22px; font-weight: 700; }
.list-panel { background: alpha(@card_bg_color, 0.5); }
.code-frame { border: 1px solid alpha(@borders, 0.6); border-radius: 10px; }
.status-success { color: #2eae71; }
.status-error { color: #e05252; }
'''


def checksum(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def build_block(kind, name, body):
    if kind == 'function':
        content = f'{name}() {{\n{body.rstrip()}\n}}\n'
    else:
        content = f"alias {name}={shell_quote(body.strip())}\n"
    return f'# >>> Alias Forge: {kind} {name} >>>\n{content}# <<< Alias Forge: {kind} {name} <<<\n'


def shell_quote(value):
    return "'" + value.replace("'", "'\\''") + "'"


def parse_blocks(content):
    found = []
    for m in BLOCK_RE.finditer(content):
        kind, name, source = m.group(1), m.group(2), m.group(3)
        if kind == 'function':
            x = re.match(r'^\s*' + re.escape(name) + r'\s*\(\)\s*\{\n(.*)\n\}\n?$', source, re.S)
            if not x:
                continue
            body = x.group(1)
        else:
            x = re.match(r'^alias\s+' + re.escape(name) + r'=(.*)\n?$', source)
            if not x:
                continue
            value = x.group(1).strip()
            # Only decode values using our own single-quote serialization.
            if not (value.startswith("'") and value.endswith("'")):
                continue
            body = value[1:-1].replace("'\\''", "'")
        found.append({'kind': kind, 'name': name, 'body': body, 'start': m.start(), 'end': m.end()})
    return found


def bash_validate(text):
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', prefix='alias-forge-check-', suffix='.sh', delete=False) as tmp:
        tmp.write(text)
        path = tmp.name
    try:
        p = subprocess.run(['/bin/bash', '-n', path], capture_output=True, text=True, timeout=8)
        return p.returncode == 0, (p.stderr.strip() or 'Bash syntax check passed.')
    finally:
        os.unlink(path)


def atomic_write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f'.{path.name}.', dir=str(path.parent))
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        if path.exists():
            os.chmod(name, stat.S_IMODE(path.stat().st_mode))
        else:
            os.chmod(name, 0o600)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def suggested_backup_name():
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    return f'bash_aliases-{stamp}.bak'


def backup_file(dest=None):
    if not ALIAS_FILE.exists():
        return None
    if dest is None:
        BACKUPS.mkdir(parents=True, exist_ok=True)
        dest = BACKUPS / suggested_backup_name()
    with ALIAS_FILE.open('rb') as source:
        with tempfile.NamedTemporaryFile(dir=dest.parent, prefix='.bash_aliases-', delete=False) as backup:
            temporary = Path(backup.name)
            try:
                shutil.copyfileobj(source, backup)
                backup.close()
                temporary.replace(dest)
            finally:
                temporary.unlink(missing_ok=True)
    return dest


VERSION = '1.0.1'
AUTHOR = 'Joshua Dwight'


class AliasForge(Adw.Application):
    def __init__(self):
        super().__init__(application_id='io.github.aliasforge.Manager')
        self.connect('activate', self.activate)
        self.text = ''
        self.disk_hash = ''
        self.items = []
        self.selected = None
        self.loading = False
        self.dirty = False
        self.raw_mode = False
        self.backup_chooser = None
        self.restore_chooser = None

    def activate(self, *_):
        if self.get_active_window():
            self.get_active_window().present()
            return
        self.win = Adw.ApplicationWindow(application=self, title='Alias Forge', default_width=1120, default_height=740)
        self.win.set_icon_name(self.get_application_id())
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.win.set_content(root)
        header = Adw.HeaderBar()
        root.append(header)
        branding = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        logo = Gtk.Image.new_from_icon_name(self.get_application_id())
        logo.set_pixel_size(26)
        branding.append(logo)
        branding.append(Adw.WindowTitle(title='Alias Forge', subtitle=f'{AUTHOR} · v{VERSION}'))
        header.set_title_widget(branding)
        for label, fn, style in [('Backup', self.backup, ''), ('Validate', self.validate, ''), ('Apply Changes', self.save, 'suggested-action')]:
            button = Gtk.Button(label=label)
            if style: button.add_css_class(style)
            button.connect('clicked', fn)
            header.pack_end(button)
        restore = Gtk.Button(label='Restore…', tooltip_text='Restore a .bash_aliases backup')
        restore.connect('clicked', self.restore)
        header.pack_end(restore)
        menu = Gio.Menu()
        menu.append('Backup…', 'app.backup')
        menu.append('Restore Backup…', 'app.restore')
        menu.append('Open Backup Folder', 'app.openbackups')
        menu.append('Install Desktop Shortcut', 'app.install-shortcut')
        menu.append('Install in Application Menu', 'app.install-app-menu')
        menu.append('Copy Source Command', 'app.copy-source')
        menu.append('Refresh from Disk', 'app.refresh')
        for name, cb in [
            ('backup', self.backup), ('restore', self.restore), ('openbackups', self.open_backups),
            ('install-shortcut', self.install_shortcut), ('install-app-menu', self.install_app_menu), ('copy-source', self.copy_source), ('refresh', self.refresh),
        ]:
            a = Gio.SimpleAction.new(name, None)
            a.connect('activate', lambda _a, _p, method=cb: method())
            self.add_action(a)
        pop = Gtk.MenuButton(label='File', menu_model=menu)
        header.pack_start(pop)
        help_menu = Gio.Menu()
        help_menu.append('User Guide', 'app.user-guide')
        guide = Gio.SimpleAction.new('user-guide', None)
        guide.connect('activate', self.show_user_guide)
        self.add_action(guide)
        help_menu.append('About', 'app.about')
        about = Gio.SimpleAction.new('about', None)
        about.connect('activate', self.show_about)
        self.add_action(about)
        header.pack_start(Gtk.MenuButton(label='Help', menu_model=help_menu))
        banner = Adw.Banner(title='New terminals load your saved changes. Existing terminals: source ~/.bash_aliases')
        banner.set_revealed(True)
        root.append(banner)
        split = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL, wide_handle=True)
        split.set_position(340)
        root.append(split)
        split.set_vexpand(True)
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        left.set_size_request(295, -1)
        left.set_margin_start(14); left.set_margin_top(12); left.set_margin_bottom(12)
        left.set_margin_end(12)
        split.set_start_child(left)
        h = Gtk.Box(spacing=6)
        label = Gtk.Label(label='Commands', xalign=0)
        label.add_css_class('title-2')
        label.set_hexpand(True)
        h.append(label)
        add_fn = Gtk.Button(icon_name='list-add-symbolic', tooltip_text='New function')
        add_fn.connect('clicked', lambda *_: self.create('function'))
        h.append(add_fn)
        left.append(h)
        self.search = Gtk.SearchEntry(placeholder_text='Search functions and aliases')
        self.search.connect('search-changed', lambda *_: self.draw_items())
        left.append(self.search)
        self.scroll_list = Gtk.ScrolledWindow(vexpand=True)
        self.listbox = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self.listbox.add_css_class('boxed-list')
        self.listbox.connect('row-selected', self.on_select)
        self.scroll_list.set_child(self.listbox)
        left.append(self.scroll_list)
        left_actions = Gtk.Box(spacing=6)
        for txt, fn in [('+ Function', lambda *_: self.create('function')), ('+ Alias', lambda *_: self.create('alias')), ('Raw file', self.raw_file)]:
            b = Gtk.Button(label=txt)
            b.connect('clicked', fn)
            left_actions.append(b)
        left.append(left_actions)
        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        right.set_margin_start(18); right.set_margin_end(18)
        right.set_margin_top(16); right.set_margin_bottom(16)
        split.set_end_child(right)
        self.page_title = Gtk.Label(label='Select or create a command', xalign=0)
        self.page_title.add_css_class('title-1')
        right.append(self.page_title)
        sub = Gtk.Label(label='Function bodies are wrapped automatically with name() { … }', xalign=0)
        sub.add_css_class('muted')
        sub.set_wrap(True)
        right.append(sub)
        self.name_entry = Gtk.Entry(placeholder_text='Function or alias name')
        self.name_entry.connect('changed', self.on_editor_change)
        right.append(self.name_entry)
        self.kind_label = Gtk.Label(label='Bash function body', xalign=0)
        self.kind_label.add_css_class('heading')
        right.append(self.kind_label)
        source = GtkSource.Buffer()
        source.set_highlight_syntax(True)
        lm = GtkSource.LanguageManager.get_default()
        source.set_language(lm.get_language('sh'))
        source.connect('changed', self.on_editor_change)
        self.buffer = source
        self.editor = GtkSource.View.new_with_buffer(source)
        self.editor.set_monospace(True)
        self.editor.set_show_line_numbers(True)
        self.editor.set_tab_width(4)
        self.editor.set_auto_indent(True)
        self.editor.set_insert_spaces_instead_of_tabs(True)
        self.editor.set_wrap_mode(Gtk.WrapMode.NONE)
        sc = Gtk.ScrolledWindow(hexpand=True, vexpand=True)
        sc.set_min_content_height(290)
        sc.set_child(self.editor)
        sc.add_css_class('code-frame')
        right.append(sc)
        self.info = Gtk.Label(label='Changes are validated before being written to disk.', xalign=0, wrap=True)
        self.info.add_css_class('muted')
        right.append(self.info)
        row = Gtk.Box(spacing=8)
        self.update_button = Gtk.Button(label='Update Command')
        self.update_button.add_css_class('suggested-action')
        self.update_button.connect('clicked', self.update_item)
        row.append(self.update_button)
        delete = Gtk.Button(label='Delete Command')
        delete.add_css_class('destructive-action')
        delete.connect('clicked', self.delete_item)
        row.append(delete)
        new = Gtk.Button(label='New Function')
        new.connect('clicked', lambda *_: self.create('function'))
        row.append(new)
        right.append(row)
        self.status = Gtk.Label(label='', xalign=0)
        self.status.add_css_class('muted')
        root.append(self.status)
        self.status.set_margin_start(18)
        self.status.set_margin_bottom(8)
        css = Gtk.CssProvider()
        css.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.reload_file()
        self.win.present()

    def show_user_guide(self, *_):
        try:
            text = Path(__file__).with_name('USER-GUIDE.txt').read_text(encoding='utf-8')
        except OSError as error:
            self.dialog('Could not open the user guide', str(error))
            return
        window = Gtk.Window(
            title='Alias Forge User Guide', transient_for=self.win, modal=True,
            destroy_with_parent=True, default_width=720, default_height=600,
        )
        view = Gtk.TextView(
            editable=False, cursor_visible=False, wrap_mode=Gtk.WrapMode.WORD_CHAR,
            left_margin=24, right_margin=24, top_margin=20, bottom_margin=20,
            pixels_below_lines=4,
        )
        view.get_buffer().set_text(text)
        window.set_child(Gtk.ScrolledWindow(child=view))
        window.present()

    def show_about(self, *_):
        about = Adw.AboutWindow(
            transient_for=self.win, modal=True, application_name='Alias Forge',
            application_icon=self.get_application_id(), version=VERSION,
            developer_name=AUTHOR, developers=[AUTHOR], comments='Manage Bash aliases and functions.',
        )
        about.present()

    def notify(self, message, bad=False):
        self.status.set_text(message)
        self.status.remove_css_class('status-success')
        self.status.remove_css_class('status-error')
        self.status.add_css_class('status-error' if bad else 'status-success')

    def dialog(self, heading, body, yes=None, callback=None, destructive=False):
        d = Adw.MessageDialog.new(self.win, heading, body)
        d.add_response('cancel', 'Close' if yes is None else 'Cancel')
        if yes:
            d.add_response('ok', yes)
            d.set_response_appearance('ok', Adw.ResponseAppearance.DESTRUCTIVE if destructive else Adw.ResponseAppearance.SUGGESTED)
        d.set_default_response('cancel')
        d.set_close_response('cancel')
        if callback:
            d.connect('response', lambda _d, response: callback() if response == 'ok' else None)
        d.present()

    def ensure_bashrc(self):
        text = BASHRC.read_text(encoding='utf-8') if BASHRC.exists() else ''
        if re.search(r'(?m)^\s*(?:\.|source)\s+(?:["\']?\$HOME/|["\']?~/|["\']?\$\{HOME\}/)\.bash_aliases', text) or '.bash_aliases' in text:
            return
        snippet = '\n# Load personal Bash aliases and functions\nif [ -f "$HOME/.bash_aliases" ]; then\n    . "$HOME/.bash_aliases"\nfi\n'
        candidate = text.rstrip('\n') + '\n' + snippet
        ok, msg = bash_validate(candidate)
        if not ok:
            self.notify(f'.bashrc was not modified: {msg}', True)
            return
        if BASHRC.exists():
            BACKUPS.mkdir(parents=True, exist_ok=True)
            shutil.copy2(BASHRC, BACKUPS / f'bashrc-{datetime.now().strftime("%Y%m%d-%H%M%S-%f")}.bak')
        atomic_write(BASHRC, candidate)

    def reload_file(self):
        if not ALIAS_FILE.exists():
            self.text = '# Bash aliases and functions — managed with Alias Forge\n'
        else:
            self.text = ALIAS_FILE.read_text(encoding='utf-8')
        self.disk_hash = checksum(self.text) if ALIAS_FILE.exists() else None
        self.items = parse_blocks(self.text)
        self.selected = None
        self.dirty = False
        self.draw_items()
        self.create('function', empty=True)
        self.notify(f'{len(self.items)} managed commands loaded • {ALIAS_FILE}')

    def draw_items(self):
        self.loading = True
        while child := self.listbox.get_row_at_index(0):
            self.listbox.remove(child)
        needle = self.search.get_text().lower()
        for item in self.items:
            if needle not in item['name'].lower() and needle not in item['kind']:
                continue
            row = Gtk.ListBoxRow()
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
            box.set_margin_top(10); box.set_margin_bottom(10)
            box.set_margin_start(12); box.set_margin_end(12)
            name = Gtk.Label(label=item['name'], xalign=0)
            name.add_css_class('heading')
            kind = Gtk.Label(label='FUNCTION' if item['kind'] == 'function' else 'ALIAS', xalign=0)
            kind.add_css_class('caption')
            kind.add_css_class('muted')
            box.append(name); box.append(kind)
            row.set_child(box)
            row.item = item
            self.listbox.append(row)
        self.loading = False

    def on_select(self, _box, row):
        if self.loading or row is None:
            return
        if self.dirty and not self.raw_mode:
            self.notify('Unsaved editor changes were not applied. Use Update Command before switching.', True)
        item = row.item
        self.selected = item
        self.raw_mode = False
        self.populate(item['name'], item['body'], item['kind'])

    def populate(self, name, body, kind):
        self.loading = True
        self.name_entry.set_editable(True)
        self.name_entry.set_text(name)
        self.buffer.set_text(body)
        self.kind = kind
        self.kind_label.set_text('Function body (wrapper generated automatically)' if kind == 'function' else 'Alias command (enter command only)')
        self.page_title.set_text(('Edit ' if self.selected else 'New ') + kind.title())
        self.update_button.set_label('Update Command' if self.selected else 'Add Command')
        self.dirty = False
        self.loading = False

    def create(self, kind, empty=False):
        self.selected = None
        self.raw_mode = False
        self.listbox.unselect_all()
        self.populate('', '' if empty else '# Commands go here\n', kind)

    def raw_file(self, *_):
        self.selected = None
        self.raw_mode = True
        self.listbox.unselect_all()
        self.loading = True
        self.page_title.set_text('Advanced · Raw .bash_aliases')
        self.name_entry.set_text('Raw file mode')
        self.name_entry.set_editable(False)
        self.kind_label.set_text('Full Bash source · managed blocks are preserved unless you edit them')
        self.buffer.set_text(self.text)
        self.update_button.set_label('Update Raw File')
        self.loading = False
        self.dirty = False

    def editor_text(self):
        start, end = self.buffer.get_bounds()
        return self.buffer.get_text(start, end, True)

    def on_editor_change(self, *_):
        if not self.loading:
            self.dirty = True

    def update_item(self, *_):
        value = self.editor_text()
        if self.raw_mode:
            ok, msg = bash_validate(value)
            if not ok:
                self.dialog('Bash syntax error', msg)
                return
            self.text = value
            self.items = parse_blocks(self.text)
            self.draw_items()
            self.dirty = False
            self.notify('Raw file updated in memory. Click Apply Changes to save.')
            return
        name = self.name_entry.get_text().strip()
        if not NAME_RE.fullmatch(name):
            self.dialog('Invalid name', 'Use letters, digits and underscores, beginning with a letter or underscore.')
            return
        if not value.strip():
            self.dialog('Empty command', 'Enter the Bash function body or alias command.')
            return
        if any(i['name'] == name and i is not self.selected for i in self.items):
            self.dialog('Duplicate name', f'A managed command named {name} already exists.')
            return
        block = build_block(self.kind, name, value)
        if self.selected:
            start, end = self.selected['start'], self.selected['end']
            proposed = self.text[:start] + block + self.text[end:]
        else:
            proposed = self.text.rstrip('\n') + '\n\n' + block
        ok, msg = bash_validate(proposed)
        if not ok:
            self.dialog('Syntax validation failed', msg)
            return
        self.text = proposed
        self.items = parse_blocks(self.text)
        self.selected = None
        self.draw_items()
        self.dirty = False
        self.notify(f'{name} staged successfully. Click Apply Changes to write to disk.')

    def delete_item(self, *_):
        if self.raw_mode or self.selected is None:
            self.notify('Select a managed function or alias to delete.', True)
            return
        def do_delete():
            start, end = self.selected['start'], self.selected['end']
            self.text = self.text[:start] + self.text[end:]
            self.items = parse_blocks(self.text)
            self.selected = None
            self.draw_items()
            self.create('function', empty=True)
            self.notify('Command removed from draft. Click Apply Changes to save.')
        self.dialog('Delete command?', f"Remove {self.selected['name']} from the aliases file?", 'Delete', do_delete, True)

    def validate(self, *_):
        proposed = self.editor_text() if self.raw_mode else self.text
        if self.dirty and not self.raw_mode:
            self.notify('Editor has unapplied changes: click Update Command first.', True)
            return
        ok, msg = bash_validate(proposed)
        self.dialog('Validation passed' if ok else 'Validation failed', msg)
        self.notify(msg, not ok)

    def save(self, *_):
        if self.dirty:
            self.notify('Click Update Command before applying unsaved editor changes.', True)
            return
        ok, msg = bash_validate(self.text)
        if not ok:
            self.dialog('Cannot save invalid Bash', msg)
            return
        current = ALIAS_FILE.read_text(encoding='utf-8') if ALIAS_FILE.exists() else None
        if (checksum(current) if current is not None else None) != self.disk_hash:
            self.dialog('File changed outside Alias Forge', 'Your .bash_aliases changed on disk. Copy your edits before choosing Refresh from Disk; no file was overwritten.')
            self.notify('External change detected: save blocked.', True)
            return
        def do_save():
            try:
                saved = backup_file()
                atomic_write(ALIAS_FILE, self.text)
                self.disk_hash = checksum(self.text)
                self.ensure_bashrc()
                # This checks syntax and that Bash can import functions without executing them.
                result = subprocess.run(['/bin/bash', '--noprofile', '--norc', '-c', 'source "$1"', 'bash', str(ALIAS_FILE)], capture_output=True, text=True, timeout=10)
                if result.returncode != 0:
                    self.notify(f'Saved, but fresh-shell load reported: {result.stderr.strip()}', True)
                else:
                    self.notify('Applied successfully. New terminals load changes. Existing terminals: source ~/.bash_aliases')
                self.items = parse_blocks(self.text)
                self.draw_items()
            except Exception as exc:
                self.dialog('Save error', str(exc))
                self.notify('Unable to apply changes.', True)
        self.dialog('Apply aliases file?', 'Validate, create a timestamped safety backup, atomically save ~/.bash_aliases, and ensure ~/.bashrc imports it. Note: importing a Bash file can run top-level commands.', 'Apply', do_save)

    def backup(self, *_):
        if not ALIAS_FILE.exists():
            self.dialog('No aliases file to back up', 'Click Apply Changes to create ~/.bash_aliases first.')
            return
        try:
            BACKUPS.mkdir(parents=True, exist_ok=True)
            chooser = Gtk.FileChooserNative.new(
                'Save aliases backup', self.win, Gtk.FileChooserAction.SAVE, 'Save', 'Cancel',
            )
            chooser.set_modal(True)
            chooser.set_current_folder(Gio.File.new_for_path(str(BACKUPS)))
            chooser.set_current_name(suggested_backup_name())
            chooser.connect('response', self.backup_chosen)
            self.backup_chooser = chooser
            chooser.show()
        except (OSError, GLib.Error) as exc:
            self.dialog('Backup failed', str(exc))

    def backup_chosen(self, chooser, response):
        try:
            selected = chooser.get_file() if response == Gtk.ResponseType.ACCEPT else None
        finally:
            chooser.destroy()
            self.backup_chooser = None
        if selected is None:
            return
        try:
            local_path = selected.get_path()
            if local_path is None:
                self.dialog('Backup failed', 'Choose a folder on this computer.')
                return
            destination = Path(local_path)
            if destination.resolve() == ALIAS_FILE.resolve():
                self.dialog('Backup failed', 'Choose a different filename or folder for the backup.')
                return
            path = backup_file(destination)
            if path:
                self.notify(f'Backup created: {path.name}')
                self.dialog('Backup created', f'Saved a copy of ~/.bash_aliases to\n{path}')
            else:
                self.dialog('No aliases file to back up', 'Click Apply Changes to create ~/.bash_aliases first.')
        except Exception as exc:
            self.dialog('Backup failed', str(exc))

    def restore(self, *_):
        chooser = Gtk.FileChooserNative.new(
            'Select a .bash_aliases backup', self.win, Gtk.FileChooserAction.OPEN,
            'Review Backup', 'Cancel',
        )
        chooser.set_modal(True)
        aliases = Gtk.FileFilter(name='Alias Forge backups')
        aliases.add_pattern('bash_aliases-*.bak')
        chooser.add_filter(aliases)
        all_files = Gtk.FileFilter(name='All files')
        all_files.add_pattern('*')
        chooser.add_filter(all_files)
        chooser.set_filter(aliases)
        folder = BACKUPS if BACKUPS.is_dir() else HOME
        chooser.set_current_folder(Gio.File.new_for_path(str(folder)))
        chooser.connect('response', self.restore_chosen)
        self.restore_chooser = chooser
        chooser.show()

    def restore_chosen(self, chooser, response):
        try:
            selected = chooser.get_file() if response == Gtk.ResponseType.ACCEPT else None
        finally:
            chooser.destroy()
            self.restore_chooser = None
        if selected is None:
            return
        try:
            local_path = selected.get_path()
            if local_path is None:
                self.dialog('Could not read backup', 'Select a backup stored on this computer.')
                return
            path = Path(local_path)
            if path.match('bashrc-*.bak'):
                self.dialog('Invalid backup', 'Select a .bash_aliases backup. This file is a .bashrc backup.')
                return
            candidate = path.read_text(encoding='utf-8')
            if '\0' in candidate:
                self.dialog('Invalid backup', 'This file contains null bytes.')
                return
            ok, msg = bash_validate(candidate)
            if not ok:
                self.dialog('Invalid backup', msg)
                return
            def do_restore():
                try:
                    saved = backup_file()
                    atomic_write(ALIAS_FILE, candidate)
                    self.reload_file()
                    message = f'Restored backup from {path.name}'
                    if saved:
                        message += f' • Previous file saved as {saved.name}'
                    self.notify(message)
                except Exception as exc:
                    self.dialog('Restore failed', str(exc))
            self.dialog(
                'Restore backup?',
                f'Use {path.name} as ~/.bash_aliases? The current file, if present, is backed up first. '
                'Unsaved changes in the editor will be discarded.',
                'Restore', do_restore, True,
            )
        except Exception as exc:
            self.dialog('Could not read backup', str(exc))

    def open_backups(self, *_):
        BACKUPS.mkdir(parents=True, exist_ok=True)
        Gio.AppInfo.launch_default_for_uri(BACKUPS.as_uri(), None)

    def install_app_menu(self, *_):
        app_id = self.get_application_id()
        script = Path(__file__).resolve()
        icon_file = script.with_name(f'{app_id}.svg')
        folder = Path(GLib.get_user_data_dir()) / 'applications'
        target = folder / 'alias-forge.desktop'
        escaped_script = str(script).replace('%', '%%')
        for character in ('\\', '"', '`', '$'):
            escaped_script = escaped_script.replace(character, '\\' + character)

        entry = GLib.KeyFile()
        properties = {
            'Type': 'Application',
            'Name': self.win.get_title(),
            'Comment': 'Manage Bash aliases and functions',
            'Exec': f'/usr/bin/python3 "{escaped_script}"',
            'Icon': str(icon_file) if icon_file.is_file() else app_id,
            'StartupWMClass': app_id,
            'Categories': 'Development;',
        }
        for key, value in properties.items():
            entry.set_string('Desktop Entry', key, value)
        entry.set_boolean('Desktop Entry', 'Terminal', False)
        entry.set_boolean('Desktop Entry', 'StartupNotify', True)
        try:
            folder.mkdir(parents=True, exist_ok=True)
            data, _ = entry.to_data()
            Gio.File.new_for_path(str(target)).replace_contents(
                data.encode('utf-8'), None, False, Gio.FileCreateFlags.REPLACE_DESTINATION, None,
            )
        except (OSError, GLib.Error) as error:
            self.dialog('Could not install application launcher', str(error))
            return
        self.dialog('Application launcher installed', f'{self.win.get_title()} is registered in your application menu.')

    def install_shortcut(self, *_):
        desktop = GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_DESKTOP)
        folder = Path(desktop) if desktop and Path(desktop) != HOME else HOME / 'Desktop'
        target = folder / 'alias-forge.desktop'
        launcher = Path(GLib.get_user_data_dir()) / 'applications' / target.name

        try:
            entry = launcher.read_text(encoding='utf-8')
            atomic_write(target, entry)
            target.chmod(0o755)
        except OSError as exc:
            self.dialog('Could not install shortcut', str(exc))
            return
        try:
            Gio.File.new_for_path(str(target)).set_attribute_string(
                'metadata::trusted', 'true', Gio.FileQueryInfoFlags.NONE, None,
            )
        except GLib.Error:
            self.dialog('Shortcut installed', f'{target}\nIf prompted, right-click it and choose Allow Launching.')
        else:
            self.dialog('Shortcut installed', str(target))

    def copy_source(self, *_):
        self.win.get_clipboard().set('source ~/.bash_aliases')
        self.notify('Copied: source ~/.bash_aliases')

    def refresh(self, *_):
        self.dialog('Reload from disk?', 'Discard changes staged in Alias Forge and reload ~/.bash_aliases?', 'Reload', self.reload_file, True)


if __name__ == '__main__':
    if os.geteuid() == 0:
        print('Do not run Alias Forge with sudo: it edits the current user\'s Bash configuration.', file=sys.stderr)
        sys.exit(1)
    app = AliasForge()
    sys.exit(app.run(sys.argv))
