import streamlit as st
import pandas as pd
from sqlalchemy import create_engine, text
import requests
import datetime
import time

# ==========================================
# 1. إعدادات الواجهة الاحترافية المحدثة بالكامل
# ==========================================
st.set_page_config(page_title="Gold Meter Pro", page_icon="🏅", layout="wide")

# هندسة الـ CSS لمنع أي تداخل وتحسين التباين والقراءة 100%
st.markdown("""
    <style>
    .main-title { font-size: 32px; font-weight: bold; text-align: center; color: #D4AF37; margin-bottom: 20px; }
    
    /* كروت الأسعار العلوية */
    .price-card { background-color: #1e2430; padding: 15px; border-radius: 10px; border-left: 4px solid #D4AF37; text-align: center; }
    .price-card h3 { margin: 8px 0 0 0; color: #ffffff; font-size: 22px; font-weight: bold; }
    .price-card h5 { margin: 0; color: #D4AF37; font-size: 14px; font-weight: bold; }
    
    /* كروت الأخبار والتوصيات الفنية بدعم كامل للغة العربية */
    .news-box { background-color: #111622; padding: 18px; border-radius: 8px; margin-bottom: 12px; border-right: 4px solid #00ffcc; color: #ffffff; direction: rtl; text-align: right; }
    .news-box-title { color: #00ffcc; font-size: 16px; font-weight: bold; margin-bottom: 8px; }
    .news-box-text { color: #f0f4f8; font-size: 14px; line-height: 1.6; margin-bottom: 5px; }
    .news-box-date { color: #a0aec0; font-size: 12px; display: block; margin-top: 5px; }
    
    .rec-box { background-color: #111622; padding: 18px; border-radius: 8px; margin-bottom: 12px; border-right: 4px solid #D4AF37; color: #ffffff; direction: rtl; text-align: right; }
    .rec-box-title { color: #D4AF37; font-size: 16px; font-weight: bold; margin-bottom: 8px; }
    .rec-box-text { color: #f0f4f8; font-size: 14px; line-height: 1.6; }
    .highlight-green { color: #00ffcc; font-weight: bold; }
    .highlight-white { color: #ffffff; font-weight: bold; }
    
    .source-text { font-size: 13px; color: #00ffcc; text-align: center; margin-top: 5px; font-weight: bold; }
    .warning-text { font-size: 13px; color: #ffcc00; text-align: center; margin-top: 5px; font-weight: bold; }
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
# 3. محرك الأسعار المطور اللحظي وسحب الـ High & Low حركياً
# ==========================================
@st.cache_data(ttl=30)
def fetch_realtime_prices_with_failover():
    ounce_usd = 4019.55  
    high_usd = 4025.00
    low_usd = 3995.00
    usd_egp = 49.25
    source_used = "الأسعار المرجعية"
    is_live = False
    error_log = ""
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    }

    # [المسار الأول]: ياهو فاينانس - سحب السعر اللحظي وأعلى/أقل نقطة لليوم
    try:
        url_gold = "https://query2.finance.yahoo.com/v8/finance/chart/XAUUSD=X?interval=1m&range=1d"
        res_gold = requests.get(url_gold, headers=headers, timeout=4)
        if res_gold.status_code == 200:
            json_data = res_gold.json()
            ounce_usd = float(json_data['chart']['result'][0]['meta']['regularMarketPrice'])
            
            # استخراج أعلى وأقل سعر بأمان لتجنب الـ None القيم الفارغة
            quote_data = json_data['chart']['result'][0]['indicators']['quote'][0]
            valid_highs = [h for h in quote_data.get('high', []) if h is not None]
            valid_lows = [l for l in quote_data.get('low', []) if l is not None]
            
            high_usd = max(valid_highs) if valid_highs else ounce_usd + 5
            low_usd = min(valid_lows) if valid_lows else ounce_usd - 5
            
            source_used = "Yahoo Finance Live Feed"
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
                    high_usd = ounce_usd * 1.002
                    low_usd = ounce_usd * 0.998
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

    return ounce_usd, high_usd, low_usd, usd_egp, is_live, source_used, error_log

ounce_usd, day_high, day_low, usd_egp, is_live, data_source, error_msg = fetch_realtime_prices_with_failover()

gold_pure_price_egp = (ounce_usd * usd_egp) / 31.10348
price_24 = round(gold_pure_price_egp, 2)
price_21 = round(gold_pure_price_egp * (21 / 24), 2)
price_18 = round(gold_pure_price_egp * (18 / 24), 2)

# ==========================================
# 4. حساب مؤشر الاتجاه (Trend Indicator)
# ==========================================
if 'last_price' not in st.session_state:
    st.session_state.last_price = ounce_usd

if ounce_usd > st.session_state.last_price:
    trend_markup = f'<div class="trend-text" style="color:#00ffcc;">📈 حركة السعر الحالية: صعود (+${round(ounce_usd - st.session_state.last_price, 2)}) مقارنة بالقراءة السابقة</div>'
elif ounce_usd < st.session_state.last_price:
    trend_markup = f'<div class="trend-text" style="color:#ff3333;">📉 حركة السعر الحالية: هبوط (-${round(st.session_state.last_price - ounce_usd, 2)}) مقارنة بالقراءة السابقة</div>'
else:
    trend_markup = f'<div class="trend-text" style="color:#ffcc00;">➡️ حركة السعر الحالية: استقرار وثبات سعري لحظي</div>'

st.session_state.last_price = ounce_usd

# ==========================================
# 5. اللوحة الجانبية: الحاسبات الاستثمارية الذكية
# ==========================================
with st.sidebar:
    st.markdown("### 🧮 حاسبة الاستثمار السريع")
    user_budget = st.number_input("أدخل المبلغ المتوفر (ج.م):", value=50000, step=5000)
    
    calc_24 = round(user_budget / price_24, 2) if price_24 > 0 else 0
    calc_21 = round(user_budget / price_21, 2) if price_21 > 0 else 0
    calc_18 = round(user_budget / price_18, 2) if price_18 > 0 else 0
    
    st.info(f"🏆 **عيار 24:** يعادل حوالي `{calc_24}` جرام")
    st.success(f"✨ **عيار 21:** يعادل حوالي `{calc_21}` جرام")
    st.warning(f"⚜️ **عيار 18:** يعادل حوالي `{calc_18}` جرام")
    
    st.divider()
    
    st.markdown("### 🏪 حاسبة السعر الفعلي في المحل")
    selected_carat_calc = st.selectbox("اختر العيار للشراء:", ["عيار 24", "عيار 21", "عيار 18"], key="shop_carat")
    making_fee = st.number_input("المصنعية والدمغة للجرام (ج.م):", value=180, step=10)
    gram_count = st.number_input("عدد الجرامات المراد شراؤها:", value=10, step=1)
    
    base_p = price_24 if selected_carat_calc == "عيار 24" else (price_21 if selected_carat_calc == "عيار 21" else price_18)
    total_per_gram = base_p + making_fee
    final_invoice = total_per_gram * gram_count
    
    st.markdown(f"""
    <div style="background-color:#1e2430; padding:10px; border-radius:5px; border-right:3px solid #00ffcc; direction:rtl; text-align:right;">
    <p style="margin:0; color:#ffffff; font-size:13px;">سعر الجرام بالمصنعية: <b>{total_per_gram:,.2f} ج.م</b></p>
    <p style="margin:5px 0 0 0; color:#00ffcc; font-size:15px; font-weight:bold;">الفاتورة الإجمالية: {final_invoice:,.2f} ج.م</p>
    </div>
    """, unsafe_allow_html=True)
    
    st.divider()
    st.caption("تم التطوير بواسطة م/ هيثم السعدني لمنظومة Gold Meter Pro")

# ==========================================
# 6. تقسيم التطبيق إلى تابات احترافية (Tabs)
# ==========================================
tab_monitor, tab_news, tab_zakat, tab_telegram_setup = st.tabs([
    "📊 شاشة المراقبة والتنبيهات", 
    "📰 الأخبار والتوصيات الفنية", 
    "🕌 حاسبة زكاة الذهب الشرعية",
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
                    time.sleep(1)
                    st.rerun()
                except Exception as e:
                    st.error(f"❌ فشل الحفظ: {e}")

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
            test_msg = f"🔔 *Gold Meter Pro*\nاتصال البوت مية مية ومستعد للمراقبة التلقائية الحقيقية! 🚀"
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

# ------------------------------------------
# محتوى التاب الثاني: الأخبار والتوصيات الاحترافية (تم حل البج المالي والبصري)
# ------------------------------------------
with tab_news:
    st.subheader("📰 شريط أخبار وتوصيات الذهب الفنية اللحظية")
    
    # [تطبيق المعادلة الكلاسيكية للارتكاز والدعم والمقاومة الفنية]
    pivot_global = round((day_high + day_low + ounce_usd) / 3, 2)
    support_global = round((2 * pivot_global) - day_high, 2)
    resistance_global = round((2 * pivot_global) - day_low, 2)
    
    support_egp_21 = round((support_global * usd_egp * 21/24) / 31.10348, 2)
    resistance_egp_21 = round((resistance_global * usd_egp * 21/24) / 31.10348, 2)

    col_news_left, col_news_right = st.columns(2)
    
    # طباعة كروت الـ HTML من اليسار لليمين بدون مسافات بادئة لمنع تحولها لصندوق كود
    with col_news_left:
        st.markdown("### 🌍 آخر المستجدات والتقارير")
        
        html_news_1 = f"""
<div class="news-box">
    <div class="news-box-title">📢 حركة الأونصة العالمية الآن</div>
    <div class="news-box-text">تتحرك الأونصة العالمية الآن في مدى يومي بين أقل سعر <span class="highlight-white">${day_low:,.2f}</span> وأعلى سعر <span class="highlight-white">${day_high:,.2f}</span>، السعر اللحظي الحالي هو <b>${ounce_usd:,.2f}</b>.</div>
    <span class="news-box-date">📅 تحديث: لحظي متزامن</span>
</div>
        """
        st.markdown(html_news_1, unsafe_allow_html=True)

        html_news_2 = f"""
<div class="news-box">
    <div class="news-box-title">🏦 استقرار سعر الصرف المحلي</div>
    <div class="news-box-text">استقرار تام لأسعار الصرف الرسمية للدولار عند مستويات <b>{usd_egp} ج.م</b>، مما يحمي السوق المحلي من القفزات العشوائية المفاجئة ويدعم استقرار التسعير.</div>
    <span class="news-box-date">📅 تحديث: منذ ساعة</span>
</div>
        """
        st.markdown(html_news_2, unsafe_allow_html=True)
        
    with col_news_right:
        st.markdown("### 🎯 التوصيات الحسابية (معادلات بورصة الذهب الكلاسيكية)")
        
        html_rec_1 = f"""
<div class="rec-box">
    <div class="rec-box-title">🎯 نقطة الارتكاز المرجعية الحركية لليوم (Pivot Point)</div>
    <div class="rec-box-text">مستوى الارتكاز المعتمد حسابياً الآن: <span class="highlight-green">${pivot_global:,.2f}</span></div>
    
    <div class="rec-box-title" style="margin-top:12px;">📉 مستويات الدعم الفني الحقيقي (فرص الشراء)</div>
    <div class="rec-box-text">• عالمياً: <b>${support_global:,.2f}</b><br>
    • يعادل محلياً لعيار 21: <span class="highlight-green">{support_egp_21:,.2f} ج.م</span></div>
    
    <div class="rec-box-title" style="margin-top:12px;">📈 مستويات المقاومة الفنية الحقيقية (أهداف البيع)</div>
    <div class="rec-box-text">• عالمياً: <b>${resistance_global:,.2f}</b><br>
    • يعادل محلياً لعيار 21: <span class="highlight-green">{resistance_egp_21:,.2f} ج.م</span></div>
</div>
        """
        st.markdown(html_rec_1, unsafe_allow_html=True)

        html_rec_2 = f"""
<div class="rec-box">
    <div class="rec-box-title">💡 نصيحة الاستثمار المبنية على مؤشر التقلب اليومي</div>
    <div class="rec-box-text">بناءً على النطاق السعري لليوم، يفضل تفعيل تنبيهات الشراء التلقائية عند اقتراب السعر المحلي من نقطة الدعم المحسوبة لتضمن الدخول بأفضل سعر تكلفة ممكن.</div>
</div>
        """
        st.markdown(html_rec_2, unsafe_allow_html=True)

# ------------------------------------------
# محتوى التاب الثالث: حاسبة زكاة الذهب الشرعية
# ------------------------------------------
with tab_zakat:
    st.subheader("🕌 حاسبة زكاة الذهب التلقائية")
    col_z_1, col_z_2 = st.columns(2)
    with col_z_1:
        gold_weight = st.number_input("أدخل الوزن الإجمالي للذهب المتوفر لديك (بالجرام):", value=90.0, step=1.0)
        zakat_carat = st.selectbox("اختر عيار الذهب المخزن لديك:", ["عيار 24", "عيار 21", "عيار 18"])
    
    if zakat_carat == "عيار 24":
        equivalent_24 = gold_weight
        current_val = gold_weight * price_24
    elif zakat_carat == "عيار 21":
        equivalent_24 = gold_weight * (21 / 24)
        current_val = gold_weight * price_21
    else:
        equivalent_24 = gold_weight * (18 / 24)
        current_val = gold_weight * price_18
        
    with col_z_2:
        st.markdown("### 📊 النتيجة الشرعية والحسابية:")
        if equivalent_24 >= 85.0:
            zakat_due_egp = current_val * 0.025
            st.error(f"🚨 **الذهب بلغ النصاب الشرعي!** (يعادل `{equivalent_24:.2f}` جرام عيار 24)")
            st.metric(label="💰 إجمالي القيمة الحالية للذهب:", value=f"{current_val:,.2f} ج.م")
            st.success(f"🕌 **قيمة الزكاة الواجب إخراجها فوراً (2.5%):** {zakat_due_egp:,.2f} ج.م")
        else:
            st.info(f"💡 **لم يبلغ النصاب الشرعي بعد.** الذهب يعادل `{equivalent_24:.2f}` جرام عيار 24، والنصاب المطلوب هو 85 جرام عيار 24 صافي.")
            st.metric(label="💰 القيمة السعرية الحالية لذهبك:", value=f"{current_val:,.2f} ج.م")

# ------------------------------------------
# محتوى التاب الرابع: دليل تشغيل وإعداد تليجرام الشامل
# ------------------------------------------
with tab_telegram_setup:
    st.subheader("🛠️ الدليل الشامل لربط واستخراج بيانات التليجرام")
    st.markdown("""
    ### 1️⃣ أولاً: استخراج الـ Chat ID الخاص بك (مجاني تماماً)
    * في خانة البحث في تليجرام أكتب اسم البوت: `@userinfobot`.
    * اضغط على زر **Start** وانسخ الرقم المكتوب أمام خانة **Id**.
    
    ### 2️⃣ ثانياً: إعداد البوت الخاص بك في الـ Secrets
    ```toml
    TELEGRAM_BOT_TOKEN = "ضع_التوكن_الخاص_بك_هنا"
    ```
    """)

# ==========================================
# 7. محرك التحديث التلقائي اللحظي (Auto-Refresh)
# ==========================================
time.sleep(30)
st.rerun()
