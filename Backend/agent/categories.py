"""Shared allowlist; no window titles or paths are accepted as categories."""
CATEGORIES = frozenset({"development", "terminal", "browser", "productivity",
    "communication", "entertainment", "design", "system", "unknown"})

_GROUPS = {
    "development": "code code-insiders vscode visual studio code devenv visual studio pycharm pycharm64 idea idea64 clion clion64 eclipse neovim nvim".split(),
    "terminal": ["powershell", "pwsh", "cmd", "windowsterminal", "terminal", "iterm2", "alacritty", "kitty", "gnome-terminal-server", "konsole"],
    "browser": ["chrome", "google chrome", "google-chrome", "chromium", "firefox", "msedge", "microsoft edge", "safari", "brave", "brave-browser"],
    "productivity": ["winword", "excel", "powerpnt", "notepad", "notepad++", "microsoft word", "microsoft excel", "libreoffice", "soffice"],
    "communication": ["discord", "slack", "teams", "ms-teams", "microsoft teams", "zoom"],
    "entertainment": ["spotify", "vlc", "netflix", "steam"],
    "design": ["blender", "figma", "photoshop", "adobe photoshop", "gimp"],
    "system": ["explorer", "finder", "systemsettings", "system settings", "nautilus", "dolphin"],
}
_GROUPS["development"] = ["code", "code-insiders", "vscode", "visual studio code", "devenv", "visual studio", "pycharm", "pycharm64", "idea", "idea64", "clion", "clion64", "eclipse", "neovim", "nvim"]
_APP_MAP = {app: category for category, apps in _GROUPS.items() for app in apps}

def normalize_category(value):
    if isinstance(value, str):
        value = value.strip().lower()
        if value in CATEGORIES:
            return value
    return "unknown"

def categorize_application(identity):
    if not isinstance(identity, str):
        return "unknown"
    name = identity.replace("\\", "/").rsplit("/", 1)[-1].strip().lower()
    if name.endswith(".exe"):
        name = name[:-4]
    return _APP_MAP.get(name, "unknown")
