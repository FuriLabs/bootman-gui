# SPDX-License-Identifier: GPL-2.0
# Copyright (C) 2026 Bardia Moshiri <bardia@furilabs.com>

import gi
gi.require_version('Adw', '1')
from gi.repository import Adw

from bootman.bootman_window import BootmanWindow

class BootmanApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id='io.furios.Bootman')
        self.connect('activate', self.on_activate)

    def on_activate(self, app):
        self.win = BootmanWindow(application=app)
        self.win.present()
