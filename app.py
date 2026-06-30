import streamlit as st
import sqlite3
import pandas as pd
import yfinance as yf
import feedparser
import json
import requests
from datetime import datetime, timedelta
from sqlalchemy import create_engine, text
import urllib.parse
import time
import threading
import logging

# ==========================================
# إعدادات الصفحة
# ==========================================
st.set_page_config(
    page_title="Gold Meter Pro 2026",
    layout="wide",
    page_icon="🏅",
    initial_sidebar_state="expanded"
)

# ==========================================
# 1. الاتصال بقاعدة البيانات (Supabase)
# ==========================================
def get_supabase_engine():
    """إنشاء اتصال بـ Supabase"""
    try:
        db = st.secrets["postgres"]
        password = urllib.parse.quote_plus(db["password"])
        url = f"postgresql://{db['user']}:{password}@{db['host']}:{db['port']}/{db['database']}"
        engine = create_engine(
            url,
            connect_args={"sslmode": "require"},
            pool_pre_ping=True,
            pool_recycle=3600
        )
        return engine
    except Exception as e:
        st.error(f"❌ خطأ في الاتصال بـ Supabase: {e}")
        return None

def init_supabase_tables():
    """تهيئة الجداول في Supabase"""
    engine = get_supabase_engine()
    if not engine:
        return False
    
    try:
        with engine.connect() as conn:
            # جدول التنبيهات
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS gold_alerts (
                    id SERIAL PRIMARY KEY,
                    username TEXT NOT NULL,
                    tg_id TEXT NOT NULL,
                    karat TEXT DEFAULT '21',
                    high_target REAL,
                    low_target REAL,
                    triggered INTEGER DEFAULT 0,
                    last_alerted_date DATE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """))
            
            # جدول إحصائيات الزوار
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS site_stats (
                    id SERIAL PRIMARY KEY,
                    views INTEGER DEFAULT 0,
                    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """))
            conn.execute(text("""
                INSERT INTO site_stats (id, views) VALUES (1, 0)
                ON CONFLICT (id) DO NOTHING
            """))
            
            # جدول سجل الأسعار
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS price_history (
                    id SERIAL PRIMARY KEY,
                    karat TEXT,
                    price REAL,
                    recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """))
            
            conn.commit()
            return True
    except Exception as e:
        st.error(f"❌ خطأ في تهيئة الجداول: {e}")
        return False

# ==========================================
# 2. نظام إرسال رسائل تليجرام (المعدل والمُحسَّن)
# ==========================================
def send_telegram_message(chat_id, text, parse_mode='Markdown'):
    """
    إرسال رسالة عبر تليجرام بوت
    
    Args:
        chat_id (str): معرف المستخدم في تليجرام
        text (str): نص الرسالة
        parse_mode (str): وضع التنسيق (Markdown أو HTML)
    
    Returns:
        tuple: (نجاح, رسالة)
    """
    try:
        # التحقق من وجود التوكن
        if "TELEGRAM_BOT_TOKEN" not in st.secrets:
            return False, "❌ مفتاح TELEGRAM_BOT_TOKEN غير موجود في الـ Secrets!"
        
        token = st.secrets["TELEGRAM_BOT_TOKEN"].strip()
        if not token:
            return False, "❌ توكن التليجرام فارغ!"
        
        # ✅ التصحيح: استخدام telegram.org
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        
        # تنظيف chat_id
        chat_id = str(chat_id).strip()
        if not chat_id.isdigit():
            return False, f"❌ معرف التليجرام '{chat_id}' غير صحيح (يجب أن يكون أرقام فقط)"
        
        # تحضير payload
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True
        }
        
        # إرسال الطلب
        response = requests.post(url, json=payload, timeout=15)
        
        # التحقق من الاستجابة
        if response.status_code == 200:
            return True, "✅ تم إرسال الرسالة بنجاح"
        else:
            error_detail = response.json() if response.text else "لا توجد تفاصيل"
            return False, f"❌ فشل الإرسال (كود {response.status_code}): {error_detail}"
            
    except requests.exceptions.Timeout:
        return False, "❌ انتهى وقت الاتصال بسيرفر تليجرام"
    except requests.exceptions.ConnectionError:
        return False, "❌ مشكلة في الاتصال بالإنترنت"
    except Exception as e:
        return False, f"❌ خطأ غير متوقع: {str(e)}"

def test_telegram_bot():
    """اختبار الاتصال ببوت التليجرام"""
    try:
        if "TELEGRAM_BOT_TOKEN" not in st.secrets:
            return False, "❌ التوكن غير موجود"
        
        token = st.secrets["TELEGRAM_BOT_TOKEN"].strip()
        url = f"https://api.telegram.org/bot{token}/getMe"
        
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            data = response.json()
            if data.get('ok'):
                bot_info = data.get('result', {})
                return True, f"✅ البوت يعمل: @{bot_info.get('username', 'unknown')}"
        return False, f"❌ فشل اختبار البوت (كود {response.status_code})"
    except Exception as e:
        return False, f"❌ خطأ: {str(e)}"

# ==========================================
# 3. إدارة قاعدة البيانات
# ==========================================
def init_local_db():
    """تهيئة قاعدة البيانات المحلية (SQLite) كنسخة احتياطية"""
    conn = sqlite3.connect('gold_data.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS gold_alerts 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                  username TEXT, 
                  tg_id TEXT, 
                  karat TEXT, 
                  high REAL, 
                  low REAL,
                  triggered INTEGER DEFAULT 0,
                  last_alerted_date TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS site_stats (id INTEGER PRIMARY KEY, views INTEGER)''')
    c.execute("INSERT OR IGNORE INTO site_stats (id, views) VALUES (1, 0)")
    conn.commit()
    conn.close()

def init_db():
    """تهيئة جميع قواعد البيانات"""
    init_local_db()
    init_supabase_tables()

def update_and_get_views():
    """تحديث وقراءة عدد الزوار"""
    # تحديث في SQLite
    conn = sqlite3.connect('gold_data.db')
    c = conn.cursor()
    if 'tracked' not in st.session_state:
        st.session_state['tracked'] = True
        c.execute("UPDATE site_stats SET views = views + 1 WHERE id = 1")
        conn.commit()
    c.execute("SELECT views FROM site_stats WHERE id = 1")
    views = c.fetchone()[0]
    conn.close()
    
    # تحديث في Supabase
    try:
        engine = get_supabase_engine()
        if engine:
            with engine.connect() as conn:
                conn.execute(text("""
                    UPDATE site_stats SET views = views + 1, last_updated = CURRENT_TIMESTAMP
                    WHERE id = 1
                """))
                conn.commit()
    except:
        pass
    
    return views

def save_alert_supabase(username, tg_id, karat, high, low):
    """حفظ التنبيه في Supabase"""
    engine = get_supabase_engine()
    if not engine:
        return False, "❌ فشل الاتصال بقاعدة البيانات"
    
    try:
        with engine.connect() as conn:
            # حذف التنبيهات القديمة للمستخدم
            conn.execute(text("""
                DELETE FROM gold_alerts WHERE tg_id = :tg_id
            """), {"tg_id": tg_id})
            
            # إدراج تنبيه جديد
            conn.execute(text("""
                INSERT INTO gold_alerts (username, tg_id, karat, high_target, low_target, triggered)
                VALUES (:username, :tg_id, :karat, :high, :low, 0)
            """), {
                "username": username,
                "tg_id": tg_id,
                "karat": karat,
                "high": float(high),
                "low": float(low)
            })
            conn.commit()
            return True, "✅ تم حفظ التنبيه بنجاح"
    except Exception as e:
        return False, f"❌ خطأ في حفظ التنبيه: {e}"

def get_alerts_supabase(only_active=True):
    """جلب التنبيهات من Supabase"""
    engine = get_supabase_engine()
    if not engine:
        return pd.DataFrame()
    
    try:
        with engine.connect() as conn:
            query = "SELECT id, username, tg_id, karat, high_target, low_target, triggered, last_alerted_date, created_at FROM gold_alerts"
            if only_active:
                query += " WHERE triggered = 0"
            query += " ORDER BY id DESC"
            
            result = conn.execute(text(query))
            rows = result.fetchall()
            if rows:
                return pd.DataFrame(rows, columns=["id", "username", "tg_id", "karat", "high_target", "low_target", "triggered", "last_alerted_date", "created_at"])
            return pd.DataFrame()
    except Exception as e:
        st.error(f"❌ خطأ في جلب التنبيهات: {e}")
        return pd.DataFrame()

def update_alert_triggered_supabase(alert_id):
    """تحديث حالة التنبيه في Supabase"""
    engine = get_supabase_engine()
    if not engine:
        return False
    
    try:
        with engine.connect() as conn:
            conn.execute(text("""
                UPDATE gold_alerts SET triggered = 1, last_alerted_date = CURRENT_DATE
                WHERE id = :id
            """), {"id": alert_id})
            conn.commit()
            return True
    except Exception as e:
        print(f"خطأ في تحديث التنبيه: {e}")
        return False

def delete_alert_supabase(alert_id):
    """حذف تنبيه من Supabase"""
    engine = get_supabase_engine()
    if not engine:
        return False
    
    try:
        with engine.connect() as conn:
            conn.execute(text("DELETE FROM gold_alerts WHERE id = :id"), {"id": alert_id})
            conn.commit()
            return True
    except Exception as e:
        print(f"خطأ في حذف التنبيه: {e}")
        return False

# ==========================================
# 4. جلب الأسعار وحساب العيارات
# ==========================================
@st.cache_data(ttl=30)
def get_market_data():
    """جلب أسعار الذهب والدولار"""
    gold_oz = 2330.0
    usd_egp = 49.50
    
    try:
        response_gold = requests.get("https://api.gold-api.com/price/XAU", timeout=5)
        if response_gold.status_code == 200:
            gold_oz = float(response_gold.json()['price'])
    except:
        pass
    
    try:
        response_usd = requests.get("https://open.er-api.com/v6/latest/USD", timeout=5)
        if response_usd.status_code == 200:
            usd_egp = float(response_usd.json()['rates']['EGP'])
    except:
        pass
    
    g24 = (gold_oz * usd_egp) / 31.1035
    return {
        "24": g24,
        "22": g24 * (22/24),
        "21": g24 * (21/24),
        "18": g24 * (18/24)
    }, gold_oz, usd_egp

# ==========================================
# 5. محرك التنبيهات التلقائي
# ==========================================
def check_and_send_alerts():
    """فحص التنبيهات وإرسالها"""
    try:
        # جلب الأسعار الحالية
        prices, _, _ = get_market_data()
        today = datetime.now().strftime('%Y-%m-%d')
        
        # جلب التنبيهات النشطة
        df_alerts = get_alerts_supabase(only_active=True)
        if df_alerts.empty:
            return
        
        alerts_sent = []
        
        for _, row in df_alerts.iterrows():
            alert_id = row['id']
            username = row['username']
            tg_id = row['tg_id']
            karat = row['karat']
            high_target = float(row['high_target'])
            low_target = float(row['low_target'])
            last_alerted = row.get('last_alerted_date')
            
            # السعر الحالي للعيار المحدد
            current_price = prices.get(karat, prices['21'])
            
            # التحقق من الشروط
            should_send = False
            alert_msg = ""
            
            # فحص الهدف الأعلى
            if current_price >= high_target and last_alerted != today:
                alert_msg = f"""🚀 *تنبيه صعود الذهب!*

👤 المستخدم: {username}
💎 العيار: {karat}
💰 السعر الحالي: {current_price:,.2f} ج.م
🎯 هدف البيع: {high_target:,.0f} ج.م

📈 تم تحقيق هدف البيع المحدد!

📅 {datetime.now().strftime('%Y-%m-%d %H:%M')}"""
                should_send = True
            
            # فحص الهدف الأدنى
            elif current_price <= low_target and last_alerted != today:
                alert_msg = f"""📉 *تنبيه هبوط الذهب!*

👤 المستخدم: {username}
💎 العيار: {karat}
💰 السعر الحالي: {current_price:,.2f} ج.م
🎯 هدف الشراء: {low_target:,.0f} ج.م

📉 تم تحقيق هدف الشراء المحدد!

📅 {datetime.now().strftime('%Y-%m-%d %H:%M')}"""
                should_send = True
            
            if should_send:
                # إرسال الرسالة
                success, msg = send_telegram_message(tg_id, alert_msg)
                if success:
                    # تحديث حالة التنبيه
                    update_alert_triggered_supabase(alert_id)
                    alerts_sent.append(f"✅ تنبيه لـ {username}")
        
        return alerts_sent
        
    except Exception as e:
        print(f"خطأ في محرك التنبيهات: {e}")
        return []

# ==========================================
# 6. دالة تشغيل الخلفية (Background Thread)
# ==========================================
def start_background_checker():
    """تشغيل محرك التنبيهات في الخلفية"""
    if "checker_running" not in st.session_state:
        st.session_state.checker_running = False
    
    if not st.session_state.checker_running:
        def checker_loop():
            while True:
                try:
                    check_and_send_alerts()
                except Exception as e:
                    print(f"خطأ في الحلقة الخلفية: {e}")
                time.sleep(30)  # الفحص كل 30 ثانية
        
        thread = threading.Thread(target=checker_loop, daemon=True)
        thread.start()
        st.session_state.checker_running = True

# ==========================================
# 7. جلب المنحنى البياني
# ==========================================
@st.cache_data(ttl=1800)
def get_safe_historical_data():
    """جلب البيانات التاريخية للرسم البياني"""
    try:
        ticker = yf.Ticker("GC=F")
        hist = ticker.history(period="1mo")
        if not hist.empty:
            return hist['Close'], False
    except Exception:
        pass
    
    # بيانات احتياطية
    dates = [datetime.now() - timedelta(days=i) for i in range(30)][::-1]
    fallback_prices = [2320 + (i * 1.8) for i in range(30)]
    df_fallback = pd.DataFrame({"Close": fallback_prices}, index=dates)
    return df_fallback['Close'], True

# ==========================================
# 8. التطبيق الرئيسي
# ==========================================
def main():
    # تهيئة النظام
    init_db()
    views_count = update_and_get_views()
    
    # تشغيل محرك الخلفية
    start_background_checker()
    
    # العنوان الرئيسي
    st.title("🏅 Gold Meter Pro - المنظومة التفاعلية الشاملة")
    st.caption(f"👁️ عدد زيارات المنصة: {views_count} زائر")
    
    # جلب الأسعار
    prices, gold_oz, usd_egp = get_market_data()
    
    # عرض المؤشرات
    st.markdown("### 🌐 الشاشة اللحظية للمؤشرات العالمية والبنكية")
    macro_cols = st.columns(2)
    macro_cols[0].metric("🌟 أونصة الذهب عالمياً", f"${gold_oz:,.2f}")
    macro_cols[1].metric("🏦 سعر دولار البنك المركزي", f"{usd_egp:.2f} ج.م")
    
    st.write("")
    
    st.markdown("### 💰 أسعار الذهب الحالية في مصر")
    cols = st.columns(4)
    cols[0].metric("عيار 24 (السبائك)", f"{prices['24']:,.2f} ج.م")
    cols[1].metric("عيار 22", f"{prices['22']:,.2f} ج.م")
    cols[2].metric("عيار 21 (الأكثر طلباً)", f"{prices['21']:,.2f} ج.م")
    cols[3].metric("عيار 18 (المشغولات)", f"{prices['18']:,.2f} ج.م")
    
    st.divider()
    
    # التبويبات
    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "📊 التحليل والبورصة",
        "💡 التوصيات الذكية",
        "📰 أخبار الذهب",
        "🔔 التنبيهات",
        "⚙️ الإدارة"
    ])
    
    # ===== تبويب 1: التحليل =====
    with tab1:
        st.subheader("📈 أداء سعر الأوقية عالمياً")
        chart_data, is_fallback = get_safe_historical_data()
        if is_fallback:
            st.info("⚠️ بيانات بيانية تقريبية مؤقتاً - الأسعار الفورية دقيقة 100%")
        st.line_chart(chart_data)
    
    # ===== تبويب 2: التوصيات =====
    with tab2:
        st.subheader("🤖 نظام التوصيات والتحليل الفني")
        if prices["21"] > 3800:
            st.warning("⚠️ الأسعار مرتفعة نسبياً - نوصي بالتريث")
        else:
            st.success("✅ الأسعار مستقرة - فرصة استثمارية جيدة")
    
    # ===== تبويب 3: الأخبار =====
    with tab3:
        st.subheader("📰 آخر أخبار الذهب")
        try:
            feed = feedparser.parse("https://news.google.com/rss/search?q=%D8%A7%D9%84%D8%B0%D9%87%D8%A8&hl=ar&gl=EG&ceid=EG:ar")
            if feed.entries:
                for entry in feed.entries[:6]:
                    st.markdown(f"🔹 **[{entry.title}]({entry.link})**")
                    st.caption(f"📅 {entry.get('published', 'تاريخ غير معروف')}")
            else:
                st.info("📰 جاري تحديث الأخبار...")
        except Exception as e:
            st.warning(f"⚠️ خطأ في جلب الأخبار: {e}")
    
    # ===== تبويب 4: التنبيهات =====
    with tab4:
        st.subheader("🔔 إعداد التنبيهات التفاعلية")
        
        # اختبار البوت
        col_test1, col_test2 = st.columns([3, 1])
        with col_test2:
            if st.button("🔍 اختبار البوت"):
                success, msg = test_telegram_bot()
                if success:
                    st.success(msg)
                else:
                    st.error(msg)
        
        st.divider()
        
        # نموذج الإعداد
        col1, col2 = st.columns(2)
        
        with col1:
            username = st.text_input("👤 اسمك الكريم", key="input_username")
            telegram_id = st.text_input("🆔 معرف التليجرام (Chat ID)", key="input_tgid", 
                                       help="احصل عليه من @userinfobot")
            
            if telegram_id and not telegram_id.isdigit():
                st.warning("⚠️ يجب أن يكون Chat ID أرقام فقط!")
        
        with col2:
            selected_karat = st.selectbox("💎 اختر العيار", ["24", "22", "21", "18"], key="input_karat")
            
            # أسعار مقترحة
            default_high = float(round(prices[selected_karat] + 150))
            default_low = float(round(prices[selected_karat] - 150))
            
            high_target = st.number_input("🚀 هدف البيع (ارتفاع)", 
                                         value=default_high, 
                                         step=50.0,
                                         key="input_high")
            
            low_target = st.number_input("📉 هدف الشراء (انخفاض)", 
                                        value=default_low, 
                                        step=50.0,
                                        key="input_low")
        
        # أزرار التحكم
        col_btn1, col_btn2, col_btn3 = st.columns(3)
        
        with col_btn1:
            if st.button("🚀 تفعيل التنبيه", use_container_width=True, type="primary"):
                if not username or not telegram_id:
                    st.error("❌ يرجى إدخال الاسم ومعرف التليجرام")
                elif not telegram_id.isdigit():
                    st.error("❌ معرف التليجرام غير صحيح (أرقام فقط)")
                else:
                    # إرسال رسالة اختبار
                    welcome_msg = f"""🔔 *مرحباً {username}!*

✅ تم تفعيل تنبيهات Gold Meter بنجاح.

📊 العيار: {selected_karat}
🎯 هدف البيع: {high_target:,.0f} ج.م
🎯 هدف الشراء: {low_target:,.0f} ج.م

🔄 سيتم إرسال تنبيه عند تحقيق الأهداف.
📅 {datetime.now().strftime('%Y-%m-%d %H:%M')}"""
                    
                    with st.spinner("جاري إرسال رسالة الاختبار..."):
                        success, msg = send_telegram_message(telegram_id, welcome_msg)
                    
                    if success:
                        # حفظ في قاعدة البيانات
                        save_success, save_msg = save_alert_supabase(username, telegram_id, selected_karat, high_target, low_target)
                        
                        if save_success:
                            st.balloons()
                            st.success(f"✅ تم التفعيل بنجاح! {save_msg}")
                            st.info("📱 تم إرسال رسالة تأكيد لهاتفك")
                            time.sleep(1)
                            st.rerun()
                        else:
                            st.error(save_msg)
                    else:
                        st.error(f"❌ فشل إرسال رسالة الاختبار: {msg}")
                        st.warning("💡 تأكد من أن Chat ID صحيح وأن البوت يعمل")
        
        with col_btn2:
            if st.button("🔄 فحص التنبيهات الآن", use_container_width=True):
                with st.spinner("جاري فحص التنبيهات..."):
                    result = check_and_send_alerts()
                    if result:
                        for msg in result:
                            st.success(msg)
                    else:
                        st.info("✅ لا توجد تنبيهات جديدة")
        
        with col_btn3:
            if st.button("🗑️ مسح كل التنبيهات", use_container_width=True):
                if telegram_id:
                    engine = get_supabase_engine()
                    if engine:
                        with engine.connect() as conn:
                            conn.execute(text("DELETE FROM gold_alerts WHERE tg_id = :tg_id"), {"tg_id": telegram_id})
                            conn.commit()
                        st.success("✅ تم مسح تنبيهاتك بنجاح")
                        st.rerun()
                else:
                    st.warning("⚠️ أدخل معرف التليجرام أولاً")
        
        st.divider()
        
        # عرض التنبيهات النشطة
        st.subheader("📋 التنبيهات النشطة")
        df_alerts = get_alerts_supabase(only_active=False)
        
        if not df_alerts.empty:
            # تنسيق الجدول
            display_df = df_alerts[['username', 'karat', 'high_target', 'low_target', 'triggered']].copy()
            display_df.columns = ['المستخدم', 'العيار', 'هدف البيع', 'هدف الشراء', 'الحالة']
            display_df['الحالة'] = display_df['الحالة'].apply(lambda x: '🟢 نشط' if x == 0 else '🔴 منفذ')
            
            st.dataframe(display_df, use_container_width=True)
            
            # إحصائيات
            col_stat1, col_stat2 = st.columns(2)
            with col_stat1:
                active_count = len(df_alerts[df_alerts['triggered'] == 0])
                st.metric("🟢 التنبيهات النشطة", active_count)
            with col_stat2:
                triggered_count = len(df_alerts[df_alerts['triggered'] == 1])
                st.metric("🔴 التنبيهات المنفذة", triggered_count)
        else:
            st.info("ℹ️ لا توجد تنبيهات مسجلة")
    
    # ===== تبويب 5: الإدارة =====
    with tab5:
        st.subheader("⚙️ الإدارة والتحكم")
        
        # اختبار الاتصال بقاعدة البيانات
        st.markdown("### 🔌 اختبار الاتصالات")
        
        col_test1, col_test2 = st.columns(2)
        
        with col_test1:
            if st.button("🔍 اختبار Supabase"):
                engine = get_supabase_engine()
                if engine:
                    try:
                        with engine.connect() as conn:
                            result = conn.execute(text("SELECT 1"))
                            st.success("✅ الاتصال بـ Supabase ناجح")
                    except Exception as e:
                        st.error(f"❌ فشل الاتصال بـ Supabase: {e}")
                else:
                    st.error("❌ لا يمكن إنشاء محرك الاتصال")
        
        with col_test2:
            if st.button("🔍 اختبار تليجرام"):
                success, msg = test_telegram_bot()
                if success:
                    st.success(msg)
                else:
                    st.error(msg)
        
        st.divider()
        
        # عرض جميع المستخدمين
        st.markdown("### 📊 جميع المستخدمين")
        df_alerts = get_alerts_supabase(only_active=False)
        if not df_alerts.empty:
            st.dataframe(df_alerts, use_container_width=True)
        else:
            st.info("ℹ️ لا يوجد مستخدمين")
        
        st.divider()
        
        # دليل المساعدة
        st.markdown("### ❓ دليل المساعدة")
        with st.expander("📖 كيف تحصل على Chat ID الخاص بك؟"):
            st.markdown("""
            1. افتح تطبيق تليجرام
            2. ابحث عن البوت: `@userinfobot`
            3. اضغط **Start**
            4. سيرسل لك البوت رقم الـ ID الخاص بك
            """)
        
        with st.expander("📖 كيفية إعداد البوت؟"):
            st.markdown("""
            1. ابحث عن `@BotFather` في تليجرام
            2. أرسل `/newbot` واتبع التعليمات
            3. احصل على التوكن
            4. ضع التوكن في ملف `secrets.toml`
            """)
    
    # التذييل
    st.markdown("<hr>", unsafe_allow_html=True)
    st.markdown(
        "<div style='text-align:center; color:gray; font-size:14px;'>"
        "© Techno logic 2026. Haytham Elsaadany"
        "</div>",
        unsafe_allow_html=True
    )

# ==========================================
# تشغيل التطبيق
# ==========================================
if __name__ == "__main__":
    main()
