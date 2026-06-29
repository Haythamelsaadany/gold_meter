import streamlit as st
import sqlite3
import pandas as pd
import yfinance as yf
import feedparser
import json
import urllib.request

st.set_page_config(page_title="Gold Meter 2026", layout="wide", page_icon="🏅")

# تهيئة قاعدة البيانات المحلية (ملف واحد)
def init_db():
    conn = sqlite3.connect('gold_data.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                  username TEXT, tg_id TEXT UNIQUE, high REAL, low REAL)''')
    conn.commit()
    conn.close()

def main():
    init_db()
    st.title("🏅 Gold Meter - لوحة تحليل الذهب المتكاملة")
    
    # جلب أسعار حية
    try:
        with urllib.request.urlopen("https://api.gold-api.com/price/XAU", timeout=5) as r: gold = float(json.load(r)['price'])
        with urllib.request.urlopen("https://open.er-api.com/v6/latest/USD", timeout=5) as r: usd = float(json.load(r)['rates']['EGP'])
    except: gold, usd = 2330.0, 49.22

    g24 = (gold * usd) / 31.1035
    c1, c2, c3 = st.columns(3)
    c1.metric("أوقية", f"${gold:,.2f}")
    c2.metric("دولار", f"{usd:.2f} ج.م")
    c3.metric("جرام 21", f"{(g24 * (21/24)):,.2f} ج.م")
    
    st.divider()
    t1, t2, t3 = st.tabs(["📊 التحليل", "📰 الأخبار", "🔔 التنبيهات"])
    with t1: st.line_chart(yf.Ticker("GC=F").history(period="1mo")['Close'])
    with t2:
        for entry in feedparser.parse("https://www.cnbcarabia.com/rss").entries[:8]:
            st.markdown(f"🔹 [{entry.title}]({entry.link})")
    with t3:
        with st.form("alert_form"):
            n = st.text_input("الاسم")
            t = st.text_input("Telegram ID")
            h = st.number_input("هدف البيع", value=6000.0)
            l = st.number_input("هدف الشراء", value=5000.0)
            if st.form_submit_button("حفظ"):
                conn = sqlite3.connect('gold_data.db')
                c = conn.cursor()
                try:
                    c.execute("INSERT OR REPLACE INTO users (username, tg_id, high, low) VALUES (?,?,?,?)", (n, t, h, l))
                    conn.commit()
                    st.success("تم الحفظ في قاعدة البيانات المحلية!")
                except Exception as e: st.error(f"خطأ: {e}")
                finally: conn.close()

if __name__ == "__main__": main()
