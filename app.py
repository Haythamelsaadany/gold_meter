import streamlit as st
import sqlite3
import pandas as pd
import yfinance as yf
import feedparser
import json
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime, timedelta

# إعداد الصفحة العام
st.set_page_config(page_title="Gold Meter Pro 2026", layout="wide", page_icon="🏅")

# ==========================================
# 1. نظام إرسال رسائل تليجرام المتطور (مع كاشف الأخطاء)
# ==========================================
def send_telegram_message(chat_id, text):
    if "TELEGRAM_BOT_TOKEN" not in st.secrets:
        return False, "❌ مفتاح الـ TELEGRAM_BOT_TOKEN غير موجود نهائياً في الـ Secrets!"
    
    token = st.secrets["TELEGRAM_BOT_TOKEN"].strip().replace('"', '').replace("'", "")
    url = f"https://api.telegram.com/bot{token}/sendMessage"
    data = urllib.parse.urlencode({"chat_id": str(chat_id).strip(), "text": text}).encode("utf-8")
    
    try:
        req = urllib.request.Request(url, data=data)
        with urllib.request.urlopen(req, timeout=7) as r:
            return True, "نجاح"
    except urllib.error.HTTPError as e:
        # قراءة رسالة الخطأ القادمة من سيرفر تليجرام مباشرة
        error_body = e.read().decode("utf-8")
        try:
            error_json = json.loads(error_body)
            return False, f"رفض من تليجرام (كود {e.code}): {error_json.get('description', error_body)}"
        except:
            return False, f"خطأ في الطلب (كود {e.code}): {e.reason}"
    except Exception as e:
        return False, f"خطأ في الشبكة أو السيرفر: {str(e)}"

