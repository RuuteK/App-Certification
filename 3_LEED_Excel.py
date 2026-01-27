# pages/3_LEED_Excel.py
import os
import re
import pandas as pd
from datetime import date
from dateutil import parser as dtparser
from dateutil.relativedelta import relativedelta
import streamlit as st

# geokodowanie – wymaga: pip install geopy
try:
    from geopy.geocoders import Nominatim
    from geopy.extra.rate_limiter import RateLimiter
    GEOCODING_AVAILABLE = True
except ImportError:
    GEOCODING_AVAILABLE = False


# ================== NAV BUTTONS ==================
def nav_buttons(active: str = "leed"):
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


# ================== KONFIG ==================
LEED_PATH = r"PublicLEEDProjectDirectory.xlsx"


# ================== PAGE ==================
st.set_page_config(page_title="LEED", layout="wide")
nav_buttons("leed")
st.divider()

st.title("📄 LEED")
#st.caption("Przegląd certyfikacji LEED z Excela + filtry + szczegóły + mapa (geokodowanie tylko wybranego projektu).")


# ================== HELPERY ==================
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
        return dtparser.parse(s, dayfirst=False, fuzzy=True).date()
    except Exception:
        pass
    m = DATE_RX.search(s)
    if m:
        try:
            return dtparser.parse(m.group(0), dayfirst=False).date()
        except Exception:
            return None
    return None


def months_left_signed(d):
    """ >0 – ważny, 0 – wygasa w bieżącym miesiącu, <0 – wygasły """
    if d is None or pd.isna(d):
        return None
    t = date.today()
    m = (d.year - t.year) * 12 + (d.month - t.month)
    if d >= t and d.day > t.day:
        m += 1
    elif d < t and d.day < t.day:
        m -= 1
    return int(m)


