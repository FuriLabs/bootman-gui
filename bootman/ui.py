# SPDX-License-Identifier: GPL-2.0
# Copyright (C) 2026 Bardia Moshiri <bardia@furilabs.com>

import gi
from typing import Callable, Optional, List, Dict, Sequence, Tuple, Union
from pathlib import Path

from bootman.models import OperatingSystem, OSRelease

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, Pango, GLib

def create_header_bar(add_callback: Callable = None) -> Adw.HeaderBar:
    """Create the main header bar with title and add button."""
    header = Adw.HeaderBar()
    header.set_title_widget(Adw.WindowTitle(title="Boot Manager"))

    if add_callback:
        add_button = Gtk.Button()
        add_button.set_icon_name("list-add-symbolic")
        add_button.connect("clicked", add_callback)
        header.pack_end(add_button)

    return header

def create_section_header(title: str) -> Gtk.Label:
    """Create a bold section header label."""
    label = Gtk.Label(label=title)
    label.set_halign(Gtk.Align.START)
    label.set_margin_bottom(6)
    attr_list = Pango.AttrList()
    attr_list.insert(Pango.attr_weight_new(Pango.Weight.BOLD))
    label.set_attributes(attr_list)
    return label

def create_boxed_list() -> Gtk.ListBox:
    """Create a styled list box with boxed appearance."""
    list_box = Gtk.ListBox()
    list_box.set_selection_mode(Gtk.SelectionMode.NONE)
    list_box.add_css_class("boxed-list")
    return list_box

def create_partition_row(display_name: str, subtitle: str = None, can_remove: bool = False,
                         partition_name: str = None, is_encrypted: bool = False,
                         install_callback: Callable = None, delete_callback: Callable = None) -> Adw.ActionRow:
    """Create a row for displaying partition information."""
    row = Adw.ActionRow(title=display_name)

    if subtitle:
        safe_subtitle = GLib.markup_escape_text(subtitle)
        row.set_subtitle(safe_subtitle)

    if can_remove and (install_callback or delete_callback):
        # Create button box for install and delete buttons
        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        button_box.set_margin_top(6)
        button_box.set_margin_bottom(6)
        button_box.set_margin_start(6)
        button_box.set_margin_end(6)

        if install_callback:
            # Install button (now regular button instead of MenuButton)
            install_button = Gtk.Button()
            install_button.set_icon_name("document-save-symbolic")
            install_button.add_css_class("suggested-action")
            install_button.set_valign(Gtk.Align.CENTER)
            ctx = install_button.get_style_context()
            ctx.add_class("wide-button")
            install_button.set_size_request(36, 34)

            # Disable button if device is encrypted
            if is_encrypted:
                install_button.set_sensitive(False)
                install_button.set_tooltip_text("Device is encrypted - installation unavailable")
            else:
                install_button.connect("clicked", lambda btn: install_callback(partition_name))

            # Store partition name for later use
            install_button.partition_name = partition_name

            button_box.append(install_button)

        if delete_callback:
            # Delete button
            delete_button = Gtk.Button()
            delete_button.set_icon_name("user-trash-symbolic")
            delete_button.add_css_class("destructive-action")
            delete_button.set_valign(Gtk.Align.CENTER)
            delete_button.connect("clicked", delete_callback)
            ctx = delete_button.get_style_context()
            ctx.add_class("wide-button")
            delete_button.set_size_request(36, 34)
            button_box.append(delete_button)

        row.add_suffix(button_box)

    return row

def create_queued_partition_row(display_name: str, operation: str,
                                restart_callback: Callable = None) -> Adw.ActionRow:
    """Create a row for displaying queued partition operations."""
    row = Adw.ActionRow(title=display_name)

    if operation == 'install':
        row.set_subtitle("Queued for installation")
        status_icon = Gtk.Image.new_from_icon_name("document-save-symbolic")
    else:  # delete
        row.set_subtitle("Queued for deletion")
        status_icon = Gtk.Image.new_from_icon_name("user-trash-symbolic")

    status_icon.set_margin_start(6)
    status_icon.set_margin_end(6)
    row.add_suffix(status_icon)

    if restart_callback:
        # Create restart button
        restart_button = Gtk.Button()
        restart_button.set_icon_name("view-refresh-symbolic")
        restart_button.set_valign(Gtk.Align.CENTER)
        restart_button.set_margin_start(6)
        restart_button.set_margin_end(6)
        restart_button.add_css_class("suggested-action")
        restart_button.connect("clicked", restart_callback)
        row.add_suffix(restart_button)

    return row

