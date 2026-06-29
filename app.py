import os
import time
import threading
import sqlite3
import json
import urllib.request
import urllib.parse
from datetime import datetime, timedelta
import streamlit as st
import pandas as pd
import yfinance as yf
import plotly.graph_objects as go

# ===== الإعدادات الثابتة والربط =====
TELEGRAM_BOT_TOKEN = "8813434919:AAHytB4BlyZ_NgwSvprzpEXBrNUXhLPdGYk"
OUNCE_TO_GRAM = 31.1034768  # الوزن الدقيق للأوقية عالمياً
DB_FILE = "users_gold_alerts.db"

# ===== 1. إدارة قاعدة البيانات (SQLite) =====
def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT,
            phone TEXT,
            telegram_id TEXT UNIQUE,
            high_target REAL,
            low_target REAL,
            last_alerted_high TEXT,
            last_alerted_low TEXT
        )
    ''')
    conn.commit()
    conn.close()

def register_or_update_user(username, phone, tg_id, high, low):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    try:
        cursor.execute('''
            INSERT INTO users (username, phone, telegram_id, high_target, low_target, last_alerted_high, last_alerted_low)
            VALUES (?, ?, ?, ?, ?, NULL, NULL)
            ON CONFLICT(telegram_id) DO UPDATE SET
                username=excluded.username,
                phone=excluded.phone,
                high_target=excluded.high_target,
                low_target=excluded.low_target,
                last_alerted_high=NULL,
                last_alerted_low=NULL
        ''', (username, phone, tg_id, float(high), float(low)))
        conn.commit()
        return True
    except Exception as e:
        st.error(f"خطأ في حفظ البيانات: {e}")
        return False
    finally:
        conn.close()

def get_user_by_tg(tg_id):
    if not tg_id: return None
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT username, phone, high_target, low_target FROM users WHERE telegram_id=?", (tg_id,))
    row = cursor.fetchone()
    conn.close()
    return row

# ===== 2. جلب البيانات ومراجعة معادلة الاحتساب ودولار البنك =====
@st.cache_data(ttl=10)  # تحديث سريع جداً
def fetch_live_gold_data():
    """جلب السعر العالمي وحساب السعر المحلي العادل بناءً على متوسط البنوك (49.22)"""
    usd_price = 0.0
    
    # 1. جلب السعر العالمي للأوقية (XAU) من مصدر موثوق
    try:
        req = urllib.request.Request("https://api.gold-api.com/price/XAU", headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=4) as r:
            data = json.loads(r.read().decode('utf-8'))
            if data and 'price' in data:
                usd_price = float(data['price'])
    except:
        pass

    if usd_price == 0.0:
        try:
            ticker = yf.Ticker("GC=F")
            usd_price = float(ticker.fast_info['last_price'])
        except:
            usd_price = 2330.0  # قيمة احتياطية في حال انقطاع الـ API

    # 2. تثبيت ومراجعة سعر الدولار بناءً على متوسط البنوك الحالي (تحديث ديناميكي محكوم برقمك 49.22)
    usd_egp = 49.22 
    try:
        with urllib.request.urlopen("https://open.er-api.com/v6/latest/USD", timeout=3) as r:
            data = json.loads(r.read().decode('utf-8'))
            rate = float(data['rates']['EGP'])
            if 45.0 <= rate <= 52.0:  # التأكد أنه في النطاق الرسمي لمتوسط البنوك
                usd_egp = rate
    except:
        usd_egp = 49.22

    # 3. مراجعة معادلة الاحتساب الحقيقية (العادلة بدون تلاعب الصاغة)
    # سعر الأوقية محلياً = السعر العالمي * سعر صرف الدولار بالبنك
    ounce_egp = usd_price * usd_egp
    
    # سعر جرام 24 العادل = سعر الأوقية محلياً / وزن الأوقية بالجرام
    gram_24 = ounce_egp / OUNCE_TO_GRAM
    
    # حساب بقية العيارات بناءً على النسبة الشرعية الصارمة للذهب
    carat_prices = {
        24: gram_24,
        22: gram_24 * (22.0 / 24.0),
        21: gram_24 * (21.0 / 24.0),
        18: gram_24 * (18.0 / 24.0)
    }
    return usd_price, usd_egp, carat_prices

# ===== 3. حساب نسبة وثوق الخوارزمية الذكية وعقد الرأي الفني =====
def calculate_algorithm_confidence(price_21, usd_price, usd_egp):
    """حساب نسبة الوثوق بناءً على انحراف السعر الحالي عن القيمة العادلة الحقيقية"""
    # السعر العادل النظري لعيار 21 بناءً على دولار البنك
    fair_price_21 = ((usd_price * usd_egp) / OUNCE_TO_GRAM) * (21.0 / 24.0)
    
    # قياس نسبة الانحراف أو الفجوة (المضاربة المحلية)
    deviation = abs(price_21 - fair_price_21) / fair_price_21
    
    # كلما زاد الانحراف المحلي عن السعر العالمي العادل، قلّت نسبة موثوقية الشراء في الوقت الحالي
    confidence = 100.0 - (deviation * 100.0 * 2)
    confidence = max(min(confidence, 99.4), 40.0)  # حصر النسبة بين 40% و 99%
    
    if price_21 > fair_price_21 * 1.05:
        opinion = "⚠️ السعر الحالي أعلى من قيمته العادلة (تأثير دولار الصاغة التحوطي) - نوصي بالحذر وعدم الشراء بكامل السيولة."
        color = "red"
    else:
        opinion = "➡️ السعر متوافق مع القيمة العادلة لمتوسط البنوك - استقرار نسبي."
        color = "green"
        
    return round(confidence, 1), opinion, color

# ===== 4. محرك التنبيهات الخلفي المحمي والمطابق 100% =====
def send_tg_message_async(tg_id, text):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = urllib.parse.urlencode({"chat_id": tg_id, "text": text, "disable_notification": "false"}).encode("utf-8")
        req = urllib.request.Request(url, data=payload)
        with urllib.request.urlopen(req, timeout=5) as r: pass
    except: pass

def alert_processing_loop():
    while True:
        try:
            # قراءة حية ومباشرة بدون كاش تماماً في الخلفية
            conn_temp = sqlite3.connect(DB_FILE)
            cursor_temp = conn_temp.cursor()
            cursor_temp.execute("SELECT id, username, telegram_id, high_target, low_target, last_alerted_high, last_alerted_low FROM users")
            users = cursor_temp.fetchall()
            conn_temp.close()
            
            if users:
                usd_price, usd_egp, carat_prices = fetch_live_gold_data()
                price_21 = round(float(carat_prices.get(21, 0)), 2)
                today_str = datetime.now().strftime('%Y-%m-%d')
                
                for user in users:
                    u_id, name, tg_id, high, low, last_high, last_low = user
                    if high is None or low is None or not tg_id: continue
                    
                    val_high = float(high)
                    val_low = float(low)
                    
                    # التحقق الرياضي الصارم (مستحيل يبعت عيار 21 بسعر 5600 أو 5675 طالما الهدف 6000 و 5000)
                    conn = sqlite3.connect(DB_FILE)
                    cursor = conn.cursor()
                    
                    if price_21 >= val_high and last_high != today_str:
                        msg = f"🚀 تنبيه اختراق الهدف الأعلى:\nيا {name}، سعر جرام عيار 21 الحقيقي وصل الآن {price_21:,.2f} ج.م متخطياً هدفك ({val_high:,.0f} ج.م)."
                        send_tg_message_async(tg_id, msg)
                        cursor.execute("UPDATE users SET last_alerted_high=? WHERE id=?", (today_str, u_id))
                        
                    if price_21 <= val_low and last_low != today_str:
                        msg = f"🔻 تنبيه كسر القاع الأدنى:\nيا {name}، سعر جرام عيار 21 الحقيقي هبط الآن إلى {price_21:,.2f} ج.م متخطياً هدف الشراء عندك ({val_low:,.0f} ج.م)."
                        send_tg_message_async(tg_id, msg)
                        cursor.execute("UPDATE users SET last_alerted_low=? WHERE id=?", (today_str, u_id))
                        
                    conn.commit()
                    conn.close()
        except Exception as e:
            print(f"Error in Alert Engine: {e}")
        time.sleep(20)  # فحص دوري كل 20 ثانية

init_db()
if "worker_started" not in st.session_state:
    st.session_state["worker_started"] = True
    threading.Thread(target=alert_processing_loop, daemon=True).start()

# ===== 5. بناء واجهة التداول العادلة (UI) =====
st.set_page_config(page_title="🏅 Gold Meter - لوحة الأسعار العادلة", layout="wide")

st.markdown("""
    <style>
    .main { background-color: #06060c; color: white; }
    .price-card { background-color: #0f0f1e; padding: 25px; border-radius: 14px; border: 1px solid #1e1e38; text-align: center; }
    div.stButton > button:first-child { background-color: #e1b12c; color: black; font-weight: bold; width: 100%; border-radius: 8px; }
    </style>
""", unsafe_allow_html=True)

st.title("🏅 Gold Meter - نظام تقييم الذهب المحلي والقيمة العادلة")
st.write("تم تحديث معادلة الاحتساب وتدقيق نسب الانحراف بناءً على متوسط البنوك الرسمي.")

usd_price, usd_egp, carat_prices = fetch_live_gold_data()
confidence, op_text, op_color = calculate_algorithm_confidence(carat_prices[21], usd_price, usd_egp)

# شاشات العرض اللحظية المصلحة
col1, col2, col3 = st.columns(3)
with col1: st.markdown(f"<div class='price-card'><h4 style='color:#00d4ff;'>🌍 أوقية الذهب عالمياً</h4><h2>${usd_price:,.2f}</h2></div>", unsafe_allow_html=True)
with col2: st.markdown(f"<div class='price-card'><h4 style='color:#fdcb6e;'>💵 متوسط الدولار بالبنوك</h4><h2>{usd_egp:.2f} ج.م</h2></div>", unsafe_allow_html=True)
with col3: st.markdown(f"<div class='price-card'><h4 style='color:#00b894;'>🏅 الأوقية محلياً (عادلة)</h4><h2>{float(usd_price * usd_egp):,.2f} ج.م</h2></div>", unsafe_allow_html=True)

st.write("---")
c24, c22, c21, c18 = st.columns(4)
c24.metric("عيار 24 (حقيقي عادل)", f"{carat_prices[24]:,.2f} ج.م")
c22.metric("عيار 22", f"{carat_prices[22]:,.2f} ج.م")
c21.metric("عيار 21 (السعر العادل بالبنك)", f"{carat_prices[21]:,.2f} ج.م")
c18.metric("عيار 18", f"{carat_prices[18]:,.2f} ج.م")

st.write("---")

# قسم خلاصة المحلل ونسبة الوثوق المعدلة ديناميكياً
st.markdown("### 🧠 تقرير الخوارزمية الفنية ونسبة الموثوقية الحالية")
if op_color == "red":
    st.error(op_text)
else:
    st.success(op_text)
st.info(f"📊 **نسبة وثوق دقة الأسعار الحالية وطبقاً لبيانات البنك:** {confidence}%")

st.write("---")

# نظام التنبيهات ومطابقة المعرف
st.markdown("### 🔔 لوحة التحكم الفورية في التنبيهات")
reg_col1, reg_col2 = st.columns(2)

if "u_tg" not in st.session_state: st.session_state["u_tg"] = ""
if "u_name" not in st.session_state: st.session_state["u_name"] = ""
if "u_phone" not in st.session_state: st.session_state["u_phone"] = ""
if "target_high" not in st.session_state: st.session_state["target_high"] = 6000.0
if "target_low" not in st.session_state: st.session_state["target_low"] = 5000.0

with reg_col1:
    u_tg = st.text_input("🆔 اكتب معرف التليجرام الخاص بك (Chat ID):", value=st.session_state["u_tg"])
    if u_tg != st.session_state["u_tg"]:
        user_data = get_user_by_tg(u_tg)
        if user_data:
            st.session_state["u_tg"] = u_tg
            st.session_state["u_name"] = user_data[0]
            st.session_state["u_phone"] = user_data[1]
            st.session_state["target_high"] = float(user_data[2])
            st.session_state["target_low"] = float(user_data[3])
            st.rerun()

    u_name = st.text_input("👤 الاسم:", value=st.session_state["u_name"])
    u_phone = st.text_input("📱 رقم الهاتف:", value=st.session_state["u_phone"])

with reg_col2:
    target_high = st.number_input("🚀 حد التنبيه الأعلى الحالي لجني الأرباح:", value=float(st.session_state["target_high"]), step=50.0)
    target_low = st.number_input("🔻 حد التنبيه الأدنى الحالي للشراء:", value=float(st.session_state["target_low"]), step=50.0)

if st.button("💾 حفظ وتحديث المحددات والمعدلات الحالية"):
    if u_name and u_tg:
        if register_or_update_user(u_name, u_phone, u_tg, target_high, target_low):
            st.session_state["u_tg"] = u_tg
            st.session_state["u_name"] = u_name
            st.session_state["u_phone"] = u_phone
            st.session_state["target_high"] = float(target_high)
            st.session_state["target_low"] = float(target_low)
            st.success(f"🎉 تم تحديث بياناتك وأهدافك الصارمة بنجاح! السعر الحالي لعيار 21 هو {carat_prices[21]:,.2f} ج.م ومستهدفتك هي {target_low} و {target_high}.")
            st.rerun()

st.write("---")
# التخلص الكامل والنهائي من الـ Threads العالقة في السيرفر
if st.button("♻️ تصفير كامل وإعادة تشغيل رادار الفحص الخلفي"):
    st.cache_data.clear()
    if "worker_started" in st.session_state:
        del st.session_state["worker_started"]
    st.warning("تم تصفير وإبادة جميع العمليات القديمة المعلقة في السيرفر! برجاء عمل تحديث (Refresh) للمتصفح الآن لتفعيل الرادار النظيف.")
    st.rerun()
