# pages/1_BREEAM_API_InUse.py
import os, re, json, requests, pandas as pd
from datetime import date
from dateutil import parser as dtparser
import streamlit as st
from requests.auth import HTTPBasicAuth

# ================== KONFIGURACJA BREEAM (credentials.py / ENV) ==================
BASE_DEFAULT = "https://api.breeam.com/datav1"

try:
    from credentials import BREEAM_USER as _CU, BREEAM_PASS as _CP
    BREEAM_USER, BREEAM_PASS = _CU, _CP
except Exception as e:
    BREEAM_USER = os.getenv("BREEAM_USER", "")
    BREEAM_PASS = os.getenv("BREEAM_PASS", "")
    print("Nie udało się zaimportować credentials.py:", e)

BREEAM_BASE = os.getenv("BREEAM_API_BASE", BASE_DEFAULT)

# ================== USTAWIENIA STRONY ==================
st.set_page_config(page_title="BREEAM aktualne", layout="wide")

# ================== NAV BUTTONS ==================
def nav_buttons(active: str = "breeam_api"):
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

nav_buttons("breeam_api")

st.title("🏢 BREEAM aktualne")

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

    if "months_to_expiry" in df.columns:
        df["expiry_status"] = df["months_to_expiry"].apply(status)
    else:
        df["expiry_status"] = "❓ Brak daty"
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

def sanitize_multiselect_state(state_key: str, options: list[str]):
    opts_set = set(options)
    if state_key in st.session_state:
        cur = st.session_state.get(state_key)
        if isinstance(cur, (list, tuple)):
            st.session_state[state_key] = [x for x in cur if x in opts_set]
        else:
            st.session_state[state_key] = []

def first_nonempty(row: pd.Series, candidates, default=""):
    for c in candidates:
        if c in row.index:
            val = row.get(c)
            if pd.notna(val) and str(val).strip().lower() not in ("", "nan"):
                return str(val).strip()
    return default

def build_address(row: pd.Series) -> str:
    street = first_nonempty(row, ["regAddresLine1", "regAddressLine1", "addressLine1", "address", "Address1", "Address"], "")
    street2 = first_nonempty(row, ["regAddresLine2", "regAddressLine2", "addressLine2", "Address2"], "")
    postcode = first_nonempty(row, ["postcode", "postCode", "zip", "zipCode", "postalCode", "PostalCode"], "")
    city = first_nonempty(row, ["city", "town"], "")
    region = first_nonempty(row, ["region", "county", "state"], "")
    country = first_nonempty(row, ["country"], "")

    parts = [p for p in [street, street2] if p]
    place = " ".join([p for p in [postcode, city] if p]).strip()
    if place:
        parts.append(place)
    if region:
        parts.append(region)
    if country:
        parts.append(country)

    return ", ".join(parts) if parts else "–"

# ================== API CALLS ==================
if not (BREEAM_USER and BREEAM_PASS):
    st.error("Brak poświadczeń. Dodaj plik credentials.py lub ustaw zmienne środowiskowe BREEAM_USER/BREEAM_PASS.")
    st.stop()

auth = HTTPBasicAuth(BREEAM_USER, BREEAM_PASS)
HDRS = {"Accept": "application/json"}

@st.cache_data(show_spinner=False, ttl=60*30)
def breeam_get(path: str, params=None):
    url = f"{BREEAM_BASE.rstrip('/')}/{path.lstrip('/')}"
    r = requests.get(url, auth=auth, headers=HDRS, params=params, timeout=60)
    if r.status_code == 401:
        raise RuntimeError("401 Unauthorized – sprawdź login/hasło/uprawnienia.")
    r.raise_for_status()
    return r.json()

@st.cache_data(show_spinner=False, ttl=60*30)
def breeam_countries():
    data = breeam_get("/countries")
    return list(sorted(data.get("results", {}).get("countries", {}).get("country", [])))

