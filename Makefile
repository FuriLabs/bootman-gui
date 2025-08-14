PREFIX ?= /usr
LIBDIR = $(PREFIX)/lib
BINDIR = $(PREFIX)/bin
LIBEXECDIR = $(PREFIX)/libexec
SHAREDIR = $(PREFIX)/share

INSTALL_DIR = $(LIBDIR)/bootman
DESKTOP_DIR = $(SHAREDIR)/applications
ICON_DIR = $(SHAREDIR)/icons/hicolor/scalable/apps
POLKIT_DIR = $(SHAREDIR)/polkit-1/actions

.PHONY: all install uninstall

all:
	@echo "Run 'make install' to install the files."

install:
	install -d $(DESTDIR)$(INSTALL_DIR)
	install -d $(DESTDIR)$(BINDIR)
	install -d $(DESTDIR)$(LIBEXECDIR)
	install -d $(DESTDIR)$(DESKTOP_DIR)
	install -d $(DESTDIR)$(ICON_DIR)
	install -d $(DESTDIR)$(POLKIT_DIR)

	cp -r bootman $(DESTDIR)$(INSTALL_DIR)/

	install -m 755 main.py $(DESTDIR)$(INSTALL_DIR)/
	install -m 755 scripts/bootman-helper $(DESTDIR)$(LIBEXECDIR)/

	install -m 644 data/io.FuriOS.Bootman.desktop $(DESTDIR)$(DESKTOP_DIR)/
	install -m 644 data/io.FuriOS.Bootman.svg $(DESTDIR)$(ICON_DIR)/
	install -m 0644 data/io.furios.bootman.policy $(DESTDIR)$(POLKIT_DIR)/

	ln -sf ../lib/bootman/main.py $(DESTDIR)$(BINDIR)/io.FuriOS.Bootman

uninstall:
	rm -f $(DESTDIR)$(BINDIR)/io.FuriOS.Bootman
	rm -f $(DESTDIR)$(LIBEXECDIR)/bootman-helper

	rm -rf $(DESTDIR)$(INSTALL_DIR)
	rm -f $(DESTDIR)$(DESKTOP_DIR)/io.FuriOS.Bootman.desktop
	rm -f $(DESTDIR)$(ICON_DIR)/io.FuriOS.Bootman.svg
	rm -f $(DESTIDR)$(POLKIT_DIR)/io.furios.bootman.policy
