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
"""

import json
from collections.abc import Callable

from qtmonaco import Monaco
from qtmonaco.resource_loader import get_monaco_base_url, get_monaco_html

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
              background-color: rgba(70, 180, 90, 0.36) !important;
              box-shadow: inset 4px 0 0 rgba(80, 200, 100, 1);
            }
            .monaco-editor .bigo-line-gray {
              background-color: rgba(150, 150, 150, 0.36) !important;
              box-shadow: inset 4px 0 0 rgba(220, 220, 220, 1);
            }
            .monaco-editor .bigo-line-yellow {
              background-color: rgba(210, 180, 60, 0.40) !important;
              box-shadow: inset 4px 0 0 rgba(245, 220, 100, 1);
            }
            .monaco-editor .bigo-line-red {
              background-color: rgba(220, 85, 85, 0.42) !important;
              box-shadow: inset 4px 0 0 rgba(255, 120, 120, 1);
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

            .monaco-editor .bigo-inline-green {
              background-color: rgba(70, 180, 90, 0.26) !important;
            }
            .monaco-editor .bigo-inline-gray {
              background-color: rgba(150, 150, 150, 0.26) !important;
            }
            .monaco-editor .bigo-inline-yellow {
              background-color: rgba(210, 180, 60, 0.30) !important;
            }
            .monaco-editor .bigo-inline-red {
              background-color: rgba(220, 85, 85, 0.30) !important;
            }

            .monaco-editor .bigo-gutter-green {
              border-left: 3px solid rgba(80, 200, 100, 1) !important;
              margin-left: 2px;
            }
            .monaco-editor .bigo-gutter-gray {
              border-left: 3px solid rgba(200, 200, 200, 1) !important;
              margin-left: 2px;
            }
            .monaco-editor .bigo-gutter-yellow {
              border-left: 3px solid rgba(235, 210, 90, 1) !important;
              margin-left: 2px;
            }
            .monaco-editor .bigo-gutter-red {
              border-left: 3px solid rgba(245, 110, 110, 1) !important;
              margin-left: 2px;
            }
            .bigo-zone-label {
              font-size: 11px;
              font-style: italic;
              padding: 0 6px;
              opacity: 0.95;
              line-height: 16px;
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
        var markers = [];
        var hints = [];
        var zones = [];
        var model = ed.getModel();
        if (!model) {
            return JSON.stringify({ ok: false, error: "No Monaco model" });
        }
        // Для linesDecorationsClassName/glyph-вставок.
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
            ds.push({
                range: new monaco.Range(s, 1, e, endCol),
                options: {
                    isWholeLine: true,
                    className: rangeClass,
                    lineClassName: rangeClass,
                    inlineClassName: inlineClass,
                    linesDecorationsClassName: gutterClass,
                    hoverMessage: [{ value: hover }],
                    minimap: { color: "rgba(220,220,220,0.35)", position: 2 },
                    overviewRuler: {
                        color: (sev === "green" ? "rgba(80,200,100,0.9)" :
                                sev === "yellow" ? "rgba(235,210,90,0.9)" :
                                sev === "red" ? "rgba(245,110,110,0.9)" :
                                "rgba(200,200,200,0.85)"),
                        position: monaco.editor.OverviewRulerLane.Full
                    }
                }
            });
            markers.push({
                startLineNumber: s,
                startColumn: 1,
                endLineNumber: s,
                endColumn: 1,
                severity: monaco.MarkerSeverity.Hint,
                message: lbl + " " + hover,
                source: "Big-O"
            });
            hints.push({
                position: { lineNumber: s, column: 1 },
                label: lbl + " ",
                kind: monaco.languages.InlayHintKind.Type
            });
            if (!seenZoneLine[s]) {
                seenZoneLine[s] = true;
                zones.push({ line: s, severity: sev, label: lbl });
            }
        }
        window.__bigODecorIds = ed.deltaDecorations(window.__bigODecorIds, ds);
        monaco.editor.setModelMarkers(model, "bigo", markers);

        if (window.__bigOInlayProviderDispose) {
            try { window.__bigOInlayProviderDispose.dispose(); } catch (e) {}
            window.__bigOInlayProviderDispose = null;
        }
        var lang = model.getLanguageId();
        window.__bigOInlayProviderDispose = monaco.languages.registerInlayHintsProvider(
            lang,
            {
                provideInlayHints: function(_model, _range, _token) {
                    return { hints: hints, dispose: function(){} };
                }
            }
        );
        ed.updateOptions({ inlayHints: { enabled: "on" } });

        // CodeLens-подписи (самый заметный и совместимый канал подписи).
        if (window.__bigOCodeLensDispose) {
            try { window.__bigOCodeLensDispose.dispose(); } catch (e) {}
            window.__bigOCodeLensDispose = null;
        }
        var lenses = [];
        for (var i = 0; i < rows.length; i++) {
            var r = rows[i];
            var s = Math.max(1, Math.min(maxLine, Number(r.startLine || 1)));
            var lbl = "Big-O: " + (r.label || "O(?)");
            lenses.push({
                range: { startLineNumber: s, startColumn: 1, endLineNumber: s, endColumn: 1 },
                id: "bigo-" + i,
                command: { id: "bigo.nop", title: lbl }
            });
        }
        window.__bigOCodeLensDispose = monaco.languages.registerCodeLensProvider(lang, {
            provideCodeLenses: function(_model, _token) {
                return { lenses: lenses, dispose: function(){} };
            },
            resolveCodeLens: function(model, codeLens, token) { return codeLens; }
        });

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
                dom.className = 'bigo-zone-label bigo-zone-' + z.severity;
                dom.textContent = z.label;
                var zid = accessor.addZone({
                    afterLineNumber: Math.max(1, z.line - 1),
                    heightInPx: 16,
                    suppressMouseDown: false,
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


class CustomMonaco(Monaco):
    def _load_editor(self):
        raw_html = get_monaco_html()
        base_url = get_monaco_base_url()
        raw_html = raw_html.replace("globalAPI: false", "globalAPI: true")
        self.setHtml(raw_html, base_url)

    def request_cursor_position(self, callback: Callable[..., None]) -> None:
        """Асинхронно запросить строку и столбец каретки (1-based), как в Monaco."""
        self.page().runJavaScript(_MONACO_CURSOR_POS_JS, callback)

    def clear_big_o_overlays(self) -> None:
        self.page().runJavaScript(_BIG_O_CLEAR_JS)

    def apply_big_o_overlays(self, rows: list[dict], callback: Callable[..., None] | None = None) -> None:
        payload = json.dumps(rows, ensure_ascii=False)
        js = _BIG_O_APPLY_JS_TEMPLATE.replace("__BIG_O_ROWS__", payload)
        if callback is None:
            self.page().runJavaScript(js)
        else:
            self.page().runJavaScript(js, callback)

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
