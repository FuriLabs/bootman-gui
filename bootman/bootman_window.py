# SPDX-License-Identifier: GPL-2.0
# Copyright (C) 2025 Bardia Moshiri <bardia@furilabs.com>

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GLib
from pathlib import Path
import urllib.request
import threading
import hashlib

import bootman.bootman_actions as actions
from bootman import ui

class BootmanWindow(Adw.ApplicationWindow):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.connect("close-request", lambda _: exit(0))
        self.set_default_size(400, 600)

        self.cache_dir = Path.home() / ".cache" / "bootman"

        # Initialize UI components
        self.setup_ui()
        self.present()

        # Delayed check for mount and partitions
        GLib.timeout_add(100, self.delayed_check_mount_and_partitions)

    def setup_ui(self):
        """Setup the main UI layout."""
        # Create main layout
        self.toast_overlay, self.toolbar_view, self.install_bottom_sheet, self.navigation_view = ui.create_main_window_layout()

        # Header setup
        self.header = ui.create_header_bar(self.show_new_install_dialog)

        # Content setup
        content_box, self.partition_list, self.queued_list = ui.create_content_layout()

        # Navigation and layout setup
        self.main_page = Adw.NavigationPage(title="Main Page")
        self.main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.main_box.append(self.header)
        self.main_box.append(content_box)
        self.main_page.set_child(self.main_box)

        self.navigation_view.add(self.main_page)
        self.set_content(self.toast_overlay)

    def show_toast(self, message, duration=3):
        """Display a toast message."""
        print(message)

        toast = Adw.Toast(title=message)
        self.toast_overlay.add_toast(toast)

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
            if not actions.is_mounted("/var/lib/furios-persist"):
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
        partitions_file = Path("/var/lib/furios-persist/bootman/partitions")

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
        ui.clear_list_widget(self.queued_list)

        # Check for queued partition
        queued = actions.get_queued_partition()
        if queued:
            operation, partition_name, display_name = queued
            row = ui.create_queued_partition_row(display_name, operation,
                                                 lambda btn: self.show_reboot_dialog())
            self.queued_list.append(row)

    def display_partitions(self, partitions_file):
        """Display partitions in the UI list."""
        ui.clear_list_widget(self.partition_list)

        try:
            ubuntu_userdata_owner = actions.get_ubuntu_userdata_owner()

            skip_partitions = []
            if ubuntu_userdata_owner:
                skip_partitions = ["ubuntu-userdata"]

            partitions = actions.read_partitions_file(partitions_file)
            is_encrypted = actions.is_encrypted()

            for partition_name, display_name in partitions:
                # Skip the userdata partition as we'll show it merged with its owner
                if partition_name in skip_partitions:
                    continue

                # Determine subtitle
                subtitle = None
                if ubuntu_userdata_owner and partition_name == ubuntu_userdata_owner:
                    size = actions.get_partition_size(partition_name)
                    userdata_size = actions.get_partition_size("ubuntu-userdata")

                    if size != "Unknown" and userdata_size != "Unknown":
                        subtitle = f"Ubuntu Touch - System: {size}, Userdata: {userdata_size}"
                    elif size != "Unknown":
                        subtitle = f"Ubuntu Touch - System: {size}"
                    else:
                        subtitle = "Ubuntu Touch"
                else:
                    # Normal partition display
                    size = actions.get_partition_size(partition_name)
                    if size != "Unknown":
                        subtitle = f"Size: {size}"

                can_remove = (partition_name != 'droidian-rootfs' and partition_name != 'furios-rootfs' and
                              not actions.is_partition_mounted(partition_name))

                install_callback = None
                delete_callback = None

                if can_remove:
                    install_callback = lambda p=partition_name: self.show_os_selection_bottom_sheet(p)
                    delete_callback = lambda btn, p=partition_name: self.show_delete_dialog(p)

                row = ui.create_partition_row(display_name, subtitle, can_remove,
                                              partition_name, is_encrypted,
                                              install_callback, delete_callback)

                self.partition_list.append(row)
        except Exception as e:
            self.show_toast(f"Error reading partitions: {str(e)}")

    def show_os_selection_bottom_sheet(self, partition_name):
        """Show the OS selection bottom sheet."""
        if actions.is_encrypted():
            self.show_encryption_warning_dialog()
            return

        try:
            supported_os = actions.get_supported_operating_systems()

            def on_os_selected(part_name, os_name):
                # Close the bottom sheet first
                self.install_bottom_sheet.set_open(False)
                # Then proceed with installation
                self.on_install_os(part_name, os_name)

            content = ui.create_os_selection_bottom_sheet(partition_name, supported_os, on_os_selected)

            # Use the existing install_bottom_sheet for OS selection too
            self.install_bottom_sheet.set_sheet(content)
            self.install_bottom_sheet.set_open(True)
        except Exception as e:
            self.show_toast(f"Error showing OS selection: {str(e)}")

    def show_new_install_dialog(self, button):
        """Show dialog for creating a new partition install."""
        # Check if device is encrypted first
        if actions.is_encrypted():
            self.show_encryption_warning_dialog()
            return

        external_disks = actions.get_external_disks()

        def on_apply():
            name = widgets['name_entry'].get_text()
            size = widgets['size_entry'].get_text() if widgets['local_button'].get_active() else None

            # Get selected storage
            storage_location = None
            if not widgets['local_button'].get_active():
                for button, disk in widgets['external_buttons'].items():
                    if button.get_active():
                        storage_location = disk
                        break

            self.on_new_install_apply(name, size, storage_location)

        def on_cancel(button):
            self.install_bottom_sheet.set_open(False)

        content, widgets = ui.create_new_install_dialog_content(external_disks, on_apply, on_cancel)

        # Setup validation
        ui.setup_name_entry_validation(widgets['name_entry'])
        ui.setup_size_entry_validation(widgets['size_entry'])

        # Setup storage selection change handler
        def on_storage_selection_changed(button):
            widgets['size_entry'].set_sensitive(button == widgets['local_button'])

        widgets['local_button'].connect("toggled", on_storage_selection_changed)
        for ext_button in widgets['external_buttons'].keys():
            ext_button.connect("toggled", on_storage_selection_changed)

        # Connect apply button
        widgets['apply_button'].connect("clicked", lambda btn: on_apply())

        self.install_bottom_sheet.set_sheet(content)
        self.install_bottom_sheet.set_open(True)

    def show_encryption_warning_dialog(self):
        """Show warning dialog when device is encrypted."""
        dialog = ui.create_alert_dialog(
            self,
            "Installation Unavailable",
            "Device is encrypted, cannot proceed"
        )
        dialog.present(self)

    def on_new_install_apply(self, name, size, storage_location=None):
        """Handle new install application."""
        if not name:
            self.show_toast("Name and size are required")
            return

        if not all(part.isalnum() for part in name.split()):
            self.show_toast("Name can only contain letters and numbers")
            return

        if storage_location is None:  # Local install
            if not size:
                self.show_toast("Size is required for local installation")
                return
            try:
                size_num = int(size)
                if size_num <= 0:
                    self.show_toast("Size must be greater than 0")
                    return
            except ValueError:
                self.show_toast("Invalid size value")

        partition_name = name.replace(" ", "-").lower()
        if partition_name == "ubuntu-userdata":
            self.show_toast("Partition name is reserved")
            return

        self.install_bottom_sheet.set_open(False)
        self.show_queue_warning_dialog(self.create_new_partition, name, size, storage_location)

    def show_queue_warning_dialog(self, callback, *callback_args, **callback_kwargs):
        """Show warning dialog when there's already a queued partition."""
        queued = actions.get_queued_partition()
        if queued:
            operation, partition_name, display_name = queued
            op_text = "installation" if operation == "install" else "deletion"

            responses = [
                ("cancel", "Cancel", None),
                ("continue", "Continue", Adw.ResponseAppearance.SUGGESTED)
            ]

            dialog = ui.create_alert_dialog(
                self,
                "Operation Already Queued",
                f"A partition {op_text} ({display_name}) is already queued. Creating a new queue will remove the existing one. Do you want to continue?",
                responses
            )

            # Store callback and args in dialog for use in response handler
            dialog.callback = callback
            dialog.callback_args = callback_args
            dialog.callback_kwargs = callback_kwargs

            dialog.connect("response", self.on_queue_warning_response)
            dialog.present(self)
        else:
            # No queue exists, proceed directly with the callback
            callback(*callback_args, **callback_kwargs)

    def on_queue_warning_response(self, dialog, response):
        """Handle queue warning dialog response."""
        if response == "continue":
            dialog.callback(*dialog.callback_args, **dialog.callback_kwargs)
        dialog.close()

    def create_new_partition(self, name, size, storage_location=None):
        """Create a new partition."""
        if storage_location:
            success, message = actions.create_external_install_commands(name, storage_location)
        else:
            success, message = actions.create_install_commands(name, size)

        self.show_toast(message)
        if success:
            self.process_partitions()
            self.show_reboot_dialog()

    def show_reboot_dialog(self):
        """Show dialog informing user they can reboot to apply changes."""
        queued = actions.get_queued_partition()
        if not queued:
            return

        operation, partition_name, display_name = queued
        op_text = "installation" if operation == "install" else "deletion"

        dialog = ui.create_alert_dialog(
            self,
            f"{op_text.title()} Queued",
            f"The partition {op_text} has been queued successfully. You can now reboot your device for the changes to take effect."
        )
        dialog.present(self)

    def show_delete_dialog(self, partition_name):
        """Show confirmation dialog for deleting a partition."""
        self.show_queue_warning_dialog(
            self.show_delete_confirmation,
            partition_name
        )

    def show_delete_confirmation(self, partition_name):
        """Show final confirmation dialog for deleting a partition."""
        responses = [
            ("cancel", "Cancel", None),
            ("delete", "Delete", Adw.ResponseAppearance.DESTRUCTIVE)
        ]

        dialog = ui.create_alert_dialog(
            self,
            "Confirm Deletion",
            f"Do you want to remove {partition_name}?",
            responses
        )

        dialog.connect("response", self.on_delete_response, partition_name)
        dialog.present(self)

    def on_delete_response(self, dialog, response, partition_name):
        """Handle partition deletion response."""
        if response == "delete":
            ubuntu_owner = actions.get_ubuntu_userdata_owner()
            if ubuntu_owner and ubuntu_owner == partition_name:
                # Ubuntu Touch partition (needs special handling)
                success, message = actions.create_delete_ubuntu_commands(partition_name)
            else:
                # Normal partition
                success, message = actions.create_delete_commands(partition_name)
            self.show_toast(message)
            if success:
                self.process_partitions()
                self.show_reboot_dialog()
        dialog.close()

    def show_error_dialog(self, message):
        """Show an error dialog with a message."""
        dialog = ui.create_alert_dialog(self, "Error", message)
        dialog.present(self)

    def on_install_os(self, partition_name, os_name):
        """Handle OS installation selection."""
        try:
            if os_name == "Ubuntu Touch":
                if actions.is_ubuntu_partition_available():
                    self.show_toast("An Ubuntu Touch installation exists already")
                    return

                self.show_queue_warning_dialog(
                    self.proceed_with_os_install,
                    partition_name,
                    os_name
                )
            else:
                # Proceed with normal installation flow
                self.proceed_with_os_install(partition_name, os_name)
        except Exception as e:
            self.show_toast(f"Error during OS installation: {str(e)}")

    def proceed_with_os_install(self, partition_name, os_name):
        """Proceed with OS installation."""
        try:
            url, md5_url = actions.get_os_download_info(os_name)

            self.cache_dir.mkdir(parents=True, exist_ok=True)
            save_path = self.cache_dir / f"{os_name.lower()}.img"
            checksum_path = save_path.with_suffix(".md5")

            # First check for existing file and verify if needed
            if save_path.exists():
                if checksum_path.exists():
                    # Show verification dialog and start verification in background
                    status_dialog = ui.create_status_dialog(self, f"Processing {os_name}", "Verifying existing file...")
                    status_dialog.present(self)
                    verify_thread = threading.Thread(
                        target=self.verify_file_thread,
                        args=(save_path, md5_url, status_dialog, partition_name, os_name, url)
                    )
                    verify_thread.daemon = True
                    verify_thread.start()
                else:
                    # No MD5 to verify, show redownload dialog directly
                    self.show_redownload_prompt(partition_name, os_name, url, md5_url, save_path)
            else:
                # No existing file, start download directly
                self.start_download(partition_name, os_name, url, md5_url)
        except Exception as e:
            self.show_toast(f"Error proceeding with OS install: {str(e)}")

    def connect_cancel_button(self, dialog, cancel_event):
        """Connect cancel button to the cancel event."""
        dialog.connect("response", lambda dlg, resp: self.handle_verification_cancel(dlg, resp, cancel_event))
        return False

    def verify_file_thread(self, file_path, md5_url, dialog, partition_name, os_name, url):
        """Verify file in a background thread."""
        try:
            # Create cancel event
            cancel_event = threading.Event()
            GLib.idle_add(self.connect_cancel_button, dialog, cancel_event)
            checksum_path = file_path.with_suffix(".md5")

            # Get expected MD5
            with open(checksum_path, 'r') as f:
                expected_md5 = f.read().split()[0]

            # Calculate MD5 of existing file
            md5_hash = hashlib.md5()
            file_size = file_path.stat().st_size
            read_size = 0

            f = None
            try:
                f = open(file_path, 'rb')

                while True:
                    if cancel_event.is_set():
                        f.close()
                        GLib.idle_add(self.handle_verification_cancelled, dialog)
                        return

                    buffer = f.read(8192)
                    if not buffer:
                        break

                    md5_hash.update(buffer)
                    read_size += len(buffer)

                    # Update dialog text with progress
                    progress = read_size / file_size
                    GLib.idle_add(
                        lambda: dialog.set_body(f"Verifying: {(progress * 100):.1f}%")
                    )
            finally:
                if f:
                    f.close()

            if not cancel_event.is_set():
                calculated_md5 = md5_hash.hexdigest()
                valid = calculated_md5 == expected_md5

                GLib.idle_add(self.handle_verification_complete,
                              dialog, valid, file_path, partition_name, os_name, url, md5_url)
        except Exception as e:
            print(f"Verification failed: {e}")
            if not cancel_event.is_set():
                GLib.idle_add(self.handle_verification_complete,
                              dialog, False, file_path, partition_name, os_name, url, md5_url)

    def handle_verification_complete(self, dialog, valid, file_path, partition_name, os_name, url, md5_url):
        """Handle completion of file verification."""
        dialog.close()

        if valid:
            # This was an existing file verification
            if url:
                # Show redownload prompt
                self.show_redownload_prompt(partition_name, os_name, url, md5_url, file_path)
            else:  # This was a post-download verification
                self.show_toast(f"Verification complete - installing {os_name}")
                self.install_with_progress(partition_name, os_name, file_path)
        else:
            # File is invalid, remove it and start download
            file_path.unlink(missing_ok=True)
            self.show_toast("Existing file is invalid - downloading new copy")
            self.start_download(partition_name, os_name, url, md5_url)
        return False

    def show_redownload_prompt(self, partition_name, os_name, url, md5_url, save_path):
        """Show the redownload dialog."""
        dialog = ui.create_redownload_dialog(self, save_path)
        dialog.connect("response", lambda dlg, resp: self.handle_redownload_response(
            dlg, resp, partition_name, os_name, url, md5_url, save_path))
        dialog.present(self)

    def handle_redownload_response(self, dialog, response, partition_name, os_name, url, md5_url, save_path):
        """Handle user's choice about redownloading."""
        dialog.close()

        if response == "redownload":
            # User wants to redownload
            save_path.unlink(missing_ok=True)
            self.start_download(partition_name, os_name, url, md5_url)
        else:
            # User wants to use existing file
            self.show_toast(f"Using existing file for {os_name}")
            self.install_with_progress(partition_name, os_name, save_path)

    def start_download(self, partition_name, os_name, url, md5_url):
        """Start the download process with progress dialog."""
        if not url:
            self.show_toast(f"This device does not have a version of {os_name} available")
            return

        # Create download state
        download_state = {
            'completed': False,
            'cancelled': False
        }

        def on_cancel(dialog, response):
            if not download_state['completed'] and not download_state['cancelled']:
                download_state['cancelled'] = True
                cancel_event.set()
                self.show_toast("Download cancelled")
            dialog.close()

        dialog, progress_bar, status_label = ui.create_download_dialog(self, os_name, on_cancel)
        dialog.download_state = download_state
        dialog.present(self)

        # Start download in a separate thread
        cancel_event = threading.Event()
        download_thread = threading.Thread(
            target=self.download_os_image,
            args=(url, md5_url, progress_bar, status_label, dialog, cancel_event,
                  partition_name, os_name, download_state)
        )

        download_thread.daemon = True
        download_thread.start()

    def download_os_image(self, url, md5_url, progress_bar, status_label, dialog,
                          cancel_event, partition_name, os_name, download_state):
        """Download OS image with progress updates and MD5 verification if available."""
        try:
            save_path = self.cache_dir / f"{os_name.lower()}.img"
            checksum_path = save_path.with_suffix(".md5")

            # Download new file
            response = urllib.request.urlopen(url)
            total_size = int(response.headers.get('content-length', 0))
            block_size = 8192
            downloaded = 0
            md5_hash = hashlib.md5()

            with open(save_path, 'wb') as f:
                while True:
                    if cancel_event.is_set():
                        # Clean up partial download
                        save_path.unlink(missing_ok=True)
                        return

                    buffer = response.read(block_size)
                    if not buffer:
                        break

                    downloaded += len(buffer)
                    f.write(buffer)
                    md5_hash.update(buffer)

                    # Update progress
                    progress = downloaded / total_size
                    GLib.idle_add(self.update_progress,
                                  progress_bar,
                                  status_label,
                                  progress,
                                  downloaded,
                                  total_size)

            # Verify MD5 if we have it
            if md5_url:
                try:
                    with open(checksum_path, 'w') as f:
                        md5_response = urllib.request.urlopen(md5_url)
                        expected_md5 = md5_response.read().decode().split()[0]
                        f.write(expected_md5)
                    calculated_md5 = md5_hash.hexdigest()
                    if calculated_md5 != expected_md5:
                        raise Exception("MD5 verification failed")
                except Exception as e:
                    print(f"MD5 verification failed: {e}")
                    raise

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

    def update_progress(self, progress_bar, status_label, progress, downloaded, total):
        """Update progress bar and status label."""
        progress_bar.set_fraction(progress)
        progress_bar.set_text(f"{int(progress * 100)}%")

        # Format sizes
        downloaded_mb = downloaded / (1024 * 1024)
        total_mb = total / (1024 * 1024)
        status_label.set_text(f"Downloaded: {downloaded_mb:.1f} MB / {total_mb:.1f} MB")
        return False

    def install_with_progress(self, partition_name, os_name, save_path):
        """Start installation with progress dialog."""
        dialog, title_label, terminal, close_button = ui.create_progress_dialog(self, f"Installing {os_name}...")
        dialog.present()

        buff = terminal.get_buffer()

        def append_output(line):
            GLib.idle_add(
                lambda: buff.insert_at_cursor(line) or
                terminal.scroll_to_mark(buff.get_insert(), 0.0, False, 0.0, 1.0)
            )

        def run_install():
            try:
                success, message = actions.run_install_commands(
                    partition_name, save_path, append_output)
                GLib.idle_add(lambda: self.handle_install_complete(
                    dialog, title_label, close_button, success, message, os_name, partition_name))
            except Exception as e:
                print(f"error: {e}")
                GLib.idle_add(lambda: self.handle_install_complete(
                    dialog, title_label, close_button, False, str(e), os_name, partition_name))

        # Start installation in background thread
        install_thread = threading.Thread(target=run_install)
        install_thread.daemon = True
        install_thread.start()

    def handle_install_complete(self, dialog, title_label, close_button, success, message, os_name, partition_name):
        """Handle installation completion."""
        if success:
            if os_name == "Ubuntu Touch":
                self.start_userdata_split_immediate(partition_name)

            title_label.set_text(f"Successfully installed {os_name}!")
            self.show_toast(f"Successfully installed {os_name}")
        else:
            title_label.set_text("Installation Failed!")
            self.show_error_dialog(f"Installation failed: {message}")

        close_button.set_sensitive(True)
        return False

    def start_userdata_split_immediate(self, partition_name):
        """Run the Ubuntu Touch userdata split immediately with progress output."""
        dialog, title_label, terminal, close_button = ui.create_progress_dialog(self, "Preparing Ubuntu userdata…")
        dialog.present()

        buff = terminal.get_buffer()

        def append_output(line):
            GLib.idle_add(
                lambda: buff.insert_at_cursor(line) or
                terminal.scroll_to_mark(buff.get_insert(), 0.0, False, 0.0, 1.0)
            )

        def worker():
            try:
                success, message = actions.create_ubuntu_userdata_commands(
                    partition_name,
                    output_callback=append_output
                )
                def finish():
                    if success:
                        title_label.set_text("Ubuntu userdata created!")
                        self.show_toast("Ubuntu userdata created")
                        # Refresh lists to show new LV and merged subtitle
                        self.process_partitions()
                    else:
                        title_label.set_text("Ubuntu userdata failed!")
                        self.show_error_dialog(message)
                    close_button.set_sensitive(True)
                GLib.idle_add(finish)
            except Exception as e:
                GLib.idle_add(lambda: (
                    title_label.set_text("Ubuntu userdata failed!"),
                    self.show_error_dialog(str(e)),
                    close_button.set_sensitive(True)
                ))

        t = threading.Thread(target=worker, daemon=True)
        t.start()

    def download_complete(self, dialog, save_path, partition_name, os_name):
        """Handle download completion."""
        dialog.close()

        # Get the md5_url again since we don't have it from the download context
        _, md5_url = actions.get_os_download_info(os_name)

        if md5_url:
            # Show verification dialog and start verification in background
            status_dialog = ui.create_status_dialog(self, f"Processing {os_name}", "Verifying downloaded file...")
            status_dialog.present(self)

            verify_thread = threading.Thread(
                target=self.verify_file_thread,
                args=(save_path, md5_url, status_dialog, partition_name, os_name, None)  # url is None since we don't need to redownload
            )
            verify_thread.daemon = True
            verify_thread.start()
        else:
            self.show_toast(f"Download complete: {os_name}")
            print(f"Downloaded image saved to: {save_path}")
            self.install_with_progress(partition_name, os_name, save_path)
        return False

    def handle_verification_cancel(self, dialog, response, cancel_event):
        """Handle cancel button click during verification."""
        if response == "cancel":
            dialog.close()
            cancel_event.set()

    def handle_verification_cancelled(self, dialog):
        """Handle when verification is cancelled."""
        dialog.close()
        self.show_toast("Verification cancelled")
        return False

    def download_error(self, dialog, error_message):
        """Handle download error."""
        dialog.close()
        self.show_error_dialog(f"Download failed: {error_message}")
        return False
