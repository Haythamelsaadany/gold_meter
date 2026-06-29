import streamlit as st
from sqlalchemy import create_engine
import json
import urllib.request
import pandas as pd
import yfinance as yf
import feedparser

# إعداد الصفحة
st.set_page_config(page_title="Gold Meter 2026", layout="wide", page_icon="🏅")

# ==========================================
# الاتصال باستخدام SQLAlchemy (الحل النهائي)
# ==========================================
def get_db_engine():
    # الرابط كما هو في الـ Secrets
    db_url = st.secrets["DATABASE_URL"]
    # إنشاء المحرك الذي يتعامل مع كل الرموز بشكل آلي
    return create_engine(db_url)

def init_db():
    try:
        engine = get_db_engine()
        with engine.connect() as conn:
            # استخدام النص التابع لـ SQLAlchemy
            conn.execute("CREATE TABLE IF NOT EXISTS users (id SERIAL PRIMARY KEY, username TEXT, tg_id TEXT UNIQUE, high NUMERIC, low NUMERIC)")
            conn.commit()
    except Exception as e:
        st.error(f"خطأ في الاتصال: {e}")

# ... (باقي دوال fetch_data و main كما في الكود السابق)
