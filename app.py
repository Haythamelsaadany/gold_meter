import streamlit as st
from sqlalchemy import create_engine, text
import json
import urllib.request
import urllib.parse
import pandas as pd
import yfinance as yf
import feedparser

# إعداد الصفحة
st.set_page_config(page_title="Gold Meter 2026", layout="wide", page_icon="🏅")

# ==========================================
# الاتصال الآمن بقاعدة البيانات (يستخدم [postgres] من الـ Secrets)
# ==========================================
def get_engine():
    # جلب البيانات من الـ Secrets
    db = st.secrets["postgres"]
    
    # تنظيف كلمة المرور من الرموز الخاصة
    password = urllib.parse.quote_plus(db["password"])
    
    # بناء رابط الاتصال (Connection String)
    url = f"postgresql://{db['user']}:{password}@{db['host']}:{db['port']}/{db['database']}"
    
    # إنشاء المحرك
    return create_engine(url, connect_args={"sslmode": "require"})

def init_db():
    try:
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
    except Exception as e:
        st.error(f"خطأ في تهيئة قاعدة البيانات: {e}")

# ==========================================
# الدوال الأساسية
# ==========================================
@st.cache_data(ttl=300)
def fetch_market_data():
    # بيانات الذهب والدولار
    gold, usd = 2330.0, 49.22
    try:
        with urllib.request.urlopen("https://api.gold-api.com/price/XAU", timeout=5) as r:
            gold = float(json.load(r)['price'])
        with urllib.request.urlopen("https://open.er-api.com/v6/latest/USD", timeout=5) as r:
            usd = float(json.load(r)['rates']['EGP'])
    except: pass
    return gold, usd

# ==========================================
# واجهة التطبيق الرئيسية
# ==========================================
def main():
    init_db()
    st.title("🏅 Gold Meter - لوحة تحليل الذهب المتكاملة")
    
    gold, usd = fetch_market_data()
    gram21 = ((gold * usd) / 31.1035) * (21/24)
    
    c1, c2, c3 = st.columns(3)
    c1.metric("أوقية عالمي", f"${gold:,.2f}")
    c2.metric("سعر الدولار", f"{usd:.2f} ج.م")
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
        st.subheader("إعداد التنبيهات")
        name = st.text_input("الاسم")
        tg_id = st.text_input("Telegram ID")
        h = st.number_input("هدف البيع", value=6000.0)
        l = st.number_input("هدف الشراء", value=5000.0)
        
        if st.button("حفظ الإعدادات"):
            try:
                engine = get_engine()
                with engine.connect() as conn:
                    conn.execute(text(
                        "INSERT INTO users (username, tg_id, high, low) VALUES (:n, :t, :h, :l) "
                        "ON CONFLICT(tg_id) DO UPDATE SET high=:h, low=:l"
                    ), {"n": name, "t": tg_id, "h": h, "l": l})
                    conn.commit()
                st.success("تم الحفظ بنجاح!")
            except Exception as e:
                st.error(f"حدث خطأ: {e}")

    st.markdown("<hr><div style='text-align:center'>© Techno logic 2026. Haytham Elsaadany</div>", unsafe_allow_html=True)

if __name__ == "__main__":
    main()
