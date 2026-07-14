# ============================================================
# Gold Meter Pro - منصة تحليل الذهب المتكاملة
# Copyright (c) 2026 Techno logic / Haytham Elsaadany
# ============================================================

import dash
from dash import dcc, html, Input, Output, State, callback
import plotly.graph_objects as go
import pandas as pd
import yfinance as yf
import requests
import sqlite3
import threading
import time
from datetime import datetime, timedelta

# ============================================================
# إعدادات التطبيق
# ============================================================
app = dash.Dash(
    __name__,
    title="🏅 Gold Meter Pro",
    update_title=None,
    suppress_callback_exceptions=True,
    meta_tags=[
        {"name": "viewport", "content": "width=device-width, initial-scale=1.0"},
        {"name": "author", "content": "Techno logic 2026 / Haytham Elsaadany"},
    ]
)
server = app.server

# ============================================================
# إعدادات ثابتة
# ============================================================
OUNCE_TO_GRAM = 31.1035
TAX_RATE = 0.019  # 1.9% دمغة

# ============================================================
# جلب الأسعار من yfinance (مباشر)
# ============================================================
def get_live_gold():
    """جلب سعر الذهب من yfinance"""
    try:
        ticker = yf.Ticker("GC=F")
        # محاولة طرق مختلفة للحصول على السعر
        price = ticker.fast_info.get('last_price')
        if price is None or price == 0:
            price = ticker.info.get('regularMarketPrice')
        if price is None or price == 0:
            price = ticker.info.get('currentPrice')
        if price is not None and price > 0:
            print(f"✅ الذهب: ${price:.2f}")
            return float(price)
    except Exception as e:
        print(f"⚠️ فشل جلب الذهب: {e}")
    return None

def get_live_usd():
    """جلب سعر الدولار من yfinance"""
    try:
        ticker = yf.Ticker("EGP=X")
        price = ticker.fast_info.get('regularMarketPrice')
        if price is None or price == 0:
            price = ticker.info.get('regularMarketPrice')
        if price is not None and price > 0:
            print(f"✅ الدولار: {price:.2f}")
            return float(price)
    except Exception as e:
        print(f"⚠️ فشل جلب الدولار: {e}")
    return None

def fetch_live_prices():
    """جلب جميع الأسعار"""
    gold = get_live_gold()
    usd = get_live_usd()
    
    if gold is not None and usd is not None:
        print(f"🎯 النهائي: الذهب ${gold:.2f}, الدولار {usd:.2f} ج.م")
        return gold, usd
    
    return None, None

# ============================================================
# تحديث الخلفية (كل 10 ثواني)
# ============================================================
CURRENT_GOLD = None
CURRENT_USD = None

def background_updater():
    global CURRENT_GOLD, CURRENT_USD
    while True:
        try:
            gold, usd = fetch_live_prices()
            if gold is not None and usd is not None:
                CURRENT_GOLD = gold
                CURRENT_USD = usd
                print(f"🔄 [{datetime.now().strftime('%H:%M:%S')}] تم التحديث")
        except Exception as e:
            print(f"⚠️ خطأ: {e}")
        time.sleep(10)

thread = threading.Thread(target=background_updater, daemon=True)
thread.start()

# ============================================================
# دوال حساب الأسعار
# ============================================================
def get_market_data(gold_price, usd_price):
    if gold_price is None or usd_price is None:
        return None
    
    gram_24_base = (gold_price * usd_price) / OUNCE_TO_GRAM
    
    karat_data = {}
    for karat in [24, 22, 21, 18]:
        base = gram_24_base * (karat / 24)
        price_with_tax = base * (1 + TAX_RATE)
        spread_rates = {24: 0.0085, 22: 0.0090, 21: 0.0085, 18: 0.0080}
        spread = spread_rates.get(karat, 0.0085)
        
        karat_data[str(karat)] = {
            'buy': round(price_with_tax * (1 - spread/2), 2),
            'sell': round(price_with_tax * (1 + spread/2), 2),
            'mid': round(price_with_tax, 2)
        }
    
    return karat_data

def get_fear_greed(gold, usd, karat_data):
    if gold is None or usd is None or karat_data is None:
        return "⚠️", "جاري التحميل..."
    
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

def get_recommendations(gold, usd, karat_data):
    if gold is None or usd is None or karat_data is None:
        return ["⚠️ جاري التحميل..."], 0
    
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

