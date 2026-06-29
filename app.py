import streamlit as st
import psycopg2
import json
import urllib.request
import pandas as pd
import yfinance as yf
import plotly.express as px
import feedparser
import time

# إعدادات الواجهة
st.set_page_config(page_title="Gold Meter 2026", layout="wide", page_icon="🏅")

# ==========================================
# 1. الاتصال بقاعدة البيانات (المحدث)
# ==========================================
def get_db_connection():
    try:
        config = st.secrets["postgres"]
        return psycopg2.connect(
            host=config["host"],
            port=config["port"],
            database=config["database"],
            user=config["user"],
            password=config["password"],
            connect_timeout=10
        )
    except Exception as e:
        st.error(f"خطأ في الاتصال بقاعدة البيانات: {e}")
        st.stop()

def init_db():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute('''CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY, 
            username TEXT, 
            tg_id TEXT UNIQUE, 
            high NUMERIC, 
            low NUMERIC, 
            enabled INT DEFAULT 1)''')
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        st.error(f"خطأ في تهيئة القاعدة: {e}")

# ==========================================
# 2. جلب البيانات (الأسعار والأخبار)
# ==========================================
@st.cache_data(ttl=300)
def fetch_data():
    # السعر العالمي
    usd_price = 2330.0
    try:
        with urllib.request.urlopen("https://api.gold-api.com/price/XAU", timeout=3) as r:
            usd_price = float(json.load(r)['price'])
    except: pass
    
    # سعر الدولار
    usd_egp = 49.22
    try:
        with urllib.request.urlopen("https://open.er-api.com/v6/latest/USD", timeout=3) as r:
            usd_egp = float(json.load(r)['rates']['EGP'])
    except: pass
    
    return usd_price, usd_egp

# ==========================================
# 3. الواجهة الرئيسية (التطبيق)
# ==========================================
def main():
    init_db()
    st.title("🏅 Gold Meter - لوحة تحليل الذهب المتكاملة")
    
    usd, egp = fetch_data()
    ounce_to_gram = 31.1034768
    gram21 = ((usd * egp) / ounce_to_gram) * (21/24)
    
    # أعمدة الأسعار
    c1, c2, c3 = st.columns(3)
    c1.metric("أوقية عالمي", f"${usd:,.2f}")
    c2.metric("سعر الدولار", f"{egp:.2f} ج.م")
    c3.metric("جرام 21", f"{gram21:,.2f} ج.م")
    
    st.divider()
    
    # الأقسام
    tab1, tab2, tab3 = st.tabs(["📊 التحليل التاريخي", "📰 الأخبار الاقتصادية", "🔔 التنبيهات"])
    
    with tab1:
        st.subheader("الاتجاه العالمي (آخر شهر)")
        hist = yf.Ticker("GC=F").history(period="1mo")
        st.line_chart(hist['Close'])
        
    with tab2:
        st.subheader("أهم العناوين")
        feed = feedparser.parse("https://www.cnbcarabia.com/rss")
        for entry in feed.entries[:5]:
            st.write(f"🔹 [{entry.title}]({entry.link})")
            
    with tab3:
        st.subheader("إعداد تنبيهات Telegram")
        name = st.text_input("الاسم")
        tg_id = st.text_input("Chat ID")
        h = st.number_input("هدف البيع (جني الأرباح)", value=6000.0)
        l = st.number_input("هدف الشراء (التجميع)", value=5000.0)
        
        if st.button("حفظ الأهداف"):
            try:
                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("INSERT INTO users (username, tg_id, high, low) VALUES (%s, %s, %s, %s) ON CONFLICT(tg_id) DO UPDATE SET high=%s, low=%s", (name, tg_id, h, l, h, l))
                conn.commit()
                cur.close()
                conn.close()
                st.success("تم حفظ إعداداتك بنجاح!")
            except Exception as e:
                st.error("حدث خطأ أثناء الحفظ")

    st.markdown("<hr><div style='text-align:center'>© Techno logic 2026. Haytham Elsaadany</div>", unsafe_allow_html=True)

if __name__ == "__main__":
    main()
