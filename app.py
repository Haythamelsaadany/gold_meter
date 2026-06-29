import os
import time
import sqlite3
import json
import urllib.request
import urllib.parse
from datetime import datetime
import streamlit as st
import pandas as pd
import yfinance as yf
import plotly.express as px
import feedparser

# ===== الإعدادات الأساسية للواجهة (يجب أن تكون في البداية) =====
st.set_page_config(page_title="🏅 Gold Meter - المساعد المالي الذكي", layout="wide")

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
    
    try:
        cursor.execute("SELECT alert_enabled FROM users LIMIT 1")
    except sqlite3.OperationalError:
        cursor.execute("ALTER TABLE users ADD COLUMN alert_enabled INTEGER DEFAULT 1")
        conn.commit()
    conn.close()

def register_or_update_user(username, phone, tg_id, high, low):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    try:
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

def reset_all_alerts():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET last_alerted_high=NULL, last_alerted_low=NULL")
    conn.commit()
    conn.close()

# ===== 2. جلب البيانات اللحظية =====
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

# ===== 3. جلب البيانات التاريخية للرسم البياني =====
@st.cache_data(ttl=3600) # تحديث كل ساعة لتخفيف الضغط
def get_gold_history():
    try:
        ticker = yf.Ticker("GC=F")
        hist = ticker.history(period="1mo")
        if not hist.empty:
            df = hist[['Close']].reset_index()
            # إزالة التوقيت من التاريخ ليكون أوضح في الرسم البياني
            df['Date'] = df['Date'].dt.date
            df.columns = ['Date', 'Price']
            return df
    except Exception as e:
        return None

# ===== 4. جلب الأخبار الاقتصادية =====
@st.cache_data(ttl=1800) # تحديث كل نصف ساعة
def fetch_economy_news():
    try:
        # رابط RSS كمثال (يمكنك تغييره لأي مصدر أخباري تفضله)
        rss_url = "https://www.cnbcarabia.com/rss" 
        feed = feedparser.parse(rss_url)
        news_list = []
        for entry in feed.entries[:6]: # جلب آخر 6 أخبار
            news_list.append({
                "title": entry.title,
                "link": entry.link
            })
        return news_list
    except:
        return []

# ===== 5. خوارزمية التوصيات الفنية الذكية =====
def calculate_algorithm_confidence(price_21, usd_price, usd_egp):
    fair_price_21 = ((usd_price * usd_egp) / OUNCE_TO_GRAM) * (21.0 / 24.0)
    deviation = (price_21 - fair_price_21) / fair_price_21
    confidence = 100.0 - (abs(deviation) * 100.0 * 2)
    confidence = max(min(confidence, 99.4), 40.0)
    
    if deviation > 0.05:
        opinion = f"⚠️ **تحذير شراء:** السعر الحالي ({price_21:,.2f} ج.م) أعلى من قيمته العادلة المباشرة بفارق واضح. التوصية: التريث للمضاربين."
        color = "red"
    elif deviation < -0.05:
        opinion = f"🔥 **فرصة شراء:** السعر الحالي أقل من القيمة العادلة بشكل ملحوظ! فرصة جيدة للتجميع والادخار."
        color = "blue"
    else:
        opinion = f"➡️ **استقرار السوق:** السعر الحالي متوافق تماماً مع القيمة العادلة المباشرة ({fair_price_21:,.2f} ج.م). الشراء بغرض الادخار طويل الأجل آمن."
        color = "green"
    return round(confidence, 1), opinion, color

# ===== 6. محرك الفحص الآمن واللحظي (تليجرام) =====
def send_tg_message(tg_id, text):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = urllib.parse.urlencode({"chat_id": tg_id, "text": text}).encode("utf-8")
        req = urllib.request.Request(url, data=payload)
        with urllib.request.urlopen(req, timeout=5) as r:
            return True
    except:
        return False

