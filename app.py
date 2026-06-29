import os
import time
import threading
import sqlite3
import json
import urllib.request
import urllib.parse
from datetime import datetime
import streamlit as st
import pandas as pd
import yfinance as yf

# ===== الإعدادات الثابتة =====
TELEGRAM_BOT_TOKEN = "8813434919:AAHytB4BlyZ_NgwSvprzpEXBrNUXhLPdGYk"
OUNCE_TO_GRAM = 31.1034768
DB_FILE = "users_gold_alerts.db"

# قفل أمان على مستوى السيرفر بالكامل لمنع تكرار الـ Threads نهائياً عند عمل Refresh
if not hasattr(st, "_scheduler_initialized"):
    st._scheduler_initialized = False

# ===== 1. إدارة قاعدة البيانات المحدثة وعلاج خطأ العمود المفقود =====
def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    # إنشاء الجدول الأساسي إن لم يكن موجوداً
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT,
            phone TEXT,
            telegram_id TEXT UNIQUE,
            high_target REAL,
            low_target REAL,
            last_alerted_high TEXT,
            last_alerted_low TEXT,
            alert_enabled INTEGER DEFAULT 1
        )
    ''')
    conn.commit()
    
    # حل مشكلة الصورة الأخيرة: التحقق من وجود عمود alert_enabled وإضافته فوراً لو مفقود
    try:
        cursor.execute("SELECT alert_enabled FROM users LIMIT 1")
    except sqlite3.OperationalError:
        cursor.execute("ALTER TABLE users ADD COLUMN alert_enabled INTEGER DEFAULT 1")
        conn.commit()
        print("💡 تم إضافة عمود alert_enabled المفقود بنجاح لواجهة الداتابيز")
        
    conn.close()

def register_or_update_user(username, phone, tg_id, high, low):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    try:
        # استخدام دالة INSERT OR REPLACE أو ON CONFLICT القياسية لضمان الاستقرار التام
        cursor.execute('''
            INSERT INTO users (username, phone, telegram_id, high_target, low_target, last_alerted_high, last_alerted_low, alert_enabled)
            VALUES (?, ?, ?, ?, ?, NULL, NULL, 1)
            ON CONFLICT(telegram_id) DO UPDATE SET
                username=excluded.username,
                phone=excluded.phone,
                high_target=excluded.high_target,
                low_target=excluded.low_target,
                last_alerted_high=NULL,
                last_alerted_low=NULL,
                alert_enabled=1
        ''', (username, phone, tg_id, float(high), float(low)))
        conn.commit()
        return True
    except Exception as e:
        st.error(f"خطأ في حفظ البيانات في الجدول: {e}")
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

def reset_all_alerts():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET last_alerted_high=NULL, last_alerted_low=NULL")
    conn.commit()
    conn.close()

# ===== 2. جلب البيانات الاستقراري عالي الدقة =====
@st.cache_data(ttl=15)
def fetch_live_gold_data():
    usd_price = 0.0
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
            usd_price = 2330.0

    usd_egp = 49.22 
    try:
        with urllib.request.urlopen("https://open.er-api.com/v6/latest/USD", timeout=3) as r:
            data = json.loads(r.read().decode('utf-8'))
            rate = float(data['rates']['EGP'])
            if 45.0 <= rate <= 52.0:
                usd_egp = rate
    except:
        usd_egp = 49.22

    ounce_egp = usd_price * usd_egp
    gram_24 = ounce_egp / OUNCE_TO_GRAM
    
    carat_prices = {
        24: gram_24,
        22: gram_24 * (22.0 / 24.0),
        21: gram_24 * (21.0 / 24.0),
        18: gram_24 * (18.0 / 24.0)
    }
    return usd_price, usd_egp, carat_prices

# ===== 3. محرك الفحص والإرسال الصارم للفترات اللحظية =====
def send_tg_message(tg_id, text):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = urllib.parse.urlencode({"chat_id": tg_id, "text": text}).encode("utf-8")
        req = urllib.request.Request(url, data=payload)
        with urllib.request.urlopen(req, timeout=5) as r:
            return True
    except:
        return False

def check_and_send_alerts():
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT id, username, telegram_id, high_target, low_target, last_alerted_high, last_alerted_low FROM users WHERE alert_enabled = 1")
        users = cursor.fetchall()
        conn.close()
        
        if not users: return "لا يوجد مستخدمين نشطين حالياً"
        
        _, _, carat_prices = fetch_live_gold_data()
        price_21 = round(float(carat_prices.get(21, 0)), 2)
        today_str = datetime.now().strftime('%Y-%m-%d')
        
        for user in users:
            u_id, name, tg_id, high, low, last_high, last_low = user
            if not tg_id or high is None or low is None: continue
            
            val_high = float(high)
            val_low = float(low)
            
            # شرط رياضي صارم مبني على الداتابيز يمنع العشوائية تماماً
            if price_21 >= val_high and last_high != today_str:
                msg = f"🚀 تنبيه اختراق الهدف الأعلى:\nيا {name}، سعر جرام عيار 21 الحالي وصل {price_21:,.2f} ج.م متخطياً هدفك المحدد ({val_high:,.0f} ج.م)."
                if send_tg_message(tg_id, msg):
                    conn = sqlite3.connect(DB_FILE)
                    cursor = conn.cursor()
                    cursor.execute("UPDATE users SET last_alerted_high=? WHERE id=?", (today_str, u_id))
                    conn.commit()
                    conn.close()
                    
            if price_21 <= val_low and last_low != today_str:
                msg = f"🔻 تنبيه كسر القاع الأدنى:\nيا {name}، سعر جرام عيار 21 هبط الآن إلى {price_21:,.2f} ج.م متخطياً هدف الشراء عندك ({val_low:,.0f} ج.م)."
                if send_tg_message(tg_id, msg):
                    conn = sqlite3.connect(DB_FILE)
                    cursor = conn.cursor()
                    cursor.execute("UPDATE users SET last_alerted_low=? WHERE id=?", (today_str, u_id))
                    conn.commit()
                    conn.close()
        return f"تم الفحص بنجاح. السعر الحالي لعيار 21 هو: {price_21} ج.م"
    except Exception as e:
        return f"خطأ في محرك الفحص الخلفي: {e}"

# ===== 4. الحماية القصوى للمجدول ومنع تكرار الـ Threads العشوائية =====
def start_stable_scheduler():
    if not st._scheduler_initialized:
        # فحص وجود أي Thread قديم يحمل نفس الاسم لمنع تراكم العمليات في الذاكرة
        current_threads = [t.name for t in threading.enumerate()]
        if "GoldSchedulerThread" not in current_threads:
            def scheduler_loop():
                while True:
                    try:
                        check_and_send_alerts()
                    except:
                        pass
                    time.sleep(30) # فحص مستقر وآمن كل 30 ثانية
            
            thread = threading.Thread(target=scheduler_loop, name="GoldSchedulerThread", daemon=True)
            thread.start()
        st._scheduler_initialized = True

# تهيئة قاعدة البيانات وتشغيل الرادار الأحادي المستقر
init_db()
start_stable_scheduler()

# ===== 5. واجهة المستخدم الرسومية الفاخرة =====
st.set_page_config(page_title="🏅 Gold Meter - النظام الذكي المطور", layout="wide")

# تصحيح الـ CSS ومنع انهيار التنسيق النصي الخاطئ المعروض في الصور
st.markdown("""
    <style>
    .main { background-color: #06060c; color: white; }
    .price-card { background-color: #0f0f1e; padding: 20px; border-radius: 12px; border: 1px solid #1e1e38; text-align: center; margin-bottom: 15px; }
    div.stButton > button:first-child { background-color: #e1b12c; color: black; font-weight: bold; width: 100%; border-radius: 8px; border: none; }
    </style>
""", unsafe_allow_html=True)

st.title("🏅 Gold Meter - لوحة تحليل الذهب التفاعلية للمستثمرين")
st.write("رصد لحظي للبورصة العالمية والسوق المحلي مع نظام تنبيهات محمي ومصلح بالكامل.")

usd_price, usd_egp, carat_prices = fetch_live_gold_data()
current_price = carat_prices[21]
ounce_local_fair = usd_price * usd_egp

# عرض مؤشرات الأسعار بشكل آمن تماماً يمنع الـ Syntax Error
col1, col2, col3 = st.columns(3)
with col1:
    st.markdown(f"<div class='price-card'><h4 style='color:#00d4ff;'>🌍 أوقية الذهب عالمياً</h4><h2>${usd_price:,.2f}</h2></div>", unsafe_allow_html=True)
with col2:
    st.markdown(f"<div class='price-card'><h4 style='color:#fdcb6e;'>💵 سعر الدولار بالبنوك</h4><h2>{usd_egp:.2f} ج.م</h2></div>", unsafe_allow_html=True)
with col3:
    st.markdown(f"<div class='price-card'><h4 style='color:#00b894;'>🏅 الأوقية محلياً (عادلة)</h4><h2>{ounce_local_fair:,.2f} ج.م</h2></div>", unsafe_allow_html=True)

st.write("---")

# عرض تفاصيل الأعيرة بمقاييس Streamlit القياسية الآمنة
c24, c22, c21, c18 = st.columns(4)
c24.metric("عيار 24 (الحقيقي العادل)", f"{carat_prices[24]:,.2f} ج.م")
c22.metric("عيار 22", f"{carat_prices[22]:,.2f} ج.م")
c21.metric("عيار 21 (المستهدف الحالي)", f"{current_price:,.2f} ج.م")
c18.metric("عيار 18", f"{carat_prices[18]:,.2f} ج.م")

st.write("---")

# لوحة تحكم وإدخال الأهداف والتنبيهات المحدثة
st.markdown("### 🔔 نظام تفعيل التنبيهات الفورية الذكي")
reg_col1, reg_col2 = st.columns(2)

if "u_tg" not in st.session_state: st.session_state["u_tg"] = ""
if "u_name" not in st.session_state: st.session_state["u_name"] = ""
if "u_phone" not in st.session_state: st.session_state["u_phone"] = ""
if "target_high" not in st.session_state: st.session_state["target_high"] = 6000.0
if "target_low" not in st.session_state: st.session_state["target_low"] = 5000.0

with reg_col1:
    u_tg = st.text_input("🆔 معرف التليجرام الخاص بك (Chat ID):", value=st.session_state["u_tg"])
    if u_tg and u_tg != st.session_state["u_tg"]:
        user_data = get_user_by_tg(u_tg)
        if user_data:
            st.session_state["u_tg"] = u_tg
            st.session_state["u_name"] = user_data[0]
            st.session_state["u_phone"] = user_data[1]
            st.session_state["target_high"] = float(user_data[2])
            st.session_state["target_low"] = float(user_data[3])
            st.rerun()

    u_name = st.text_input("👤 الاسم الكريم:", value=st.session_state["u_name"])
    u_phone = st.text_input("📱 رقم الموبايل (مرفقاً بكود الدولة):", value=st.session_state["u_phone"])

with reg_col2:
    target_high = st.number_input("🚀 تبهني لو عيار 21 رفع وكسر السعر ده (جني أرباح):", value=float(st.session_state["target_high"]), step=50.0)
    target_low = st.number_input("🔻 تبهني لو عيار 21 نزل وكسر السعر ده (دعم شراء):", value=float(st.session_state["target_low"]), step=50.0)
    
    st.write("")
    col_btn1, col_btn2 = st.columns(2)
    with col_btn1:
        # زر الحفظ مع إرجاع البلالين والاحتفال الجميل! 🎉🎈
        if st.button("💾 تفعيل الاشتراك وحفظ الإعدادات"):
            if u_name and u_tg:
                if register_or_update_user(u_name, u_phone, u_tg, target_high, target_low):
                    st.session_state["u_tg"] = u_tg
                    st.session_state["u_name"] = u_name
                    st.session_state["u_phone"] = u_phone
                    st.session_state["target_high"] = float(target_high)
                    st.session_state["target_low"] = float(target_low)
                    
                    # البلالين والاحتفال اللذيذ عادوا للعمل بقوة هنا!
                    st.balloons()
                    st.success(f"🎉 تم تفعيل اشتراكك بنجاح يا هندسة! أهدافك الحالية الحالية هي {target_low} و {target_high}.")
                    time.sleep(1)
                    st.rerun()
            else:
                st.error("⚠️ يرجى كتابة الاسم ومعرف التليجرام أولاً لحفظ البيانات بشكل سليم!")
                
    with col_btn2:
        if st.button("🔄 إعادة تعيين وتصفير التنبيهات"):
            reset_all_alerts()
            st.warning("🔄 تم تصفير سجل الإرسال اليومي للتنبيهات لجميع المستخدمين بنجاح.")

# استعراض البيانات المسجلة بالكامل للتأكد من نجاح الإدخال
st.write("---")
if st.button("📋 استعراض جدول مراقبة الأهداف النشطة בסيرفر"):
    conn = sqlite3.connect(DB_FILE)
    df = pd.read_sql_query("SELECT username AS [الاسم], telegram_id AS [التليجرام], high_target AS [الحد الأعلى], low_target AS [الحد الأدنى], alert_enabled AS [حالة التفعيل] FROM users", conn)
    conn.close()
    if not df.empty:
        st.dataframe(df, use_container_width=True)
    else:
        st.info("لا توجد بيانات مستخدمين مسجلة حتى الآن.")