# ==========================================
# 2. إدارة قاعدة البيانات وعداد الزوار
# ==========================================
def init_db():
    conn = sqlite3.connect('gold_data.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS gold_alerts 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                  username TEXT, 
                  tg_id TEXT, 
                  karat TEXT, 
                  high REAL, 
                  low REAL,
                  triggered INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS site_stats (id INTEGER PRIMARY KEY, views INTEGER)''')
    c.execute("INSERT OR IGNORE INTO site_stats (id, views) VALUES (1, 0)")
    conn.commit()
    conn.close()

def update_and_get_views():
    conn = sqlite3.connect('gold_data.db')
    c = conn.cursor()
    if 'tracked' not in st.session_state:
        st.session_state['tracked'] = True
        c.execute("UPDATE site_stats SET views = views + 1 WHERE id = 1")
        conn.commit()
    c.execute("SELECT views FROM site_stats WHERE id = 1")
    views = c.fetchone()[0]
    conn.close()
    return views

# ==========================================
# 3. جلب الأسعار وحساب العيارات
# ==========================================
def get_market_data():
    try:
        with urllib.request.urlopen("https://api.gold-api.com/price/XAU", timeout=5) as r:
            gold_oz = float(json.load(r)['price'])
        with urllib.request.urlopen("https://open.er-api.com/v6/latest/USD", timeout=5) as r:
            usd_egp = float(json.load(r)['rates']['EGP'])
    except:
        gold_oz, usd_egp = 2330.0, 49.50
    
    g24 = (gold_oz * usd_egp) / 31.1035
    return {
        "24": g24,
        "22": g24 * (22/24),
        "21": g24 * (21/24),
        "18": g24 * (18/24)
    }, gold_oz, usd_egp

# ==========================================
# 4. جلب المنحنى البياني الآمن
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
# 5. واجهة التطبيق والتحكم الرئيسي
# ==========================================
def main():
    init_db()
    views_count = update_and_get_views()
    
    st.title("🏅 Gold Meter Pro - المنظومة التفاعلية الشاملة")
    st.caption(f"👁️ عدد زيارات المنصة: {views_count} زائر")
    
    prices, gold_oz, usd_egp = get_market_data()
    
    st.markdown("### 🌐 الشاشة اللحظية للمؤشرات العالمية والبنكية")
    macro_cols = st.columns(2)
    macro_cols[0].metric("🌟 شاشة أونصة الذهب عالمياً", f"${gold_oz:,.2f}")
    macro_cols[1].metric("🏦 سعر دولار البنك المركزي (EGP)", f"{usd_egp:.2f} ج.م")
    
    st.write("") 
    
    st.markdown("### 💰 أسعار الذهب الحالية في مصر")
    cols = st.columns(4)
    cols[0].metric("عيار 24 (السبائك)", f"{prices['24']:,.2f} ج.م")
    cols[1].metric("عيار 22", f"{prices['22']:,.2f} ج.م")
    cols[2].metric("عيار 21 (الأكثر طلباً)", f"{prices['21']:,.2f} ج.م")
    cols[3].metric("عيار 18 (المشغولات)", f"{prices['18']:,.2f} ج.م")
    
    st.divider()
    
    # محرك التنبيهات التلقائي اللحظي
    conn = sqlite3.connect('gold_data.db')
    df_active_alerts = pd.read_sql_query("SELECT * FROM gold_alerts WHERE triggered = 0", conn)
    conn.close()
    
    if not df_active_alerts.empty:
        for idx, row in df_active_alerts.iterrows():
            current_karat_price = prices.get(row['karat'], prices['21'])
            is_fired = False
            alert_msg = ""
            
            if current_karat_price >= row['high']:
                alert_msg = f"🚨 تنبيه صعود الذهب لـ {row['username']}!\nعيار {row['karat']} وصل لـ {row['high']} ج.م\nالسعر الحالي: {current_karat_price:,.2f} ج.م"
                is_fired = True
            elif current_karat_price <= row['low']:
                alert_msg = f"📉 تنبيه هبوط الذهب لـ {row['username']}!\nعيار {row['karat']} وصل لـ {row['low']} ج.م\nالسعر الحالي: {current_karat_price:,.2f} ج.م"
                is_fired = True
                
            if is_fired:
                st.toast(alert_msg)
                success, _ = send_telegram_message(row['tg_id'], alert_msg)
                if success:
                    conn = sqlite3.connect('gold_data.db')
                    c = conn.cursor()
                    c.execute("UPDATE gold_alerts SET triggered = 1 WHERE id = ?", (row['id'],))
                    conn.commit()
                    conn.close()

    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "📊 التحليل والبورصة", "💡 التوصيات الذكية", "📰 أخبار الذهب الحية", "🔔 إعداد التنبيهات", "❓ دليل المساعدة والدعم"
    ])
    
    with tab1:
        st.subheader("📈 أداء سعر الأوقية عالمياً بالدولار")
        chart_data, is_fallback = get_safe_historical_data()
        st.line_chart(chart_data)
        
    with tab2:
        st.subheader("🤖 نظام التوصيات الآلي")
        if prices["21"] > 3800:
            st.warning("⚠️ مستويات الأسعار مرتفعة نسبياً. نوصي بالتريث.")
        else:
            st.success("✅ الأسعار مستقرة فرصة استثمارية ممتازة للشراء.")
            
    with tab3:
        st.subheader("📰 آخر مستجدات أسواق الذهب")
        gold_news_url = "https://news.google.com/rss/search?q=%D8%A7%D9%84%D8%B0%D9%87%D8%A8&hl=ar&gl=EG&ceid=EG:ar"
        feed = feedparser.parse(gold_news_url)
        if feed.entries:
            for entry in feed.entries[:6]:
                st.markdown(f"🔹 **[{entry.title}]({entry.link})**")
        else:
            st.info("جاري مزامنة الأخبار الاقتصادية...")
            
    # --- تبويب التنبيهات الذكي والمطور لكشف الخطأ الحقيقي ---
    with tab4:
        st.subheader("👤 تفعيل ومتابعة أهدافك السعرية الخاصة")
        
        name = st.text_input("اسمك الكريم", key="input_username")
        telegram_id = st.text_input("معرف التليجرام الخاص بك (Chat ID) - يجب أن يكون أرقاماً فقط", key="input_tgid")
        selected_karat = st.selectbox("اختر عيار الذهب المراد مراقبته", ["24", "22", "21", "18"], key="input_karat")
        
        default_high = float(round(prices[selected_karat] + 150))
        default_low = float(round(prices[selected_karat] - 150))
        
        high_target = st.number_input("تنبيه عند الارتفاع إلى", value=default_high, key="input_high")
        low_target = st.number_input("تنبيه عند الانخفاض إلى", value=default_low, key="input_low")
        
        if st.button("🚀 تفعيل التنبيه المخصّص واختبار الإرسال"):
            if name and telegram_id:
                # التأكد من أن الـ ID أرقام فقط
                if not telegram_id.strip().isdigit():
                    st.error("❌ خطأ: معرف الـ Chat ID يجب أن يتكون من أرقام فقط! تأكد أنك لم تضع اسم المستخدم الذي يبدأ بـ @.")
                else:
                    welcome_msg = f"🔔 مرحباً {name}! تم ربط حسابك بـ Gold Meter.\nمراقبة عيار {selected_karat}\nمستهدف البيع: {high_target} ج.م\nمستهدف الشراء: {low_target} ج.م"
                    
                    with st.spinner("جاري الاتصال وتجربة الإرسال الحقيقي..."):
                        success, reason = send_telegram_message(telegram_id, welcome_msg)
                    
                    if success:
                        conn = sqlite3.connect('gold_data.db')
                        c = conn.cursor()
                        c.execute("""INSERT OR REPLACE INTO gold_alerts (username, tg_id, karat, high, low, triggered) 
                                     VALUES (?, ?, ?, ?, ?, 0)""", (name, telegram_id, selected_karat, high_target, low_target))
                        conn.commit()
                        conn.close()
                        st.success(f"🎯 مبروك يا {name}! الرسالة وصلت لهاتفك بنجاح، وتم تسجيل الهدف في السيرفر.")
                        st.rerun()
                    else:
                        # هنا الصندوق السحري اللي هيقولنا العيب فين بالظبط
                        st.error(f"❌ فشل تليجرام في تسليم الرسالة.")
                        st.warning(f"🔍 السبب المرتد من السيرفر: {reason}")
            else:
                st.error("الرجاء إدخال الاسم ومعرف تليجرام الرقمي أولاً.")

        # عرض الجدول للمشتركين
        conn = sqlite3.connect('gold_data.db')
        df_all = pd.read_sql_query("SELECT * FROM gold_alerts", conn)
        conn.close()
        if not df_all.empty:
            st.write("📋 **شاشة مراقبة الطلبات النشطة في السيرفر:**")
            df_all['الحالة'] = df_all['triggered'].apply(lambda x: "🟢 يراقب السوق" if x == 0 else "📬 تم الإرسال")
            st.dataframe(df_all[['username', 'karat', 'high', 'low', 'الحالة']], use_container_width=True)

    with tab5:
        st.header("❓ دليل استخدام وإعداد منصة Gold Meter")
        st.markdown("تفقد التبويب الرابع لإدخال البيانات المحدثة.")

    st.markdown("<br><hr>", unsafe_allow_html=True)
    st.markdown("<div style='text-align:center; color:gray; font-size:14px;'>© Techno logic 2026. Haytham Elsaadany</div>", unsafe_allow_html=True)

if __name__ == "__main__":
    main()
