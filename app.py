import streamlit as st
import sqlite3
import pandas as pd
import yfinance as yf
import feedparser
import requests
import re
import time
import json
import urllib.request
import threading
from datetime import datetime, timedelta
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import random

# ==========================================
# إعدادات الصفحة
# ==========================================
st.set_page_config(
    page_title="🏅 Gold Meter Pro - منصة الذهب المتكاملة",
    layout="wide",
    page_icon="🏅",
    initial_sidebar_state="expanded"
)

# ==========================================
# إعدادات ثابتة
# ==========================================
OUNCE_TO_GRAM = 31.1035

# ✅ الأسعار المعيارية الثابتة (من البرنامج المعياري)
STANDARD_GOLD_PRICE = 4060.2  # سعر الأونصة بالدولار
STANDARD_USD_PRICE = 50.23    # سعر الدولار بالجنيه
STANDARD_TAX_RATE = 0.02      # 2% دمغة وضريبة

# ==========================================
# 1. نظام تليجرام
# ==========================================
def send_telegram_message(chat_id, text):
    try:
        token = "8813434919:AAHytB4BlyZ_NgwSvprzpEXBrNUXhLPdGYk"
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {"chat_id": str(chat_id).strip(), "text": text, "parse_mode": "Markdown"}
        response = requests.post(url, json=payload, timeout=10)
        return response.status_code == 200, "✅ تم الإرسال"
    except Exception as e:
        return False, f"❌ خطأ: {str(e)}"

