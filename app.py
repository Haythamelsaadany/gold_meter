import streamlit as st
from sqlalchemy import create_engine, text
import json
import urllib.request
import pandas as pd
import yfinance as yf
import feedparser

# إعداد الصفحة
st.set_page_config(page_title="Gold Meter 2026", layout="wide", page_icon="🏅")

# ==========================================
# الاتصال الآمن بقاعدة البيانات (المحدث)
# ==========================================
def get_engine():
    # جلب البيانات من القسم [postgres] الذي وضعناه في الـ Secrets
    db = st.secrets["postgres"]
    url = f"postgresql://{db['user']}:{urllib.parse.quote_plus(db['password'])}@{db['host']}:{db['port']}/{db['database']}"
    return create_engine(url, connect_args={"sslmode": "require"})

def init_db():
    try:
        engine = get_engine()
        with engine.connect() as conn:
            conn.execute(text("CREATE TABLE IF NOT EXISTS users (id SERIAL PRIMARY KEY, username TEXT, tg_id TEXT UNIQUE, high NUMERIC, low NUMERIC)"))
            conn.commit()
    except Exception as e:
        st.error(f"خطأ في الاتصال: {e}")

# ... (باقي الدوال: fetch_data, main كما في الكود السابق) ...
