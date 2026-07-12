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
# 3. جلب الأسعار (محسن جداً)
# ==========================================
def get_market_data(usd_hedge=0.50):
    """
    جلب الأسعار من 5 مصادر للذهب و 6 مصادر للدولار مع تحوط قابل للتعديل
    """
    
    # ===== سعر الذهب من 5 مصادر =====
    gold_prices = []
    
    # المصدر 1: Gold-API
    try:
        req = urllib.request.Request("https://api.gold-api.com/price/XAU", headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=3) as r:
            data = json.loads(r.read().decode('utf-8'))
            if data and 'price' in data:
                gold_prices.append(float(data['price']))
    except:
        pass
    
    # المصدر 2: YFinance
    try:
        ticker = yf.Ticker("GC=F")
        gold_prices.append(float(ticker.fast_info['last_price']))
    except:
        pass
    
    # المصدر 3: Kitco
    try:
        r = requests.get("https://www.kitco.com/price/precious-metals", timeout=3, headers={'User-Agent': 'Mozilla/5.0'})
        if r.status_code == 200:
            match = re.search(r'XAUUSD\s*=\s*([0-9.]+)', r.text)
            if match:
                gold_prices.append(float(match.group(1)))
    except:
        pass
    
    # المصدر 4: Metals-API
    try:
        r = requests.get("https://api.metals.live/v1/spot/gold", timeout=3)
        if r.status_code == 200:
            data = r.json()
            if data and len(data) > 0 and 'price' in data[0]:
                gold_prices.append(float(data[0]['price']))
    except:
        pass
    
    # المصدر 5: Investing.com (عن طريق HTML)
    try:
        r = requests.get("https://www.investing.com/currencies/xau-usd", timeout=3, headers={'User-Agent': 'Mozilla/5.0'})
        if r.status_code == 200:
            # بحث عن السعر في الصفحة
            match = re.search(r'data-test="instrument-price-last"\s*data-value="([0-9.]+)"', r.text)
            if match:
                gold_prices.append(float(match.group(1)))
    except:
        pass
    
    # حساب متوسط الذهب (ذكي)
    if len(gold_prices) >= 4:
        gold_prices_sorted = sorted(gold_prices)
        # حذف أعلى وأقل قيمتين
        gold_oz = sum(gold_prices_sorted[2:-2]) / (len(gold_prices_sorted) - 4)
        gold_oz = round(gold_oz, 2)
    elif len(gold_prices) >= 3:
        gold_prices_sorted = sorted(gold_prices)
        gold_oz = sum(gold_prices_sorted[1:-1]) / (len(gold_prices_sorted) - 2)
        gold_oz = round(gold_oz, 2)
    elif len(gold_prices) >= 2:
        gold_oz = round(sum(gold_prices) / len(gold_prices), 2)
    elif len(gold_prices) == 1:
        gold_oz = gold_prices[0]
    else:
        gold_oz = 2350.0
    
    # ===== سعر الدولار من 6 مصادر =====
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
    
    # المصدر 3: Yahoo Finance
    try:
        ticker = yf.Ticker("EGP=X")
        rate = float(ticker.fast_info['regularMarketPrice'])
        if 40 <= rate <= 70:
            usd_rates.append(rate)
    except:
        pass
    
    # المصدر 4: CurrencyAPI
    try:
        r = requests.get("https://api.currencyapi.com/v3/latest?apikey=cur_live_8d8e3dXK9BwA5sYp4Z&base_currency=USD&currencies=EGP", timeout=3)
        if r.status_code == 200:
            data = r.json()
            if data and 'data' in data and 'EGP' in data['data']:
                rate = float(data['data']['EGP']['value'])
                if 40 <= rate <= 70:
                    usd_rates.append(rate)
    except:
        pass
    
    # المصدر 5: Fixer.io
    try:
        r = requests.get("https://data.fixer.io/api/latest?access_key=8d8e3dXK9BwA5sYp4Z&base=USD&symbols=EGP", timeout=3)
        if r.status_code == 200:
            data = r.json()
            if data and data.get('success') and 'rates' in data and 'EGP' in data['rates']:
                rate = float(data['rates']['EGP'])
                if 40 <= rate <= 70:
                    usd_rates.append(rate)
    except:
        pass
    
    # المصدر 6: البنك المركزي المصري (API غير رسمي)
    try:
        r = requests.get("https://www.cbe.org.eg/api/v1/exchange-rates/usd", timeout=3)
        if r.status_code == 200:
            data = r.json()
            if data and 'rate' in data:
                rate = float(data['rate'])
                if 40 <= rate <= 70:
                    usd_rates.append(rate)
    except:
        pass
    
    # حساب متوسط الدولار (ذكي)
    if len(usd_rates) >= 4:
        usd_rates_sorted = sorted(usd_rates)
        usd_egp = sum(usd_rates_sorted[2:-2]) / (len(usd_rates_sorted) - 4)
        usd_egp = round(usd_egp, 2)
    elif len(usd_rates) >= 3:
        usd_rates_sorted = sorted(usd_rates)
        usd_egp = sum(usd_rates_sorted[1:-1]) / (len(usd_rates_sorted) - 2)
        usd_egp = round(usd_egp, 2)
    elif len(usd_rates) >= 2:
        usd_egp = round(sum(usd_rates) / len(usd_rates), 2)
    elif len(usd_rates) == 1:
        usd_egp = usd_rates[0]
    else:
        usd_egp = 49.50
    
    # ✅ إضافة تحوط ديناميكي
    usd_egp = round(usd_egp + usd_hedge, 2)
    
    # ===== حساب أسعار الجرامات =====
    gram_24_base = (gold_oz * usd_egp) / OUNCE_TO_GRAM
    
    karat_data = {}
    for karat in [24, 22, 21, 18]:
        base_price = gram_24_base * (karat / 24)
        
        # نسب سبريد مختلفة حسب العيار (محسنة)
        spread_rates = {24: 0.0085, 22: 0.0090, 21: 0.0085, 18: 0.0080}
        spread = spread_rates.get(karat, 0.0085)
        
        buy_price = base_price * (1 - spread/2)
        sell_price = base_price * (1 + spread/2)
        
        karat_data[str(karat)] = {
            'buy': round(buy_price, 2),
            'sell': round(sell_price, 2),
            'mid': round(base_price, 2)
        }
    
    return karat_data, gold_oz, usd_egp

