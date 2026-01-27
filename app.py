# app.py
import os
import csv
from datetime import datetime
import streamlit as st

st.set_page_config(page_title="BREEAM & LEED – przegląd certyfikacji", layout="wide")

# ====== KONFIG (jak było wcześniej: credentials.py / ENV) ======
BASE_DEFAULT = "https://api.breeam.com/datav1"
try:
    from credentials import BREEAM_USER as _CU, BREEAM_PASS as _CP, ADMIN_CODE as _AC
    BREEAM_USER, BREEAM_PASS = _CU, _CP
    ADMIN_CODE = _AC
except Exception:
    BREEAM_USER = os.getenv("BREEAM_USER", "")
    BREEAM_PASS = os.getenv("BREEAM_PASS", "")
    ADMIN_CODE = os.getenv("ADMIN_CODE", "")

BREEAM_BASE = os.getenv("BREEAM_API_BASE", BASE_DEFAULT)

# Pliki lokalne
BREEAM_HIST_PATH = r"BREEAM.xlsx"
LEED_PATH = r"PublicLEEDProjectDirectory.xlsx"

# Feedback
FEEDBACK_PATH = "feedback.csv"



def save_feedback_local(message: str, full_name: str = "", page: str = "Home"):
    exists = os.path.exists(FEEDBACK_PATH)
    with open(FEEDBACK_PATH, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if not exists:
            w.writerow(["timestamp", "page", "full_name", "message"])
        w.writerow([datetime.now().isoformat(timespec="seconds"), page, full_name, message])


def nav_buttons(active: str = "home"):
    c1, c2, c3, c4 = st.columns(4, gap="medium")
    with c1:
        if st.button("🏠 Home", use_container_width=True, disabled=(active=="home")):
            st.switch_page("app.py")
    with c2:
        if st.button("🏢 BREEAM aktualne", use_container_width=True, disabled=(active=="breeam_api")):
            st.switch_page("pages/1_BREEAM_API_InUse.py")
    with c3:
        if st.button("⛔ BREEAM wygasłe", use_container_width=True, disabled=(active=="breeam_exp")):
            st.switch_page("pages/2_BREEAM_Wygasle_Excel.py")
    with c4:
        if st.button("📄 LEED", use_container_width=True, disabled=(active=="leed")):
            st.switch_page("pages/3_LEED_Excel.py")

nav_buttons("home")
st.title("BREEAM & LEED – przegląd certyfikacji")
#st.caption("Aplikacja wielostronicowa: BREEAM (API In-Use), BREEAM wygasłe (Excel), LEED (Excel).")


st.divider()


# ====== Feedback (imię i nazwisko) ======
st.subheader("Masz problem? Masz pomysł jak ulepszyć aplikację?")

with st.form("feedback_form", clear_on_submit=True):
    full_name = st.text_input("Imię i nazwisko", value="", placeholder="np. Jan Kowalski")
    msg = st.text_area("Wiadomość", height=160, placeholder="Opisz problem lub propozycję ulepszenia…")
    submitted = st.form_submit_button("Wyślij")

if submitted:
    if not full_name.strip():
        st.warning("Wpisz imię i nazwisko.")
    elif not msg.strip():
        st.warning("Wpisz treść wiadomości.")
    else:
        save_feedback_local(msg.strip(), full_name.strip(), page="Home")
        st.success("Dziękuję! Zgłoszenie zapisane.")

# ====== Admin: odblokowanie pobrania feedback.csv kodem ======
st.divider()
st.subheader("Zgłoszenia (admin)")

# stan dostępu
if "admin_ok" not in st.session_state:
    st.session_state.admin_ok = False

if not st.session_state.admin_ok:
    col1, col2 = st.columns([2, 1], gap="medium")
    with col1:
        code = st.text_input("Wpisz kod dostępu", type="password", placeholder="")
    with col2:
        if st.button("Otwórz", use_container_width=True):
            if code == ADMIN_CODE:
                st.session_state.admin_ok = True
                st.success("Dostęp przyznany.")
            else:
                st.error("Błędny kod.")
else:
    st.success("Panel admina odblokowany.")
    if os.path.exists(FEEDBACK_PATH):
        with open(FEEDBACK_PATH, "rb") as f:
            st.download_button(
                "Pobierz feedback.csv",
                data=f,
                file_name="feedback.csv",
                mime="text/csv",
                use_container_width=True,
            )
    else:
        st.info("Brak zgłoszeń (feedback.csv jeszcze nie istnieje).")

    # opcjonalnie: wylogowanie
    if st.button("Zablokuj panel admina", use_container_width=True):
        st.session_state.admin_ok = False
        st.info("Panel admina zablokowany.")
