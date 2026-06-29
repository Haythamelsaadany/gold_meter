import streamlit as st
import json
import urllib.request
import urllib.parse
import pandas as pd
import yfinance as yf
import feedparser
from sqlalchemy import create_engine, text

st.set_page_config(page_title="Gold Meter 2026", layout="wide")

def get_engine():
    db = st.secrets["postgres"]
    # استخدام quote_plus هو الحل النهائي للرموز الخاصة في كلمة المرور
    password = urllib.parse.quote_plus(str(db["password"]))
    url = f"postgresql://{db['user']}:{password}@{db['host']}:{db['port']}/{db['database']}"
    return create_engine(url, connect_args={"sslmode": "require"})

def init_db():
    try:
        with get_engine().connect() as conn:
            conn.execute(text("CREATE TABLE IF NOT EXISTS users (id SERIAL PRIMARY KEY, username TEXT, tg_id TEXT UNIQUE, high NUMERIC, low NUMERIC)"))
            conn.commit()
    except Exception as e: st.error(f"Error: {e}")

def main():
    init_db()
    st.title("🏅 Gold Meter - لوحة تحليل الذهب المتكاملة")
    
    # جلب البيانات
    gold, usd = 2330.0, 49.22
    try:
        with urllib.request.urlopen("https://api.gold-api.com/price/XAU", timeout=5) as r: gold = float(json.load(r)['price'])
        with urllib.request.urlopen("https://open.er-api.com/v6/latest/USD", timeout=5) as r: usd = float(json.load(r)['rates']['EGP'])
    except: pass
    
    gram21 = ((gold * usd) / 31.1035) * (21/24)
    c1, c2, c3 = st.columns(3)
    c1.metric("أوقية عالمي", f"${gold:,.2f}")
    c2.metric("سعر الدولار", f"{usd:.2f} ج.م")
    c3.metric("جرام 21", f"{gram21:,.2f} ج.م")
    
    st.divider()
    t1, t2, t3 = st.tabs(["📊 التحليل", "📰 الأخبار", "🔔 التنبيهات"])
    with t1: st.line_chart(yf.Ticker("GC=F").history(period="1mo")['Close'])
    with t2:
        for entry in feedparser.parse("https://www.cnbcarabia.com/rss").entries[:5]: st.write(f"🔹 [{entry.title}]({entry.link})")
    with t3:
        n, t, h, l = st.text_input("الاسم"), st.text_input("ID"), st.number_input("هدف البيع", 6000.0), st.number_input("هدف الشراء", 5000.0)
        if st.button("حفظ"):
            with get_engine().connect() as conn:
                conn.execute(text("INSERT INTO users (username, tg_id, high, low) VALUES (:n, :t, :h, :l) ON CONFLICT(tg_id) DO UPDATE SET high=:h, low=:l"), {"n": n, "t": t, "h": h, "l": l})
                conn.commit()
            st.success("تم الحفظ!")

if __name__ == "__main__": main()
