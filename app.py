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
    .source-text { font-size: 12px; color: #888888; text-align: center; margin-top: 5px; }
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
# 3. محرك جلب الأسعار اللحظي متعدد المصادر (محمي بكاش 5 دقائق)
# ==========================================
@st.cache_data(ttl=300)
def fetch_live_prices_from_exchanges():
    # المصادر الافتراضية كخط دفاع أخير في حال انقطاع الإنترنت
    ounce_usd = 3976.40
    usd_egp = 49.23
    sources_used = []

    # أ. سحب سعر الدولار مقابل الجنيه لحظياً من البورصة العالمية المفتوحة
    try:
        req_currency = requests.get("https://open.er-api.com/v6/latest/USD", timeout=5)
        if req_currency.status_code == 200:
            rates = req_currency.json().get("rates", {})
            if "EGP" in rates:
                usd_egp = round(rates["EGP"], 2)
                sources_used.append("OpenExchange (USD/EGP)")
    except Exception:
        pass

    # ب. سحب سعر أونصة الذهب - المصدر الأول الاحترافي (إذا وفرت تتوكن في الـ Secrets)
    gold_api_key = st.secrets.get("GOLD_API_KEY")
    if gold_api_key:
        try:
            headers = {'x-access-token': gold_api_key}
            req_gold_api = requests.get("https://www.goldapi.io/api/XAU/USD", headers=headers, timeout=5)
            if req_gold_api.status_code == 200:
                price = req_gold_api.json().get("price")
                if price:
                    ounce_usd = float(price)
                    sources_used.append("GoldAPI.io (XAU)")
        except Exception:
            pass

    # ج. سحب سعر أونصة الذهب - المصدر الثاني المفتوح (CoinGecko PAXG المربوط بالذهب الفعلي)
    if len(sources_used) < 2:  # إذا لم يعمل المصدر الأول أو لزيادة التأكيد
        try:
            req_gecko = requests.get("https://api.coingecko.com/api/v3/simple/price?ids=pax-gold&vs_currencies=usd", timeout=5)
            if req_gecko.status_code == 200:
                gecko_price = req_gecko.json().get("pax-gold", {}).get("usd")
                if gecko_price:
                    ounce_usd = float(gecko_price)
                    sources_used.append("CoinGecko Live Spot")
        except Exception:
            pass

    return ounce_usd, usd_egp, " | ".join(sources_used) if sources_used else "Fallback Static Data"

# تشغيل الفحص اللحظي للمحرك الجديد
ounce_usd, usd_egp, data_source = fetch_live_prices_from_exchanges()

# الحسابات الرياضية الدقيقة المبنية على بيانات البورصة الحية
gold_pure_price_egp = (ounce_usd * usd_egp) / 31.10348
price_24 = round(gold_pure_price_egp, 2)
price_21 = round(gold_pure_price_egp * (21 / 24), 2)
price_18 = round(gold_pure_price_egp * (18 / 24), 2)

# عرض الـ 5 كروت كاملة شاملة عيار 24
st.subheader("📈 أسعار الذهب والدولار الحية مباشرة من البورصة")
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

st.markdown(f'<div class="source-text">📡 مصادر البيانات النشطة حالياً: {data_source}</div>', unsafe_allow_html=True)
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
        st.cache_data.clear() # تفريغ الكاش مؤقتاً عند طلب الفحص اليدوي لجلب أحدث سعر بالثانية
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
                        # فحص دقيق للشرط الرياضي التلقائي
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
