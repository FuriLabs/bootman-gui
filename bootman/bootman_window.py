# SPDX-License-Identifier: GPL-2.0
# Copyright (C) 2025 Bardia Moshiri <bardia@furilabs.com>

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GLib, Pango, Gio
from pathlib import Path
import urllib.request
import threading
import os

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

        # Installed Systems section
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

        # Add spacing between sections
        separator = Gtk.Box()
        separator.set_margin_top(12)
        separator.set_margin_bottom(12)
        content_box.append(separator)

        # Queued Partitions section
        queued_label = Gtk.Label(label="Queued Partition")
        queued_label.set_halign(Gtk.Align.START)
        queued_label.set_margin_bottom(6)
        attr_list = Pango.AttrList()
        attr_list.insert(Pango.attr_weight_new(Pango.Weight.BOLD))
        queued_label.set_attributes(attr_list)
        content_box.append(queued_label)

        self.queued_list = Gtk.ListBox()
        self.queued_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self.queued_list.add_css_class("boxed-list")
        content_box.append(self.queued_list)

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
        try:
            if not actions.is_mounted("/furios_persist"):
                success, message = actions.mount_partition()
                if success:
                    self.process_partitions()
                else:
                    self.show_toast("Failed to mount partition")
            else:
                self.process_partitions()
        except Exception as e:
            self.show_error_dialog(str(e))
        return False

    def process_partitions(self):
        """Process and display partitions."""
        partitions_file = Path("/furios_persist/bootman/partitions")

        if not partitions_file.exists():
            try:
                partitions = actions.list_partitions()
                success, message = actions.write_partitions_file(partitions)
                if not success:
                    self.show_toast(message)
                    return

                # Delay displaying partitions to ensure file is written
                GLib.timeout_add(100, lambda: self.display_partitions(partitions_file))
            except Exception as e:
                self.show_toast(f"Error processing partitions: {str(e)}")
        else:
            self.display_partitions(partitions_file)

        # Always display queued partitions
        self.display_queued_partition()

    def display_queued_partition(self):
        """Display any queued partition in the queued list."""
        # Clear existing list
        while True:
            row = self.queued_list.get_first_child()
            if row is None:
                break
            self.queued_list.remove(row)

        # Check for queued partition
        queued = actions.get_queued_partition()
        if queued:
            partition_name, display_name = queued
            row = Adw.ActionRow(title=display_name)
            row.set_subtitle("Queued for installation")

            status_icon = Gtk.Image()
            status_icon.set_from_icon_name("alarm-symbolic")
            status_icon.set_margin_start(6)
            status_icon.set_margin_end(6)
            row.add_suffix(status_icon)

            self.queued_list.append(row)

    def display_partitions(self, partitions_file):
        """
        Display partitions in the UI list.

        Args:
            partitions_file (Path): Path to the partitions file
        """
        # Clear existing list
        while True:
            row = self.partition_list.get_first_child()
            if row is None:
                break
            self.partition_list.remove(row)

        try:
            partitions = actions.read_partitions_file(partitions_file)

            for partition_name, display_name in partitions:
                row = Adw.ActionRow(title=display_name)

                size = actions.get_partition_size(partition_name)
                if size != "Unknown":
                    row.set_subtitle(f"Size: {size}")

                can_remove = (partition_name != 'droidian-rootfs' and
                              not actions.is_partition_mounted(partition_name))

                if can_remove:
                    # Create button box for install and delete buttons
                    button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
                    button_box.set_margin_top(6)
                    button_box.set_margin_bottom(6)
                    button_box.set_margin_start(6)
                    button_box.set_margin_end(6)

                    # Install button with popover
                    install_button = Gtk.MenuButton()
                    install_button.set_icon_name("document-save-symbolic")
                    install_button.add_css_class("suggested-action")
                    install_button.set_valign(Gtk.Align.CENTER)
                    ctx = install_button.get_style_context()
                    ctx.add_class("wide-button")
                    install_button.set_size_request(42, 40)

                    # Create and set popover
                    popover = self.create_os_popover(partition_name)
                    install_button.set_popover(popover)

                    # Delete button
                    delete_button = Gtk.Button()
                    delete_button.set_icon_name("user-trash-symbolic")
                    delete_button.add_css_class("destructive-action")
                    delete_button.set_valign(Gtk.Align.CENTER)
                    ctx = delete_button.get_style_context()
                    ctx.add_class("wide-button")
                    delete_button.set_size_request(42, 40)
                    delete_button.connect("clicked", lambda btn, p=partition_name: self.show_delete_dialog(p))

                    button_box.append(install_button)
                    button_box.append(delete_button)
                    row.add_suffix(button_box)

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
            self.show_queue_warning_dialog(name, size)
        except ValueError:
            self.show_toast("Invalid size value")

    def show_queue_warning_dialog(self, name, size):
        """
        Show warning dialog when there's already a queued partition.

        Args:
            name (str): Name of the new installation
            size (str): Size of the new installation
        """
        queued = actions.get_queued_partition()
        if queued:
            partition_name, display_name = queued
            dialog = Adw.MessageDialog(
                transient_for=self,
                heading="Partition Already Queued",
                body=f"A partition installation ({display_name}) is already queued. Creating a new queue will remove the existing one. Do you want to continue?",
                modal=True
            )

            dialog.add_response("cancel", "Cancel")
            dialog.add_response("continue", "Continue")
            dialog.set_response_appearance("continue", Adw.ResponseAppearance.SUGGESTED)

            dialog.connect("response", self.on_queue_warning_response, name, size)
            dialog.present()
        else:
            # No queue exists, proceed directly with creation
            self.create_new_partition(name, size)

    def create_new_partition(self, name, size):
        """
        Create a new partition.

        Args:
            name (str): Name of the new installation
            size (str): Size of the new installation
        """
        success, message = actions.create_install_commands(name, size)
        self.show_toast(message)
        if success:
            self.process_partitions()
            self.show_reboot_dialog()

    def show_reboot_dialog(self):
        """Show dialog informing user they can reboot to apply changes."""
        dialog = Adw.MessageDialog(
            transient_for=self,
            heading="Installation Queued",
            body="The installation has been queued successfully. You can now reboot your device for the changes to take effect.",
            modal=True
        )

        dialog.add_response("ok", "OK")
        dialog.present()

    def on_queue_warning_response(self, dialog, response, name, size):
        """
        Handle queue warning dialog response.

        Args:
            dialog: The dialog widget
            response: User's response
            name: Name of the new installation
            size: Size of the new installation
        """
        if response == "continue":
            self.create_new_partition(name, size)
        dialog.close()

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
            success, message = actions.delete_install_commands(partition_name)
            self.show_toast(message)
            if success:
                self.process_partitions()
                self.show_reboot_dialog()
        dialog.close()

    def show_error_dialog(self, message):
        """
        Show an error dialog with a message.

        Args:
            message (str): Error message to display
        """
        dialog = Adw.MessageDialog(
            transient_for=self,
            heading="Error",
            body=message,
            modal=True
        )

        dialog.add_response("ok", "OK")
        dialog.present()

    def refresh_ui(self):
        """Refresh all UI elements."""
        self.process_partitions()
        self.display_queued_partition()

    def create_os_popover(self, partition_name):
        """
        Create a popover with supported OS options.

        Args:
            partition_name (str): Name of the target partition

        Returns:
            Gtk.Popover: Configured popover widget
        """
        popover = Gtk.Popover()
        popover_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        popover_box.add_css_class("menu")

        title = Adw.PreferencesGroup()
        title.set_title("Select Operating System")

        # Add a row for each supported OS
        for os_name, description, icon_name in actions.get_supported_operating_systems():
            os_row = Adw.ActionRow()
            os_row.set_title(os_name)
            os_row.set_subtitle(description)

            # Add OS icon
            icon = Gtk.Image()
            icon.set_from_icon_name(icon_name)
            os_row.add_prefix(icon)

            # Add arrow
            arrow = Gtk.Image()
            arrow.set_from_icon_name("go-next-symbolic")
            os_row.add_suffix(arrow)

            # Make the row clickable
            row_click = Gtk.GestureClick.new()
            row_click.connect("released",
                              lambda gesture, n_press, x, y, part=partition_name, os=os_name:
                              self.on_install_os(part, os))
            os_row.add_controller(row_click)

            title.add(os_row)

        popover_box.append(title)
        popover.set_child(popover_box)
        return popover

    def on_install_os(self, partition_name, os_name):
        """
        Handle OS installation selection.

        Args:
            partition_name (str): Name of the partition to install to
            os_name (str): Name of the OS to install
        """
        url = actions.get_os_download_url(os_name)
        if not url:
            self.show_toast(f"Download URL not found for {os_name}")
            return

        dialog = self.create_download_dialog(partition_name, os_name, url)
        dialog.present()

    def create_download_dialog(self, partition_name, os_name, url):
        """
        Create a dialog with a progress bar for downloading.

        Args:
            partition_name (str): Target partition name
            os_name (str): Name of OS being installed
            url (str): Download URL

        Returns:
            Adw.MessageDialog: Dialog with progress bar
        """
        dialog = Adw.MessageDialog(
            transient_for=self,
            modal=True,
            heading=f"Downloading {os_name}",
            body=f"Downloading {os_name} for installation..."
        )

        # Store download state
        download_state = {
            'completed': False,
            'cancelled': False
        }
        dialog.download_state = download_state

        # Create content box for progress
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        content.set_margin_top(12)
        content.set_margin_bottom(12)

        # Add status label
        status_label = Gtk.Label()
        status_label.set_text("Starting download...")
        status_label.set_halign(Gtk.Align.START)
        content.append(status_label)

        # Add progress bar
        progress_bar = Gtk.ProgressBar()
        progress_bar.set_show_text(True)
        progress_bar.set_text("0%")
        progress_bar.set_valign(Gtk.Align.CENTER)
        content.append(progress_bar)

        dialog.set_extra_child(content)

        # Add cancel button
        dialog.add_response("cancel", "Cancel")
        dialog.set_response_appearance("cancel", Adw.ResponseAppearance.DESTRUCTIVE)

        # Start download in a separate thread
        cancel_event = threading.Event()
        download_thread = threading.Thread(
            target=self.download_os_image,
            args=(url, progress_bar, status_label, dialog, cancel_event,
                  partition_name, os_name, download_state)
        )

        # Connect cancel button
        dialog.connect("response", lambda dlg, resp: self.on_download_response(dlg, resp, cancel_event, download_state))

        download_thread.daemon = True
        download_thread.start()

        return dialog

    def on_download_response(self, dialog, response, cancel_event, download_state):
        """
        Handle dialog response (typically cancel button).
        """
        if not download_state['completed'] and not download_state['cancelled']:
            download_state['cancelled'] = True
            cancel_event.set()
            self.show_toast("Download cancelled")
        dialog.close()

    def download_os_image(self, url, progress_bar, status_label, dialog,
                          cancel_event, partition_name, os_name, download_state):
        """Download OS image with progress updates."""
        try:
            response = urllib.request.urlopen(url)
            total_size = int(response.headers.get('content-length', 0))
            block_size = 8192
            downloaded = 0

            save_path = f"/tmp/{os_name.lower()}-{partition_name}.img"
            with open(save_path, 'wb') as f:
                while True:
                    if cancel_event.is_set():
                        # Clean up partial download
                        os.unlink(save_path)
                        return

                    buffer = response.read(block_size)
                    if not buffer:
                        break

                    downloaded += len(buffer)
                    f.write(buffer)

                    # Update progress
                    progress = downloaded / total_size
                    GLib.idle_add(self.update_progress,
                                  progress_bar,
                                  status_label,
                                  progress,
                                  downloaded,
                                  total_size)

            # Download complete
            download_state['completed'] = True
            GLib.idle_add(self.download_complete,
                          dialog,
                          save_path,
                          partition_name,
                          os_name)

        except Exception as e:
            if not cancel_event.is_set():
                GLib.idle_add(self.download_error, dialog, str(e))

    def download_complete(self, dialog, save_path, partition_name, os_name):
        """Handle download completion."""
        dialog.close()
        self.show_toast(f"Download complete: {os_name}")
        print(f"Downloaded image saved to: {save_path}")
        return False

    def download_error(self, dialog, error_message):
        """Handle download error."""
        dialog.close()
        self.show_error_dialog(f"Download failed: {error_message}")
        return False

    def cancel_download(self, cancel_event, dialog):
        """
        Handle download cancellation.

        Args:
            cancel_event (threading.Event): Event to signal cancellation
            dialog (Adw.MessageDialog): Dialog to close
        """
        cancel_event.set()
        dialog.close()
        self.show_toast("Download cancelled")

    def update_progress(self, progress_bar, status_label, progress, downloaded, total):
        """Update progress bar and status label."""
        progress_bar.set_fraction(progress)
        progress_bar.set_text(f"{int(progress * 100)}%")

        # Format sizes
        downloaded_mb = downloaded / (1024 * 1024)
        total_mb = total / (1024 * 1024)
        status_label.set_text(f"Downloaded: {downloaded_mb:.1f} MB / {total_mb:.1f} MB")
        return False

    def download_complete(self, dialog, save_path, partition_name, os_name):
        """Handle download completion."""
        dialog.close()
        self.show_toast(f"Download complete: {os_name}")
        print(f"Downloaded image saved to: {save_path}")
        # TODO: implement installation
        return False

    def download_error(self, dialog, error_message):
        """Handle download error."""
        dialog.close()
        self.show_error_dialog(f"Download failed: {error_message}")
        return False
