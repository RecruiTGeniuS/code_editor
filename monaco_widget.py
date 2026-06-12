"""
Кастомный виджет Monaco, в котором `monaco` доступен из глобальной области JS.

`qtmonaco` по умолчанию запускает Monaco c `MonacoEnvironment.globalAPI = false`,
поэтому JS-объект `monaco` не виден из `runJavaScript()` — нельзя ни регистрировать
кастомные темы, ни вызывать любые публичные API Monaco напрямую. Эта обёртка
переопределяет `_load_editor`, чтобы перед `setHtml` патчить только эту настройку.
Сам пакет `qtmonaco` не модифицируется — патчится только HTML-байтстрим перед
загрузкой в QWebEngineView, поэтому обновление пакета ничего не сломает.

Позицию курсора для статус-бара берём через `runJavaScript`: свойство
`Monaco.current_cursor` в qtmonaco не обновляется при движении каретки, зато
`editor.getPosition()` в Monaco всегда актуально.

Big-O overlay-слой:
  - apply_big_o_overlays / clear_big_o_overlays — подсветка, decorations и
    view zone с подписью сложности (см. `_BIG_O_APPLY_JS_TEMPLATE`).
  - рядом с подписью view zone находится кнопка "AI рецензия блока".
  - JS открывает невидимый iframe с URL `bigo-review:/<block_id>`; `_BigOReviewPage`
    перехватывает этот URL и транслирует `block_review_requested(str)` в Python.
"""

import json
from collections.abc import Callable
from urllib.parse import unquote

from qtmonaco import Monaco
from qtmonaco.monaco_page import MonacoPage
from qtmonaco.resource_loader import get_monaco_base_url, get_monaco_html
from PySide6.QtCore import Signal

from bigo_bridge import BigOBridge

# Возвращает JSON-строку { "line": number, "column": number } или пустую строку.
_MONACO_CURSOR_POS_JS = """
(function() {
    try {
        if (typeof monaco === "undefined" || !monaco.editor) return "";
        var eds = monaco.editor.getEditors();
        if (!eds || eds.length === 0) return "";
        var ed = eds[0];
        var p = ed.getPosition();
        if (!p) return "";
        return JSON.stringify({ line: p.lineNumber, column: p.column });
    } catch (e) {
        return "";
    }
})()
"""

_MONACO_STICKY_SCROLL_JS = """
(function() {
    try {
        if (typeof monaco === "undefined" || !monaco.editor) return;
        var eds = monaco.editor.getEditors();
        if (!eds || eds.length === 0) return;
        var ed = eds[0];
        ed.updateOptions({
            stickyScroll: {
                enabled: true,
                maxLineCount: 2
            }
        });

        function getStickyRows() {
            var root = ed.getDomNode();
            if (!root) return { widget: null, rows: [], numbers: [] };
            var widget = root.querySelector(".sticky-widget");
            if (!widget) return { widget: null, rows: [], numbers: [] };
            var rows = Array.from(widget.querySelectorAll(".sticky-line"));
            if (!rows.length) {
                rows = Array.from(widget.querySelectorAll(".sticky-widget-line"));
            }
            if (!rows.length) {
                var scrollable = widget.querySelector(".sticky-widget-lines-scrollable");
                if (scrollable) {
                    rows = Array.from(scrollable.children).filter(function(el) {
                        return el && el.textContent && el.textContent.trim();
                    });
                }
            }
            var numbers = Array.from(widget.querySelectorAll(".sticky-line-number"));
            return { widget: widget, rows: rows, numbers: numbers };
        }

        function isClassLikeLine(text) {
            var t = String(text || "").trim();
            // Для class-based контекста разрешаем 2 строки: class + method.
            // Для standalone function оставляем только её первую строку.
            return /\b(class|interface|struct|enum|trait|record|object)\b/.test(t);
        }

        function applyStickyScrollLimit() {
            var info = getStickyRows();
            if (!info.widget || !info.rows.length) return;

            var firstText = info.rows[0].textContent || "";
            var allowed = isClassLikeLine(firstText) ? 2 : 1;
            for (var i = 0; i < info.rows.length; i++) {
                var visible = i < allowed;
                info.rows[i].style.display = visible ? "" : "none";
                if (info.numbers[i]) {
                    info.numbers[i].style.display = visible ? "" : "none";
                }
            }

            var firstRect = info.rows[0].getBoundingClientRect();
            var rowHeight = firstRect && firstRect.height ? firstRect.height : 19;
            var height = Math.max(rowHeight, rowHeight * Math.min(allowed, info.rows.length));
            info.widget.style.height = height + "px";
            info.widget.style.maxHeight = height + "px";
            info.widget.style.overflow = "hidden";

            var scrollable = info.widget.querySelector(".sticky-widget-lines-scrollable");
            if (scrollable) {
                scrollable.style.height = height + "px";
                scrollable.style.maxHeight = height + "px";
                scrollable.style.overflow = "hidden";
            }
            var numberPane = info.widget.querySelector(".sticky-widget-line-numbers");
            if (numberPane) {
                numberPane.style.height = height + "px";
                numberPane.style.maxHeight = height + "px";
                numberPane.style.overflow = "hidden";
            }
        }

        if (!window.__stickyScrollClassMethodLimiterInstalled) {
            window.__stickyScrollClassMethodLimiterInstalled = true;
            ed.onDidScrollChange(function() {
                window.requestAnimationFrame(applyStickyScrollLimit);
            });
            ed.onDidChangeModel(function() {
                setTimeout(applyStickyScrollLimit, 0);
            });
            var root = ed.getDomNode();
            if (root && window.MutationObserver) {
                var obs = new MutationObserver(function() {
                    window.requestAnimationFrame(applyStickyScrollLimit);
                });
                obs.observe(root, { childList: true, subtree: true, characterData: true });
                window.__stickyScrollClassMethodLimiterObserver = obs;
            }
        }
        setTimeout(applyStickyScrollLimit, 0);
    } catch (e) {}
})()
"""

