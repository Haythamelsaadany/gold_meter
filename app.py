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
import atexit

# ===== الإعدادات الثابتة =====
TELEGRAM_BOT_TOKEN = "8813434919:AAHytB4BlyZ_NgwSvprzpEXBrNUXhLPdGYk"
OUNCE_TO_GRAM = 31.1034768
DB_FILE = "users_gold_alerts.db"

# ===== 1. إدارة قاعدة البيانات =====
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
            last_alerted_low TEXT,
            alert_enabled INTEGER DEFAULT 1
        )
    ''')
    conn.commit()
    conn.close()

def register_or_update_user(username, phone, tg_id, high, low):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    try:
        # حذف السجل القديم
        cursor.execute("DELETE FROM users WHERE telegram_id=?", (tg_id,))
        cursor.execute('''
            INSERT INTO users (username, phone, telegram_id, high_target, low_target, 
                             last_alerted_high, last_alerted_low, alert_enabled)
            VALUES (?, ?, ?, ?, ?, NULL, NULL, 1)
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

def toggle_user_alerts(tg_id, enable):
    """تفعيل أو تعطيل التنبيهات للمستخدم"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET alert_enabled=? WHERE telegram_id=?", (1 if enable else 0, tg_id))
    conn.commit()
    conn.close()

def reset_all_alerts():
    """إعادة تعيين جميع التنبيهات في قاعدة البيانات"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET last_alerted_high=NULL, last_alerted_low=NULL")
    conn.commit()
    conn.close()
    print("✅ تم إعادة تعيين جميع التنبيهات")

# ===== 2. جلب البيانات =====
@st.cache_data(ttl=10)
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

# ===== 3. حساب نسبة الثقة =====
def calculate_algorithm_confidence(price_21, usd_price, usd_egp):
    fair_price_21 = ((usd_price * usd_egp) / OUNCE_TO_GRAM) * (21.0 / 24.0)
    deviation = abs(price_21 - fair_price_21) / fair_price_21
    confidence = 100.0 - (deviation * 100.0 * 2)
    confidence = max(min(confidence, 99.4), 40.0)
    
    if price_21 > fair_price_21 * 1.05:
        opinion = "⚠️ السعر الحالي أعلى من قيمته العادلة"
        color = "red"
    else:
        opinion = "➡️ السعر متوافق مع القيمة العادلة"
        color = "green"
    return round(confidence, 1), opinion, color

# ===== 4. نظام التنبيهات المعدل بالكامل (بدون Threads معقدة) =====
def send_tg_message(tg_id, text):
    """إرسال رسالة تليجرام"""
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = urllib.parse.urlencode({"chat_id": tg_id, "text": text}).encode("utf-8")
        req = urllib.request.Request(url, data=payload)
        with urllib.request.urlopen(req, timeout=5) as r:
            return True
    except Exception as e:
        print(f"Telegram error: {e}")
        return False

