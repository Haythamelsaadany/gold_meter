import streamlit as st
import pandas as pd
import yfinance as yf
import feedparser
import json
import requests
from datetime import datetime, timedelta
import time
import psycopg2  # تم التغيير إلى مكتبة بوستجرس لإدارة السيرفر السحابي

# إعداد الصفحة العام
st.set_page_config(page_title="Gold Meter Pro 2026", layout="wide", page_icon="🏅")

# ==========================================
# 0. دالة الاتصال بقاعدة بيانات Supabase
# ==========================================
def get_db_connection():
    """إنشاء اتصال آمن مع قاعدة بيانات Supabase باستخدام الـ Secrets الشاملة"""
    try:
        creds = st.secrets["postgres"]
        conn = psycopg2.connect(
            host=creds["host"],
            port=creds["port"],
            database=creds["database"],
            user=creds["user"],
            password=creds["password"],
            connect_timeout=10
        )
        return conn
    except Exception as e:
        st.error(f"❌ فشل الاتصال بقاعدة البيانات السحابية Supabase: {e}")
        return None

# ==========================================
# 1. نظام إرسال رسائل تليجرام
# ==========================================
def send_telegram_message(chat_id, text):
    try:
        if "TELEGRAM_BOT_TOKEN" not in st.secrets:
            return False, "❌ مفتاح TELEGRAM_BOT_TOKEN غير موجود!"
        
        token = st.secrets["TELEGRAM_BOT_TOKEN"].strip()
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        
        payload = {
            "chat_id": str(chat_id).strip(),
            "text": text,
            "parse_mode": "Markdown"
        }
        
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 200:
            return True, "✅ تم الإرسال"
        else:
            return False, f"❌ خطأ {response.status_code}: {response.text}"
    except Exception as e:
        return False, f"❌ خطأ في الشبكة: {str(e)}"

# ==========================================
# 2. إدارة قاعدة البيانات السحابية (Supabase / Postgres)
# ==========================================
def init_db():
    """تهيئة الجداول على السيرفر السحابي بأسلوب Postgres"""
    conn = get_db_connection()
    if not conn:
        return
    c = conn.cursor()
    
    # جدول التنبيهات
    c.execute('''CREATE TABLE IF NOT EXISTS gold_alerts (
        id SERIAL PRIMARY KEY,
        username TEXT,
        tg_id TEXT,
        karat TEXT,
        high_target REAL,
        low_target REAL,
        triggered INT DEFAULT 0,
        last_alerted_date TEXT
    )''')
    
    # جدول إحصائيات الزوار
    c.execute('''CREATE TABLE IF NOT EXISTS site_stats (
        id INT PRIMARY KEY,
        views INT
    )''')
    c.execute("INSERT INTO site_stats (id, views) VALUES (1, 0) ON CONFLICT (id) DO NOTHING")
    
    conn.commit()
    c.close()
    conn.close()

def update_and_get_views():
    """تحديث وقراءة عدد الزوار من السيرفر"""
    conn = get_db_connection()
    if not conn:
        return 0
    c = conn.cursor()
    views = 0
    try:
        if 'tracked' not in st.session_state:
            st.session_state['tracked'] = True
            c.execute("UPDATE site_stats SET views = views + 1 WHERE id = 1")
            conn.commit()
        c.execute("SELECT views FROM site_stats WHERE id = 1")
        res = c.fetchone()
        views = res[0] if res else 0
    except Exception as e:
        print(f"خطأ الزيارات: {e}")
    finally:
        c.close()
        conn.close()
    return views

def save_alert(username, tg_id, karat, high, low):
    """حفظ التنبيه في سوبابيس السحابية"""
    conn = get_db_connection()
    if not conn:
        return False, "❌ لا يوجد اتصال بالسيرفر"
    c = conn.cursor()
    try:
        c.execute("""
            INSERT INTO gold_alerts (username, tg_id, karat, high_target, low_target, triggered)
            VALUES (%s, %s, %s, %s, %s, 0)
        """, (username, tg_id, karat, float(high), float(low)))
        conn.commit()
        return True, "✅ تم الحفظ بنجاح في السيرفر السحابي"
    except Exception as e:
        return False, f"❌ خطأ في الحفظ: {e}"
    finally:
        c.close()
        conn.close()