def add_expiry_status_leed(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    def status(m):
        if pd.isna(m):
            return "❓ Brak daty"
        m = int(m)
        if m < 0:
            return "⛔ Wygasły"
        if m <= 6:
            return "🔴 ≤ 6 mies."
        if m <= 12:
            return "🟠 6–12 mies."
        if m <= 18:
            return "🟡 12–18 mies."
        return "✅ > 18 mies."

    df["expiry_status"] = df.get("months_to_expiry", pd.Series([None] * len(df))).apply(status)
    return df


def color_rows_by_expiry(row):
    m = row.get("months_to_expiry", None)
    if pd.isna(m):
        return [""] * len(row)
    m = int(m)
    if m < 0:
        color = "#ffcccc"
    elif m <= 6:
        color = "#ffe0cc"
    elif m <= 12:
        color = "#fff2cc"
    elif m <= 18:
        color = "#fff7cc"
    else:
        color = "#e6ffea"
    return [f"background-color: {color}"] * len(row)


def first_nonempty(row: pd.Series, candidates, default="–"):
    for c in candidates:
        if c in row.index:
            val = row.get(c)
            if pd.notna(val) and str(val).strip().lower() not in ("", "nan"):
                return val
    return default


def years_for_version(version: str | None) -> int:
    """
    LEEDSystemVersion:
    - v2009 => 5 lat
    - v4, v4.1, v4.1.1, itd => 3 lata
    - fallback => 3 lata
    """
    if not version:
        return 3
    v = str(version).strip().lower()
    if v == "v2009":
        return 5
    if v.startswith("v"):
        return 3
    return 3


# ================== GEOKODOWANIE (tylko wybrany rekord) ==================
@st.cache_resource
def get_geocoder():
    if not GEOCODING_AVAILABLE:
        return None
    geolocator = Nominatim(user_agent="leed_app")
    # limiter: bezpieczniej dla Nominatim
    return RateLimiter(geolocator.geocode, min_delay_seconds=1)


def build_address_for_geocoding(row: pd.Series) -> str:
    street = first_nonempty(row, ["Street", "Address", "Address1", "Street Address"], default="")
    city = first_nonempty(row, ["City", "city"], default="")
    region = first_nonempty(row, ["State/Province", "State", "region"], default="")
    zipcode = first_nonempty(row, ["Zipcode", "ZIP", "PostalCode", "Postal Code"], default="")
    country = first_nonempty(row, ["Country", "country"], default="")

    parts = []
    if street: parts.append(str(street).strip())
    if zipcode: parts.append(str(zipcode).strip())
    if city: parts.append(str(city).strip())
    if region: parts.append(str(region).strip())
    if country: parts.append(str(country).strip())

    return ", ".join([p for p in parts if p and p.lower() != "nan"])


@st.cache_data(show_spinner=False, ttl=60 * 60 * 24)
def geocode_address_cached(query: str):
    """Cache po adresie, żeby nie odpalać geokodera wielokrotnie dla tego samego."""
    if not GEOCODING_AVAILABLE:
        return None, None
    geocode = get_geocoder()
    if geocode is None:
        return None, None
    try:
        loc = geocode(query)
    except Exception:
        loc = None
    if not loc:
        return None, None
    return float(loc.latitude), float(loc.longitude)


# ================== LOAD ==================
if not os.path.exists(LEED_PATH):
    st.error(f"Plik LEED nie istnieje pod ścieżką:\n\n{LEED_PATH}")
    st.stop()

@st.cache_data(show_spinner=False)
def load_leed_df(path: str) -> pd.DataFrame:
    return pd.read_excel(path, engine="openpyxl")

df_raw = load_leed_df(LEED_PATH)
st.success(f"Wczytano {len(df_raw):,} wierszy z pliku: {LEED_PATH}")


# ================== NORMALIZACJA ==================
df = df_raw.copy()

rename_map = {
    "Project Name": "asset_name",
    "ProjectName": "asset_name",
    "Name": "asset_name",
    "Country": "country",
    "City": "city",
    "State/Province": "region",
    "State": "region",
    "LEEDSystemVersion": "LEEDSystemVersion",
    "LEED System Version": "LEEDSystemVersion",
    "LEED Rating System": "rating_system",
    "Rating System": "rating_system",
    "LEED Certification Level": "level",
    "Certification Level": "level",
    "Project ID": "project_id",
    "ID": "project_id",
    "URL": "publicUrl",
    "Certification Date": "certification_date",
    "CertDate": "certification_date",
    "Award Date": "certification_date",
    "Street": "Street",
    "Zipcode": "Zipcode",
}
for src, dst in rename_map.items():
    if src in df.columns and dst not in df.columns:
        df[dst] = df[src]


# ================== DATY: expiry zależnie od wersji ==================
if "certification_date" in df.columns:
    df["certification_date"] = pd.to_datetime(df["certification_date"].map(parse_date_any), errors="coerce").dt.date
else:
    df["certification_date"] = None

def calc_expiry(row):
    d = row.get("certification_date", None)
    if d is None or pd.isna(d):
        return None
    years = years_for_version(row.get("LEEDSystemVersion", None))
    return d + relativedelta(years=years)

df["expiry_date"] = df.apply(calc_expiry, axis=1)
df["months_to_expiry"] = df["expiry_date"].map(months_left_signed)
df = add_expiry_status_leed(df)


# ================== FILTRY ==================
countries = sorted(df["country"].dropna().unique().tolist()) if "country" in df.columns else []
opts_c = ["(dowolne)"] + countries
idx_pl = opts_c.index("Poland") if "Poland" in opts_c else 0
sel_country = st.selectbox("Państwo", opts_c, index=idx_pl, key="l_country")

mask = pd.Series([True] * len(df))
if "country" in df.columns and sel_country != "(dowolne)":
    mask &= (df["country"] == sel_country)
df_f = df[mask].copy()

versions = sorted(df_f["LEEDSystemVersion"].dropna().astype(str).unique().tolist()) if "LEEDSystemVersion" in df_f.columns else []
opts_v = ["(dowolna)"] + versions
sel_version = st.selectbox("LEEDSystemVersion", opts_v, index=0, key="l_version")
if "LEEDSystemVersion" in df_f.columns and sel_version != "(dowolna)":
    df_f = df_f[df_f["LEEDSystemVersion"].astype(str) == sel_version].copy()


# ================== METRYKI ==================
st.markdown("### Podsumowanie")

m = pd.to_numeric(df_f.get("months_to_expiry", pd.Series([None] * len(df_f))), errors="coerce")

total = int(len(df_f))
expired = int((m < 0).sum())
urgent_0_6 = int(m.between(0, 6, inclusive="both").sum())
urgent_6_12 = int(m.between(7, 12, inclusive="both").sum())
mid_12_18 = int(m.between(12, 18, inclusive="both").sum())
ok_18 = int((m > 18).sum())

c1, c2, c3, c4, c5, c6 = st.columns(6)
c1.metric("Liczba certyfikacji", total)
c2.metric("⛔ Wygasłe", expired)
c3.metric("🔴 ≤ 6 mies.", urgent_0_6)
c4.metric("🟠 6–12 mies.", urgent_6_12)
c5.metric("🟡 12–18 mies.", mid_12_18)
c6.metric("✅ > 18 mies.", ok_18)


# ================== RADIO (bez suwaka i bez checkboxa NA) ==================
view = st.radio(
    "Zakres widocznych certyfikacji",
    [
        "Wszystkie",
        "Tylko wygasłe",
        "≤ 6 mies.",
        "6–12 mies.",
        "12–18 mies.",
        "> 18 mies.",
    ],
    horizontal=True,
    key="l_view",
)

if df_f.empty:
    st.info("Brak wyników dla wybranych filtrów.")
    st.stop()

m_all = pd.to_numeric(df_f["months_to_expiry"], errors="coerce")

if view == "Tylko wygasłe":
    df_show = df_f[m_all < 0].copy()
elif view == "≤ 6 mies.":
    df_show = df_f[m_all.between(0, 6, inclusive="both")].copy()
elif view == "6–12 mies.":
    df_show = df_f[m_all.between(7, 12, inclusive="both")].copy()
elif view == "12–18 mies.":
    df_show = df_f[m_all.between(12, 18, inclusive="both")].copy()
elif view == "> 18 mies.":
    df_show = df_f[m_all > 18].copy()
else:
    df_show = df_f.copy()


# ================== TABELA ==================
st.divider()
st.markdown("### Tabela (LEED)")

preferred = [
    "asset_name",
    "Street",
    "city",
    "Zipcode",
    "country",
    "LEEDSystemVersion",
    "level",
    "certification_date",
    "expiry_date",
    "months_to_expiry",
    "expiry_status",
]
cols = [c for c in preferred if c in df_show.columns] + [c for c in df_show.columns if c not in preferred]
df_view = df_show[cols].copy()

st.dataframe(df_view.style.apply(color_rows_by_expiry, axis=1), use_container_width=True)

# ================== SZCZEGÓŁY + MAPA ==================
st.divider()
st.markdown("## Szczegóły wybranego certyfikatu")

if df_show.empty:
    st.info("Brak wyników po zastosowaniu filtrów.")
    st.stop()

name_col = "asset_name" if "asset_name" in df_show.columns else df_show.columns[0]
name_options = df_show[name_col].astype(str).fillna("(brak nazwy)").tolist()
sel_name = st.selectbox("Wybierz projekt", name_options, index=0, key="l_proj_sel")

row = df_show[df_show[name_col].astype(str) == sel_name].head(1).iloc[0]

col_info, col_map = st.columns([3, 5], gap="large")

default_addr = build_address_for_geocoding(row)

with col_info:
    st.write("**Nazwa budynku:**", row.get("asset_name", "–"))
    st.write("**LEEDSystemVersion:**", row.get("LEEDSystemVersion", "–"))
    st.write("**Poziom (CertLevel):**", row.get("level", row.get("CertLevel", "–")))
    st.write("**Data certyfikacji:**", row.get("certification_date", "–"))
    st.write("**Data wygaśnięcia:**", row.get("expiry_date", "–"))
    st.write("**Miesiące do końca:**", row.get("months_to_expiry", "–"))
    st.write("**Status ważności:**", row.get("expiry_status", "❓ Brak daty"))
    st.write("**Adres:**", default_addr if default_addr else "–")

    url = row.get("publicUrl", None)
    if url:
        st.markdown(f"[Otwórz kartę projektu]({url})")

with col_map:
    st.markdown("**Mapa lokalizacji**")

    if not GEOCODING_AVAILABLE:
        st.info("Geokodowanie niedostępne (zainstaluj pakiet `geopy`).")
    else:
        # 1) automatyczne geokodowanie na podstawie wybranego projektu (jak w BREEAM aktualne)
        #    - bez przycisku
        #    - tylko jeśli adres się zmienił
        project_key = str(row.get("project_id", "")) + "|" + str(row.get("asset_name", ""))

        if "leed_last_project_key" not in st.session_state:
            st.session_state.leed_last_project_key = None
        if "leed_last_addr" not in st.session_state:
            st.session_state.leed_last_addr = None
        if "leed_last_lat" not in st.session_state:
            st.session_state.leed_last_lat = None
        if "leed_last_lon" not in st.session_state:
            st.session_state.leed_last_lon = None

        should_geocode = False
        if project_key != st.session_state.leed_last_project_key:
            should_geocode = True
        if (default_addr or "") != (st.session_state.leed_last_addr or ""):
            should_geocode = True

        if should_geocode:
            st.session_state.leed_last_project_key = project_key
            st.session_state.leed_last_addr = default_addr or ""
            st.session_state.leed_last_lat = None
            st.session_state.leed_last_lon = None

            if default_addr and default_addr.strip():
                lat, lon = geocode_address_cached(default_addr.strip())
                st.session_state.leed_last_lat = lat
                st.session_state.leed_last_lon = lon

        # 2) pokaż mapę (albo komunikat)
        lat = st.session_state.leed_last_lat
        lon = st.session_state.leed_last_lon

        if default_addr:
            st.caption(default_addr)

        if lat is not None and lon is not None:
            st.map(pd.DataFrame({"lat": [lat], "lon": [lon]}))
        else:
            st.info("Nie udało się ustalić lokalizacji dla tego adresu (geokoder nie zwrócił wyniku).")
