import os
import sys
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# ── Versión del aplicativo ──────────────────────────────────────────────────
APP_VERSION = "1.1.0"


def _resolve_base_dir() -> Path:
    """Carpeta raíz del proyecto, compatible con PyInstaller."""
    env_override = os.environ.get("_AVISTA_BASE_DIR")
    if env_override:
        return Path(env_override)
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR = _resolve_base_dir()
load_dotenv(BASE_DIR / ".env")


@dataclass(frozen=True)
class MySQLConfig:
    host: str = os.getenv("MYSQL_HOST", "127.0.0.1")
    port: int = int(os.getenv("MYSQL_PORT", "3306"))
    user: str = os.getenv("MYSQL_USER", "root")
    password: str = os.getenv("MYSQL_PASSWORD", "")
    database: str = os.getenv("MYSQL_DATABASE", "print_analytics")


@dataclass(frozen=True)
class AppConfig:
    app_name: str = os.getenv("APP_NAME", "AVISTA CPAnalisis")
    upload_dir: Path = BASE_DIR / "data" / "uploads"
    report_dir: Path = BASE_DIR / "reportes"
    toner_yield_m3655idn: int = int(os.getenv("TONER_YIELD_M3655IDN", "14500"))
    maintenance_threshold: int = int(os.getenv("MAINTENANCE_THRESHOLD", "10000"))
    snmp_community: str = os.getenv("SNMP_COMMUNITY", "public")
    login_user: str = os.getenv("APP_LOGIN_USER", "avista")
    login_password: str = os.getenv("APP_LOGIN_PASSWORD", "avista123")
    admin_password: str = os.getenv("APP_ADMIN_PASSWORD", "AdminAvista2026")
    email_imap_host: str = os.getenv("EMAIL_IMAP_HOST", "imap.gmail.com")
    email_imap_port: int = int(os.getenv("EMAIL_IMAP_PORT", "993"))
    email_inbox_folder: str = os.getenv("EMAIL_INBOX_FOLDER", "datecsa")
    email_sender_filter: str = os.getenv("EMAIL_SENDER_FILTER", "")
    email_subject_filter: str = os.getenv("EMAIL_SUBJECT_FILTER", "")
    # Carpeta compartida donde se publica version.json para auto-actualizaciones
    update_folder: str = os.getenv("UPDATE_FOLDER", "")


MYSQL_CONFIG = MySQLConfig()
APP_CONFIG = AppConfig()