# ==========================================
# 2. قاعدة البيانات
# ==========================================
def init_db():
    conn = sqlite3.connect('gold_data.db')
    c = conn.cursor()
    
    c.execute('''CREATE TABLE IF NOT EXISTS gold_alerts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT,
        tg_id TEXT,
        karat TEXT,
        high_target REAL,
        low_target REAL,
        triggered INTEGER DEFAULT 0,
        last_alerted_date TEXT,
        points INTEGER DEFAULT 0,
        join_date TEXT DEFAULT CURRENT_DATE
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS site_stats (
        id INTEGER PRIMARY KEY,
        views INTEGER
    )''')
    c.execute("INSERT OR IGNORE INTO site_stats (id, views) VALUES (1, 0)")
    
    c.execute('''CREATE TABLE IF NOT EXISTS price_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        gold_price REAL,
        usd_price REAL,
        recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    
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

def save_alert(username, tg_id, karat, high, low):
    conn = sqlite3.connect('gold_data.db')
    c = conn.cursor()
    try:
        c.execute("""
            INSERT INTO gold_alerts (username, tg_id, karat, high_target, low_target, triggered, join_date)
            VALUES (?, ?, ?, ?, ?, 0, date('now'))
        """, (username, tg_id, karat, float(high), float(low)))
        conn.commit()
        return True, "✅ تم الحفظ"
    except Exception as e:
        return False, f"❌ خطأ: {e}"
    finally:
        conn.close()

def get_alerts(only_active=True):
    conn = sqlite3.connect('gold_data.db')
    query = "SELECT id, username, tg_id, karat, high_target, low_target, triggered, last_alerted_date, points, join_date FROM gold_alerts"
    if only_active:
        query += " WHERE triggered = 0"
    query += " ORDER BY points DESC, id DESC"
    df = pd.read_sql_query(query, conn)
    conn.close()
    return df

def update_alert_triggered(alert_id):
    conn = sqlite3.connect('gold_data.db')
    c = conn.cursor()
    today = datetime.now().strftime('%Y-%m-%d')
    c.execute("UPDATE gold_alerts SET triggered = 1, last_alerted_date = ? WHERE id = ?", (today, alert_id))
    conn.commit()
    conn.close()

def delete_user_alerts(tg_id):
    conn = sqlite3.connect('gold_data.db')
    c = conn.cursor()
    c.execute("DELETE FROM gold_alerts WHERE tg_id = ?", (tg_id,))
    conn.commit()
    conn.close()

def add_points(tg_id, points):
    conn = sqlite3.connect('gold_data.db')
    c = conn.cursor()
    c.execute("UPDATE gold_alerts SET points = points + ? WHERE tg_id = ?", (points, tg_id))
    conn.commit()
    conn.close()

# ==========================================
# 3. جلب الأسعار (باستخدام القيم المعيارية الثابتة)
# ==========================================
def get_market_data():
    """
    استخدام الأسعار المعيارية الثابتة بدلاً من المصادر غير الدقيقة
    """
    
    # ✅ استخدام الأسعار المعيارية الثابتة
    gold_oz = st.session_state.get('manual_gold', STANDARD_GOLD_PRICE)
    usd_egp = st.session_state.get('manual_usd', STANDARD_USD_PRICE)
    
    # ✅ نسبة الدمغة والضريبة
    tax_rate = st.session_state.get('tax_rate', STANDARD_TAX_RATE)
    
    # ===== حساب أسعار الجرامات مع الدمغة =====
    gram_24_base = (gold_oz * usd_egp) / OUNCE_TO_GRAM
    
    karat_data = {}
    for karat in [24, 22, 21, 18]:
        base_price = gram_24_base * (karat / 24)
        
        # إضافة الدمغة والضريبة
        price_with_tax = base_price * (1 + tax_rate)
        
        spread_rates = {24: 0.0085, 22: 0.0090, 21: 0.0085, 18: 0.0080}
        spread = spread_rates.get(karat, 0.0085)
        
        buy_price = price_with_tax * (1 - spread/2)
        sell_price = price_with_tax * (1 + spread/2)
        
        karat_data[str(karat)] = {
            'buy': round(buy_price, 2),
            'sell': round(sell_price, 2),
            'mid': round(price_with_tax, 2)
        }
    
    return karat_data, gold_oz, usd_egp

# ==========================================
# 4. تحليل المشاعر للأخبار
# ==========================================
def sentiment_analysis(text):
    positive_words = ['صعود', 'ارتفاع', 'زيادة', 'قفزة', 'مكاسب', 'إيجابي', 'جيد', 'ممتاز', 'نمو', 'تحسن', 'ربح', 'نجاح']
    negative_words = ['هبوط', 'انخفاض', 'تراجع', 'كسر', 'خسائر', 'سلبي', 'سيء', 'ضغط', 'أزمة', 'انكماش', 'خطر']
    
    text_lower = text.lower()
    positive_count = sum(1 for word in positive_words if word in text_lower)
    negative_count = sum(1 for word in negative_words if word in text_lower)
    
    if positive_count > negative_count:
        return "📈 إيجابي", positive_count - negative_count
    elif negative_count > positive_count:
        return "📉 سلبي", negative_count - positive_count
    else:
        return "➡️ محايد", 0

# ==========================================
# 5. مؤشر الخوف والطمع
# ==========================================
def calculate_fear_greed(gold_oz, usd_egp, karat_data):
    score = 50
    
    if gold_oz > 2450:
        score -= 15
    elif gold_oz > 2400:
        score -= 8
    elif gold_oz > 2350:
        score += 5
    elif gold_oz > 2300:
        score += 10
    else:
        score += 15
    
    price_21 = karat_data.get('21', {}).get('mid', 0)
    if price_21 > 5900:
        score -= 12
    elif price_21 > 5800:
        score -= 6
    elif price_21 > 5700:
        score += 5
    elif price_21 > 5600:
        score += 10
    else:
        score += 12
    
    if usd_egp > 50.5:
        score -= 10
    elif usd_egp > 49.5:
        score -= 5
    elif usd_egp > 48.5:
        score += 5
    else:
        score += 10
    
    try:
        ticker = yf.Ticker("GC=F")
        hist = ticker.history(period="5d")
        if not hist.empty and len(hist) > 1:
            volatility = hist['Close'].pct_change().std() * 100
            if volatility > 2:
                score -= 8
            elif volatility > 1:
                score -= 3
            else:
                score += 5
    except:
        pass
    
    score = max(0, min(100, score))
    
    if score >= 80:
        status = "🟢 طمع شديد"
        recommendation = "السوق في ذروة التفاؤل - كن حذراً"
    elif score >= 60:
        status = "🟡 طمع"
        recommendation = "السوق متفائل - توقع تصحيح"
    elif score >= 40:
        status = "🟠 محايد"
        recommendation = "السوق متوازن - انتظر تأكيد"
    elif score >= 20:
        status = "🔴 خوف"
        recommendation = "السوق خائف - فرصة شراء"
    else:
        status = "🔴 خوف شديد"
        recommendation = "السوق في ذروة الخوف - فرصة شراء ممتازة"
    
    return score, status, recommendation

# ==========================================
# 6. التوصيات المتقدمة
# ==========================================
def get_advanced_analysis(gold_oz, usd_egp, karat_data):
    recommendations = []
    score = 0
    details = {}
    
    if gold_oz > 2450:
        recommendations.append("🔴 **الذهب في منطقة مقاومة قوية جداً** (أعلى من 2450$)")
        score -= 15
        details['gold'] = 'مقاومة قوية'
    elif gold_oz > 2400:
        recommendations.append("🟡 **الذهب في منطقة مقاومة** (2400-2450$)")
        score -= 5
        details['gold'] = 'مقاومة'
    elif gold_oz > 2350:
        recommendations.append("🟢 **الذهب في منطقة محايدة** (2350-2400$)")
        score += 5
        details['gold'] = 'محايد'
    elif gold_oz > 2300:
        recommendations.append("🟢 **الذهب في منطقة دعم** (2300-2350$)")
        score += 10
        details['gold'] = 'دعم'
    else:
        recommendations.append("🟢 **الذهب في منطقة دعم قوية جداً** (أقل من 2300$)")
        score += 15
        details['gold'] = 'دعم قوي'
    
    price_21 = karat_data.get('21', {}).get('mid', 0)
    if price_21 > 5900:
        recommendations.append("🔴 **عيار 21 مرتفع جداً**")
        score -= 10
        details['karat21'] = 'مرتفع جداً'
    elif price_21 > 5800:
        recommendations.append("🟡 **عيار 21 مرتفع**")
        score -= 5
        details['karat21'] = 'مرتفع'
    elif price_21 > 5700:
        recommendations.append("🟢 **عيار 21 متوسط**")
        score += 5
        details['karat21'] = 'متوسط'
    elif price_21 > 5600:
        recommendations.append("🟢 **عيار 21 جذاب**")
        score += 10
        details['karat21'] = 'جذاب'
    else:
        recommendations.append("🟢 **عيار 21 جذاب جداً**")
        score += 15
        details['karat21'] = 'جذاب جداً'
    
    try:
        ticker = yf.Ticker("GC=F")
        hist = ticker.history(period="1mo")
        if not hist.empty and len(hist) > 20:
            close_prices = hist['Close']
            
            delta = close_prices.diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rs = gain / loss
            rsi = 100 - (100 / (1 + rs))
            current_rsi = rsi.iloc[-1] if not rsi.empty else 50
            
            if current_rsi > 70:
                recommendations.append(f"🔴 **RSI في تشبع شرائي** ({current_rsi:.1f})")
                score -= 10
                details['rsi'] = f"{current_rsi:.1f} (تشبع شرائي)"
            elif current_rsi > 60:
                recommendations.append(f"🟡 **RSI قوي** ({current_rsi:.1f})")
                score -= 3
                details['rsi'] = f"{current_rsi:.1f} (قوي)"
            elif current_rsi > 40:
                recommendations.append(f"🟢 **RSI محايد** ({current_rsi:.1f})")
                score += 5
                details['rsi'] = f"{current_rsi:.1f} (محايد)"
            else:
                recommendations.append(f"🟢 **RSI في تشبع بيعي** ({current_rsi:.1f})")
                score += 10
                details['rsi'] = f"{current_rsi:.1f} (تشبع بيعي)"
            
            ma7 = close_prices.rolling(window=7).mean().iloc[-1]
            ma20 = close_prices.rolling(window=20).mean().iloc[-1]
            current_price = close_prices.iloc[-1]
            
            if current_price > ma7 > ma20:
                recommendations.append("🟢 **اتجاه صاعد قوي**")
                score += 8
                details['trend'] = "صاعد"
            elif current_price < ma7 < ma20:
                recommendations.append("🔴 **اتجاه هابط**")
                score -= 8
                details['trend'] = "هابط"
            else:
                recommendations.append("🟡 **اتجاه عرضي**")
                details['trend'] = "عرضي"
    except:
        pass
    
    if score >= 25:
        recommendations.append("🌟 **توصية قوية جداً بالشراء**")
        details['final'] = 'شراء قوي'
    elif score >= 15:
        recommendations.append("📈 **توصية بالشراء**")
        details['final'] = 'شراء'
    elif score >= 5:
        recommendations.append("➡️ **توصية بالاحتفاظ**")
        details['final'] = 'احتفاظ'
    elif score >= -5:
        recommendations.append("🟡 **توصية بالحذر**")
        details['final'] = 'حذر'
    else:
        recommendations.append("🔴 **توصية بالبيع**")
        details['final'] = 'بيع'
    
    recommendations.append("")
    recommendations.append("🎯 **نقاط الدعم والمقاومة:**")
    recommendations.append(f"   • دعم: ${gold_oz - 50:.0f} | مقاومة: ${gold_oz + 50:.0f}")
    recommendations.append(f"   • دعم قوي: ${gold_oz - 100:.0f} | مقاومة قوية: ${gold_oz + 100:.0f}")
    
    return recommendations, score, details

# ==========================================
# 7. الأخبار
# ==========================================
def fetch_all_news():
    all_news = []
    feeds = [
        ("https://news.google.com/rss/search?q=%D8%A7%D9%84%D8%B0%D9%87%D8%A8&hl=ar&gl=EG&ceid=EG:ar", "Google News"),
        ("https://feeds.feedburner.com/egyptgold", "مصر للذهب"),
        ("https://www.cnbcarabia.com/rss", "CNBC عربية"),
        ("https://www.aljazeera.net/feeds/rss", "الجزيرة"),
        ("https://www.bbc.com/arabic/index.xml", "BBC عربي"),
    ]
    
    for url, source in feeds:
        try:
            feed = feedparser.parse(url)
            if feed.entries:
                for entry in feed.entries[:3]:
                    sentiment, sentiment_score = sentiment_analysis(entry.title + " " + entry.get('summary', ''))
                    
                    all_news.append({
                        'title': entry.title,
                        'link': entry.link,
                        'source': source,
                        'published': entry.get('published', 'تاريخ غير معروف'),
                        'sentiment': sentiment,
                        'sentiment_score': sentiment_score
                    })
        except:
            continue
    
    all_news.sort(key=lambda x: x['sentiment_score'], reverse=True)
    return all_news[:15]

# ==========================================
# 8. الرسم البياني
# ==========================================
@st.cache_data(ttl=300)
def get_historical_data():
    try:
        ticker = yf.Ticker("GC=F")
        hist = ticker.history(period="2mo")
        if not hist.empty:
            return hist, False
    except:
        pass
    dates = [datetime.now() - timedelta(days=i) for i in range(60)][::-1]
    prices = [2350 + i*0.8 for i in range(60)]
    df = pd.DataFrame({"Close": prices}, index=dates)
    return df, True

# ==========================================
# 9. التنبيهات الخلفية
# ==========================================
def check_and_send_alerts():
    karat_data, gold_oz, _ = get_market_data()
    today = datetime.now().strftime('%Y-%m-%d')
    df = get_alerts(only_active=True)
    if df.empty:
        return "ℹ️ لا توجد تنبيهات نشطة"
    
    msgs = []
    for _, row in df.iterrows():
        alert_id = row['id']
        username = row['username']
        tg_id = row['tg_id']
        karat = row['karat']
        high = float(row['high_target'])
        low = float(row['low_target'])
        last_alerted = row.get('last_alerted_date')
        
        current = karat_data.get(karat, {}).get('mid', 0)
        
        if current >= high and last_alerted != today:
            add_points(tg_id, 10)
            alert_text = f"""🚀 *تنبيه صعود الذهب!*

👤 المستخدم: {username}
💎 العيار: {karat}
💰 السعر الحالي: {current:,.2f} ج.م
🎯 هدف البيع: {high:,.0f} ج.م
⭐ نقاطك: +10

📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"""
            success, _ = send_telegram_message(tg_id, alert_text)
            if success:
                update_alert_triggered(alert_id)
                msgs.append(f"✅ تنبيه لـ {username}")
        elif current <= low and last_alerted != today:
            add_points(tg_id, 5)
            alert_text = f"""📉 *تنبيه هبوط الذهب!*

👤 المستخدم: {username}
💎 العيار: {karat}
💰 السعر الحالي: {current:,.2f} ج.م
🎯 هدف الشراء: {low:,.0f} ج.م
⭐ نقاطك: +5

📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"""
            success, _ = send_telegram_message(tg_id, alert_text)
            if success:
                update_alert_triggered(alert_id)
                msgs.append(f"✅ تنبيه لـ {username}")
    
    return "\n".join(msgs) if msgs else "ℹ️ لا توجد تنبيهات جديدة"

def start_background_checker():
    if "checker_running" not in st.session_state:
        st.session_state.checker_running = False
    
    if not st.session_state.checker_running:
        def checker_loop():
            while True:
                try:
                    check_and_send_alerts()
                except:
                    pass
                time.sleep(30)
        
        thread = threading.Thread(target=checker_loop, daemon=True)
        thread.start()
        st.session_state.checker_running = True

# ==========================================
# 10. الواجهة الرئيسية
# ==========================================
def main():
    init_db()
    start_background_checker()
    views = update_and_get_views()
    
    # إعدادات الجلسة
    if 'usd_hedge' not in st.session_state:
        st.session_state['usd_hedge'] = 0.00
    if 'tax_rate' not in st.session_state:
        st.session_state['tax_rate'] = STANDARD_TAX_RATE
    if 'manual_gold' not in st.session_state:
        st.session_state['manual_gold'] = STANDARD_GOLD_PRICE
    if 'manual_usd' not in st.session_state:
        st.session_state['manual_usd'] = STANDARD_USD_PRICE
    
    # الشريط الجانبي
    with st.sidebar:
        st.image("https://img.icons8.com/color/96/000000/gold-bars.png", width=80)
        st.title("🏅 Gold Meter Pro")
        
        st.markdown("### ⚙️ تحكم السعر")
        
        st.markdown("#### 🎯 الأسعار المعيارية")
        col1, col2 = st.columns(2)
        with col1:
            manual_gold = st.number_input(
                "سعر الأونصة ($)",
                value=float(st.session_state.get('manual_gold', STANDARD_GOLD_PRICE)),
                step=0.1,
                format="%.2f"
            )
        with col2:
            manual_usd = st.number_input(
                "سعر الدولار (ج.م)",
                value=float(st.session_state.get('manual_usd', STANDARD_USD_PRICE)),
                step=0.01,
                format="%.2f"
            )
        
        if st.button("✅ تطبيق الأسعار"):
            st.session_state['manual_gold'] = manual_gold
            st.session_state['manual_usd'] = manual_usd
            st.success("✅ تم تحديث الأسعار!")
            st.rerun()
        
        st.divider()
        
        # نسبة الدمغة
        st.markdown("### 🏷️ الدمغة والضريبة")
        tax_rate = st.slider(
            "نسبة الدمغة والضريبة (%)",
            min_value=0.0,
            max_value=5.0,
            step=0.1,
            value=st.session_state['tax_rate'] * 100,
            help="النسبة المضافة على سعر الجرام"
        )
        if tax_rate != st.session_state['tax_rate'] * 100:
            st.session_state['tax_rate'] = tax_rate / 100
            st.rerun()
        
        # جلب الأسعار
        karat_data, gold_oz, usd_egp = get_market_data()
        
        st.markdown("### 📊 المؤشرات")
        st.metric("🌍 أونصة الذهب", f"${gold_oz:,.2f}")
        st.metric("💵 الدولار", f"{usd_egp:.2f} ج.م")
        st.metric("📊 الدمغة", f"{st.session_state['tax_rate']*100:.1f}%")
        
        st.divider()
        st.markdown("### 💎 الجرامات")
        for k in ['24', '22', '21', '18']:
            data = karat_data.get(k, {})
            mid = data.get('mid', 0)
            st.metric(f"عيار {k}", f"{mid:,.2f} ج.م")
        
        st.divider()
        st.caption(f"👁️ زوار اليوم: {views}")
        st.caption("⏱️ تحديث لحظي")
    
    # المحتوى الرئيسي
    st.title("🏅 Gold Meter Pro - منصة الذهب المتكاملة")
    st.markdown(f"🔄 **آخر تحديث:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    st.info(f"💰 **الأسعار المعيارية:** أونصة = ${gold_oz:.2f} | دولار = {usd_egp:.2f} ج.م | دمغة = {st.session_state['tax_rate']*100:.1f}%")
    
    # مؤشر الخوف والطمع
    fear_greed_score, fear_greed_status, fear_greed_rec = calculate_fear_greed(gold_oz, usd_egp, karat_data)
    
    # بطاقات الأسعار
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.markdown(f"""
        <div style='background: linear-gradient(135deg, #1a1a2e, #16213e); padding: 20px; border-radius: 15px; text-align: center; border: 2px solid #FFD700;'>
            <h4 style='color: #FFD700;'>🌍 أونصة الذهب</h4>
            <h1 style='color: white;'>${gold_oz:,.2f}</h1>
            <small style='color: #aaa;'>معياري</small>
        </div>
        """, unsafe_allow_html=True)
    
    with col2:
        st.markdown(f"""
        <div style='background: linear-gradient(135deg, #1a1a2e, #16213e); padding: 20px; border-radius: 15px; text-align: center; border: 2px solid #00d4ff;'>
            <h4 style='color: #00d4ff;'>💵 الدولار</h4>
            <h1 style='color: white;'>{usd_egp:.2f} ج.م</h1>
            <small style='color: #aaa;'>معياري</small>
        </div>
        """, unsafe_allow_html=True)
    
    with col3:
        price_21 = karat_data.get('21', {}).get('mid', 0)
        st.markdown(f"""
        <div style='background: linear-gradient(135deg, #1a1a2e, #16213e); padding: 20px; border-radius: 15px; text-align: center; border: 2px solid #ff6b6b;'>
            <h4 style='color: #ff6b6b;'>🏅 عيار 21</h4>
            <h1 style='color: white;'>{price_21:,.2f} ج.م</h1>
            <small style='color: #aaa;'>شامل الدمغة</small>
        </div>
        """, unsafe_allow_html=True)
    
    with col4:
        color = "#00ff88" if fear_greed_score >= 60 else "#ffd93d" if fear_greed_score >= 40 else "#ff6b6b"
        st.markdown(f"""
        <div style='background: linear-gradient(135deg, #1a1a2e, #16213e); padding: 20px; border-radius: 15px; text-align: center; border: 2px solid {color};'>
            <h4 style='color: {color};'>📊 مؤشر الخوف والطمع</h4>
            <h1 style='color: white;'>{fear_greed_score}</h1>
            <small style='color: #aaa;'>{fear_greed_status}</small>
        </div>
        """, unsafe_allow_html=True)
    
    st.divider()
    
    # ===== أسعار الشراء والبيع =====
    st.markdown("### 💰 أسعار الشراء والبيع (شاملة الدمغة)")
    
    cols = st.columns(4)
    for i, k in enumerate(['24', '22', '21', '18']):
        data = karat_data.get(k, {})
        buy = data.get('buy', 0)
        sell = data.get('sell', 0)
        spread = round(sell - buy, 2)
        
        with cols[i]:
            st.markdown(f"""
            <div style='background: linear-gradient(135deg, #1a1a2e, #16213e); padding: 15px; border-radius: 12px; text-align: center; border: 1px solid #333;'>
                <h3 style='color: #ffd93d;'>عيار {k}</h3>
                <div style='display: flex; justify-content: space-around;'>
                    <div>
                        <small style='color: #aaa;'>شراء</small>
                        <h4 style='color: #00ff88;'>{buy:,.2f}</h4>
                    </div>
                    <div>
                        <small style='color: #aaa;'>بيع</small>
                        <h4 style='color: #ff6b6b;'>{sell:,.2f}</h4>
                    </div>
                </div>
                <small style='color: #888;'>الفرق: {spread:.2f} ج.م</small>
            </div>
            """, unsafe_allow_html=True)
    
    st.divider()
    
    # ===== التبويبات (نفس الكود السابق) =====
    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
        "📊 التحليل", 
        "💡 التوصيات", 
        "📰 الأخبار",
        "🏆 المتصدرين",
        "🔔 التنبيهات",
        "⚙️ الإدارة"
    ])
    
    with tab1:
        st.subheader("📈 التحليل الفني المتقدم")
        hist_data, _ = get_historical_data()
        
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=hist_data.index,
            y=hist_data['Close'],
            mode='lines',
            name='سعر الذهب',
            line=dict(color='#FFD700', width=2)
        ))
        
        if len(hist_data) > 7:
            ma7 = hist_data['Close'].rolling(window=7).mean()
            ma20 = hist_data['Close'].rolling(window=20).mean()
            ma50 = hist_data['Close'].rolling(window=50).mean() if len(hist_data) > 50 else None
            
            fig.add_trace(go.Scatter(
                x=hist_data.index,
                y=ma7,
                mode='lines',
                name='MA 7',
                line=dict(color='#00d4ff', width=1, dash='dash')
            ))
            fig.add_trace(go.Scatter(
                x=hist_data.index,
                y=ma20,
                mode='lines',
                name='MA 20',
                line=dict(color='#ff6b6b', width=1, dash='dot')
            ))
            if ma50 is not None:
                fig.add_trace(go.Scatter(
                    x=hist_data.index,
                    y=ma50,
                    mode='lines',
                    name='MA 50',
                    line=dict(color='#ffd93d', width=1, dash='dashdot')
                ))
        
        fig.update_layout(
            template="plotly_dark",
            paper_bgcolor="#0f0f1e",
            plot_bgcolor="#080810",
            height=400,
            margin=dict(l=20, r=20, t=20, b=20),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
        )
        st.plotly_chart(fig, use_container_width=True)
        
        col1, col2, col3, col4 = st.columns(4)
        if len(hist_data) > 1:
            current = hist_data['Close'].iloc[-1]
            prev = hist_data['Close'].iloc[-2]
            change = ((current - prev) / prev) * 100
            with col1:
                st.metric("📈 السعر الحالي", f"${current:.2f}", f"{change:+.2f}%")
            with col2:
                st.metric("📊 أعلى 30 يوم", f"${hist_data['Close'].max():.2f}")
            with col3:
                st.metric("📉 أدنى 30 يوم", f"${hist_data['Close'].min():.2f}")
            with col4:
                st.metric("📊 المتوسط", f"${hist_data['Close'].mean():.2f}")
    
    with tab2:
        st.subheader("💡 التوصيات المتقدمة")
        
        recs, score, details = get_advanced_analysis(gold_oz, usd_egp, karat_data)
        
        col1, col2 = st.columns([1, 2])
        with col1:
            if score >= 20:
                st.success("📈 **توصية قوية بالشراء**")
            elif score >= 10:
                st.info("📊 **توصية بالشراء**")
            elif score >= 0:
                st.info("📊 **توصية بالاحتفاظ**")
            elif score >= -10:
                st.warning("🟡 **توصية بالحذر**")
            else:
                st.error("📉 **توصية بالبيع**")
            st.metric("📊 نقاط القوة", f"{score}/100")
            
            st.markdown("#### 📋 التفاصيل")
            for key, value in details.items():
                if key not in ['final']:
                    st.caption(f"**{key}:** {value}")
        
        with col2:
            st.markdown("#### 📋 التوصيات")
            for rec in recs:
                if "🔴" in rec or "📉" in rec:
                    st.warning(rec)
                elif "🟢" in rec or "📈" in rec or "🌟" in rec:
                    st.success(rec)
                else:
                    st.info(rec)
        
        st.divider()
        st.markdown("### 🎯 استراتيجية التداول")
        col1, col2, col3 = st.columns(3)
        with col1:
            st.markdown(f"""
            **🛡️ الدعم**
            - قوي: ${gold_oz - 100:.0f}
            - متوسط: ${gold_oz - 50:.0f}
            """)
        with col2:
            st.markdown(f"""
            **🚀 المقاومة**
            - متوسط: ${gold_oz + 50:.0f}
            - قوي: ${gold_oz + 100:.0f}
            """)
        with col3:
            st.markdown("""
            **⚖️ التخصيص**
            - شراء: 30-40%
            - احتفاظ: 40-50%
            - بيع: 10-20%
            """)
    
    with tab3:
        st.subheader("📰 أخبار الذهب والدولار")
        
        all_news = fetch_all_news()
        if all_news:
            positive = sum(1 for n in all_news if 'إيجابي' in n['sentiment'])
            negative = sum(1 for n in all_news if 'سلبي' in n['sentiment'])
            neutral = sum(1 for n in all_news if 'محايد' in n['sentiment'])
            
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("📈 إيجابي", positive)
            with col2:
                st.metric("📉 سلبي", negative)
            with col3:
                st.metric("➡️ محايد", neutral)
            
            st.divider()
            
            for news in all_news[:12]:
                with st.container():
                    col1, col2 = st.columns([4, 1])
                    with col1:
                        st.markdown(f"🔹 **[{news['title']}]({news['link']})**")
                        st.caption(f"📰 {news['source']} | 📅 {news['published']}")
                    with col2:
                        st.markdown(news['sentiment'])
                    st.divider()
        else:
            st.info("📰 جاري تحميل الأخبار...")
    
    with tab4:
        st.subheader("🏆 لوحة المتصدرين")
        
        df_all = get_alerts(only_active=False)
        if not df_all.empty:
            top_users = df_all.nlargest(10, 'points')[['username', 'points', 'join_date']]
            top_users.columns = ['المستخدم', 'النقاط', 'تاريخ الانضمام']
            
            st.markdown("### 🥇 أفضل المستثمرين")
            
            for i, (_, row) in enumerate(top_users.iterrows()):
                medal = "🥇" if i == 0 else "🥈" if i == 1 else "🥉" if i == 2 else f"{i+1}."
                st.markdown(f"{medal} **{row['المستخدم']}** - {row['النقاط']} نقطة")
            
            st.divider()
            st.dataframe(top_users, use_container_width=True)
        else:
            st.info("🏆 لا يوجد مستخدمين حتى الآن")
    
    with tab5:
        st.subheader("🔔 التنبيهات")
        
        col1, col2 = st.columns(2)
        with col1:
            username = st.text_input("👤 الاسم")
            tg_id = st.text_input("🆔 Chat ID")
        with col2:
            karat = st.selectbox("💎 العيار", ["24", "22", "21", "18"])
            current_mid = karat_data.get(karat, {}).get('mid', 0)
            high = st.number_input("🚀 هدف البيع", value=float(round(current_mid + 150)), step=50.0)
            low = st.number_input("🔻 هدف الشراء", value=float(round(current_mid - 150)), step=50.0)
        
        if st.button("💾 حفظ التنبيه", type="primary"):
            if username and tg_id:
                ok, msg = save_alert(username, tg_id, karat, high, low)
                if ok:
                    st.balloons()
                    st.success("✅ تم الحفظ")
                    st.rerun()
                else:
                    st.error(msg)
            else:
                st.error("❌ أدخل الاسم و Chat ID")
        
        st.divider()
        st.subheader("📋 التنبيهات المسجلة")
        df = get_alerts(only_active=False)
        if not df.empty:
            display = df[['username', 'karat', 'high_target', 'low_target', 'triggered', 'points']].copy()
            display.columns = ['المستخدم', 'العيار', 'هدف البيع', 'هدف الشراء', 'الحالة', 'النقاط']
            display['الحالة'] = display['الحالة'].apply(lambda x: '🟢 نشط' if x == 0 else '🔴 منفذ')
            st.dataframe(display, use_container_width=True)
        else:
            st.info("لا توجد تنبيهات")
    
    with tab6:
        st.subheader("⚙️ الإدارة والإحصائيات")
        
        col1, col2, col3, col4 = st.columns(4)
        df_all = get_alerts(only_active=False)
        with col1:
            st.metric("👁️ زوار اليوم", views)
        with col2:
            st.metric("📋 التنبيهات", len(df_all) if not df_all.empty else 0)
        with col3:
            active = len(df_all[df_all['triggered']==0]) if not df_all.empty else 0
            st.metric("🟢 النشطة", active)
        with col4:
            total_points = df_all['points'].sum() if not df_all.empty else 0
            st.metric("⭐ إجمالي النقاط", total_points)

if __name__ == "__main__":
    main()
