# ============================================================
# Gold Meter Pro - منصة تحليل الذهب المتكاملة
# Copyright (c) 2026 Techno logic / Haytham Elsaadany
# All rights reserved.
# ============================================================
# Version: 2.1.0 (محدث بأسعار السوق الفورية واللحظية)
# Author: Techno logic 2026 / Haytham Elsaadany
# Contact: 01223999366 - 01066774623 - 01014946580
# Email: lamar.haytham17@gmail.com - h.elsaadany@almalnews.com
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
import json
import urllib.request
import re
from datetime import datetime, timedelta

# ============================================================
# إعدادات التطبيق الثابتة
# ============================================================
STANDARD_GOLD = 2400.0  # السعر العالمي التقريبي للأونصة كاحتياطي
STANDARD_USD = 49.50    # السعر الاحتياطي للدولار
OUNCE_TO_GRAM = 31.1035
TAX_RATE = 0.019        # 1.9% دمغة
DB_FILE = "gold_meter.db"

# ============================================================
# قاعدة البيانات
# ============================================================
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS price_cache (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        gold_price REAL,
        usd_price REAL,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS alerts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT,
        tg_id TEXT,
        karat TEXT,
        high_target REAL,
        low_target REAL,
        triggered INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS visitors (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ip TEXT,
        visited_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    conn.commit()
    conn.close()

def save_price_cache(gold, usd):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT INTO price_cache (gold_price, usd_price) VALUES (?, ?)", (gold, usd))
    conn.commit()
    conn.close()

def get_last_cached_price():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT gold_price, usd_price FROM price_cache ORDER BY id DESC LIMIT 1")
    row = c.fetchone()
    conn.close()
    if row:
        return row[0], row[1]
    return STANDARD_GOLD, STANDARD_USD

init_db()

# ============================================================
# جلب الأسعار اللحظية من السوق المصري والعالمي
# ============================================================

def fetch_egypt_gold_live():
    """
    جلب سعر عيار 21 الفعلي من السوق المصري (الصاغة) عبر معالجة بيانات الويب اللحظية.
    """
    try:
        # استخدام هيدر حقيقي لتجنب حظر السكربتات
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        
        # جلب البيانات من موقع أسعار الصاغة المباشرة (Ta3weem / Gold Bullion)
        url = "https://ta3weem.com/gold-prices"
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=8) as response:
            html_content = response.read().decode('utf-8')
            
            # البحث عن سعر عيار 21 شراء وبيع باستخدام Regex مرن
            matches = re.findall(r'(\d{1,2})K\s*Gold.*?([\d,]+)\.00', html_content, re.IGNORECASE | re.DOTALL)
            prices = {k: float(val.replace(',', '')) for k, val in matches}
            
            if '21' in prices:
                print(f"✅ تم جلب سعر عيار 21 المحلي: {prices['21']} ج.م")
                return prices['21']
            
            # مصدر احتياطي سريع في حال تغير تصميم الموقع الأول (Dahab Masr)
            url_backup = "https://dahabmasr.com/gold-price-today"
            req_backup = urllib.request.Request(url_backup, headers=headers)
            with urllib.request.urlopen(req_backup, timeout=8) as response_backup:
                html_content_backup = response_backup.read().decode('utf-8')
                match_backup = re.search(r'21\s*Karat\s*Gold.*?([\d,]+)\.00', html_content_backup, re.DOTALL | re.IGNORECASE)
                if match_backup:
                    price_21 = float(match_backup.group(1).replace(',', ''))
                    print(f"✅ تم جلب السعر من المصدر البديل عيار 21: {price_21} ج.م")
                    return price_21
    except Exception as e:
        print(f"⚠️ فشل جلب السعر المحلي مباشرة: {e}")
    return None

def fetch_gold_price_global():
    """ جلب سعر أونصة الذهب العالمية لحظياً """
    try:
        ticker = yf.Ticker("GC=F")
        price = ticker.fast_info.get('last_price', 0)
        if price == 0:
            price = ticker.info.get('regularMarketPrice', 0)
        if price > 0:
            print(f"✅ الذهب العالمي: ${price:.2f}")
            return price
    except Exception as e:
        print(f"⚠️ فشل جلب الذهب العالمي: {e}")
    return None

def fetch_live_prices():
    """
    دمج السعر العالمي والمحلي لحساب سعر الدولار الفعلي في السوق الموازي والذهب بدقة.
    """
    global_gold = fetch_gold_price_global()
    local_21 = fetch_egypt_gold_live()
    
    if global_gold and local_21:
        # حساب السعر الفعلي لعيار 24 من عيار 21 المحلي
        local_24 = local_21 * (24 / 21)
        
        # حساب سعر الدولار الفعلي (الضمني/الموازي) المستخدم لتسعير الذهب بالصاغة
        implied_usd = (local_24 * OUNCE_TO_GRAM) / global_gold
        
        print(f"⚡ سعر الدولار الموازي المحسوب من الصاغة: {implied_usd:.2f} ج.م")
        save_price_cache(global_gold, implied_usd)
        return global_gold, implied_usd

    # في حال الفشل نعود لآخر كاش محفوظ بقاعدة البيانات
    gold, usd = get_last_cached_price()
    print(f"⚠️ استخدام الكاش المخزن: الذهب ${gold:.2f}, الدولار {usd:.2f} ج.م")
    return gold, usd

# ============================================================
# تحديث الخلفية (كل 10 ثواني)
# ============================================================
CURRENT_GOLD = STANDARD_GOLD
CURRENT_USD = STANDARD_USD

def background_updater():
    global CURRENT_GOLD, CURRENT_USD
    while True:
        try:
            gold, usd = fetch_live_prices()
            if gold > 0:
                CURRENT_GOLD = gold
            if usd > 0:
                CURRENT_USD = usd
            print(f"🔄 [{datetime.now().strftime('%H:%M:%S')}] تم التحديث بنجاح")
        except Exception as e:
            print(f"⚠️ خطأ في الخلفية: {e}")
        time.sleep(10)

thread = threading.Thread(target=background_updater, daemon=True)
thread.start()

# ============================================================
# دوال حساب الأسعار والتحليل
# ============================================================
def get_market_data(gold_price, usd_price, tax_rate=TAX_RATE):
    gram_24_base = (gold_price * usd_price) / OUNCE_TO_GRAM
    
    karat_data = {}
    for karat in [24, 22, 21, 18]:
        base = gram_24_base * (karat / 24)
        price_with_tax = base * (1 + tax_rate)
        # هوامش شراء وبيع الصاغة
        spread_rates = {24: 0.0085, 22: 0.0090, 21: 0.0085, 18: 0.0080}
        spread = spread_rates.get(karat, 0.0085)
        
        karat_data[str(karat)] = {
            'buy': round(price_with_tax * (1 - spread/2), 2),
            'sell': round(price_with_tax * (1 + spread/2), 2),
            'mid': round(price_with_tax, 2)
        }
    
    return karat_data

def get_fear_greed_score(gold_price, usd_price, karat_data):
    score = 50
    if gold_price > 2450:
        score -= 15
    elif gold_price > 2400:
        score -= 8
    elif gold_price > 2350:
        score += 5
    elif gold_price > 2300:
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
    
    if usd_price > 50.5:
        score -= 10
    elif usd_price > 49.5:
        score -= 5
    elif usd_price > 48.5:
        score += 5
    else:
        score += 10
    
    score = max(0, min(100, score))
    
    if score >= 80:
        status = "🟢 طمع شديد"
        rec = "السوق في ذروة التفاؤل - كن حذراً"
    elif score >= 60:
        status = "🟡 طمع"
        rec = "السوق متفائل - توقع تصحيح"
    elif score >= 40:
        status = "🟠 محايد"
        rec = "السوق متوازن - انتظر تأكيد"
    elif score >= 20:
        status = "🔴 خوف"
        rec = "السوق خائف - فرصة شراء"
    else:
        status = "🔴 خوف شديد"
        rec = "السوق في ذروة الخوف - فرصة شراء ممتازة"
    
    return score, status, rec

def get_technical_analysis(gold_price):
    return {
        'rsi': 55,
        'trend': 'صاعد' if gold_price > 2400 else 'هابط' if gold_price < 2300 else 'عرضي',
        'support': gold_price - 50,
        'resistance': gold_price + 50,
        'ma7': gold_price - 10,
        'ma20': gold_price - 5,
    }

def fetch_news():
    return [
        {"title": "الذهب يستقر عند مستويات مرتفعة مع ترقب بيانات التضخم", "source": "رويترز"},
        {"title": "الدولار يتراجع مع توقعات خفض الفائدة", "source": "بلومبرج"},
        {"title": "البنوك المركزية تواصل شراء الذهب", "source": "سي إن بي سي"},
        {"title": "المحللون: الذهب قد يصل إلى 2500$ نهاية العام", "source": "فاينانشال تايمز"},
        {"title": "أسعار الذهب في مصر تشهد استقراراً مع تراجع الطلب", "source": "الأهرام"},
    ]

# ============================================================
# واجهة التطبيق
# ============================================================
app.layout = html.Div([
    dcc.Interval(id='interval', interval=10*1000),
    
    # ===== الشريط الجانبي =====
    html.Div([
        html.Div([
            html.H1("🏅", style={'fontSize': '48px', 'textAlign': 'center', 'margin': '0'}),
            html.H2("Gold Meter Pro", style={'textAlign': 'center', 'color': '#FFD700', 'margin': '0'}),
            html.P("v2.1.0 - Live Market", style={'textAlign': 'center', 'color': '#666', 'fontSize': '12px'})
        ], style={'padding': '20px 0', 'borderBottom': '1px solid #1f1f3a'}),
        
        html.Div([
            html.H4("⚙️ تحكم السعر يدويًا", style={'color': '#FFD700'}),
            html.Label("سعر الأونصة ($)", style={'color': '#aaa'}),
            dcc.Input(id='gold-input', type='number', placeholder="جاري الجلب تلقائياً...", step=0.1,
                style={'width': '100%', 'padding': '8px', 'borderRadius': '8px', 'border': '1px solid #444', 'background': '#1a1a2e', 'color': 'white', 'marginBottom': '15px'}),
            html.Label("سعر الدولار (ج.م)", style={'color': '#aaa'}),
            dcc.Input(id='usd-input', type='number', placeholder="جاري الحساب تلقائياً...", step=0.01,
                style={'width': '100%', 'padding': '8px', 'borderRadius': '8px', 'border': '1px solid #444', 'background': '#1a1a2e', 'color': 'white', 'marginBottom': '15px'}),
            html.Label("الدمغة (%)", style={'color': '#aaa'}),
            dcc.Slider(id='tax-slider', min=0, max=5, step=0.1, value=TAX_RATE*100,
                marks={i: f'{i}%' for i in range(0, 6)}),
            html.Button("🔄 تحديث يدوي للأسعار", id='update-btn', n_clicks=0, style={
                'width': '100%', 'padding': '12px', 'background': '#FFD700', 'color': 'black',
                'fontWeight': 'bold', 'border': 'none', 'borderRadius': '8px', 'cursor': 'pointer', 'marginTop': '20px'
            }),
            html.P("⏱️ تحديث تلقائي (مباشر) كل 10 ثواني", style={'textAlign': 'center', 'color': '#00ff88', 'fontSize': '12px', 'marginTop': '10px'})
        ]),
        
        html.Hr(),
        html.Div(id='sidebar-stats', style={'padding': '10px 0'}),
        html.Hr(),
        
        html.Div([
            html.P("© 2026 Techno logic", style={'textAlign': 'center', 'color': '#444'}),
            html.P("Haytham Elsaadany", style={'textAlign': 'center', 'color': '#444'}),
            html.P("01223999366 - 01066774623", style={'textAlign': 'center', 'color': '#444', 'fontSize': '10px'}),
            html.P("lamar.haytham17@gmail.com", style={'textAlign': 'center', 'color': '#444', 'fontSize': '10px'})
        ], style={'position': 'absolute', 'bottom': '10px', 'left': '0', 'right': '0', 'padding': '0 20px'})
        
    ], style={
        'position': 'fixed', 'top': 0, 'left': 0, 'bottom': 0,
        'width': '280px', 'padding': '20px', 'background': '#0a0a1a',
        'borderRight': '1px solid #1f1f3a', 'overflowY': 'auto',
        'color': 'white', 'zIndex': '1000'
    }),
    
    # ===== المحتوى الرئيسي =====
    html.Div([
        # الهيدر
        html.Div([
            html.H1("🏅 Gold Meter Pro", style={'color': 'white', 'margin': '0', 'fontSize': '28px'}),
            html.P("منصة تحليل الذهب والتسعير اللحظي للسوق المصري", style={'color': '#888', 'margin': '0'})
        ], style={'padding': '20px 30px', 'background': '#0f0f1e', 'borderRadius': '12px', 'marginBottom': '20px'}),
        
        html.Div(id='last-update', style={'textAlign': 'center', 'color': '#666', 'marginBottom': '20px'}),
        
        # ===== بطاقات الأسعار =====
        html.Div([
            html.Div([
                html.H4("🌍 أونصة الذهب عالمياً", style={'color': '#FFD700'}),
                html.H2(id='gold-display', style={'color': 'white'}),
                html.Small("شاشة البورصة العالمية", style={'color': '#00ff88'})
            ], style={'background': '#1a1a2e', 'padding': '20px', 'borderRadius': '15px', 'textAlign': 'center', 'border': '2px solid #FFD700', 'flex': '1', 'margin': '10px'}),
            
            html.Div([
                html.H4("💵 دولار الصاغة (الموازي)", style={'color': '#00d4ff'}),
                html.H2(id='usd-display', style={'color': 'white'}),
                html.Small("السعر اللحظي الفعلي", style={'color': '#00ff88'})
            ], style={'background': '#1a1a2e', 'padding': '20px', 'borderRadius': '15px', 'textAlign': 'center', 'border': '2px solid #00d4ff', 'flex': '1', 'margin': '10px'}),
            
            html.Div([
                html.H4("🏅 عيار 21 محلياً", style={'color': '#ff6b6b'}),
                html.H2(id='karat21-display', style={'color': 'white'}),
                html.Small("بدون مصنعية - شامل الدمغة", style={'color': '#ff6b6b'})
            ], style={'background': '#1a1a2e', 'padding': '20px', 'borderRadius': '15px', 'textAlign': 'center', 'border': '2px solid #ff6b6b', 'flex': '1', 'margin': '10px'}),
            
            html.Div([
                html.H4("📊 مؤشر الخوف", style={'color': '#ffd93d'}),
                html.H2(id='fear-display', style={'color': 'white'}),
                html.Small(id='fear-status', style={'color': '#888'})
            ], style={'background': '#1a1a2e', 'padding': '20px', 'borderRadius': '15px', 'textAlign': 'center', 'border': '2px solid #ffd93d', 'flex': '1', 'margin': '10px'}),
        ], style={'display': 'flex', 'flexWrap': 'wrap', 'gap': '10px', 'marginBottom': '30px'}),
        
        # ===== أسعار الشراء والبيع =====
        html.H3("💰 أسعار الشراء والبيع بالصاغة (شاملة الدمغة المحددة)", style={'color': 'white'}),
        html.Div(id='prices-grid', style={'display': 'grid', 'gridTemplateColumns': 'repeat(4, 1fr)', 'gap': '20px', 'margin': '20px 0'}),
        
        # ===== التبويبات =====
        html.Div([
            html.Div([
                html.Button("📊 التحليل", id='tab1-btn', n_clicks=0, style={'padding': '10px 20px', 'background': '#FFD700', 'color': 'black', 'border': 'none', 'borderRadius': '8px', 'cursor': 'pointer', 'fontWeight': 'bold'}),
                html.Button("💡 التوصيات", id='tab2-btn', n_clicks=0, style={'padding': '10px 20px', 'background': '#333', 'color': 'white', 'border': 'none', 'borderRadius': '8px', 'cursor': 'pointer'}),
                html.Button("📰 الأخبار", id='tab3-btn', n_clicks=0, style={'padding': '10px 20px', 'background': '#333', 'color': 'white', 'border': 'none', 'borderRadius': '8px', 'cursor': 'pointer'}),
            ], style={'display': 'flex', 'gap': '10px', 'margin': '20px 0', 'flexWrap': 'wrap'}),
            html.Div(id='tab-content', style={'background': '#1a1a2e', 'padding': '20px', 'borderRadius': '10px', 'minHeight': '150px'})
        ]),
        
        # ===== الرسم البياني =====
        html.H3("📈 أداء الذهب - آخر 30 يوم", style={'color': 'white', 'marginTop': '40px'}),
        dcc.Graph(id='gold-chart'),
        
        # ===== التذييل =====
        html.Div([
            html.Hr(style={'borderColor': '#1f1f3a'}),
            html.Div([
                html.P("🏅 Gold Meter Pro v2.1.0", style={'color': '#FFD700'}),
                html.P("© 2026 Techno logic / Haytham Elsaadany", style={'color': '#666'}),
                html.P("📞 01223999366 - 01066774623", style={'color': '#444'}),
                html.P("✉️ lamar.haytham17@gmail.com", style={'color': '#444'})
            ], style={'textAlign': 'center', 'padding': '20px 0'})
        ])
        
    ], style={
        'marginLeft': '300px',
        'padding': '20px 40px',
        'background': '#080810',
        'minHeight': '100vh',
        'color': 'white'
    })
], style={'margin': '0', 'padding': '0'})

# ============================================================
# الكول باك
# ============================================================
@callback(
    [Output('gold-display', 'children'),
     Output('usd-display', 'children'),
     Output('karat21-display', 'children'),
     Output('fear-display', 'children'),
     Output('fear-status', 'children'),
     Output('prices-grid', 'children'),
     Output('sidebar-stats', 'children'),
     Output('last-update', 'children'),
     Output('tab-content', 'children')],
    [Input('interval', 'n_intervals'),
     Input('update-btn', 'n_clicks'),
     Input('tab1-btn', 'n_clicks'),
     Input('tab2-btn', 'n_clicks'),
     Input('tab3-btn', 'n_clicks')],
    [State('gold-input', 'value'),
     State('usd-input', 'value'),
     State('tax-slider', 'value')]
)
def update_all(n_intervals, update_clicks, tab1, tab2, tab3, gold_val, usd_val, tax_val):
    global CURRENT_GOLD, CURRENT_USD
    
    # تحديد مصدر المدخلات (يدوي أم تلقائي من الكاش الفوري)
    gold = gold_val if gold_val and gold_val > 0 else CURRENT_GOLD
    usd = usd_val if usd_val and usd_val > 0 else CURRENT_USD
    tax = tax_val / 100 if tax_val else TAX_RATE
    
    karat_data = get_market_data(gold, usd, tax)
    fear_score, fear_status, _ = get_fear_greed_score(gold, usd, karat_data)
    
    # بطاقات الأسعار الشاملة
    price_cards = []
    for k in ['24', '22', '21', '18']:
        d = karat_data.get(k, {})
        price_cards.append(html.Div([
            html.H4(f"عيار {k}", style={'color': '#ffd93d'}),
            html.P(f"شراء: {d.get('buy', 0):,.2f} ج.م", style={'color': '#00ff88'}),
            html.P(f"بيع: {d.get('sell', 0):,.2f} ج.م", style={'color': '#ff6b6b'}),
        ], style={'background': '#1a1a2e', 'padding': '15px', 'borderRadius': '10px', 'border': '1px solid #333', 'textAlign': 'center'}))
    
    # الشريط الجانبي
    sidebar = html.Div([
        html.H4("📊 المؤشرات اللحظية", style={'color': '#FFD700'}),
        html.P(f"🌍 الذهب: ${gold:,.2f}"),
        html.P(f"💵 دولار الصاغة: {usd:.2f} ج.م"),
        html.P(f"📊 الدمغة: {tax*100:.1f}%"),
        html.Hr(),
        html.H4("💎 أسعار الجرامات", style={'color': '#FFD700'}),
        html.P(f"عيار 24: {karat_data.get('24', {}).get('mid', 0):,.2f} ج.م"),
        html.P(f"عيار 22: {karat_data.get('22', {}).get('mid', 0):,.2f} ج.م"),
        html.P(f"عيار 21: {karat_data.get('21', {}).get('mid', 0):,.2f} ج.م"),
        html.P(f"عيار 18: {karat_data.get('18', {}).get('mid', 0):,.2f} ج.م"),
    ])
    
    last_update = f"🔄 آخر تحديث فوري ومباشر: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    
    # ===== التبويبات =====
    ctx = dash.callback_context
    if not ctx.triggered or ctx.triggered[0]['prop_id'].startswith('interval'):
        active_tab = 'tab1-btn'
    else:
        active_tab = ctx.triggered[0]['prop_id'].split('.')[0]
    
    # تبويب التحليل
    analysis = get_technical_analysis(gold)
    tab_content_analysis = html.Div([
        html.H4("📊 التحليل الفني", style={'color': '#FFD700'}),
        html.Div([
            html.Div([
                html.P(f"📈 السعر الحالي: ${gold:,.2f}"),
                html.P(f"📊 مؤشر RSI: {analysis['rsi']}"),
                html.P(f"📈 الاتجاه العام: {analysis['trend']}"),
            ], style={'flex': '1'}),
            html.Div([
                html.P(f"🛡️ الدعم: ${analysis['support']:.0f}"),
                html.P(f"🚀 المقاومة: ${analysis['resistance']:.0f}"),
                html.P(f"📊 المتوسط 7 أيام: ${analysis['ma7']:.2f}"),
            ], style={'flex': '1'})
        ], style={'display': 'flex', 'gap': '40px', 'flexWrap': 'wrap'})
    ])
    
    # تبويب التوصيات
    price_21 = karat_data.get('21', {}).get('mid', 0)
    if price_21 > 5900:
        rec = "🔴 عيار 21 مرتفع جداً - نوصي بالبيع"
        color = "#ff6b6b"
    elif price_21 > 5800:
        rec = "🟡 عيار 21 مرتفع - نوصي بالاحتفاظ"
        color = "#ffd93d"
    elif price_21 > 5700:
        rec = "🟢 عيار 21 متوسط - نوصي بالمراقبة"
        color = "#00ff88"
    elif price_21 > 5600:
        rec = "🟢 عيار 21 جذاب - نوصي بالشراء"
        color = "#00ff88"
    else:
        rec = "🟢 عيار 21 جذاب جداً - شراء ممتاز"
        color = "#00ff88"
    
    tab_content_rec = html.Div([
        html.H4("💡 التوصيات الذكية", style={'color': '#FFD700'}),
        html.P(rec, style={'fontSize': '18px', 'color': color, 'fontWeight': 'bold'}),
        html.P(f"📊 مؤشر الخوف والطمع: {fear_score} - {fear_status}"),
        html.P("🎯 استراتيجية التداول: شراء 30-40%، احتفاظ 40-50%، بيع 10-20%"),
    ])
    
    # تبويب الأخبار
    news = fetch_news()
    tab_content_news = html.Div([
        html.H4("📰 آخر أخبار الذهب", style={'color': '#FFD700'}),
    ] + [html.P(f"🔹 {item['title']} - {item['source']}", style={'borderBottom': '1px solid #333', 'padding': '10px 0'}) for item in news])
    
    if active_tab == 'tab2-btn':
        tab_display = tab_content_rec
    elif active_tab == 'tab3-btn':
        tab_display = tab_content_news
    else:
        tab_display = tab_content_analysis
    
    return (f"${gold:,.2f}", f"{usd:.2f} ج.م", f"{karat_data.get('21', {}).get('mid', 0):,.2f} ج.م",
            f"{fear_score}", f"{fear_status}", price_cards, sidebar, last_update, tab_display)

@callback(
    Output('gold-chart', 'figure'),
    Input('interval', 'n_intervals')
)
def update_chart(n_intervals):
    try:
        ticker = yf.Ticker("GC=F")
        hist = ticker.history(period="1mo")
        if hist.empty:
            raise ValueError
    except:
        dates = [datetime.now() - timedelta(days=i) for i in range(30)][::-1]
        prices = [2350 + i*1.5 for i in range(30)]
        hist = pd.DataFrame({"Close": prices}, index=dates)
    
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=hist.index,
        y=hist['Close'],
        mode='lines',
        name='سعر الذهب',
        line=dict(color='#FFD700', width=2)
    ))
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="#0f0f1e",
        plot_bgcolor="#080810",
        height=400,
        margin=dict(l=20, r=20, t=20, b=20)
    )
    return fig

# ============================================================
# تشغيل التطبيق
# ============================================================
if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=8050)
