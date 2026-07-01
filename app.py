import streamlit as st
import pandas as pd
from sqlalchemy import create_engine
import requests
import datetime

# ==========================================
# 1. إعدادات الصفحة والواجهة الاحترافية
# ==========================================
st.set_page_config(page_title="Gold Meter Pro", page_icon="🏅", layout="wide")

st.markdown("""
    <style>
    .main-title { font-size: 32px; font-weight: bold; text-align: center; color: #D4AF37; margin-bottom: 20px; }
    .price-card { background-color: #1e2430; padding: 15px; border-radius: 10px; border-left: 5px solid #D4AF37; text-align: center; }
    </style>
""", unsafe_index=True)

st.markdown('<div class="main-title">🏅 منظومة الذهب الذكية - Gold Meter Pro</div>', unsafe_allow_html=True)

# ==========================================
# 2. إدارة الاتصال بقاعدة البيانات (Supabase) via SQLAlchemy
# ==========================================
def get_db_engine():
    try:
        db = st.secrets["postgres"]
        # بناء الـ Connection String المتوافق تماماً مع Pandas الحديثة
        db_url = f"postgresql://{db['user']}:{db['password']}@{db['host']}:{db['port']}/{db['database']}"
        engine = create_engine(db_url)
        return engine
    except Exception as e:
        st.error(f"❌ خطأ في قراءة بيانات الـ Secrets لقاعدة البيانات: {e}")
        return None

engine = get_db_engine()

