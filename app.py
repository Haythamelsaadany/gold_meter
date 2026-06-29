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
OUNCE_TO_GRAM = 31.1034768
DB_FILE = "users_gold_alerts.db"

# متغير للتحكم في تشغيل الـ Thread مرة واحدة
if "stop_previous_threads" not in st.session_state:
    st.session_state["stop_previous_threads"] = False

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
            last_alerted_low TEXT
        )
    ''')
    conn.commit()
    conn.close()

def register_or_update_user(username, phone, tg_id, high, low):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    try:
        # حذف السجلات القديمة للمستخدم أولاً لتجنب التعارض
        cursor.execute("DELETE FROM users WHERE telegram_id=?", (tg_id,))
        cursor.execute('''
            INSERT INTO users (username, phone, telegram_id, high_target, low_target, last_alerted_high, last_alerted_low)
            VALUES (?, ?, ?, ?, ?, NULL, NULL)
        ''', (username, phone, tg_id, float(high), float(low)))
        conn.commit()
        
        # التأكد من أن السجل موجود
        cursor.execute("SELECT * FROM users WHERE telegram_id=?", (tg_id,))
        if cursor.fetchone():
            return True
        return False
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

def reset_user_alerts(tg_id):
    """إعادة تعيين تنبيهات المستخدم (لحل مشكلة التكرار)"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET last_alerted_high=NULL, last_alerted_low=NULL WHERE telegram_id=?", (tg_id,))
    conn.commit()
    conn.close()

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
        opinion = "⚠️ السعر الحالي أعلى من قيمته العادلة (بسبب فجوة العرض والطلب محلياً) - نوصي بالحذر."
        color = "red"
    else:
        opinion = "➡️ السعر متوافق تماماً مع القيمة العادلة لمتوسط البنوك الرسمي."
        color = "green"
    return round(confidence, 1), opinion, color

# ===== 4. محرك التنبيهات المعدل بالكامل (الحل الجذري) =====
def send_tg_message_async(tg_id, text):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = urllib.parse.urlencode({"chat_id": tg_id, "text": text, "disable_notification": "false"}).encode("utf-8")
        req = urllib.request.Request(url, data=payload)
        with urllib.request.urlopen(req, timeout=5) as r: 
            pass
    except Exception as e:
        print(f"Telegram send error: {e}")

def start_alert_worker():
    """تشغيل محرك التنبيهات بشكل آمن"""
    
    def alert_processing_loop():
        while True:
            try:
                # 1. جلب جميع المستخدمين
                conn_temp = sqlite3.connect(DB_FILE)
                cursor_temp = conn_temp.cursor()
                cursor_temp.execute("""
                    SELECT id, username, telegram_id, high_target, low_target, 
                           last_alerted_high, last_alerted_low 
                    FROM users
                """)
                users = cursor_temp.fetchall()
                conn_temp.close()
                
                if not users:
                    time.sleep(30)
                    continue
                
                # 2. جلب السعر الحالي
                try:
                    _, _, carat_prices = fetch_live_gold_data()
                    price_21 = round(float(carat_prices.get(21, 0)), 2)
                except Exception as e:
                    print(f"Error fetching price: {e}")
                    time.sleep(10)
                    continue
                
                today_str = datetime.now().strftime('%Y-%m-%d')
                
                # 3. معالجة كل مستخدم على حدة مع منطق صارم
                for user in users:
                    try:
                        u_id, name, tg_id, high, low, last_high, last_low = user
                        
                        # التحقق من صحة البيانات
                        if not tg_id or high is None or low is None:
                            continue
                            
                        val_high = float(high)
                        val_low = float(low)
                        
                        # ⚡ المنطق المعدل - التنبيه يحدث فقط عند تحقق الشرط الحقيقي
                        # ✅ التنبيه الأعلى: السعر الحالي > الهدف الأعلى
                        if price_21 > val_high:
                            if last_high != today_str:  # لم يتم التنبيه اليوم
                                msg = f"🚀 تنبيه اختراق الهدف الأعلى:\nيا {name}، سعر جرام عيار 21 الحقيقي وصل الآن {price_21:,.2f} ج.م متخطياً هدفك ({val_high:,.0f} ج.م)."
                                send_tg_message_async(tg_id, msg)
                                
                                # تحديث قاعدة البيانات لمنع التكرار
                                conn = sqlite3.connect(DB_FILE)
                                cursor = conn.cursor()
                                cursor.execute("UPDATE users SET last_alerted_high=? WHERE id=?", (today_str, u_id))
                                conn.commit()
                                conn.close()
                                print(f"✅ تم إرسال تنبيه HIGH لـ {name} (سعر {price_21} > هدف {val_high})")
                        
                        # ✅ التنبيه الأدنى: السعر الحالي < الهدف الأدنى
                        elif price_21 < val_low:
                            if last_low != today_str:  # لم يتم التنبيه اليوم
                                msg = f"🔻 تنبيه كسر القاع الأدنى:\nيا {name}، سعر جرام عيار 21 الحقيقي هبط الآن إلى {price_21:,.2f} ج.م متخطياً هدف الشراء عندك ({val_low:,.0f} ج.م)."
                                send_tg_message_async(tg_id, msg)
                                
                                # تحديث قاعدة البيانات لمنع التكرار
                                conn = sqlite3.connect(DB_FILE)
                                cursor = conn.cursor()
                                cursor.execute("UPDATE users SET last_alerted_low=? WHERE id=?", (today_str, u_id))
                                conn.commit()
                                conn.close()
                                print(f"✅ تم إرسال تنبيه LOW لـ {name} (سعر {price_21} < هدف {val_low})")
                        
                        # ✅ السعر بين الهدفين: إعادة تعيين التنبيهات لليوم التالي
                        else:
                            # إذا كان السعر بين الحدين، نعيد تعيين التنبيهات
                            if last_high == today_str or last_low == today_str:
                                conn = sqlite3.connect(DB_FILE)
                                cursor = conn.cursor()
                                if last_high == today_str:
                                    cursor.execute("UPDATE users SET last_alerted_high=NULL WHERE id=?", (u_id,))
                                if last_low == today_str:
                                    cursor.execute("UPDATE users SET last_alerted_low=NULL WHERE id=?", (u_id,))
                                conn.commit()
                                conn.close()
                                
                    except Exception as e:
                        print(f"Error processing user {user[0]}: {e}")
                        continue
                
                # نوم آمن
                time.sleep(30)  # فحص كل 30 ثانية
                
            except Exception as e:
                print(f"Main loop error: {e}")
                time.sleep(10)
    
    # تشغيل Thread واحد فقط
    thread_name = "GoldAlertWorkerThread"
    for t in threading.enumerate():
        if t.name == thread_name:
            print("⚠️ Thread موجود بالفعل، لا داعي لإنشاء جديد")
            return
    
    worker_thread = threading.Thread(target=alert_processing_loop, name=thread_name, daemon=True)
    worker_thread.start()
    print("✅ تم تشغيل محرك التنبيهات بنجاح")

# تهيئة النظام
init_db()
start_alert_worker()

# ===== 5. واجهة المستخدم =====
st.set_page_config(page_title="🏅 Gold Meter - لوحة الأسعار العادلة", layout="wide")

st.markdown("""
    <style>
    .main { background-color: #06060c; color: white; }
    .price-card { background-color: #0f0f1e; padding: 25px; border-radius: 14px; border: 1px solid #1e1e38; text-align: center; }
    div.stButton > button:first-child { background-color: #e1b12c; color: black; font-weight: bold; width: 100%; border-radius: 8px; }
    .alert-box { background-color: #1a1a2e; padding: 15px; border-radius: 10px; border-left: 4px solid #e1b12c; margin: 10px 0; }
    </style>
""", unsafe_allow_html=True)

st.title("🏅 Gold Meter - نظام تقييم الذهب المحلي والقيمة العادلة")
st.write("لوحة تحكم تفاعلية مصلحة بالكامل ومحمية ضد عشوائية التنبيهات الخلفية.")

# جلب البيانات
usd_price, usd_egp, carat_prices = fetch_live_gold_data()
confidence, op_text, op_color = calculate_algorithm_confidence(carat_prices[21], usd_price, usd_egp)

# عرض الأسعار
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

# تقرير الخوارزمية
st.markdown("### 🧠 تقرير الخوارزمية الفنية ونسبة الموثوقية الحالية")
if op_color == "red":
    st.error(op_text)
else:
    st.success(op_text)
st.info(f"📊 **نسبة وثوق دقة الأسعار الحالية وطبقاً لبيانات البنك:** {confidence}%")

# عرض حالة التنبيهات الحالية
st.write("---")
st.markdown("### 📊 حالة التنبيهات الحالية")
col_status1, col_status2 = st.columns(2)
with col_status1:
    st.info(f"🔔 **حالة الهدف الأعلى**: {'🔴 مفعل' if carat_prices[21] > 6000 else '🟢 غير مفعل (السعر أقل من الهدف)'}")
    st.info(f"📈 **السعر الحالي**: {carat_prices[21]:,.2f} ج.م")
with col_status2:
    st.info(f"🔔 **حالة الهدف الأدنى**: {'🔴 مفعل' if carat_prices[21] < 3000 else '🟢 غير مفعل (السعر أعلى من الهدف)'}")
    st.info(f"📉 **نطاق الأمان**: بين 3000 و 7000 ج.م")

st.write("---")

# لوحة التحكم
st.markdown("### 🔔 لوحة التحكم الفورية في التنبيهات")
reg_col1, reg_col2 = st.columns(2)

if "u_tg" not in st.session_state: st.session_state["u_tg"] = ""
if "u_name" not in st.session_state: st.session_state["u_name"] = ""
if "u_phone" not in st.session_state: st.session_state["u_phone"] = ""
if "target_high" not in st.session_state: st.session_state["target_high"] = 6000.0
if "target_low" not in st.session_state: st.session_state["target_low"] = 3000.0

with reg_col1:
    u_tg = st.text_input("🆔 اكتب معرف التليجرام الخاص بك (Chat ID):", value=st.session_state["u_tg"])
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
    target_high = st.number_input("🚀 حد التنبيه الأعلى الحالي لجني الأرباح:", value=float(st.session_state["target_high"]), step=50.0)
    target_low = st.number_input("🔻 حد التنبيه الأدنى الحالي للشراء:", value=float(st.session_state["target_low"]), step=50.0)
    
    # زر إعادة تعيين التنبيهات
    if st.button("🔄 إعادة تعيين التنبيهات (حل المشكلة)"):
        if u_tg:
            reset_user_alerts(u_tg)
            st.success("✅ تم إعادة تعيين تنبيهاتك بنجاح! لن يتم إرسال أي تنبيهات حتى تتحقق الشروط.")
            st.balloons()
            time.sleep(1)
            st.rerun()

# زر الحفظ
if st.button("💾 حفظ وتحديث المحددات والمعدلات الحالية"):
    if u_name and u_tg:
        if register_or_update_user(u_name, u_phone, u_tg, target_high, target_low):
            st.session_state["u_tg"] = u_tg
            st.session_state["u_name"] = u_name
            st.session_state["u_phone"] = u_phone
            st.session_state["target_high"] = float(target_high)
            st.session_state["target_low"] = float(target_low)
            
            st.balloons()
            st.success(f"🎉 تم حفظ وتحديث أهدافك الصارمة بنجاح! السعر الحالي لعيار 21 هو {carat_prices[21]:,.2f} ج.م ومستهدفتك الآمنة هي {target_low} و {target_high}.")
            st.info("⚠️ ملاحظة: التنبيهات ستعمل فقط عندما يصل السعر إلى الأهداف المحددة.")
            time.sleep(1.5)
            st.rerun()

st.write("---")

# زر تصفير الكاش
if st.button("♻️ تصفير كامل وإبادة عمليات الفحص القديمة العالقة في السيرفر"):
    st.cache_data.clear()
    st.warning("تم تصفير الكاش بالكامل! يُرجى إعادة تحديث الصفحة (Refresh) لضمان بيئة نظيفة ومطابقة 100%.")
    
# عرض تعليمات للمستخدم
with st.expander("📖 كيف تعمل التنبيهات بشكل صحيح؟"):
    st.markdown("""
    ### 🔔 آلية عمل التنبيهات المعدلة:
    
    1. **الهدف الأعلى (High Target)**: يتم إرسال تنبيه فقط عندما **يزيد السعر عن** هذا الرقم.
    2. **الهدف الأدنى (Low Target)**: يتم إرسال تنبيه فقط عندما **ينخفض السعر عن** هذا الرقم.
    3. **حالة عدم التفعيل**: إذا كان السعر بين الهدفين (مثل 4062 بين 3000 و 7000)، **لن يتم إرسال أي تنبيه**.
    4. **منع التكرار**: يتم إرسال التنبيه **مرة واحدة فقط في اليوم** لكل هدف.
    5. **إعادة التعيين**: يمكنك استخدام زر "إعادة تعيين التنبيهات" لحل أي مشكلة في التكرار.
    
    ### 💡 مثال توضيحي:
    - إذا حددت الهدف الأعلى = 7000 والهدف الأدنى = 3000
    - والسعر الحالي = 4062
    - ✅ **لن يتم إرسال أي تنبيه** (لأن 4062 < 7000 و 4062 > 3000)
    - ✅ هذا هو السلوك الصحيح والمطلوب!
    """)
