PREFIX  ?= $(HOME)/.local
BINDIR  := $(PREFIX)/bin
LIBDIR  := $(PREFIX)/share/portwatch
APPDIR  := $(PREFIX)/share/applications

.PHONY: install uninstall run web demo check help

help:
	@echo "make install    - $(BINDIR) 에 설치합니다 (pip 없이 복사만 합니다)"
	@echo "make uninstall  - 설치한 파일과 설정을 지웁니다"
	@echo "make run        - 소스 트리에서 바로 실행합니다 (OS 기본 화면)"
	@echo "make web        - 브라우저 화면으로 실행합니다"
	@echo "make demo       - 가상 데이터로 실행합니다 (스크린샷용)"
	@echo "make check      - 바이트 컴파일과 간단한 점검"

install:
	rm -rf $(LIBDIR)
	mkdir -p $(LIBDIR) $(BINDIR) $(APPDIR)
	cp -r portwatch $(LIBDIR)/
	sed 's|__LIBDIR__|$(LIBDIR)|' data/portwatch.in > $(BINDIR)/portwatch
	chmod 755 $(BINDIR)/portwatch
	install -Dm644 data/portwatch.desktop $(APPDIR)/portwatch.desktop
	sed -i.bak 's|^Exec=.*|Exec=$(BINDIR)/portwatch|' $(APPDIR)/portwatch.desktop && rm -f $(APPDIR)/portwatch.desktop.bak
	-update-desktop-database $(APPDIR) 2>/dev/null
	@echo "설치 완료 — 런처에서 'PortWatch' 를 검색하거나 터미널에서 portwatch 를 실행하세요."

uninstall:
	rm -rf $(LIBDIR) $(BINDIR)/portwatch $(APPDIR)/portwatch.desktop
	rm -f $(HOME)/.config/portwatch.json $(HOME)/.config/portwatch/config.json
	-update-desktop-database $(APPDIR) 2>/dev/null
	@echo "제거 완료."

run:
	python3 -m portwatch

web:
	python3 -m portwatch --web

demo:
	PORTWATCH_DEMO=1 python3 -m portwatch

check:
	python3 -m compileall -q portwatch
	python3 -c "from portwatch.core import collect; rows = collect(); print(f'{len(rows)} 행 수집')"
	@echo "점검 통과"