_BIG_O_CLEAR_JS = """
(function() {
    try {
        if (typeof monaco === "undefined" || !monaco.editor) return;
        var eds = monaco.editor.getEditors();
        if (!eds || eds.length === 0) return;
        var ed = eds[0];
        if (!window.__bigODecorIds) window.__bigODecorIds = [];
        window.__bigODecorIds = ed.deltaDecorations(window.__bigODecorIds, []);
        if (window.__bigOZoneIds && window.__bigOZoneIds.length) {
            var zids = window.__bigOZoneIds.slice();
            ed.changeViewZones(function(accessor){
                for (var i=0;i<zids.length;i++) {
                    try { accessor.removeZone(zids[i]); } catch (e) {}
                }
            });
            window.__bigOZoneIds = [];
        }
        var model = ed.getModel();
        if (model) {
            monaco.editor.setModelMarkers(model, "bigo", []);
        }
        if (window.__bigOInlayProviderDispose) {
            try { window.__bigOInlayProviderDispose.dispose(); } catch (e) {}
            window.__bigOInlayProviderDispose = null;
        }
        if (window.__bigOCodeLensDispose) {
            try { window.__bigOCodeLensDispose.dispose(); } catch (e) {}
            window.__bigOCodeLensDispose = null;
        }
    } catch (e) {}
})()
"""

