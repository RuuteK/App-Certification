# pages/2_BREEAM_Wygasle_Excel.py
import os, re
import pandas as pd
from datetime import date
from dateutil import parser as dtparser
import streamlit as st

# --- geokodowanie (opcjonalne) ---
GEOCODING_AVAILABLE = True
try:
    from geopy.geocoders import Nominatim
    from geopy.extra.rate_limiter import RateLimiter
except Exception:
    GEOCODING_AVAILABLE = False

# ================== UI / NAV ==================
st.set_page_config(page_title="BREEAM wygasłe", layout="wide")

def nav_buttons(active: str = "breeam_exp"):
    c1, c2, c3, c4 = st.columns(4, gap="medium")
    with c1:
        if st.button("🏠 Home", use_container_width=True, disabled=(active == "home")):
            st.switch_page("app.py")
    with c2:
        if st.button("🏢 BREEAM aktualne", use_container_width=True, disabled=(active == "breeam_api")):
            st.switch_page("pages/1_BREEAM_API_InUse.py")
    with c3:
        if st.button("⛔ BREEAM wygasłe", use_container_width=True, disabled=(active == "breeam_exp")):
            st.switch_page("pages/2_BREEAM_Wygasle_Excel.py")
    with c4:
        if st.button("📄 LEED", use_container_width=True, disabled=(active == "leed")):
            st.switch_page("pages/3_LEED_Excel.py")

nav_buttons("breeam_exp")

st.title("⛔ BREEAM wygasłe")
#st.caption("Pokazuje tylko rekordy wygasłe na dzień dzisiejszy (months_to_expiry < 0) z pliku BREEAM.xlsx.")
st.divider()

# ================== PLIKI ==================
BREEAM_HIST_PATH = r"BREEAM.xlsx"

if not os.path.exists(BREEAM_HIST_PATH):
    st.error(f"Brak pliku: {BREEAM_HIST_PATH}")
    st.stop()

# ================== HELPERY: DATY ==================
DATE_RX = re.compile(
    r"(\d{4}[-/\.]\d{1,2}[-/\.]\d{1,2})|"
    r"(\d{1,2}[-/\.]\d{1,2}[-/\.]\d{2,4})|"
    r"(\d{4}[-/\.]\d{1,2})"
)

def parse_date_any(x):
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return None
    s = str(x).strip()
    if not s:
        return None
    try:
        return dtparser.parse(s, dayfirst=True, fuzzy=True).date()
    except Exception:
        pass
    m = DATE_RX.search(s)
    if m:
        try:
            return dtparser.parse(m.group(0), dayfirst=True).date()
        except Exception:
            return None
    return None

def months_left_signed(d):
    if d is None or pd.isna(d):
        return None
    t = date.today()
    m = (d.year - t.year) * 12 + (d.month - t.month)
    if d >= t and d.day > t.day:
        m += 1
    elif d < t and d.day < t.day:
        m -= 1
    return int(m)

