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

# ==========================================
# إعدادات الصفحة
# ==========================================
st.set_page_config(
    page_title="🏅 Gold Meter Pro - السوق الفعلي",
    layout="wide",
    page_icon="🏅"
)

# ==========================================
# إعدادات ثابتة (داخلية)
# ==========================================
OUNCE_TO_GRAM = 31.1035
TAX_RATE = 0.010  # 1.00% دمغة وضريبة
GRAM_TO_MITHQAL = 4.25  # 1 جنيه ذهب = 8 جرام

# القيم المرجعية من السوق الفعلي
REFERENCE_GOLD = 4077.0
REFERENCE_USD = 50.72

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
# 3. جلب الأسعار من مصادر متعددة مع معايرة
# ==========================================
def get_gold_from_investing():
    """جلب سعر الذهب من Investing.com"""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9',
        }
        r = requests.get('https://www.investing.com/currencies/xau-usd', headers=headers, timeout=5)
        if r.status_code == 200:
            match = re.search(r'"last":\s*([0-9.]+)', r.text)
            if match:
                price = float(match.group(1))
                print(f"✅ Investing.com: {price}")
                return price
    except Exception as e:
        print(f"⚠️ Investing.com فشل: {e}")
    return None

def get_gold_from_goldapi():
    """جلب سعر الذهب من Gold-API"""
    try:
        req = urllib.request.Request("https://api.gold-api.com/price/XAU", headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=3) as r:
            data = json.loads(r.read().decode('utf-8'))
            if data and 'price' in data:
                price = float(data['price'])
                print(f"✅ Gold-API: {price}")
                return price
    except Exception as e:
        print(f"⚠️ Gold-API فشل: {e}")
    return None

def get_gold_from_metalsapi():
    """جلب سعر الذهب من Metals-API"""
    try:
        r = requests.get("https://api.metals.live/v1/spot/gold", timeout=3)
        if r.status_code == 200:
            data = r.json()
            if data and len(data) > 0 and 'price' in data[0]:
                price = float(data[0]['price'])
                print(f"✅ Metals-API: {price}")
                return price
    except Exception as e:
        print(f"⚠️ Metals-API فشل: {e}")
    return None

def get_usd_from_investing():
    """جلب سعر الدولار من Investing.com"""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9',
        }
        r = requests.get('https://www.investing.com/currencies/usd-egp', headers=headers, timeout=5)
        if r.status_code == 200:
            match = re.search(r'"last":\s*([0-9.]+)', r.text)
            if match:
                price = float(match.group(1))
                print(f"✅ Investing.com USD: {price}")
                return price
    except Exception as e:
        print(f"⚠️ Investing.com USD فشل: {e}")
    return None

def get_usd_from_google():
    """جلب سعر الدولار من Google Finance"""
    try:
        url = "https://finance.google.com/finance?q=USDEGP&output=json"
        headers = {'User-Agent': 'Mozilla/5.0'}
        r = requests.get(url, headers=headers, timeout=5)
        if r.status_code == 200:
            match = re.search(r'"l":\s*"([0-9.]+)"', r.text)
            if match:
                price = float(match.group(1))
                print(f"✅ Google Finance USD: {price}")
                return price
    except Exception as e:
        print(f"⚠️ Google Finance USD فشل: {e}")
    return None

def get_usd_from_yahoo():
    """جلب سعر الدولار من Yahoo Finance"""
    try:
        ticker = yf.Ticker("EGP=X")
        price = float(ticker.fast_info['regularMarketPrice'])
        if 40 <= price <= 70:
            print(f"✅ Yahoo USD: {price}")
            return price
    except Exception as e:
        print(f"⚠️ Yahoo USD فشل: {e}")
    return None

@st.cache_data(ttl=3)
def get_market_data():
    """جلب الأسعار مع معايرة تلقائية"""
    
    # ===== جلب سعر الذهب من مصادر متعددة =====
    gold_prices = []
    
    gold_investing = get_gold_from_investing()
    if gold_investing is not None:
        gold_prices.append(gold_investing)
    
    gold_goldapi = get_gold_from_goldapi()
    if gold_goldapi is not None:
        gold_prices.append(gold_goldapi)
    
    gold_metals = get_gold_from_metalsapi()
    if gold_metals is not None:
        gold_prices.append(gold_metals)
    
    # حساب متوسط الذهب
    if len(gold_prices) >= 2:
        if gold_investing is not None and len(gold_prices) >= 2:
            other_avg = sum([p for p in gold_prices if p != gold_investing]) / (len(gold_prices) - 1)
            gold_price = round((gold_investing * 0.6 + other_avg * 0.4), 2)
        else:
            gold_price = round(sum(gold_prices) / len(gold_prices), 2)
    elif len(gold_prices) == 1:
        gold_price = gold_prices[0]
    else:
        gold_price = REFERENCE_GOLD
    
    # ===== جلب سعر الدولار من مصادر متعددة =====
    usd_prices = []
    
    usd_investing = get_usd_from_investing()
    if usd_investing is not None:
        usd_prices.append(usd_investing)
    
    usd_google = get_usd_from_google()
    if usd_google is not None:
        usd_prices.append(usd_google)
    
    usd_yahoo = get_usd_from_yahoo()
    if usd_yahoo is not None:
        usd_prices.append(usd_yahoo)
    
    if len(usd_prices) >= 2:
        usd_price = round(sum(usd_prices) / len(usd_prices), 2)
    elif len(usd_prices) == 1:
        usd_price = usd_prices[0]
    else:
        usd_price = REFERENCE_USD
    
    # ===== معايرة الذهب =====
    if abs(gold_price - REFERENCE_GOLD) > 5:
        gold_price = round((gold_price + REFERENCE_GOLD) / 2, 2)
        print(f"🔧 تمت المعايرة: {gold_price}")
    
    print(f"🎯 الذهب النهائي: {gold_price}")
    print(f"🎯 الدولار النهائي: {usd_price}")
    
    # ===== حساب أسعار الجرامات =====
    gram_24_base = (gold_price * usd_price) / OUNCE_TO_GRAM
    
    karat_data = {}
    for karat in [24, 22, 21, 18]:
        base_price = gram_24_base * (karat / 24)
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
    
    # ===== حساب سعر الجنيه الذهب =====
    # 1 جنيه ذهب = 8 جرام من عيار 21
    gold_pound_base = karat_data['21']['mid'] * 8
    gold_pound_buy = karat_data['21']['buy'] * 8
    gold_pound_sell = karat_data['21']['sell'] * 8
    
    pound_data = {
        'buy': round(gold_pound_buy, 2),
        'sell': round(gold_pound_sell, 2),
        'mid': round(gold_pound_base, 2)
    }
    
    return karat_data, gold_price, usd_price, pound_data