_BIG_O_APPLY_JS_TEMPLATE = r"""
(function() {
    try {
        if (typeof monaco === "undefined" || !monaco.editor) return;
        var eds = monaco.editor.getEditors();
        if (!eds || eds.length === 0) return;
        var ed = eds[0];
        if (!window.__bigODecorIds) window.__bigODecorIds = [];

        if (!document.getElementById("bigo-overlay-style")) {
            var st = document.createElement("style");
            st.id = "bigo-overlay-style";
            st.textContent = `
            .monaco-editor .bigo-line-green {
              background-color: rgba(70, 180, 90, 0.10) !important;
              box-shadow: inset 1px 0 0 rgba(80, 200, 100, 1);
            }
            .monaco-editor .bigo-line-gray {
              background-color: rgba(150, 150, 150, 0.10) !important;
              box-shadow: inset 1px 0 0 rgba(220, 220, 220, 1);
            }
            .monaco-editor .bigo-line-yellow {
              background-color: rgba(210, 180, 60, 0.10) !important;
              box-shadow: inset 1px 0 0 rgba(245, 220, 100, 1);
            }
            .monaco-editor .bigo-line-red {
              background-color: rgba(220, 85, 85, 0.10) !important;
              box-shadow: inset 1px 0 0 rgba(255, 120, 120, 1);
            }

            .monaco-editor .bigo-label-green {
              color: #77dd88 !important; font-style: italic; opacity: 1;
            }
            .monaco-editor .bigo-label-gray {
              color: #d0d0d0 !important; font-style: italic; opacity: 1;
            }
            .monaco-editor .bigo-label-yellow {
              color: #f2dc7b !important; font-style: italic; opacity: 1;
            }
            .monaco-editor .bigo-label-red {
              color: #ff9a9a !important; font-style: italic; opacity: 1;
            }

            # .monaco-editor .bigo-inline-green {
            #   background-color: rgba(70, 180, 90, 0.26) !important;
            # }
            # .monaco-editor .bigo-inline-gray {
            #   background-color: rgba(150, 150, 150, 0.26) !important;
            # }
            # .monaco-editor .bigo-inline-yellow {
            #   background-color: rgba(210, 180, 60, 0.30) !important;
            # }
            # .monaco-editor .bigo-inline-red {
            #   background-color: rgba(220, 85, 85, 0.30) !important;
            # }

            .monaco-editor .bigo-gutter-green {
              border-left: 2px solid rgba(80, 200, 100, 1) !important;
              margin-left: 2px;
            }
            .monaco-editor .bigo-gutter-gray {
              border-left: 2px solid rgba(200, 200, 200, 1) !important;
              margin-left: 2px;
            }
            .monaco-editor .bigo-gutter-yellow {
              border-left: 2px solid rgba(235, 210, 90, 1) !important;
              margin-left: 2px;
            }
            .monaco-editor .bigo-gutter-red {
              border-left: 2px solid rgba(245, 110, 110, 1) !important;
              margin-left: 2px;
            }
            .bigo-zone-row {
              display: inline-flex;
              align-items: center;
              gap: 6px;
              height: 22px;
              padding-left: 1px;
              position: relative;
              z-index: 80;
              pointer-events: auto;
              user-select: none;
            }
            .bigo-zone-chip {
              font-size: 12.5px;
              font-style: italic;
              line-height: 18px;
              opacity: 0.95;
              #transform: translateY(20px);
              position: relative;
              top: -2px;
            }
            .bigo-zone-review-btn {
              width: 22px;
              height: 22px;
              /* Previous filled-button look for quick rollback:
              border: 1px solid rgba(255, 255, 255, 0.12);
              border-radius: 7px;
              background: rgba(35, 38, 45, 0.48);
              box-shadow: 0 1px 4px rgba(0, 0, 0, 0.25);
              opacity: 0.78; */
              border: 1px solid transparent;
              border-radius: 7px;
              background: transparent;
              box-shadow: none;
              opacity: 0.82;
              cursor: pointer;
              display: inline-flex;
              align-items: center;
              justify-content: center;
              padding: 0;
              transition: opacity 120ms ease, background 120ms ease;
              transform: translateY(2px);
              position: relative;
              z-index: 81;
              pointer-events: auto;
            }
            .bigo-zone-review-btn:hover {
              /* Previous filled-button hover for quick rollback:
              background: rgba(55, 62, 75, 0.72); */
              opacity: 1;
              background: rgba(55, 62, 75, 0.24);
            }
            .bigo-zone-review-btn img {
              width: 15px;
              height: 15px;
              pointer-events: none;
            }
            .bigo-zone-review-fallback {
              color: #d8e0ee;
              font-size: 10px;
              font-weight: 600;
              pointer-events: none;
            }
            .bigo-zone-green { color: #77dd88; }
            .bigo-zone-gray { color: #d0d0d0; }
            .bigo-zone-yellow { color: #f2dc7b; }
            .bigo-zone-red { color: #ff9a9a; }
            `;
            document.head.appendChild(st);
        }

        var rows = __BIG_O_ROWS__;
        var ds = [];
        var zones = [];
        var model = ed.getModel();
        if (!model) {
            return JSON.stringify({ ok: false, error: "No Monaco model" });
        }
        ed.updateOptions({ glyphMargin: true });
        var maxLine = model.getLineCount();
        var seenZoneLine = {};
        for (var i = 0; i < rows.length; i++) {
            var r = rows[i];
            var sev = r.severity || "gray";
            var rangeClass = "bigo-line-" + sev;
            var labelClass = "bigo-label-" + sev;
            var inlineClass = "bigo-inline-" + sev;
            var gutterClass = "bigo-gutter-" + sev;
            var s = Math.max(1, Math.min(maxLine, Number(r.startLine || 1)));
            var e = Math.max(s, Math.min(maxLine, Number(r.endLine || s)));
            var endCol = model.getLineMaxColumn(e);
            var lbl = "[" + (r.label || "O(?)") + "]";
            var hover = (r.hover || r.label || "Big-O");
            // Minimap стабильнее принимает hex-цвета, чем rgba(...).
            // Эти значения соответствуют цветам Big-O подсветки в редакторе.
            var navColor = (sev === "green" ? "#50c864" :
                            sev === "yellow" ? "#ebd25a" :
                            sev === "red" ? "#f56e6e" :
                            "#c8c8c8");
            ds.push({
                range: new monaco.Range(s, 1, e, endCol),
                options: {
                    isWholeLine: true,
                    className: rangeClass,
                    lineClassName: rangeClass,
                    inlineClassName: inlineClass,
                    linesDecorationsClassName: gutterClass,
                    hoverMessage: [{ value: hover }],
                    minimap: {
                        color: navColor,
                        position: monaco.editor.MinimapPosition.Gutter
                    },
                    overviewRuler: {
                        color: navColor,
                        position: monaco.editor.OverviewRulerLane.Full
                    }
                }
            });
            if (!seenZoneLine[s]) {
                seenZoneLine[s] = true;
                zones.push({
                    line: s,
                    severity: sev,
                    label: lbl,
                    blockId: r.blockId || "",
                    confidence: r.confidence || "",
                    analyzerKind: r.analyzerKind || ""
                });
            }
        }
        window.__bigODecorIds = ed.deltaDecorations(window.__bigODecorIds, ds);
        monaco.editor.setModelMarkers(model, "bigo", []);

        if (window.__bigOInlayProviderDispose) {
            try { window.__bigOInlayProviderDispose.dispose(); } catch (e) {}
            window.__bigOInlayProviderDispose = null;
        }
        var lang = model.getLanguageId();

        if (window.__bigOCodeLensDispose) {
            try { window.__bigOCodeLensDispose.dispose(); } catch (e) {}
            window.__bigOCodeLensDispose = null;
        }

        if (window.__bigOZoneIds && window.__bigOZoneIds.length) {
            var old = window.__bigOZoneIds.slice();
            ed.changeViewZones(function(accessor){
                for (var i=0;i<old.length;i++) {
                    try { accessor.removeZone(old[i]); } catch (e) {}
                }
            });
        }
        window.__bigOZoneIds = [];
        ed.changeViewZones(function(accessor){
            for (var i=0;i<zones.length;i++) {
                var z = zones[i];
                var dom = document.createElement('div');
                dom.className = 'bigo-zone-row bigo-zone-' + z.severity;

                var chip = document.createElement('span');
                chip.className = 'bigo-zone-chip';
                chip.textContent = z.label;
                dom.appendChild(chip);

                if (z.blockId) {
                    var btn = document.createElement('button');
                    btn.className = 'bigo-zone-review-btn';
                    btn.type = 'button';
                    btn.dataset.blockId = z.blockId;
                    btn.setAttribute('title', 'Рецензия блока (AI)');
                    btn.setAttribute('aria-label', 'Рецензия блока');
                    if (z.confidence || z.analyzerKind) {
                        btn.setAttribute(
                            'data-bigo-meta',
                            [z.analyzerKind, z.confidence].filter(Boolean).join(' · ')
                        );
                    }
                    if (window.__bigoReviewIcon) {
                        var img = document.createElement('img');
                        img.alt = 'AI';
                        img.src = window.__bigoReviewIcon;
                        btn.appendChild(img);
                    } else {
                        var fallback = document.createElement('span');
                        fallback.className = 'bigo-zone-review-fallback';
                        fallback.textContent = 'AI';
                        btn.appendChild(fallback);
                    }
                    btn.addEventListener('mousedown', function(e) {
                        e.preventDefault();
                        e.stopPropagation();
                    });
                    btn.addEventListener('pointerdown', function(e) {
                        e.preventDefault();
                        e.stopPropagation();
                    });
                    btn.addEventListener('mouseup', function(e) {
                        e.preventDefault();
                        e.stopPropagation();
                    });
                    btn.addEventListener('click', function(e) {
                        e.preventDefault();
                        e.stopPropagation();
                        var bid = this.dataset.blockId || '';
                        if (!bid) return;
                        try {
                            var iframe = document.createElement('iframe');
                            iframe.style.display = 'none';
                            iframe.setAttribute('aria-hidden', 'true');
                            iframe.src = 'bigo-review:/' + encodeURIComponent(bid);
                            document.body.appendChild(iframe);
                            setTimeout(function() {
                                try { document.body.removeChild(iframe); } catch (err) {}
                            }, 120);
                        } catch (err) {
                            console.warn('[bigo] review nav failed:', err);
                        }
                    });
                    dom.appendChild(btn);
                }
                var zid = accessor.addZone({
                    afterLineNumber: Math.max(1, z.line - 1),
                    heightInPx: 24,
                    suppressMouseDown: true,
                    domNode: dom
                });
                window.__bigOZoneIds.push(zid);
            }
        });
        ed.layout();
        ed.render(true);
        return JSON.stringify({ ok: true, decorations: window.__bigODecorIds.length });
    } catch (e) {}
    return JSON.stringify({ ok: false, error: String(e) });
})()
"""


