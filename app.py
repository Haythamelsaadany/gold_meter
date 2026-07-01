import streamlit as st
import pandas as pd
from sqlalchemy import create_engine, text
import requests
import datetime
import time

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
    .warning-text { font-size: 13px; color: #ffcc00; text-align: center; margin-top: 5px; font-weight: bold; }
    .news-card { background-color: #1a1f2c; padding: 15px; border-radius: 8px; margin-bottom: 10px; border-right: 4px solid #00ffcc; }
    .rec-card { background-color: #1a1f2c; padding: 15px; border-radius: 8px; margin-bottom: 10px; border-right: 4px solid #D4AF37; }
    .trend-text { font-size: 16px; font-weight: bold; text-align: center; margin-top: -10px; margin-bottom: 15px; }
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
# 3. محرك الأسعار المطور اللحظي (Failover لمنع الـ Gap)
# ==========================================
@st.cache_data(ttl=30)
def fetch_realtime_prices_with_failover():
    ounce_usd = 4019.55  
    usd_egp = 49.25
    source_used = "الأسعار المرجعية"
    is_live = False
    error_log = ""
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    }

    # [المسار الأول]: ياهو فاينانس
    try:
        url_gold = "https://query2.finance.yahoo.com/v8/finance/chart/XAUUSD=X?interval=1m&range=1d"
        res_gold = requests.get(url_gold, headers=headers, timeout=4)
        if res_gold.status_code == 200:
            json_data = res_gold.json()
            ounce_usd = float(json_data['chart']['result'][0]['meta']['regularMarketPrice'])
            source_used = "Yahoo Finance Live"
            is_live = True
        else:
            error_log += f"Yahoo ({res_gold.status_code}) "
    except Exception:
        error_log += "Yahoo Timeout "

    # [المسار الثاني - الإنقاذ]: كوين جيكو
    if not is_live:
        try:
            url_gecko = "https://api.coingecko.com/api/v3/simple/price?ids=pax-gold&vs_currencies=usd"
            res_gecko = requests.get(url_gecko, headers=headers, timeout=4)
            if res_gecko.status_code == 200:
                gecko_price = res_gecko.json().get("pax-gold", {}).get("usd")
                if gecko_price:
                    ounce_usd = float(gecko_price)
                    source_used = "CoinGecko (PAXG Spot)"
                    is_live = True
            else:
                error_log += f"CoinGecko ({res_gecko.status_code}) "
        except Exception:
            error_log += "CoinGecko Error "

    # جلب سعر الدولار
    try:
        url_egp = "https://query2.finance.yahoo.com/v8/finance/chart/USDEGP=X?interval=1m&range=1d"
        res_egp = requests.get(url_egp, headers=headers, timeout=4)
        if res_egp.status_code == 200:
            json_data = res_egp.json()
            usd_egp = float(json_data['chart']['result'][0]['meta']['regularMarketPrice'])
        else:
            req_currency = requests.get("https://open.er-api.com/v6/latest/USD", timeout=4)
            if req_currency.status_code == 200:
                usd_egp = float(req_currency.json().get("rates", {}).get("EGP", usd_egp))
    except Exception:
        pass

    return ounce_usd, usd_egp, is_live, source_used, error_log

ounce_usd, usd_egp, is_live, data_source, error_msg = fetch_realtime_prices_with_failover()

gold_pure_price_egp = (ounce_usd * usd_egp) / 31.10348
price_24 = round(gold_pure_price_egp, 2)
price_21 = round(gold_pure_price_egp * (21 / 24), 2)
price_18 = round(gold_pure_price_egp * (18 / 24), 2)

# ==========================================
# 4. ترقية: حساب مؤشر الاتجاه (Trend Indicator) عبر الـ Session State
# ==========================================
if 'last_price' not in st.session_state:
    st.session_state.last_price = ounce_usd

if ounce_usd > st.session_state.last_price:
    trend_markup = f'<div class="trend-text" style="color:#00ffcc;">📈 حركة السعر الحالية: صعود (+${round(ounce_usd - st.session_state.last_price, 2)}) مقارنة بالقراءة السابقة</div>'
elif ounce_usd < st.session_state.last_price:
    trend_markup = f'<div class="trend-text" style="color:#ff3333;">📉 حركة السعر الحالية: هبوط (-${round(st.session_state.last_price - ounce_usd, 2)}) مقارنة بالقراءة السابقة</div>'
else:
    trend_markup = f'<div class="trend-text" style="color:#ffcc00;">➡️ حركة السعر الحالية: استقرار ثبات سعري لحظي</div>'

st.session_state.last_price = ounce_usd

# ==========================================
# 5. ترقية: لوحة جانبية ذكية (Sidebar Calculator) لرفع جودة الـ UI
# ==========================================
with st.sidebar:
    st.markdown("### 🧮 حاسبة الاستثمار السريع")
    st.write("احسب تقدر تشتري كام جرام بميزانيتك الحالية:")
    user_budget = st.number_input("أدخل المبلغ المتوفر (ج.م):", value=50000, step=5000)
    
    calc_24 = round(user_budget / price_24, 2) if price_24 > 0 else 0
    calc_21 = round(user_budget / price_21, 2) if price_21 > 0 else 0
    calc_18 = round(user_budget / price_18, 2) if price_18 > 0 else 0
    
    st.info(f"🏆 **عيار 24:** يعادل حوالي `{calc_24}` جرام")
    st.success(f"✨ **عيار 21:** يعادل حوالي `{calc_21}` جرام")
    st.warning(f"⚜️ **عيار 18:** يعادل حوالي `{calc_18}` جرام")
    st.divider()
    st.caption("تم التطوير بواسطة م/ هيثم الصعيدي لمنظومة Gold Meter Pro")

# ==========================================
# 6. تقسيم التطبيق إلى تابات احترافية (Tabs)
# ==========================================
tab_monitor, tab_news, tab_telegram_setup = st.tabs([
    "📊 شاشة المراقبة والتنبيهات", 
    "📰 الأخبار والتوصيات الرياضية الفنية", 
    "🛠️ دليل تشغيل بوت التليجرام"
])

# ------------------------------------------
# محتوى التاب الأول: الشاشة الرئيسية والتنبيهات
# ------------------------------------------
with tab_monitor:
    st.markdown(trend_markup, unsafe_allow_html=True)
    
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

    if is_live:
        st.markdown(f'<div class="source-text">📡 المصدر النشط: {data_source} (تحديث تلقائي مستمر كل 30 ثانية)</div>', unsafe_allow_html=True)
    else:
        st.markdown(f'<div class="warning-text">⚠️ وضع الأمان نشط (لمنع الفجوات السعرية). تفاصيل: {error_msg}</div>', unsafe_allow_html=True)

    st.divider()

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
                    st.success(f"✅ تم حفظ هدف الـ {target_type} بنجاح!")
                    st.json({"status": "success", "target": target_price})
                    time.sleep(1)
                    st.rerun()
                except Exception as e:
                    st.error(f"❌ فشل الحفظ: {e}")

    # دالة إرسال التليجرام
    def send_telegram_msg(chat_id, text_msg):
        token = st.secrets.get("TELEGRAM_BOT_TOKEN")
        if not token:
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
            test_msg = f"🔔 *Gold Meter Pro*\nاتصال البوت ممتاز وشغال يا هندسة ومستعد للمراقبة أثناء الإجازة! 🏖️"
            if send_telegram_msg(user_chat_id, test_msg):
                st.success("🎯 تم إرسال رسالة الاختبار بنجاح للتليجرام!")
            else:
                st.error("❌ فشل الإرسال، تحقق من الـ Secrets.")

        if st.button("🔍 فحص التنبيهات يدوياً الآن"):
            st.cache_data.clear() 
            if engine:
                try:
                    df_active = pd.read_sql_query("SELECT * FROM gold_targets WHERE is_active = TRUE", engine)
                    if df_active.empty:
                        st.info("لا توجد أهداف نشطة حالياً.")
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
                                    f"💰 *السعر الحالي الآن:* {current_local_price:,.2f} ج.م\n"
                                )
                                if send_telegram_msg(c_id, alert_text):
                                    alerts_triggered += 1
                                    with engine.begin() as conn:
                                        conn.execute(text("UPDATE gold_targets SET is_active = FALSE WHERE id = :id"), {"id": row_id})
                        
                        if alerts_triggered > 0:
                            st.success(f"🚀 تم إرسال ({alerts_triggered}) تنبيه لتليجرام!")
                            st.rerun()
                        else:
                            st.info("💡 لم يحقق السعر شروط أي هدف حالياً.")
                except Exception as e:
                    st.error(f"❌ خطأ أثناء الفحص: {e}")

    st.divider()
    st.subheader("📋 سجل الأهداف المخزنة سحابياً (آخر 10 أهداف)")
    if engine:
        try:
            df_view = pd.read_sql_query("SELECT id, carat_type, target_type, target_price, is_active FROM gold_targets ORDER BY id DESC LIMIT 10", engine)
            if not df_view.empty:
                st.dataframe(df_view, width="stretch")
            else:
                st.info("الداتا بيز فارغة حالياً.")
        except Exception:
            pass

# ------------------------------------------
# محتوى التاب الثاني: الأخبار والتوصيات الفنية (ترقية الحساب الديناميكي)
# ------------------------------------------
with tab_news:
    st.subheader("📰 شريط أخبار الذهب الفني")
    
    # حساب نقاط الدعم والمقاومة ديناميكياً بناء على السعر اللحظي الحالي للأونصة
    pivot_global = ounce_usd
    support_global = round(ounce_usd - 20, 2)
    resistance_global = round(ounce_usd + 20, 2)
    
    # حساب الدعم والمقاومة محلياً لعيار 21 لتعود بالفائدة الفورية للمستخدم
    support_egp_21 = round((support_global * usd_egp * 21/24) / 31.10348, 2)
    resistance_egp_21 = round((resistance_global * usd_egp * 21/24) / 31.10348, 2)

    col_news_left, col_news_right = st.columns(2)
    
    with col_news_left:
        st.markdown("### 🌍 آخر المستجدات والتقارير")
        st.markdown(f"""
        <div class="news-card">
            <h5>ثبات الأونصة العالمية حول مستويات الـ {ounce_usd:,.2f}$ بانتظار إغلاق المحاضر الفيدرالية.</h5>
            <small>📅 تحديث: لحظي مع الشاشة</small>
        </div>
        <div class="news-card">
            <h5>استقرار تام لأسعار الصرف الرسمية عند مستويات {usd_egp} ج.م للدولار مما يدعم توازن السوق المحلي.</h5>
            <small>📅 تحديث: منذ ساعة</small>
        </div>
        """, unsafe_allow_html=True)
        
    with col_news_right:
        st.markdown("### 🎯 التوصيات الرياضية الحسابية (تتغير ديناميكياً)")
        st.markdown(f"""
        <div class="rec-card">
            <h5>🎯 <b>نقطة الارتكاز العالمية الحالية:</b> ${pivot_global:,.2f}</h5>
            <p>📉 <b>مستوى الدعم العالمي (شراء):</b> ${support_global:,.2f} <br> 
               ➡️ يعادل محلياً لعيار 21: <b>{support_egp_21:,.2f} ج.م</b></p>
            <p>📈 <b>مستوى المقاومة العالمي (بيع):</b> ${resistance_global:,.2f} <br>
               ➡️ يعادل محلياً لعيار 21: <b>{resistance_egp_21:,.2f} ج.م</b></p>
        </div>
        <div class="rec-card">
            💡 <b>نصيحة المنظومة اللحظية:</b> السعر الحالي يعطي استقراراً نسبياً. يفضل دائماً الشراء التراكمي قرب نقاط الدعم المحسوبة أعلاه، وتفعيل التنبيه الآلي على التليجرام لضمان قنص الفرصة فوراً.
        </div>
        """, unsafe_allow_html=True)

# ------------------------------------------
# محتوى التاب الثالث: دليل تشغيل وإعداد تليجرام الشامل
# ------------------------------------------
with tab_telegram_setup:
    st.subheader("🛠️ الدليل الشامل لربط واستخراج بيانات التليجرام")
    
    st.markdown("""
    لضمان أن المنظومة تعمل وترسل لك الإشعارات على موبايلك أثناء تواجدك في المصيف، اتبع الآتي:
    
    ### 1️⃣ أولاً: استخراج الـ Chat ID الخاص بك (مجاني تماماً)
    * افتح تطبيق تليجرام في الموبايل أو الكمبيوتر.
    * في خانة البحث أكتب اسم البوت العالمي الموثق: `@userinfobot`.
    * اضغط على زر **Start**.
    * سيقوم البوت فوراً بإرسال بياناتك، انسخ الرقم المكتوب أمام خانة **Id** (مثال: `452445185`).
    * هذا هو الرقم الذي تضعه في خانة **Telegram Chat ID** داخل شاشة المراقبة.
    
    ### 2️⃣ ثانياً: إعداد البوت الخاص بك بالكامل (في الـ Secrets)
    إذا كنت تريد تشغيل بوت خاص بك بالكامل ليرسل التنبيهات:
    1. ابحث في تليجرام عن `@BotFather` واضغط **Start**.
    2. أرسل أمر `/newbot` ثم اختر اسماً للبوت (مثال: `MyGoldBot`).
    3. اختر يوزر نيم ينتهي بكلمة bot (مثال: `HaythamGold_bot`).
    4. سيعطيك الـ **HTTP API Token** (سلسلة طويلة من الحروف والأرقام).
    5. قم بفتح ملف الـ Secrets في الـ Streamlit Cloud وضعه بالشكل التالي:
    ```toml
    TELEGRAM_BOT_TOKEN = "ضع_التوكن_الخاص_بك_هنا"
    ```
    * **ملحوظة حرجة جداً:** يجب أن تفتح البوت الخاص بك في تليجرام وتضغط **Start** أولاً، حتى تسمح له بإرسال الرسائل إليك!
    """)

# ==========================================
# 7. محرك التحديث التلقائي اللحظي (Auto-Refresh)
# ==========================================
time.sleep(30)
st.rerun()
