"""
Расширенные Monarch-грамматики для подсветки разных ЯП.

Зачем нужно: встроенные Monarch-грамматики Monaco для большинства языков выдают
очень мало типов токенов (для Python — фактически только keyword / string /
number / comment / identifier). Из-за этого имена переменных, функций и классов
все попадают в `identifier` и получают одинаковый «дефолтный» цвет, поэтому
никакая тема One Dark Pro не сможет их раскрасить отдельно.

Решение: подменяем грамматику через `monaco.languages.setMonarchTokensProvider`
на более «умную», которая выделяет:

- `class.name`     — имя класса в `class Foo:`
- `function.name`  — имя функции/метода в `def foo(...)`
- `function.call`  — вызов функции (имя + `(`)
- `function.builtin` — вызов встроенной функции (`print(...)`)
- `support.function` — упоминание встроенной функции/типа без вызова (`int`, `str`)
- `decorator`      — декораторы (`@functools.lru_cache`)
- `variable.self`  — `self` / `cls`
- `variable`       — все остальные идентификаторы
- `constant.language` — `True`, `False`, `None`

Цвета для всех этих токенов прописаны в `editor_theme.py`.

Формат словарей соответствует параметру `IMonarchLanguage`:
https://microsoft.github.io/monaco-editor/api/interfaces/monaco.languages.IMonarchLanguage.html
JSON-сериализуется без проблем, потому что мы не используем функции — только
строки регулярок и токенов.

Чтобы добавить язык, опишите грамматику и положите в `LANGUAGE_GRAMMARS`.
"""


PYTHON_GRAMMAR = {
    "defaultToken": "",
    "tokenPostfix": ".python",
    "keywords": [
        "False", "None", "True", "and", "as", "assert", "async", "await",
        "break", "class", "continue", "def", "del", "elif", "else", "except",
        "finally", "for", "from", "global", "if", "import", "in", "is",
        "lambda", "nonlocal", "not", "or", "pass", "raise", "return", "try",
        "while", "with", "yield", "match", "case",
    ],
    "builtins": [
        "abs", "all", "any", "ascii", "bin", "bool", "bytearray", "bytes",
        "callable", "chr", "classmethod", "compile", "complex", "delattr",
        "dict", "dir", "divmod", "enumerate", "eval", "exec", "filter",
        "float", "format", "frozenset", "getattr", "globals", "hasattr",
        "hash", "help", "hex", "id", "input", "int", "isinstance",
        "issubclass", "iter", "len", "list", "locals", "map", "max",
        "memoryview", "min", "next", "object", "oct", "open", "ord", "pow",
        "print", "property", "range", "repr", "reversed", "round", "set",
        "setattr", "slice", "sorted", "staticmethod", "str", "sum", "super",
        "tuple", "type", "vars", "zip", "__import__",
    ],
    "brackets": [
        {"open": "{", "close": "}", "token": "delimiter.curly"},
        {"open": "[", "close": "]", "token": "delimiter.square"},
        {"open": "(", "close": ")", "token": "delimiter.parenthesis"},
    ],
    "tokenizer": {
        "root": [
            {"include": "@whitespace"},
            {"include": "@numbers"},
            {"include": "@strings"},

            # Объявления `class Foo` / `def foo`
            [r"(class)(\s+)([a-zA-Z_]\w*)",
             ["keyword", "white", "class.name"]],
            [r"(def)(\s+)([a-zA-Z_]\w*)",
             ["keyword", "white", "function.name"]],

            # Декораторы: @functools.lru_cache, @app.route, …
            [r"@[a-zA-Z_]\w*(?:\.[a-zA-Z_]\w*)*", "decorator"],

            # Языковые константы (порядок важен — они есть в keywords, поэтому
            # ловим их явно ДО общего правила идентификаторов).
            [r"\b(True|False|None|NotImplemented|Ellipsis)\b",
             "constant.language"],

            # self / cls — конвенциональный первый аргумент метода
            [r"\b(self|cls)\b", "variable.self"],

            # Вызовы функций: имя, за которым (с пробелами или без) идёт `(`
            [r"[a-zA-Z_]\w*(?=\s*\()", {
                "cases": {
                    "@keywords": "keyword",
                    "@builtins": "function.builtin",
                    "@default": "function.call",
                },
            }],

            # Остальные идентификаторы
            [r"[a-zA-Z_]\w*", {
                "cases": {
                    "@keywords": "keyword",
                    "@builtins": "support.function",
                    "@default": "variable",
                },
            }],

            [r"[{}\[\]()]", "@brackets"],
            [r"[<>]=?|[!=]=?|//?=?|\*\*?=?|[+\-*/%&|^~]=?", "operator"],
            [r"[;,.:]", "delimiter"],
        ],

        "whitespace": [
            [r"\s+", "white"],
            [r"#.*$", "comment"],
        ],

        "numbers": [
            [r"-?0[xX][0-9a-fA-F_]+[lL]?", "number.hex"],
            [r"-?(\d[\d_]*\.)?\d[\d_]*([eE][+-]?\d+)?[jJ]?[lL]?", "number"],
        ],

        "strings": [
            # Тройные строки (с возможным префиксом b/f/r/u)
            [r'[bBfFrRuU]*"""', "string", "@dblTriple"],
            [r"[bBfFrRuU]*'''", "string", "@sglTriple"],
            # Одинарные/двойные строки с префиксами
            [r'[bBfFrRuU]*"', "string", "@dblString"],
            [r"[bBfFrRuU]*'", "string", "@sglString"],
        ],
        "dblString": [
            [r'[^\\"]+', "string"],
            [r"\\.", "string.escape"],
            [r'"', "string", "@pop"],
        ],
        "sglString": [
            [r"[^\\']+", "string"],
            [r"\\.", "string.escape"],
            [r"'", "string", "@pop"],
        ],
        "dblTriple": [
            [r'[^"]+', "string"],
            [r'"""', "string", "@pop"],
            [r'"', "string"],
        ],
        "sglTriple": [
            [r"[^']+", "string"],
            [r"'''", "string", "@pop"],
            [r"'", "string"],
        ],
    },
}


# Подключаем грамматики, которыми хотим переопределить встроенные Monaco-провайдеры.
# Чтобы добавить ещё один язык — опишите его грамматику по образцу выше и допишите
# сюда: ключ — id языка Monaco (как в `editor.set_language(...)`).
LANGUAGE_GRAMMARS = {
    "python": PYTHON_GRAMMAR,
}