# Legacy hover ContentWidget-слой. Больше не устанавливается: кнопка рецензии
# теперь создаётся прямо в Big-O view zone рядом с подписью сложности. Оставлен
# как резерв, но `_install_big_o_review_layer` ниже поднимает только no-op state.
_BIG_O_REVIEW_LAYER_INSTALL_JS = r"""
(function() {
    try {
        if (window.__bigoReviewInstalled) return;
        window.__bigoReviewInstalled = true;
        window.__bigoReviewRows = window.__bigoReviewRows || [];
        window.__bigoReviewIcon = window.__bigoReviewIcon || "";

        if (!document.getElementById("bigo-review-style")) {
            var st = document.createElement("style");
            st.id = "bigo-review-style";
            st.textContent = `
            .bigo-review-btn {
              display: inline-flex;
              align-items: center;
              justify-content: center;
              width: 26px;
              height: 26px;
              margin-left: 8px;
              padding: 0;
              border: none;
              border-radius: 6px;
              background: rgba(40, 42, 48, 0.85);
              box-shadow: 0 1px 4px rgba(0, 0, 0, 0.45);
              cursor: pointer;
              opacity: 0;
              transition: opacity 120ms ease;
              z-index: 60;
              pointer-events: auto;
            }
            .bigo-review-btn.visible { opacity: 1; }
            .bigo-review-btn:hover {
              background: rgba(70, 80, 95, 0.95);
            }
            .bigo-review-btn img {
              width: 18px;
              height: 18px;
              pointer-events: none;
            }
            .bigo-review-btn .bigo-review-fallback {
              color: #d8e0ee;
              font-size: 11px;
              font-weight: 600;
              letter-spacing: 0.5px;
              pointer-events: none;
            }
            `;
            document.head.appendChild(st);
        }

        function ensureWidget(ed) {
            if (window.__bigoReviewWidget) return window.__bigoReviewWidget;
            var btn = document.createElement("button");
            btn.className = "bigo-review-btn";
            btn.type = "button";
            btn.setAttribute("title", "Рецензия блока (AI)");
            btn.setAttribute("aria-label", "Рецензия блока");
            if (window.__bigoReviewIcon) {
                var img = document.createElement("img");
                img.alt = "AI";
                img.src = window.__bigoReviewIcon;
                btn.appendChild(img);
            } else {
                var span = document.createElement("span");
                span.className = "bigo-review-fallback";
                span.textContent = "AI";
                btn.appendChild(span);
            }
            btn.addEventListener("mousedown", function(e) {
                e.preventDefault();
                e.stopPropagation();
            });
            btn.addEventListener("click", function(e) {
                e.preventDefault();
                e.stopPropagation();
                var bid = btn.dataset.blockId || "";
                if (!bid) return;
                // Невидимый iframe -> Python ловит navigation request на
                // схему bigo-review: и кэнсэлит её, эмитя signal.
                try {
                    var iframe = document.createElement("iframe");
                    iframe.style.display = "none";
                    iframe.setAttribute("aria-hidden", "true");
                    iframe.src = "bigo-review:/" + encodeURIComponent(bid);
                    document.body.appendChild(iframe);
                    setTimeout(function() {
                        try { document.body.removeChild(iframe); } catch (err) {}
                    }, 120);
                } catch (err) {
                    console.warn("[bigo] review nav failed:", err);
                }
            });
            btn.addEventListener("mouseenter", function() {
                window.__bigoReviewBtnHover = true;
            });
            btn.addEventListener("mouseleave", function() {
                window.__bigoReviewBtnHover = false;
                hideButton();
            });
            var widget = {
                _domNode: btn,
                _position: null,
                getId: function() { return "bigo.review.button"; },
                getDomNode: function() { return btn; },
                getPosition: function() {
                    if (!widget._position) return null;
                    return {
                        position: widget._position,
                        preference: [monaco.editor.ContentWidgetPositionPreference.EXACT]
                    };
                }
            };
            ed.addContentWidget(widget);
            window.__bigoReviewWidget = widget;
            return widget;
        }

        function findRowForLine(line) {
            var rows = window.__bigoReviewRows || [];
            for (var i = 0; i < rows.length; i++) {
                var r = rows[i];
                if (!r || !r.blockId) continue;
                if (line >= r.startLine && line <= r.endLine) return r;
            }
            return null;
        }

        function showButton(ed, row) {
            var widget = ensureWidget(ed);
            var model = ed.getModel();
            if (!model) return;
            var maxLine = model.getLineCount();
            var s = Math.max(1, Math.min(maxLine, Number(row.startLine || 1)));
            var col = model.getLineMaxColumn(s);
            widget._position = { lineNumber: s, column: col };
            widget._domNode.dataset.blockId = row.blockId;
            widget._domNode.classList.add("visible");
            ed.layoutContentWidget(widget);
        }

        function hideButton() {
            var widget = window.__bigoReviewWidget;
            if (!widget) return;
            widget._domNode.classList.remove("visible");
            widget._position = null;
            try {
                var eds = monaco.editor.getEditors();
                if (eds && eds[0]) eds[0].layoutContentWidget(widget);
            } catch (e) {}
        }
        window.__bigoReviewHide = hideButton;

        function attachEditor() {
            if (typeof monaco === "undefined" || !monaco.editor) return false;
            var eds = monaco.editor.getEditors();
            if (!eds || eds.length === 0) return false;
            var ed = eds[0];
            if (window.__bigoReviewAttached) return true;
            window.__bigoReviewAttached = true;
            ensureWidget(ed);

            ed.onMouseMove(function(ev) {
                var rows = window.__bigoReviewRows || [];
                if (!rows.length) { hideButton(); return; }
                var pos = ev && ev.target && ev.target.position;
                if (!pos) {
                    if (!window.__bigoReviewBtnHover) hideButton();
                    return;
                }
                var row = findRowForLine(pos.lineNumber);
                if (row) {
                    showButton(ed, row);
                } else if (!window.__bigoReviewBtnHover) {
                    hideButton();
                }
            });

            ed.onMouseLeave(function() {
                if (!window.__bigoReviewBtnHover) hideButton();
            });

            return true;
        }

        if (!attachEditor()) {
            var tries = 0;
            var tm = setInterval(function() {
                tries++;
                if (attachEditor() || tries > 40) clearInterval(tm);
            }, 100);
        }

        return "ok";
    } catch (e) {
        return "err:" + String(e);
    }
})()
"""

