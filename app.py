import streamlit as st
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import pandas as pd
import yfinance as yf
import feedparser
import urllib.request
import json

st.set_page_config(page_title="Gold Meter 2026", layout="wide")

# إعداد Google Sheets
scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
# ضع ملف الـ JSON الخاص بـ Google Service Account في المستودع باسم creds.json
creds = ServiceAccountCredentials.from_json_keyfile_name('creds.json', scope)
client = gspread.authorize(creds)
sheet = client.open("GoldMeterDB").sheet1

def main():
    st.title("🏅 Gold Meter - لوحة تحليل الذهب")
    
    # جلب الأسعار
    gold, usd = 2330.0, 49.22
    try:
        with urllib.request.urlopen("https://api.gold-api.com/price/XAU", timeout=5) as r: gold = float(json.load(r)['price'])
        with urllib.request.urlopen("https://open.er-api.com/v6/latest/USD", timeout=5) as r: usd = float(json.load(r)['rates']['EGP'])
    except: pass
    
    gram21 = ((gold * usd) / 31.1035) * (21/24)
    st.metric("جرام 21", f"{gram21:,.2f} ج.م")

    with st.form("alert_form"):
        n, t, h, l = st.text_input("الاسم"), st.text_input("ID"), st.number_input("هدف البيع"), st.number_input("هدف الشراء")
        if st.form_submit_button("حفظ"):
            sheet.append_row([n, t, str(h), str(l)])
            st.success("تم الحفظ في Google Sheets!")

if __name__ == "__main__": main()
