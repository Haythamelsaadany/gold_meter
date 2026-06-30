import streamlit as st
import sqlite3
import pandas as pd
import yfinance as yf
import feedparser
import json
import urllib.request

st.set_page_config(page_title="Gold Meter Pro 2026", layout="wide", page_icon="📈")

# 1. تهيئة قاعدة البيانات المحلية
def init_db():
    conn = sqlite3.connect('gold_data.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, tg_id TEXT UNIQUE, high REAL, low REAL)''')
    conn.commit()
    conn.close()

# 2. حساب الأسعار
def get_gold_prices():
    try:
        with urllib.request.urlopen("https://api.gold-api.com/price/XAU", timeout=5) as r: gold = float(json.load(r)['price'])
        with urllib.request.urlopen("https://open.er-api.com/v6/latest/USD", timeout=5) as r: usd = float(json.load(r)['rates']['EGP'])
    except: gold, usd = 2330.0, 49.22
    
    g24 = (gold * usd) / 31.1035
    return {
        "24": g24,
        "22": g24 * (22/24),
        "21": g24 * (21/24),
        "18": g24 * (18/24)
    }, g24

def main():
    init_db()
    st.title("📈 Gold Meter Pro - لوحة تحليل الذهب المتكاملة")
    
    prices, g24 = get_gold_prices()
    
    # عرض العيارات
    cols = st.columns(4)
    for i, (karat, price) in enumerate(prices.items()):
        cols[i].metric(f"عيار {karat}", f"{price:,.2f} ج.م")
    
    st.divider()
    
    # قسم التحليل والتوصيات
    t1, t2, t3 = st.tabs(["📊 التحليل الفني", "💡 التوصيات", "🔔 إعداد التنبيهات"])
    
    with t1:
        st.line_chart(yf.Ticker("GC=F").history(period="1mo")['Close'])
        
    with t2:
        st.subheader("توصيات التداول اليومية")
        if prices["21"] > 5500:
            st.warning("⚠️ السعر مرتفع: يُنصح بالانتظار قبل الشراء.")
        else:
            st.success("✅ فرصة شراء جيدة: السعر في مستويات داعمة.")
        st.info("نصيحة: تابع الأخبار العالمية الملحقة لضمان دقة قرارك.")
        
    with t3:
        with st.form("alert_form"):
            n, t, h, l = st.text_input("الاسم"), st.text_input("ID"), st.number_input("سعر البيع", value=6000.0), st.number_input("سعر الشراء", value=5000.0)
            if st.form_submit_button("حفظ التنبيه"):
                conn = sqlite3.connect('gold_data.db')
                conn.execute("INSERT OR REPLACE INTO users (username, tg_id, high, low) VALUES (?,?,?,?)", (n, t, h, l))
                conn.commit()
                conn.close()
                st.success("تم تفعيل التنبيه!")

    # قسم الأخبار
    with st.expander("📰 أحدث الأخبار العالمية"):
        for entry in feedparser.parse("https://www.cnbcarabia.com/rss").entries[:5]:
            st.write(f"🔹 {entry.title}")

if __name__ == "__main__": main()
