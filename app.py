import streamlit as st
from sqlalchemy import create_engine, text
import json
import urllib.request
import pandas as pd
import yfinance as yf
import feedparser

# 1. إعدادات الصفحة والاتصال
st.set_page_config(page_title="Gold Meter 2026", layout="wide", page_icon="🏅")

def get_engine():
    # الرابط الكامل من Secrets
    return create_engine(st.secrets["DATABASE_URL"], connect_args={"sslmode": "require"})

def init_db():
    try:
        engine = get_engine()
        with engine.connect() as conn:
            conn.execute(text("CREATE TABLE IF NOT EXISTS users (id SERIAL PRIMARY KEY, username TEXT, tg_id TEXT UNIQUE, high NUMERIC, low NUMERIC)"))
            conn.commit()
    except Exception as e:
        st.error(f"خطأ اتصال: {e}")

# 2. جلب الأسعار
@st.cache_data(ttl=300)
def fetch_data():
    usd_price, usd_egp = 2330.0, 49.22
    try:
        with urllib.request.urlopen("https://api.gold-api.com/price/XAU", timeout=5) as r:
            usd_price = float(json.load(r)['price'])
        with urllib.request.urlopen("https://open.er-api.com/v6/latest/USD", timeout=5) as r:
            usd_egp = float(json.load(r)['rates']['EGP'])
    except: pass
    return usd_price, usd_egp

# 3. الواجهة
def main():
    init_db()
    st.title("🏅 Gold Meter - لوحة تحليل الذهب المتكاملة")
    usd, egp = fetch_data()
    gram21 = ((usd * egp) / 31.1035) * (21/24)
    
    c1, c2, c3 = st.columns(3)
    c1.metric("أوقية عالمي", f"${usd:,.2f}")
    c2.metric("سعر الدولار", f"{egp:.2f} ج.م")
    c3.metric("جرام 21", f"{gram21:,.2f} ج.م")
    
    st.divider()
    t1, t2, t3 = st.tabs(["📊 التحليل", "📰 الأخبار", "🔔 التنبيهات"])
    
    with t1:
        hist = yf.Ticker("GC=F").history(period="1mo")
        st.line_chart(hist['Close'])
    with t2:
        for entry in feedparser.parse("https://www.cnbcarabia.com/rss").entries[:5]:
            st.write(f"🔹 [{entry.title}]({entry.link})")
    with t3:
        name = st.text_input("الاسم")
        tg_id = st.text_input("Chat ID")
        h, l = st.number_input("هدف البيع", 6000.0), st.number_input("هدف الشراء", 5000.0)
        if st.button("حفظ"):
            engine = get_engine()
            with engine.connect() as conn:
                conn.execute(text("INSERT INTO users (username, tg_id, high, low) VALUES (:n, :t, :h, :l) ON CONFLICT(tg_id) DO UPDATE SET high=:h, low=:l"), {"n": name, "t": tg_id, "h": h, "l": l})
                conn.commit()
            st.success("تم الحفظ!")

if __name__ == "__main__":
    main()
