import streamlit as st
import pandas as pd
from sqlalchemy import create_engine, text
import requests
import datetime

# ==========================================
# 1. إعدادات الواجهة الاحترافية لـ Gold Meter Pro
# ==========================================
st.set_page_config(page_title="Gold Meter Pro", page_icon="🏅", layout="wide")

st.markdown("""
    <style>
    .main-title { font-size: 32px; font-weight: bold; text-align: center; color: #D4AF37; margin-bottom: 20px; }
    .price-card { background-color: #1e2430; padding: 15px; border-radius: 10px; border-left: 4px solid #D4AF37; text-align: center; }
    .price-card h3 { margin: 8px 0 0 0; color: #ffffff; font-size: 22px; }
    .price-card h5 { margin: 0; color: #D4AF37; font-size: 14px; }
    .source-text { font-size: 13px; color: #00ffcc; text-align: center; margin-top: 5px; font-weight: bold; }
    .warning-text { font-size: 13px; color: #ff9900; text-align: center; margin-top: 5px; font-weight: bold; }
    </style>
""", unsafe_allow_html=True)

st.markdown('<div class="main-title">🏅 منظومة الذهب الذكية - Gold Meter Pro</div>', unsafe_allow_html=True)

# ==========================================
# 2. الاتصال الآمن بـ Supabase عبر SQLAlchemy
# ==========================================
def get_db_engine():
    try:
        db = st.secrets["postgres"]
        db_url = f"postgresql://{db['user']}:{db['password']}@{db['host']}:{db['port']}/{db['database']}"
        return create_engine(db_url)
    except Exception as e:
        st.error(f"❌ خطأ في الـ Secrets لقاعدة البيانات: {e}")
        return None

engine = get_db_engine()