_BIG_O_REVIEW_SET_ROWS_JS_TEMPLATE = r"""
(function() {
    try {
        window.__bigoReviewRows = __BIG_O_REVIEW_ROWS__;
        if (typeof window.__bigoReviewHide === "function") {
            window.__bigoReviewHide();
        }
        return JSON.stringify({ ok: true, count: window.__bigoReviewRows.length });
    } catch (e) {
        return JSON.stringify({ ok: false, error: String(e) });
    }
})()
"""

_BIG_O_REVIEW_CLEAR_JS = r"""
(function() {
    window.__bigoReviewRows = [];
    if (typeof window.__bigoReviewHide === "function") {
        window.__bigoReviewHide();
    }
})()
"""

_BIG_O_REVIEW_SET_ICON_JS_TEMPLATE = r"""
(function() {
    window.__bigoReviewIcon = "__BIG_O_REVIEW_ICON__";
    document.querySelectorAll(".bigo-zone-review-btn").forEach(function(btn) {
        btn.innerHTML = "";
        if (window.__bigoReviewIcon) {
            var img = document.createElement("img");
            img.alt = "AI";
            img.src = window.__bigoReviewIcon;
            btn.appendChild(img);
        } else {
            var span = document.createElement("span");
            span.className = "bigo-zone-review-fallback";
            span.textContent = "AI";
            btn.appendChild(span);
        }
    });
    document.querySelectorAll(".bigo-zone-review-btn img").forEach(function(img) {
        img.src = window.__bigoReviewIcon;
    });
    if (window.__bigoReviewWidget) {
        var btn = window.__bigoReviewWidget._domNode;
        if (btn) {
            btn.innerHTML = "";
            if (window.__bigoReviewIcon) {
                var img = document.createElement("img");
                img.alt = "AI";
                img.src = window.__bigoReviewIcon;
                btn.appendChild(img);
            } else {
                var span = document.createElement("span");
                span.className = "bigo-review-fallback";
                span.textContent = "AI";
                btn.appendChild(span);
            }
        }
    }
})()
"""


