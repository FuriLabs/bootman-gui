import gi
import subprocess
from pathlib import Path
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GLib, Pango

class BootmanWindow(Adw.ApplicationWindow):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.connect("close-request", lambda _: exit(0))
        self.set_default_size(400, 600)

        self.toast_overlay = Adw.ToastOverlay()
        self.toolbar_view = Adw.ToolbarView()
        self.install_bottom_sheet = Adw.BottomSheet()
        self.install_bottom_sheet.set_modal(True)

        self.header = Adw.HeaderBar()
        self.header.set_title_widget(Adw.WindowTitle(title="Boot Manager"))
        add_button = Gtk.Button()
        add_button.set_icon_name("list-add-symbolic")
        add_button.connect("clicked", self.show_new_install_dialog)
        self.header.pack_end(add_button)

        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        content_box.set_margin_top(12)
        content_box.set_margin_bottom(12)
        content_box.set_margin_start(12)
        content_box.set_margin_end(12)

        systems_label = Gtk.Label(label="Installed Systems")
        systems_label.set_halign(Gtk.Align.START)
        systems_label.set_margin_bottom(6)
        attr_list = Pango.AttrList()
        attr_list.insert(Pango.attr_weight_new(Pango.Weight.BOLD))
        systems_label.set_attributes(attr_list)
        content_box.append(systems_label)

        self.partition_list = Gtk.ListBox()
        self.partition_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self.partition_list.add_css_class("boxed-list")
        content_box.append(self.partition_list)

        self.main_page = Adw.NavigationPage(title="Main Page")
        self.main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.main_box.append(self.header)
        self.main_box.append(content_box)
        self.main_page.set_child(self.main_box)

        self.navigation_view = Adw.NavigationView()
        self.navigation_view.add(self.main_page)

        self.install_bottom_sheet.set_content(self.navigation_view)
        self.toolbar_view.set_content(self.install_bottom_sheet)
        self.toast_overlay.set_child(self.toolbar_view)
        self.set_content(self.toast_overlay)

        self.present()

        GLib.timeout_add(100, self.delayed_check_mount_and_partitions)

    def show_toast(self, message, duration=3):
        toast = Adw.Toast(title=message)
        self.toast_overlay.add_toast(toast)
        def dismiss_toast():
            toast.dismiss()
            return False
        GLib.timeout_add_seconds(duration, dismiss_toast)

    def get_partition_size(self, partition_name, password=None):
        try:
            cmd = f'echo {password} | sudo -S lvdisplay /dev/droidian/{partition_name}'
            result = subprocess.run(cmd, shell=True, text=True, capture_output=True)
            if result.returncode == 0:
                for line in result.stdout.splitlines():
                    if "LV Size" in line:
                        size = line.split()[2]
                        unit = line.split()[3]
                        return f"{size}{unit}"
            return "Unknown"
        except Exception:
            return "Unknown"

    def delayed_check_mount_and_partitions(self):
        self.check_mount_and_partitions()
        return False

    def check_mount_and_partitions(self):
        if not self.is_mounted("/furios_persist"):
            self.show_password_dialog(False)
        else:
            partitions_file = Path("/furios_persist/partitions")
            if not partitions_file.exists():
                self.show_password_dialog(True)
            else:
                self.show_password_dialog(True)
        return False

    def is_mounted(self, mount_point):
        try:
            with open('/proc/mounts', 'r') as f:
                return any(mount_point in line for line in f)
        except Exception:
            return False

    def show_password_dialog(self, only_write):
        dialog = Adw.MessageDialog(
            transient_for=self,
            modal=True,
            heading="Password Required",
            body="Please enter your password to continue"
        )

        password_entry = Gtk.PasswordEntry()
        password_entry.set_show_peek_icon(True)
        password_entry.set_margin_top(12)
        password_entry.set_margin_bottom(12)
        password_entry.set_margin_start(12)
        password_entry.set_margin_end(12)

        dialog.set_extra_child(password_entry)
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("ok", "OK")
        dialog.set_default_response("ok")
        dialog.set_close_response("cancel")

        dialog.connect("response", self.on_password_response, password_entry, only_write)
        dialog.present()

    def on_password_response(self, dialog, response, password_entry, only_write):
        if response == "ok":
            password = password_entry.get_text()
            if only_write:
                self.process_partitions(password)
            else:
                self.mount_partition(password)
        else:
            exit(0)
        dialog.destroy()

    def mount_partition(self, password):
        try:
            mkdir_cmd = f'echo {password} | sudo -S mkdir -p /furios_persist'
            result = subprocess.run(mkdir_cmd, shell=True, text=True, capture_output=True)
            if result.returncode != 0:
                self.show_toast(f"Failed to create mount point: {result.stderr}")
                return

            mount_cmd = f'echo {password} | sudo -S mount /dev/disk/by-partlabel/furios_persist /furios_persist'
            result = subprocess.run(mount_cmd, shell=True, text=True, capture_output=True)

            if result.returncode == 0:
                self.show_toast("Successfully mounted partition")
                self.process_partitions(password)
            else:
                self.show_toast(f"Failed to mount partition: {result.stderr}")
        except Exception as e:
            self.show_toast(f"Error mounting partition: {str(e)}")

    def show_new_install_dialog(self, button):
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        content.set_margin_top(48)
        content.set_margin_bottom(24)
        content.set_margin_start(24)
        content.set_margin_end(24)

        name_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        name_label = Gtk.Label(label="Install Name")
        name_entry = Gtk.Entry()
        name_entry.set_hexpand(True)
        name_box.append(name_label)
        name_box.append(name_entry)
        content.append(name_box)

        size_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        size_label = Gtk.Label(label="Install Size (GB)")
        size_entry = Gtk.Entry()
        size_entry.set_input_purpose(Gtk.InputPurpose.DIGITS)
        size_entry.set_hexpand(True)
        size_entry.connect("insert-text", self.on_size_insert)
        size_box.append(size_label)
        size_box.append(size_entry)
        content.append(size_box)

        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        button_box.set_margin_top(12)
        button_box.set_halign(Gtk.Align.END)

        cancel_button = Gtk.Button(label="Cancel")
        cancel_button.connect("clicked", lambda _: self.install_bottom_sheet.set_open(False))
        button_box.append(cancel_button)

        apply_button = Gtk.Button(label="Apply")
        apply_button.add_css_class("suggested-action")
        apply_button.connect("clicked", lambda _: self.on_new_install_apply(name_entry.get_text(), size_entry.get_text()))
        button_box.append(apply_button)

        content.append(button_box)
        self.install_bottom_sheet.set_sheet(content)
        self.install_bottom_sheet.set_open(True)

    def on_size_insert(self, entry, text, length, position):
        if not text.isdigit():
            entry.stop_emission_by_name("insert-text")
            return True
        return False

    def on_new_install_apply(self, name, size):
        print(f"New install requested - Name: {name}, Size: {size}GB")
        self.install_bottom_sheet.set_open(False)

    def show_delete_dialog(self, partition_name):
        dialog = Adw.MessageDialog(
            transient_for=self,
            heading="Confirm Deletion",
            body=f"Do you want to remove {partition_name}?",
            modal=True
        )

        dialog.add_response("cancel", "Cancel")
        dialog.add_response("delete", "Delete")
        dialog.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)

        dialog.connect("response", self.on_delete_response, partition_name)
        dialog.present()

    def on_delete_response(self, dialog, response, partition_name):
        if response == "delete":
            print(f"Delete requested for: {partition_name}")
        dialog.close()

    def process_partitions(self, password=None):
        partitions_file = Path("/furios_persist/partitions")

        if not partitions_file.exists():
            try:
                droidian_path = Path("/dev/droidian")
                if not droidian_path.exists():
                    self.show_toast("Error: /dev/droidian not found")
                    return

                partitions = [p.name for p in droidian_path.iterdir()
                              if p.name not in ['droidian-persistent', 'droidian-reserved']]

                content = ''
                for partition in partitions:
                    display_name = self.process_partition_name(partition)
                    size = self.get_partition_size(partition, password)
                    content += f"{partition}:{display_name}:{size}\\n"

                if password:
                    content = content.replace('\\n', '\n')
                    cmd = ['sudo', '-S', 'tee', '/furios_persist/partitions']
                    try:
                        process = subprocess.Popen(cmd, stdin=subprocess.PIPE, text=True)
                        process.communicate(input=content, timeout=2)
                        if process.returncode != 0:
                            raise Exception("Failed to write partitions file")
                    except subprocess.TimeoutExpired:
                        process.kill()
                        raise Exception("Timeout while writing partitions file")

                    subprocess.run(['sync'], check=True)

                GLib.timeout_add(100, lambda: self.display_partitions(partitions_file))
            except Exception as e:
                self.show_toast(f"Error processing partitions: {str(e)}")
        else:
            if password:
                droidian_path = Path("/dev/droidian")
                if droidian_path.exists():
                    partitions = [p.name for p in droidian_path.iterdir()
                                  if p.name not in ['droidian-persistent', 'droidian-reserved']]
                    content = ''
                    for partition in partitions:
                        display_name = self.process_partition_name(partition)
                        size = self.get_partition_size(partition, password)
                        content += f"{partition}:{display_name}:{size}\\n"

                    content = content.replace('\\n', '\n')
                    cmd = ['sudo', '-S', 'tee', '/furios_persist/partitions']
                    process = subprocess.Popen(cmd, stdin=subprocess.PIPE, text=True)
                    process.communicate(input=content, timeout=2)
                    subprocess.run(['sync'], check=True)
            self.display_partitions(partitions_file)

    def process_partition_name(self, partition_name):
        if partition_name == 'droidian-rootfs':
            return 'FuriOS rootfs'

        if partition_name.startswith('droidian-'):
            name = partition_name.replace('droidian-', '')
            words = name.split('-')
            return 'FuriOS ' + ' '.join(words)

        if partition_name.startswith('furios-'):
            name = partition_name.replace('furios-', '')
            words = name.split('-')
            return 'FuriOS ' + ' '.join(words)

        words = partition_name.split('-')
        return ' '.join(word.capitalize() for word in words)

    def display_partitions(self, partitions_file):
        while True:
            row = self.partition_list.get_first_child()
            if row is None:
                break
            self.partition_list.remove(row)

        try:
            with open(partitions_file, 'r') as f:
                content = f.read().strip()
                for line in content.split('\n'):
                    if ':' in line:
                        parts = line.strip().split(':')
                        if len(parts) >= 3:
                            partition, name, size = parts[:3]
                        else:
                            partition, name = parts[:2]
                            size = "Unknown"

                        row = Adw.ActionRow(title=name)
                        row.set_subtitle(f"Size: {size}")

                        if partition != 'droidian-rootfs':
                            delete_button = Gtk.Button()
                            delete_button.set_icon_name("user-trash-symbolic")
                            delete_button.add_css_class("destructive-action")
                            delete_button.set_valign(Gtk.Align.CENTER)
                            delete_button.set_margin_top(6)
                            delete_button.set_margin_bottom(6)
                            delete_button.set_margin_start(6)
                            delete_button.set_margin_end(6)
                            ctx = delete_button.get_style_context()
                            ctx.add_class("wide-button")
                            delete_button.set_size_request(42, 40)
                            delete_button.connect("clicked", lambda btn, p=partition: self.show_delete_dialog(p))
                            row.add_suffix(delete_button)

                        self.partition_list.append(row)
        except Exception as e:
            self.show_toast(f"Error reading partitions: {str(e)}")
