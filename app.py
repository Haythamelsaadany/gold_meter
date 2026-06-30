import streamlit as st
import requests
import psycopg2
from psycopg2.extras import RealDictCursor

# تصحيح إعدادات الصفحة لـ Streamlit لتبدو احترافية باللغة العربية
st.set_page_config(
    page_title="Gold Meter - نظام تنبيهات الذهب",
    page_icon="👑",
    layout="centered",
    initial_sidebar_state="expanded"
)

# -------------------------------------------------------------------------
# 1. دالة إرسال التنبيهات عبر تليجرام باستخدام مكتبة requests الاحترافية
# -------------------------------------------------------------------------
def send_telegram_message(chat_id, text):
    try:
        # قراءة التوكن من السيكرتس وتنظيفه من أي علامات اقتباس زائدة
        if "TELEGRAM_BOT_TOKEN" not in st.secrets:
            return False, "خطأ: لم يتم العثور على التوكن TELEGRAM_BOT_TOKEN في الـ Secrets!"
            
        token = st.secrets["TELEGRAM_BOT_TOKEN"].strip().replace('"', '').replace("'", "")
        url = f"https://api.telegram.com/bot{token}/sendMessage"
        
        # تجهيز البيانات بصيغة JSON لضمان دعم الحروف العربية والرموز التعبيرية 100%
        payload = {
            "chat_id": str(chat_id).strip(),
            "text": text,
            "parse_mode": "Markdown"
        }
        
        # إرسال الطلب مع مهلة اتصال 10 ثوانٍ لمنع تعليق السيرفر
        response = requests.post(url, json=payload, timeout=10)
        
        if response.status_code == 200:
            return True, "تم تسليم الرسالة بنجاح وبشكل فوري!"
        elif response.status_code == 403:
            return False, "خطأ تليجرام (403 Forbidden): تأكد أنك قمت بعمل Start للبوت الصحيح أولاً من حسابك، أو أن الـ Chat ID غير دقيق."
        elif response.status_code == 404:
            return False, "خطأ تليجرام (404 Not Found): التوكن الموجود في الـ Secrets غير صحيح أو البوت غير موجود."
        else:
            return False, f"خطأ من سيرفر تليجرام (كود {response.status_code}): {response.text}"
            
    except requests.exceptions.RequestException as req_err:
        return False, f"خطأ في الاتصال بالشبكة: {str(req_err)}"
    except Exception as e:
        return False, f"خطأ داخلي غير متوقع: {str(e)}"

# -------------------------------------------------------------------------
# 2. دالة الاتصال بقاعدة بيانات Supabase (PostgreSQL)
# -------------------------------------------------------------------------
def get_db_connection():
    try:
        if "postgres" not in st.secrets:
            st.error("خطأ: إعدادات [postgres] غير موجودة في الـ Secrets!")
            return None
            
        db_config = st.secrets["postgres"]
        
        # إنشاء الاتصال بالاعتماد على البيانات الممررة من السيرفر
        conn = psycopg2.connect(
            host=db_config["host"],
            port=db_config["port"],
            database=db_config["database"],
            user=db_config["user"],
            password=db_config["password"],
            connect_timeout=5
        )
        return conn
    except Exception as e:
        st.error(f"❌ فشل الاتصال بقاعدة بيانات Supabase: {str(e)}")
        return None

# -------------------------------------------------------------------------
# 3. واجهة المستخدم الرسومية لـ Streamlit
# -------------------------------------------------------------------------
st.title("👑 لوحة تحكم مؤشر الذهب وتفعيل التنبيهات")
st.write("مرحباً بك في النظام الذكي لمتابعة الأسعار وإرسال الإشعارات المباشرة لحسابك.")

st.markdown("---")

# قسم فحص حالة قاعدة البيانات
st.subheader("🗄️ حالة الاتصال بقاعدة البيانات (Supabase)")
if st.button("🔄 اختبار الاتصال بقاعدة البيانات"):
    with st.spinner("جاري الاتصال بـ Supabase..."):
        connection = get_db_connection()
        if connection:
            st.success("⚡ تم الاتصال بقاعدة البيانات بنجاح واستجابة السيرفر ممتازة!")
            connection.close()

st.markdown("---")

# قسم إعدادات وتجربة تنبيهات التليجرام
st.subheader("📢 إعدادات وتفعيل تنبيهات تليجرام")

# حقول إدخال البيانات من المستخدم
user_name = st.text_input("👤 اسم المستخدم المُراد تسجيله:", placeholder="اكتب اسمك هنا")
chat_id_input = st.text_input("🆔 رقم الـ Chat ID الخاص بك:", placeholder="مثال: 59874123")

if st.button("🚀 تفعيل التنبيه المخصّص واختبار الإرسال"):
    # التحقق من إدخال البيانات أولاً
    if not user_name.strip():
        st.warning("⚠️ من فضلك قم بكتابة اسمك أولاً قبل التفعيل.")
    elif not chat_id_input.strip():
        st.warning("⚠️ من فضلك قم بكتابة رقم الـ Chat ID الخاص بك.")
    else:
        # نص الرسالة الترحيبية والتجريبية التي ستصل على التليجرام
        alert_message = (
            f"🔔 *تنبيه من تطبيق مؤشر الذهب!*\n\n"
            f"مرحباً يا {user_name}، تم تفعيل نظام التنبيهات المخصصة لحسابك بنجاح.\n"
            f"ستصلك الأسعار والتحديثات فوراً هنا عند أي تغيير في السوق الداخلي."
        )
        
        with st.spinner("جاري معالجة الطلب وإرسال الإشارة عبر سيرفر تليجرام..."):
            success, message = send_telegram_message(chat_id_input, alert_message)
            
            if success:
                st.success(f"✅ {message}")
                st.balloons()
                
                # هنا يمكنك إدراج دالة حفظ الـ Chat ID في قاعدة البيانات تلقائياً بعد نجاح الإرسال
                conn = get_db_connection()
                if conn:
                    try:
                        with conn.cursor() as cursor:
                            # كود تجريبي لإدخال أو تحديث بيانات المستخدم (تعدل حسب هيكل جداولك)
                            # cursor.execute("INSERT INTO users (name, chat_id) VALUES (%s, %s) ON CONFLICT DO NOTHING;", (user_name, chat_id_input))
                            # conn.commit()
                            pass
                        conn.close()
                    except Exception as db_err:
                        st.info(f"تم إرسال الرسالة بنجاح، لكن تعذر التحديث في الجدول: {str(db_err)}")
            else:
                st.error(message)

st.markdown("---")
st.caption("تطبيق Gold Meter © 2026 - نظام إدارة التنبيهات الذكي.")
