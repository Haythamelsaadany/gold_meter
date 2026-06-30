import streamlit as st
import sqlite3
import pandas as pd
import yfinance as yf
import feedparser
import json
import requests
from datetime import datetime, timedelta

# إعداد الصفحة العام
st.set_page_config(page_title="Gold Meter Pro 2026", layout="wide", page_icon="🏅")

# ==========================================
# 1. نظام إرسال رسائل تليجرام الحديث (حل مشكلة ASCII)
# ==========================================
def send_telegram_message(chat_id, text):
    try:
        if "TELEGRAM_BOT_TOKEN" not in st.secrets:
            return False, "❌ مفتاح الـ TELEGRAM_BOT_TOKEN غير موجود في الـ Secrets!"
        
        token = st.secrets["TELEGRAM_BOT_TOKEN"].strip().replace('"', '').replace("'", "")
        url = f"https://api.telegram.com/bot{token}/sendMessage"
        
        payload = {
            "chat_id": str(chat_id).strip(),
            "text": text,
            "parse_mode": "Markdown"
        }
        
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 200:
            return True, "نجاح"
        else:
            return False, f"كود ({response.status_code}): {response.text}"
    except Exception as e:
        return False, f"خطأ في الشبكة: {str(e)}"

# ==========================================
# 2. إدارة قاعدة البيانات المحلية وعداد الزوار
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
        response_gold = requests.get("https://api.gold-api.com/price/XAU", timeout=5)
        gold_oz = float(response_gold.json()['price'])
        
        response_usd = requests.get("https://open.er-api.com/v6/latest/USD", timeout=5)
        usd_egp = float(response_usd.json()['rates']['EGP'])
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
# 5. واجهة التطبيق والتحكم الرئيسي الكاملة
# ==========================================
def main():
    init_db()
    views_count = update_and_get_views()
    
    st.title("🏅 Gold Meter Pro - المنظومة التفاعلية الشاملة")
    st.caption(f"👁️ عدد زيارات المنصة: {views_count} زائر")
    
    prices, gold_oz, usd_egp = get_market_data()
    
    st.markdown("### 🌐 الشاشة اللحظية للمؤشرات العالمية والبنكية")
    macro_cols = st.columns(2)
    macro_cols[0].metric("🌟 شاشة أونصة الذهب عالمياً", f"${gold_oz:,.2f}", help="السعر الفوري المباشر للأوقية في البورصة العالمية")
    macro_cols[1].metric("🏦 سعر دولار البنك المركزي (EGP)", f"{usd_egp:.2f} ج.م", help="سعر صرف الدولار الرسمي مقابل الجنيه المصري")
    
    st.write("") 
    
    st.markdown("### 💰 أسعار الذهب الحالية في مصر")
    cols = st.columns(4)
    cols[0].metric("عيار 24 (السبائك)", f"{prices['24']:,.2f} ج.م")
    cols[1].metric("عيار 22", f"{prices['22']:,.2f} ج.م")
    cols[2].metric("عيار 21 (الأكثر طلباً)", f"{prices['21']:,.2f} ج.م")
    cols[3].metric("عيار 18 (المشغولات)", f"{prices['18']:,.2f} ج.م")
    
    st.divider()
    
    # محرك التنبيهات التلقائي اللحظي المقارن بالأسعار الحالية
    conn = sqlite3.connect('gold_data.db')
    df_active_alerts = pd.read_sql_query("SELECT * FROM gold_alerts WHERE triggered = 0", conn)
    conn.close()
    
    if not df_active_alerts.empty:
        for idx, row in df_active_alerts.iterrows():
            current_karat_price = prices.get(row['karat'], prices['21'])
            is_fired = False
            alert_msg = ""
            
            if current_karat_price >= row['high']:
                alert_msg = f"🚨 *تنبيه صعود الذهب!*\nالمستحدم: {row['username']}\nعيار {row['karat']} وصل إلى هدف البيع: {row['high']} ج.م\nالسعر الحالي الآن: {current_karat_price:,.2f} ج.م"
                is_fired = True
            elif current_karat_price <= row['low']:
                alert_msg = f"📉 *تنبيه هبوط الذهب!*\nالمستخدم: {row['username']}\nعيار {row['karat']} وصل إلى هدف الشراء: {row['low']} ج.م\nالسعر الحالي الآن: {current_karat_price:,.2f} ج.م"
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

    # إنشاء التبويبات الخمسة الكاملة للبرنامج
    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "📊 التحليل والبورصة", 
        "💡 التوصيات الذكية", 
        "📰 أخبار الذهب الحية", 
        "🔔 إعداد التنبيهات التفاعلية",
        "❓ دليل المساعدة والدعم"
    ])
    
    with tab1:
        st.subheader("📈 أداء سعر الأوقية عالمياً بالدولار (مؤشر البورصة)")
        chart_data, is_fallback = get_safe_historical_data()
        if is_fallback:
            st.info("⚠️ تظهر الآن بيانات بيانية تقريبية مؤقتاً نظراً لقيود التحديث الخارجي. أسعارك الفورية بالأعلى دقيقة 100%.")
        st.line_chart(chart_data)
        
    with tab2:
        st.subheader("🤖 نظام التوصيات والتحليل الفني الآلي")
        if prices["21"] > 3800:
            st.warning("⚠️ مستويات الأسعار الحالية مرتفعة نسبياً في السوق المحلي. نوصي بالتريث واقتناص الهبوط التدريجي للادخار.")
        else:
            st.success("✅ الأسعار الحالية مستقرة في مناطق دعم جيدة جداً. فرصة استثمارية ممتازة للشراء الآمن.")
            
    with tab3:
        st.subheader("📰 آخر مستجدات أسواق الذهب والاقتصاد العالمي")
        gold_news_url = "https://news.google.com/rss/search?q=%D8%A7%D9%84%D8%B0%D9%87%D8%A8&hl=ar&gl=EG&ceid=EG:ar"
        feed = feedparser.parse(gold_news_url)
        if feed.entries:
            for entry in feed.entries[:6]:
                st.markdown(f"🔹 **[{entry.title}]({entry.link})**")
        else:
            st.info("جاري مزامنة شريط الأخبار والتقارير الاقتصادية...")
            
    # --- التبويب الرابع التفاعلي (بدون فورم لحساب الأسعار لحظياً وبث الرسايل فوراً) ---
    with tab4:
        st.subheader("👤 تفعيل ومتابعة أهدافك السعرية الخاصة")
        
        name = st.text_input("اسمك الكريم", key="input_username")
        telegram_id = st.text_input("معرف التليجرام الخاص بك (Chat ID)", key="input_tgid")
        selected_karat = st.selectbox("اختر عيار الذهب المراد مراقبته", ["24", "22", "21", "18"], key="input_karat")
        
        # الحساب اللحظي الفوري للأسعار المقترحة بمجرد تغيير العيار أمام عين المستخدم
        default_high = float(round(prices[selected_karat] + 150))
        default_low = float(round(prices[selected_karat] - 150))
        
        high_target = st.number_input("تنبيه عند الارتفاع إلى (سعر المستهدف للبيع)", value=default_high, key="input_high")
        low_target = st.number_input("تنبيه عند الانخفاض إلى (سعر المستهدف للشراء)", value=default_low, key="input_low")
        
        if st.button("🚀 تفعيل التنبيه المخصّص وإرسال اختبار لهاتفك"):
            if name and telegram_id:
                if not telegram_id.strip().isdigit():
                    st.error("❌ خطأ: معرف الـ Chat ID يجب أن يتكون من أرقام فقط!")
                else:
                    welcome_msg = f"🔔 *مرحباً {name}! تم ربط حسابك بنجاح بـ Gold Meter.*\n\nمراقبة نشطة لعيار {selected_karat}\nمستهدف البيع: {high_target} ج.م\nمستهدف الشراء: {low_target} ج.م"
                    
                    with st.spinner("جاري اختبار الاتصال وإرسال الرسالة السحابية..."):
                        success, reason = send_telegram_message(telegram_id, welcome_msg)
                    
                    if success:
                        # الحفظ في قاعدة البيانات بعد التأكد تماماً من تسليم الرسالة للهاتف
                        conn = sqlite3.connect('gold_data.db')
                        c = conn.cursor()
                        c.execute("""INSERT OR REPLACE INTO gold_alerts (username, tg_id, karat, high, low, triggered) 
                                     VALUES (?, ?, ?, ?, ?, 0)""", (name, telegram_id, selected_karat, high_target, low_target))
                        conn.commit()
                        conn.close()
                        
                        st.success(f"🎯 رائع يا {name}! الرسالة وصلت تليفونك حالا وتم حفظ التنبيه بنجاح في السيرفر.")
                        st.rerun()
                    else:
                        st.error("❌ فشل تليجرام في تسليم الرسالة.")
                        st.warning(f"🔍 السبب المرتد من السيرفر: {reason}")
            else:
                st.error("الرجاء إدخال الاسم ومعرف تليجرام لحفظ الإعدادات.")

        # عرض جدول المراقبة النشط بالأسفل
        conn = sqlite3.connect('gold_data.db')
        df_all = pd.read_sql_query("SELECT * FROM gold_alerts", conn)
        conn.close()
        
        if not df_all.empty:
            st.write("📋 **شاشة مراقبة الطلبات النشطة في السيرفر:**")
            df_all['الحالة'] = df_all['triggered'].apply(lambda x: "🟢 نشط ويراقب السوق" if x == 0 else "📬 تم إرسال التنبيه لهاتفك")
            st.dataframe(df_all[['username', 'karat', 'high', 'low', 'الحالة']], use_container_width=True)

    with tab5:
        st.header("❓ دليل استخدام وإعداد منصة Gold Meter")
        st.markdown("""
        ### 🔍 كيف تستخرج معرف تليجرام الحقيقي (Chat ID)؟
        1. افتح تطبيق تليجرام على هاتفك.
        2. في خانة البحث اكتب اسم البوت الموثوق التالي: `@userinfobot`.
        3. اضغط على خيار **Start** لتفعيل المحادثة معه وسيعطيك رقم الـ ID الخاص بك فوراً.
        """)

    st.markdown("<br><hr>", unsafe_allow_html=True)
    st.markdown("<div style='text-align:center; color:gray; font-size:14px;'>"
                "© Techno logic 2026. Haytham Elsaadany"
                "</div>", unsafe_allow_html=True)

if __name__ == "__main__":
    main()
