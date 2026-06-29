import streamlit as st
from sqlalchemy import create_engine, text, inspect
import json
import urllib.request
import urllib.parse
import pandas as pd
import yfinance as yf
import feedparser
import time
from datetime import datetime, timedelta
import threading
import plotly.graph_objects as go
import plotly.express as px

# إعداد الصفحة
st.set_page_config(
    page_title="🏅 Gold Meter - نظام الذهب المتكامل", 
    layout="wide", 
    page_icon="🏅",
    initial_sidebar_state="expanded"
)

# ==========================================
# الاتصال الآمن بقاعدة البيانات (Supabase PostgreSQL)
# ==========================================
def get_engine():
    """
    إنشاء محرك اتصال بقاعدة البيانات باستخدام st.secrets
    يستخدم PostgreSQL مع Supabase
    """
    try:
        # جلب بيانات الاتصال من الـ Secrets
        db_config = st.secrets["postgres"]
        
        # تنظيف كلمة المرور من الرموز الخاصة للتأكد من صحة الرابط
        password = urllib.parse.quote_plus(db_config["password"])
        
        # بناء رابط الاتصال (Connection String)
        database_url = f"postgresql://{db_config['user']}:{password}@{db_config['host']}:{db_config['port']}/{db_config['database']}"
        
        # إنشاء المحرك مع إعدادات SSL المطلوبة لـ Supabase
        engine = create_engine(
            database_url,
            connect_args={
                "sslmode": "require",
                "connect_timeout": 10
            },
            pool_pre_ping=True,  # التحقق من الاتصال قبل الاستخدام
            pool_recycle=3600    # إعادة تعيين الاتصال كل ساعة
        )
        
        return engine
    except Exception as e:
        st.error(f"❌ خطأ في إنشاء اتصال قاعدة البيانات: {e}")
        return None

