import streamlit as st
import pandas as pd
import yfinance as yf
import feedparser
import json
import urllib.request
import urllib.parse
from sqlalchemy import create_engine, text
from datetime import datetime

# ==========================================================
# فئة التطبيق الشاملة (GoldMeterApp)
# ==========================================================
class GoldMeterApp:
    def __init__(self):
        # إعداد الاتصال بقاعدة البيانات بشكل احترافي
        self.engine = self._connect_db()
        self._initialize_tables()

    def _connect_db(self):
        """إنشاء محرك اتصال بقاعدة البيانات"""
        db = st.secrets["postgres"]
        url = f"postgresql://{db['user']}:{urllib.parse.quote_plus(str(db['password']))}@{db['host']}:{db['port']}/{db['database']}"
        return create_engine(url, connect_args={"sslmode": "require"})

    def _initialize_tables(self):
        """إنشاء الجداول إذا لم تكن موجودة"""
        with self.engine.connect() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    username VARCHAR(255),
                    tg_id VARCHAR(100) UNIQUE,
                    high NUMERIC,
                    low NUMERIC,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """))
            conn.commit()

    def get_market_data(self):
        """جلب بيانات الذهب والدولار الحية"""
        try:
            with urllib.request.urlopen("https://api.gold-api.com/price/XAU", timeout=5) as r:
                gold_price = json.load(r)['price']
            with urllib.request.urlopen("https://open.er-api.com/v6/latest/USD", timeout=5) as r:
                dollar_rate = json.load(r)['rates']['EGP']
            return float(gold_price), float(dollar_rate)
        except:
            return 2330.0, 49.22 # قيم افتراضية في حالة تعطل الـ API

    def run(self):
        """الواجهة الرئيسية للتطبيق"""
        st.set_page_config(page_title="Gold Meter Pro", layout="wide")
        st.title("🏅 Gold Meter - النظام الشامل")
        
        # 1. قسم الأسعار
        gold, usd = self.get_market_data()
        gram21 = ((gold * usd) / 31.1035) * (21/24)
        
        c1, c2, c3 = st.columns(3)
        c1.metric("أوقية عالمي", f"${gold:,.2f}")
        c2.metric("سعر الدولار", f"{usd:.2f} ج.م")
        c3.metric("جرام 21", f"{gram21:,.2f} ج.م")

        # 2. قسم الأخبار
        with st.expander("📰 آخر الأخبار الاقتصادية"):
            feed = feedparser.parse("https://www.cnbcarabia.com/rss")
            for entry in feed.entries[:5]:
                st.markdown(f"🔹 [{entry.title}]({entry.link})")

        # 3. قسم التحليل الفني
        st.subheader("📊 التحليل الفني (سعر الأوقية)")
        hist = yf.Ticker("GC=F").history(period="1mo")
        st.line_chart(hist['Close'])

        # 4. قسم التنبيهات
        st.subheader("🔔 نظام التنبيهات الذكي")
        with st.form("alert_form"):
            name = st.text_input("الاسم الكريم")
            tid = st.text_input("معرف التليجرام (Chat ID)")
            h = st.number_input("سعر البيع المستهدف", value=6000.0)
            l = st.number_input("سعر الشراء المستهدف", value=5000.0)
            
            if st.form_submit_button("حفظ الإعدادات في السحابة"):
                with self.engine.connect() as conn:
                    conn.execute(text(
                        "INSERT INTO users (username, tg_id, high, low) VALUES (:n, :t, :h, :l) "
                        "ON CONFLICT(tg_id) DO UPDATE SET high=:h, low=:l, username=:n"
                    ), {"n": name, "t": tid, "h": h, "l": l})
                    conn.commit()
                st.success("تم ربط حسابك بنظام التنبيهات بنجاح!")

# تشغيل التطبيق
if __name__ == "__main__":
    app = GoldMeterApp()
    app.run()
