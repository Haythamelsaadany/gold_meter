import streamlit as st
import json
import urllib.request
import urllib.parse
import pandas as pd
import yfinance as yf
import feedparser
from sqlalchemy import create_engine, text

# إعداد الصفحة
st.set_page_config(page_title="Gold Meter 2026", layout="wide", page_icon="🏅")

def get_engine():
    db = st.secrets["postgres"]
    # تنظيف كلمة المرور من أي رموز خاصة قد تسبب خطأ DSN
    password = urllib.parse.quote_plus(str(db["password"]))
    url = f"postgresql://{db['user']}:{password}@{db['host']}:{db['port']}/{db['database']}"
    return create_engine(url, connect_args={"sslmode": "require"})

def main():
    st.title("🏅 Gold Meter - لوحة تحليل الذهب المتكاملة")
    
    # جلب أسعار حية
    try:
        with urllib.request.urlopen("https://api.gold-api.com/price/XAU", timeout=5) as r:
            gold_oz = float(json.load(r)['price'])
        with urllib.request.urlopen("https://open.er-api.com/v6/latest/USD", timeout=5) as r:
            usd_egp = float(json.load(r)['rates']['EGP'])
    except:
        gold_oz, usd_egp = 2330.0, 49.22

    # حساب العيارات
    ounce_to_gram = 31.1035
    g24 = (gold_oz * usd_egp) / ounce_to_gram
    g21 = g24 * (21/24)
    g18 = g24 * (18/24)

    # عرض الأسعار
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("أوقية عالمي", f"${gold_oz:,.2f}")
    c2.metric("جرام 24", f"{g24:,.2f} ج.م")
    c3.metric("جرام 21", f"{g21:,.2f} ج.م")
    c4.metric("جرام 18", f"{g18:,.2f} ج.م")
    
    st.divider()
    
    tab1, tab2, tab3 = st.tabs(["📊 التحليل", "📰 الأخبار", "🔔 التنبيهات"])
    
    with tab1:
        st.line_chart(yf.Ticker("GC=F").history(period="1mo")['Close'])
        
    with tab2:
        feed = feedparser.parse("https://www.cnbcarabia.com/rss")
        for entry in feed.entries[:8]:
            st.markdown(f"🔹 [{entry.title}]({entry.link})")
            
    with tab3:
        with st.form("alert_form"):
            name = st.text_input("الاسم")
            tg_id = st.text_input("Telegram ID")
            h = st.number_input("هدف البيع", value=g21 + 100)
            l = st.number_input("هدف الشراء", value=g21 - 100)
            if st.form_submit_button("حفظ الإعدادات"):
                try:
                    with get_engine().connect() as conn:
                        conn.execute(text("INSERT INTO users (username, tg_id, high, low) VALUES (:n, :t, :h, :l) ON CONFLICT(tg_id) DO UPDATE SET high=:h, low=:l"), {"n": name, "t": tg_id, "h": h, "l": l})
                        conn.commit()
                    st.success("تم الحفظ!")
                except Exception as e: st.error(f"خطأ: {e}")

if __name__ == "__main__": main()
