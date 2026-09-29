"""Streamlit entry point (``daytrader dashboard`` or ``streamlit run .../app.py``)."""

import streamlit as st

from daytrader.dashboard import common, views

st.set_page_config(page_title="Daytrader", page_icon="📈", layout="wide")

pages = {
    "analysis": st.Page(views.analysis_page, title="Analýza", icon="📈", url_path="analyza", default=True),
    "scanner": st.Page(views.scanner_page, title="Scanner", icon="🔎", url_path="scanner"),
    "backtest": st.Page(views.backtest_page, title="Backtest", icon="🧪", url_path="backtest"),
    "trading": st.Page(views.trading_page, title="Obchodování", icon="💼", url_path="obchodovani"),
    "bot": st.Page(views.bot_page, title="Bot", icon="🤖", url_path="bot"),
    "journal": st.Page(views.journal_page, title="Deník", icon="📒", url_path="denik"),
    "settings": st.Page(views.settings_page, title="Nastavení", icon="⚙️", url_path="nastaveni"),
}
st.session_state["_pages"] = pages

navigation = st.navigation(list(pages.values()))
common.render_sidebar()
navigation.run()
