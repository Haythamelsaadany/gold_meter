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
from streamlit_autorefresh import st_autorefresh

# ==========================================
# إعدادات الصفحة
# ==========================================
st.set_page_config(
    page_title="🏅 Gold Meter Pro - تحديث لحظي",
    layout="wide",
    page_icon="🏅"
)

# ==========================================
# إعدادات ثابتة (داخلية)
# ==========================================
OUNCE_TO_GRAM = 31.1035
TAX_RATE = 0.0225  # 2.25% دمغة وضريبة (داخلية)
GOLD_HEDGE = -5.0  # خصم 5 دولار من سعر الذهب
REFRESH_INTERVAL = 5  # تحديث تلقائي كل 5 ثواني

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
        last_alerted_date TEXT
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS site_stats (
        id INTEGER PRIMARY KEY,
        views INTEGER
    )''')
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

def save_alert(username, tg_id, karat, high, low):
    conn = sqlite3.connect('gold_data.db')
    c = conn.cursor()
    try:
        c.execute("""
            INSERT INTO gold_alerts (username, tg_id, karat, high_target, low_target, triggered)
            VALUES (?, ?, ?, ?, ?, 0)
        """, (username, tg_id, karat, float(high), float(low)))
        conn.commit()
        return True, "✅ تم الحفظ"
    except Exception as e:
        return False, f"❌ خطأ: {e}"
    finally:
        conn.close()

def get_alerts(only_active=True):
    conn = sqlite3.connect('gold_data.db')
    query = "SELECT id, username, tg_id, karat, high_target, low_target, triggered, last_alerted_date FROM gold_alerts"
    if only_active:
        query += " WHERE triggered = 0"
    query += " ORDER BY id DESC"
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

# ==========================================
# 3. جلب الأسعار مع تحديث لحظي
# ==========================================
@st.cache_data(ttl=5)
def get_market_data():
    """جلب الأسعار من مصادر متعددة مع تحديث لحظي"""
    
    gold_prices = []
    
    # ===== سعر الذهب =====
    # Gold-API
    try:
        req = urllib.request.Request("https://api.gold-api.com/price/XAU", headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=3) as r:
            data = json.loads(r.read().decode('utf-8'))
            if data and 'price' in data:
                gold_prices.append(float(data['price']))
    except:
        pass
    
    # YFinance
    try:
        ticker = yf.Ticker("GC=F")
        gold_prices.append(float(ticker.fast_info['last_price']))
    except:
        pass
    
    # Kitco
    try:
        r = requests.get("https://www.kitco.com/price/precious-metals", timeout=3, headers={'User-Agent': 'Mozilla/5.0'})
        if r.status_code == 200:
            match = re.search(r'XAUUSD\s*=\s*([0-9.]+)', r.text)
            if match:
                gold_prices.append(float(match.group(1)))
    except:
        pass
    
    # حساب متوسط الذهب
    if len(gold_prices) >= 3:
        gold_prices_sorted = sorted(gold_prices)
        gold_oz = sum(gold_prices_sorted[1:-1]) / (len(gold_prices_sorted) - 2)
        gold_oz = round(gold_oz, 2)
    elif len(gold_prices) >= 2:
        gold_oz = round(sum(gold_prices) / len(gold_prices), 2)
    elif len(gold_prices) == 1:
        gold_oz = gold_prices[0]
    else:
        gold_oz = 2350.0
    
    # خصم 5 دولار من سعر الذهب
    gold_oz = round(gold_oz + GOLD_HEDGE, 2)
    
    # ===== سعر الدولار (تحديث لحظي من مصادر متعددة) =====
    usd_rates = []
    
    # المصدر 1: ExchangeRate-API
    try:
        r = requests.get("https://open.er-api.com/v6/latest/USD", timeout=3)
        if r.status_code == 200:
            rate = float(r.json()['rates']['EGP'])
            if 40 <= rate <= 70:
                usd_rates.append(rate)
    except:
        pass
    
    # المصدر 2: Frankfurter
    try:
        r = requests.get("https://api.frankfurter.app/latest?from=USD&to=EGP", timeout=3)
        if r.status_code == 200:
            data = r.json()
            if data and 'rates' in data and 'EGP' in data['rates']:
                rate = float(data['rates']['EGP'])
                if 40 <= rate <= 70:
                    usd_rates.append(rate)
    except:
        pass
    
    # المصدر 3: Yahoo Finance (السوق الفعلي)
    try:
        ticker = yf.Ticker("EGP=X")
        rate = float(ticker.fast_info['regularMarketPrice'])
        if 40 <= rate <= 70:
            usd_rates.append(rate)
    except:
        pass
    
    # المصدر 4: Investing.com (السوق الفعلي)
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9',
            'Accept-Language': 'en-US,en;q=0.5',
        }
        r = requests.get('https://www.investing.com/currencies/usd-egp', headers=headers, timeout=5)
        if r.status_code == 200:
            match = re.search(r'"last":\s*([0-9.]+)', r.text)
            if match:
                rate = float(match.group(1))
                if 40 <= rate <= 70:
                    usd_rates.append(rate)
    except:
        pass
    
    # حساب متوسط الدولار
    if len(usd_rates) >= 3:
        usd_rates_sorted = sorted(usd_rates)
        usd_egp = sum(usd_rates_sorted[1:-1]) / (len(usd_rates_sorted) - 2)
        usd_egp = round(usd_egp, 2)
    elif len(usd_rates) >= 2:
        usd_egp = round(sum(usd_rates) / len(usd_rates), 2)
    elif len(usd_rates) == 1:
        usd_egp = usd_rates[0]
    else:
        usd_egp = 49.50
    
    # إضافة تحوط بسيط جداً 0.05 فقط للتعديل
    usd_egp = round(usd_egp + 0.05, 2)
    
    # ===== حساب أسعار الجرامات مع 2.25% دمغة =====
    gram_24_base = (gold_oz * usd_egp) / OUNCE_TO_GRAM
    
    karat_data = {}
    for karat in [24, 22, 21, 18]:
        base_price = gram_24_base * (karat / 24)
        
        # إضافة 2.25% دمغة وضريبة (داخلية - غير معروضة)
        price_with_tax = base_price * (1 + TAX_RATE)
        
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
# 4. مؤشر الخوف والطمع
# ==========================================
def get_fear_greed_index(gold_oz, usd_egp, karat_data):
    score = 50
    
    # 1. تحليل سعر الذهب (30%)
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
    
    # 2. تحليل عيار 21 (25%)
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
    
    # 3. تحليل سعر الدولار (20%)
    if usd_egp > 50.5:
        score -= 10
    elif usd_egp > 49.5:
        score -= 5
    elif usd_egp > 48.5:
        score += 5
    else:
        score += 10
    
    # 4. تحليل التقلبات (15%)
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
    
    # 5. تحليل الاتجاه (10%)
    try:
        ticker = yf.Ticker("GC=F")
        hist = ticker.history(period="10d")
        if not hist.empty and len(hist) > 5:
            recent = hist['Close'].iloc[-5:].mean()
            older = hist['Close'].iloc[:5].mean()
            if recent > older * 1.01:
                score += 5
            elif recent < older * 0.99:
                score -= 5
    except:
        pass
    
    score = max(0, min(100, score))
    
    if score >= 80:
        level = "🟢 طمع شديد"
        description = "السوق في ذروة التفاؤل - كن حذراً"
        recommendation = "توقع تصحيح - نوصي بتقليل المراكز"
    elif score >= 60:
        level = "🟡 طمع"
        description = "السوق متفائل - توقع تصحيح"
        recommendation = "خفض نسبة الشراء تدريجياً"
    elif score >= 40:
        level = "🟠 محايد"
        description = "السوق متوازن - انتظر تأكيد"
        recommendation = "الاحتفاظ بالمراكز الحالية"
    elif score >= 20:
        level = "🔴 خوف"
        description = "السوق خائف - فرصة شراء"
        recommendation = "زيادة الوزن الشرائي تدريجياً"
    else:
        level = "🔴 خوف شديد"
        description = "السوق في ذروة الخوف - فرصة شراء ممتازة"
        recommendation = "شراء قوي - استغلال الهبوط"
    
    return score, level, description, recommendation

# ==========================================
# 5. توصيات بسيطة
# ==========================================
def get_recommendations(gold_oz, karat_data):
    recommendations = []
    score = 0
    
    if gold_oz > 2450:
        recommendations.append("🔴 الذهب في مقاومة قوية - تجنب الشراء")
        score -= 15
    elif gold_oz > 2400:
        recommendations.append("🟡 الذهب في منطقة مقاومة - انتظر")
        score -= 5
    elif gold_oz > 2350:
        recommendations.append("🟢 الذهب في منطقة محايدة - راقب")
        score += 5
    elif gold_oz > 2300:
        recommendations.append("🟢 الذهب في منطقة دعم - فرصة شراء")
        score += 10
    else:
        recommendations.append("🟢 الذهب في دعم قوي - شراء ممتاز")
        score += 15
    
    price_21 = karat_data.get('21', {}).get('mid', 0)
    if price_21 > 5900:
        recommendations.append("🔴 عيار 21 مرتفع - لا تشتري")
        score -= 10
    elif price_21 > 5800:
        recommendations.append("🟡 عيار 21 مرتفع نسبياً")
        score -= 5
    elif price_21 > 5700:
        recommendations.append("🟢 عيار 21 متوسط")
        score += 5
    elif price_21 > 5600:
        recommendations.append("🟢 عيار 21 جذاب - فرصة شراء")
        score += 10
    else:
        recommendations.append("🟢 عيار 21 جذاب جداً - شراء ممتاز")
        score += 15
    
    if score >= 20:
        recommendations.append("🌟 **توصية: شراء قوي**")
    elif score >= 10:
        recommendations.append("📈 **توصية: شراء**")
    elif score >= 0:
        recommendations.append("➡️ **توصية: احتفاظ**")
    else:
        recommendations.append("🔴 **توصية: بيع**")
    
    return recommendations, score

# ==========================================
# 6. الأخبار
# ==========================================
def fetch_news():
    all_news = []
    feeds = [
        ("https://news.google.com/rss/search?q=%D8%A7%D9%84%D8%B0%D9%87%D8%A8&hl=ar&gl=EG&ceid=EG:ar", "Google News"),
        ("https://feeds.feedburner.com/egyptgold", "مصر للذهب"),
        ("https://www.cnbcarabia.com/rss", "CNBC عربية"),
    ]
    
    for url, source in feeds:
        try:
            feed = feedparser.parse(url)
            if feed.entries:
                for entry in feed.entries[:3]:
                    all_news.append({
                        'title': entry.title,
                        'link': entry.link,
                        'source': source,
                        'published': entry.get('published', 'تاريخ غير معروف')
                    })
        except:
            continue
    
    return all_news[:10]

# ==========================================
# 7. الرسم البياني
# ==========================================
@st.cache_data(ttl=300)
def get_historical_data():
    try:
        ticker = yf.Ticker("GC=F")
        hist = ticker.history(period="1mo")
        if not hist.empty:
            return hist, False
    except:
        pass
    dates = [datetime.now() - timedelta(days=i) for i in range(30)][::-1]
    prices = [2350 + i*1.5 for i in range(30)]
    df = pd.DataFrame({"Close": prices}, index=dates)
    return df, True

# ==========================================
# 8. التنبيهات الخلفية
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
            alert_text = f"""🚀 *تنبيه صعود!*
👤 {username}
💎 عيار {karat}
💰 السعر: {current:,.2f} ج.م
🎯 هدف البيع: {high:,.0f} ج.م"""
            success, _ = send_telegram_message(tg_id, alert_text)
            if success:
                update_alert_triggered(alert_id)
                msgs.append(f"✅ تنبيه لـ {username}")
        elif current <= low and last_alerted != today:
            alert_text = f"""📉 *تنبيه هبوط!*
👤 {username}
💎 عيار {karat}
💰 السعر: {current:,.2f} ج.م
🎯 هدف الشراء: {low:,.0f} ج.م"""
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
# 9. الواجهة الرئيسية مع التحديث التلقائي
# ==========================================
def main():
    # ===== التحديث التلقائي =====
    # Refresh الصفحة كل 5 ثواني
    st_autorefresh(interval=REFRESH_INTERVAL * 1000, key="auto_refresh")
    
    init_db()
    start_background_checker()
    views = update_and_get_views()
    
    karat_data, gold_oz, usd_egp = get_market_data()
    
    # حساب مؤشر الخوف والطمع
    fear_score, fear_level, fear_desc, fear_rec = get_fear_greed_index(gold_oz, usd_egp, karat_data)
    
    # ===== الشريط الجانبي =====
    with st.sidebar:
        st.image("https://img.icons8.com/color/96/000000/gold-bars.png", width=80)
        st.title("🏅 Gold Meter Pro")
        
        st.markdown("### 📊 المؤشرات")
        st.metric("🌍 الذهب", f"${gold_oz:,.2f}")
        st.metric("💵 الدولار (لحظي)", f"{usd_egp:.2f} ج.م")
        
        st.divider()
        st.markdown("### 💎 الجرامات")
        for k in ['24', '22', '21', '18']:
            data = karat_data.get(k, {})
            st.metric(f"عيار {k}", f"{data.get('mid', 0):,.2f} ج.م")
        
        st.divider()
        st.markdown("### 📊 مؤشر الخوف والطمع")
        st.metric("المؤشر", f"{fear_score}/100", delta=fear_level)
        st.caption(fear_desc)
        st.caption(f"💡 {fear_rec}")
        
        st.divider()
        
        # ===== زر التحديث اليدوي =====
        if st.button("🔄 تحديث يدوي", type="primary", use_container_width=True):
            st.cache_data.clear()
            st.success("✅ تم تحديث الأسعار!")
            time.sleep(0.5)
            st.rerun()
        
        st.caption(f"👁️ زوار اليوم: {views}")
        st.caption(f"⏱️ تحديث تلقائي كل {REFRESH_INTERVAL} ثواني")
        st.caption("📊 4 مصادر للدولار")
    
    # ===== المحتوى الرئيسي =====
    st.title("🏅 Gold Meter - منصة الذهب")
    
    # عرض وقت آخر تحديث
    st.info(f"🔄 آخر تحديث: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} (تلقائي كل {REFRESH_INTERVAL} ثانية)")
    
    # بطاقات الأسعار
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.markdown(f"""
        <div style='background: linear-gradient(135deg, #1a1a2e, #16213e); padding: 20px; border-radius: 15px; text-align: center; border: 2px solid #FFD700;'>
            <h4 style='color: #FFD700;'>🌍 أونصة الذهب</h4>
            <h1 style='color: white;'>${gold_oz:,.2f}</h1>
            <small style='color: #00ff88;'>تحديث لحظي</small>
        </div>
        """, unsafe_allow_html=True)
    
    with col2:
        st.markdown(f"""
        <div style='background: linear-gradient(135deg, #1a1a2e, #16213e); padding: 20px; border-radius: 15px; text-align: center; border: 2px solid #00d4ff;'>
            <h4 style='color: #00d4ff;'>💵 الدولار</h4>
            <h1 style='color: white;'>{usd_egp:.2f} ج.م</h1>
            <small style='color: #ffd93d;'>4 مصادر</small>
        </div>
        """, unsafe_allow_html=True)
    
    with col3:
        price_21 = karat_data.get('21', {}).get('mid', 0)
        st.markdown(f"""
        <div style='background: linear-gradient(135deg, #1a1a2e, #16213e); padding: 20px; border-radius: 15px; text-align: center; border: 2px solid #ff6b6b;'>
            <h4 style='color: #ff6b6b;'>🏅 عيار 21</h4>
            <h1 style='color: white;'>{price_21:,.2f} ج.م</h1>
            <small style='color: #888;'>شامل الدمغة</small>
        </div>
        """, unsafe_allow_html=True)
    
    with col4:
        color = "#00ff88" if fear_score >= 60 else "#ffd93d" if fear_score >= 40 else "#ff6b6b"
        st.markdown(f"""
        <div style='background: linear-gradient(135deg, #1a1a2e, #16213e); padding: 20px; border-radius: 15px; text-align: center; border: 2px solid {color};'>
            <h4 style='color: {color};'>📊 مؤشر الخوف</h4>
            <h1 style='color: white;'>{fear_score}</h1>
            <small style='color: #888;'>{fear_level}</small>
        </div>
        """, unsafe_allow_html=True)
    
    st.divider()
    
    # مؤشر الخوف والطمع الموسع
    st.markdown("### 📊 تحليل مؤشر الخوف والطمع")
    col1, col2 = st.columns([1, 2])
    with col1:
        st.metric("القيمة", f"{fear_score}/100", delta=fear_level)
    with col2:
        st.info(f"**{fear_desc}**")
        st.success(f"💡 {fear_rec}")
    
    st.divider()
    
    # ===== أسعار الشراء والبيع =====
    st.markdown("### 💰 أسعار الشراء والبيع")
    cols = st.columns(4)
    for i, k in enumerate(['24', '22', '21', '18']):
        data = karat_data.get(k, {})
        with cols[i]:
            st.markdown(f"""
            <div style='background: linear-gradient(135deg, #1a1a2e, #16213e); padding: 15px; border-radius: 12px; text-align: center; border: 1px solid #333;'>
                <h3 style='color: #ffd93d;'>عيار {k}</h3>
                <div style='display: flex; justify-content: space-around;'>
                    <div>
                        <small style='color: #aaa;'>شراء</small>
                        <h4 style='color: #00ff88;'>{data.get('buy', 0):,.2f}</h4>
                    </div>
                    <div>
                        <small style='color: #aaa;'>بيع</small>
                        <h4 style='color: #ff6b6b;'>{data.get('sell', 0):,.2f}</h4>
                    </div>
                </div>
                <small style='color: #888;'>الفرق: {round(data.get('sell', 0) - data.get('buy', 0), 2):.2f} ج.م</small>
            </div>
            """, unsafe_allow_html=True)
    
    st.divider()
    
    # ===== التبويبات =====
    tab1, tab2, tab3, tab4 = st.tabs(["📊 التحليل", "💡 التوصيات", "📰 الأخبار", "🔔 التنبيهات"])
    
    with tab1:
        st.subheader("📈 أداء الذهب - آخر 30 يوم")
        hist_data, _ = get_historical_data()
        st.line_chart(hist_data['Close'])
        
        # إحصائيات
        if not hist_data.empty:
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("📈 أعلى سعر", f"${hist_data['Close'].max():.2f}")
            with col2:
                st.metric("📉 أدنى سعر", f"${hist_data['Close'].min():.2f}")
            with col3:
                change = ((hist_data['Close'].iloc[-1] - hist_data['Close'].iloc[-2]) / hist_data['Close'].iloc[-2]) * 100 if len(hist_data) > 1 else 0
                st.metric("📊 التغير اليومي", f"{change:+.2f}%")
    
    with tab2:
        st.subheader("💡 التوصيات الذكية")
        recs, score = get_recommendations(gold_oz, karat_data)
        for rec in recs:
            if "🔴" in rec:
                st.warning(rec)
            elif "🟢" in rec or "🌟" in rec:
                st.success(rec)
            else:
                st.info(rec)
        
        st.divider()
        st.markdown("### 🎯 استراتيجية التداول")
        col1, col2, col3 = st.columns(3)
        with col1:
            st.markdown(f"""
            **🛡️ مناطق الدعم**
            - دعم أول: ${gold_oz - 50:.0f}
            - دعم ثاني: ${gold_oz - 100:.0f}
            """)
        with col2:
            st.markdown(f"""
            **🚀 مناطق المقاومة**
            - مقاومة أولى: ${gold_oz + 50:.0f}
            - مقاومة ثانية: ${gold_oz + 100:.0f}
            """)
        with col3:
            st.markdown("""
            **⚖️ نسب التخصيص**
            - شراء: 30-40%
            - احتفاظ: 40-50%
            - بيع: 10-20%
            """)
    
    with tab3:
        st.subheader("📰 آخر أخبار الذهب والدولار")
        news = fetch_news()
        if news:
            for item in news:
                st.markdown(f"🔹 **[{item['title']}]({item['link']})**")
                st.caption(f"📰 {item['source']} | 📅 {item['published']}")
                st.divider()
        else:
            st.info("📰 جاري تحميل الأخبار...")
    
    with tab4:
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
            display = df[['username', 'karat', 'high_target', 'low_target', 'triggered']].copy()
            display.columns = ['المستخدم', 'العيار', 'هدف البيع', 'هدف الشراء', 'الحالة']
            display['الحالة'] = display['الحالة'].apply(lambda x: '🟢 نشط' if x == 0 else '🔴 منفذ')
            st.dataframe(display, use_container_width=True)
        else:
            st.info("لا توجد تنبيهات")

if __name__ == "__main__":
    main()