class _BigOReviewPage(MonacoPage):
    """MonacoPage с перехватом bigo-review: для рецензии блока.

    JS делает невидимый iframe.src = "bigo-review:/<encoded block_id>".
    acceptNavigationRequest ловит это, отменяет навигацию и эмитит сигнал
    в BigOBridge — далее BigOController.review_block получает id блока.

    Альтернатива через второй QWebChannel(transport, …) ломает qtmonaco:
    transport.onmessage перетирается и сообщения connector → JS теряются.
    """

    def __init__(self, parent=None, bridge: "BigOBridge | None" = None):
        super().__init__(parent=parent)
        self._bigo_bridge = bridge

    def set_bigo_bridge(self, bridge: "BigOBridge") -> None:
        self._bigo_bridge = bridge

    def acceptNavigationRequest(self, url, nav_type, is_main_frame):  # noqa: N802
        try:
            if url.scheme() == "bigo-review":
                raw = url.path() or url.host() or ""
                if raw.startswith("/"):
                    raw = raw[1:]
                try:
                    block_id = unquote(raw)
                except Exception:
                    block_id = raw
                if self._bigo_bridge is not None and block_id:
                    self._bigo_bridge.block_review_requested.emit(block_id)
                return False
        except Exception:
            pass
        return super().acceptNavigationRequest(url, nav_type, is_main_frame)


