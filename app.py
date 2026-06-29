import streamlit as st
import json
import urllib.request
import urllib.parse
import pandas as pd
import yfinance as yf
import feedparser
from sqlalchemy import create_engine, text, inspect

st.set_page_config(page_title="Gold Meter 2026", layout="wide", page_icon="🏅")

def get_engine():
    db = st.secrets["postgres"]
    password = urllib.parse.quote_plus(str(db["password"]))
    url = f"postgresql://{db['user']}:{password}@{db['host']}:{db['port']}/{db['database']}"
    return create_engine(url, connect_args={"sslmode": "require"})

def init_db():
    """تأكد من وجود الجدول قبل أي عملية"""
    engine = get_engine()
    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY, 
                username TEXT, 
                tg_id TEXT UNIQUE, 
                high NUMERIC, 
                low NUMERIC
            )
        """))
        conn.commit()

def main():
    init_db()
    st.title("🏅 Gold Meter - لوحة تحليل الذهب المتكاملة")
    
    # جلب الأسعار
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
    
    tab1, tab2, tab3 = st.tabs(["📊 التحليل", "📰 الأخبار", "🔔 التنبيهات"])
    
    with tab1:
        st.line_chart(yf.Ticker("GC=F").history(period="1mo")['Close'])
        
    with tab2:
        for entry in feedparser.parse("https://www.cnbcarabia.com/rss").entries[:5]:
            st.write(f"🔹 [{entry.title}]({entry.link})")
            
    with tab3:
        with st.form("alert_form"):
            n = st.text_input("الاسم")
            t = st.text_input("Telegram ID")
            h = st.number_input("هدف البيع", value=6000.0)
            l = st.number_input("هدف الشراء", value=5000.0)
            
            if st.form_submit_button("حفظ الإعدادات"):
                try:
                    engine = get_engine()
                    with engine.connect() as conn:
                        # استخدام الاستعلام المباشر
                        query = text("""
                            INSERT INTO users (username, tg_id, high, low) 
                            VALUES (:n, :t, :h, :l) 
                            ON CONFLICT(tg_id) DO UPDATE SET high=:h, low=:l, username=:n
                        """)
                        conn.execute(query, {"n": n, "t": t, "h": h, "l": l})
                        conn.commit()
                    st.success("تم حفظ بياناتك بنجاح في قاعدة البيانات!")
                except Exception as e:
                    st.error(f"خطأ أثناء الحفظ: {e}")

if __name__ == "__main__":
    main()
