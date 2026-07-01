import streamlit as st
import pandas as pd
from sqlalchemy import create_engine, text
import requests
import datetime

# ==========================================
# 1. إعدادات الصفحة والواجهة الاحترافية لـ Gold Meter Pro
# ==========================================
st.set_page_config(page_title="Gold Meter Pro", page_icon="🏅", layout="wide")

# تم إصلاح هذا السطر ليعمل فوراً بدون أخطاء التايب
st.markdown("""
    <style>
    .main-title { font-size: 34px; font-weight: bold; text-align: center; color: #D4AF37; margin-bottom: 25px; }
    .price-card { background-color: #1e2430; padding: 20px; border-radius: 12px; border-left: 5px solid #D4AF37; text-align: center; box-shadow: 2px 2px 10px rgba(0,0,0,0.3); }
    .price-card h3 { margin: 10px 0 0 0; color: #ffffff; }
    .price-card h5 { margin: 0; color: #D4AF37; }
    </style>
""", unsafe_allow_html=True)

st.markdown('<div class="main-title">🏅 منظومة الذهب الذكية - Gold Meter Pro</div>', unsafe_allow_html=True)

# ==========================================
# 2. إدارة الاتصال الآمن بالسيرفر السحابي (Supabase) via SQLAlchemy
# ==========================================
def get_db_engine():
    try:
        db = st.secrets["postgres"]
        db_url = f"postgresql://{db['user']}:{db['password']}@{db['host']}:{db['port']}/{db['database']}"
        engine = create_engine(db_url)
        return engine
    except Exception as e:
        st.error(f"❌ خطأ في قراءة بيانات الـ Secrets لقاعدة البيانات: {e}")
        return None

engine = get_db_engine()

# تهيئة الجدول تلقائياً في السيرفر لضمان عدم حدوث كراش
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
# 3. إدخال وحساب الأسعار الحالية (عالمياً ومحلياً)
# ==========================================
st.subheader("📈 أسعار الذهب والدولار اللحظية")
col_in1, col_in2 = st.columns(2)

with col_in1:
    ounce_usd = st.number_input("💵 سعر أونصة الذهب عالمياً ($):", value=3976.40, step=0.5, format="%.2f")
with col_in2:
    usd_egp = st.number_input("🏦 سعر دولار البنك المركزي (ج.م):", value=49.23, step=0.01, format="%.2f")

# الحسبة الرياضية الدقيقة للجرامات داخل السوق المصري
gold_pure_price_egp = (ounce_usd * usd_egp) / 31.10348
price_24 = round(gold_pure_price_egp, 2)
price_21 = round(gold_pure_price_egp * (21 / 24), 2)
price_18 = round(gold_pure_price_egp * (18 / 24), 2)

# عرض كروت الأسعار التفاعلية للمستخدم
c1, c2, c3, c4 = st.columns(4)
with c1:
    st.markdown(f'<div class="price-card"><h5>🌍 أونصة الذهب</h5><h3>${ounce_usd:,.2f}</h3></div>', unsafe_allow_html=True)
with c2:
    st.markdown(f'<div class="price-card"><h5>🏦 دولار المركزي</h5><h3>{usd_egp} ج.م</h3></div>', unsafe_allow_html=True)
with c3:
    st.markdown(f'<div class="price-card"><h5>✨ عيار 21</h5><h3>{price_21:,.2f} ج.م</h3></div>', unsafe_allow_html=True)
with c4:
    st.markdown(f'<div class="price-card"><h5>⚜️ عيار 18</h5><h3>{price_18:,.2f} ج.م</h3></div>', unsafe_allow_html=True)

st.divider()

# ==========================================
# 4. لوحة التحكم وتخزين الأهداف في قاعدة البيانات
# ==========================================
col_form, col_actions = st.columns([1, 1])

with col_form:
    st.subheader("🎯 تسجيل هدف جديد للمراقبة")
    carat_choice = st.selectbox("اختر العيار المستهدف:", ["عيار 24", "عيار 21", "عيار 18"])
    target_type = st.selectbox("نوع التنبيه:", ["بيع (ارتفاع السعر)", "شراء (انخفاض السعر)"])
    
    # جلب السعر الحالي للعيار تلقائياً لتسهيل الكتابة
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
                st.error(f"❌ فشل الحفظ في قاعدة البيانات: {e}")

# ==========================================
# 5. منطق فحص الأهداف وإرسال إشعارات التليجرام الفورية
# ==========================================
def send_telegram_msg(chat_id, text_msg):
    token = st.secrets.get("TELEGRAM_BOT_TOKEN")
    if not token:
        st.error("❌ مفتاح TELEGRAM_BOT_TOKEN غير متاح في الـ Secrets!")
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text_msg, "parse_mode": "Markdown"}
    try:
        res = requests.post(url, json=payload)
        return res.status_code == 200
    except Exception:
        return False

with col_actions:
    st.subheader("⚡ العمليات وفحص التنبيهات")
    
    if st.button("🔔 اختبار اتصال البوت الجديد"):
        test_msg = f"🔔 *Gold Meter Pro*\nاتصال البوت الجديد شغال تمام التمام يا هندسة! 🚀\nالوقت الحالي: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        if send_telegram_msg(user_chat_id, test_msg):
            st.success("🎯 تم إرسال رسالة الاختبار بنجاح! شيك على موبايلك.")
        else:
            st.error("❌ فشل إرسال رسالة الاختبار. تحقق من التوكن.")

    if st.button("🔍 فحص التنبيهات يدوياً الآن"):
        if engine:
            try:
                # القراءة باستخدام محرك SQLAlchemy لمنع الـ UserWarning نهائياً
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
                        # تحقق منطق الشروط بدقة
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
                                # إيقاف التنبيه بعد إرساله لعدم التكرار المزعج
                                with engine.begin() as conn:
                                    conn.execute(text("UPDATE gold_targets SET is_active = FALSE WHERE id = :id"), {"id": row_id})
                    
                    if alerts_triggered > 0:
                        st.success(f"🚀 تم إرسال ({alerts_triggered}) تنبيه بنجاح لتليجرام!")
                        st.rerun()
                    else:
                        st.info("💡 تم الفحص: السعر الحالي لم يتجاوز أو يحقق أي هدف نشط بعد.")
            except Exception as e:
                st.error(f"❌ خطأ أثناء فحص الشروط: {e}")

# ==========================================
# 6. عرض سجل الأهداف الفعالة (ببرامتر العرض المحدث)
# ==========================================
st.divider()
st.subheader("📋 سجل الأهداف المخزنة سحابياً (آخر 10 أهداف)")

if engine:
    try:
        df_view = pd.read_sql_query("SELECT id, carat_type, target_type, target_price, is_active FROM gold_targets ORDER BY id DESC LIMIT 10", engine)
        if not df_view.empty:
            # استبدال use_container_width بالبرامتر الجديد لمنع الـ Logs من الامتلاء بالتحذيرات
            st.dataframe(df_view, width="stretch")
        else:
            st.info("الداتا بيز فارغة حالياً.")
    except Exception as e:
        st.error(f"❌ تعذر جلب سجل الأهداف: {e}")