# ==========================================
# 4. التحليل الفني المتقدم (محسن جداً)
# ==========================================
def get_advanced_analysis(gold_oz, usd_egp, karat_data):
    """تحليل فني متكامل مع توصيات قوية ومتنوعة"""
    
    recommendations = []
    score = 0
    details = {}
    signals = []
    
    # ===== 1. تحليل سعر الذهب العالمي =====
    if gold_oz > 2450:
        recommendations.append("🔴 **الذهب في منطقة مقاومة قوية جداً** (أعلى من 2450$)")
        recommendations.append("📉 احتمال تصحيح هابط - نوصي بتقليل المراكز الشرائية")
        score -= 15
        details['gold'] = 'مقاومة قوية'
        signals.append('بيع')
    elif gold_oz > 2400:
        recommendations.append("🟡 **الذهب في منطقة مقاومة** (2400-2450$)")
        recommendations.append("➡️ نوصي بالانتظار حتى اختراق 2450$ أو كسر 2380$")
        score -= 5
        details['gold'] = 'مقاومة'
        signals.append('انتظار')
    elif gold_oz > 2350:
        recommendations.append("🟢 **الذهب في منطقة محايدة** (2350-2400$)")
        recommendations.append("➡️ السوق في حالة ترقب - نوصي بالمراقبة")
        score += 5
        details['gold'] = 'محايد'
        signals.append('مراقبة')
    elif gold_oz > 2300:
        recommendations.append("🟢 **الذهب في منطقة دعم** (2300-2350$)")
        recommendations.append("📈 فرصة شراء جيدة - نوصي بالدخول التدريجي")
        score += 10
        details['gold'] = 'دعم'
        signals.append('شراء')
    else:
        recommendations.append("🟢 **الذهب في منطقة دعم قوية جداً** (أقل من 2300$)")
        recommendations.append("📈 فرصة شراء ممتازة - نوصي بزيادة المراكز الشرائية")
        score += 15
        details['gold'] = 'دعم قوي'
        signals.append('شراء قوي')
    
    # ===== 2. تحليل سعر الدولار =====
    if usd_egp > 50.5:
        recommendations.append("🔴 **ارتفاع الدولار يضغط بقوة على الذهب محلياً**")
        recommendations.append("📉 ارتفاع الدولار يزيد من تكلفة الذهب - نوصي بالحذر")
        score -= 10
        details['usd'] = 'مرتفع'
    elif usd_egp > 49.5:
        recommendations.append("🟡 **الدولار في مستويات مرتفعة نسبياً**")
        recommendations.append("➡️ تأثير سلبي محدود على الذهب")
        score -= 3
        details['usd'] = 'مرتفع نسبياً'
    elif usd_egp > 48.5:
        recommendations.append("🟢 **الدولار في مستويات متوسطة**")
        recommendations.append("✅ تأثير محايد على أسعار الذهب")
        score += 5
        details['usd'] = 'متوسط'
    else:
        recommendations.append("🟢 **انخفاض الدولار يدعم الذهب محلياً**")
        recommendations.append("📈 بيئة مواتية لارتفاع الذهب")
        score += 10
        details['usd'] = 'منخفض'
    
    # ===== 3. تحليل عيار 21 =====
    price_21 = karat_data.get('21', {}).get('mid', 0)
    
    if price_21 > 5900:
        recommendations.append("🔴 **عيار 21 في مستويات مرتفعة جداً** (أعلى من 5900)")
        recommendations.append("📉 نوصي بعدم الشراء عند هذه المستويات")
        score -= 10
        details['karat21'] = 'مرتفع جداً'
    elif price_21 > 5800:
        recommendations.append("🟡 **عيار 21 في مستويات مرتفعة** (5800-5900)")
        recommendations.append("➡️ نوصي بالانتظار للانخفاض")
        score -= 5
        details['karat21'] = 'مرتفع'
    elif price_21 > 5700:
        recommendations.append("🟢 **عيار 21 في مستويات متوسطة** (5700-5800)")
        recommendations.append("➡️ منطقة مقبولة للتداول")
        score += 5
        details['karat21'] = 'متوسط'
    elif price_21 > 5600:
        recommendations.append("🟢 **عيار 21 في مستويات جذابة** (5600-5700)")
        recommendations.append("📈 فرصة شراء جيدة")
        score += 10
        details['karat21'] = 'جذاب'
    else:
        recommendations.append("🟢 **عيار 21 في مستويات جذابة جداً** (أقل من 5600)")
        recommendations.append("📈 فرصة شراء ممتازة")
        score += 15
        details['karat21'] = 'جذاب جداً'
    
    # ===== 4. التحليل الفني المتقدم (RSI, MACD, المتوسطات) =====
    try:
        ticker = yf.Ticker("GC=F")
        hist = ticker.history(period="2mo")
        if not hist.empty and len(hist) > 20:
            close_prices = hist['Close']
            
            # RSI (14 يوم)
            delta = close_prices.diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rs = gain / loss
            rsi = 100 - (100 / (1 + rs))
            current_rsi = rsi.iloc[-1] if not rsi.empty else 50
            
            # المتوسطات المتحركة
            ma7 = close_prices.rolling(window=7).mean().iloc[-1] if len(close_prices) >= 7 else close_prices.iloc[-1]
            ma20 = close_prices.rolling(window=20).mean().iloc[-1] if len(close_prices) >= 20 else close_prices.iloc[-1]
            ma50 = close_prices.rolling(window=50).mean().iloc[-1] if len(close_prices) >= 50 else close_prices.iloc[-1]
            current_price = close_prices.iloc[-1]
            
            # تحليل RSI
            if current_rsi > 70:
                recommendations.append(f"🔴 **مؤشر RSI في منطقة تشبع شرائي** ({current_rsi:.1f} > 70)")
                recommendations.append("📉 يشير إلى احتمالية تصحيح هابط")
                score -= 10
                details['rsi'] = f"{current_rsi:.1f} (تشبع شرائي)"
            elif current_rsi > 60:
                recommendations.append(f"🟡 **مؤشر RSI في منطقة قوية** ({current_rsi:.1f})")
                score -= 3
                details['rsi'] = f"{current_rsi:.1f} (قوي)"
            elif current_rsi > 40:
                recommendations.append(f"🟢 **مؤشر RSI في منطقة محايدة** ({current_rsi:.1f})")
                score += 5
                details['rsi'] = f"{current_rsi:.1f} (محايد)"
            else:
                recommendations.append(f"🟢 **مؤشر RSI في منطقة تشبع بيعي** ({current_rsi:.1f} < 40)")
                recommendations.append("📈 يشير إلى احتمالية ارتفاع")
                score += 10
                details['rsi'] = f"{current_rsi:.1f} (تشبع بيعي)"
            
            # تحليل المتوسطات المتحركة
            if current_price > ma7 > ma20 > ma50:
                recommendations.append("🟢 **اتجاه صاعد قوي جداً** (السعر > MA7 > MA20 > MA50)")
                score += 10
                details['ma'] = "صاعد قوي جداً"
            elif current_price > ma7 > ma20:
                recommendations.append("🟢 **اتجاه صاعد** (السعر > MA7 > MA20)")
                score += 5
                details['ma'] = "صاعد"
            elif current_price < ma7 < ma20 < ma50:
                recommendations.append("🔴 **اتجاه هابط قوي جداً** (السعر < MA7 < MA20 < MA50)")
                score -= 10
                details['ma'] = "هابط قوي جداً"
            elif current_price < ma7 < ma20:
                recommendations.append("🔴 **اتجاه هابط** (السعر < MA7 < MA20)")
                score -= 5
                details['ma'] = "هابط"
            else:
                recommendations.append("🟡 **اتجاه عرضي** (المتوسطات متقاربة)")
                details['ma'] = "عرضي"
            
            # MACD (تحليل مبسط)
            exp1 = close_prices.ewm(span=12, adjust=False).mean()
            exp2 = close_prices.ewm(span=26, adjust=False).mean()
            macd = exp1 - exp2
            signal = macd.ewm(span=9, adjust=False).mean()
            
            if macd.iloc[-1] > signal.iloc[-1] and macd.iloc[-1] > 0:
                recommendations.append("🟢 **مؤشر MACD إيجابي** (في منطقة صاعدة)")
                score += 5
                details['macd'] = "إيجابي (صاعد)"
            elif macd.iloc[-1] < signal.iloc[-1] and macd.iloc[-1] < 0:
                recommendations.append("🔴 **مؤشر MACD سلبي** (في منطقة هابطة)")
                score -= 5
                details['macd'] = "سلبي (هابط)"
            else:
                recommendations.append("🟡 **مؤشر MACD محايد** (في منطقة تقاطع)")
                details['macd'] = "محايد"
    except:
        pass
    
    # ===== 5. التوصية النهائية =====
    if score >= 30:
        recommendations.append("🌟 **توصية قوية جداً بالشراء**")
        recommendations.append("📈 فرصة استثمارية ممتازة - زيادة الوزن الشرائي")
        details['final'] = 'شراء قوي جداً'
    elif score >= 20:
        recommendations.append("📈 **توصية قوية بالشراء**")
        recommendations.append("✅ فرصة جيدة للدخول التدريجي")
        details['final'] = 'شراء قوي'
    elif score >= 10:
        recommendations.append("📈 **توصية بالشراء**")
        recommendations.append("➡️ فرصة مناسبة للدخول بحذر")
        details['final'] = 'شراء'
    elif score >= 0:
        recommendations.append("➡️ **توصية بالاحتفاظ**")
        recommendations.append("📊 السوق في منطقة محايدة - انتظر تأكيد الاتجاه")
        details['final'] = 'احتفاظ'
    elif score >= -10:
        recommendations.append("🟡 **توصية بالحذر**")
        recommendations.append("⚠️ السوق متذبذب - نوصي بتقليل المراكز")
        details['final'] = 'حذر'
    else:
        recommendations.append("🔴 **توصية بالبيع**")
        recommendations.append("📉 السوق في منطقة مقاومة - نوصي بتسييل جزء من المحفظة")
        details['final'] = 'بيع'
    
    # ===== 6. نقاط الدعم والمقاومة =====
    recommendations.append("")
    recommendations.append("🎯 **نقاط الدعم والمقاومة الفنية:**")
    recommendations.append(f"   • دعم قوي: ${gold_oz - 100:.0f}")
    recommendations.append(f"   • دعم متوسط: ${gold_oz - 50:.0f}")
    recommendations.append(f"   • المستوى الحالي: ${gold_oz:.0f}")
    recommendations.append(f"   • مقاومة متوسطة: ${gold_oz + 50:.0f}")
    recommendations.append(f"   • مقاومة قوية: ${gold_oz + 100:.0f}")
    
    # ===== 7. نسبة المخاطرة/العائد =====
    if score >= 20:
        risk_reward = "1:3"
    elif score >= 10:
        risk_reward = "1:2"
    elif score >= 0:
        risk_reward = "1:1"
    else:
        risk_reward = "2:1"
    recommendations.append(f"⚖️ **نسبة المخاطرة/العائد المقترحة:** {risk_reward}")
    
    return recommendations, score, details