def create_os_selection_bottom_sheet(partition_name: str,
                                     supported_os_list: Sequence[OperatingSystem],
                                     install_callback: Callable,
                                     local_file_callback: Callable) -> Adw.NavigationView:
    """Create a navigable OS selector with support for nested release options."""
    navigation_view = Adw.NavigationView()

    def create_selection_page(title: str) -> Tuple[Adw.NavigationPage,
                                                   Adw.PreferencesGroup]:
        page = Adw.NavigationPage(title=title)
        page_content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        header = Adw.HeaderBar()
        header.set_title_widget(Adw.WindowTitle(title=title))
        page_content.append(header)

        selection_content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        selection_content.set_margin_top(12)
        selection_content.set_margin_bottom(24)
        selection_content.set_margin_start(24)
        selection_content.set_margin_end(24)

        option_group = Adw.PreferencesGroup()
        selection_content.append(option_group)
        page_content.append(selection_content)
        page.set_child(page_content)
        return page, option_group

    def create_option_row(
        option: Union[OperatingSystem, OSRelease],
    ) -> Adw.ActionRow:
        option_row = Adw.ActionRow(
            title=option.name,
            subtitle=option.description,
        )
        option_row.set_activatable(True)

        icon = Gtk.Image.new_from_icon_name(option.icon_name)
        option_row.add_prefix(icon)

        arrow = Gtk.Image.new_from_icon_name("go-next-symbolic")
        option_row.add_suffix(arrow)
        return option_row

    def create_release_page(
        operating_system: OperatingSystem,
    ) -> Adw.NavigationPage:
        page, option_group = create_selection_page(
            f"Select {operating_system.name} Version"
        )

        for release in operating_system.options:
            option_row = create_option_row(release)
            option_row.connect(
                "activated",
                lambda row, download=release.download: install_callback(
                    partition_name, download
                ),
            )
            option_group.add(option_row)

        local_row = Adw.ActionRow(
            title="Local",
            subtitle="Install an OS image from a local file",
        )
        local_row.set_activatable(True)
        local_row.add_prefix(Gtk.Image.new_from_icon_name("folder-open-symbolic"))
        local_row.add_suffix(Gtk.Image.new_from_icon_name("go-next-symbolic"))
        os_type = operating_system.options[0].download.os_type
        local_row.connect(
            "activated",
            lambda row, selected_os_type=os_type: local_file_callback(
                partition_name, selected_os_type
            ),
        )
        option_group.add(local_row)

        return page

    main_page, os_group = create_selection_page("Select Operating System")
    for operating_system in supported_os_list:
        os_row = create_option_row(operating_system)
        os_row.connect(
            "activated",
            lambda row, selected=operating_system: navigation_view.push(
                create_release_page(selected)
            ),
        )
        os_group.add(os_row)

    navigation_view.add(main_page)
    return navigation_view

