import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GLib, Pango
from pathlib import Path

import bootman.bootman_actions as actions

class BootmanWindow(Adw.ApplicationWindow):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.connect("close-request", lambda _: exit(0))
        self.set_default_size(400, 600)

        self.toast_overlay = Adw.ToastOverlay()
        self.toolbar_view = Adw.ToolbarView()
        self.install_bottom_sheet = Adw.BottomSheet()
        self.install_bottom_sheet.set_modal(True)

        # Header setup
        self.header = Adw.HeaderBar()
        self.header.set_title_widget(Adw.WindowTitle(title="Boot Manager"))
        add_button = Gtk.Button()
        add_button.set_icon_name("list-add-symbolic")
        add_button.connect("clicked", self.show_new_install_dialog)
        self.header.pack_end(add_button)

        # Content setup
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

        # Navigation and layout setup
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

        # Delayed check for mount and partitions
        GLib.timeout_add(100, self.delayed_check_mount_and_partitions)

    def show_toast(self, message, duration=3):
        """Display a toast message."""
        toast = Adw.Toast(title=message)
        self.toast_overlay.add_toast(toast)
        print(message)
        def dismiss_toast():
            toast.dismiss()
            return False
        GLib.timeout_add_seconds(duration, dismiss_toast)

    def delayed_check_mount_and_partitions(self):
        """Delayed initial check of mount and partitions."""
        self.check_mount_and_partitions()
        return False

    def check_mount_and_partitions(self):
        """Check if the partition is mounted and process partitions."""
        if not actions.is_mounted("/furios_persist"):
            self.show_password_dialog(False)
        else:
            self.show_password_dialog(True)
        return False

    def show_password_dialog(self, only_write):
        """
        Show password dialog for mounting or writing partitions.

        Args:
            only_write (bool): If True, only write partitions. If False, mount first.
        """
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
        """
        Handle password dialog response.

        Args:
            dialog: The dialog widget
            response: User's response
            password_entry: Password entry widget
            only_write: Whether to only write partitions
        """
        if response == "ok":
            password = password_entry.get_text()
            if only_write:
                self.process_partitions(password)
            else:
                success, message = actions.mount_partition(password)
                self.show_toast(message)
                if success:
                    self.process_partitions(password)
        else:
            exit(0)
        dialog.destroy()

    def process_partitions(self, password=None):
        """
        Process and display partitions.

        Args:
            password (str, optional): Sudo password
        """
        partitions_file = Path("/furios_persist/bootman/partitions")

        if not partitions_file.exists():
            try:
                partitions = actions.list_partitions()

                if password:
                    success, message = actions.write_partitions_file(partitions, password)
                    if not success:
                        self.show_toast(message)
                        return

                # Delay displaying partitions to ensure file is written
                GLib.timeout_add(100, lambda: self.display_partitions(partitions_file, password))
            except Exception as e:
                self.show_toast(f"Error processing partitions: {str(e)}")
        else:
            self.display_partitions(partitions_file, password)

    def display_partitions(self, partitions_file, password=None):
        """
        Display partitions in the UI list.

        Args:
            partitions_file (Path): Path to the partitions file
            password (str, optional): Sudo password for getting partition sizes
        """

        # Clear existing list
        while True:
            row = self.partition_list.get_first_child()
            if row is None:
                break
            self.partition_list.remove(row)

        try:
            partitions = actions.read_partitions_file(partitions_file)

            for partition, name in partitions:
                row = Adw.ActionRow(title=name)

                if password:
                    size = actions.get_partition_size(partition, password)
                    if size != "Unknown":
                        row.set_subtitle(f"Size: {size}")

                # Main rootfs should not be removed
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

    def show_new_install_dialog(self, button):
        """Show dialog for creating a new partition install."""
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        content.set_margin_top(48)
        content.set_margin_bottom(24)
        content.set_margin_start(24)
        content.set_margin_end(24)

        name_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        name_label = Gtk.Label(label="Install Name")
        name_label.set_width_chars(15)
        name_entry = Gtk.Entry()
        name_entry.set_hexpand(True)
        name_box.append(name_label)
        name_box.append(name_entry)
        content.append(name_box)

        size_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        size_label = Gtk.Label(label="Install Size (GB)")
        size_label.set_width_chars(15)
        size_entry = Gtk.Entry()
        size_entry.set_input_purpose(Gtk.InputPurpose.DIGITS)
        size_entry.set_hexpand(True)
        size_entry.connect("insert-text", self.on_size_insert)
        size_box.append(size_label)
        size_box.append(size_entry)
        content.append(size_box)

        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        button_box.set_homogeneous(True)
        button_box.set_margin_top(12)

        cancel_button = Gtk.Button(label="Cancel")
        cancel_button.set_hexpand(True)
        cancel_button.set_halign(Gtk.Align.FILL)
        cancel_button.connect("clicked", lambda _: self.install_bottom_sheet.set_open(False))
        button_box.append(cancel_button)

        apply_button = Gtk.Button(label="Apply")
        apply_button.set_hexpand(True)
        apply_button.set_halign(Gtk.Align.FILL)
        apply_button.add_css_class("suggested-action")
        apply_button.connect("clicked", lambda _: self.on_new_install_apply(name_entry.get_text(), size_entry.get_text()))
        button_box.append(apply_button)

        content.append(button_box)
        self.install_bottom_sheet.set_sheet(content)
        self.install_bottom_sheet.set_open(True)

    def on_size_insert(self, entry, text, length, position):
        """
        Validate size entry to only accept digits.

        Args:
            entry: The entry widget
            text: Text being inserted
            length: Length of text being inserted
            position: Position of insertion

        Returns:
            bool: Whether to allow the insertion
        """
        if not text.isdigit():
            entry.stop_emission_by_name("insert-text")
            return True
        return False

    def on_new_install_apply(self, name, size):
        """
        Handle new install application.

        Args:
            name (str): Name of the new installation
            size (str): Size of the new installation
        """
        if not name or not size:
            self.show_toast("Name and size are required")
            return
        try:
            size_num = int(size)
            if size_num <= 0:
                self.show_toast("Size must be greater than 0")
                return
            self.install_bottom_sheet.set_open(False)
            self.show_password_dialog_for_commands(name, size)
        except ValueError:
            self.show_toast("Invalid size value")

    def show_password_dialog_for_commands(self, name, size):
        """
        Show password dialog for creating new partition commands.

        Args:
            name (str): Name of the new installation
            size (str): Size of the new installation
        """
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

        dialog.connect("response", self.on_command_password_response, password_entry, name, size)
        dialog.present()

    def on_command_password_response(self, dialog, response, password_entry, name, size):
        """
        Handle password dialog response for commands.

        Args:
            dialog: The dialog widget
            response: User's response
            password_entry: Password entry widget
            name: Name of the new installation
            size: Size of the new installation
        """
        if response == "ok":
            password = password_entry.get_text()
            success, message = actions.create_install_commands(password, name, size)
            self.show_toast(message)
        dialog.destroy()

    def show_delete_dialog(self, partition_name):
        """
        Show confirmation dialog for deleting a partition.

        Args:
            partition_name (str): Name of the partition to delete
        """
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
        """
        Handle partition deletion response.

        Args:
            dialog: The dialog widget
            response: User's response
            partition_name: Name of the partition to delete
        """
        if response == "delete":
            self.show_password_dialog_for_delete(partition_name)
        dialog.close()

    def show_password_dialog_for_delete(self, partition_name):
        """
        Show password dialog for deletion commands.

        Args:
            partition_name (str): Name of the partition to delete
        """
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

        dialog.connect("response", self.on_delete_password_response, password_entry, partition_name)
        dialog.present()

    def on_delete_password_response(self, dialog, response, password_entry, partition_name):
        """
        Handle password dialog response for deletion.

        Args:
            dialog: The dialog widget
            response: User's response
            password_entry: Password entry widget
            partition_name: Name of the partition to delete
        """
        if response == "ok":
            password = password_entry.get_text()
            success, message = actions.delete_install_commands(password, partition_name)
            self.show_toast(message)
            if success:
                self.process_partitions(password)
        dialog.destroy()
