import streamlit as st
import psycopg2
import json
import urllib.request
import urllib.parse
import pandas as pd
import yfinance as yf
import feedparser

# إعداد الصفحة
st.set_page_config(page_title="Gold Meter 2026", layout="wide", page_icon="🏅")

# ==========================================
# 1. الاتصال الآمن بقاعدة البيانات (حل مشكلة الرموز)
# ==========================================
def get_db_connection():
    try:
        raw_url = st.secrets["DATABASE_URL"]
        parsed = urllib.parse.urlparse(raw_url)
        # تشفير كلمة المرور لتجنب خطأ الرموز الخاصة
        encoded_password = urllib.parse.quote(parsed.password, safe='')
        safe_url = f"{parsed.scheme}://{parsed.username}:{encoded_password}@{parsed.hostname}:{parsed.port}{parsed.path}"
        return psycopg2.connect(safe_url, sslmode='require')
    except Exception as e:
        st.error(f"خطأ في الاتصال: {e}")
        return None

def init_db():
    conn = get_db_connection()
    if conn:
        with conn.cursor() as cur:
            cur.execute('''CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY, username TEXT, tg_id TEXT UNIQUE, 
                high NUMERIC, low NUMERIC)''')
            conn.commit()
        conn.close()

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
    init_db()
    st.title("🏅 Gold Meter - لوحة تحليل الذهب المتكاملة")
    
    usd, egp = fetch_data()
    ounce_to_gram = 31.1034768
    gram21 = ((usd * egp) / ounce_to_gram) * (21/24)
    
    # عرض الأسعار
    c1, c2, c3 = st.columns(3)
    c1.metric("أوقية عالمي", f"${usd:,.2f}")
    c2.metric("سعر الدولار", f"{egp:.2f} ج.م")
    c3.metric("جرام 21", f"{gram21:,.2f} ج.م")
    
    st.divider()
    
    # الأقسام
    tab1, tab2, tab3 = st.tabs(["📊 التحليل", "📰 الأخبار", "🔔 التنبيهات"])
    
    with tab1:
        st.subheader("الاتجاه التاريخي")
        hist = yf.Ticker("GC=F").history(period="1mo")
        st.line_chart(hist['Close'])
        
    with tab2:
        st.subheader("أهم الأخبار")
        feed = feedparser.parse("https://www.cnbcarabia.com/rss")
        for entry in feed.entries[:5]:
            st.write(f"🔹 [{entry.title}]({entry.link})")
            
    with tab3:
        st.subheader("إعدادات التنبيهات (Telegram)")
        name = st.text_input("الاسم")
        tg_id = st.text_input("Chat ID")
        h = st.number_input("هدف البيع", value=6000.0)
        l = st.number_input("هدف الشراء", value=5000.0)
        
        if st.button("حفظ الإعدادات"):
            conn = get_db_connection()
            if conn:
                with conn.cursor() as cur:
                    cur.execute("INSERT INTO users (username, tg_id, high, low) VALUES (%s, %s, %s, %s) ON CONFLICT(tg_id) DO UPDATE SET high=%s, low=%s", (name, tg_id, h, l, h, l))
                    conn.commit()
                conn.close()
                st.success("تم حفظ أهدافك بنجاح!")

    st.markdown("<hr><div style='text-align:center'>© Techno logic 2026. Haytham Elsaadany</div>", unsafe_allow_html=True)

if __name__ == "__main__":
    main()