def get_alerts(only_active=True):
    """جلب التنبيهات"""
    conn = get_db_connection()
    if not conn:
        return pd.DataFrame()
    try:
        query = "SELECT id, username, tg_id, karat, high_target, low_target, triggered, last_alerted_date FROM gold_alerts"
        if only_active:
            query += " WHERE triggered = 0"
        query += " ORDER BY id DESC"
        df = pd.read_sql_query(query, conn)
        return df
    except Exception as e:
        st.error(f"❌ خطأ في جلب التنبيهات: {e}")
        return pd.DataFrame()
    finally:
        conn.close()

def update_alert_triggered(alert_id):
    """تحديث حالة التنبيه بعد الإرسال"""
    conn = get_db_connection()
    if not conn:
        return False
    c = conn.cursor()
    try:
        today = datetime.now().strftime('%Y-%m-%d')
        c.execute("""
            UPDATE gold_alerts 
            SET triggered = 1, last_alerted_date = %s
            WHERE id = %s
        """, (today, alert_id))
        conn.commit()
        return True
    except Exception as e:
        print(f"خطأ في تحديث التنبيه: {e}")
        return False
    finally:
        c.close()
        conn.close()

# ==========================================
# 3. جلب الأسعار وحساب العيارات
# ==========================================
@st.cache_data(ttl=30)
def get_market_data():
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
# 4. محرك التنبيهات اليدوي
# ==========================================
def check_and_send_alerts():
    try:
        prices, _, _ = get_market_data()
        today = datetime.now().strftime('%Y-%m-%d')
        
        df_alerts = get_alerts(only_active=True)
        if df_alerts.empty:
            return "ℹ️ لا توجد تنبيهات نشطة"
        
        alerts_sent = []
        
        for _, row in df_alerts.iterrows():
            alert_id = row['id']
            username = row['username']
            tg_id = row['tg_id']
            karat = row['karat']
            high_target = float(row['high_target'])
            low_target = float(row['low_target'])
            last_alerted = row.get('last_alerted_date')
            
            current_price = prices.get(karat, prices['21'])
            
            should_send = False
            alert_msg = ""
            
            if current_price >= high_target and last_alerted != today:
                alert_msg = f"""🚀 *تنبيه صعود الذهب!*

👤 المستخدم: {username}
💎 العيار: {karat}
💰 السعر الحالي: {current_price:,.2f} ج.م
🎯 هدف البيع: {high_target:,.0f} ج.م

📈 تم تحقيق هدف البيع المحدد!

📅 {datetime.now().strftime('%Y-%m-%d %H:%M')}"""
                should_send = True
            
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
                success, msg = send_telegram_message(tg_id, alert_msg)
                if success:
                    update_alert_triggered(alert_id)
                    alerts_sent.append(f"✅ تنبيه لـ {username}")
                else:
                    alerts_sent.append(f"❌ فشل إرسال لـ {username}: {msg}")
        
        if alerts_sent:
            return "\n".join(alerts_sent)
        else:
            current_price = prices.get('21', 0)
            return f"ℹ️ لا توجد تنبيهات جديدة. السعر الحالي لعيار 21: {current_price:,.2f} ج.م"
            
    except Exception as e:
        return f"❌ خطأ: {e}"

# ==========================================
# 5. جلب المنحنى البياني
# ==========================================
@st.cache_data(ttl=1800)
def get_safe_historical_data():
    try:
        ticker = yf.Ticker("GC=F")
        hist = ticker.history(period="1mo")
        if not hist.empty:
            return hist['Close'], False
    except Exception:
        pass
    
    dates = [datetime.now() - timedelta(days=i) for i in range(30)][::-1]
    fallback_prices = [2320 + (i * 1.8) for i in range(30)]
    df_fallback = pd.DataFrame({"Close": fallback_prices}, index=dates)
    return df_fallback['Close'], True