# ============================================================
# الواجهة
# ============================================================
app.layout = html.Div([
    dcc.Interval(id='interval', interval=10*1000),
    
    html.Div([
        html.H1("🏅 Gold Meter Pro", style={'color': '#FFD700', 'textAlign': 'center'}),
        html.P("منصة تحليل الذهب المتكاملة - v2.0.0", style={'textAlign': 'center', 'color': '#888'}),
        html.Hr(),
        
        html.Div(id='status-display', style={'textAlign': 'center', 'color': '#00ff88', 'marginBottom': '20px'}),
        
        html.Div([
            html.Div([
                html.H4("🌍 أونصة الذهب", style={'color': '#FFD700'}),
                html.H2(id='gold-display', style={'color': 'white'})
            ], style={'display': 'inline-block', 'width': '30%', 'padding': '20px', 'background': '#1a1a2e', 'borderRadius': '10px', 'margin': '10px'}),
            
            html.Div([
                html.H4("💵 الدولار", style={'color': '#00d4ff'}),
                html.H2(id='usd-display', style={'color': 'white'})
            ], style={'display': 'inline-block', 'width': '30%', 'padding': '20px', 'background': '#1a1a2e', 'borderRadius': '10px', 'margin': '10px'}),
            
            html.Div([
                html.H4("🏅 عيار 21", style={'color': '#ff6b6b'}),
                html.H2(id='karat21-display', style={'color': 'white'})
            ], style={'display': 'inline-block', 'width': '30%', 'padding': '20px', 'background': '#1a1a2e', 'borderRadius': '10px', 'margin': '10px'}),
        ], style={'textAlign': 'center'}),
        
        html.Hr(),
        
        html.Div([
            html.Div(id='prices-grid', style={'display': 'grid', 'gridTemplateColumns': 'repeat(4, 1fr)', 'gap': '20px', 'padding': '20px'})
        ]),
        
        html.Hr(),
        
        html.Div([
            html.Div(id='recommendations', style={'padding': '20px'})
        ]),
        
        html.Hr(),
        
        html.Div([
            html.P("© 2026 Techno logic / Haytham Elsaadany", style={'textAlign': 'center', 'color': '#444'}),
            html.P("📞 01223999366 - 01066774623", style={'textAlign': 'center', 'color': '#444'}),
        ])
    ], style={'padding': '20px', 'background': '#080810', 'color': 'white', 'minHeight': '100vh'})
])

# ============================================================
# الكول باك
# ============================================================
@app.callback(
    [Output('gold-display', 'children'),
     Output('usd-display', 'children'),
     Output('karat21-display', 'children'),
     Output('prices-grid', 'children'),
     Output('recommendations', 'children'),
     Output('status-display', 'children')],
    [Input('interval', 'n_intervals')]
)
def update_ui(n):
    global CURRENT_GOLD, CURRENT_USD
    
    if CURRENT_GOLD is None or CURRENT_USD is None:
        return ("⏳ جاري التحميل...", "⏳ جاري التحميل...", "⏳ جاري التحميل...",
                html.Div("⏳ جاري التحميل..."), html.Div("⏳ جاري التحميل..."), 
                "⏳ جاري جلب الأسعار من البورصة...")
    
    gold = CURRENT_GOLD
    usd = CURRENT_USD
    
    karat_data = get_market_data(gold, usd)
    if karat_data is None:
        return ("⚠️ خطأ", "⚠️ خطأ", "⚠️ خطأ",
                html.Div("⚠️ خطأ في البيانات"), html.Div("⚠️ خطأ"), 
                "⚠️ فشل جلب الأسعار")
    
    fear_score, fear_status = get_fear_greed(gold, usd, karat_data)
    recs, score = get_recommendations(gold, usd, karat_data)
    
    # بطاقات الشراء والبيع
    cards = []
    for k in ['24', '22', '21', '18']:
        d = karat_data.get(k, {})
        cards.append(html.Div([
            html.H4(f"عيار {k}", style={'color': '#ffd93d'}),
            html.P(f"شراء: {d.get('buy', 0):,.2f} ج.م", style={'color': '#00ff88'}),
            html.P(f"بيع: {d.get('sell', 0):,.2f} ج.م", style={'color': '#ff6b6b'}),
        ], style={'background': '#1a1a2e', 'padding': '15px', 'borderRadius': '10px', 'border': '1px solid #333', 'textAlign': 'center'}))
    
    # التوصيات
    rec_display = html.Div([
        html.H4("💡 التوصيات الذكية", style={'color': '#FFD700'}),
        html.P(f"📊 مؤشر الخوف والطمع: {fear_score} - {fear_status}", style={'color': '#ffd93d'}),
    ] + [html.P(rec, style={'padding': '5px 0'}) for rec in recs])
    
    status = f"🔄 آخر تحديث: {datetime.now().strftime('%H:%M:%S')} | الذهب: ${gold:.2f} | الدولار: {usd:.2f} ج.م"
    
    return (f"${gold:,.2f}", f"{usd:.2f} ج.م", f"{karat_data.get('21', {}).get('mid', 0):,.2f} ج.م",
            cards, rec_display, status)

# ============================================================
# تشغيل التطبيق
# ============================================================
if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=8050)
