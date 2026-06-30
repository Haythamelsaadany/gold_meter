import streamlit as st
import sqlite3
import pandas as pd
import yfinance as yf
import feedparser
import json
import urllib.request

# إعداد الصفحة العام
st.set_page_config(page_title="Gold Meter Pro 2026", layout="wide", page_icon="🏅")

# ==========================================
# 1. إدارة قاعدة البيانات وعداد الزوار
# ==========================================
def init_db():
    conn = sqlite3.connect('gold_data.db')
    c = conn.cursor()
    # جدول المستخدمين مع إضافة عمود العيار (karat)
    c.execute('''CREATE TABLE IF NOT EXISTS users 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                  username TEXT, 
                  tg_id TEXT UNIQUE, 
                  karat TEXT, 
                  high REAL, 
                  low REAL)''')
    # جدول عداد الزوار
    c.execute('''CREATE TABLE IF NOT EXISTS site_stats (id INTEGER PRIMARY KEY, views INTEGER)''')
    c.execute("INSERT OR IGNORE INTO site_stats (id, views) VALUES (1, 0)")
    conn.commit()
    conn.close()

def update_and_get_views():
    conn = sqlite3.connect('gold_data.db')
    c = conn.cursor()
    # زيادة العداد مع كل تحديث حقيقي للصفحة (Session-based)
    if 'tracked' not in st.session_state:
        st.session_state['tracked'] = True
        c.execute("UPDATE site_stats SET views = views + 1 WHERE id = 1")
        conn.commit()
    c.execute("SELECT views FROM site_stats WHERE id = 1")
    views = c.fetchone()[0]
    conn.close()
    return views

# ==========================================
# 2. جلب الأسعار وحساب العيارات
# ==========================================
def get_market_data():
    try:
        # جلب سعر الأوقية العالمي
        with urllib.request.urlopen("https://api.gold-api.com/price/XAU", timeout=5) as r:
            gold_oz = float(json.load(r)['price'])
        # جلب سعر الدولار مقابل الجنيه
        with urllib.request.urlopen("https://open.er-api.com/v6/latest/USD", timeout=5) as r:
            usd_egp = float(json.load(r)['rates']['EGP'])
    except:
        # قيم احتياطية في حال فشل الاتصال مؤقتاً
        gold_oz, usd_egp = 2330.0, 49.50
    
    g24 = (gold_oz * usd_egp) / 31.1035
    return {
        "24": g24,
        "22": g24 * (22/24),
        "21": g24 * (21/24),
        "18": g24 * (18/24)
    }, gold_oz, usd_egp

