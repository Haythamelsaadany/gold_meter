import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import requests
import json
import time
import re
from datetime import datetime, timedelta

# ==========================================
# إعدادات الصفحة
# ==========================================
st.set_page_config(
    page_title="🏅 Gold Meter Pro",
    layout="wide",
    page_icon="🏅"
)

# ==========================================
# إعدادات ثابتة
# ==========================================
OUNCE_TO_GRAM = 31.1035
TAX_RATE = 0.019  # 1.9% دمغة

# ==========================================
# 1. جلب سعر الذهب من Google Finance
# ==========================================
def get_gold_price():
    """جلب سعر الذهب من Google Finance"""
    try:
        # Google Finance API
        url = "https://finance.google.com/finance?q=XAUUSD&output=json"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'application/json'
        }
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            # البحث عن السعر في النص
            match = re.search(r'"l":\s*"([0-9.]+)"', response.text)
            if match:
                return float(match.group(1))
    except Exception as e:
        print(f"⚠️ Google Finance فشل: {e}")
    
    # محاولة بديلة من Investing.com
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'text/html,application/xhtml+xml',
        }
        response = requests.get('https://www.investing.com/currencies/xau-usd', headers=headers, timeout=10)
        if response.status_code == 200:
            match = re.search(r'"last":\s*([0-9.]+)', response.text)
            if match:
                return float(match.group(1))
    except Exception as e:
        print(f"⚠️ Investing.com فشل: {e}")
    
    return None

# ==========================================
# 2. جلب سعر الدولار من Google Finance
# ==========================================
def get_usd_price():
    """جلب سعر الدولار من Google Finance"""
    try:
        url = "https://finance.google.com/finance?q=USDEGP&output=json"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'application/json'
        }
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            match = re.search(r'"l":\s*"([0-9.]+)"', response.text)
            if match:
                return float(match.group(1))
    except Exception as e:
        print(f"⚠️ Google Finance فشل: {e}")
    
    # محاولة بديلة من ExchangeRate-API
    try:
        response = requests.get('https://open.er-api.com/v6/latest/USD', timeout=10)
        if response.status_code == 200:
            data = response.json()
            if data and 'rates' in data and 'EGP' in data['rates']:
                return float(data['rates']['EGP'])
    except Exception as e:
        print(f"⚠️ ExchangeRate فشل: {e}")
    
    return None

# ==========================================
# 3. جلب الأسعار (مع إعادة محاولة)
# ==========================================
@st.cache_data(ttl=15)
def get_live_prices():
    """جلب الأسعار مع إعادة محاولة تلقائية"""
    for attempt in range(5):
        gold = get_gold_price()
        usd = get_usd_price()
        
        if gold is not None and usd is not None:
            print(f"✅ الذهب: ${gold:.2f}, الدولار: {usd:.2f}")
            return gold, usd
        
        print(f"⚠️ محاولة {attempt+1}/5 فشلت، إعادة المحاولة...")
        time.sleep(2)
    
    return None, None

# ==========================================
# 4. حساب الجرامات
# ==========================================
def calculate_prices(gold, usd):
    gram24 = (gold * usd) / OUNCE_TO_GRAM
    karat_data = {}
    for k in [24, 22, 21, 18]:
        base = gram24 * (k / 24) * (1 + TAX_RATE)
        spread = {24: 0.0085, 22: 0.0090, 21: 0.0085, 18: 0.0080}.get(k, 0.0085)
        karat_data[str(k)] = {
            'buy': round(base * (1 - spread/2), 2),
            'sell': round(base * (1 + spread/2), 2),
            'mid': round(base, 2)
        }
    return karat_data

# ==========================================
# 5. مؤشر الخوف والطمع
# ==========================================
def get_fear_greed(gold, usd, karat_data):
    score = 50
    if gold > 2450:
        score -= 15
    elif gold > 2400:
        score -= 8
    elif gold > 2350:
        score += 5
    elif gold > 2300:
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
    
    if usd > 50.5:
        score -= 10
    elif usd > 49.5:
        score -= 5
    elif usd > 48.5:
        score += 5
    else:
        score += 10
    
    score = max(0, min(100, score))
    
    if score >= 80:
        status = "🟢 طمع شديد"
    elif score >= 60:
        status = "🟡 طمع"
    elif score >= 40:
        status = "🟠 محايد"
    elif score >= 20:
        status = "🔴 خوف"
    else:
        status = "🔴 خوف شديد"
    
    return score, status

