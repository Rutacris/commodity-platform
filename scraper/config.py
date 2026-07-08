import os

# ─── Database ────────────────────────────────────────────────────────────────
DB_HOST     = os.getenv("DB_HOST",     "postgres")
DB_PORT     = os.getenv("DB_PORT",     "5432")
DB_NAME     = os.getenv("DB_NAME",     "commodities")
DB_USER     = os.getenv("DB_USER",     "admin")
DB_PASSWORD = os.getenv("DB_PASSWORD", "strongpassword")

DATABASE_URL = (
    f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
)

# ─── Ollama ───────────────────────────────────────────────────────────────────
OLLAMA_HOST  = os.getenv("OLLAMA_HOST",  "http://host.docker.internal:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "mistral:7b-instruct")

# ─── Scrapers ─────────────────────────────────────────────────────────────────

# WFP VAM — Humanitarian Data Exchange public CSV
# Rwanda ADM0 code = 654 in HDX / WFP system
WFP_HDX_URL = (
    "https://data.humdata.org/dataset/"
    "wfp-food-prices-for-rwanda/resource/"
    "download/wfp_food_prices_rwa.csv"
)
WFP_API_URL = (
    "https://api.vam.wfp.org/marketPrices/foodPrices"
    "?adm0Code=654&page=1&pageSize=500"
)

# NISR — National Institute of Statistics Rwanda
NISR_BASE_URL   = "https://www.statistics.gov.rw"
NISR_CPI_URL    = f"{NISR_BASE_URL}/statistical-publications/consumer-price-index"

# MINAGRI / RAB
RAB_BASE_URL    = "https://www.rab.gov.rw"
RAB_PRICES_URL  = f"{RAB_BASE_URL}/market-prices"

# FEWS NET
FEWS_BASE_URL   = "https://fews.net"
FEWS_RWANDA_URL = f"{FEWS_BASE_URL}/east-africa/rwanda"

# ─── Target commodities (normalised names) ────────────────────────────────────
TARGET_COMMODITIES = {"maize", "beans", "rice", "cooking oil", "sugar"}

# Alias map — raw source names → canonical names
COMMODITY_ALIASES = {
    # maize
    "maize":          "maize",
    "corn":           "maize",
    "maize grain":    "maize",
    "maize flour":    "maize",
    # beans
    "beans":          "beans",
    "kidney beans":   "beans",
    "bean":           "beans",
    # rice
    "rice":           "rice",
    "rice (imported)":"rice",
    "rice local":     "rice",
    # cooking oil
    "cooking oil":    "cooking oil",
    "vegetable oil":  "cooking oil",
    "palm oil":       "cooking oil",
    "oil":            "cooking oil",
    # sugar
    "sugar":          "sugar",
    "sugar (imported)":"sugar",
    "white sugar":    "sugar",
}

# ─── Request settings ─────────────────────────────────────────────────────────
REQUEST_TIMEOUT = 30   # seconds
REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; RwandaCommodityBot/1.0; "
        "+https://github.com/yourorg/commodity-platform)"
    )
}