class CustomMonaco(Monaco):
    block_review_requested = Signal(str)

    def __init__(self, parent=None):
        # Мост создаём заранее без parent — потом отдадим self как parent,
        # когда Qt-инициализация QWebEngineView завершится. Это упрощает
        # передачу bridge в _load_editor (его вызывает Monaco.__init__).
        self._bigo_bridge = BigOBridge()
        self._bigo_bridge.block_review_requested.connect(self._on_review_requested)
        super().__init__(parent=parent)
        self._bigo_bridge.setParent(self)
        self._review_layer_installed = False
        self.initialized.connect(self._install_big_o_review_layer)
        self.initialized.connect(self._configure_sticky_scroll)

    def _on_review_requested(self, block_id: str) -> None:
        self.block_review_requested.emit(block_id)

    def _load_editor(self):
        # Подменяем MonacoPage на наш subclass до setHtml. Канал qtmonaco
        # (_channel) уже создан и привязан к старой странице — перепривязываем
        # его к новой, чтобы connector остался живым.
        new_page = _BigOReviewPage(parent=self, bridge=self._bigo_bridge)
        self.setPage(new_page)
        try:
            new_page.setWebChannel(self._channel)
        except Exception:
            pass

        raw_html = get_monaco_html()
        base_url = get_monaco_base_url()
        raw_html = raw_html.replace("globalAPI: false", "globalAPI: true")
        self.setHtml(raw_html, base_url)

    def _install_big_o_review_layer(self) -> None:
        if self._review_layer_installed:
            return
        self._review_layer_installed = True
        self.page().runJavaScript(
            """
            (function() {
                window.__bigoReviewInstalled = true;
                window.__bigoReviewRows = [];
                window.__bigoReviewHide = function() {};
            })()
            """
        )

    def _configure_sticky_scroll(self) -> None:
        """Оставить Sticky Scroll как в VS Code: класс + текущий метод, не глубже."""
        self.page().runJavaScript(_MONACO_STICKY_SCROLL_JS)

    def set_big_o_review_icon(self, data_uri: str) -> None:
        """Установить data URI иконки для кнопки рецензии (icons/ai_ricense_block.png)."""
        safe = (data_uri or "").replace("\\", "\\\\").replace('"', '\\"')
        js = _BIG_O_REVIEW_SET_ICON_JS_TEMPLATE.replace("__BIG_O_REVIEW_ICON__", safe)
        self.page().runJavaScript(js)

    def request_cursor_position(self, callback: Callable[..., None]) -> None:
        """Асинхронно запросить строку и столбец каретки (1-based), как в Monaco."""
        self.page().runJavaScript(_MONACO_CURSOR_POS_JS, callback)

    def clear_big_o_overlays(self) -> None:
        self.page().runJavaScript(_BIG_O_CLEAR_JS)
        self.clear_big_o_review_rows()

    def apply_big_o_overlays(self, rows: list[dict], callback: Callable[..., None] | None = None) -> None:
        payload = json.dumps(rows, ensure_ascii=False)
        js = _BIG_O_APPLY_JS_TEMPLATE.replace("__BIG_O_ROWS__", payload)
        if callback is None:
            self.page().runJavaScript(js)
        else:
            self.page().runJavaScript(js, callback)
        # Review-кнопка теперь создаётся прямо в view zone рядом с [O(...)].
        # Старый hover ContentWidget больше не получает rows, поэтому не
        # появляется в конце первой строки блока.
        self.clear_big_o_review_rows()

    def apply_big_o_review_rows(self, rows: list[dict]) -> None:
        """Передать набор overlay rows в слой кнопок рецензии.

        В JS остаётся фильтрация: кнопка показывается только для строк с
        непустым blockId, то есть фактически для overlayable-блоков.
        """
        review_rows = [
            {
                "blockId": r.get("blockId") or "",
                "filePath": r.get("filePath") or "",
                "startLine": int(r.get("startLine") or 1),
                "endLine": int(r.get("endLine") or r.get("startLine") or 1),
                "complexity": r.get("complexity"),
                "confidence": r.get("confidence"),
                "analyzerKind": r.get("analyzerKind") or "static",
            }
            for r in rows
            if r.get("blockId")
        ]
        payload = json.dumps(review_rows, ensure_ascii=False)
        js = _BIG_O_REVIEW_SET_ROWS_JS_TEMPLATE.replace(
            "__BIG_O_REVIEW_ROWS__", payload
        )
        self.page().runJavaScript(js)

    def clear_big_o_review_rows(self) -> None:
        self.page().runJavaScript(_BIG_O_REVIEW_CLEAR_JS)

    @staticmethod
    def parse_cursor_js_result(result) -> tuple[int, int] | None:
        """Разобрать результат runJavaScript в (line, column) или None."""
        if result is None:
            return None
        if isinstance(result, dict):
            data = result
        else:
            s = str(result).strip()
            if not s:
                return None
            try:
                data = json.loads(s)
            except (json.JSONDecodeError, TypeError):
                return None
        try:
            line = int(data.get("line") or data.get("lineNumber") or 0)
            col = int(data.get("column") or 0)
        except (TypeError, ValueError):
            return None
        if line < 1 or col < 1:
            return None
        return line, col