def check_and_send_alerts_safely(price_21):
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT id, username, telegram_id, high_target, low_target, last_alerted_high, last_alerted_low FROM users WHERE alert_enabled = 1")
        users = cursor.fetchall()
        conn.close()
        
        if not users: return "لا يوجد مستخدمين نشطين"
        today_str = datetime.now().strftime('%Y-%m-%d')
        status_report = []
        
        for user in users:
            u_id, name, tg_id, high, low, last_high, last_low = user
            if not tg_id or high is None or low is None: continue
            
            val_high = float(high)
            val_low = float(low)
            
            if price_21 >= val_high and last_high != today_str:
                msg = f"🚀 تنبيه اختراق الهدف الأعلى:\nيا {name}، سعر جرام عيار 21 الحالي وصل {price_21:,.2f} ج.م متخطياً هدفك ({val_high:,.0f} ج.م)."
                if send_tg_message(tg_id, msg):
                    conn = sqlite3.connect(DB_FILE)
                    cursor = conn.cursor()
                    cursor.execute("UPDATE users SET last_alerted_high=? WHERE id=?", (today_str, u_id))
                    conn.commit()
                    conn.close()
                    status_report.append(f"تم إرسال تنبيه صعود لـ {name}")
                    
            if price_21 <= val_low and last_low != today_str:
                msg = f"🔻 تنبيه كسر القاع الأدنى:\nيا {name}، سعر جرام عيار 21 هبط الآن إلى {price_21:,.2f} ج.م متخطياً هدفك ({val_low:,.0f} ج.م)."
                if send_tg_message(tg_id, msg):
                    conn = sqlite3.connect(DB_FILE)
                    cursor = conn.cursor()
                    cursor.execute("UPDATE users SET last_alerted_low=? WHERE id=?", (today_str, u_id))
                    conn.commit()
                    conn.close()
                    status_report.append(f"تم إرسال تنبيه هبوط لـ {name}")
        
        if status_report:
            return ", ".join(status_report)
        return "السعر في النطاق الآمن لأهدافك الحالية"
    except Exception as e:
        return f"خطأ: {e}"

# تجهيز قاعدة البيانات
init_db()

# ===== 7. واجهة المستخدم (تنسيق مطور) =====
st.markdown("""
    <style>
    .main { background-color: #06060c; color: white; }
    .price-card { background-color: #0f0f1e; padding: 20px; border-radius: 12px; border: 1px solid #1e1e38; text-align: center; margin-bottom: 15px; }
    div.stButton > button:first-child { background-color: #e1b12c; color: black; font-weight: bold; width: 100%; border-radius: 8px; border: none; }
    .news-box { background-color: #1a1a2e; padding: 15px; border-radius: 8px; margin-bottom: 10px; border-right: 4px solid #e1b12c; }
    .news-box a { color: #f1c40f; text-decoration: none; font-weight: bold; }
    .news-box a:hover { color: #ffffff; text-decoration: underline; }
    </style>
""", unsafe_allow_html=True)

st.title("🏅 Gold Meter - لوحة تحليل الذهب المتكاملة")

# جلب البيانات
usd_price, usd_egp, carat_prices = fetch_live_gold_data()
current_price = carat_prices[21]
ounce_local_fair = usd_price * usd_egp

# --- قسم 1: المؤشرات المباشرة ---
col1, col2, col3 = st.columns(3)
with col1: st.markdown(f"<div class='price-card'><h4 style='color:#00d4ff;'>🌍 أوقية الذهب عالمياً</h4><h2>${usd_price:,.2f}</h2></div>", unsafe_allow_html=True)
with col2: st.markdown(f"<div class='price-card'><h4 style='color:#fdcb6e;'>💵 سعر الصرف التقديري</h4><h2>{usd_egp:.2f} ج.م</h2></div>", unsafe_allow_html=True)
with col3: st.markdown(f"<div class='price-card'><h4 style='color:#00b894;'>🏅 الأوقية محلياً (عادلة)</h4><h2>{ounce_local_fair:,.2f} ج.م</h2></div>", unsafe_allow_html=True)

st.write("---")

# --- قسم 2: أسعار الجرامات والمشغولات ---
c24, c22, c21, c18 = st.columns(4)
c24.metric("عيار 24", f"{carat_prices[24]:,.2f} ج.م")
c22.metric("عيار 22", f"{carat_prices[22]:,.2f} ج.م")
c21.metric("عيار 21 (السوق)", f"{current_price:,.2f} ج.م", delta="الأكثر شعبية")
c18.metric("عيار 18", f"{carat_prices[18]:,.2f} ج.م")