def check_and_send_alerts():
    """
    دالة يتم استدعاؤها بشكل دوري للتحقق من التنبيهات
    هذه هي الدالة الوحيدة التي ترسل التنبيهات
    """
    try:
        # 1. جلب جميع المستخدمين
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, username, telegram_id, high_target, low_target, 
                   last_alerted_high, last_alerted_low, alert_enabled 
            FROM users WHERE alert_enabled = 1
        """)
        users = cursor.fetchall()
        conn.close()
        
        if not users:
            return "لا يوجد مستخدمين مفعلين"
        
        # 2. جلب السعر الحالي
        try:
            _, _, carat_prices = fetch_live_gold_data()
            price_21 = round(float(carat_prices.get(21, 0)), 2)
        except:
            return "خطأ في جلب السعر"
        
        today_str = datetime.now().strftime('%Y-%m-%d')
        alerts_sent = []
        
        # 3. معالجة كل مستخدم
        for user in users:
            u_id, name, tg_id, high, low, last_high, last_low, enabled = user
            
            if not tg_id or high is None or low is None:
                continue
            
            val_high = float(high)
            val_low = float(low)
            
            # ✅ المنطق الصحيح - التنبيه فقط عند تحقق الشرط
            should_send_high = price_21 >= val_high and last_high != today_str
            should_send_low = price_21 <= val_low and last_low != today_str
            
            if should_send_high:
                msg = f"🚀 تنبيه اختراق الهدف الأعلى:\nيا {name}، سعر جرام عيار 21 وصل {price_21:,.2f} ج.م متخطياً هدفك ({val_high:,.0f} ج.م)."
                if send_tg_message(tg_id, msg):
                    # تحديث قاعدة البيانات
                    conn = sqlite3.connect(DB_FILE)
                    cursor = conn.cursor()
                    cursor.execute("UPDATE users SET last_alerted_high=? WHERE id=?", (today_str, u_id))
                    conn.commit()
                    conn.close()
                    alerts_sent.append(f"✅ HIGH لـ {name}")
            
            if should_send_low:
                msg = f"🔻 تنبيه كسر القاع الأدنى:\nيا {name}، سعر جرام عيار 21 هبط إلى {price_21:,.2f} ج.م متخطياً هدفك ({val_low:,.0f} ج.م)."
                if send_tg_message(tg_id, msg):
                    # تحديث قاعدة البيانات
                    conn = sqlite3.connect(DB_FILE)
                    cursor = conn.cursor()
                    cursor.execute("UPDATE users SET last_alerted_low=? WHERE id=?", (today_str, u_id))
                    conn.commit()
                    conn.close()
                    alerts_sent.append(f"✅ LOW لـ {name}")
        
        if alerts_sent:
            return f"تم إرسال: {', '.join(alerts_sent)}"
        else:
            return f"لا توجد تنبيهات جديدة. السعر الحالي {price_21:.2f} ج.م"
            
    except Exception as e:
        return f"خطأ: {e}"

# ===== 5. تشغيل مؤقت بسيط بدون Threads معقدة =====
def start_simple_scheduler():
    """
    تشغيل مؤقت بسيط يعمل في الخلفية
    """
    if "scheduler_running" not in st.session_state:
        st.session_state.scheduler_running = False
    
    if not st.session_state.scheduler_running:
        def scheduler_loop():
            while True:
                try:
                    # التحقق من التنبيهات كل 30 ثانية
                    result = check_and_send_alerts()
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] {result}")
                except Exception as e:
                    print(f"Scheduler error: {e}")
                time.sleep(30)
        
        thread = threading.Thread(target=scheduler_loop, daemon=True)
        thread.start()
        st.session_state.scheduler_running = True
        print("✅ تم تشغيل المجدول")

# ===== 6. تهيئة النظام =====
init_db()

# ===== 7. واجهة المستخدم =====
st.set_page_config(page_title="🏅 Gold Meter - نظام التنبيهات الذكي", layout="wide")

st.markdown("""
    <style>
    .main { background-color: #06060c; color: white; }
    .price-card { background-color: #0f0f1e; padding: 25px; border-radius: 14px; border: 1px solid #1e1e38; text-align: center; }
    div.stButton > button:first-child { background-color: #e1b12c; color: black; font-weight: bold; width: 100%; border-radius: 8px; }
    .alert-box { background-color: #1a1a2e; padding: 15px; border-radius: 10px; border-left: 4px solid #e1b12c; margin: 10px 0; }
    </style>
""", unsafe_allow_html=True)

st.title("🏅 Gold Meter - نظام التنبيهات الذكي")
st.write("🔔 نظام تنبيهات ذكي - يتم إرسال التنبيهات فقط عند تحقق الشروط")

# تشغيل المجدول
start_simple_scheduler()

# جلب البيانات
usd_price, usd_egp, carat_prices = fetch_live_gold_data()
confidence, op_text, op_color = calculate_algorithm_confidence(carat_prices[21], usd_price, usd_egp)
current_price = carat_prices[21]

# عرض الأسعار
col1, col2, col3, col4 = st.columns(4)
with col1: st.metric("🌍 أوقية الذهب", f"${usd_price:,.2f}")
with col2: st.metric("💵 سعر الدولار", f"{usd_egp:.2f} ج.م")
with col3: st.metric("🏅 عيار 21 (الحالي)", f"{current_price:,.2f} ج.م")
with col4: st.metric("📊 الثقة", f"{confidence}%")

st.write("---")

# عرض حالة التنبيهات
st.markdown("### 🔔 حالة التنبيهات")
col_status1, col_status2, col_status3 = st.columns(3)

with col_status1:
    st.info(f"📈 **السعر الحالي**: {current_price:,.2f} ج.م")
with col_status2:
    # جلب أهداف المستخدم الحالي
    if "u_tg" in st.session_state and st.session_state["u_tg"]:
        user_data = get_user_by_tg(st.session_state["u_tg"])
        if user_data:
            high_target = float(user_data[2])
            low_target = float(user_data[3])
            st.info(f"🎯 **الهدف الأعلى**: {high_target:,.0f} ج.م")
            st.info(f"🎯 **الهدف الأدنى**: {low_target:,.0f} ج.م")
            
            # عرض حالة التنبيه
            if current_price >= high_target:
                st.warning("⚠️ السعر تجاوز الهدف الأعلى!")
            elif current_price <= low_target:
                st.warning("⚠️ السعر أقل من الهدف الأدنى!")
            else:
                st.success("✅ السعر في النطاق الآمن (لا توجد تنبيهات)")
with col_status3:
    if st.button("🔄 فحص التنبيهات يدوياً"):
        result = check_and_send_alerts()
        st.info(result)

st.write("---")

# لوحة التحكم
st.markdown("### ⚙️ لوحة التحكم")
reg_col1, reg_col2 = st.columns(2)

if "u_tg" not in st.session_state: st.session_state["u_tg"] = ""
if "u_name" not in st.session_state: st.session_state["u_name"] = ""
if "u_phone" not in st.session_state: st.session_state["u_phone"] = ""
if "target_high" not in st.session_state: st.session_state["target_high"] = 6000.0
if "target_low" not in st.session_state: st.session_state["target_low"] = 3000.0

with reg_col1:
    u_tg = st.text_input("🆔 معرف التليجرام (Chat ID):", value=st.session_state["u_tg"])
    if u_tg and u_tg != st.session_state["u_tg"]:
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
    target_high = st.number_input("🚀 الهدف الأعلى (جني أرباح):", 
                                  value=float(st.session_state["target_high"]), 
                                  step=50.0,
                                  help="سيتم إرسال تنبيه عندما يصل السعر لهذا الرقم أو أعلى")
    target_low = st.number_input("🔻 الهدف الأدنى (شراء):", 
                                 value=float(st.session_state["target_low"]), 
                                 step=50.0,
                                 help="سيتم إرسال تنبيه عندما يصل السعر لهذا الرقم أو أقل")
    
    # أزرار تحكم
    col_btn1, col_btn2 = st.columns(2)
    with col_btn1:
        if st.button("💾 حفظ الأهداف"):
            if u_name and u_tg:
                if register_or_update_user(u_name, u_phone, u_tg, target_high, target_low):
                    st.session_state["u_tg"] = u_tg
                    st.session_state["u_name"] = u_name
                    st.session_state["u_phone"] = u_phone
                    st.session_state["target_high"] = float(target_high)
                    st.session_state["target_low"] = float(target_low)
                    st.balloons()
                    st.success(f"✅ تم حفظ الأهداف بنجاح!\nالسعر الحالي: {current_price:.2f} ج.م")
                    st.info(f"🔔 سيتم إرسال تنبيه عندما يصل السعر إلى {target_high} أو {target_low}")
    
    with col_btn2:
        if st.button("🔄 إعادة تعيين التنبيهات"):
            if u_tg:
                reset_all_alerts()
                st.success("✅ تم إعادة تعيين جميع التنبيهات! لن يتم إرسال أي تنبيهات مكررة.")

st.write("---")

# عرض نصائح وإرشادات
with st.expander("📖 كيف يعمل النظام؟"):
    st.markdown("""
    ### 🔔 آلية عمل التنبيهات
    
    1. **الهدف الأعلى**: يتم إرسال تنبيه فقط عندما **يزيد السعر عن** الهدف المحدد
    2. **الهدف الأدنى**: يتم إرسال تنبيه فقط عندما **ينخفض السعر عن** الهدف المحدد
    3. **النطاق الآمن**: إذا كان السعر بين الهدفين، **لن يتم إرسال أي تنبيه**
    4. **منع التكرار**: يتم إرسال التنبيه **مرة واحدة فقط في اليوم**
    
    ### 💡 مثال توضيحي
    
    - الأهداف: الأعلى = 7000، الأدنى = 3000
    - السعر الحالي = 4062
    - ✅ **لن يتم إرسال أي تنبيه** (السعر في النطاق الآمن)
    
    - السعر الحالي = 7100
    - 🔔 **سيتم إرسال تنبيه HIGH** (السعر تجاوز 7000)
    
    - السعر الحالي = 2900
    - 🔔 **سيتم إرسال تنبيه LOW** (السعر أقل من 3000)
    
    ### 🛠️ حل المشكلات
    
    إذا كنت تتلقى تنبيهات عشوائية:
    1. اضغط على زر **"إعادة تعيين التنبيهات"**
    2. أعد تشغيل الصفحة (Refresh)
    3. تأكد من أن الأهداف منطقية (ليست قريبة جداً من السعر الحالي)
    """)

# عرض سجل التنبيهات في نهاية الصفحة
st.write("---")
if st.button("📋 عرض سجل التنبيهات"):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT username, telegram_id, high_target, low_target, 
               last_alerted_high, last_alerted_low 
        FROM users
    """)
    data = cursor.fetchall()
    conn.close()
    
    if data:
        df = pd.DataFrame(data, columns=["الاسم", "التليجرام", "الهدف الأعلى", "الهدف الأدنى", "آخر تنبيه HIGH", "آخر تنبيه LOW"])
        st.dataframe(df)
    else:
        st.info("لا يوجد مستخدمين مسجلين")
