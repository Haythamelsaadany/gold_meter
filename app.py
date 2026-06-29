import streamlit as st
from sqlalchemy import create_engine, text
import json
import urllib.request
import urllib.parse
import pandas as pd
import yfinance as yf
import feedparser
import time
from datetime import datetime, timedelta
import threading
import asyncio

# إعداد الصفحة
st.set_page_config(page_title="Gold Meter 2026", layout="wide", page_icon="🏅")

# ==========================================
# الاتصال الآمن بقاعدة البيانات
# ==========================================
def get_engine():
    """إنشاء اتصال بقاعدة البيانات باستخدام st.secrets"""
    try:
        db = st.secrets["postgres"]
        password = urllib.parse.quote_plus(db["password"])
        url = f"postgresql://{db['user']}:{password}@{db['host']}:{db['port']}/{db['database']}"
        return create_engine(url, connect_args={"sslmode": "require"})
    except Exception as e:
        st.error(f"❌ خطأ في الاتصال بقاعدة البيانات: {e}")
        return None

@st.cache_resource
def init_db():
    """تهيئة قاعدة البيانات وإنشاء الجداول"""
    try:
        engine = get_engine()
        if not engine:
            return False
        
        with engine.connect() as conn:
            # جدول المستخدمين
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    username TEXT,
                    tg_id TEXT UNIQUE,
                    high_target NUMERIC,
                    low_target NUMERIC,
                    last_alerted_high TEXT,
                    last_alerted_low TEXT,
                    alerts_active INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """))
            
            # جدول سجل التنبيهات
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS alert_logs (
                    id SERIAL PRIMARY KEY,
                    tg_id TEXT,
                    alert_type TEXT,
                    price NUMERIC,
                    sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """))
            
            conn.commit()
            return True
    except Exception as e:
        st.error(f"❌ خطأ في تهيئة قاعدة البيانات: {e}")
        return False

# ==========================================
# دوال التعامل مع قاعدة البيانات
# ==========================================
def save_user(username, tg_id, high_target, low_target):
    """حفظ أو تحديث بيانات المستخدم"""
    try:
        engine = get_engine()
        if not engine:
            return False
        
        with engine.connect() as conn:
            # حذف السجل القديم لتجنب التعارض
            conn.execute(text("DELETE FROM users WHERE tg_id = :tg_id"), {"tg_id": tg_id})
            
            # إدراج سجل جديد
            conn.execute(text("""
                INSERT INTO users (username, tg_id, high_target, low_target, alerts_active)
                VALUES (:username, :tg_id, :high_target, :low_target, 1)
            """), {
                "username": username,
                "tg_id": tg_id,
                "high_target": float(high_target),
                "low_target": float(low_target)
            })
            conn.commit()
            return True
    except Exception as e:
        st.error(f"❌ خطأ في حفظ البيانات: {e}")
        return False

def get_user_by_tg(tg_id):
    """جلب بيانات مستخدم"""
    try:
        engine = get_engine()
        if not engine:
            return None
        
        with engine.connect() as conn:
            result = conn.execute(text("""
                SELECT username, high_target, low_target, alerts_active
                FROM users WHERE tg_id = :tg_id
            """), {"tg_id": tg_id})
            row = result.fetchone()
            return row if row else None
    except Exception as e:
        st.error(f"❌ خطأ في جلب البيانات: {e}")
        return None

def get_all_users():
    """جلب جميع المستخدمين"""
    try:
        engine = get_engine()
        if not engine:
            return []
        
        with engine.connect() as conn:
            result = conn.execute(text("""
                SELECT id, username, tg_id, high_target, low_target, 
                       last_alerted_high, last_alerted_low, alerts_active
                FROM users ORDER BY created_at DESC
            """))
            return result.fetchall()
    except Exception as e:
        st.error(f"❌ خطأ في جلب المستخدمين: {e}")
        return []

def update_alert_status(tg_id, alert_type, today_date):
    """تحديث حالة التنبيه"""
    try:
        engine = get_engine()
        if not engine:
            return False
        
        with engine.connect() as conn:
            if alert_type == "high":
                conn.execute(text("""
                    UPDATE users SET last_alerted_high = :today
                    WHERE tg_id = :tg_id
                """), {"today": today_date, "tg_id": tg_id})
            elif alert_type == "low":
                conn.execute(text("""
                    UPDATE users SET last_alerted_low = :today
                    WHERE tg_id = :tg_id
                """), {"today": today_date, "tg_id": tg_id})
            
            # تسجيل في سجل التنبيهات
            conn.execute(text("""
                INSERT INTO alert_logs (tg_id, alert_type, price)
                VALUES (:tg_id, :alert_type, :price)
            """), {
                "tg_id": tg_id,
                "alert_type": alert_type,
                "price": get_current_price()
            })
            
            conn.commit()
            return True
    except Exception as e:
        print(f"خطأ في تحديث حالة التنبيه: {e}")
        return False

