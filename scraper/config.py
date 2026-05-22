from pathlib import Path

BASE_URL = "https://www.berlin.de"
LISTING_URL = f"{BASE_URL}/polizei/polizeimeldungen/"
ARCHIV_URL = f"{BASE_URL}/polizei/polizeimeldungen/archiv/"
ARCHIV_START_YEAR = 2014

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
DB_PATH = DATA_DIR / "meldungen.db"

USER_AGENT = (
    "PolizeiMeldungenArchiv/1.0 (+local research; respectful scrape; contact via project owner)"
)
REQUEST_DELAY_SEC = 0.35
REQUEST_TIMEOUT_SEC = 30