@st.cache_resource
def init_database():
    """
    تهيئة قاعدة البيانات وإنشاء جميع الجداول المطلوبة
    """
    try:
        engine = get_engine()
        if not engine:
            return False
        
        with engine.connect() as conn:
            # 1. جدول المستخدمين
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    username VARCHAR(100) NOT NULL,
                    tg_id VARCHAR(50) UNIQUE NOT NULL,
                    phone VARCHAR(20),
                    high_target NUMERIC(10, 2) DEFAULT 6000.00,
                    low_target NUMERIC(10, 2) DEFAULT 5000.00,
                    last_alerted_high DATE,
                    last_alerted_low DATE,
                    alerts_active INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """))
            
            # 2. جدول سجل التنبيهات
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS alert_logs (
                    id SERIAL PRIMARY KEY,
                    tg_id VARCHAR(50) NOT NULL,
                    alert_type VARCHAR(10) NOT NULL,
                    price NUMERIC(10, 2) NOT NULL,
                    sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    message TEXT
                )
            """))
            
            # 3. جدول سجل الأسعار (للتاريخ)
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS price_history (
                    id SERIAL PRIMARY KEY,
                    gold_price NUMERIC(10, 2),
                    usd_price NUMERIC(10, 2),
                    gram21_price NUMERIC(10, 2),
                    recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """))
            
            # 4. إضافة عمود phone إذا لم يكن موجوداً (للتحديث)
            try:
                conn.execute(text("""
                    ALTER TABLE users ADD COLUMN IF NOT EXISTS phone VARCHAR(20)
                """))
            except:
                pass
            
            conn.commit()
            
            # التحقق من وجود البيانات
            inspector = inspect(engine)
            tables = inspector.get_table_names()
            if 'users' in tables:
                return True
            else:
                st.error("❌ فشل في إنشاء الجداول")
                return False
            
    except Exception as e:
        st.error(f"❌ خطأ في تهيئة قاعدة البيانات: {e}")
        return False

# ==========================================
# دوال CRUD للمستخدمين
# ==========================================
def save_user(username, tg_id, high_target, low_target, phone=""):
    """
    حفظ أو تحديث بيانات المستخدم
    """
    try:
        engine = get_engine()
        if not engine:
            return False, "فشل الاتصال بقاعدة البيانات"
        
        with engine.connect() as conn:
            # التحقق من وجود المستخدم
            result = conn.execute(
                text("SELECT id FROM users WHERE tg_id = :tg_id"),
                {"tg_id": tg_id}
            )
            existing_user = result.fetchone()
            
            if existing_user:
                # تحديث المستخدم الموجود
                conn.execute(text("""
                    UPDATE users SET 
                        username = :username,
                        phone = :phone,
                        high_target = :high_target,
                        low_target = :low_target,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE tg_id = :tg_id
                """), {
                    "username": username,
                    "phone": phone,
                    "tg_id": tg_id,
                    "high_target": float(high_target),
                    "low_target": float(low_target)
                })
            else:
                # إدراج مستخدم جديد
                conn.execute(text("""
                    INSERT INTO users (username, phone, tg_id, high_target, low_target, alerts_active)
                    VALUES (:username, :phone, :tg_id, :high_target, :low_target, 1)
                """), {
                    "username": username,
                    "phone": phone,
                    "tg_id": tg_id,
                    "high_target": float(high_target),
                    "low_target": float(low_target)
                })
            
            conn.commit()
            return True, "✅ تم حفظ البيانات بنجاح"
            
    except Exception as e:
        return False, f"❌ خطأ: {e}"

def get_user_by_tg(tg_id):
    """
    جلب بيانات مستخدم باستخدام معرف التليجرام
    """
    try:
        engine = get_engine()
        if not engine:
            return None
        
        with engine.connect() as conn:
            result = conn.execute(text("""
                SELECT username, phone, high_target, low_target, alerts_active,
                       last_alerted_high, last_alerted_low
                FROM users 
                WHERE tg_id = :tg_id
            """), {"tg_id": tg_id})
            row = result.fetchone()
            return row if row else None
            
    except Exception as e:
        st.error(f"❌ خطأ في جلب البيانات: {e}")
        return None

def get_all_users():
    """
    جلب جميع المستخدمين
    """
    try:
        engine = get_engine()
        if not engine:
            return []
        
        with engine.connect() as conn:
            result = conn.execute(text("""
                SELECT id, username, phone, tg_id, high_target, low_target,
                       last_alerted_high, last_alerted_low, alerts_active,
                       created_at
                FROM users 
                ORDER BY created_at DESC
            """))
            return result.fetchall()
            
    except Exception as e:
        st.error(f"❌ خطأ في جلب المستخدمين: {e}")
        return []

def toggle_user_alerts(tg_id, active):
    """
    تفعيل أو إيقاف تنبيهات المستخدم
    """
    try:
        engine = get_engine()
        if not engine:
            return False
        
        with engine.connect() as conn:
            conn.execute(text("""
                UPDATE users 
                SET alerts_active = :active, updated_at = CURRENT_TIMESTAMP
                WHERE tg_id = :tg_id
            """), {"active": 1 if active else 0, "tg_id": tg_id})
            conn.commit()
            return True
            
    except Exception as e:
        st.error(f"❌ خطأ في تحديث حالة التنبيهات: {e}")
        return False

def reset_user_alerts(tg_id):
    """
    إعادة تعيين تنبيهات المستخدم
    """
    try:
        engine = get_engine()
        if not engine:
            return False
        
        with engine.connect() as conn:
            conn.execute(text("""
                UPDATE users 
                SET last_alerted_high = NULL, last_alerted_low = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE tg_id = :tg_id
            """), {"tg_id": tg_id})
            conn.commit()
            return True
            
    except Exception as e:
        st.error(f"❌ خطأ في إعادة تعيين التنبيهات: {e}")
        return False

def delete_user(tg_id):
    """
    حذف مستخدم
    """
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

def save_price_history(gold_price, usd_price, gram21_price):
    """
    حفظ سجل الأسعار
    """
    try:
        engine = get_engine()
        if not engine:
            return False
        
        with engine.connect() as conn:
            conn.execute(text("""
                INSERT INTO price_history (gold_price, usd_price, gram21_price)
                VALUES (:gold, :usd, :gram21)
            """), {
                "gold": gold_price,
                "usd": usd_price,
                "gram21": gram21_price
            })
            conn.commit()
            return True
            
    except Exception as e:
        print(f"خطأ في حفظ سجل الأسعار: {e}")
        return False

def get_price_history(days=30):
    """
    جلب سجل الأسعار للأيام المحددة
    """
    try:
        engine = get_engine()
        if not engine:
            return pd.DataFrame()
        
        with engine.connect() as conn:
            result = conn.execute(text("""
                SELECT recorded_at, gold_price, usd_price, gram21_price
                FROM price_history 
                WHERE recorded_at >= CURRENT_DATE - INTERVAL :days DAY
                ORDER BY recorded_at DESC
            """), {"days": days})
            rows = result.fetchall()
            
            if rows:
                df = pd.DataFrame(rows, columns=["التاريخ", "الذهب", "الدولار", "جرام 21"])
                return df
            return pd.DataFrame()
            
    except Exception as e:
        print(f"خطأ في جلب سجل الأسعار: {e}")
        return pd.DataFrame()

# ==========================================
# جلب البيانات الحية
# ==========================================
@st.cache_data(ttl=60)
def fetch_market_data():
    """
    جلب بيانات الذهب والدولار من مصادر متعددة
    """
    gold_price = 2330.0
    usd_price = 49.22
    
    # 1. جلب سعر الذهب
    try:
        with urllib.request.urlopen("https://api.gold-api.com/price/XAU", timeout=5) as r:
            data = json.load(r)
            if data and 'price' in data:
                gold_price = float(data['price'])
    except:
        # محاولة مصدر بديل
        try:
            ticker = yf.Ticker("GC=F")
            gold_price = float(ticker.fast_info['last_price'])
        except:
            pass
    
    # 2. جلب سعر الدولار
    try:
        with urllib.request.urlopen("https://open.er-api.com/v6/latest/USD", timeout=5) as r:
            data = json.load(r)
            if data and 'rates' in data and 'EGP' in data['rates']:
                usd_price = float(data['rates']['EGP'])
                # التأكد من أن السعر منطقي
                if not (45 <= usd_price <= 52):
                    usd_price = 49.22
    except:
        pass
    
    return gold_price, usd_price

def calculate_gram_prices(gold_price, usd_price):
    """
    حساب أسعار الجرامات المختلفة
    """
    ounce_egp = gold_price * usd_price
    gram_24 = ounce_egp / 31.1034768
    
    return {
        '24': gram_24,
        '22': gram_24 * (22/24),
        '21': gram_24 * (21/24),
        '18': gram_24 * (18/24)
    }

def get_current_gram21():
    """
    جلب سعر جرام 21 الحالي
    """
    gold, usd = fetch_market_data()
    gram_prices = calculate_gram_prices(gold, usd)
    return round(gram_prices['21'], 2)

# ==========================================
# إرسال تنبيهات التليجرام
# ==========================================
def send_telegram_message(tg_id, message):
    """
    إرسال رسالة عبر تليجرام بوت
    """
    try:
        # جلب التوكن من secrets
        bot_token = st.secrets.get("TELEGRAM_BOT_TOKEN", "")
        if not bot_token:
            return False, "❌ لم يتم تعيين توكن التليجرام"
        
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        payload = urllib.parse.urlencode({
            "chat_id": tg_id,
            "text": message,
            "parse_mode": "HTML"
        }).encode("utf-8")
        
        req = urllib.request.Request(url, data=payload)
        with urllib.request.urlopen(req, timeout=5) as response:
            return True, "✅ تم إرسال الرسالة"
            
    except Exception as e:
        return False, f"❌ خطأ في الإرسال: {e}"

def check_and_send_alerts():
    """
    فحص التنبيهات وإرسالها للمستخدمين
    """
    try:
        current_price = get_current_gram21()
        today_str = datetime.now().strftime('%Y-%m-%d')
        
        # جلب المستخدمين المفعلين
        users = get_all_users()
        if not users:
            return "ℹ️ لا يوجد مستخدمين مسجلين"
        
        alerts_sent = []
        
        for user in users:
            user_id, username, phone, tg_id, high_target, low_target, last_high, last_low, active, created = user
            
            if not tg_id or active == 0:
                continue
            
            # تحويل الأهداف إلى float
            high_target = float(high_target) if high_target else 6000.0
            low_target = float(low_target) if low_target else 5000.0
            
            # فحص التنبيهات
            high_alert = current_price >= high_target and last_high != today_str
            low_alert = current_price <= low_target and last_low != today_str
            
            # إرسال تنبيه HIGH
            if high_alert:
                message = f"""🚀 <b>تنبيه اختراق الهدف الأعلى!</b>

👤 المستخدم: {username}
💰 السعر الحالي: <b>{current_price:,.2f}</b> ج.م
🎯 هدف البيع: <b>{high_target:,.0f}</b> ج.م

📈 تم تجاوز هدف البيع المحدد!

📅 {datetime.now().strftime('%Y-%m-%d %H:%M')}"""
                
                success, msg = send_telegram_message(tg_id, message)
                if success:
                    # تحديث حالة التنبيه
                    engine = get_engine()
                    with engine.connect() as conn:
                        conn.execute(text("""
                            UPDATE users SET last_alerted_high = :today
                            WHERE tg_id = :tg_id
                        """), {"today": today_str, "tg_id": tg_id})
                        conn.commit()
                    alerts_sent.append(f"✅ HIGH لـ {username}")
            
            # إرسال تنبيه LOW
            if low_alert:
                message = f"""🔻 <b>تنبيه كسر القاع الأدنى!</b>

👤 المستخدم: {username}
💰 السعر الحالي: <b>{current_price:,.2f}</b> ج.م
🎯 هدف الشراء: <b>{low_target:,.0f}</b> ج.م

📉 تم كسر هدف الشراء المحدد!

📅 {datetime.now().strftime('%Y-%m-%d %H:%M')}"""
                
                success, msg = send_telegram_message(tg_id, message)
                if success:
                    # تحديث حالة التنبيه
                    engine = get_engine()
                    with engine.connect() as conn:
                        conn.execute(text("""
                            UPDATE users SET last_alerted_low = :today
                            WHERE tg_id = :tg_id
                        """), {"today": today_str, "tg_id": tg_id})
                        conn.commit()
                    alerts_sent.append(f"✅ LOW لـ {username}")
        
        if alerts_sent:
            return f"✅ تم إرسال: {', '.join(alerts_sent)}"
        else:
            return f"ℹ️ لا توجد تنبيهات جديدة. السعر الحالي: {current_price:,.2f} ج.م"
            
    except Exception as e:
        return f"❌ خطأ: {e}"

# ==========================================
# بدء التطبيق الرئيسي
# ==========================================
def main():
    # تهيئة قاعدة البيانات
    if not init_database():
        st.error("⚠️ فشل في تهيئة قاعدة البيانات. يرجى التحقق من الإعدادات.")
        return
    
    # الشريط الجانبي
    with st.sidebar:
        st.image("https://img.icons8.com/color/96/000000/gold-bars.png", width=80)
        st.title("🏅 Gold Meter")
        st.markdown("---")
        
        # عرض الأسعار في الشريط الجانبي
        gold, usd = fetch_market_data()
        gram_prices = calculate_gram_prices(gold, usd)
        
        st.subheader("📊 الأسعار الحالية")
        st.metric("🌍 الذهب عالمياً", f"${gold:,.2f}")
        st.metric("💵 الدولار", f"{usd:.2f} ج.م")
        st.divider()
        st.subheader("💎 أسعار الجرامات")
        st.metric("عيار 24", f"{gram_prices['24']:,.2f} ج.م")
        st.metric("عيار 22", f"{gram_prices['22']:,.2f} ج.م")
        st.metric("عيار 21", f"{gram_prices['21']:,.2f} ج.م")
        st.metric("عيار 18", f"{gram_prices['18']:,.2f} ج.م")
        
        st.markdown("---")
        st.caption("© Techno logic 2026")
        st.caption("Haytham Elsaadany")
    
    # المحتوى الرئيسي
    st.title("🏅 Gold Meter - نظام تحليل الذهب المتكامل")
    st.markdown("نظام متكامل لتحليل أسعار الذهب وإدارة التنبيهات")
    
    # التبويبات الرئيسية
    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "📊 التحليل الفني",
        "💎 أسعار الجرامات",
        "📰 الأخبار",
        "🔔 التنبيهات",
        "📋 الإدارة"
    ])
    
    # ===== تبويب 1: التحليل الفني =====
    with tab1:
        st.subheader("📈 تحركات أسعار الذهب")
        
        col1, col2 = st.columns([2, 1])
        
        with col1:
            try:
                # جلب بيانات التاريخ
                hist = yf.Ticker("GC=F").history(period="1mo")
                if not hist.empty:
                    # رسم بياني تفاعلي
                    fig = go.Figure()
                    fig.add_trace(go.Scatter(
                        x=hist.index,
                        y=hist['Close'],
                        mode='lines',
                        name='سعر الذهب',
                        line=dict(color='gold', width=2)
                    ))
                    fig.update_layout(
                        title="سعر الذهب - آخر 30 يوم",
                        xaxis_title="التاريخ",
                        yaxis_title="السعر (دولار)",
                        template="plotly_dark",
                        height=400
                    )
                    st.plotly_chart(fig, use_container_width=True)
                    
                    # إحصائيات
                    col_a, col_b, col_c, col_d = st.columns(4)
                    col_a.metric("أعلى سعر", f"${hist['Close'].max():.2f}")
                    col_b.metric("أدنى سعر", f"${hist['Close'].min():.2f}")
                    col_c.metric("متوسط السعر", f"${hist['Close'].mean():.2f}")
                    col_d.metric("آخر سعر", f"${hist['Close'].iloc[-1]:.2f}")
                else:
                    st.info("📊 لا توجد بيانات تاريخية متاحة")
            except Exception as e:
                st.warning(f"⚠️ خطأ في جلب البيانات: {e}")
        
        with col2:
            st.subheader("📊 التغيرات")
            try:
                # التغير اليومي
                hist = yf.Ticker("GC=F").history(period="2d")
                if not hist.empty and len(hist) >= 2:
                    yesterday = hist['Close'].iloc[-2]
                    today = hist['Close'].iloc[-1]
                    change = today - yesterday
                    change_pct = (change / yesterday) * 100
                    
                    color = "🟢" if change > 0 else "🔴"
                    st.metric(
                        "التغير اليومي",
                        f"${today:.2f}",
                        f"{color} {change:+.2f} ({change_pct:+.2f}%)"
                    )
            except:
                pass
            
            # مؤشرات إضافية
            st.metric("⚠️ التقلبات", "متوسطة")
            st.metric("📊 الاتجاه", "صاعد" if gold > 2300 else "هابط")
    
    # ===== تبويب 2: أسعار الجرامات =====
    with tab2:
        st.subheader("💎 تفاصيل أسعار الجرامات")
        
        # عرض الأسعار في بطاقات
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.markdown(f"""
            <div style='background: linear-gradient(135deg, #1a1a2e, #16213e); padding: 20px; border-radius: 10px; text-align: center; border: 1px solid #FFD700;'>
                <h4 style='color: #FFD700;'>عيار 24</h4>
                <h2>{gram_prices['24']:,.2f} ج.م</h2>
                <small>الذهب الخالص</small>
            </div>
            """, unsafe_allow_html=True)
        
        with col2:
            st.markdown(f"""
            <div style='background: linear-gradient(135deg, #1a1a2e, #16213e); padding: 20px; border-radius: 10px; text-align: center; border: 1px solid #C0C0C0;'>
                <h4 style='color: #C0C0C0;'>عيار 22</h4>
                <h2>{gram_prices['22']:,.2f} ج.م</h2>
                <small>الذهب المستخدم</small>
            </div>
            """, unsafe_allow_html=True)
        
        with col3:
            st.markdown(f"""
            <div style='background: linear-gradient(135deg, #1a1a2e, #16213e); padding: 20px; border-radius: 10px; text-align: center; border: 1px solid #CD7F32;'>
                <h4 style='color: #CD7F32;'>عيار 21</h4>
                <h2>{gram_prices['21']:,.2f} ج.م</h2>
                <small>الأكثر تداولاً</small>
            </div>
            """, unsafe_allow_html=True)
        
        with col4:
            st.markdown(f"""
            <div style='background: linear-gradient(135deg, #1a1a2e, #16213e); padding: 20px; border-radius: 10px; text-align: center; border: 1px solid #8B7355;'>
                <h4 style='color: #8B7355;'>عيار 18</h4>
                <h2>{gram_prices['18']:,.2f} ج.م</h2>
                <small>الذهب السفلي</small>
            </div>
            """, unsafe_allow_html=True)
        
        st.divider()
        
        # رسم بياني للأسعار
        st.subheader("📊 مقارنة أسعار الجرامات")
        
        # تحويل البيانات إلى DataFrame للرسم
        grams_data = pd.DataFrame({
            'العيار': ['24', '22', '21', '18'],
            'السعر': [gram_prices['24'], gram_prices['22'], gram_prices['21'], gram_prices['18']]
        })
        
        fig = px.bar(
            grams_data, 
            x='العيار', 
            y='السعر',
            title='أسعار الجرامات بالجنيه المصري',
            labels={'السعر': 'السعر (ج.م)', 'العيار': 'العيار'},
            color='السعر',
            color_continuous_scale='gold'
        )
        fig.update_layout(showlegend=False, height=350)
        st.plotly_chart(fig, use_container_width=True)
    
    # ===== تبويب 3: الأخبار =====
    with tab3:
        st.subheader("📰 آخر أخبار الذهب")
        
        try:
            # محاولة جلب الأخبار من عدة مصادر
            feeds = [
                "https://www.cnbcarabia.com/rss",
                "https://feeds.feedburner.com/egyptgold",
            ]
            
            all_news = []
            for feed_url in feeds:
                try:
                    feed = feedparser.parse(feed_url)
                    if feed.entries:
                        for entry in feed.entries[:5]:
                            all_news.append({
                                'title': entry.title,
                                'link': entry.link,
                                'published': entry.get('published', 'تاريخ غير معروف'),
                                'summary': entry.get('summary', '')[:200] + '...'
                            })
                except:
                    continue
            
            if all_news:
                for news in all_news[:10]:
                    with st.container():
                        st.markdown(f"### 🔹 [{news['title']}]({news['link']})")
                        st.caption(f"📅 {news['published']}")
                        st.write(news['summary'])
                        st.divider()
            else:
                st.info("📰 لا توجد أخبار حالياً")
                
        except Exception as e:
            st.warning(f"⚠️ خطأ في جلب الأخبار: {e}")
    
    # ===== تبويب 4: التنبيهات =====
    with tab4:
        st.subheader("⚙️ إعدادات التنبيهات")
        
        # حالة الجلسة
        if "tg_id" not in st.session_state:
            st.session_state["tg_id"] = ""
        if "username" not in st.session_state:
            st.session_state["username"] = ""
        if "phone" not in st.session_state:
            st.session_state["phone"] = ""
        if "high_target" not in st.session_state:
            st.session_state["high_target"] = 6000.0
        if "low_target" not in st.session_state:
            st.session_state["low_target"] = 5000.0
        
        # نموذج إدخال البيانات
        col1, col2 = st.columns(2)
        
        with col1:
            username = st.text_input("👤 الاسم", value=st.session_state["username"])
            tg_id = st.text_input("🆔 معرف التليجرام (Chat ID)", value=st.session_state["tg_id"])
            phone = st.text_input("📱 رقم الهاتف (اختياري)", value=st.session_state["phone"])
        
        with col2:
            high_target = st.number_input(
                "🚀 هدف البيع (جني أرباح)",
                value=float(st.session_state["high_target"]),
                step=50.0,
                help="سيتم إرسال تنبيه عندما يصل السعر لهذا الرقم أو أعلى"
            )
            
            low_target = st.number_input(
                "🔻 هدف الشراء",
                value=float(st.session_state["low_target"]),
                step=50.0,
                help="سيتم إرسال تنبيه عندما يصل السعر لهذا الرقم أو أقل"
            )
            
            # عرض السعر الحالي
            current_price = get_current_gram21()
            st.info(f"💰 السعر الحالي لعيار 21: {current_price:,.2f} ج.م")
        
        # أزرار التحكم
        col_btn1, col_btn2, col_btn3, col_btn4 = st.columns(4)
        
        with col_btn1:
            if st.button("💾 حفظ الإعدادات", use_container_width=True):
                if username and tg_id:
                    success, msg = save_user(username, tg_id, high_target, low_target, phone)
                    if success:
                        st.session_state["username"] = username
                        st.session_state["tg_id"] = tg_id
                        st.session_state["phone"] = phone
                        st.session_state["high_target"] = high_target
                        st.session_state["low_target"] = low_target
                        st.balloons()
                        st.success(msg)
                        st.rerun()
                    else:
                        st.error(msg)
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
                        active = user_data[4]  # alerts_active
                        new_status = not bool(active)
                        if toggle_user_alerts(tg_id, new_status):
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
                
                col_info1, col_info2, col_info3, col_info4, col_info5 = st.columns(5)
                with col_info1:
                    st.info(f"👤 **الاسم:** {user_data[0]}")
                with col_info2:
                    st.info(f"📱 **الهاتف:** {user_data[1] or 'غير محدد'}")
                with col_info3:
                    st.info(f"🎯 **هدف البيع:** {user_data[2]:,.0f} ج.م")
                with col_info4:
                    st.info(f"🎯 **هدف الشراء:** {user_data[3]:,.0f} ج.م")
                with col_info5:
                    status = "🟢 مفعلة" if user_data[4] == 1 else "🔴 موقفة"
                    st.info(f"🔔 **الحالة:** {status}")
                
                # عرض حالة السعر الحالي
                if current_price >= float(user_data[2]):
                    st.warning(f"⚠️ السعر الحالي ({current_price:,.2f} ج.م) تجاوز هدف البيع ({user_data[2]:,.0f} ج.م)")
                elif current_price <= float(user_data[3]):
                    st.warning(f"⚠️ السعر الحالي ({current_price:,.2f} ج.م) أقل من هدف الشراء ({user_data[3]:,.0f} ج.م)")
                else:
                    st.success(f"✅ السعر الحالي ({current_price:,.2f} ج.م) في النطاق الآمن بين {user_data[3]:,.0f} و {user_data[2]:,.0f} ج.م")
    
    # ===== تبويب 5: الإدارة =====
    with tab5:
        st.subheader("📋 إدارة المستخدمين")
        
        # عرض جميع المستخدمين
        users = get_all_users()
        if users:
            # تحويل إلى DataFrame
            df = pd.DataFrame(users, columns=[
                "ID", "الاسم", "الهاتف", "التليجرام", "هدف البيع", "هدف الشراء",
                "آخر HIGH", "آخر LOW", "مفعل", "تاريخ التسجيل"
            ])
            
            # تنسيق العمود
            df["مفعل"] = df["مفعل"].apply(lambda x: "✅" if x == 1 else "❌")
            df["هدف البيع"] = df["هدف البيع"].apply(lambda x: f"{x:,.0f}")
            df["هدف الشراء"] = df["هدف الشراء"].apply(lambda x: f"{x:,.0f}")
            
            st.dataframe(df, use_container_width=True, hide_index=True)
            
            # إحصائيات
            col_stat1, col_stat2, col_stat3 = st.columns(3)
            with col_stat1:
                st.metric("👥 عدد المستخدمين", len(users))
            with col_stat2:
                active_users = len([u for u in users if u[8] == 1])
                st.metric("🟢 المستخدمين المفعلين", active_users)
            with col_stat3:
                inactive_users = len([u for u in users if u[8] == 0])
                st.metric("🔴 المستخدمين المتوقفين", inactive_users)
            
            st.divider()
            
            # حذف مستخدم
            st.subheader("🗑️ حذف مستخدم")
            col_del1, col_del2 = st.columns([2, 1])
            with col_del1:
                tg_id_delete = st.text_input("أدخل معرف التليجرام للحذف")
            with col_del2:
                if st.button("🗑️ حذف", type="secondary", use_container_width=True):
                    if tg_id_delete:
                        if delete_user(tg_id_delete):
                            st.success("✅ تم حذف المستخدم بنجاح")
                            st.rerun()
                    else:
                        st.error("❌ يرجى إدخال معرف التليجرام")
        else:
            st.info("ℹ️ لا يوجد مستخدمين مسجلين")

# ==========================================
# تشغيل التطبيق
# ==========================================
if __name__ == "__main__":
    main()