def add_expiry_status(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    def status(m):
        if pd.isna(m): return "❓ Brak daty"
        m = int(m)
        if m < 0: return "⛔ Wygasły"
        if m <= 6: return "🔴 ≤ 6 mies."
        if m <= 12: return "🟠 6–12 mies."
        if m <= 18: return "🟡 12–18 mies."
        return "✅ > 18 mies."
    df["expiry_status"] = df.get("months_to_expiry", pd.Series([None]*len(df))).apply(status)
    return df

def color_rows_by_expiry(row):
    m = row.get("months_to_expiry", None)
    if pd.isna(m):
        return [""] * len(row)
    m = int(m)
    if m < 0: color = "#ffcccc"
    elif m <= 6: color = "#ffe0cc"
    elif m <= 12: color = "#fff2cc"
    elif m <= 18: color = "#fff7cc"
    else: color = "#e6ffea"
    return [f"background-color: {color}"] * len(row)

# ================== NORMALIZACJA EXCEL ==================
def normalize_breeam_from_excel(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    rename_excel = {
        "Nazwa budynku": "asset_name",
        "Rodzaj budynku": "projectType",
        "System": "system",
        "Standard": "standard",
        "Scheme": "scheme",
        "Rating": "rating",
        "Status/Data ważności": "stage",
        "Województwo": "region",
        "Miasto": "city",
        "Adres": "regAddresLine1",
        "Audytor/Assesor": "assessor",
        "Assessor/Auditor": "assessor",
        "Assessor": "assessor",
        "Kraj": "country",
        "Country": "country",
        # czasem:
        "Kod pocztowy": "postcode",
        "Postcode": "postcode",
        "Zipcode": "postcode",
    }
    for src, dst in rename_excel.items():
        if src in df.columns:
            df.rename(columns={src: dst}, inplace=True)
    if "system" not in df.columns:
        df["system"] = "BREEAM"
    return df

def _clean_token(x):
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return ""
    s = str(x).strip()
    if s.lower() in ("nan", "none", "null"):
        return ""
    return s

def build_address_variants(row: pd.Series) -> list[str]:
    """
    Zwraca listę coraz prostszych wariantów adresu (fallbacki),
    żeby geokoder miał większą szansę znaleźć wynik.
    """
    street = _clean_token(row.get("regAddresLine1"))
    city = _clean_token(row.get("city"))
    region = _clean_token(row.get("region"))
    postcode = _clean_token(row.get("postcode"))
    country = _clean_token(row.get("country")) or "Poland"

    # Usuwanie prefiksów typu "ul." -> czasem pomaga
    street_no_prefix = re.sub(r"^\s*(ul\.|al\.|pl\.|os\.)\s*", "", street, flags=re.I).strip()

    # podstawowe warianty
    v = []
    if street and city:
        v.append(f"{street}, {city}, {country}")
    if street_no_prefix and city:
        v.append(f"{street_no_prefix}, {city}, {country}")
    if street and postcode and city:
        v.append(f"{street}, {postcode} {city}, {country}")
    if street_no_prefix and postcode and city:
        v.append(f"{street_no_prefix}, {postcode} {city}, {country}")
    if city and region:
        v.append(f"{city}, {region}, {country}")
    if city:
        v.append(f"{city}, {country}")
    if region:
        v.append(f"{region}, {country}")

    # unikalne
    out = []
    seen = set()
    for a in v:
        a2 = a.strip()
        if a2 and a2 not in seen:
            seen.add(a2)
            out.append(a2)
    return out

# ================== GEOKODOWANIE (tylko wybrany rekord) ==================
@st.cache_resource
def get_geocoder(provider: str):
    if not GEOCODING_AVAILABLE:
        return None
    if provider == "nominatim":
        geolocator = Nominatim(user_agent="breeam_expired_excel_app")
        return RateLimiter(geolocator.geocode, min_delay_seconds=1)
    # miejsce na przyszłe providery, ale na razie używamy tylko Nominatim
    geolocator = Nominatim(user_agent="breeam_expired_excel_app")
    return RateLimiter(geolocator.geocode, min_delay_seconds=1)

@st.cache_data(show_spinner=False, ttl=60*60*24)
def geocode_variants_cached(address_variants: tuple, provider: str):
    """
    Cache per (warianty adresu, provider).
    Zwraca (lat, lon, matched_address) lub (None, None, None)
    """
    if not GEOCODING_AVAILABLE:
        return None, None, None
    geocode = get_geocoder(provider)
    if geocode is None:
        return None, None, None

    for addr in address_variants:
        try:
            loc = geocode(addr)
        except Exception:
            loc = None
        if loc:
            return float(loc.latitude), float(loc.longitude), addr

    return None, None, None

# ================== LOAD & PREP ==================
df_raw = pd.read_excel(BREEAM_HIST_PATH, engine="openpyxl")
df = normalize_breeam_from_excel(df_raw)

# expiry zawsze od 'stage'
if "stage" in df.columns:
    parsed = df["stage"].map(parse_date_any)
    df["expiry_date"] = pd.to_datetime(parsed, errors="coerce").dt.date
else:
    df["expiry_date"] = None

df["months_to_expiry"] = df["expiry_date"].map(months_left_signed)
df = add_expiry_status(df)

expired = df[df["months_to_expiry"].notna() & (df["months_to_expiry"] < 0)].copy()
st.success(f"Wygasłe rekordy (na dziś): {len(expired):,}")

# ================== TABELA ==================
show_cols = ["asset_name","projectType","standard","scheme","expiry_date","months_to_expiry","expiry_status","assessor"]
for c in show_cols:
    if c not in expired.columns:
        expired[c] = None
expired_view = expired[show_cols].copy()
st.dataframe(expired_view.style.apply(color_rows_by_expiry, axis=1), use_container_width=True)

# ================== SZCZEGÓŁY + MAPA ==================
st.markdown("## Szczegóły wybranego certyfikatu")

if expired.empty:
    st.info("Brak wygasłych rekordów.")
    st.stop()

name_col = "asset_name" if "asset_name" in expired.columns else None
if not name_col:
    st.error("Brak kolumny z nazwą (asset_name).")
    st.stop()

name_options = expired[name_col].astype(str).fillna("(brak nazwy)").tolist()
sel_name = st.selectbox("Wybierz projekt", name_options, index=0, key="exp_proj_sel")
row = expired[expired[name_col].astype(str) == sel_name].head(1).iloc[0]

col_info, col_map = st.columns([3, 5], gap="large")

with col_info:
    st.write("**Nazwa budynku:**", row.get("asset_name", "–"))
    st.write("**Typ projektu:**", row.get("projectType", "–"))
    st.write("**Standard:**", row.get("standard", "–"))
    st.write("**Scheme:**", row.get("scheme", "–"))
    st.write("**Assessor/Auditor:**", row.get("assessor", "–"))
    st.write("**Data ważności:**", row.get("expiry_date", "–"))
    st.write("**Miesiące do końca:**", row.get("months_to_expiry", "–"))
    st.write("**Status ważności:**", row.get("expiry_status", "–"))

    street = _clean_token(row.get("regAddresLine1"))
    city = _clean_token(row.get("city"))
    region = _clean_token(row.get("region"))
    country = _clean_token(row.get("country")) or "Poland"

    # pełny adres do wyświetlenia
    full_addr = ", ".join([x for x in [street, city, region, country] if x])
    st.write("**Adres:**", full_addr if full_addr else "–")

with col_map:
    st.write("**Mapa lokalizacji**")

    if not GEOCODING_AVAILABLE:
        st.info("Geokodowanie niedostępne — zainstaluj `geopy`, aby włączyć mapę z adresu.")
        st.stop()

    # --- domyślny adres z rekordu (ulica tylko do pierwszego przecinka) ---
    street_raw = _clean_token(row.get("regAddresLine1"))
    # jeśli w ulicy są dodatkowe części po przecinku (np. "146 A, B, C"), bierzemy tylko pierwszą część
    street_main = street_raw.split(",")[0].strip() if street_raw else ""

    city = _clean_token(row.get("city"))
    region = _clean_token(row.get("region"))
    country = _clean_token(row.get("country")) or "Poland"

    default_addr = ", ".join([x for x in [street_main, city, region, country] if x])

    # --- KLUCZ: zaktualizuj text_input gdy zmienił się projekt ---
    # (streamlit nie nadpisuje wartości inputa, jeśli istnieje session_state pod tym samym key)
    sel_key = f"geo_addr_for_{sel_name}"  # unikalnie per wybrany projekt
    if sel_key not in st.session_state:
        st.session_state[sel_key] = default_addr

    manual_addr = st.text_input(
        "Adres do geokodowania (możesz poprawić ręcznie)",
        value=st.session_state[sel_key],
        key=sel_key,
        help="Jeśli geokoder nie znajduje wyniku, skróć adres (np. bez 'Al.'/'ul.') albo usuń województwo.",
    )

    # --- warianty do geokodowania ---
    variants = []
    if manual_addr and manual_addr.strip():
        variants.append(manual_addr.strip())
    variants.extend(build_address_variants(row))

    # unikalne warianty
    uniq = []
    seen = set()
    for a in variants:
        a2 = a.strip()
        if a2 and a2 not in seen:
            seen.add(a2)
            uniq.append(a2)

    provider = "nominatim"

    if st.button("📍 Ustal lokalizację", type="primary", use_container_width=True, key=f"geo_btn_{sel_name}"):
        with st.spinner("Geokoduję adres…"):
            lat, lon, matched = geocode_variants_cached(tuple(uniq), provider)

        if lat is not None and lon is not None:
            st.success(f"Znaleziono lokalizację dla: {matched}")
            st.map(pd.DataFrame({"lat": [lat], "lon": [lon]}))
        else:
            st.warning("Nie udało się ustalić lokalizacji (geokoder nie zwrócił wyniku).")
            st.caption("Spróbuj uprościć adres, usunąć województwo albo dopisać kod pocztowy.")
            with st.expander("Pokaż użyte warianty adresu"):
                for a in uniq[:15]:
                    st.write(a)