def toggle_alerts(tg_id, active):
    """تفعيل أو إيقاف التنبيهات"""
    try:
        engine = get_engine()
        if not engine:
            return False
        
        with engine.connect() as conn:
            conn.execute(text("""
                UPDATE users SET alerts_active = :active
                WHERE tg_id = :tg_id
            """), {"active": 1 if active else 0, "tg_id": tg_id})
            conn.commit()
            return True
    except Exception as e:
        st.error(f"❌ خطأ في تحديث حالة التنبيهات: {e}")
        return False

def reset_user_alerts(tg_id):
    """إعادة تعيين تنبيهات المستخدم"""
    try:
        engine = get_engine()
        if not engine:
            return False
        
        with engine.connect() as conn:
            conn.execute(text("""
                UPDATE users SET last_alerted_high = NULL, last_alerted_low = NULL
                WHERE tg_id = :tg_id
            """), {"tg_id": tg_id})
            conn.commit()
            return True
    except Exception as e:
        st.error(f"❌ خطأ في إعادة تعيين التنبيهات: {e}")
        return False

def delete_user(tg_id):
    """حذف مستخدم"""
    try:
        engine = get_engine()
        if not engine:
            return False
        
        with engine.connect() as conn:
            conn.execute(text("DELETE FROM users WHERE tg_id = :tg_id"), {"tg_id": tg_id})
            conn.commit()
            return True
    except Exception as e:
        st.error(f"❌ خطأ في حذف المستخدم: {e}")
        return False

# ==========================================
# جلب البيانات
# ==========================================
@st.cache_data(ttl=60)
def fetch_market_data():
    """جلب بيانات الذهب والدولار"""
    gold_price = 2330.0
    usd_price = 49.22
    
    try:
        with urllib.request.urlopen("https://api.gold-api.com/price/XAU", timeout=5) as r:
            data = json.load(r)
            if data and 'price' in data:
                gold_price = float(data['price'])
    except:
        pass
    
    try:
        with urllib.request.urlopen("https://open.er-api.com/v6/latest/USD", timeout=5) as r:
            data = json.load(r)
            if data and 'rates' in data and 'EGP' in data['rates']:
                usd_price = float(data['rates']['EGP'])
    except:
        pass
    
    return gold_price, usd_price

def get_current_price():
    """جلب سعر جرام 21 الحالي"""
    gold, usd = fetch_market_data()
    gram21 = ((gold * usd) / 31.1035) * (21/24)
    return round(gram21, 2)

# ==========================================
# إرسال تنبيهات التليجرام
# ==========================================
def send_telegram_alert(tg_id, message):
    """إرسال تنبيه عبر تليجرام"""
    try:
        bot_token = st.secrets.get("TELEGRAM_BOT_TOKEN", "")
        if not bot_token:
            return False
        
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        payload = urllib.parse.urlencode({
            "chat_id": tg_id,
            "text": message,
            "parse_mode": "HTML"
        }).encode("utf-8")
        
        req = urllib.request.Request(url, data=payload)
        with urllib.request.urlopen(req, timeout=5):
            return True
    except Exception as e:
        print(f"خطأ في إرسال رسالة تليجرام: {e}")
        return False

# ==========================================
# نظام التنبيهات
# ==========================================
def check_and_send_alerts():
    """فحص التنبيهات وإرسالها"""
    try:
        current_price = get_current_price()
        today_str = datetime.now().strftime('%Y-%m-%d')
        
        # جلب جميع المستخدمين المفعلين
        users = get_all_users()
        if not users:
            return "لا يوجد مستخدمين"
        
        alerts_sent = []
        
        for user in users:
            user_id, username, tg_id, high_target, low_target, last_high, last_low, active = user
            
            if not tg_id or active == 0:
                continue
            
            # التحقق من التنبيهات
            high_alert = current_price >= float(high_target) and last_high != today_str
            low_alert = current_price <= float(low_target) and last_low != today_str
            
            if high_alert:
                message = f"""🚀 <b>تنبيه اختراق الهدف الأعلى!</b>
                
👤 المستخدم: {username}
💰 السعر الحالي: {current_price:,.2f} ج.م
🎯 هدف البيع: {float(high_target):,.0f} ج.م

📈 تم تجاوز هدف البيع المحدد!"""
                
                if send_telegram_alert(tg_id, message):
                    update_alert_status(tg_id, "high", today_str)
                    alerts_sent.append(f"✅ HIGH لـ {username}")
            
            if low_alert:
                message = f"""🔻 <b>تنبيه كسر القاع الأدنى!</b>

👤 المستخدم: {username}
💰 السعر الحالي: {current_price:,.2f} ج.م
🎯 هدف الشراء: {float(low_target):,.0f} ج.م

📉 تم كسر هدف الشراء المحدد!"""
                
                if send_telegram_alert(tg_id, message):
                    update_alert_status(tg_id, "low", today_str)
                    alerts_sent.append(f"✅ LOW لـ {username}")
        
        if alerts_sent:
            return f"✅ تم إرسال: {', '.join(alerts_sent)}"
        else:
            return f"ℹ️ لا توجد تنبيهات جديدة. السعر الحالي: {current_price:,.2f} ج.م"
            
    except Exception as e:
        return f"❌ خطأ: {e}"

