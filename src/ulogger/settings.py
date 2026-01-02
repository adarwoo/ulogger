"""Settings and application data storage using platformdirs."""
import json
from pathlib import Path
from typing import List
from platformdirs import user_data_dir


class Settings:
    """Manage application settings and recent files."""

    def __init__(self):
        """Initialize settings manager."""
        self.app_name = "ulogger"
        self.app_author = "adarwoo"
        self.data_dir = Path(user_data_dir(self.app_name, self.app_author))
        self.settings_file = self.data_dir / "settings.json"
        self.max_recent_files = 10

        # Ensure data directory exists
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # Load settings
        self._settings = self._load_settings()

    def _load_settings(self) -> dict:
        """Load settings from file."""
        if self.settings_file.exists():
            try:
                with open(self.settings_file, 'r') as f:
                    return json.load(f)
            except Exception as e:
                print(f"Warning: Could not load settings: {e}")
                return self._default_settings()
        return self._default_settings()

    def _default_settings(self) -> dict:
        """Return default settings."""
        return {
            "recent_elf_files": [],
            "last_com_port": None
        }

    def _save_settings(self) -> None:
        """Save settings to file."""
        try:
            with open(self.settings_file, 'w') as f:
                json.dump(self._settings, f, indent=2)
        except Exception as e:
            print(f"Warning: Could not save settings: {e}")

    def get_recent_files(self) -> List[str]:
        """Get list of recent ELF files."""
        # Filter out files that no longer exist
        recent = self._settings.get("recent_elf_files", [])
        existing = [f for f in recent if Path(f).exists()]

        # Update if list changed
        if len(existing) != len(recent):
            self._settings["recent_elf_files"] = existing
            self._save_settings()

        return existing

    def add_recent_file(self, filepath: str) -> None:
        """Add a file to the recent files list."""
        filepath = str(Path(filepath).resolve())
        recent = self._settings.get("recent_elf_files", [])

        # Remove if already exists (to move to front)
        if filepath in recent:
            recent.remove(filepath)

        # Add to front
        recent.insert(0, filepath)

        # Trim to max size
        recent = recent[:self.max_recent_files]

        self._settings["recent_elf_files"] = recent
        self._save_settings()

    def get_com_port(self) -> str:
        """Get the last used COM port."""
        return self._settings.get("last_com_port", None)

    def set_com_port(self, port: str) -> None:
        """Set the last used COM port."""
        self._settings["last_com_port"] = port
        self._save_settings()

    @staticmethod
    def list_comports():
        """List all sorted COM ports."""
        import serial.tools.list_ports
        return sorted([p.device for p in serial.tools.list_ports.comports()],
                      key=lambda x: int(''.join(filter(str.isdigit, x)) or 0))


# Global settings instance
_settings = None


def get_settings() -> Settings:
    """Get the global settings instance."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