@st.cache_data(show_spinner=False, ttl=60*30)
def breeam_schemes_df() -> pd.DataFrame:
    """
    Bezpieczny parser /schemes:
    - obsługuje list/dict/None
    - zawsze zwraca DF z kolumnami schemeID, schemeName
    """
    data = breeam_get("/schemes")

    schemes = (
        data.get("results", {})
            .get("schemes", {})
            .get("scheme", [])
    )

    if isinstance(schemes, dict):
        schemes = [schemes]
    if schemes is None:
        schemes = []

    items = []
    for s in schemes:
        if not isinstance(s, dict):
            continue

        sid = s.get("schemeID")
        sname = s.get("schemeName")
        if sid is not None and sname is not None:
            items.append({"schemeID": sid, "schemeName": sname})

        sub = s.get("subSchemes", {}).get("scheme", [])
        if isinstance(sub, dict):
            sub = [sub]
        if sub is None:
            sub = []

        for ss in sub:
            if not isinstance(ss, dict):
                continue
            ssid = ss.get("schemeID")
            ssname = ss.get("schemeName")
            if ssid is not None and ssname is not None and sname is not None:
                items.append({"schemeID": ssid, "schemeName": f"{sname} / {ssname}"})

    df = pd.DataFrame(items)

    # ✅ gwarantuj kolumny nawet gdy pusto
    if df.empty:
        df = pd.DataFrame(columns=["schemeID", "schemeName"])
    else:
        for c in ["schemeID", "schemeName"]:
            if c not in df.columns:
                df[c] = pd.NA
        df = df[["schemeID", "schemeName"]].drop_duplicates()

    return df