if engine:
    try:
        with engine.begin() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS gold_targets (
                    id SERIAL PRIMARY KEY,
                    carat_type VARCHAR(50),
                    target_type VARCHAR(50),
                    target_price NUMERIC,
                    chat_id VARCHAR(50),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    is_active BOOLEAN DEFAULT TRUE
                );
            """))
    except Exception:
        pass

# ==========================================
# 3. محرك ياهو فاينانس المطور (Query2 المفتوح + كاش 5 ثوانٍ فقط)
# ==========================================
@st.cache_data(ttl=5)
def fetch_yahoo_realtime_prices():
    # أسعار احتياطية ديناميكية قريبة جداً من السوق الحالي
    ounce_usd = 4015.00  
    usd_egp = 49.25
    is_live = False
    error_log = ""
    
    # هيدرز متقدمة جداً لمنع الـ 403 Forbidden على السيرفر السحابي
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9"
    }

    # جلب سعر أونصة الذهب الفوري عبر سيرفر ياهو الثاني الأكثر استقراراً للمنصات
    try:
        url_gold = "https://query2.finance.yahoo.com/v8/finance/chart/XAUUSD=X?interval=1m&range=1d"
        res_gold = requests.get(url_gold, headers=headers, timeout=5)
        if res_gold.status_code == 200:
            json_data = res_gold.json()
            ounce_usd = float(json_data['chart']['result'][0]['meta']['regularMarketPrice'])
            is_live = True
        else:
            error_log += f"Gold API Error ({res_gold.status_code}) "
    except Exception as e:
        error_log += f"Gold Connection Failed ({str(e)}) "

    # جلب سعر دولار البنك المركزي / الفوركس لحظياً
    try:
        url_egp = "https://query2.finance.yahoo.com/v8/finance/chart/USDEGP=X?interval=1m&range=1d"
        res_egp = requests.get(url_egp, headers=headers, timeout=5)
        if res_egp.status_code == 200:
            json_data = res_egp.json()
            usd_egp = float(json_data['chart']['result'][0]['meta']['regularMarketPrice'])
        else:
            error_log += f"Forex API Error ({res_egp.status_code})"
    except Exception as e:
        error_log += f"Forex Connection Failed ({str(e)})"

    return ounce_usd, usd_egp, is_live, error_log

# استدعاء المحرك الجديد
ounce_usd, usd_egp, is_live, error_msg = fetch_yahoo_realtime_prices()

# الحسابات الرياضية بالسوق المصري
gold_pure_price_egp = (ounce_usd * usd_egp) / 31.10348
price_24 = round(gold_pure_price_egp, 2)
price_21 = round(gold_pure_price_egp * (21 / 24), 2)
price_18 = round(gold_pure_price_egp * (18 / 24), 2)

# عرض الـ 5 كروت كاملة شاملة عيار 24
st.subheader("📈 شاشة مراقبة الأسعار الحية بالثانية")
c1, c2, c3, c4, c5 = st.columns(5)
with c1:
    st.markdown(f'<div class="price-card"><h5>🌍 أونصة الذهب</h5><h3>${ounce_usd:,.2f}</h3></div>', unsafe_allow_html=True)
with c2:
    st.markdown(f'<div class="price-card"><h5>🏦 دولار المركزي</h5><h3>{usd_egp} ج.م</h3></div>', unsafe_allow_html=True)
with c3:
    st.markdown(f'<div class="price-card"><h5>🏆 عيار 24</h5><h3>{price_24:,.2f} ج.م</h3></div>', unsafe_allow_html=True)
with c4:
    st.markdown(f'<div class="price-card"><h5>✨ عيار 21</h5><h3>{price_21:,.2f} ج.م</h3></div>', unsafe_allow_html=True)
with c5:
    st.markdown(f'<div class="price-card"><h5>⚜️ عيار 18</h5><h3>{price_18:,.2f} ج.م</h3></div>', unsafe_allow_html=True)

# طباعة حالة البيانات للمصداقية التامة والشفافية
if is_live:
    st.markdown('<div class="source-text">📡 اتصال البورصة: نشط ولحظي 100% (Yahoo Finance Live Server)</div>', unsafe_allow_html=True)
else:
    st.markdown(f'<div class="warning-text">⚠️ تحذير: السيرفر محجوب مؤقتاً ويقرأ بيانات مرجعية قريبة. السبب: {error_msg}</div>', unsafe_allow_html=True)

st.divider()

# ==========================================
# 4. لوحة التحكم وتخزين الأهداف
# ==========================================
col_form, col_actions = st.columns([1, 1])

with col_form:
    st.subheader("🎯 تسجيل هدف جديد للمراقبة")
    carat_choice = st.selectbox("اختر العيار المستهدف:", ["عيار 24", "عيار 21", "عيار 18"])
    target_type = st.selectbox("نوع التنبيه:", ["بيع (ارتفاع السعر)", "شراء (انخفاض السعر)"])
    
    current_selected_price = price_24 if carat_choice == "عيار 24" else (price_21 if carat_choice == "عيار 21" else price_18)
    target_price = st.number_input(f"سعر الهدف المطلوب (الحالي: {current_selected_price}):", value=float(current_selected_price), step=5.0)
    user_chat_id = st.text_input("Telegram Chat ID:", value="452445185")

    if st.button("💾 حفظ هدف التنبيه"):
        if engine:
            try:
                with engine.begin() as conn:
                    conn.execute(
                        text("""
                        INSERT INTO gold_targets (carat_type, target_type, target_price, chat_id, is_active)
                        VALUES (:carat, :type, :price, :chat_id, TRUE)
                        """),
                        {"carat": carat_choice, "type": target_type, "price": target_price, "chat_id": user_chat_id}
                    )
                st.success(f"✅ تم حفظ هدف الـ {target_type} للـ {carat_choice} بنجاح!")
                st.rerun()
            except Exception as e:
                st.error(f"❌ فشل الحفظ: {e}")

# ==========================================
# 5. منطق فحص الأهداف وإرسال إشعارات التليجرام
# ==========================================
def send_telegram_msg(chat_id, text_msg):
    token = st.secrets.get("TELEGRAM_BOT_TOKEN")
    if not token:
        st.error("❌ مفتاح TELEGRAM_BOT_TOKEN غير متاح في الـ Secrets!")
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        res = requests.post(url, json={"chat_id": chat_id, "text": text_msg, "parse_mode": "Markdown"})
        return res.status_code == 200
    except Exception:
        return False

with col_actions:
    st.subheader("⚡ العمليات وفحص التنبيهات")
    
    if st.button("🔔 اختبار اتصال البوت"):
        test_msg = f"🔔 *Gold Meter Pro*\nاتصال البوت شغال وممتاز يا هندسة! 🚀\nالوقت: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        if send_telegram_msg(user_chat_id, test_msg):
            st.success("🎯 تم إرسال رسالة الاختبار بنجاح!")
        else:
            st.error("❌ فشل الإرسال، تحقق من توكن التليجرام في الـ Secrets.")

    if st.button("🔍 فحص التنبيهات يدوياً الآن"):
        st.cache_data.clear() 
        if engine:
            try:
                df_active = pd.read_sql_query("SELECT * FROM gold_targets WHERE is_active = TRUE", engine)
                
                if df_active.empty:
                    st.info("لا توجد أهداف نشطة حالياً للفحص.")
                else:
                    alerts_triggered = 0
                    for index, row in df_active.iterrows():
                        c_type = row['carat_type']
                        t_type = row['target_type']
                        t_price = float(row['target_price'])
                        c_id = row['chat_id']
                        row_id = row['id']
                        
                        current_local_price = price_24 if c_type == "عيار 24" else (price_21 if c_type == "عيار 21" else price_18)
                        
                        condition_met = False
                        if "بيع" in t_type and current_local_price >= t_price:
                            condition_met = True
                        elif "شراء" in t_type and current_local_price <= t_price:
                            condition_met = True
                            
                        if condition_met:
                            alert_text = (
                                f"🚨 *تنبيه ذهبي متحقق!*\n\n"
                                f"📦 *العيار:* {c_type}\n"
                                f"📈 *نوع الهدف:* {t_type}\n"
                                f"🎯 *السعر المستهدف:* {t_price:,.2f} ج.م\n"
                                f"💰 *السعر الحالي الآن:* {current_local_price:,.2f} ج.م\n\n"
                                f"الـ Gold Bot شغال ومتابع لحظة بلحظة! ✨"
                            )
                            if send_telegram_msg(c_id, alert_text):
                                alerts_triggered += 1
                                with engine.begin() as conn:
                                    conn.execute(text("UPDATE gold_targets SET is_active = FALSE WHERE id = :id"), {"id": row_id})
                    
                    if alerts_triggered > 0:
                        st.success(f"🚀 تم إرسال ({alerts_triggered}) تنبيه بنجاح لتليجرام!")
                        st.rerun()
                    else:
                        st.info("💡 تم الفحص: السعر الحالي لم يحقق شروط أي هدف نشط بعد.")
            except Exception as e:
                st.error(f"❌ خطأ أثناء فحص الشروط: {e}")

# ==========================================
# 6. عرض سجل الأهداف
# ==========================================
st.divider()
st.subheader("📋 سجل الأهداف المخزنة سحابياً (آخر 10 أهداف)")

if engine:
    try:
        df_view = pd.read_sql_query("SELECT id, carat_type, target_type, target_price, is_active FROM gold_targets ORDER BY id DESC LIMIT 10", engine)
        if not df_view.empty:
            st.dataframe(df_view, width="stretch")
        else:
            st.info("الداتا بيز فارغة حالياً.")
    except Exception as e:
        st.error(f"❌ تعذر جلب السجل: {e}")