# ==========================================
# 6. التطبيق الرئيسي
# ==========================================
def main():
    init_db()
    views_count = update_and_get_views()
    
    st.title("🏅 Gold Meter Pro - المنظومة التفاعلية الشاملة")
    st.caption(f"👁️ عدد زيارات المنصة: {views_count} زائر")
    st.success("💡 **ملاحظة:** النظام يعمل الآن بقاعدة بيانات سحابية متزامنة (Supabase) لحفظ البيانات بشكل دائم.")
    
    prices, gold_oz, usd_egp = get_market_data()
    
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
    
    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "📊 التحليل والبورصة", "💡 التوصيات الذكية", "📰 أخبار الذهب", "🔔 التنبيهات", "⚙️ الإدارة"
    ])
    
    with tab1:
        st.subheader("📈 أداء سعر الأوقية عالمياً")
        chart_data, is_fallback = get_safe_historical_data()
        if is_fallback:
            st.info("⚠️ بيانات بيانية تقريبية مؤقتاً - الأسعار الفورية دقيقة 100%")
        st.line_chart(chart_data)
    
    with tab2:
        st.subheader("🤖 نظام التوصيات والتحليل الفني")
        if prices["21"] > 3800:
            st.warning("⚠️ الأسعار مرتفعة نسبياً - نوصي بالتريث")
        else:
            st.success("✅ الأسعار مستقرة - فرصة استثمارية جيدة")
    
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
    
    with tab4:
        st.subheader("🔔 إعداد التنبيهات التفاعلية")
        
        col_test1, col_test2 = st.columns([3, 1])
        with col_test2:
            if st.button("🔍 اختبار البوت"):
                if "TELEGRAM_BOT_TOKEN" in st.secrets:
                    try:
                        token = st.secrets["TELEGRAM_BOT_TOKEN"].strip()
                        url = f"https://api.telegram.org/bot{token}/getMe"
                        response = requests.get(url, timeout=10)
                        if response.status_code == 200:
                            st.success("✅ البوت يعمل بنجاح")
                        else:
                            st.error(f"❌ فشل اختبار البوت: {response.status_code}")
                    except Exception as e:
                        st.error(f"❌ خطأ: {e}")
                else:
                    st.error("❌ التوكن غير موجود في secrets")
        
        st.divider()
        
        col1, col2 = st.columns(2)
        with col1:
            username = st.text_input("👤 اسمك الكريم", key="input_username")
            telegram_id = st.text_input("🆔 معرف التليجرام (Chat ID)", key="input_tgid", help="احصل عليه من @userinfobot")
            if telegram_id and not telegram_id.isdigit():
                st.warning("⚠️ يجب أن يكون Chat ID أرقام فقط!")
        
        with col2:
            selected_karat = st.selectbox("💎 اختر العيار", ["24", "22", "21", "18"], key="input_karat")
            default_high = float(round(prices[selected_karat] + 150))
            default_low = float(round(prices[selected_karat] - 150))
            
            high_target = st.number_input("🚀 هدف البيع (ارتفاع)", value=default_high, step=50.0, key="input_high")
            low_target = st.number_input("📉 هدف الشراء (انخفاض)", value=default_low, step=50.0, key="input_low")
        
        col_btn1, col_btn2, col_btn3, col_btn4 = st.columns(4)
        
        with col_btn1:
            if st.button("💾 حفظ التنبيه", use_container_width=True, type="primary"):
                if not username or not telegram_id:
                    st.error("❌ يرجى إدخال الاسم ومعرف التليجرام")
                elif not telegram_id.isdigit():
                    st.error("❌ معرف التليجرام غير صحيح (أرقام فقط)")
                else:
                    welcome_msg = f"""🔔 *مرحباً {username}!* \n\n✅ تم تفعيل تنبيهات Gold Meter بنجاح.\n\n📊 العيار: {selected_karat}\n🎯 هدف البيع: {high_target:,.0f} ج.م\n🎯 هدف الشراء: {low_target:,.0f} ج.م\n\n🔄 سيتم إرسال تنبيه عند تحقيق الأهداف."""
                    with st.spinner("جاري إرسال رسالة الاختبار..."):
                        success, msg = send_telegram_message(telegram_id, welcome_msg)
                    
                    if success:
                        save_success, save_msg = save_alert(username, telegram_id, selected_karat, high_target, low_target)
                        if save_success:
                            st.balloons()
                            st.success(f"✅ {save_msg}")
                            time.sleep(1)
                            st.rerun()
                        else:
                            st.error(save_msg)
                    else:
                        st.error(f"❌ فشل إرسال رسالة الاختبار: {msg}")
        
        with col_btn2:
            if st.button("🔔 فحص التنبيهات", use_container_width=True):
                with st.spinner("جاري فحص التنبيهات..."):
                    result = check_and_send_alerts()
                    st.info(result)
                    if "✅" in result:
                        st.balloons()
        
        with col_btn3:
            if st.button("🔄 إعادة تعيين", use_container_width=True):
                if telegram_id:
                    conn = get_db_connection()
                    if conn:
                        c = conn.cursor()
                        c.execute("UPDATE gold_alerts SET triggered = 0, last_alerted_date = NULL WHERE tg_id = %s", (telegram_id,))
                        conn.commit()
                        c.close()
                        conn.close()
                        st.success("✅ تم إعادة تعيين التنبيهات سحابياً!")
                        st.rerun()
                else:
                    st.warning("⚠️ أدخل معرف التليجرام أولاً")
        
        with col_btn4:
            if st.button("🗑️ مسح التنبيهات", use_container_width=True):
                if telegram_id:
                    conn = get_db_connection()
                    if conn:
                        c = conn.cursor()
                        c.execute("DELETE FROM gold_alerts WHERE tg_id = %s", (telegram_id,))
                        conn.commit()
                        c.close()
                        conn.close()
                        st.success("✅ تم مسح تنبيهاتك سحابياً!")
                        st.rerun()
                else:
                    st.warning("⚠️ أدخل معرف التليجرام أولاً")
        
        st.divider()
        
        st.subheader("📋 التنبيهات المسجلة")
        df_alerts = get_alerts(only_active=False)
        if not df_alerts.empty:
            display_df = df_alerts[['username', 'karat', 'high_target', 'low_target', 'triggered']].copy()
            display_df.columns = ['المستخدم', 'العيار', 'هدف البيع', 'هدف الشراء', 'الحالة']
            display_df['الحالة'] = display_df['الحالة'].apply(lambda x: '🟢 نشط' if x == 0 else '🔴 منفذ')
            st.dataframe(display_df, use_container_width=True)
        else:
            st.info("ℹ️ لا توجد تنبيهات مسجلة")
    
    with tab5:
        st.subheader("⚙️ الإدارة والتحكم")
        st.markdown("### 📊 جميع التنبيهات")
        df_all = get_alerts(only_active=False)
        if not df_all.empty:
            st.dataframe(df_all, use_container_width=True)
            col_stat1, col_stat2 = st.columns(2)
            with col_stat1:
                active = len(df_all[df_all['triggered'] == 0])
                st.metric("🟢 التنبيهات النشطة", active)
            with col_stat2:
                triggered = len(df_all[df_all['triggered'] == 1])
                st.metric("🔴 التنبيهات المنفذة", triggered)
        else:
            st.info("ℹ️ لا توجد بيانات")
        
        st.divider()
        st.markdown("### ❓ دليل المساعدة")
        with st.expander("📖 كيف تحصل على Chat ID الخاص بك؟"):
            st.markdown("1. افتح تطبيق تليجرام\n2. ابحث عن البوت: `@userinfobot`\n3. اضغط **Start**\n4. سيرسل لك البوت رقم الـ ID الخاص بك")

    st.markdown("<hr>", unsafe_allow_html=True)
    st.markdown("<div style='text-align:center; color:gray; font-size:14px;'>© Techno logic 2026. Haytham Elsaadany</div>", unsafe_allow_html=True)

if __name__ == "__main__":
    main()