# ==========================================
# التطبيق الرئيسي
# ==========================================
def main():
    # تهيئة قاعدة البيانات
    if not init_db():
        st.error("فشل في تهيئة قاعدة البيانات")
        return
    
    st.title("🏅 Gold Meter - لوحة تحليل الذهب المتكاملة")
    
    # جلب البيانات
    gold, usd = fetch_market_data()
    gram21 = ((gold * usd) / 31.1035) * (21/24)
    
    # عرض الأسعار
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("🌍 أوقية الذهب", f"${gold:,.2f}")
    col2.metric("💵 سعر الدولار", f"{usd:.2f} ج.م")
    col3.metric("🏅 جرام عيار 21", f"{gram21:,.2f} ج.م")
    
    # حالة التنبيهات
    if "tg_id" in st.session_state and st.session_state["tg_id"]:
        user_data = get_user_by_tg(st.session_state["tg_id"])
        if user_data:
            active = user_data[3]
            status = "🟢 مفعلة" if active == 1 else "🔴 موقفة"
            col4.metric("🔔 التنبيهات", status)
    
    st.divider()
    
    # التبويبات
    tab1, tab2, tab3, tab4 = st.tabs(["📊 التحليل الفني", "📰 الأخبار", "🔔 التنبيهات", "📋 الإدارة"])
    
    # ===== تبويب التحليل =====
    with tab1:
        st.subheader("📈 تحركات الذهب")
        
        try:
            hist = yf.Ticker("GC=F").history(period="1mo")
            if not hist.empty:
                st.line_chart(hist['Close'])
                
                # إحصائيات
                col1, col2, col3 = st.columns(3)
                col1.metric("أعلى سعر", f"${hist['Close'].max():.2f}")
                col2.metric("أدنى سعر", f"${hist['Close'].min():.2f}")
                col3.metric("متوسط السعر", f"${hist['Close'].mean():.2f}")
            else:
                st.info("لا توجد بيانات تاريخية متاحة")
        except Exception as e:
            st.warning(f"⚠️ خطأ في جلب بيانات الرسم البياني: {e}")
    
    # ===== تبويب الأخبار =====
    with tab2:
        st.subheader("📰 آخر أخبار الذهب")
        
        try:
            feed = feedparser.parse("https://www.cnbcarabia.com/rss")
            if feed.entries:
                for entry in feed.entries[:10]:
                    published = entry.get('published', 'تاريخ غير معروف')
                    st.markdown(f"🔹 **[{entry.title}]({entry.link})**")
                    st.caption(f"📅 {published}")
                    st.divider()
            else:
                st.info("لا توجد أخبار حالياً")
        except Exception as e:
            st.warning(f"⚠️ خطأ في جلب الأخبار: {e}")
    
    # ===== تبويب التنبيهات =====
    with tab3:
        st.subheader("⚙️ إعدادات التنبيهات")
        
        # نموذج إدخال البيانات
        col1, col2 = st.columns(2)
        
        with col1:
            username = st.text_input("👤 الاسم", value=st.session_state.get("username", ""))
            tg_id = st.text_input("🆔 معرف التليجرام (Chat ID)", value=st.session_state.get("tg_id", ""))
        
        with col2:
            high_target = st.number_input("🚀 هدف البيع (جني أرباح)", 
                                        value=float(st.session_state.get("high_target", 6000.0)), 
                                        step=50.0,
                                        help="سيتم إرسال تنبيه عندما يصل السعر لهذا الرقم أو أعلى")
            
            low_target = st.number_input("🔻 هدف الشراء", 
                                       value=float(st.session_state.get("low_target", 5000.0)), 
                                       step=50.0,
                                       help="سيتم إرسال تنبيه عندما يصل السعر لهذا الرقم أو أقل")
        
        # أزرار التحكم
        col_btn1, col_btn2, col_btn3, col_btn4 = st.columns(4)
        
        with col_btn1:
            if st.button("💾 حفظ الإعدادات", use_container_width=True):
                if username and tg_id:
                    if save_user(username, tg_id, high_target, low_target):
                        st.session_state["username"] = username
                        st.session_state["tg_id"] = tg_id
                        st.session_state["high_target"] = high_target
                        st.session_state["low_target"] = low_target
                        st.balloons()
                        st.success(f"✅ تم حفظ الإعدادات بنجاح!\nالسعر الحالي: {gram21:,.2f} ج.م")
                        st.rerun()
                else:
                    st.error("❌ يرجى إدخال الاسم ومعرف التليجرام")
        
        with col_btn2:
            if st.button("🔔 فحص التنبيهات", use_container_width=True, type="primary"):
                if tg_id:
                    with st.spinner("جاري فحص التنبيهات..."):
                        result = check_and_send_alerts()
                        st.info(result)
                        if "✅" in result:
                            st.balloons()
                else:
                    st.error("❌ يرجى إدخال معرف التليجرام أولاً")
        
        with col_btn3:
            if st.button("🔄 إعادة تعيين", use_container_width=True):
                if tg_id:
                    if reset_user_alerts(tg_id):
                        st.success("✅ تم إعادة تعيين التنبيهات!")
                        st.rerun()
                else:
                    st.error("❌ يرجى إدخال معرف التليجرام أولاً")
        
        with col_btn4:
            if st.button("⏸️ إيقاف/تشغيل", use_container_width=True):
                if tg_id:
                    user_data = get_user_by_tg(tg_id)
                    if user_data:
                        active = user_data[3]
                        new_status = not bool(active)
                        if toggle_alerts(tg_id, new_status):
                            status_text = "مفعلة" if new_status else "موقفة"
                            st.success(f"✅ تم {status_text} التنبيهات!")
                            st.rerun()
                else:
                    st.error("❌ يرجى إدخال معرف التليجرام أولاً")
        
        # عرض معلومات المستخدم الحالي
        if tg_id:
            user_data = get_user_by_tg(tg_id)
            if user_data:
                st.divider()
                st.subheader("📊 معلومات المستخدم")
                
                col_info1, col_info2, col_info3, col_info4 = st.columns(4)
                with col_info1:
                    st.info(f"👤 **الاسم:** {user_data[0]}")
                with col_info2:
                    st.info(f"🎯 **هدف البيع:** {user_data[1]:,.0f} ج.م")
                with col_info3:
                    st.info(f"🎯 **هدف الشراء:** {user_data[2]:,.0f} ج.م")
                with col_info4:
                    status = "🟢 مفعلة" if user_data[3] == 1 else "🔴 موقفة"
                    st.info(f"🔔 **الحالة:** {status}")
                
                # عرض حالة السعر الحالي
                if gram21 >= float(user_data[1]):
                    st.warning(f"⚠️ السعر الحالي ({gram21:,.2f} ج.م) تجاوز هدف البيع ({user_data[1]:,.0f} ج.م)")
                elif gram21 <= float(user_data[2]):
                    st.warning(f"⚠️ السعر الحالي ({gram21:,.2f} ج.م) أقل من هدف الشراء ({user_data[2]:,.0f} ج.م)")
                else:
                    st.success(f"✅ السعر الحالي ({gram21:,.2f} ج.م) في النطاق الآمن")
    
    # ===== تبويب الإدارة =====
    with tab4:
        st.subheader("📋 إدارة المستخدمين")
        
        # عرض جميع المستخدمين
        users = get_all_users()
        if users:
            # تحويل البيانات إلى DataFrame
            df = pd.DataFrame(users, columns=[
                "ID", "الاسم", "التليجرام", "هدف البيع", "هدف الشراء",
                "آخر تنبيه HIGH", "آخر تنبيه LOW", "مفعل"
            ])
            df["مفعل"] = df["مفعل"].apply(lambda x: "✅" if x == 1 else "❌")
            st.dataframe(df, use_container_width=True)
            
            # حذف مستخدم
            st.subheader("🗑️ حذف مستخدم")
            tg_id_delete = st.text_input("أدخل معرف التليجرام للحذف")
            if st.button("حذف المستخدم", type="secondary"):
                if tg_id_delete:
                    if delete_user(tg_id_delete):
                        st.success("✅ تم حذف المستخدم بنجاح")
                        st.rerun()
                else:
                    st.error("❌ يرجى إدخال معرف التليجرام")
        else:
            st.info("ℹ️ لا يوجد مستخدمين مسجلين")

    # تذييل الصفحة
    st.markdown("---")
    st.markdown("""
        <div style='text-align: center; color: #666; padding: 20px;'>
            © Techno logic 2026. Haytham Elsaadany<br>
            <small>جميع الحقوق محفوظة</small>
        </div>
    """, unsafe_allow_html=True)

if __name__ == "__main__":
    main()