def normalize_breeam_from_api(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    rename_api = {
        "buildingName": "asset_name",
        "name": "asset_name",
        "certNo": "certificate_number",
        "country": "country",
        "city": "city",
        "county": "region",
        "regAddresLine1": "regAddresLine1",
        "addressLine1": "addressLine1",
        "projectType": "projectType",
        "scheme": "scheme",
        "standard": "standard",
        "stage": "stage",
        "assessor": "assessor",
        "assessorAuditor": "assessor",
        "assessorName": "assessor",
        "auditor": "assessor",
        "publicUrl": "publicUrl",
    }
    for src, dst in rename_api.items():
        if src in df.columns and dst not in df.columns:
            df[dst] = df[src]
    return df

def compute_breeam_expiries(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    if "stage" in df.columns:
        parsed = df["stage"].map(parse_date_any)
        df["expiry_date"] = pd.to_datetime(parsed, errors="coerce").dt.date
        df["months_to_expiry"] = df["expiry_date"].map(months_left_signed)
    else:
        df["expiry_date"] = None
        df["months_to_expiry"] = None
    df = add_expiry_status(df)
    return df

def breeam_fetch_api(country: str | None, scheme_id: int | None) -> pd.DataFrame:
    path = f"/assessments/{scheme_id}" if scheme_id else "/assessments"
    params = {}
    if country:
        params["country"] = country
    data = breeam_get(path, params)
    raw = data.get("results", {}).get("assessments", {}).get("assessment", []) or []
    if isinstance(raw, dict):
        raw = [raw]
    if raw is None:
        raw = []
    return pd.DataFrame(raw)

# ================== UI: FILTRY POBIERANIA ==================
c1, c2 = st.columns([2, 3], gap="large")

with c1:
    countries = breeam_countries()
    opts_c = ["(dowolne)"] + countries
    idx_pl = opts_c.index("Poland") if "Poland" in opts_c else 0
    sel_country_lbl = st.selectbox("Państwo (API)", opts_c, index=idx_pl, key="b_country")
    sel_country = None if sel_country_lbl == "(dowolne)" else sel_country_lbl

with c2:
    df_schemes = breeam_schemes_df()

    with st.expander("Diagnostyka: /schemes"):
        st.write("BREEAM_BASE:", BREEAM_BASE)
        st.write("Liczba rekordów df_schemes:", len(df_schemes))
        st.write("Kolumny:", list(df_schemes.columns))
        st.dataframe(df_schemes.head(30), use_container_width=True)

    if df_schemes.empty or "schemeName" not in df_schemes.columns:
        st.error(
            "Nie udało się pobrać listy schematów z /schemes (brak danych lub brak kolumny schemeName). "
            "Sprawdź diagnostykę powyżej."
        )
        st.stop()

    df_inuse = df_schemes[
        df_schemes["schemeName"].astype(str).str.contains("in-use", case=False, na=False)
    ].copy()

    opts_s = df_inuse["schemeName"].tolist()
    if not opts_s:
        st.error("Nie znaleziono scheme zawierających 'In-Use' w API /schemes. Sprawdź diagnostykę /schemes.")
        st.stop()

    default_idx = 0
    for i, nm in enumerate(opts_s):
        if str(nm).strip().lower() == "in-use":
            default_idx = i
            break

    sel_scheme_name = st.selectbox("Rodzaj certyfikacji (tylko In-Use)", opts_s, index=default_idx, key="b_scheme")
    sel_scheme_id = int(df_inuse.loc[df_inuse["schemeName"] == sel_scheme_name, "schemeID"].iloc[0])

left_btn, right_btn = st.columns([1, 1])

if left_btn.button("Pobierz BREEAM z API (In-Use)", type="primary", key="btn_breeam"):
    with st.spinner("Pobieram dane z BREEAM API..."):
        df_api_raw = breeam_fetch_api(sel_country, sel_scheme_id)
        df_api = normalize_breeam_from_api(df_api_raw)
        df_api = compute_breeam_expiries(df_api)

    st.session_state.breeam_api_raw = df_api

    for k in ["b_pt_sel", "b_pt_multi", "b_view", "b_proj_sel"]:
        if k in st.session_state:
            del st.session_state[k]

    st.success(f"Pobrano rekordów z API: {len(df_api):,}")

if right_btn.button("Reset filtrów", key="btn_breeam_reset"):
    for k in ["b_pt_sel", "b_pt_multi", "b_view", "b_proj_sel"]:
        if k in st.session_state:
            del st.session_state[k]
    st.success("Filtry zresetowane.")

st.divider()

# ================== WIDOK DANYCH ==================
if "breeam_api_raw" not in st.session_state or st.session_state.breeam_api_raw is None or st.session_state.breeam_api_raw.empty:
    st.info("Brak danych. Kliknij **Pobierz BREEAM z API (In-Use)**.")
    st.stop()

df = st.session_state.breeam_api_raw.copy()

# ================== FILTR projectType ==================
st.markdown("## Filtr – typ projektu")

if "projectType" in df.columns:
    types = (
        df["projectType"]
        .astype(str)
        .str.strip()
        .replace("nan", pd.NA)
        .dropna()
        .unique()
        .tolist()
    )
    types = sorted(types)

    if "b_pt_sel" not in st.session_state or st.session_state.b_pt_sel is None:
        st.session_state.b_pt_sel = types[:]

    st.session_state.b_pt_sel = [x for x in st.session_state.b_pt_sel if x in set(types)]
    sanitize_multiselect_state("b_pt_multi", types)

    sel_types = st.multiselect(
        "Wybierz typy projektu",
        options=types,
        default=st.session_state.b_pt_sel,
        key="b_pt_multi",
    )
    st.session_state.b_pt_sel = sel_types

    if sel_types:
        df = df[df["projectType"].astype(str).str.strip().isin(sel_types)].copy()
    else:
        df = df.iloc[0:0].copy()

    st.caption(f"Po filtrze: **{len(df):,}** rekordów.")
else:
    st.warning("Brak kolumny projectType w danych z API.")

# ================== METRYKI + FILTR OKRESÓW ==================
st.markdown("## Podsumowanie")
total = len(df)
m = pd.to_numeric(df.get("months_to_expiry", pd.Series([None] * len(df))), errors="coerce")

urgent_0_6 = int(m.between(0, 6, inclusive="both").sum())
urgent_6_12 = int(m.between(7, 12, inclusive="both").sum())
mid_12_18 = int(m.between(12, 18, inclusive="both").sum())
over_18 = int((m > 18).sum())

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Liczba certyfikacji", f"{total:,}")
c2.metric("🔴 ≤ 6 mies.", urgent_0_6)
c3.metric("🟠 6–12 mies.", urgent_6_12)
c4.metric("🟡 12–18 mies.", mid_12_18)
c5.metric("✅ > 18 mies.", over_18)

view = st.radio(
    "Zakres widocznych certyfikacji",
    [
        "Wszystkie",
        "≤ 6 mies.",
        "6–12 mies.",
        "12–18 mies.",
        "> 18 mies.",
    ],
    horizontal=True,
    key="b_view",
)

if "months_to_expiry" in df.columns:
    mm = pd.to_numeric(df["months_to_expiry"], errors="coerce")
    if view == "≤ 6 mies.":
        df = df[mm.between(0, 6, inclusive="both")].copy()
    elif view == "6–12 mies.":
        df = df[mm.between(7, 12, inclusive="both")].copy()
    elif view == "12–18 mies.":
        df = df[mm.between(12, 18, inclusive="both")].copy()
    elif view == "> 18 mies.":
        df = df[mm > 18].copy()

st.divider()

# ================== TABELA (tylko wybrane kolumny) ==================
st.markdown("## Tabela (BREEAM aktualne)")

visible_cols = [
    "asset_name",
    "projectType",
    "standard",
    "scheme",
    "expiry_date",
    "months_to_expiry",
    "expiry_status",
    "assessor",
]
present = [c for c in visible_cols if c in df.columns]
df_view = df[present].copy()

st.dataframe(
    df_view.style.apply(color_rows_by_expiry, axis=1),
    use_container_width=True,
)

# ================== SZCZEGÓŁY + MAPA ==================
st.markdown("## Szczegóły wybranego certyfikatu")

if df.empty:
    st.info("Brak wyników po zastosowaniu filtrów.")
else:
    name_col = "asset_name" if "asset_name" in df.columns else df.columns[0]
    name_options = df[name_col].astype(str).fillna("(brak nazwy)").tolist()
    sel_name = st.selectbox("Wybierz projekt", name_options, index=0, key="b_proj_sel")
    row = df[df[name_col].astype(str) == sel_name].head(1).iloc[0]

    col_info, col_map = st.columns([3, 5], gap="large")

    with col_info:
        st.write("**Nazwa budynku:**", row.get("asset_name", "–"))
        st.write("**Typ projektu:**", row.get("projectType", "–"))
        st.write("**Standard:**", row.get("standard", "–"))
        st.write("**Scheme:**", row.get("scheme", "–"))
        st.write("**Assessor/Auditor:**", row.get("assessor", "–"))
        st.write("**Data ważności (stage):**", row.get("stage", "–"))
        st.write("**Data wygaśnięcia:**", row.get("expiry_date", "–"))
        st.write("**Miesiące do końca:**", row.get("months_to_expiry", "–"))
        st.write("**Status ważności:**", row.get("expiry_status", "–"))

        address_full = build_address(row)
        st.write("**Adres:**", address_full)

        url = row.get("publicUrl", None)
        if url:
            st.markdown(f"[Otwórz kartę projektu]({url})")

    with col_map:
        st.write("**Mapa lokalizacji**")

        lat, lon = None, None
        lat_col, lon_col = None, None
        for c in df.columns:
            cl = c.lower()
            if cl in ("lat", "latitude", "y") and lat_col is None:
                lat_col = c
            if cl in ("lon", "lng", "longitude", "x") and lon_col is None:
                lon_col = c

        if (
            lat_col and lon_col
            and pd.notna(row.get(lat_col)) and pd.notna(row.get(lon_col))
        ):
            try:
                lat = float(row[lat_col])
                lon = float(row[lon_col])
            except Exception:
                lat, lon = None, None

        if lat is not None and lon is not None:
            st.map(pd.DataFrame({"lat": [lat], "lon": [lon]}))
        else:
            st.info("Brak współrzędnych w danych z API — mapa niedostępna.")