def create_new_install_dialog_content(external_disks: List[str],
                                      apply_callback: Callable,
                                      cancel_callback: Callable) -> Tuple[Gtk.Box, Dict[str, Gtk.Widget]]:
    """Create the content for new install dialog."""
    content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
    content.set_margin_top(48)
    content.set_margin_bottom(24)
    content.set_margin_start(24)
    content.set_margin_end(24)

    # Name entry
    name_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
    name_label = Gtk.Label(label="Install Name")
    name_label.set_width_chars(15)
    name_entry = Gtk.Entry()
    name_entry.set_hexpand(True)
    name_box.append(name_label)
    name_box.append(name_entry)
    content.append(name_box)

    # Size entry
    size_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
    size_label = Gtk.Label(label="Install Size (GB)")
    size_label.set_width_chars(15)
    size_entry = Gtk.Entry()
    size_entry.set_input_purpose(Gtk.InputPurpose.DIGITS)
    size_entry.set_hexpand(True)
    size_box.append(size_label)
    size_box.append(size_entry)
    content.append(size_box)

    # Storage location expander
    expander = Adw.ExpanderRow()
    expander.set_title("Storage Location")

    local_button = Gtk.CheckButton()
    local_button.set_label("Install to local storage")
    local_button.set_active(True)
    expander.add_row(local_button)

    external_buttons = {}
    for disk in external_disks:
        ext_button = Gtk.CheckButton()
        ext_button.set_label(f"Install to external storage ({disk})")
        ext_button.set_group(local_button)
        expander.add_row(ext_button)
        external_buttons[ext_button] = disk

    content.append(expander)

    # Button box
    button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
    button_box.set_homogeneous(True)
    button_box.set_margin_top(12)

    cancel_button = Gtk.Button(label="Cancel")
    cancel_button.set_hexpand(True)
    cancel_button.set_halign(Gtk.Align.FILL)
    cancel_button.connect("clicked", cancel_callback)
    button_box.append(cancel_button)

    apply_button = Gtk.Button(label="Apply")
    apply_button.set_hexpand(True)
    apply_button.set_halign(Gtk.Align.FILL)
    apply_button.add_css_class("suggested-action")
    button_box.append(apply_button)

    content.append(button_box)

    widgets = {
        'name_entry': name_entry,
        'size_entry': size_entry,
        'local_button': local_button,
        'external_buttons': external_buttons,
        'apply_button': apply_button,
        'cancel_button': cancel_button
    }

    return content, widgets

def create_main_window_layout() -> Tuple[Adw.ToastOverlay, Adw.ToolbarView, Adw.BottomSheet, Adw.NavigationView]:
    """Create the main window layout structure."""
    toast_overlay = Adw.ToastOverlay()
    toolbar_view = Adw.ToolbarView()
    install_bottom_sheet = Adw.BottomSheet()
    install_bottom_sheet.set_modal(True)

    navigation_view = Adw.NavigationView()

    install_bottom_sheet.set_content(navigation_view)
    toolbar_view.set_content(install_bottom_sheet)
    toast_overlay.set_child(toolbar_view)

    return toast_overlay, toolbar_view, install_bottom_sheet, navigation_view

def create_content_layout() -> Tuple[Gtk.Box, Gtk.ListBox, Gtk.ListBox]:
    """Create the main content layout with partition lists."""
    content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    content_box.set_margin_top(12)
    content_box.set_margin_bottom(12)
    content_box.set_margin_start(12)
    content_box.set_margin_end(12)

    # Installed Systems section
    systems_label = create_section_header("Installed Systems")
    content_box.append(systems_label)

    partition_list = create_boxed_list()
    content_box.append(partition_list)

    # Add spacing between sections
    separator = Gtk.Box()
    separator.set_margin_top(12)
    separator.set_margin_bottom(12)
    content_box.append(separator)

    # Queued Partitions section
    queued_label = create_section_header("Queued Partition")
    content_box.append(queued_label)

    queued_list = create_boxed_list()
    content_box.append(queued_list)

    return content_box, partition_list, queued_list

def create_alert_dialog(parent, heading: str, body: str, responses: List[Tuple[str, str, Optional[Adw.ResponseAppearance]]] = None) -> Adw.AlertDialog:
    """Create an alert dialog with specified responses."""
    dialog = Adw.AlertDialog(
        heading=heading,
        body=body
    )

    if responses:
        for response_id, response_text, appearance in responses:
            dialog.add_response(response_id, response_text)
            if appearance:
                dialog.set_response_appearance(response_id, appearance)
    else:
        dialog.add_response("ok", "OK")

    return dialog

def create_download_dialog(parent, os_name: str, cancel_callback: Callable) -> Tuple[Adw.AlertDialog, Gtk.ProgressBar, Gtk.Label]:
    """Create a download dialog with progress bar."""
    dialog = Adw.AlertDialog(
        heading=f"Downloading {os_name}",
        body=f"Downloading {os_name} for installation..."
    )

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
    dialog.connect("response", cancel_callback)

    return dialog, progress_bar, status_label

