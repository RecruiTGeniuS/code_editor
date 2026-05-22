"""
Кастомные темы для встроенного Monaco-редактора.

Формат словарей соответствует API `monaco.editor.defineTheme(name, themeData)`.
Цвета в `rules` указываются БЕЗ префикса `#`, в `colors` — С префиксом.
Подробнее: https://microsoft.github.io/monaco-editor/api/interfaces/monaco.editor.IStandaloneThemeData.html
"""

# Палитра One Dark Pro (по мотивам Atom One Dark, цвета взяты с
# https://github.com/Binaryify/OneDark-Pro). Фон редактора заменён на
# rgb(49, 51, 56) = #313338, чтобы совпадал с фоном основного приложения.
ONE_DARK_PRO_THEME = {
    "base": "vs-dark",
    "inherit": True,
    "rules": [
        {"token": "", "foreground": "abb2bf"},

        {"token": "comment", "foreground": "5c6370", "fontStyle": "italic"},

        {"token": "keyword", "foreground": "c678dd"},
        {"token": "keyword.flow", "foreground": "c678dd"},
        {"token": "keyword.json", "foreground": "c678dd"},

        {"token": "string", "foreground": "98c379"},
        {"token": "string.escape", "foreground": "56b6c2"},
        {"token": "string.key.json", "foreground": "e06c75"},

        {"token": "number", "foreground": "d19a66"},
        {"token": "number.hex", "foreground": "d19a66"},

        {"token": "type", "foreground": "e5c07b"},
        {"token": "type.identifier", "foreground": "e5c07b"},

        {"token": "function", "foreground": "61afef"},
        {"token": "support.function", "foreground": "61afef"},

        {"token": "variable", "foreground": "e06c75"},
        {"token": "variable.parameter", "foreground": "e06c75"},
        {"token": "variable.predefined", "foreground": "e06c75"},
        {"token": "variable.predefined.python", "foreground": "e06c75"},

        {"token": "operator", "foreground": "56b6c2"},
        {"token": "delimiter", "foreground": "abb2bf"},

        {"token": "constant", "foreground": "d19a66"},
        {"token": "constant.language", "foreground": "d19a66"},

        {"token": "tag", "foreground": "e06c75"},
        {"token": "attribute.name", "foreground": "d19a66"},
        {"token": "attribute.value", "foreground": "98c379"},

        {"token": "regexp", "foreground": "98c379"},
        {"token": "annotation", "foreground": "61afef"},

        # Токены, которые эмитят наши кастомные Monarch-грамматики из
        # `language_grammars.py`. Они работают для всех языков, у которых мы
        # подменили грамматику (Monaco применяет правила по префиксу: правило
        # без явного `tokenPostfix` ловит и `class.name.python`, и `class.name.cpp`).
        {"token": "class.name", "foreground": "e5c07b"},          # классы — жёлтый
        {"token": "function.name", "foreground": "61afef"},       # объявление функции — синий
        {"token": "function.call", "foreground": "61afef"},       # вызов функции — синий
        {"token": "function.builtin", "foreground": "56b6c2"},    # вызов встроенной — голубой
        {"token": "support.function", "foreground": "56b6c2"},    # упоминание встроенной — голубой
        {"token": "decorator", "foreground": "61afef"},           # декораторы — синий
        {"token": "variable.self", "foreground": "e06c75",
         "fontStyle": "italic"},                                  # self/cls — красный курсив
        {"token": "variable", "foreground": "e06c75"},            # переменные — красный
    ],
    "colors": {
        "editor.background": "#313338",
        "editor.foreground": "#abb2bf",

        "editor.lineHighlightBackground": "#3a3d44",
        "editor.lineHighlightBorder": "#00000000",

        "editor.selectionBackground": "#3e4451",
        "editor.selectionHighlightBackground": "#3e4451",

        "editor.findMatchBackground": "#42557b",
        "editor.findMatchHighlightBackground": "#314365",

        "editorCursor.foreground": "#528bff",
        "editorWhitespace.foreground": "#3b4048",
        "editorIndentGuide.background": "#3b4048",
        "editorIndentGuide.activeBackground": "#5c6370",

        "editorLineNumber.foreground": "#495162",
        "editorLineNumber.activeForeground": "#abb2bf",

        "editorBracketMatch.background": "#3e4451",
        "editorBracketMatch.border": "#528bff",

        "editorGutter.background": "#313338",

        "editorWidget.background": "#21252b",
        "editorWidget.border": "#3e4451",
        "editorHoverWidget.background": "#21252b",
        "editorHoverWidget.border": "#3e4451",

        "editorSuggestWidget.background": "#21252b",
        "editorSuggestWidget.border": "#3e4451",
        "editorSuggestWidget.selectedBackground": "#2c313a",

        "scrollbarSlider.background": "#4e565740",
        "scrollbarSlider.hoverBackground": "#5a626380",
        "scrollbarSlider.activeBackground": "#747d8aa0",
    },
}

ONE_DARK_PRO_THEME_NAME = "one-dark-pro-custom"