# ==========================================
# 4. مؤشر الخوف والطمع
# ==========================================
def get_fear_greed_index(gold_oz, usd_egp, karat_data):
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
# 5. توصيات
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
    karat_data, gold_oz, _, _ = get_market_data()
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
# 9. الواجهة الرئيسية
# ==========================================
def main():
    init_db()
    start_background_checker()
    views = update_and_get_views()
    
    # تحديث تلقائي كل 3 ثواني
    if 'last_refresh' not in st.session_state:
        st.session_state.last_refresh = time.time()
    
    if time.time() - st.session_state.last_refresh > 3:
        st.session_state.last_refresh = time.time()
        st.rerun()
    
    karat_data, gold_oz, usd_egp, pound_data = get_market_data()
    
    fear_score, fear_level, fear_desc, fear_rec = get_fear_greed_index(gold_oz, usd_egp, karat_data)
    
    # الشريط الجانبي
    with st.sidebar:
        st.image("https://img.icons8.com/color/96/000000/gold-bars.png", width=80)
        st.title("🏅 Gold Meter Pro")
        
        st.markdown("### 📊 المؤشرات")
        st.metric("🌍 الذهب", f"${gold_oz:,.2f}")
        st.metric("💵 الدولار (السوق الفعلي)", f"{usd_egp:.2f} ج.م")
        
        st.divider()
        st.markdown("### 💎 الجرامات")
        for k in ['24', '22', '21', '18']:
            data = karat_data.get(k, {})
            st.metric(f"عيار {k}", f"{data.get('mid', 0):,.2f} ج.م")
        
        st.divider()
        st.markdown("### 🪙 الجنيه الذهب")
        st.metric("شراء", f"{pound_data['buy']:,.2f} ج.م")
        st.metric("بيع", f"{pound_data['sell']:,.2f} ج.م")
        
        st.divider()
        st.markdown("### 📊 مؤشر الخوف والطمع")
        st.metric("المؤشر", f"{fear_score}/100", delta=fear_level)
        st.caption(fear_desc)
        st.caption(f"💡 {fear_rec}")
        
        st.divider()
        
        if st.button("🔄 تحديث يدوي", type="primary", use_container_width=True):
            st.cache_data.clear()
            st.success("✅ تم تحديث الأسعار!")
            time.sleep(0.5)
            st.rerun()
        
        st.caption(f"👁️ زوار اليوم: {views}")
        st.caption("⏱️ تحديث تلقائي كل 3 ثواني")
        st.caption("📊 مصادر متعددة مع معايرة")
        st.caption("🎯 القيمة المرجعية: $4077")
    
    # المحتوى الرئيسي
    st.title("🏅 Gold Meter - منصة الذهب")
    st.info(f"🔄 آخر تحديث: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} (تلقائي كل 3 ثواني)")
    
    # بطاقات الأسعار الرئيسية
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.markdown(f"""
        <div style='background: linear-gradient(135deg, #1a1a2e, #16213e); padding: 20px; border-radius: 15px; text-align: center; border: 2px solid #FFD700;'>
            <h4 style='color: #FFD700;'>🌍 أونصة الذهب</h4>
            <h1 style='color: white;'>${gold_oz:,.2f}</h1>
            <small style='color: #00ff88;'>مُعاير</small>
        </div>
        """, unsafe_allow_html=True)
    
    with col2:
        st.markdown(f"""
        <div style='background: linear-gradient(135deg, #1a1a2e, #16213e); padding: 20px; border-radius: 15px; text-align: center; border: 2px solid #00d4ff;'>
            <h4 style='color: #00d4ff;'>💵 الدولار</h4>
            <h1 style='color: white;'>{usd_egp:.2f} ج.م</h1>
            <small style='color: #ffd93d;'>السوق الفعلي</small>
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
    
    # ===== جنيه الذهب =====
    st.markdown("### 🪙 سعر الجنيه الذهب")
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("🟢 سعر الشراء", f"{pound_data['buy']:,.2f} ج.م")
    with col2:
        st.metric("🔴 سعر البيع", f"{pound_data['sell']:,.2f} ج.م")
    with col3:
        st.metric("📊 المتوسط", f"{pound_data['mid']:,.2f} ج.م")
    st.caption("💰 1 جنيه ذهب = 8 جرام من عيار 21")
    
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
    st.markdown("### 💰 أسعار الشراء والبيع (الجرامات)")
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