# دالة لإنشاء الجدول تلقائياً لو مش موجود (تأمين السيستم)
def init_db():
    if engine:
        with engine.begin() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS gold_targets (
                    id SERIAL PRIMARY KEY,
                    carat_type VARCHAR(50),
                    target_type VARCHAR(50),
                    target_price NUMERIC,
                    chat_id VARCHAR(50),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    is_active BOOLEAN DEFAULT TRUE
                );
            """)

init_db()

# ==========================================
# 3. جلب الأسعار اللحظية (عالمياً ومحلياً)
# ==========================================
def fetch_live_prices():
    """
    جلب الأسعار الحالية. يمكنك ربطها بـ API حقيقي.
    مدمج بها الأسعار الحالية من واقع لقطات الشاشة الخاصة بك كـ Fallback آمن.
    """
    try:
        # هنا يمكنك وضع الـ API الخاص بك، كمثال سنعتمد الأسعار المستقرة الحالية من لوحتك
        ounce_usd = 3976.40
        usd_egp = 49.23
        return ounce_usd, usd_egp
    except Exception:
        return 3976.40, 49.23  # قيم احتياطية بناءً على لوحة التحكم الخاصة بك

ounce_usd, usd_egp = fetch_live_prices()

# حساب أسعار العيارات بالمعادلة الرياضية الدقيقة
gold_pure_price_egp = (ounce_usd * usd_egp) / 31.10348
price_24 = round(gold_pure_price_egp, 2)
price_21 = round(gold_pure_price_egp * (21 / 24), 2)
price_18 = round(gold_pure_price_egp * (18 / 24), 2)

# عرض الأسعار الحالية في كروت أنيقة
col1, col2, col3, col4 = st.columns(4)
with col1:
    st.markdown(f'<div class="price-card"><h5>🌍 أونصة الذهب</h5><h3>${ounce_usd:,.2f}</h3></div>', unsafe_allow_html=True)
with col2:
    st.markdown(f'<div class="price-card"><h5>🏦 دولار المركزي</h5><h3>{usd_egp} ج.م</h3></div>', unsafe_allow_html=True)
with col3:
    st.markdown(f'<div class="price-card"><h5>✨ عيار 21</h5><h3>{price_21:,.2f} ج.م</h3></div>', unsafe_allow_html=True)
with col4:
    st.markdown(f'<div class="price-card"><h5>⚜️ عيار 18</h5><h3>{price_18:,.2f} ج.م</h3></div>', unsafe_allow_html=True)

st.divider()

# ==========================================
# 4. لوحة التحكم وإدخال الأهداف (UI)
# ==========================================
col_form, col_actions = st.columns([1, 1])

with col_form:
    st.subheader("🎯 تسجيل هدف جديد")
    carat_choice = st.selectbox("اختر العيار المستهدف:", ["عيار 24", "عيار 21", "عيار 18"])
    target_type = st.selectbox("نوع التنبيه:", ["بيع (ارتفاع السعر)", "شراء (انخفاض السعر)"])
    
    # تحديد السعر الحالي بناءً على اختيار العيار لتسهيل الإدخال على المستخدم
    current_selected_price = price_24 if carat_choice == "عيار 24" else (price_21 if carat_choice == "عيار 21" else price_18)
    
    target_price = st.number_input(f"سعر الهدف (السعر الحالي: {current_selected_price}):", value=float(current_selected_price), step=10.0)
    user_chat_id = st.text_input("Telegram Chat ID:", value="452445185")

    if st.button("💾 حفظ التنبيه في الداتا بيز"):
        if engine:
            try:
                with engine.begin() as conn:
                    conn.execute(
                        """
                        INSERT INTO gold_targets (carat_type, target_type, target_price, chat_id, is_active)
                        VALUES (%s, %s, %s, %s, TRUE)
                        """,
                        (carat_choice, target_type, target_price, user_chat_id)
                    )
                st.success(f"✅ تم حفظ هدف الـ {target_type} للـ {carat_choice} بنجاح عند سعر {target_price}!")
            except Exception as e:
                st.error(f"❌ فشل الحفظ: {e}")

# ==========================================
# 5. منطق إرسال تنبيهات التليجرام وفحص الشروط
# ==========================================
def send_telegram_msg(chat_id, text):
    token = st.secrets.get("TELEGRAM_BOT_TOKEN")
    if not token:
        st.error("❌ مفتاح TELEGRAM_BOT_TOKEN غير معرف في الـ Secrets!")
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    try:
        res = requests.post(url, json=payload)
        return res.status_code == 200
    except Exception as e:
        st.error(f"❌ خطأ اتصال تليجرام: {e}")
        return False

with col_actions:
    st.subheader("⚡ العمليات الفورية")
    
    if st.button("🔔 اختبار اتصال البوت الجديد"):
        test_msg = f"🔔 *Gold Meter Pro*\nاتصال البوت الجديد شغال تمام التمام يا هندسة! 🚀\nالوقت: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%M')}"
        if send_telegram_msg(user_chat_id, test_msg):
            st.success("🎯 تم إرسال رسالة الاختبار بنجاح! شيك على موبايلك.")
        else:
            st.error("❌ فشل إرسال رسالة الاختبار. تحقق من التوكن أو الـ Chat ID.")

    if st.button("🔄 فحص وتشغيل التنبيهات الآن"):
        if engine:
            try:
                # حل تحذير السطر 143 باستخدام الـ engine مباشرة
                df_active = pd.read_sql_query("SELECT * FROM gold_targets WHERE is_active = TRUE", engine)
                
                if df_active.empty:
                    st.info("لا توجد أهداف نشطة حالياً للفحص.")
                else:
                    alerts_triggered = 0
                    for index, row in df_active.iterrows():
                        # تحديد السعر الحالي المقابل للعيار في الصف
                        c_type = row['carat_type']
                        t_type = row['target_type']
                        t_price = float(row['target_price'])
                        c_id = row['chat_id']
                        row_id = row['id']
                        
                        current_local_price = price_24 if c_type == "عيار 24" else (price_21 if c_type == "عيار 21" else price_18)
                        
                        condition_met = False
                        # شرط البيع: السعر الحالي أكبر من أو يساوي المستهدف
                        if "بيع" in t_type and current_local_price >= t_price:
                            condition_met = True
                        # شرط الشراء: السعر الحالي أقل من أو يساوي المستهدف
                        elif "شراء" in t_type and current_local_price <= t_price:
                            condition_met = True
                            
                        if condition_met:
                            alert_text = (
                                f"🚨 *تنبيه ذهبي متحقق!*\n\n"
                                f"📦 *العيار:* {c_type}\n"
                                f"📈 *نوع الهدف:* {t_type}\n"
                                f"🎯 *السعر المستهدف:* {t_price:,.2f} ج.م\n"
                                f"💰 *السعر الحالي الآن:* {current_local_price:,.2f} ج.م\n\n"
                                f" الـ Gold Bot شغال ومتابع لحظة بلحظة! ✨"
                            )
                            if send_telegram_msg(c_id, alert_text):
                                alerts_triggered += 1
                                # تعطيل الهدف بعد تحققه وإرساله لعدم التكرار المزعج
                                with engine.begin() as conn:
                                    conn.execute("UPDATE gold_targets SET is_active = FALSE WHERE id = %s", (row_id,))
                    
                    if alerts_triggered > 0:
                        st.success(f"🚀 تم إرسال عدد ({alerts_triggered}) تنبيه بنجاح إلى تليجرام!")
                    else:
                        st.info("💡 تم فحص الأهداف؛ ولم يتخطى السعر الحالي أي هدف منها بعد.")
            except Exception as e:
                st.error(f"خطأ أثناء الفحص: {e}")

# ==========================================
# 6. عرض سجل الأهداف الفعالة (UI الحديث)
# ==========================================
st.divider()
st.subheader("📋 سجل الأهداف المخزنة سحابياً")

if engine:
    # جلب آخر 10 أهداف مسجلة
    df_view = pd.read_sql_query("SELECT id, carat_type, target_type, target_price, is_active FROM gold_targets ORDER BY id DESC LIMIT 10", engine)
    if not df_view.empty:
        # 🌟 التعديل السحري: استخدام width="stretch" المعتمد رسمياً بدلاً من البرامتر الملغى
        st.dataframe(df_view, width="stretch")
    else:
        st.info("الداتا بيز فارغة حالياً. قم بإضافة أهداف لتظهر هنا.")
