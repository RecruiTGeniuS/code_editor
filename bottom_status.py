"""
Тексты и подписи для нижней панели (BottomBar): путь, строка/столбец, язык.
"""

from __future__ import annotations

# Когда нет текстового редактора или вкладок — как в шаблоне main.ui.
LINE_COL_PLACEHOLDER = "Лин. —, Столб. —"


# Человекочитаемые подписи для идентификаторов языков Monaco / TextMate id.
# Совпадают с ключами EXTENSION_TO_LANGUAGE в tab_manager и с `set_language`.
LANGUAGE_LABEL_RU: dict[str, str] = {
    "python": "Python",
    "javascript": "JavaScript",
    "typescript": "TypeScript",
    "cpp": "C++",
    "c": "C",
    "json": "JSON",
    "html": "HTML",
    "css": "CSS",
    "scss": "SCSS",
    "less": "Less",
    "markdown": "Markdown",
    "yaml": "YAML",
    "xml": "XML",
    "sql": "SQL",
    "shell": "Shell",
    "powershell": "PowerShell",
    "bat": "Batch",
    "rust": "Rust",
    "go": "Go",
    "ruby": "Ruby",
    "java": "Java",
    "kotlin": "Kotlin",
    "swift": "Swift",
    "php": "PHP",
    "lua": "Lua",
    "r": "R",
    "dart": "Dart",
    "ini": "INI",
    "dockerfile": "Dockerfile",
    "plaintext": "Текст",
}


def language_label_for_monaco_id(language_id: str | None) -> str:
    """Короткая подпись языка для languageLabel (пустая строка если неизвестно)."""
    if not language_id:
        return ""
    lid = language_id.strip().lower()
    if lid in LANGUAGE_LABEL_RU:
        return LANGUAGE_LABEL_RU[lid]
    # На случай редких id — аккуратный Title Case.
    return language_id.replace("_", " ").title()
