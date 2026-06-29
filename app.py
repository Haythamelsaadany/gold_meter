import streamlit as st
import psycopg2
import json
import urllib.request
import pandas as pd
import yfinance as yf
import plotly.express as px
import feedparser
import time

# إعداد الصفحة
st.set_page_config(page_title="Gold Meter 2026", layout="wide", page_icon="🏅")

# ==========================================
# 1. دالة الاتصال (الطريقة الأكثر استقراراً)
# ==========================================
def get_db_connection():
    # تأكد في الـ Secrets أنك وضعت DATABASE_URL بالكامل
    # الرابط يجب أن يكون: postgresql://postgres:[password]@db.zufalogivvjkejxewvnb.supabase.co:5432/postgres
    db_url = st.secrets["DATABASE_URL"]
    return psycopg2.connect(db_url, sslmode='require')

def init_db():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute('''CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY, 
            username TEXT, 
            tg_id TEXT UNIQUE, 
            high NUMERIC, 
            low NUMERIC)''')
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        st.error(f"خطأ في قاعدة البيانات: {e}")

# ==========================================
# 2. جلب البيانات (الأسعار والأخبار)
# ==========================================
@st.cache_data(ttl=300)
def fetch_data():
    usd_price = 2330.0
    try:
        with urllib.request.urlopen("https://api.gold-api.com/price/XAU", timeout=5) as r:
            usd_price = float(json.load(r)['price'])
    except: pass
    usd_egp = 49.22
    try:
        with urllib.request.urlopen("https://open.er-api.com/v6/latest/USD", timeout=5) as r:
            usd_egp = float(json.load(r)['rates']['EGP'])
    except: pass
    return usd_price, usd_egp

# ==========================================
# 3. الواجهة الرئيسية
# ==========================================
def main():
    st.title("🏅 Gold Meter - لوحة تحليل الذهب المتكاملة")
    
    usd, egp = fetch_data()
    ounce_to_gram = 31.1034768
    gram21 = ((usd * egp) / ounce_to_gram) * (21/24)
    
    c1, c2, c3 = st.columns(3)
    c1.metric("أوقية عالمي", f"${usd:,.2f}")
    c2.metric("سعر الدولار", f"{egp:.2f} ج.م")
    c3.metric("جرام 21", f"{gram21:,.2f} ج.م")
    
    st.divider()
    
    tab1, tab2, tab3 = st.tabs(["📊 التحليل", "📰 الأخبار", "🔔 التنبيهات"])
    
    with tab1:
        hist = yf.Ticker("GC=F").history(period="1mo")
        st.line_chart(hist['Close'])
        
    with tab2:
        feed = feedparser.parse("https://www.cnbcarabia.com/rss")
        for entry in feed.entries[:5]:
            st.write(f"🔹 [{entry.title}]({entry.link})")
            
    with tab3:
        name = st.text_input("الاسم")
        tg_id = st.text_input("Chat ID")
        h = st.number_input("هدف البيع", value=6000.0)
        l = st.number_input("هدف الشراء", value=5000.0)
        
        if st.button("حفظ الإعدادات"):
            try:
                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("INSERT INTO users (username, tg_id, high, low) VALUES (%s, %s, %s, %s) ON CONFLICT(tg_id) DO UPDATE SET high=%s, low=%s", (name, tg_id, h, l, h, l))
                conn.commit()
                cur.close()
                conn.close()
                st.success("تم الحفظ!")
            except Exception as e:
                st.error(f"خطأ أثناء الحفظ: {e}")

    st.markdown("<hr><div style='text-align:center'>© Techno logic 2026. Haytham Elsaadany</div>", unsafe_allow_html=True)

if __name__ == "__main__":
    init_db()
    main()