# ==========================================
# 3. واجهة التطبيق والتحكم التفاعلي
# ==========================================
def main():
    init_db()
    views_count = update_and_get_views()
    
    # رأس الصفحة والعداد
    st.title("🏅 Gold Meter Pro - المنظومة التفاعلية الشاملة")
    st.caption(f"👁️ عدد زيارات المنصة: {views_count} زائر")
    
    # جلب الأسعار الحالية
    prices, gold_oz, usd_egp = get_market_data()
    
    # عرض جميع العيارات في صدارة الموقع
    cols = st.columns(4)
    cols[0].metric("عيار 24 (السبائك)", f"{prices['24']:,.2f} ج.م")
    cols[1].metric("عيار 22", f"{prices['22']:,.2f} ج.م")
    cols[2].metric("عيار 21 (الأكثر طلباً)", f"{prices['21']:,.2f} ج.م")
    cols[3].metric("عيار 18 (المشغولات)", f"{prices['18']:,.2f} ج.م")
    
    st.divider()
    
    # ==========================================
    # محرك التنبيهات التفاعلي اللحظي (المحاكاة النشطة)
    # ==========================================
    conn = sqlite3.connect('gold_data.db')
    df_users = pd.read_sql_query("SELECT * FROM users", conn)
    conn.close()
    
    # فحص التنبيهات وعرضها للمستخدم فوراً إذا تحقق الشرط
    if not df_users.empty:
        for idx, row in df_users.iterrows():
            current_karat_price = prices.get(row['karat'], prices['21'])
            if current_karat_price >= row['high']:
                st.toast(f"🚨 تنبيه للعميل {row['username']}: عيار {row['karat']} وصل لهدف البيع المستهدف ({row['high']} ج.م)!")
            elif current_karat_price <= row['low']:
                st.toast(f"📉 تنبيه للعميل {row['username']}: عيار {row['karat']} وصل لهدف الشراء المستهدف ({row['low']} ج.م)!")

    # الأقسام الرئيسية للموقع
    tab1, tab2, tab3, tab4 = st.tabs(["📊 التحليل والبورصة", "💡 التوصيات الذكية", "📰 أخبار الذهب الحية", "🔔 إعداد التنبيهات"])
    
    with tab1:
        st.subheader("📈 أداء الأوقية عالمياً (بالدولار)")
        hist = yf.Ticker("GC=F").history(period="1mo")
        st.line_chart(hist['Close'])
        
    with tab2:
        st.subheader("🤖 نظام التوصيات الآلي")
        # تحليل فني مبسط مبني على السعر الحالي لعيار 21
        if prices["21"] > 3800:
            st.warning("⚠️ السعر الحالي مرتفع نسبياً. نوصي بالتريث في الشراء ومراقبة جني الأرباح.")
        else:
            st.success("✅ الأسعار في مناطق دعم جيدة. فرصة مناسبة للادخار والشراء على أجزاء.")
            
    with tab3:
        st.subheader("📰 آخر أخبار الذهب والاقتصاد (جلب تلقائي ومباشر)")
        # استخدام RSS من جوغل نيوز لضمان التحديث المستمر وعدم الحظر
        gold_news_url = "https://news.google.com/rss/search?q=%D8%A7%D9%84%D8%B0%D9%87%D8%A8&hl=ar&gl=EG&ceid=EG:ar"
        feed = feedparser.parse(gold_news_url)
        
        if feed.entries:
            for entry in feed.entries[:6]:
                st.markdown(f"🔹 **[{entry.title}]({entry.link})**")
                st.caption(f"تاريخ النشر: {entry.published}")
        else:
            st.info("جاري تحديث شريط الأخبار من السيرفر العالمي...")
            
    with tab4:
        st.subheader("👤 سجل تنبيهك المخصص حسب عيار ذهبك")
        with st.form("user_alert_form"):
            name = st.text_input("اسم المستخدم")
            telegram_id = st.text_input("معرف التليجرام أو رقم الهاتف")
            # إضافة قائمة اختيار العيار المطلوبة
            selected_karat = st.selectbox("اختر عيار الذهب الذي تمتلكه", ["24", "22", "21", "18"])
            
            high_target = st.number_input("تنبيه عند الارتفاع إلى (سعر البيع)", value=float(round(prices[selected_karat] + 200)))
            low_target = st.number_input("تنبيه عند الانخفاض إلى (سعر الشراء)", value=float(round(prices[selected_karat] - 200)))
            
            if st.form_submit_button("تفعيل التنبيه المخصّص"):
                if name and telegram_id:
                    conn = sqlite3.connect('gold_data.db')
                    c = conn.cursor()
                    c.execute("""INSERT OR REPLACE INTO users (username, tg_id, karat, high, low) 
                                 VALUES (?, ?, ?, ?, ?)""", (name, telegram_id, selected_karat, high_target, low_target))
                    conn.commit()
                    conn.close()
                    st.success(f"🎯 تم بنجاح تفعيل التنبيه لـ عيار {selected_karat}! سيظهر التنبيه في النظام فور وصول السعر للهدف.")
                    st.rerun()
                else:
                    st.error("الرجاء ملء حقول الاسم والمعرف لتفعيل النظام.")

        # عرض قائمة المشتركين النشطين داخل التطبيق للتفاعلية
        if not df_users.empty:
            st.write("📋 **التنبيهات النشطة حالياً في النظام:**")
            st.dataframe(df_users[['username', 'karat', 'high', 'low']], use_container_width=True)

    # تذييل الصفحة الاحترافي بالحقوق المطلوبة
    st.markdown("<br><hr>", unsafe_allow_html=True)
    st.markdown("<div style='text-align:center; color:gray; font-size:14px;'>"
                "© Techno logic 2026. Haytham Elsaadany"
                "</div>", unsafe_allow_html=True)

if __name__ == "__main__":
    main()