# ==========================================
# 5. الأخبار (محسنة)
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
                    # تصنيف الخبر حسب الكلمات المفتاحية
                    title_lower = entry.title.lower()
                    if any(word in title_lower for word in ['صعود', 'ارتفاع', 'زيادة', 'قفزة']):
                        sentiment = "📈 صعود"
                    elif any(word in title_lower for word in ['هبوط', 'انخفاض', 'تراجع', 'كسر']):
                        sentiment = "📉 هبوط"
                    else:
                        sentiment = "➡️ محايد"
                    
                    all_news.append({
                        'title': entry.title,
                        'link': entry.link,
                        'source': source,
                        'published': entry.get('published', 'تاريخ غير معروف'),
                        'sentiment': sentiment
                    })
        except:
            continue
    
    # ترتيب حسب الأحدث
    return all_news[:15]

# ==========================================
# 6. الرسم البياني المتقدم
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
# 7. التنبيهات الخلفية
# ==========================================
def check_and_send_alerts():
    usd_hedge = st.session_state.get('usd_hedge', 0.50)
    karat_data, gold_oz, _ = get_market_data(usd_hedge)
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
            alert_text = f"""🚀 *تنبيه صعود الذهب!*

👤 المستخدم: {username}
💎 العيار: {karat}
💰 السعر الحالي: {current:,.2f} ج.م
🎯 هدف البيع: {high:,.0f} ج.م

📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"""
            success, _ = send_telegram_message(tg_id, alert_text)
            if success:
                update_alert_triggered(alert_id)
                msgs.append(f"✅ تنبيه لـ {username}")
        elif current <= low and last_alerted != today:
            alert_text = f"""📉 *تنبيه هبوط الذهب!*

👤 المستخدم: {username}
💎 العيار: {karat}
💰 السعر الحالي: {current:,.2f} ج.م
🎯 هدف الشراء: {low:,.0f} ج.م

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
# 8. الواجهة الرئيسية (محسنة)
# ==========================================
def main():
    init_db()
    start_background_checker()
    views = update_and_get_views()
    
    # إعدادات التحوط
    if 'usd_hedge' not in st.session_state:
        st.session_state['usd_hedge'] = 0.50
    
    # الشريط الجانبي
    with st.sidebar:
        st.image("https://img.icons8.com/color/96/000000/gold-bars.png", width=80)
        st.title("🏅 Gold Meter Pro")
        
        st.markdown("### ⚙️ تحكم السعر")
        usd_hedge = st.slider(
            "تحوط الدولار (جنيه)",
            min_value=0.00,
            max_value=2.00,
            step=0.05,
            value=st.session_state['usd_hedge'],
            help="أضف قيمة تحوط لتقريب السعر من السوق الفعلي"
        )
        if usd_hedge != st.session_state['usd_hedge']:
            st.session_state['usd_hedge'] = usd_hedge
            st.rerun()
        
        # جلب الأسعار
        karat_data, gold_oz, usd_egp = get_market_data(usd_hedge)
        
        st.markdown("### 📊 المؤشرات")
        st.metric("🌍 أونصة الذهب", f"${gold_oz:,.2f}")
        st.metric("💵 الدولار", f"{usd_egp:.2f} ج.م", delta=f"+{usd_hedge:.2f}")
        
        st.divider()
        st.markdown("### 💎 الجرامات")
        for k in ['24', '22', '21', '18']:
            data = karat_data.get(k, {})
            mid = data.get('mid', 0)
            st.metric(f"عيار {k}", f"{mid:,.2f} ج.م")
        
        st.divider()
        st.caption(f"👁️ زوار اليوم: {views}")
        st.caption("⏱️ تحديث لحظي")
        st.caption("💡 حرك شريط التحوط")
    
    # المحتوى الرئيسي
    st.title("🏅 Gold Meter Pro - منصة الذهب المتكاملة")
    st.markdown(f"🔄 **آخر تحديث:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # بطاقات الأسعار الرئيسية
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.markdown(f"""
        <div style='background: linear-gradient(135deg, #1a1a2e, #16213e); padding: 20px; border-radius: 15px; text-align: center; border: 2px solid #FFD700;'>
            <h4 style='color: #FFD700;'>🌍 أونصة الذهب</h4>
            <h1 style='color: white;'>${gold_oz:,.2f}</h1>
        </div>
        """, unsafe_allow_html=True)
    
    with col2:
        st.markdown(f"""
        <div style='background: linear-gradient(135deg, #1a1a2e, #16213e); padding: 20px; border-radius: 15px; text-align: center; border: 2px solid #00d4ff;'>
            <h4 style='color: #00d4ff;'>💵 الدولار</h4>
            <h1 style='color: white;'>{usd_egp:.2f} ج.م</h1>
            <small style='color: #ffd93d;'>⚡ تحوط: {usd_hedge:.2f}</small>
        </div>
        """, unsafe_allow_html=True)
    
    with col3:
        price_21 = karat_data.get('21', {}).get('mid', 0)
        st.markdown(f"""
        <div style='background: linear-gradient(135deg, #1a1a2e, #16213e); padding: 20px; border-radius: 15px; text-align: center; border: 2px solid #ff6b6b;'>
            <h4 style='color: #ff6b6b;'>🏅 عيار 21</h4>
            <h1 style='color: white;'>{price_21:,.2f} ج.م</h1>
        </div>
        """, unsafe_allow_html=True)
    
    with col4:
        recs, score, details = get_advanced_analysis(gold_oz, usd_egp, karat_data)
        color = "#00ff88" if score >= 10 else "#ffd93d" if score >= 0 else "#ff6b6b"
        final = details.get('final', 'احتفاظ')
        st.markdown(f"""
        <div style='background: linear-gradient(135deg, #1a1a2e, #16213e); padding: 20px; border-radius: 15px; text-align: center; border: 2px solid {color};'>
            <h4 style='color: {color};'>📊 التوصية</h4>
            <h2 style='color: white;'>{final}</h2>
            <small style='color: #aaa;'>نقاط القوة: {score}</small>
        </div>
        """, unsafe_allow_html=True)
    
    st.divider()
    
    # ===== أسعار الشراء والبيع =====
    st.markdown("### 💰 أسعار الشراء والبيع")
    
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
    
    # ===== التبويبات =====
    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "📊 التحليل المتقدم", 
        "💡 التوصيات", 
        "📰 الأخبار", 
        "🔔 التنبيهات",
        "⚙️ الإدارة"
    ])
    
    with tab1:
        st.subheader("📈 التحليل الفني المتقدم")
        
        # رسم بياني مع المتوسطات
        hist_data, _ = get_historical_data()
        
        fig = go.Figure()
        
        # السعر
        fig.add_trace(go.Scatter(
            x=hist_data.index,
            y=hist_data['Close'],
            mode='lines',
            name='سعر الذهب',
            line=dict(color='#FFD700', width=2)
        ))
        
        # المتوسطات المتحركة
        if len(hist_data) > 7:
            ma7 = hist_data['Close'].rolling(window=7).mean()
            ma20 = hist_data['Close'].rolling(window=20).mean()
            ma50 = hist_data['Close'].rolling(window=50).mean() if len(hist_data) > 50 else None
            
            fig.add_trace(go.Scatter(
                x=hist_data.index,
                y=ma7,
                mode='lines',
                name='MA 7 أيام',
                line=dict(color='#00d4ff', width=1, dash='dash')
            ))
            fig.add_trace(go.Scatter(
                x=hist_data.index,
                y=ma20,
                mode='lines',
                name='MA 20 يوم',
                line=dict(color='#ff6b6b', width=1, dash='dot')
            ))
            if ma50 is not None:
                fig.add_trace(go.Scatter(
                    x=hist_data.index,
                    y=ma50,
                    mode='lines',
                    name='MA 50 يوم',
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
        
        # مؤشرات إضافية
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
                st.metric("📊 المتوسط 30 يوم", f"${hist_data['Close'].mean():.2f}")
    
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
            
            st.markdown("#### 📋 التفاصيل الفنية")
            for key, value in details.items():
                if key not in ['final']:
                    st.caption(f"**{key}:** {value}")
        
        with col2:
            st.markdown("#### 📋 التوصيات المفصلة")
            for rec in recs:
                if "🔴" in rec or "📉" in rec:
                    st.warning(rec)
                elif "🟢" in rec or "📈" in rec or "🌟" in rec:
                    st.success(rec)
                else:
                    st.info(rec)
    
    with tab3:
        st.subheader("📰 أخبار الذهب والدولار")
        all_news = fetch_all_news()
        if all_news:
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
    
    with tab5:
        st.subheader("⚙️ الإدارة والإحصائيات")
        
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("👁️ زوار اليوم", views)
        with col2:
            df_all = get_alerts(only_active=False)
            st.metric("📋 التنبيهات", len(df_all) if not df_all.empty else 0)
        with col3:
            active = len(df_all[df_all['triggered']==0]) if not df_all.empty else 0
            st.metric("🟢 النشطة", active)
        
        st.divider()
        st.markdown("### 📖 دليل المستخدم")
        with st.expander("📖 كيف تحصل على Chat ID؟"):
            st.markdown("""
            1. ابحث عن `@userinfobot` في تليجرام
            2. اضغط **Start**
            3. سيرسل لك البوت رقم الـ ID الخاص بك
            """)
        with st.expander("📖 كيف تعمل التوصيات؟"):
            st.markdown("""
            تعتمد التوصيات على:
            1. **تحليل سعر الذهب** (دعم/مقاومة)
            2. **تحليل سعر الدولار** (تأثير محلي)
            3. **تحليل عيار 21** (الأكثر تداولاً)
            4. **مؤشر RSI** (قوة السوق)
            5. **المتوسطات المتحركة** (الاتجاه)
            6. **مؤشر MACD** (زخم السوق)
            """)
        with st.expander("📖 كيف يعمل التحوط؟"):
            st.markdown("""
            التحوط هو إضافة قيمة على سعر الدولار لتقريب السعر من السوق الفعلي.
            - حرك شريط التحوط في الشريط الجانبي
            - شاهد الأسعار تتغير فوراً
            - استخدم التحوط لضبط دقة الأسعار
            """)

if __name__ == "__main__":
    main()
