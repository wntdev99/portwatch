PREFIX  ?= $(HOME)/.local
BINDIR  := $(PREFIX)/bin
APPDIR  := $(PREFIX)/share/applications
CONFIG  := $(HOME)/.config/portwatch.json

.PHONY: install uninstall run demo check help

help:
	@echo "make install    - install portwatch into $(BINDIR)"
	@echo "make uninstall  - remove portwatch, its desktop entry and its config"
	@echo "make run        - run from the source tree"
	@echo "make demo       - run with fake data (for screenshots)"
	@echo "make check      - byte-compile the source"

install:
	install -Dm755 portwatch $(BINDIR)/portwatch
	install -Dm644 data/portwatch.desktop $(APPDIR)/portwatch.desktop
	sed -i 's|^Exec=.*|Exec=$(BINDIR)/portwatch|' $(APPDIR)/portwatch.desktop
	-update-desktop-database $(APPDIR)
	@echo "설치 완료 — 런처에서 'PortWatch'를 검색하거나 터미널에서 portwatch 를 실행하세요."

uninstall:
	rm -f $(BINDIR)/portwatch $(APPDIR)/portwatch.desktop $(CONFIG)
	-update-desktop-database $(APPDIR)
	@echo "제거 완료."

run:
	./portwatch

demo:
	PORTWATCH_DEMO=1 ./portwatch

check:
	python3 -m py_compile portwatch
	@echo "문법 검사 통과"
