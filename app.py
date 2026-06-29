import streamlit as st
import psycopg2
import json
import urllib.request
import pandas as pd
import yfinance as yf
import plotly.express as px
import feedparser
from datetime import datetime

# إعداد الصفحة
st.set_page_config(page_title="Gold Meter 2026", layout="wide")

class GoldMeterApp:
    def __init__(self):
        self.OUNCE_TO_GRAM = 31.1034768
        self.init_db()

    def get_db(self):
        config = st.secrets["postgres"]
        return psycopg2.connect(**config)

    def init_db(self):
        with self.get_db() as conn:
            with conn.cursor() as cur:
                cur.execute('''CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY, username TEXT, tg_id TEXT UNIQUE, 
                    high NUMERIC, low NUMERIC, enabled INT DEFAULT 1)''')
                conn.commit()

    @st.cache_data(ttl=60)
    def get_data(self):
        # جلب السعر العالمي
        usd_price = 2330.0
        try:
            with urllib.request.urlopen("https://api.gold-api.com/price/XAU", timeout=3) as r:
                usd_price = float(json.load(r)['price'])
        except: pass
        
        # جلب الدولار
        usd_egp = 49.22
        try:
            with urllib.request.urlopen("https://open.er-api.com/v6/latest/USD", timeout=3) as r:
                usd_egp = float(json.load(r)['rates']['EGP'])
        except: pass
        
        return usd_price, usd_egp

    def render_ui(self):
        st.title("🏅 Gold Meter - المساعد المالي الذكي")
        usd, egp = self.get_data()
        gram21 = ((usd * egp) / self.OUNCE_TO_GRAM) * (21/24)
        
        # Dashboard
        c1, c2, c3 = st.columns(3)
        c1.metric("أوقية عالمي", f"${usd:,.2f}")
        c2.metric("سعر الدولار", f"{egp:.2f} ج.م")
        c3.metric("جرام 21", f"{gram21:,.2f} ج.م")
        
        st.divider()
        
        # Tabs for Content
        tab1, tab2, tab3 = st.tabs(["📊 التحليل", "📰 الأخبار", "🔔 التنبيهات"])
        
        with tab1:
            st.subheader("الاتجاه التاريخي")
            hist = yf.Ticker("GC=F").history(period="1mo")
            if not hist.empty:
                st.line_chart(hist['Close'])
        
        with tab2:
            st.subheader("آخر المستجدات الاقتصادية")
            feed = feedparser.parse("https://www.cnbcarabia.com/rss")
            for entry in feed.entries[:5]:
                st.markdown(f"👉 [{entry.title}]({entry.link})")
                
        with tab3:
            st.subheader("إعداد التنبيهات الشخصية")
            name = st.text_input("الاسم")
            tg = st.text_input("Telegram ID")
            h, l = st.number_input("هدف البيع", 6000.0), st.number_input("هدف الشراء", 5000.0)
            if st.button("تفعيل التنبيهات"):
                with self.get_db() as conn:
                    with conn.cursor() as cur:
                        cur.execute("INSERT INTO users (username, tg_id, high, low) VALUES (%s, %s, %s, %s) ON CONFLICT(tg_id) DO UPDATE SET high=%s, low=%s", (name, tg, h, l, h, l))
                        conn.commit()
                st.success("تم تحديث أهدافك في قاعدة البيانات بنجاح!")

        st.markdown("<hr><div style='text-align:center'>© Techno logic 2026. Haytham Elsaadany</div>", unsafe_allow_html=True)

# تشغيل التطبيق
if __name__ == "__main__":
    app = GoldMeterApp()
    app.render_ui()