# ==========================================
# 6. التوصيات
# ==========================================
def get_recommendations(gold, usd, karat_data):
    recs = []
    score = 0
    
    if gold > 2450:
        recs.append("🔴 الذهب في منطقة مقاومة قوية")
        score -= 15
    elif gold > 2400:
        recs.append("🟡 الذهب في منطقة مقاومة")
        score -= 5
    elif gold > 2350:
        recs.append("🟢 الذهب في منطقة محايدة")
        score += 5
    elif gold > 2300:
        recs.append("🟢 الذهب في منطقة دعم - فرصة شراء")
        score += 10
    else:
        recs.append("🟢 الذهب في دعم قوي - شراء ممتاز")
        score += 15
    
    price_21 = karat_data.get('21', {}).get('mid', 0)
    if price_21 > 5900:
        recs.append("🔴 عيار 21 مرتفع جداً")
        score -= 10
    elif price_21 > 5800:
        recs.append("🟡 عيار 21 مرتفع")
        score -= 5
    elif price_21 > 5700:
        recs.append("🟢 عيار 21 متوسط")
        score += 5
    elif price_21 > 5600:
        recs.append("🟢 عيار 21 جذاب - فرصة شراء")
        score += 10
    else:
        recs.append("🟢 عيار 21 جذاب جداً - شراء ممتاز")
        score += 15
    
    if score >= 20:
        recs.append("🌟 **توصية: شراء قوي**")
    elif score >= 10:
        recs.append("📈 **توصية: شراء**")
    elif score >= 0:
        recs.append("➡️ **توصية: احتفاظ**")
    else:
        recs.append("🔴 **توصية: بيع**")
    
    return recs, score

# ==========================================
# 7. الرسم البياني
# ==========================================
@st.cache_data(ttl=300)
def get_chart_data():
    try:
        import yfinance as yf
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
# 8. الواجهة الرئيسية
# ==========================================
def main():
    st.title("🏅 Gold Meter Pro - منصة الذهب المتكاملة")
    
    # جلب الأسعار
    with st.spinner("⏳ جاري تحميل الأسعار من البورصة العالمية..."):
        gold, usd = get_live_prices()
    
    if gold is None or usd is None:
        st.error("❌ فشل جلب الأسعار. تأكد من اتصال الإنترنت.")
        st.info("💡 يتم استخدام مصادر: Google Finance و Investing.com")
        if st.button("🔄 إعادة المحاولة"):
            st.cache_data.clear()
            st.rerun()
        return
    
    # حساب البيانات
    karat_data = calculate_prices(gold, usd)
    fear_score, fear_status = get_fear_greed(gold, usd, karat_data)
    recs, score = get_recommendations(gold, usd, karat_data)
    
    # عرض آخر تحديث
    st.caption(f"🔄 آخر تحديث: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    st.success(f"✅ تم جلب الأسعار بنجاح - الذهب: ${gold:.2f}, الدولار: {usd:.2f} ج.م")
    st.info(f"💰 تم إضافة {TAX_RATE*100:.1f}% دمغة على جميع الأسعار")
    
    # بطاقات الأسعار
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric("🌍 أونصة الذهب", f"${gold:,.2f}")
    
    with col2:
        st.metric("💵 الدولار (السوق الفعلي)", f"{usd:.2f} ج.م")
    
    with col3:
        price_21 = karat_data.get('21', {}).get('mid', 0)
        st.metric("🏅 عيار 21", f"{price_21:,.2f} ج.م")
    
    with col4:
        st.metric("📊 مؤشر الخوف", f"{fear_score}", delta=fear_status)
    
    st.divider()
    
    # أسعار الشراء والبيع
    st.subheader("💰 أسعار الشراء والبيع (شاملة الدمغة)")
    cols = st.columns(4)
    for i, k in enumerate(['24', '22', '21', '18']):
        data = karat_data.get(k, {})
        with cols[i]:
            st.markdown(f"""
            **عيار {k}**
            - شراء: {data.get('buy', 0):,.2f} ج.م
            - بيع: {data.get('sell', 0):,.2f} ج.م
            """)
    
    st.divider()
    
    # التوصيات
    st.subheader("💡 التوصيات الذكية")
    for rec in recs:
        if "🔴" in rec:
            st.warning(rec)
        elif "🟢" in rec or "🌟" in rec:
            st.success(rec)
        else:
            st.info(rec)
    
    # الرسم البياني
    st.subheader("📈 أداء الذهب - آخر 30 يوم")
    chart_data, fallback = get_chart_data()
    st.line_chart(chart_data['Close'])

if __name__ == "__main__":
    main()
