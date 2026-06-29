import streamlit as st
import json
import urllib.request
import urllib.parse
import pandas as pd
import yfinance as yf
import feedparser
from sqlalchemy import create_engine, text

st.set_page_config(page_title="Gold Meter 2026", layout="wide", page_icon="🏅")

# ==========================================
# إدارة الاتصال بمحرك ذكي (Engine)
# ==========================================
@st.cache_resource
def get_engine():
    db = st.secrets["postgres"]
    password = urllib.parse.quote_plus(str(db["password"]))
    url = f"postgresql://{db['user']}:{password}@{db['host']}:{db['port']}/{db['database']}"
    # تقليل حجم الـ pool لتجنب الأخطاء
    return create_engine(url, pool_size=5, max_overflow=10, pool_timeout=30)

def init_db():
    try:
        engine = get_engine()
        with engine.begin() as conn: # استخدام engine.begin() يضمن إغلاق الاتصال تلقائياً
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY, username TEXT, tg_id TEXT UNIQUE, high NUMERIC, low NUMERIC
                )
            """))
    except Exception as e:
        st.error(f"خطأ في الاتصال: {e}")

# ==========================================
# الدالة الرئيسية
# ==========================================
def main():
    init_db()
    st.title("🏅 Gold Meter - لوحة تحليل الذهب المتكاملة")
    
    # جلب البيانات
    gold, usd = 2330.0, 49.22
    try:
        with urllib.request.urlopen("https://api.gold-api.com/price/XAU", timeout=5) as r: gold = float(json.load(r)['price'])
        with urllib.request.urlopen("https://open.er-api.com/v6/latest/USD", timeout=5) as r: usd = float(json.load(r)['rates']['EGP'])
    except: pass
    
    # حساب العيارات
    g21 = ((gold * usd) / 31.1035) * (21/24)
    c1, c2, c3 = st.columns(3)
    c1.metric("أوقية", f"${gold:,.2f}")
    c2.metric("دولار", f"{usd:.2f} ج.م")
    c3.metric("جرام 21", f"{g21:,.2f} ج.م")
    
    st.divider()
    
    # قسم التنبيهات
    with st.form("alert_form"):
        n, t, h, l = st.text_input("الاسم"), st.text_input("ID"), st.number_input("هدف البيع", value=6000.0), st.number_input("هدف الشراء", value=5000.0)
        if st.form_submit_button("حفظ"):
            try:
                with get_engine().begin() as conn: # الاتصال هنا يغلق نفسه فور انتهاء العملية
                    conn.execute(text("INSERT INTO users (username, tg_id, high, low) VALUES (:n, :t, :h, :l) ON CONFLICT(tg_id) DO UPDATE SET high=:h, low=:l"), 
                                 {"n": n, "t": t, "h": h, "l": l})
                st.success("تم الحفظ!")
            except Exception as e:
                st.error(f"فشل الحفظ: {e}")

if __name__ == "__main__":
    main()