# أسعار السبائك والعملات
st.markdown("**🪙 أسعار السبائك والعملات الذهبية (بدون مصنعية):**")
sub1, sub2, sub3, sub4 = st.columns(4)
sub1.metric("جنيه ذهب (8 جرام عيار 21)", f"{current_price * 8:,.2f} ج.م")
sub2.metric("سبيكة 5 جرام (عيار 24)", f"{carat_prices[24] * 5:,.2f} ج.م")
sub3.metric("سبيكة 10 جرام", f"{carat_prices[24] * 10:,.2f} ج.م")
sub4.metric("سبيكة 50 جرام", f"{carat_prices[24] * 50:,.2f} ج.م")

st.write("---")

# --- قسم 3: الرسوم البيانية والأخبار ---
chart_col, news_col = st.columns([2, 1]) # تقسيم الشاشة: ثلثين للرسم البياني وثلث للأخبار

with chart_col:
    st.markdown("### 📊 الاتجاه العام عالمياً (آخر 30 يوم)")
    df_hist = get_gold_history()
    if df_hist is not None:
        fig = px.line(df_hist, x='Date', y='Price', 
                      labels={'Price': 'سعر الأوقية ($)', 'Date': 'التاريخ'})
        fig.update_traces(line_color='#e1b12c', line_width=3)
        fig.update_layout(plot_bgcolor='#06060c', paper_bgcolor='#06060c', font_color='white')
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.warning("تعذر جلب البيانات التاريخية في الوقت الحالي.")

    # التوصية الفنية أسفل الرسم البياني
    st.markdown("### 🧠 التحليل المالي والتوصية")
    confidence, op_text, op_color = calculate_algorithm_confidence(current_price, usd_price, usd_egp)
    if op_color == "red": st.error(op_text)
    elif op_color == "blue": st.info(op_text)
    else: st.success(op_text)
    st.markdown(f"📊 **مؤشر استقرار السوق:** `{confidence}%`")

with news_col:
    st.markdown("### 📰 آخر الأخبار الاقتصادية")
    news_items = fetch_economy_news()
    if news_items:
        for item in news_items:
            st.markdown(f"""
                <div class='news-box'>
                    <a href="{item['link']}" target="_blank">{item['title']}</a>
                </div>
            """, unsafe_allow_html=True)
    else:
        st.write("لم نتمكن من جلب الأخبار الآن. جرب لاحقاً.")

st.write("---")

# --- قسم 4: نظام التنبيهات وإدارة حسابات المستخدمين ---
st.markdown("### 🔔 نظام التنبيهات الآلية عبر تليجرام")
reg_col1, reg_col2 = st.columns(2)

if "u_tg" not in st.session_state: st.session_state["u_tg"] = ""
if "u_name" not in st.session_state: st.session_state["u_name"] = ""
if "u_phone" not in st.session_state: st.session_state["u_phone"] = ""
if "target_high" not in st.session_state: st.session_state["target_high"] = 6000.0
if "target_low" not in st.session_state: st.session_state["target_low"] = 5000.0

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
    target_high = st.number_input("🚀 هدف أعلى لبيع الذهب (جني أرباح):", value=float(st.session_state["target_high"]), step=50.0)
    target_low = st.number_input("🔻 هدف أدنى لشراء الذهب (تجميع):", value=float(st.session_state["target_low"]), step=50.0)
    
    st.write("")
    col_btn1, col_btn2 = st.columns(2)
    with col_btn1:
        if st.button("💾 حفظ الإعدادات"):
            if u_name and u_tg:
                if register_or_update_user(u_name, u_phone, u_tg, target_high, target_low):
                    st.session_state["u_tg"] = u_tg
                    st.session_state["u_name"] = u_name
                    st.session_state["u_phone"] = u_phone
                    st.session_state["target_high"] = float(target_high)
                    st.session_state["target_low"] = float(target_low)
                    st.balloons()
                    st.success("🎉 تم حفظ أهدافك بنجاح! سيتم إشعارك تلقائياً عند وصول السعر.")
                    time.sleep(1)
                    st.rerun()
            else:
                st.error("⚠️ يرجى إدخال الاسم والـ Chat ID")
                
    with col_btn2:
        if st.button("🔄 فحص وإرسال التنبيهات للمستخدمين"):
            report = check_and_send_alerts_safely(current_price)
            st.info(report)

st.write("---")
if st.button("🔄 تصفير سجل الإرسال لجميع المستخدمين"):
    reset_all_alerts()
    st.success("تم تصفير السجل بنجاح، النظام مستعد لإرسال التنبيهات من جديد.")