def create_status_dialog(parent, heading: str, message: str) -> Adw.AlertDialog:
    """Create a simple status dialog for operations like verification."""
    dialog = Adw.AlertDialog(
        heading=heading,
        body=message
    )

    # Add cancel button
    dialog.add_response("cancel", "Cancel")
    dialog.set_response_appearance("cancel", Adw.ResponseAppearance.DESTRUCTIVE)

    return dialog

def create_redownload_dialog(parent, file_path: Path) -> Adw.AlertDialog:
    """Create dialog asking if user wants to redownload existing file."""
    dialog = Adw.AlertDialog(
        heading="File Already Exists",
        body="This file has already been downloaded. Do you want to download it again?"
    )

    dialog.add_response("use_existing", "Use Existing")
    dialog.add_response("redownload", "Download Again")
    dialog.set_response_appearance("redownload", Adw.ResponseAppearance.SUGGESTED)

    return dialog

def create_progress_dialog(parent, title: str) -> Tuple[Adw.Dialog, Gtk.Label, Gtk.TextView, Gtk.Button]:
    """Create a progress dialog for installation operations."""
    dialog = Adw.Dialog(title=title, can_close=False)
    dialog.set_content_width(parent.get_width())
    dialog.set_content_height(parent.get_height())

    content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
    content_box.set_margin_top(24)
    content_box.set_margin_bottom(24)
    content_box.set_margin_start(24)
    content_box.set_margin_end(24)
    dialog.set_child(content_box)

    title_label = Gtk.Label(label=title)
    title_label.set_halign(Gtk.Align.CENTER)
    title_label.set_margin_bottom(12)
    title_label.get_style_context().add_class('heading')
    content_box.append(title_label)

    scrolled = Gtk.ScrolledWindow()
    scrolled.set_vexpand(True)
    scrolled.get_style_context().add_class('view')
    content_box.append(scrolled)

    terminal = Gtk.TextView()
    terminal.set_editable(False)
    terminal.set_monospace(True)
    scrolled.set_child(terminal)

    close_button = Gtk.Button(label='Close')
    close_button.connect('clicked', lambda _: dialog.force_close())
    close_button.set_halign(Gtk.Align.CENTER)
    close_button.add_css_class('suggested-action')
    close_button.set_margin_top(12)
    close_button.set_sensitive(False)
    content_box.append(close_button)

    return dialog, title_label, terminal, close_button

def find_install_button_in_row(row: Adw.ActionRow) -> Optional[Gtk.Button]:
    """
    Find the install button (Button) in a partition row.

    Args:
        row: The ActionRow to search in

    Returns:
        The Button if found, None otherwise
    """
    def search_widget(widget):
        if isinstance(widget, Gtk.Button):
            # Check if this is the install button by looking for the save icon
            if widget.get_icon_name() == "document-save-symbolic":
                return widget
        elif hasattr(widget, 'get_first_child'):
            # Recursively search child widgets
            child = widget.get_first_child()
            while child:
                result = search_widget(child)
                if result:
                    return result
                child = child.get_next_sibling()
        return None

    return search_widget(row)

def clear_list_widget(list_widget: Gtk.ListBox):
    """Clear all children from a list widget."""
    while True:
        row = list_widget.get_first_child()
        if row is None:
            break
        list_widget.remove(row)

def setup_name_entry_validation(entry: Gtk.Entry):
    """Setup validation for name entry to only accept alphanumeric characters."""
    def on_name_insert(entry, text, length, position):
        # Only allow letters and numbers
        if not all(c.isalnum() for c in text):
            entry.stop_emission_by_name("insert-text")
            return True
        return False

    entry.connect("insert-text", on_name_insert)

def setup_size_entry_validation(entry: Gtk.Entry):
    """Setup validation for size entry to only accept digits."""
    def on_size_insert(entry, text, length, position):
        if not text.isdigit():
            entry.stop_emission_by_name("insert-text")
            return True
        return False

    entry.connect("insert-text", on_size_insert)
