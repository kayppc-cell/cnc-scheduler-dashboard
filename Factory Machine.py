import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta, time as dtime
import zoneinfo
import os
import base64
import json
from PIL import Image
import requests
import streamlit.components.v1 as components

# =========================================================
# 0. Timezone Helper (GMT+7) & Factory Shift Rules & Data Sanitizers
# =========================================================
def get_bangkok_now():
    try:
        return datetime.now(zoneinfo.ZoneInfo("Asia/Bangkok"))
    except Exception:
        return datetime.utcnow() + timedelta(hours=7)

def get_bangkok_str():
    return get_bangkok_now().strftime("%Y-%m-%d %H:%M:%S")

def safe_float(val, default=0.0):
    try:
        if pd.isna(val) or val is None or str(val).strip() in ["", "None", "nan", "NaN", "null"]:
            return float(default)
        f = float(val)
        return float(default) if pd.isna(f) else f
    except Exception:
        return float(default)

def safe_int(val, default=1):
    try:
        if pd.isna(val) or val is None or str(val).strip() in ["", "None", "nan", "NaN", "null"]:
            return int(default)
        f = float(val)
        return int(default) if pd.isna(f) else int(f)
    except Exception:
        return int(default)

def safe_str(val, default=""):
    if pd.isna(val) or val is None:
        return default
    s = str(val).strip()
    return default if s in ["", "None", "nan", "NaN", "null"] else s

def parse_flexible_datetime(dt_val):
    if pd.isna(dt_val) or dt_val is None:
        return None
    if isinstance(dt_val, (datetime, pd.Timestamp)):
        if getattr(dt_val, 'tzinfo', None) is not None:
            return dt_val.tz_localize(None)
        return dt_val
        
    s = str(dt_val).strip()
    if s in ["", "None", "nan", "NaN", "null", "-"]:
        return None
    
    current_year = get_bangkok_now().year

    if "-" in s:
        parts_dash = s.split(" ")[0].split("-")
        if len(parts_dash) == 3 and len(parts_dash[0]) == 4:
            dt_parsed = pd.to_datetime(s, errors='coerce')
            return dt_parsed.tz_localize(None) if (pd.notna(dt_parsed) and getattr(dt_parsed, 'tzinfo', None) is not None) else dt_parsed

    if "/" in s:
        date_part = s.split(" ")[0]
        time_part = s.split(" ")[1] if len(s.split(" ")) > 1 else "08:00:00"
        parts = date_part.split("/")
        
        if len(parts) == 2:
            d, m = parts[0].zfill(2), parts[1].zfill(2)
            s_fixed = f"{current_year}-{m}-{d} {time_part}"
            dt_parsed = pd.to_datetime(s_fixed, errors='coerce')
            return dt_parsed
        elif len(parts) == 3:
            d, m, y = parts[0].zfill(2), parts[1].zfill(2), parts[2]
            if len(y) == 2: y = f"20{y}"
            s_fixed = f"{y}-{m}-{d} {time_part}"
            dt_parsed = pd.to_datetime(s_fixed, errors='coerce')
            return dt_parsed

    dt_parsed = pd.to_datetime(s, errors='coerce', dayfirst=True)
    if pd.notna(dt_parsed):
        if getattr(dt_parsed, 'tzinfo', None) is not None:
            return dt_parsed.tz_localize(None)
        return dt_parsed
    return None

def get_day_working_windows(dt_date):
    weekday = dt_date.weekday()
    if weekday == 6:
        return []
    elif weekday == 5:
        return [
            (datetime.combine(dt_date, dtime(8, 0)), datetime.combine(dt_date, dtime(12, 0))),
            (datetime.combine(dt_date, dtime(13, 0)), datetime.combine(dt_date, dtime(17, 0)))
        ]
    else:
        return [
            (datetime.combine(dt_date, dtime(8, 0)), datetime.combine(dt_date, dtime(12, 0))),
            (datetime.combine(dt_date, dtime(13, 0)), datetime.combine(dt_date, dtime(20, 0)))
        ]

def get_next_valid_work_time(dt: datetime) -> datetime:
    cur_date = dt.date()
    for _ in range(14):
        windows = get_day_working_windows(cur_date)
        for w_start, w_end in windows:
            if dt < w_start:
                return w_start
            elif w_start <= dt < w_end:
                return dt
        cur_date += timedelta(days=1)
        dt = datetime.combine(cur_date, dtime(8, 0))
    return dt

def add_work_time_with_shift(start_dt: datetime, duration_hours: float):
    segments = []
    remaining_hours = duration_hours
    current_dt = get_next_valid_work_time(start_dt)

    while remaining_hours > 0.0001:
        current_dt = get_next_valid_work_time(current_dt)
        windows = get_day_working_windows(current_dt.date())
        
        active_window = None
        for w_start, w_end in windows:
            if w_start <= current_dt < w_end:
                active_window = (w_start, w_end)
                break
                
        if not active_window:
            current_dt = get_next_valid_work_time(current_dt + timedelta(minutes=10))
            continue
            
        w_start, w_end = active_window
        available_hours = (w_end - current_dt).total_seconds() / 3600.0

        if remaining_hours <= available_hours:
            seg_end = current_dt + timedelta(hours=remaining_hours)
            segments.append((current_dt, seg_end))
            current_dt = seg_end
            remaining_hours = 0.0
        else:
            segments.append((current_dt, w_end))
            remaining_hours -= available_hours
            current_dt = w_end

    return segments, current_dt

def calculate_working_hours_between(start_dt: datetime, end_dt: datetime) -> float:
    if start_dt >= end_dt:
        return 0.0
    total_sec = 0.0
    cur_d = start_dt.date()
    while cur_d <= end_dt.date():
        windows = get_day_working_windows(cur_d)
        for ws, we in windows:
            s_overlap = max(start_dt, ws)
            e_overlap = min(end_dt, we)
            if s_overlap < e_overlap:
                total_sec += (e_overlap - s_overlap).total_seconds()
        cur_d += timedelta(days=1)
    return total_sec / 3600.0

def highlight_running_deadlines(row, planned_finish_map):
    status = str(row.get("สถานะ", row.get("สถานะงาน", "")))
    p_code = str(row.get("แผนงาน", ""))
    d_code = str(row.get("ชื่อ Drawing.", ""))

    if "กำลังผลิต" in status:
        finish_dt = planned_finish_map.get((p_code, d_code))
        if finish_dt is not None and pd.notna(finish_dt):
            now = get_bangkok_now().replace(tzinfo=None)
            diff_mins = (finish_dt - now).total_seconds() / 60.0

            if diff_mins < 0:
                return ['background-color: #FECACA; color: #991B1B; font-weight: bold;'] * len(row)
            elif 0 <= diff_mins <= 60:
                return ['background-color: #FEF08A; color: #854D0E; font-weight: bold;'] * len(row)

    return [''] * len(row)

# =========================================================
# 1. การจัดการรูปภาพ (App Icon & Header Logo)
# =========================================================
icon_file = "log_ cnc_1.png"
if not os.path.exists(icon_file):
    for alt_icon in ["log_cnc_1.png", "icon.png", "logo.png"]:
        if os.path.exists(alt_icon):
            icon_file = alt_icon
            break

favicon_img = Image.open(icon_file) if os.path.exists(icon_file) else "🏭"

st.set_page_config(
    page_title="PES Production Monitor",
    page_icon=favicon_img,
    layout="wide",
    initial_sidebar_state="collapsed"
)

components.html("""
<script>
    window.parent.document.body.style.overscrollBehaviorY = 'none';
    window.parent.document.documentElement.style.overscrollBehaviorY = 'none';
</script>
""", height=0)

@st.cache_data(show_spinner=False)
def get_cached_logo():
    for fname in ["Logo_Pes.png", "logo.png", "logo.jpg", r"D:\Python\Logo_Pes.png"]:
        if os.path.exists(fname):
            with open(fname, "rb") as f:
                return base64.b64encode(f.read()).decode("utf-8")
    return None

logo_base64 = get_cached_logo()
logo_html = f'<img src="data:image/png;base64,{logo_base64}" class="header-logo" alt="Logo"/>' if logo_base64 else '<div class="header-logo-icon">🏭</div>'

# =========================================================
# 2. ตกแต่ง UI
# =========================================================
st.markdown("""
<style>
    header[data-testid="stHeader"] { display: none !important; }
    #MainMenu { visibility: hidden !important; }
    footer { visibility: hidden !important; }

    .block-container {
        padding-top: 0.8rem !important;
        padding-bottom: 2.5rem !important;
        padding-left: 0.8rem !important;
        padding-right: 0.8rem !important;
        max-width: 100% !important;
    }

    .main-header {
        background: linear-gradient(135deg, #0B192C 0%, #1E3E62 50%, #000000 100%);
        padding: 14px 20px;
        border-radius: 16px;
        color: white;
        margin-bottom: 14px;
        display: flex;
        align-items: center;
        gap: 16px;
        box-shadow: 0 6px 20px rgba(11, 25, 44, 0.35);
    }
    .header-logo {
        width: 110px;
        max-height: 75px;
        height: auto;
        object-fit: contain;
        display: block;
        flex-shrink: 0;
        background: transparent !important;
        filter: drop-shadow(0 2px 6px rgba(255,255,255,0.2));
    }
    .header-text h1 {
        color: #FFFFFF !important;
        font-size: 17px !important;
        margin: 0 !important;
        font-weight: 800 !important;
        letter-spacing: 0.3px;
        line-height: 1.3 !important;
    }
    .header-text p {
        color: #93C5FD !important;
        margin: 4px 0 0 0 !important;
        font-size: 11.5px !important;
        font-weight: 500;
    }

    .kpi-container {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
        gap: 12px;
        margin-bottom: 16px;
    }
    .kpi-card {
        padding: 14px 18px;
        border-radius: 14px;
        color: white;
        box-shadow: 0 4px 12px rgba(0,0,0,0.08);
        transition: transform 0.2s ease;
    }
    .kpi-card:hover { transform: translateY(-2px); }
    .kpi-green { background: linear-gradient(135deg, #059669 0%, #10B981 100%); }
    .kpi-blue { background: linear-gradient(135deg, #2563EB 0%, #38BDF8 100%); }
    .kpi-orange { background: linear-gradient(135deg, #EA580C 0%, #F59E0B 100%); }
    .kpi-purple { background: linear-gradient(135deg, #7C3AED 0%, #EC4899 100%); }
    
    .kpi-title { 
        font-size: 13.5px !important; 
        font-weight: 700 !important; 
        margin-bottom: 4px;
        opacity: 0.95;
    }
    .kpi-value { 
        font-size: 23px !important; 
        font-weight: 800 !important; 
    }
    .kpi-sub {
        font-size: 11.5px;
        margin-top: 4px;
        opacity: 0.9;
        font-weight: 500;
    }

    .shop-live-banner {
        padding: 12px 18px;
        border-radius: 14px;
        margin-bottom: 16px;
        display: flex;
        align-items: center;
        justify-content: space-between;
        font-size: 13.5px;
        font-weight: 700;
        box-shadow: 0 4px 14px rgba(0,0,0,0.06);
    }
    .shop-live-running {
        background: linear-gradient(135deg, #ECFDF5 0%, #D1FAE5 100%);
        border: 2px solid #10B981;
        color: #065F46;
    }
    .shop-live-hold {
        background: linear-gradient(135deg, #FFFBEB 0%, #FEF3C7 100%);
        border: 2px dashed #F59E0B;
        color: #92400E;
    }
    .shop-live-idle {
        background: #F8FAFC;
        border: 2px solid #CBD5E1;
        color: #475569;
    }

    .op-job-header {
        background: linear-gradient(145deg, #FFFFFF 0%, #F8FAFC 100%);
        padding: 16px 20px;
        border-radius: 16px;
        border: 1.5px solid #E2E8F0;
        border-left: 7px solid #4F46E5;
        margin-top: 18px;
        margin-bottom: 14px;
        box-shadow: 0 8px 24px rgba(79, 70, 229, 0.08), 0 2px 6px rgba(0, 0, 0, 0.03);
    }
    .op-job-header-running {
        border-left: 7px solid #10B981 !important;
        background: linear-gradient(145deg, #FFFFFF 0%, #F0FDF4 100%) !important;
        box-shadow: 0 8px 24px rgba(16, 185, 129, 0.15), 0 2px 6px rgba(0, 0, 0, 0.03) !important;
    }
    .op-job-header-urgent {
        border-left: 7px solid #EF4444 !important;
        background: linear-gradient(145deg, #FFFFFF 0%, #FEF2F2 100%) !important;
        box-shadow: 0 8px 24px rgba(239, 68, 68, 0.12), 0 2px 6px rgba(0, 0, 0, 0.03) !important;
    }
    .op-job-header-hold {
        border-left: 7px solid #F59E0B !important;
        background: linear-gradient(145deg, #FFFFFF 0%, #FFFBEB 100%) !important;
        box-shadow: 0 8px 24px rgba(245, 158, 11, 0.12), 0 2px 6px rgba(0, 0, 0, 0.03) !important;
    }

    .badge-chip {
        display: inline-flex;
        align-items: center;
        padding: 4px 12px;
        border-radius: 8px;
        font-weight: 700;
        font-size: 12.5px;
        margin-right: 8px;
        margin-bottom: 4px;
    }
    .badge-station { background: #EEF2FF; color: #4338CA; border: 1px solid #C7D2FE; }
    .badge-drawing { background: #F0F9FF; color: #0369A1; border: 1px solid #BAE6FD; }
    .badge-qty { background: #ECFDF5; color: #047857; border: 1px solid #A7F3D0; font-weight: 800; }
    .badge-mat { background: #FFFBEB; color: #B45309; border: 1px solid #FDE68A; }
    .badge-date { background: #F3E8FF; color: #6B21A8; border: 1px solid #E9D5FF; font-weight: 800; }
    .badge-finish-date { background: #ECFDF5; color: #065F46; border: 1px solid #A7F3D0; font-weight: 800; }
    .badge-running { background: #ECFDF5; color: #059669; border: 1.5px solid #34D399; font-weight: 800; }
    .badge-urgent { background: #FEF2F2; color: #DC2626; border: 1px solid #FECACA; font-weight: 800; }
    .badge-hold { background: #FFFBEB; color: #D97706; border: 1px solid #FCD34D; font-weight: 800; }

    .step-card {
        background: #FFFFFF;
        padding: 14px 16px;
        border-radius: 14px;
        border: 1.5px solid #E2E8F0;
        margin-bottom: 12px;
        box-shadow: 0 2px 8px rgba(0,0,0,0.02);
    }
    .step-card-running {
        border-color: #34D399 !important;
        background: linear-gradient(145deg, #FFFFFF 0%, #ECFDF5 100%) !important;
        box-shadow: 0 4px 14px rgba(16, 185, 129, 0.15) !important;
    }
    .step-card-ready {
        border-color: #FCD34D !important;
        background: linear-gradient(145deg, #FFFFFF 0%, #FFFBEB 100%) !important;
    }
    .step-card-hold {
        border-color: #F59E0B !important;
        background: linear-gradient(145deg, #FFFFFF 0%, #FFFBEB 100%) !important;
        border-style: dashed !important;
    }
    .step-card-finished {
        border-color: #A7F3D0 !important;
        background: linear-gradient(145deg, #FFFFFF 0%, #F0FDF4 100%) !important;
    }

    .batch-toolbar {
        background: #F1F5F9;
        border: 1.5px dashed #CBD5E1;
        border-radius: 12px;
        padding: 12px 16px;
        margin-bottom: 16px;
        display: flex;
        justify-content: space-between;
        align-items: center;
    }

    .schedule-info-box {
        background: #F8FAFC;
        border: 1.5px solid #E2E8F0;
        border-radius: 12px;
        padding: 12px 18px;
        margin-top: 6px;
        margin-bottom: 18px;
        display: flex;
        flex-wrap: wrap;
        gap: 16px;
        align-items: center;
        justify-content: space-between;
    }
    .schedule-pill {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        font-size: 13px;
        font-weight: 600;
        color: #334155;
    }

    div.stButton > button:disabled {
        background-color: #F1F5F9 !important;
        color: #94A3B8 !important;
        border-color: #CBD5E1 !important;
        cursor: not-allowed !important;
    }

    .tv-grid-container {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(290px, 1fr));
        gap: 14px;
        margin-top: 10px;
    }
    .tv-card {
        border-radius: 14px;
        padding: 16px 18px;
        color: #FFFFFF;
        box-shadow: 0 4px 14px rgba(0,0,0,0.12);
        display: flex;
        flex-direction: column;
        justify-content: space-between;
        min-height: 155px;
        border: 1px solid rgba(255,255,255,0.12);
    }
    .tv-card-running {
        background: linear-gradient(135deg, #065F46 0%, #059669 100%);
        border-left: 8px solid #34D399;
    }
    
    @keyframes pulse-card-warning {
        0% { box-shadow: 0 0 8px rgba(245, 158, 11, 0.4); opacity: 1; }
        50% { box-shadow: 0 0 24px rgba(245, 158, 11, 0.9); opacity: 0.85; }
        100% { box-shadow: 0 0 8px rgba(245, 158, 11, 0.4); opacity: 1; }
    }
    @keyframes pulse-card-late {
        0% { box-shadow: 0 0 10px rgba(239, 68, 68, 0.5); opacity: 1; }
        50% { box-shadow: 0 0 30px rgba(239, 68, 68, 1); opacity: 0.8; }
        100% { box-shadow: 0 0 10px rgba(239, 68, 68, 0.5); opacity: 1; }
    }
    .tv-card-warning {
        background: linear-gradient(135deg, #B45309 0%, #D97706 100%) !important;
        border-left: 8px solid #FCD34D !important;
        animation: pulse-card-warning 1.8s infinite ease-in-out !important;
    }
    .tv-card-late {
        background: linear-gradient(135deg, #991B1B 0%, #DC2626 100%) !important;
        border-left: 8px solid #F87171 !important;
        animation: pulse-card-late 1.2s infinite ease-in-out !important;
    }

    .tv-card-hold {
        background: linear-gradient(135deg, #92400E 0%, #D97706 100%);
        border-left: 8px solid #FBBF24;
    }
    .tv-card-idle {
        background: linear-gradient(135deg, #1E293B 0%, #334155 100%);
        border-left: 8px solid #64748B;
        opacity: 0.92;
    }
    .tv-pulse-dot {
        width: 10px;
        height: 10px;
        border-radius: 50%;
        background-color: #34D399;
        display: inline-block;
        box-shadow: 0 0 0 0 rgba(52, 211, 153, 0.7);
        animation: tv-pulse 1.8s infinite;
    }
    @keyframes tv-pulse {
        0% { transform: scale(0.95); box-shadow: 0 0 0 0 rgba(52, 211, 153, 0.7); }
        70% { transform: scale(1); box-shadow: 0 0 0 8px rgba(52, 211, 153, 0); }
        100% { transform: scale(0.95); box-shadow: 0 0 0 0 rgba(52, 211, 153, 0); }
    }
</style>
""", unsafe_allow_html=True)

header_content = f'''<div class="main-header">{logo_html}<div class="header-text"><h1>ระบบติดตามและบันทึกงานหน้าเครื่องแผนกผลิต</h1><p>จ.-ศ. (08:00-20:00 น.) | ส. (08:00-17:00 น.) | พักเที่ยง 12:00-13:00 น. | หยุดวันอาทิตย์</p></div></div>'''
st.markdown(header_content, unsafe_allow_html=True)

# =========================================================
# 3. กำหนดสิทธิ์และความปลอดภัย & รายชื่อเครื่องจักร
# =========================================================
ADMIN_PASSWORD = "pesadmin"
VIEWER_PASSWORD = "pes1234"

if "user_role" not in st.session_state:
    st.session_state.user_role = None

if "current_view" not in st.session_state:
    st.session_state.current_view = "👷 โหมดช่างหน้าเครื่อง"

if "active_select_all" not in st.session_state:
    st.session_state.active_select_all = False

if "finish_select_all" not in st.session_state:
    st.session_state.finish_select_all = False

if "scroll_to_bottom" not in st.session_state:
    st.session_state.scroll_to_bottom = False

if "gantt_date_range" not in st.session_state:
    st.session_state.gantt_date_range = None

MACHINE_LIST = [
    "No.1 Awea", "No.2 Awea", "No.3 Hartford", "No.4 Sanco", "No.5 Hartford",
    "No.6 Bridgeport", "No.7 Bridgeport", "No.8 Hartford", "No.9 Mikron",
    "No.10 เครื่องเจียรราบ", "No.11 เครื่องเจียรกลม",
    "No.12 มิลลิ่ง 1", "No.13 มิลลิ่ง 2", "No.14 มิลลิ่ง 3", "No.15 มิลลิ่ง 4",
    "No.16 เครื่องกลึง", "No.17 แผนกเชื่อม"
]

DEFAULT_RATES = {
    "No.1 Awea": 1200, "No.2 Awea": 1000, "No.3 Hartford": 1000, "No.4 Sanco": 1000,
    "No.5 Hartford": 1000, "No.6 Bridgeport": 600, "No.7 Bridgeport": 600, "No.8 Hartford": 600, "No.9 Mikron": 1300,
    "No.10 เครื่องเจียรราบ": 500, "No.11 เครื่องเจียรกลม": 500,
    "No.12 มิลลิ่ง 1": 400, "No.13 มิลลิ่ง 2": 400, "No.14 มิลลิ่ง 3": 400, "No.15 มิลลิ่ง 4": 400,
    "No.16 เครื่องกลึง": 400, "No.17 แผนกเชื่อม": 450
}

ASSIGN_OPTIONS = ["อัตโนมัติ (เครื่อง 3 แกนใดก็ได้)"] + MACHINE_LIST
JOB_TYPES = ["🟢 งานปกติ", "🔴 งานด่วนแทรก"]
JOB_STATUS = ["🟧 รอคิวผลิต", "🟦 กำลังผลิต", "🟨 พักงาน (รอวัสดุ)", "🟩 เสร็จสิ้นแล้ว"]

# =========================================================
# 4. ฟังก์ชันเชื่อมต่อ Supabase
# =========================================================
def get_supabase_headers():
    key = st.secrets["SUPABASE_KEY"]
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "return=representation"
    }

def insert_supabase_job(payload: dict) -> bool:
    try:
        base_url = st.secrets["SUPABASE_URL"].rstrip("/")
        endpoint = f"{base_url}/rest/v1/cnc_jobs"
        res = requests.post(endpoint, headers=get_supabase_headers(), json=payload, timeout=8)
        if res.status_code in [200, 201]:
            st.cache_data.clear()
            return True
        else:
            if "qty" in payload:
                payload_no_qty = {k: v for k, v in payload.items() if k != "qty"}
                res2 = requests.post(endpoint, headers=get_supabase_headers(), json=payload_no_qty, timeout=8)
                if res2.status_code in [200, 201]:
                    st.cache_data.clear()
                    return True
            st.error(f"⚠️ บันทึกไม่สำเร็จ Supabase ({res.status_code}): {res.text}")
            return False
    except Exception as e:
        st.error(f"⚠️ เกิดข้อผิดพลาดในการเชื่อมต่อ: {str(e)}")
        return False

def update_supabase_job(job_id: int, payload: dict) -> bool:
    try:
        base_url = st.secrets["SUPABASE_URL"].rstrip("/")
        endpoint = f"{base_url}/rest/v1/cnc_jobs?id=eq.{job_id}"
        res = requests.patch(endpoint, headers=get_supabase_headers(), json=payload, timeout=8)
        if res.status_code in [200, 204]:
            st.cache_data.clear()
            return True
        else:
            if "qty" in payload:
                payload_no_qty = {k: v for k, v in payload.items() if k != "qty"}
                res2 = requests.patch(endpoint, headers=get_supabase_headers(), json=payload_no_qty, timeout=8)
                if res2.status_code in [200, 204]:
                    st.cache_data.clear()
                    return True
            st.error(f"⚠️ อัปเดตไม่สำเร็จ Supabase ({res.status_code}): {res.text}")
            return False
    except Exception as e:
        st.error(f"⚠️ เกิดข้อผิดพลาดในการเชื่อมต่อ: {str(e)}")
        return False

def delete_supabase_job(job_id: int) -> bool:
    try:
        base_url = st.secrets["SUPABASE_URL"].rstrip("/")
        endpoint = f"{base_url}/rest/v1/cnc_jobs?id=eq.{job_id}"
        res = requests.delete(endpoint, headers=get_supabase_headers(), timeout=8)
        st.cache_data.clear()
        return res.status_code in [200, 204]
    except Exception:
        return False

def normalize_status(status_str: str) -> str:
    s = str(status_str)
    if "พักงาน" in s or "รอวัสดุ" in s:
        return "🟨 พักงาน (รอวัสดุ)"
    elif "กำลังผลิต" in s:
        return "🟦 กำลังผลิต"
    elif "เสร็จสิ้น" in s:
        return "🟩 เสร็จสิ้นแล้ว"
    else:
        return "🟧 รอคิวผลิต"

@st.cache_data(ttl=5, show_spinner=False)
def fetch_jobs_from_supabase() -> pd.DataFrame:
    try:
        base_url = st.secrets["SUPABASE_URL"].rstrip("/")
        endpoint = f"{base_url}/rest/v1/cnc_jobs?select=*&order=id.asc"
        res = requests.get(endpoint, headers=get_supabase_headers(), timeout=8)
        
        if res.status_code == 200:
            data = res.json()
            if isinstance(data, list) and len(data) > 0:
                df = pd.DataFrame(data)
                
                if "ready_at" in df.columns:
                    df["ready_at"] = df["ready_at"].apply(parse_flexible_datetime)
                if "actual_start" in df.columns:
                    df["actual_start"] = pd.to_datetime(df["actual_start"].astype(str).str.replace('T', ' ').str.split('+').str[0].str.split('Z').str[0], errors='coerce')
                if "actual_finish" in df.columns:
                    df["actual_finish"] = pd.to_datetime(df["actual_finish"].astype(str).str.replace('T', ' ').str.split('+').str[0].str.split('Z').str[0], errors='coerce')
                
                if "status" in df.columns:
                    df["status"] = df["status"].apply(normalize_status)
                
                if "qty" not in df.columns:
                    df["qty"] = 1
                else:
                    df["qty"] = pd.to_numeric(df["qty"], errors='coerce').fillna(1).astype(int)
                    
                col_map = {
                    "id": "ID", "plan_code": "แผนงาน", "drawing_name": "ชื่อ Drawing.",
                    "qty": "จำนวน", "material": "วัสดุ", "job_type": "ประเภทงาน",
                    "step_name": "ขั้นตอน (Step)", "machine_name": "เลือกเครื่องจักร",
                    "ready_at": "วัน-เวลาขึ้นงาน", "setup_mins": "Setup (น.)",
                    "basic_hrs": "Basic (น.)", "prog_hrs": "โปรแกรม (น.)",
                    "status": "สถานะงาน", "actual_start": "เริ่มจริง", "actual_finish": "เสร็จจริง"
                }
                return df.rename(columns=col_map)
        return pd.DataFrame()
    except Exception:
        return pd.DataFrame()

# =========================================================
# 5. Scheduling Engine
# =========================================================
def calculate_shop_schedule(jobs_df, default_start_datetime):
    now_dt = get_next_valid_work_time(default_start_datetime)
    m_available = {m: now_dt for m in MACHINE_LIST}
    m_last_mat = {m: None for m in MACHINE_LIST}
    m_busy_hrs = {m: 0.0 for m in MACHINE_LIST}
    
    active_mask = jobs_df["สถานะงาน"].isin(["🟧 รอคิวผลิต", "🟦 กำลังผลิต", "⏳ รอคิวผลิต", "⚙️ กำลังผลิต"])
    valid_jobs = []
    
    for j in jobs_df[active_mask].to_dict("records"):
        ready_time = j.get("วัน-เวลาขึ้นงาน")
        dt_val = parse_flexible_datetime(ready_time)
        if dt_val is None:
            continue
            
        j["ready_at"] = get_next_valid_work_time(dt_val.to_pydatetime() if isinstance(dt_val, pd.Timestamp) else dt_val)

        basic_mins = safe_float(j.get("Basic (น.)"), 0.0)
        prog_mins = safe_float(j.get("โปรแกรม (น.)"), 0.0)
        setup_mins = safe_float(j.get("Setup (น.)"), 10.0)
        
        cut_mins = basic_mins + prog_mins
        cut_hrs = (cut_mins / 60.0) if cut_mins > 0 else 0.01
        
        j["basic_mins"] = basic_mins
        j["prog_mins"] = prog_mins
        j["setup_mins"] = setup_mins
        j["cut_hrs"] = cut_hrs
            
        j["is_urgent"] = "ด่วนแทรก" in str(j.get("ประเภทงาน", ""))
        j["remain_cut_hrs"] = j["cut_hrs"]
        j["need_setup"] = "กำลังผลิต" not in str(j["สถานะงาน"])
        valid_jobs.append(j)
        
    gantt_records, summary_records = [], []
    
    while valid_jobs:
        pending_machines = set()
        for j in valid_jobs:
            target = j.get("เลือกเครื่องจักร", "")
            if target in MACHINE_LIST:
                pending_machines.add(target)
            elif target == "อัตโนมัติ (เครื่อง 3 แกนใดก็ได้)":
                for m in MACHINE_LIST[:8]:
                    pending_machines.add(m)
                        
        if not pending_machines: break
        earliest_m = min(pending_machines, key=lambda m: m_available[m])
        cur_time = get_next_valid_work_time(m_available[earliest_m])
        last_mat = m_last_mat[earliest_m]
        
        ready_candidates = [
            j for j in valid_jobs if (j.get("เลือกเครื่องจักร") == earliest_m or 
            (j.get("เลือกเครื่องจักร") == "อัตโนมัติ (เครื่อง 3 แกนใดก็ได้)" and earliest_m in MACHINE_LIST[:8])) and j["ready_at"] <= cur_time
        ]
                    
        if not ready_candidates:
            future_candidates = [
                j["ready_at"] for j in valid_jobs if (j.get("เลือกเครื่องจักร") == earliest_m or 
                (j.get("เลือกเครื่องจักร") == "อัตโนมัติ (เครื่อง 3 แกนใดก็ได้)" and earliest_m in MACHINE_LIST[:8])) and j["ready_at"] > cur_time
            ]
            if future_candidates:
                next_ready_target = get_next_valid_work_time(min(future_candidates))
                
                idle_work_hrs = calculate_working_hours_between(cur_time, next_ready_target)
                if idle_work_hrs >= 0.2:
                    gantt_records.append({
                        "ข้อความบนแท่งกราฟ": f"⏳ รอรัน {idle_work_hrs:.1f} ชม.",
                        "แผนงาน": "⏳ รอรัน (เครื่องว่าง)",
                        "ชื่อ Drawing.": "ช่วงว่างรอขึ้นงานตามกำหนด",
                        "จำนวน": "-",
                        "ขั้นตอน (Step)": "รอขึ้นงานรอบถัดไป",
                        "กิจกรรม": "⏳ รอรัน (เครื่องว่าง)",
                        "เครื่องจักร": earliest_m,
                        "วัสดุ": "-",
                        "เวลาเริ่ม": cur_time,
                        "เวลาเสร็จ": next_ready_target,
                        "ระยะเวลา": f"{idle_work_hrs:.2f} ชม."
                    })
                m_available[earliest_m] = next_ready_target
            else:
                m_available[earliest_m] = get_next_valid_work_time(cur_time + timedelta(minutes=15))
            continue
            
        urgent_pool = [j for j in ready_candidates if j["is_urgent"]]
        if urgent_pool:
            selected_job = urgent_pool[0]
        else:
            same_mat = [j for j in ready_candidates if j["วัสดุ"] == last_mat]
            selected_job = same_mat[0] if same_mat else ready_candidates[0]

        setup_mins = selected_job["setup_mins"] if selected_job["need_setup"] else 0
        setup_hrs = setup_mins / 60.0
        actual_cut_hrs = selected_job["remain_cut_hrs"]
        
        raw_step = safe_str(selected_job.get("ขั้นตอน (Step)"), "รอหน้าเครื่องระบุ")
        if raw_step in ["", "None", "nan", "รันงาน"]:
            step_raw = "รอหน้าเครื่องระบุ"
        else:
            step_raw = raw_step
            
        job_code = str(selected_job.get('แผนงาน', '-'))
        drawing_name = str(selected_job.get("ชื่อ Drawing.", "-"))
        qty_val = str(selected_job.get("จำนวน", 1))
        
        short_bar_label = f"{job_code}"
        
        setup_start = cur_time
        if setup_hrs > 0:
            setup_segments, setup_end = add_work_time_with_shift(setup_start, setup_hrs)
            for s_st, s_en in setup_segments:
                gantt_records.append({
                    "ข้อความบนแท่งกราฟ": "🔧 Setup", 
                    "แผนงาน": job_code, 
                    "ชื่อ Drawing.": drawing_name,
                    "จำนวน": qty_val, 
                    "ขั้นตอน (Step)": "Setup ตั้งเครื่อง", 
                    "กิจกรรม": "🔧 ตั้งเครื่อง / เซ็ตศูนย์",
                    "เครื่องจักร": earliest_m, 
                    "วัสดุ": selected_job.get("วัสดุ", "-"),
                    "เวลาเริ่ม": s_st, 
                    "เวลาเสร็จ": s_en, 
                    "ระยะเวลา": f"{setup_mins:.0f} นาที"
                })
            cut_start = setup_end
        else:
            cut_start = setup_start
            setup_end = setup_start

        cut_segments, cut_end = add_work_time_with_shift(cut_start, actual_cut_hrs)
        for c_st, c_en in cut_segments:
            seg_hrs = (c_en - c_st).total_seconds() / 3600.0
            gantt_records.append({
                "ข้อความบนแท่งกราฟ": short_bar_label, 
                "แผนงาน": job_code, 
                "ชื่อ Drawing.": drawing_name,
                "จำนวน": qty_val, 
                "ขั้นตอน (Step)": step_raw,
                "กิจกรรม": "🔴 งานด่วน" if selected_job["is_urgent"] else "⚙️ งานปกติ",
                "เครื่องจักร": earliest_m, 
                "วัสดุ": selected_job.get("วัสดุ", "-"),
                "เวลาเริ่ม": c_st, 
                "เวลาเสร็จ": c_en, 
                "ระยะเวลา": f"{seg_hrs:.2f} ชม."
            })
        
        total_cycle = setup_hrs + actual_cut_hrs
        summary_records.append({
            "ID": selected_job.get("ID", ""), "เครื่องจักร": earliest_m, "สถานะ": selected_job["สถานะงาน"],
            "ประเภทงาน": "🔴 งานด่วนแทรก" if selected_job["is_urgent"] else "🟢 งานปกติ",
            "แผนงาน": job_code, "ชื่อ Drawing.": drawing_name, "จำนวน": safe_int(selected_job.get("จำนวน"), 1),
            "วัสดุ": selected_job.get("วัสดุ", "-"), "ขั้นตอน (Step)": step_raw, "เวลาเริ่มจริง": setup_start,
            "เวลาเริ่ม Setup": setup_start.strftime("%d/%m %H:%M") if setup_mins > 0 else "-",
            "เวลาเริ่มขึ้นงาน": cut_start.strftime("%d/%m %H:%M"), "เวลาจบงาน": cut_end.strftime("%d/%m %H:%M"),
            "เวลาจบงาน_DT": cut_end,
            "Setup (น.)": int(setup_mins), "Basic (น.)": int(selected_job["basic_mins"]),
            "โปรแกรม (น.)": int(selected_job["prog_mins"]), "รวม (ชม.)": round(total_cycle, 2)
        })
        
        m_available[earliest_m] = cut_end
        m_last_mat[earliest_m] = selected_job["วัสดุ"]
        m_busy_hrs[earliest_m] += total_cycle
        valid_jobs.remove(selected_job)
            
    start_anchor = now_dt
    max_finish = max(m_available.values()) if summary_records else (now_dt + timedelta(hours=11))
    
    total_factory_work_hours = 0.0
    iter_date = start_anchor.date()
    while iter_date <= max_finish.date():
        w_list = get_day_working_windows(iter_date)
        for ws, we in w_list:
            total_factory_work_hours += (we - ws).total_seconds() / 3600.0
        iter_date += timedelta(days=1)
        
    total_horizon_work_hrs = max(total_factory_work_hours, 11.0)
    
    util_list = []
    for m in MACHINE_LIST:
        busy = m_busy_hrs[m]
        util_pct = min((busy / total_horizon_work_hrs) * 100.0, 100.0) if total_horizon_work_hrs > 0 else 0.0
        util_list.append({
            "เครื่องจักร": m, "ชั่วโมงทำงาน (ชม.)": round(busy, 2),
            "อัตราการใช้งาน (%)": round(util_pct, 1), "ข้อความแสดง": f"{util_pct:.1f}% ({busy:.2f} ชม.)"
        })
        
    return pd.DataFrame(gantt_records), pd.DataFrame(summary_records), pd.DataFrame(util_list), total_horizon_work_hrs

# =========================================================
# 6. เมนูเปลี่ยนโหมด (4 แท็บมาตรฐาน)
# =========================================================
nav_options = ["👷 โหมดช่างหน้าเครื่อง", "📊 แดชบอร์ดภาพรวมโรงงาน", "📑 รายงานสรุปประจำเดือน", "📺 จอทีวีกลางโรงงาน (TV Live)"]

cur_idx = nav_options.index(st.session_state.current_view) if st.session_state.current_view in nav_options else 0
selected_tab = st.radio(
    "เลือกมุมมอง:",
    nav_options,
    index=cur_idx,
    horizontal=True,
    label_visibility="collapsed"
)

if selected_tab != st.session_state.current_view:
    st.session_state.current_view = selected_tab
    st.rerun()

# ---------------------------------------------------------
# VIEW 1: หน้าจอช่างหน้าเครื่อง
# ---------------------------------------------------------
if st.session_state.current_view == "👷 โหมดช่างหน้าเครื่อง":
    st.markdown("### 📱 บันทึกสถานะงานหน้าเครื่อง / แผนกผลิต")
    
    df_all = fetch_jobs_from_supabase()
    
    c_m_sel, c_mode_sel = st.columns([2, 2])
    with c_m_sel:
        selected_m = st.selectbox("🏭 เลือกเครื่องจักร / แผนก:", MACHINE_LIST, key="op_machine_select")
    with c_mode_sel:
        run_mode = st.radio(
            "⚙️ รูปแบบการผลิต:",
            ["🔹 รันทีละคิว (Piece by Piece)", "📦 รันรวมหลายงานพร้อมกัน (Batch Processing)"],
            horizontal=True
        )

    planned_finish_map = {}
    if not df_all.empty:
        _, df_summary_plan, _, _ = calculate_shop_schedule(df_all, get_bangkok_now().replace(tzinfo=None))
        if not df_summary_plan.empty:
            for _, s_row in df_summary_plan.iterrows():
                key_pair = (str(s_row["แผนงาน"]), str(s_row["ชื่อ Drawing."]))
                f_dt = s_row.get("เวลาจบงาน_DT")
                if key_pair not in planned_finish_map or (pd.notna(f_dt) and f_dt > planned_finish_map[key_pair]):
                    planned_finish_map[key_pair] = f_dt

    if not df_all.empty:
        m_all_jobs = df_all[
            (df_all["เลือกเครื่องจักร"] == selected_m) &
            (df_all["วัน-เวลาขึ้นงาน"].notna() | df_all["สถานะงาน"].isin(["🟦 กำลังผลิต", "🟨 พักงาน (รอวัสดุ)"]))
        ].copy()
    else:
        m_all_jobs = pd.DataFrame()

    if not m_all_jobs.empty:
        running_now = m_all_jobs[m_all_jobs["สถานะงาน"].str.contains("กำลังผลิต")]
        hold_now = m_all_jobs[m_all_jobs["สถานะงาน"].str.contains("พักงาน")]
        
        if not running_now.empty:
            r_cur = running_now.iloc[0]
            st_t = r_cur.get("เริ่มจริง")
            st_txt = "-"
            elap_txt = "-"
            if pd.notna(st_t):
                st_dt = pd.to_datetime(st_t)
                st_txt = st_dt.strftime("%H:%M น.")
                elap_min = int((get_bangkok_now().replace(tzinfo=None) - st_dt).total_seconds() / 60.0)
                elap_txt = f"{elap_min} นาที ({elap_min/60.0:.1f} ชม.)"
            st.markdown(f"""
            <div class="shop-live-banner shop-live-running">
                <div style="display:flex; align-items:center; gap:8px;">
                    <span class="tv-pulse-dot"></span>
                    <span>🟢 <b>{selected_m}: กำลังรันงานอยู่</b> (เริ่ม: {st_txt} | รันแล้ว {elap_txt})</span>
                </div>
                <div style="font-size:12.5px; opacity:0.9;">
                    📌 <b>แผนงาน:</b> {r_cur.get('แผนงาน', '-')} | 📄 <b>Drawing:</b> {r_cur.get('ชื่อ Drawing.', '-')}
                </div>
            </div>
            """, unsafe_allow_html=True)
        elif not hold_now.empty:
            h_cur = hold_now.iloc[0]
            st.markdown(f"""
            <div class="shop-live-banner shop-live-hold">
                <div>🛑 <b>{selected_m}: เครื่องหยุดพักงานชั่วคราว (รอเบิกวัสดุใหม่)</b></div>
                <div style="font-size:12.5px;">📌 <b>แผนงาน:</b> {h_cur.get('แผนงาน', '-')} | 📄 <b>Drawing:</b> {h_cur.get('ชื่อ Drawing.', '-')}</div>
            </div>
            """, unsafe_allow_html=True)
        else:
            st.markdown(f"""
            <div class="shop-live-banner shop-live-idle">
                <div>⚪ <b>{selected_m}: เครื่องว่าง (IDLE)</b> — พร้อมกด Start เริ่มงานใหม่</div>
            </div>
            """, unsafe_allow_html=True)

    if not m_all_jobs.empty:
        raw_groups = m_all_jobs.groupby(["แผนงาน", "ชื่อ Drawing."], sort=False).size().reset_index()[["แผนงาน", "ชื่อ Drawing."]]
        
        group_meta = []
        for _, g_row in raw_groups.iterrows():
            p_code = g_row["แผนงาน"]
            d_code = g_row["ชื่อ Drawing."]
            steps = m_all_jobs[(m_all_jobs["แผนงาน"] == p_code) & (m_all_jobs["ชื่อ Drawing."] == d_code)]
            
            has_pending = any("เสร็จสิ้น" not in str(s) for s in steps["สถานะงาน"])
            if has_pending:
                is_running = any("กำลังผลิต" in str(s) for s in steps["สถานะงาน"])
                is_hold = any("พักงาน" in str(s) for s in steps["สถานะงาน"])
                is_urgent = any("ด่วนแทรก" in str(t) for t in steps.get("ประเภทงาน", []))
                
                valid_ready_times = steps["วัน-เวลาขึ้นงาน"].dropna()
                earliest_ready = valid_ready_times.min() if not valid_ready_times.empty else None
                min_id = steps["ID"].min()
                
                if is_hold:
                    prio = 0
                elif is_running:
                    prio = 1
                elif is_urgent:
                    prio = 2
                else:
                    prio = 3
                    
                group_meta.append({
                    "plan_code": p_code,
                    "drawing_name": d_code,
                    "priority": prio,
                    "is_running": is_running,
                    "is_hold": is_hold,
                    "is_urgent": is_urgent,
                    "ready_at": earliest_ready,
                    "min_id": min_id
                })

        sorted_groups = sorted(
            group_meta, 
            key=lambda x: (
                x["priority"], 
                x["ready_at"] if pd.notna(x["ready_at"]) else pd.Timestamp.max, 
                x["min_id"]
            )
        )

        if "Batch" in run_mode:
            st.markdown("""
            <div class="batch-toolbar">
                <div>
                    <b style="color:#1E3A8A; font-size:14.5px;">📦 แผงควบคุมการรันงานแบบกลุ่ม (Batch Processing Mode)</b><br>
                    <span style="font-size:12px; color:#64748B;">เหมาะสำหรับงานที่เซ็ตทูลครั้งเดียวแล้วรัน Step เดียวกันต่อเนื่องหลายๆ คิว</span>
                </div>
            </div>
            """, unsafe_allow_html=True)
            
            b_c1, b_c2 = st.columns(2)
            waiting_jobs = m_all_jobs[m_all_jobs["สถานะงาน"].str.contains("รอคิว")]
            running_jobs = m_all_jobs[m_all_jobs["สถานะงาน"].str.contains("กำลังผลิต")]

            with b_c1:
                if st.button(f"🚀 Start รวมทุกงานที่รอคิว ({len(waiting_jobs)} คิว)", disabled=(len(waiting_jobs) == 0), type="primary", use_container_width=True):
                    now_str = get_bangkok_str()
                    for _, r in waiting_jobs.iterrows():
                        update_supabase_job(int(r["ID"]), {"status": "🟦 กำลังผลิต", "actual_start": now_str})
                    st.toast("เริ่มจับเวลาจริงทุกคิวพร้อมกันเรียบร้อย!", icon="🚀")
                    st.rerun()

            with b_c2:
                if st.button(f"🏁 Finish รวมทุกงานที่กำลังรัน ({len(running_jobs)} คิว)", disabled=(len(running_jobs) == 0), type="secondary", use_container_width=True):
                    now_str = get_bangkok_str()
                    for _, r in running_jobs.iterrows():
                        p = {
                            "status": "🟩 เสร็จสิ้นแล้ว", 
                            "actual_finish": now_str
                        }
                        update_supabase_job(int(r["ID"]), p)
                    st.toast("บันทึกจบงานจริงทุกคิวเรียบร้อย!", icon="🏁")
                    st.rerun()

        machine_any_running = any("กำลังผลิต" in str(r.get("สถานะงาน", "")) for _, r in m_all_jobs.iterrows())
        next_available_start_found = False

        if len(sorted_groups) == 0:
            st.info(f"🎉 สถานี {selected_m} ไม่มีคิวงานค้างในระบบ")
        else:
            for group_idx, g_info in enumerate(sorted_groups, 1):
                plan_code = g_info["plan_code"]
                drawing_code = g_info["drawing_name"]
                is_urgent = g_info["is_urgent"]
                is_hold = g_info["is_hold"]
                is_running = g_info["is_running"]
                ready_at_dt = g_info["ready_at"]
                
                plan_steps = m_all_jobs[(m_all_jobs["แผนงาน"] == plan_code) & (m_all_jobs["ชื่อ Drawing."] == drawing_code)].sort_values(by="ID", ascending=True)
                first_step_info = plan_steps.iloc[0]
                mat_val = first_step_info.get('วัสดุ', '-')
                qty_val = int(first_step_info.get('จำนวน', 1) or 1)

                if pd.notna(ready_at_dt):
                    ready_display_str = ready_at_dt.strftime("%d/%m/%Y %H:%M น.")
                else:
                    ready_display_str = "ยังไม่ระบุเวลา"

                plan_finish_dt = planned_finish_map.get((str(plan_code), str(drawing_code)))
                if plan_finish_dt is not None and pd.notna(plan_finish_dt):
                    finish_plan_display_str = plan_finish_dt.strftime("%d/%m/%Y %H:%M น.")
                else:
                    if pd.notna(ready_at_dt):
                        tot_hrs = 0.0
                        for _, s_r in plan_steps.iterrows():
                            tot_hrs += (safe_float(s_r.get("Setup (น.)"), 10) + safe_float(s_r.get("Basic (น.)"), 0) + safe_float(s_r.get("โปรแกรม (น.)"), 120)) / 60.0
                        _, est_finish = add_work_time_with_shift(ready_at_dt, tot_hrs)
                        finish_plan_display_str = est_finish.strftime("%d/%m/%Y %H:%M น.")
                    else:
                        finish_plan_display_str = "-"

                if is_hold:
                    header_box_class = "op-job-header op-job-header-hold"
                    badge_gradient = "linear-gradient(135deg, #D97706 0%, #F59E0B 100%)"
                    status_badge_html = '<span class="badge-chip badge-hold">🛑 พักงาน (รอวัสดุใหม่)</span>'
                elif is_running:
                    header_box_class = "op-job-header op-job-header-running"
                    badge_gradient = "linear-gradient(135deg, #059669 0%, #10B981 100%)"
                    status_badge_html = '<span class="badge-chip badge-running"><span class="tv-pulse-dot" style="margin-right:4px;"></span> 🟦 กำลังผลิต (รันงานอยู่ ⏱️)</span>'
                elif is_urgent:
                    header_box_class = "op-job-header op-job-header-urgent"
                    badge_gradient = "linear-gradient(135deg, #DC2626 0%, #EF4444 100%)"
                    status_badge_html = '<span class="badge-chip badge-urgent">🔥 🔴 งานด่วนแทรก</span>'
                else:
                    header_box_class = "op-job-header"
                    badge_gradient = "linear-gradient(135deg, #4F46E5 0%, #7C3AED 100%)"
                    status_badge_html = ''

                card_header_html = f'''<div class="{header_box_class}"><div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px;"><div style="font-size:20px; font-weight:800; color:#1E1B4B; display:flex; align-items:center; gap:8px;"><span style="background:{badge_gradient}; color:white; padding:4px 12px; border-radius:10px; font-size:14px; box-shadow:0 3px 8px rgba(0,0,0,0.15);">คิวที่ {group_idx}</span><span>แผนงาน: {plan_code}</span></div><span class="badge-chip badge-station">🏭 {selected_m}</span></div><div style="display:flex; flex-wrap:wrap; gap:6px; align-items:center;">{status_badge_html}<span class="badge-chip badge-date">📅 <b>กำหนดขึ้นงาน:</b> {ready_display_str}</span><span class="badge-chip badge-finish-date">🏁 <b>กำหนดจบงานตามแผน:</b> {finish_plan_display_str}</span><span class="badge-chip badge-drawing">📄 <b>Drawing:</b> {drawing_code}</span><span class="badge-chip badge-qty">🔢 <b>จำนวน:</b> {qty_val} ชิ้น</span><span class="badge-chip badge-mat">🔩 <b>วัสดุ:</b> {mat_val}</span></div></div>'''
                st.markdown(card_header_html, unsafe_allow_html=True)

                st.markdown(f"**📋 รายการขั้นตอนและปุ่มควบคุม ({plan_code} | {drawing_code}):**")

                for idx, (_, step_row) in enumerate(plan_steps.iterrows(), 1):
                    s_id = int(step_row["ID"])
                    raw_s_name = str(step_row.get("ขั้นตอน (Step)", f"OP{idx*10}"))
                    s_name = raw_s_name if raw_s_name not in ["", "None", "nan", "รอหน้าเครื่องระบุ"] else f"OP{idx*10}"
                    s_status = str(step_row.get("สถานะงาน", "🟧 รอคิวผลิต"))
                    s_start = step_row.get("เริ่มจริง")
                    s_finish = step_row.get("เสร็จจริง")
                    
                    is_step_running = "กำลังผลิต" in s_status
                    is_step_hold = "พักงาน" in s_status
                    is_step_finished = "เสร็จสิ้น" in s_status
                    is_step_waiting = not is_step_running and not is_step_finished and not is_step_hold

                    if "Batch" in run_mode:
                        can_start = is_step_waiting
                    else:
                        can_start = False
                        if is_step_waiting and not machine_any_running and not next_available_start_found:
                            can_start = True
                            next_available_start_found = True

                    card_style_class = "step-card"
                    if is_step_running:
                        card_style_class += " step-card-running"
                    elif is_step_hold:
                        card_style_class += " step-card-hold"
                    elif can_start:
                        card_style_class += " step-card-ready"
                    elif is_step_finished:
                        card_style_class += " step-card-finished"

                    with st.container():
                        st.markdown(f"<div class='{card_style_class}'>", unsafe_allow_html=True)
                        
                        if is_step_finished:
                            finish_txt = pd.to_datetime(s_finish).strftime('%d/%m %H:%M') if pd.notna(s_finish) else '-'
                            st.caption(f"**Step {idx}:** <span style='color:#059669; font-weight:800;'>🟩 เสร็จสิ้นแล้ว (จบงาน: {finish_txt})</span>", unsafe_allow_html=True)
                        elif is_step_running:
                            start_txt = pd.to_datetime(s_start).strftime('%d/%m %H:%M') if pd.notna(s_start) else '-'
                            st.caption(f"**Step {idx}:** <span style='color:#059669; font-weight:800; font-size:14px;'><span class='tv-pulse-dot'></span> 🟦 กำลังผลิต (เริ่มรัน: {start_txt}) ⏱️</span>", unsafe_allow_html=True)
                        elif is_step_hold:
                            st.caption(f"**Step {idx}:** <span style='color:#D97706; font-weight:800; font-size:13.5px;'>🟨 พักงานชั่วคราว (ชิ้นงานมีปัญหา / รอเบิกวัสดุใหม่) 🛑</span>", unsafe_allow_html=True)
                        else:
                            if can_start:
                                st.caption(f"**Step {idx}:** <span style='color:#D97706; font-weight:800;'>🟧 พร้อมเริ่มงาน (Ready to Start)</span>", unsafe_allow_html=True)
                            else:
                                st.caption(f"**Step {idx}:** <span style='color:#64748B; font-weight:600;'>🔒 รอลำดับขั้นตอนก่อนหน้า</span>", unsafe_allow_html=True)

                        if not is_step_finished:
                            step_val = st.text_input(
                                f"ชื่อขั้นตอน Step {idx}:", 
                                value=s_name, 
                                placeholder="เช่น OP10, ปาดผิวเจาะรู, กลึง, เชื่อมประกอบ, เจียร", 
                                key=f"input_step_name_{s_id}"
                            )

                            if is_step_hold:
                                c_btn_save, c_btn_resume = st.columns([1.5, 4])
                                with c_btn_save:
                                    if st.button("💾 บันทึกชื่อ", key=f"btn_save_edit_{s_id}", use_container_width=True):
                                        update_payload = {"step_name": safe_str(step_val, f"OP{idx*10}")}
                                        if update_supabase_job(s_id, update_payload):
                                            st.toast(f"บันทึกชื่อ Step {idx} เรียบร้อย!", icon="💾")
                                            st.rerun()
                                with c_btn_resume:
                                    if st.button("▶️ ได้วัสดุใหม่แล้ว (Resume เริ่มรันต่อ)", key=f"btn_resume_{s_id}", type="primary", use_container_width=True):
                                        now_str = get_bangkok_str()
                                        update_payload = {
                                            "step_name": safe_str(step_val, f"OP{idx*10}"),
                                            "status": "🟦 กำลังผลิต",
                                            "actual_start": now_str
                                        }
                                        if update_supabase_job(s_id, update_payload):
                                            st.toast("เริ่มรันงานต่อเรียบร้อย!", icon="🚀")
                                            st.rerun()
                            elif is_step_running:
                                c_btn_save, c_btn_hold, c_btn_finish = st.columns([1.5, 2.5, 2])
                                with c_btn_save:
                                    if st.button("💾 บันทึกชื่อ", key=f"btn_save_edit_{s_id}", use_container_width=True):
                                        update_payload = {"step_name": safe_str(step_val, f"OP{idx*10}")}
                                        if update_supabase_job(s_id, update_payload):
                                            st.toast(f"บันทึกชื่อ Step {idx} เรียบร้อย!", icon="💾")
                                            st.rerun()
                                with c_btn_hold:
                                    if st.button("🛑 พักงาน (รอวัสดุใหม่)", key=f"btn_hold_{s_id}", use_container_width=True):
                                        update_payload = {
                                            "step_name": safe_str(step_val, f"OP{idx*10}"),
                                            "status": "🟨 พักงาน (รอวัสดุ)"
                                        }
                                        if update_supabase_job(s_id, update_payload):
                                            st.toast("พักงานเรียบร้อย สามารถรันงานอื่นต่อได้ทันที!", icon="🛑")
                                            st.rerun()
                                with c_btn_finish:
                                    if st.button("🏁 Finish (จบงานจริง)", key=f"btn_finish_step_{s_id}", type="primary", use_container_width=True):
                                        now_str = get_bangkok_str()
                                        finish_payload = {
                                            "status": "🟩 เสร็จสิ้นแล้ว",
                                            "actual_finish": now_str
                                        }
                                        if update_supabase_job(s_id, finish_payload):
                                            st.toast(f"บันทึกเวลาจบจริง {s_name} เรียบร้อย!", icon="🏁")
                                            st.rerun()
                            else:
                                c_btn_save, c_btn_start, c_btn_finish = st.columns([1.5, 2, 2])
                                with c_btn_save:
                                    if st.button("💾 บันทึกชื่อ", key=f"btn_save_edit_{s_id}", use_container_width=True):
                                        update_payload = {"step_name": safe_str(step_val, f"OP{idx*10}")}
                                        if update_supabase_job(s_id, update_payload):
                                            st.toast(f"บันทึกชื่อ Step {idx} เรียบร้อย!", icon="💾")
                                            st.rerun()
                                with c_btn_start:
                                    if can_start:
                                        if st.button("🚀 Start (เริ่มจับเวลาจริง)", key=f"btn_start_step_{s_id}", type="primary", use_container_width=True):
                                            now_str = get_bangkok_str()
                                            update_payload = {
                                                "step_name": safe_str(step_val, f"OP{idx*10}"),
                                                "status": "🟦 กำลังผลิต",
                                                "actual_start": now_str
                                            }
                                            if update_supabase_job(s_id, update_payload):
                                                st.toast(f"เริ่มผลิตและบันทึกเวลาเริ่มจริงแล้ว!", icon="🚀")
                                                st.rerun()
                                    else:
                                        st.button("🚀 Start", key=f"btn_start_disabled_{s_id}", disabled=True, use_container_width=True)
                                with c_btn_finish:
                                    st.button("🏁 Finish", key=f"btn_finish_disabled_{s_id}", disabled=True, use_container_width=True)

                        else:
                            st.markdown(f"**ขั้นตอน:** {s_name}")
                            c_btn_done, c_btn_edit_done = st.columns([2, 2])
                            with c_btn_done:
                                st.button("✅ Finish แล้ว", key=f"btn_finished_done_{s_id}", disabled=True, use_container_width=True)
                            
                            with c_btn_edit_done:
                                with st.popover("✏️ แก้ไขชื่อขั้นตอน"):
                                    re_step = st.text_input("แก้ชื่อขั้นตอน:", value=s_name, key=f"re_name_{s_id}")
                                    if st.button("💾 บันทึกทับชื่อ", key=f"btn_re_save_{s_id}", type="primary", use_container_width=True):
                                        if update_supabase_job(s_id, {"step_name": re_step.strip()}):
                                            st.toast("อัปเดตชื่อ Step สำเร็จ!", icon="💾")
                                            st.rerun()

                    st.markdown("</div>", unsafe_allow_html=True)

                next_step_num = len(plan_steps) + 1
                default_next_step_label = f"OP{next_step_num*10}"
                
                with st.expander(f"➕ เพิ่ม Step ถัดไปสำหรับ {plan_code} ({drawing_code})", expanded=False):
                    new_step_input = st.text_input("ชื่อ Step ถัดไป:", value=default_next_step_label, placeholder="เช่น OP20, กลึง, เจียร, เชื่อม", key=f"new_step_name_input_{plan_code}_{drawing_code}_{group_idx}")

                    if st.button(f"➕ บันทึกเพิ่ม Step {next_step_num}", key=f"btn_add_step_{plan_code}_{drawing_code}_{group_idx}", type="secondary", use_container_width=True):
                        now_str = get_bangkok_str()
                        
                        base_setup = safe_float(first_step_info.get("Setup (น.)"), 10.0)
                        base_basic = safe_float(first_step_info.get("Basic (น.)"), 0.0)
                        base_prog = safe_float(first_step_info.get("โปรแกรม (น.)"), 120.0)
                        
                        new_payload = {
                            "plan_code": str(plan_code),
                            "drawing_name": str(drawing_code),
                            "qty": int(first_step_info.get("จำนวน", 1) or 1),
                            "material": str(first_step_info.get("วัสดุ", "SS400")),
                            "job_type": str(first_step_info.get("ประเภทงาน", "🟢 งานปกติ")),
                            "step_name": new_step_input.strip() if new_step_input.strip() != "" else default_next_step_label,
                            "machine_name": selected_m,
                            "ready_at": now_str,
                            "setup_mins": base_setup,
                            "basic_hrs": base_basic,
                            "prog_hrs": base_prog,
                            "status": "🟧 รอคิวผลิต"
                        }
                        if insert_supabase_job(new_payload):
                            st.cache_data.clear()
                            st.toast(f"เพิ่มขั้นตอน {new_step_input} เรียบร้อยแล้ว!", icon="🚀")
                            st.rerun()
                
                st.write("")

# ---------------------------------------------------------
# VIEW 2: Dashboard ภาพรวมโรงงาน
# ---------------------------------------------------------
elif st.session_state.current_view == "📊 แดชบอร์ดภาพรวมโรงงาน":
    if st.session_state.user_role is None:
        st.subheader("🔒 ยืนยันตัวตนสำหรับเข้าใช้งานแดชบอร์ดภาพรวมโรงงาน")
        st.info("กรุณากรอกรหัสผ่านเพื่อเข้าใช้งาน:\n* **ผู้บริหาร/วางแผน (แก้ไขได้):** รหัสผ่านระดับ Admin\n* **เข้าชมทั่วไป (ดูอย่างเดียว):** รหัสผ่าน `pes1234`")
        col_pwd, col_btn = st.columns([3, 1])
        with col_pwd:
            input_pwd = st.text_input("รหัสผ่าน (Password):", type="password")
        with col_btn:
            st.write("")
            st.write("")
            if st.button("🔓 เข้าสู่ระบบ", type="primary", use_container_width=True):
                if input_pwd == ADMIN_PASSWORD:
                    st.session_state.user_role = "admin"
                    st.rerun()
                elif input_pwd == VIEWER_PASSWORD:
                    st.session_state.user_role = "viewer"
                    st.rerun()
                else:
                    st.error("รหัสผ่านไม่ถูกต้อง")
    else:
        is_admin = (st.session_state.user_role == "admin")

        c_head, c_logout = st.columns([8, 2])
        with c_head:
            if is_admin:
                st.subheader("📊 แดชบอร์ดภาพรวมโรงงานและการคำนวณต้นทุน 👑 (โหมดผู้บริหาร - แก้ไขได้)")
            else:
                st.subheader("📊 แดชบอร์ดภาพรวมโรงงานและการคำนวณต้นทุน 👁️ (โหมดเข้าชมทั่วไป - ดูอย่างเดียว)")
        with c_logout:
            if st.button("🚪 ออกจากระบบ", use_container_width=True):
                st.session_state.user_role = None
                st.rerun()

        df_db = fetch_jobs_from_supabase()

        if is_admin:
            with st.expander("➕ สั่งผลิตงานใหม่เข้าระบบ (Add New Job)", expanded=False):
                with st.form("form_add_new_job_main", clear_on_submit=True):
                    f_c1, f_c2, f_c_qty, f_c3 = st.columns([1.5, 2.5, 1, 1.2])
                    with f_c1:
                        new_f_plan = st.text_input("รหัสแผนงาน (Plan No.):", placeholder="เช่น 26-105")
                    with f_c2:
                        new_f_draw = st.text_input("ชื่อ Drawing:", placeholder="เช่น P26-PES-105-001-Unit10")
                    with f_c_qty:
                        new_f_qty = st.number_input("จำนวน:", min_value=1, max_value=10000, value=1, step=1)
                    with f_c3:
                        new_f_mat = st.text_input("วัสดุ:", value="SS400")

                    f_c4, f_c5, f_c6 = st.columns([1.5, 2, 2])
                    with f_c4:
                        new_f_type = st.selectbox("ประเภทงาน:", JOB_TYPES)
                    with f_c5:
                        st.text_input("ขั้นตอน (Step):", value="รอหน้าเครื่องระบุ", disabled=True, help="ช่องนี้ถูกล็อกไว้ ให้ช่างหน้าเครื่องเป็นผู้ระบุชื่อขั้นตอนจริง")
                    with f_c6:
                        new_f_machine = st.selectbox("เลือกเครื่องจักร / แผนก:", MACHINE_LIST)

                    f_c7, f_c8, f_c9 = st.columns([1.5, 1.5, 1.5])
                    with f_c7:
                        new_f_setup = st.number_input("เวลาตั้งเครื่อง Setup (นาที):", min_value=0, max_value=720, value=10, step=5)
                    with f_c8:
                        new_f_basic = st.number_input("Basic Machine (นาที):", min_value=0, max_value=6000, value=0, step=5)
                    with f_c9:
                        new_f_prog = st.number_input("รันโปรแกรม/เวลาทำงานตามแผน (นาที):", min_value=0, max_value=12000, value=120, step=10)

                    if st.form_submit_button("🚀 บันทึกสั่งผลิตใหม่เข้าสู่ระบบ", type="primary", use_container_width=True):
                        if new_f_plan.strip() != "":
                            payload = {
                                "plan_code": new_f_plan.strip(),
                                "drawing_name": new_f_draw.strip(),
                                "qty": int(new_f_qty),
                                "material": new_f_mat.strip(),
                                "job_type": new_f_type,
                                "step_name": "รอหน้าเครื่องระบุ",
                                "machine_name": new_f_machine,
                                "ready_at": get_bangkok_str(),
                                "setup_mins": float(new_f_setup),
                                "basic_hrs": float(new_f_basic),
                                "prog_hrs": float(new_f_prog),
                                "status": "🟧 รอคิวผลิต"
                            }
                            if insert_supabase_job(payload):
                                st.cache_data.clear()
                                st.success(f"เพิ่มแผนงาน {new_f_plan} เข้าสู่ระบบสำเร็จ!")
                                st.rerun()
                        else:
                            st.error("กรุณาระบุรหัสแผนงาน")

        if not df_db.empty:
            calc_df = df_db.copy()
            calc_df["Setup (น.)"] = pd.to_numeric(calc_df["Setup (น.)"], errors='coerce').fillna(10.0)
            calc_df["Basic (น.)"] = pd.to_numeric(calc_df["Basic (น.)"], errors='coerce').fillna(0.0)
            calc_df["โปรแกรม (น.)"] = pd.to_numeric(calc_df["โปรแกรม (น.)"], errors='coerce').fillna(0.0)
            calc_df["รวม (ชม.)"] = ((calc_df["Setup (น.)"] + calc_df["Basic (น.)"] + calc_df["โปรแกรม (น.)"]) / 60.0).round(2)

            st.markdown("### 🎯 แผงสรุปภาพรวมและจุดวิกฤตการผลิต (Executive Overview)")
            
            ov_col1, ov_col2 = st.columns([1.2, 1.8])

            with ov_col1:
                status_counts = calc_df["สถานะงาน"].value_counts().reset_index()
                status_counts.columns = ["สถานะ", "จำนวน"]
                donut_color_map = {
                    "🟩 เสร็จสิ้นแล้ว": "#10B981",
                    "🟦 กำลังผลิต": "#2563EB",
                    "🟨 พักงาน (รอวัสดุ)": "#F59E0B",
                    "🟧 รอคิวผลิต": "#94A3B8"
                }
                fig_donut = px.pie(
                    status_counts, 
                    values="จำนวน", 
                    names="สถานะ", 
                    hole=0.55,
                    color="สถานะ",
                    color_discrete_map=donut_color_map,
                    title="📊 สัดส่วนสถานะงานทั้งหมดในระบบ"
                )
                fig_donut.update_traces(textposition='inside', textinfo='percent+value')
                fig_donut.update_layout(
                    height=260, 
                    margin=dict(l=10, r=10, t=35, b=10),
                    legend=dict(orientation="h", yanchor="bottom", y=-0.25, xanchor="center", x=0.5),
                    plot_bgcolor="#FFFFFF", paper_bgcolor="#FFFFFF"
                )
                st.plotly_chart(fig_donut, use_container_width=True)

            with ov_col2:
                st.markdown("**⚠️ 3 อันดับสถานีคอขวดสูงสุด (คิวงานค้างรอนานที่สุด):**")
                waiting_sub = calc_df[calc_df["สถานะงาน"] == "🟧 รอคิวผลิต"]
                if not waiting_sub.empty:
                    m_load = waiting_sub.groupby("เลือกเครื่องจักร").agg(
                        คิวรอ=('ID', 'count'),
                        ชั่วโมงรวม=('รวม (ชม.)', 'sum')
                    ).reset_index().sort_values(by="คิวรอ", ascending=False).head(3)

                    bn_cols = st.columns(3)
                    for idx_b, (_, b_row) in enumerate(m_load.iterrows()):
                        with bn_cols[idx_b]:
                            st.markdown(f"""
                            <div style="background:#FEF2F2; border:1.5px solid #FECACA; border-left:5px solid #DC2626; border-radius:10px; padding:10px 14px;">
                                <div style="font-size:11px; font-weight:bold; color:#991B1B;">อันดับ {idx_b+1} งานค้างสูงสุด</div>
                                <div style="font-size:14px; font-weight:800; color:#1E293B; margin:2px 0;">{b_row['เลือกเครื่องจักร']}</div>
                                <div style="font-size:12px; color:#475569;">คิวรอ: <b style="color:#DC2626;">{b_row['คิวรอ']} งาน</b> ({b_row['ชั่วโมงรวม']:.1f} ชม.)</div>
                            </div>
                            """, unsafe_allow_html=True)
                else:
                    st.success("🎉 ทุกสถานีไม่มีคิวงานคั่งค้าง")

                st.write("")
                hold_sub = calc_df[calc_df["สถานะงาน"] == "🟨 พักงาน (รอวัสดุ)"]
                total_hold_count = len(hold_sub)
                total_hold_hrs = hold_sub["รวม (ชม.)"].sum()
                rate_map_quick = dict(zip(st.session_state.get("machine_rates", pd.DataFrame([{"เครื่องจักร": m, "เรตราคา (บาท/ชม.)": DEFAULT_RATES.get(m, 500)} for m in MACHINE_LIST]))["เครื่องจักร"], st.session_state.get("machine_rates", pd.DataFrame([{"เครื่องจักร": m, "เรตราคา (บาท/ชม.)": DEFAULT_RATES.get(m, 500)} for m in MACHINE_LIST]))["เรตราคา (บาท/ชม.)"]))
                total_hold_val = sum([r.get("รวม (ชม.)", 0.0) * rate_map_quick.get(r.get("เลือกเครื่องจักร"), 500) for _, r in hold_sub.iterrows()])

                st.markdown(f"""
                <div style="background:#FFFBEB; border:1.5px dashed #F59E0B; border-radius:10px; padding:10px 16px; display:flex; justify-content:space-between; align-items:center;">
                    <div>
                        <span style="font-size:13px; font-weight:800; color:#B45309;">🛑 เวลาและมูลค่าสูญเปล่าสะสมจากงานที่พักไว้ (Downtime Loss):</span><br>
                        <span style="font-size:11.5px; color:#78350F;">มีงานติดปัญหาชะงักรอเบิกวัสดุ <b>{total_hold_count} งาน</b></span>
                    </div>
                    <div style="text-align:right;">
                        <span style="font-size:18px; font-weight:900; color:#D97706;">{total_hold_hrs:.1f} ชม.</span><br>
                        <span style="font-size:12px; font-weight:700; color:#B45309;">({total_hold_val:,.2f} ฿)</span>
                    </div>
                </div>
                """, unsafe_allow_html=True)

            with st.expander("📈 ตารางติดตามความคืบหน้าราย Drawing (Drawing Multi-Step Progress Tracker)", expanded=False):
                drawing_progress_list = []
                for (p_c, d_c), g_data in calc_df.groupby(["แผนงาน", "ชื่อ Drawing."]):
                    total_steps = len(g_data)
                    fin_steps = len(g_data[g_data["สถานะงาน"] == "🟩 เสร็จสิ้นแล้ว"])
                    pct = int((fin_steps / total_steps * 100)) if total_steps > 0 else 0
                    
                    cur_run = g_data[g_data["สถานะงาน"] == "🟦 กำลังผลิต"]
                    cur_hold = g_data[g_data["สถานะงาน"] == "🟨 พักงาน (รอวัสดุ)"]
                    if not cur_run.empty:
                        stage = f"🟦 กำลังรันที่ {cur_run.iloc[0]['เลือกเครื่องจักร']} ({cur_run.iloc[0]['ขั้นตอน (Step)']})"
                    elif not cur_hold.empty:
                        stage = f"🛑 พักงานที่ {cur_hold.iloc[0]['เลือกเครื่องจักร']} (รอวัสดุ)"
                    elif fin_steps == total_steps:
                        stage = "🟩 ผลิตเสร็จครบทุก Step แล้ว"
                    else:
                        first_wait = g_data[g_data["สถานะงาน"] == "🟧 รอคิวผลิต"].iloc[0]
                        stage = f"🟧 รอคิวที่ {first_wait['เลือกเครื่องจักร']}"

                    drawing_progress_list.append({
                        "แผนงาน": p_c,
                        "ชื่อ Drawing.": d_c,
                        "จำนวน (ชิ้น)": int(g_data.iloc[0].get("จำนวน", 1)),
                        "ความคืบหน้า (%)": pct,
                        "ขั้นตอน (เสร็จ/ทั้งหมด)": f"{fin_steps}/{total_steps} Step",
                        "สถานะและสถานีปัจจุบัน": stage
                    })
                
                df_dp = pd.DataFrame(drawing_progress_list).sort_values(by=["ความคืบหน้า (%)", "แผนงาน"], ascending=[False, True])
                st.dataframe(
                    df_dp,
                    column_config={
                        "แผนงาน": st.column_config.TextColumn("แผนงาน", width=90),
                        "ชื่อ Drawing.": st.column_config.TextColumn("ชื่อ Drawing.", width=200),
                        "จำนวน (ชิ้น)": st.column_config.NumberColumn("จำนวน", width=70),
                        "ความคืบหน้า (%)": st.column_config.ProgressColumn("ความคืบหน้า", width=150, min_value=0, max_value=100, format="%d%%"),
                        "ขั้นตอน (เสร็จ/ทั้งหมด)": st.column_config.TextColumn("สเต็ปงาน", width=110),
                        "สถานะและสถานีปัจจุบัน": st.column_config.TextColumn("สถานะและสถานีปัจจุบัน", width=250),
                    },
                    hide_index=True,
                    use_container_width=True
                )

            st.divider()

            column_order = [
                "ID", "แผนงาน", "ชื่อ Drawing.", "จำนวน", "วัสดุ", "ประเภทงาน", "ขั้นตอน (Step)",
                "เลือกเครื่องจักร", "วัน-เวลาขึ้นงาน", "Setup (น.)",
                "Basic (น.)", "โปรแกรม (น.)", "รวม (ชม.)", "สถานะงาน",
            ]
            calc_df = calc_df[[c for c in column_order if c in calc_df.columns]]

            active_jobs_editor_df = calc_df[
                calc_df["สถานะงาน"].isin(["🟧 รอคิวผลิต", "🟦 กำลังผลิต", "🟨 พักงาน (รอวัสดุ)", "⏳ รอคิวผลิต", "⚙️ กำลังผลิต"])
            ].sort_values(by="ID", ascending=True).copy().reset_index(drop=True)
            
            for idx_row in active_jobs_editor_df.index:
                row_status = str(active_jobs_editor_df.at[idx_row, "สถานะงาน"])
                row_step = str(active_jobs_editor_df.at[idx_row, "ขั้นตอน (Step)"])
                if "รอคิวผลิต" in row_status and (row_step in ["", "None", "nan", "OP10", "OP20", "OP30", "OP40", "OP50", "(รอช่างหน้าเครื่องระบุ)", "รันงาน"]):
                    active_jobs_editor_df.at[idx_row, "ขั้นตอน (Step)"] = "รอหน้าเครื่องระบุ"

            active_jobs_editor_df["วัน-เวลาขึ้นงาน"] = active_jobs_editor_df["วัน-เวลาขึ้นงาน"].apply(
                lambda x: x.strftime("%d/%m/%Y %H:%M") if pd.notna(x) else ""
            )

            if "ลบ" not in active_jobs_editor_df.columns:
                active_jobs_editor_df["ลบ"] = st.session_state.active_select_all
            else:
                if st.session_state.active_select_all:
                    active_jobs_editor_df["ลบ"] = True

            with st.expander("📝 รายการสั่งผลิตในระบบ (ตารางแก้ไข/เพิ่มแถวข้อมูล)" if is_admin else "📝 รายการสั่งผลิตในระบบ (ตารางแสดงข้อมูล)", expanded=True):
                if is_admin:
                    st.markdown("**📌 เครื่องมือจัดการตาราง:**")
                    tool_col1, tool_col2, tool_search = st.columns([2.5, 3.5, 4])
                    
                    with tool_col1:
                        btn_c1, btn_c2 = st.columns(2)
                        with btn_c1:
                            if st.button("✅ เลือกหมด", use_container_width=True):
                                st.session_state.active_select_all = True
                                st.rerun()
                        with btn_c2:
                            if st.button("❌ ยกเลิก", use_container_width=True):
                                st.session_state.active_select_all = False
                                st.rerun()

                    with tool_col2:
                        with st.popover("➕ แทรกแถวใหม่ใต้รายการที่เลือก"):
                            if not active_jobs_editor_df.empty:
                                row_choices = [f"แถวที่ {i+1}: {r['แผนงาน']} - {r['ชื่อ Drawing.']}" for i, r in active_jobs_editor_df.iterrows()]
                                selected_target_idx = st.selectbox("เลือกแทรกใต้รายการ:", range(len(row_choices)), format_func=lambda x: row_choices[x])
                                target_row_data = active_jobs_editor_df.iloc[selected_target_idx]
                                
                                ins_qty = st.number_input("จำนวน:", min_value=1, value=int(target_row_data.get("จำนวน", 1) or 1), step=1)
                                ins_setup = st.number_input("Setup (น.):", value=10, step=5)
                                ins_basic = st.number_input("Basic (น.):", value=0, step=5)
                                ins_prog = st.number_input("โปรแกรม (น.):", value=120, step=10)
                                
                                if st.button("🚀 ยืนยันการแทรกข้อมูล", type="primary", use_container_width=True):
                                    ins_payload = {
                                        "plan_code": str(target_row_data["แผนงาน"]),
                                        "drawing_name": str(target_row_data["ชื่อ Drawing."]),
                                        "qty": int(ins_qty),
                                        "material": str(target_row_data["วัสดุ"]),
                                        "job_type": str(target_row_data["ประเภทงาน"]),
                                        "step_name": "รอหน้าเครื่องระบุ",
                                        "machine_name": str(target_row_data["เลือกเครื่องจักร"]),
                                        "ready_at": get_bangkok_str(),
                                        "setup_mins": float(ins_setup),
                                        "basic_hrs": float(ins_basic),
                                        "prog_hrs": float(ins_prog),
                                        "status": "🟧 รอคิวผลิต"
                                    }
                                    if insert_supabase_job(ins_payload):
                                        st.cache_data.clear()
                                        st.session_state.scroll_to_bottom = True
                                        st.toast("แทรกแถวใหม่เข้าระบบสำเร็จ!", icon="🚀")
                                        st.rerun()

                    with tool_search:
                        search_query_editor = st.text_input(
                            "🔍 ค้นหาในตารางสั่งผลิต (แผนงาน, Drawing, วัสดุ, เครื่องจักร, สถานะ):",
                            placeholder="พิมพ์เพื่อกรองข้อมูล เช่น SS400, No.1, รอคิวผลิต, กำลังผลิต...",
                            key="search_active_editor_input"
                        )

                    with st.expander("🛠️ เครื่องมือกู้คืนข้อมูล (เวลาแผน & วันขึ้นงานที่เพี้ยน)", expanded=False):
                        st.caption("เลือกเครื่องมือกู้คืนข้อมูลเฉพาะรายการที่ยังค้างอยู่ในคิว (ไม่กระทบงานที่ Finish แล้ว)")
                        tab_rec1, tab_rec2 = st.tabs(["⏱️ กู้คืนชั่วโมงทำงาน (Setup/โปรแกรม)", "📅 กู้คืนวัน-เวลาขึ้นงาน (Ready At)"])
                        
                        with tab_rec1:
                            c_rec_set, c_rec_prog, c_rec_btn = st.columns([2, 2, 2])
                            with c_rec_set:
                                rec_setup_val = st.number_input("Setup เริ่มต้น (นาที):", value=10, step=5, key="rec_setup_input")
                            with c_rec_prog:
                                rec_prog_val = st.number_input("โปรแกรมเริ่มต้น (นาที):", value=120, step=10, key="rec_prog_input")
                            with c_rec_btn:
                                st.write("")
                                st.write("")
                                if st.button("⚡ กู้คืนชั่วโมงทำงาน", type="primary", use_container_width=True, key="btn_recover_pending_jobs"):
                                    recovered_count = 0
                                    pending_mask = df_db["สถานะงาน"].isin(["🟧 รอคิวผลิต", "🟦 กำลังผลิต", "🟨 พักงาน (รอวัสดุ)"]) & (df_db["โปรแกรม (น.)"] <= 5)
                                    for _, r in df_db[pending_mask].iterrows():
                                        update_supabase_job(int(r["ID"]), {
                                            "setup_mins": float(rec_setup_val),
                                            "prog_hrs": float(rec_prog_val)
                                        })
                                        recovered_count += 1
                                    st.cache_data.clear()
                                    st.toast(f"กู้คืนเวลาทำงานสำเร็จ {recovered_count} รายการ!", icon="⚡")
                                    st.rerun()

                        with tab_rec2:
                            st.markdown("**ดึงวัน-เวลาขึ้นงานจาก Step แรกของแต่ละ Drawing กลับมาใส่อัตโนมัติ:**")
                            if st.button("🔄 กู้คืนวัน-เวลาขึ้นงาน (Sync ตาม Step 1)", type="secondary", use_container_width=True, key="btn_sync_ready_dates"):
                                sync_count = 0
                                base_ready_map = {}
                                for _, r in df_db.sort_values(by="ID", ascending=True).iterrows():
                                    key = (str(r["แผนงาน"]), str(r["ชื่อ Drawing."]))
                                    r_dt = parse_flexible_datetime(r.get("วัน-เวลาขึ้นงาน"))
                                    if key not in base_ready_map and r_dt is not None:
                                        base_ready_map[key] = r_dt.strftime("%Y-%m-%d %H:%M:%S")

                                pending_jobs = df_db[df_db["สถานะงาน"].isin(["🟧 รอคิวผลิต", "🟦 กำลังผลิต", "🟨 พักงาน (รอวัสดุ)"])]
                                for _, r in pending_jobs.iterrows():
                                    key = (str(r["แผนงาน"]), str(r["ชื่อ Drawing."]))
                                    target_ready_str = base_ready_map.get(key)
                                    if target_ready_str:
                                        update_supabase_job(int(r["ID"]), {"ready_at": target_ready_str})
                                        sync_count += 1

                                st.cache_data.clear()
                                st.toast(f"กู้คืนวัน-เวลาขึ้นงานสำเร็จ {sync_count} รายการ!", icon="📅")
                                st.rerun()
                else:
                    search_query_editor = st.text_input(
                        "🔍 ค้นหาในตารางสั่งผลิต (แผนงาน, Drawing, วัสดุ, เครื่องจักร, สถานะ):",
                        placeholder="พิมพ์เพื่อกรองข้อมูล เช่น SS400, No.1, รอคิวผลิต, กำลังผลิต...",
                        key="search_active_editor_input_viewer"
                    )

                if search_query_editor.strip() != "":
                    q = search_query_editor.strip().lower()
                    display_editor_df = active_jobs_editor_df[
                        active_jobs_editor_df["แผนงาน"].astype(str).str.lower().str.contains(q) |
                        active_jobs_editor_df["ชื่อ Drawing."].astype(str).str.lower().str.contains(q) |
                        active_jobs_editor_df["วัสดุ"].astype(str).str.lower().str.contains(q) |
                        active_jobs_editor_df["เลือกเครื่องจักร"].astype(str).str.lower().str.contains(q) |
                        active_jobs_editor_df["สถานะงาน"].astype(str).str.lower().str.contains(q)
                    ].copy().reset_index(drop=True)
                else:
                    display_editor_df = active_jobs_editor_df.copy().reset_index(drop=True)

                if is_admin:
                    edited_jobs = st.data_editor(
                        display_editor_df,
                        key="editor_cnc_jobs_grid_main",
                        num_rows="dynamic",
                        column_order=[
                            "แผนงาน", "ชื่อ Drawing.", "จำนวน", "วัสดุ", "ประเภทงาน", "ขั้นตอน (Step)",
                            "เลือกเครื่องจักร", "วัน-เวลาขึ้นงาน", "Setup (น.)",
                            "Basic (น.)", "โปรแกรม (น.)", "รวม (ชม.)", "สถานะงาน", "ลบ"
                        ],
                        column_config={
                            "ID": None,
                            "แผนงาน": st.column_config.TextColumn("แผนงาน", width=85),
                            "ชื่อ Drawing.": st.column_config.TextColumn("ชื่อ Drawing.", width=180),
                            "จำนวน": st.column_config.NumberColumn("จำนวน", width=65, min_value=1, max_value=10000, step=1, format="%d", default=1),
                            "วัสดุ": st.column_config.TextColumn("วัสดุ", width=75, default="SS400"),
                            "ประเภทงาน": st.column_config.SelectboxColumn("ประเภทงาน", width=125, options=JOB_TYPES, default="🟢 งานปกติ"),
                            "ขั้นตอน (Step)": st.column_config.TextColumn("ขั้นตอน (Step)", width=130, disabled=True, default="รอหน้าเครื่องระบุ"),
                            "เลือกเครื่องจักร": st.column_config.SelectboxColumn("เลือกเครื่องจักร", width=160, options=ASSIGN_OPTIONS, default="No.1 Awea"),
                            "วัน-เวลาขึ้นงาน": st.column_config.TextColumn(
                                "วัน-เวลาขึ้นงาน", 
                                width=165,
                                help="พิมพ์วันขึ้นก่อนเสมอ เช่น 01/09/2026 10:50 หรือ 01/09 10:50"
                            ),
                            "Setup (น.)": st.column_config.NumberColumn("Setup (น.)", width=85, min_value=0, max_value=720, step=5, format="%d", default=10),
                            "Basic (น.)": st.column_config.NumberColumn("Basic (น.)", width=85, min_value=0, max_value=6000, step=5, format="%d", default=0),
                            "โปรแกรม (น.)": st.column_config.NumberColumn("โปรแกรม (น.)", width=100, min_value=0, max_value=12000, step=10, format="%d", default=120),
                            "รวม (ชม.)": st.column_config.NumberColumn("รวม (ชม.)", width=85, format="%.2f", disabled=True),
                            "สถานะงาน": st.column_config.SelectboxColumn("สถานะงาน", width=145, options=JOB_STATUS, default="🟧 รอคิวผลิต"),
                            "ลบ": st.column_config.CheckboxColumn("🗑️", width=55, default=False),
                        },
                        hide_index=True,
                        use_container_width=True
                    )
                else:
                    edited_jobs = display_editor_df.copy()
                    st.dataframe(
                        display_editor_df[[c for c in display_editor_df.columns if c not in ["ID", "ลบ"]]],
                        column_config={
                            "แผนงาน": st.column_config.TextColumn("แผนงาน", width=85),
                            "ชื่อ Drawing.": st.column_config.TextColumn("ชื่อ Drawing.", width=180),
                            "จำนวน": st.column_config.NumberColumn("จำนวน", width=65, format="%d"),
                            "วัสดุ": st.column_config.TextColumn("วัสดุ", width=75),
                            "ประเภทงาน": st.column_config.TextColumn("ประเภทงาน", width=125),
                            "ขั้นตอน (Step)": st.column_config.TextColumn("ขั้นตอน (Step)", width=130),
                            "เลือกเครื่องจักร": st.column_config.TextColumn("เลือกเครื่องจักร", width=160),
                            "วัน-เวลาขึ้นงาน": st.column_config.TextColumn("วัน-เวลาขึ้นงาน", width=165),
                            "Setup (น.)": st.column_config.NumberColumn("Setup (น.)", width=85, format="%d"),
                            "Basic (น.)": st.column_config.NumberColumn("Basic (น.)", width=85, format="%d"),
                            "โปรแกรม (น.)": st.column_config.NumberColumn("โปรแกรม (น.)", width=100, format="%d"),
                            "รวม (ชม.)": st.column_config.NumberColumn("รวม (ชม.)", width=85, format="%.2f"),
                            "สถานะงาน": st.column_config.TextColumn("สถานะงาน", width=145),
                        },
                        hide_index=True,
                        use_container_width=True
                    )
                
                st.markdown('<div id="editor_table_bottom_mark"></div>', unsafe_allow_html=True)

                if is_admin:
                    active_to_delete = edited_jobs[
                        (edited_jobs["ลบ"] == True) & 
                        (edited_jobs["แผนงาน"].notna()) & 
                        (edited_jobs["แผนงาน"].astype(str).str.strip() != "") & 
                        (edited_jobs["แผนงาน"].astype(str).str.strip() != "None")
                    ]
                    delete_count = len(active_to_delete)

                    c_save, c_del_top, _ = st.columns([2.5, 3.5, 4])
                    with c_save:
                        if st.button("💾 บันทึกข้อมูลลง Supabase", type="primary", use_container_width=True):
                            db_original_map = {}
                            for _, orig_row in df_db.iterrows():
                                if pd.notna(orig_row.get("ID")):
                                    db_original_map[int(float(orig_row["ID"]))] = orig_row

                            saved_inserts = 0
                            saved_updates = 0

                            for _, row in edited_jobs.iterrows():
                                raw_plan = row.get("แผนงาน")
                                p_code = safe_str(raw_plan, "")
                                if not p_code:
                                    continue
                                
                                d_name = safe_str(row.get("ชื่อ Drawing."), "")
                                qty_int = safe_int(row.get("จำนวน"), 1)
                                mat_val = safe_str(row.get("วัสดุ"), "SS400")
                                job_type_val = safe_str(row.get("ประเภทงาน"), "🟢 งานปกติ")
                                step_val = safe_str(row.get("ขั้นตอน (Step)"), "รอหน้าเครื่องระบุ")
                                machine_val = safe_str(row.get("เลือกเครื่องจักร"), "No.1 Awea")
                                status_val = safe_str(row.get("สถานะงาน"), "🟧 รอคิวผลิต")
                                
                                s_val = safe_float(row.get("Setup (น.)"), 10.0)
                                b_val = safe_float(row.get("Basic (น.)"), 0.0)
                                p_val = safe_float(row.get("โปรแกรม (น.)"), 120.0)
                                
                                raw_ready = row.get("วัน-เวลาขึ้นงาน")
                                dt_parsed = parse_flexible_datetime(raw_ready)
                                ready_str = dt_parsed.strftime("%Y-%m-%d %H:%M:%S") if dt_parsed is not None else None
                                
                                payload = {
                                    "plan_code": p_code,
                                    "drawing_name": d_name,
                                    "qty": qty_int,
                                    "material": mat_val,
                                    "job_type": job_type_val,
                                    "step_name": step_val,
                                    "machine_name": machine_val,
                                    "ready_at": ready_str,
                                    "setup_mins": s_val,
                                    "basic_hrs": b_val,
                                    "prog_hrs": p_val,
                                    "status": status_val
                                }
                                
                                row_id = row.get("ID")
                                
                                is_new_row = False
                                if pd.isna(row_id) or row_id is None:
                                    is_new_row = True
                                elif str(row_id).strip() in ["", "None", "nan", "NaN", "null"]:
                                    is_new_row = True
                                else:
                                    try:
                                        if float(row_id) <= 0:
                                            is_new_row = True
                                    except Exception:
                                        is_new_row = True

                                if is_new_row:
                                    if insert_supabase_job(payload):
                                        saved_inserts += 1
                                else:
                                    target_id = int(float(row_id))
                                    orig = db_original_map.get(target_id)
                                    
                                    is_changed = False
                                    if orig is None:
                                        is_changed = True
                                    else:
                                        if safe_str(orig.get("แผนงาน")) != p_code or \
                                           safe_str(orig.get("ชื่อ Drawing.")) != d_name or \
                                           safe_int(orig.get("จำนวน")) != qty_int or \
                                           safe_str(orig.get("วัสดุ")) != mat_val or \
                                           safe_str(orig.get("ประเภทงาน")) != job_type_val or \
                                           safe_str(orig.get("ขั้นตอน (Step)")) != step_val or \
                                           safe_str(orig.get("เลือกเครื่องจักร")) != machine_val or \
                                           safe_str(orig.get("สถานะงาน")) != status_val or \
                                           safe_float(orig.get("Setup (น.)")) != s_val or \
                                           safe_float(orig.get("Basic (น.)")) != b_val or \
                                           safe_float(orig.get("โปรแกรม (น.)")) != p_val:
                                            is_changed = True
                                        else:
                                            orig_ready_dt = parse_flexible_datetime(orig.get("วัน-เวลาขึ้นงาน"))
                                            orig_ready_str = orig_ready_dt.strftime("%Y-%m-%d %H:%M:%S") if orig_ready_dt is not None else None
                                            if orig_ready_str != ready_str:
                                                is_changed = True

                                    if is_changed:
                                        if update_supabase_job(target_id, payload):
                                            saved_updates += 1

                            st.cache_data.clear()
                            st.session_state.scroll_to_bottom = True
                            total_affected = saved_inserts + saved_updates
                            if total_affected > 0:
                                st.success(f"บันทึกข้อมูลสำเร็จ! (เพิ่มใหม่ {saved_inserts} รายการ, แก้ไข {saved_updates} รายการ)")
                            else:
                                st.info("ไม่มีข้อมูลเปลี่ยนแปลงที่ต้องบันทึก")
                            st.rerun()

                    with c_del_top:
                        btn_del_label = f"🗑️ ลบรายการที่เลือก ({delete_count} รายการ)" if delete_count > 0 else "🗑️ ลบรายการที่เลือก (0 รายการ)"
                        if st.button(btn_del_label, type="secondary", disabled=(delete_count == 0), use_container_width=True):
                            del_success = True
                            for _, row in active_to_delete.iterrows():
                                row_id = row.get("ID")
                                if pd.notna(row_id) and str(row_id).strip() not in ["", "None", "nan"] and float(row_id) > 0:
                                    if not delete_supabase_job(int(float(row_id))):
                                        del_success = False
                                        
                            if del_success:
                                st.session_state.active_select_all = False
                                st.cache_data.clear()
                                st.session_state.scroll_to_bottom = True
                                st.toast("ลบรายการที่เลือกเรียบร้อยแล้ว", icon="🗑️")
                                st.rerun()
                            else:
                                st.error("เกิดข้อผิดพลาดในการลบข้อมูลจาก Supabase")

            if st.session_state.scroll_to_bottom:
                components.html("""
                <script>
                    function scrollToTarget() {
                        const target = window.parent.document.getElementById('editor_table_bottom_mark');
                        if (target) {
                            target.scrollIntoView({behavior: 'smooth', block: 'center'});
                        }
                    }
                    setTimeout(scrollToTarget, 300);
                    setTimeout(scrollToTarget, 700);
                </script>
                """, height=0)
                st.session_state.scroll_to_bottom = False

            current_real_time = get_bangkok_now().replace(tzinfo=None)
            df_gantt, df_summary, df_util, total_plan_hrs = calculate_shop_schedule(edited_jobs, current_real_time)

            finished_jobs_df = df_db[df_db["สถานะงาน"].isin(["🟩 เสร็จสิ้นแล้ว", "✅ เสร็จสิ้นแล้ว"])].copy()
            active_jobs_count = len(edited_jobs[edited_jobs["สถานะงาน"].isin(["🟧 รอคิวผลิต", "🟦 กำลังผลิต", "🟨 พักงาน (รอวัสดุ)", "⏳ รอคิวผลิต", "⚙️ กำลังผลิต"])])
            avg_util = df_util["อัตราการใช้งาน (%)"].mean() if not df_util.empty else 0.0

            kpi_html = f'''<div class="kpi-container"><div class="kpi-card kpi-green"><div class="kpi-title">✅ งานเสร็จสิ้น</div><div class="kpi-value">{len(finished_jobs_df)} <span style="font-size:15px; font-weight:600;">รายการ</span></div></div><div class="kpi-card kpi-blue"><div class="kpi-title">⚙️ งานในแผน</div><div class="kpi-value">{active_jobs_count} <span style="font-size:15px; font-weight:600;">รายการ</span></div></div><div class="kpi-card kpi-orange"><div class="kpi-title">⏱️ เวลาทำงานรวม</div><div class="kpi-value">{total_plan_hrs:.1f} <span style="font-size:15px; font-weight:600;">ชม.</span></div></div><div class="kpi-card kpi-purple"><div class="kpi-title">📊 การใช้เครื่อง</div><div class="kpi-value">{avg_util:.1f} %</div></div></div>'''
            st.markdown(kpi_html, unsafe_allow_html=True)

            st.divider()

            # =====================================================
            # 2. ใบจ่ายคิวงานหน้าเครื่อง (Work Order Sheet) + แถบกรองสีกดได้
            # =====================================================
            if not df_summary.empty:
                st.subheader("📋 ใบจ่ายคิวงานหน้าเครื่อง (Work Order Sheet)")

                if "wo_color_filter" not in st.session_state:
                    st.session_state.wo_color_filter = "ALL"

                wo_finish_map = dict(
                    zip(
                        zip(df_summary["แผนงาน"].astype(str), df_summary["ชื่อ Drawing."].astype(str)),
                        df_summary["เวลาจบงาน_DT"]
                    )
                )

                now_check = get_bangkok_now().replace(tzinfo=None)
                warn_count = 0
                late_count = 0
                for _, r in df_summary.iterrows():
                    if "กำลังผลิต" in str(r.get("สถานะ", "")):
                        f_dt = wo_finish_map.get((str(r["แผนงาน"]), str(r["ชื่อ Drawing."])))
                        if pd.notna(f_dt):
                            diff_m = (f_dt - now_check).total_seconds() / 60.0
                            if diff_m < 0:
                                late_count += 1
                            elif 0 <= diff_m <= 60:
                                warn_count += 1

                wo_search_col, wo_filter_btn_col = st.columns([4, 6])
                with wo_search_col:
                    search_query_wo = st.text_input(
                        "🔍 ค้นหาในใบจ่ายคิวงาน (แผนงาน, Drawing, เครื่องจักร, สถานะ):",
                        placeholder="พิมพ์เพื่อค้นหาคิวงาน เช่น รอคิวผลิต, กำลังผลิต...",
                        key="search_wo_sheet_input"
                    )

                with wo_filter_btn_col:
                    st.caption("**🎯 ตัวกรองด่วนสถานะเตือนเวลา:**")
                    f_b1, f_b2, f_b3 = st.columns([1.5, 2.2, 2.2])
                    with f_b1:
                        btn_all_type = "primary" if st.session_state.wo_color_filter == "ALL" else "secondary"
                        if st.button("🌐 ทั้งหมด", type=btn_all_type, use_container_width=True):
                            st.session_state.wo_color_filter = "ALL"
                            st.rerun()
                    with f_b2:
                        btn_warn_type = "primary" if st.session_state.wo_color_filter == "WARN" else "secondary"
                        if st.button(f"🟡 ใกล้เสร็จ ({warn_count})", type=btn_warn_type, use_container_width=True, help="เหลือน้อยกว่า 1 ชม."):
                            st.session_state.wo_color_filter = "WARN"
                            st.rerun()
                    with f_b3:
                        btn_late_type = "primary" if st.session_state.wo_color_filter == "LATE" else "secondary"
                        if st.button(f"🔴 เกินแผน ({late_count})", type=btn_late_type, use_container_width=True, help="เลยกำหนดเวลาแผน"):
                            st.session_state.wo_color_filter = "LATE"
                            st.rerun()

                df_display = df_summary.sort_values(by="เวลาเริ่มจริง", ascending=True).copy()

                if st.session_state.wo_color_filter == "WARN":
                    def is_warn_row(r):
                        if "กำลังผลิต" not in str(r.get("สถานะ", "")): return False
                        f_dt = wo_finish_map.get((str(r["แผนงาน"]), str(r["ชื่อ Drawing."])))
                        if pd.notna(f_dt):
                            diff_m = (f_dt - now_check).total_seconds() / 60.0
                            return 0 <= diff_m <= 60
                        return False
                    df_display = df_display[df_display.apply(is_warn_row, axis=1)]

                elif st.session_state.wo_color_filter == "LATE":
                    def is_late_row(r):
                        if "กำลังผลิต" not in str(r.get("สถานะ", "")): return False
                        f_dt = wo_finish_map.get((str(r["แผนงาน"]), str(r["ชื่อ Drawing."])))
                        if pd.notna(f_dt):
                            diff_m = (f_dt - now_check).total_seconds() / 60.0
                            return diff_m < 0
                        return False
                    df_display = df_display[df_display.apply(is_late_row, axis=1)]

                if search_query_wo.strip() != "":
                    q_wo = search_query_wo.strip().lower()
                    df_display = df_display[
                        df_display["แผนงาน"].astype(str).str.lower().str.contains(q_wo) |
                        df_display["ชื่อ Drawing."].astype(str).str.lower().str.contains(q_wo) |
                        df_display["เครื่องจักร"].astype(str).str.lower().str.contains(q_wo) |
                        df_display["สถานะ"].astype(str).str.lower().str.contains(q_wo)
                    ]

                display_cols = [c for c in df_display.columns if c not in ["เวลาเริ่มจริง", "ID", "เวลาจบงาน_DT"]]

                styled_df_display = df_display[display_cols].style.apply(
                    highlight_running_deadlines,
                    planned_finish_map=wo_finish_map,
                    axis=1
                )

                st.dataframe(
                    styled_df_display,
                    column_config={
                        "เครื่องจักร": st.column_config.TextColumn("เครื่องจักร / แผนก", width=150),
                        "สถานะ": st.column_config.TextColumn("สถานะ", width=110),
                        "ประเภทงาน": st.column_config.TextColumn("ประเภทงาน", width=105),
                        "แผนงาน": st.column_config.TextColumn("แผนงาน", width=80),
                        "ชื่อ Drawing.": st.column_config.TextColumn("ชื่อ Drawing.", width=180),
                        "จำนวน": st.column_config.NumberColumn("จำนวน", width=65, format="%d"),
                        "วัสดุ": st.column_config.TextColumn("วัสดุ", width=75),
                        "ขั้นตอน (Step)": st.column_config.TextColumn("ขั้นตอน (Step)", width=130),
                        "เวลาเริ่ม Setup": st.column_config.TextColumn("เริ่ม Setup", width=105),
                        "เวลาเริ่มขึ้นงาน": st.column_config.TextColumn("เริ่มขึ้นงาน", width=105),
                        "เวลาจบงาน": st.column_config.TextColumn("จบงาน", width=105),
                        "Setup (น.)": st.column_config.NumberColumn("Setup (น.)", width=85, format="%d"),
                        "Basic (น.)": st.column_config.NumberColumn("Basic (น.)", width=85, format="%d"),
                        "โปรแกรม (น.)": st.column_config.NumberColumn("โปรแกรม (น.)", width=95, format="%d"),
                        "รวม (ชม.)": st.column_config.NumberColumn("รวม (ชม.)", width=85, format="%.2f"),
                    },
                    use_container_width=True,
                    hide_index=True
                )

                st.divider()

            # =====================================================
            # 3. รายการงานที่ Finish แล้ว
            # =====================================================
            if not finished_jobs_df.empty:
                st.subheader("📋 รายการงานที่ Finish แล้ว และเช็คเวลาวางแผนเทียบกับเวลาจริง (Plan vs Actual Performance)")
                perf_df = finished_jobs_df.copy()
                perf_df["เวลาแผน (ชม.)"] = ((perf_df["Setup (น.)"] + perf_df["Basic (น.)"] + perf_df["โปรแกรม (น.)"]) / 60.0).round(2)
                
                actual_hrs_list, diff_list, status_eval_list = [], [], []
                for _, r in perf_df.iterrows():
                    s_real, f_real = r.get("เริ่มจริง"), r.get("เสร็จจริง")
                    if pd.notna(s_real) and pd.notna(f_real):
                        diff_seconds = (pd.to_datetime(f_real) - pd.to_datetime(s_real)).total_seconds()
                        act_hrs = round(diff_seconds / 3600.0, 2)
                        variance_hrs = round(act_hrs - r["เวลาแผน (ชม.)"], 2)
                        diff_mins = round((diff_seconds / 60.0) - (r["เวลาแผน (ชม.)"] * 60.0))
                        
                        actual_hrs_list.append(act_hrs)
                        diff_list.append(variance_hrs)
                        
                        if diff_mins <= 0:
                            status_eval_list.append(f"🟢 เร็วกว่าแผน {abs(diff_mins):.0f} นาที")
                        else:
                            status_eval_list.append(f"🔴 ช้ากว่าแผน +{diff_mins:.0f} นาที")
                    else:
                        actual_hrs_list.append(None)
                        diff_list.append(None)
                        status_eval_list.append("⚪ รอกดบันทึกเวลาจริง")
                        
                perf_df["เวลาจริง (ชม.)"] = actual_hrs_list
                perf_df["ผลต่าง (ชม.)"] = diff_list
                perf_df["การประเมิน"] = status_eval_list
                perf_df["ลบ"] = st.session_state.finish_select_all
                
                display_finish_df = perf_df.sort_values(by="แผนงาน", ascending=True)[["ID", "แผนงาน", "ชื่อ Drawing.", "จำนวน", "ขั้นตอน (Step)", "เลือกเครื่องจักร", "เริ่มจริง", "เสร็จจริง", "เวลาแผน (ชม.)", "เวลาจริง (ชม.)", "ผลต่าง (ชม.)", "การประเมิน", "ลบ"]].copy().reset_index(drop=True)

                if is_admin:
                    tool_c1, tool_c2, _ = st.columns([1.5, 1.5, 7])
                    with tool_c1:
                        if st.button("✅ เลือกทั้งหมด (งาน Finish)", use_container_width=True):
                            st.session_state.finish_select_all = True
                            st.rerun()
                    with tool_c2:
                        if st.button("❌ ยกเลิกทั้งหมด (งาน Finish)", use_container_width=True):
                            st.session_state.finish_select_all = False
                            st.rerun()

                    edited_finish_table = st.data_editor(
                        display_finish_df,
                        key="editor_finish_jobs_table_mins_v12",
                        column_order=[
                            "แผนงาน", "ชื่อ Drawing.", "จำนวน", "ขั้นตอน (Step)", "เลือกเครื่องจักร",
                            "เริ่มจริง", "เสร็จจริง", "เวลาแผน (ชม.)", "เวลาจริง (ชม.)",
                            "ผลต่าง (ชม.)", "การประเมิน", "ลบ"
                        ],
                        column_config={
                            "ID": None,
                            "แผนงาน": st.column_config.TextColumn("PLAN NO.", disabled=True, width=85),
                            "ชื่อ Drawing.": st.column_config.TextColumn("DRAWING NO.", disabled=True, width=180),
                            "จำนวน": st.column_config.NumberColumn("จำนวน", disabled=True, width=65, format="%d"),
                            "ขั้นตอน (Step)": st.column_config.TextColumn("ขั้นตอน", disabled=True, width=120),
                            "เลือกเครื่องจักร": st.column_config.TextColumn("สถานีผลิต", width=140),
                            "เริ่มจริง": st.column_config.DatetimeColumn("เริ่มจริง", width=145, format="DD/MM HH:mm"),
                            "เสร็จจริง": st.column_config.DatetimeColumn("เวลาจบจริง", width=145, format="DD/MM HH:mm"),
                            "เวลาแผน (ชม.)": st.column_config.NumberColumn("แผน (ชม.)", width=90, format="%.2f"),
                            "เวลาจริง (ชม.)": st.column_config.NumberColumn("จริง (ชม.)", width=90, format="%.2f"),
                            "ผลต่าง (ชม.)": st.column_config.NumberColumn("Diff", width=80, format="%.2f"),
                            "การประเมิน": st.column_config.TextColumn("ผลการผลิต", width=170),
                            "ลบ": st.column_config.CheckboxColumn("🗑️", help="ติ๊กถูกช่องนี้เพื่อเลือกลบรายการ", width=55),
                        },
                        hide_index=True,
                        use_container_width=True
                    )

                    c_del_act, _ = st.columns([3, 7])
                    with c_del_act:
                        selected_rows_to_delete = edited_finish_table[edited_finish_table["ลบ"] == True]
                        if st.button(f"🗑️ ลบรายการ Finish ที่เลือก ({len(selected_rows_to_delete)} รายการ)", type="secondary", disabled=(len(selected_rows_to_delete) == 0)):
                            del_success = True
                            for _, row in selected_rows_to_delete.iterrows():
                                row_id = row.get("ID")
                                if pd.notna(row_id) and str(row_id).strip() not in ["", "None", "nan"] and float(row_id) > 0:
                                    if not delete_supabase_job(int(float(row_id))):
                                        del_success = False
                            if del_success:
                                st.session_state.finish_select_all = False
                                st.cache_data.clear()
                                st.toast("ลบรายการที่เลือกเรียบร้อยแล้ว", icon="🗑️")
                                st.rerun()
                            else:
                                st.error("เกิดข้อผิดพลาดในการลบข้อมูล")
                else:
                    st.dataframe(
                        display_finish_df[[c for c in display_finish_df.columns if c not in ["ID", "ลบ"]]],
                        column_config={
                            "แผนงาน": st.column_config.TextColumn("PLAN NO.", width=85),
                            "ชื่อ Drawing.": st.column_config.TextColumn("DRAWING NO.", width=180),
                            "จำนวน": st.column_config.NumberColumn("จำนวน", width=65, format="%d"),
                            "ขั้นตอน (Step)": st.column_config.TextColumn("ขั้นตอน", width=120),
                            "เลือกเครื่องจักร": st.column_config.TextColumn("สถานีผลิต", width=140),
                            "เริ่มจริง": st.column_config.DatetimeColumn("เริ่มจริง", width=145, format="DD/MM HH:mm"),
                            "เสร็จจริง": st.column_config.DatetimeColumn("เวลาจบจริง", width=145, format="DD/MM HH:mm"),
                            "เวลาแผน (ชม.)": st.column_config.NumberColumn("แผน (ชม.)", width=90, format="%.2f"),
                            "เวลาจริง (ชม.)": st.column_config.NumberColumn("จริง (ชม.)", width=90, format="%.2f"),
                            "ผลต่าง (ชม.)": st.column_config.NumberColumn("Diff", width=80, format="%.2f"),
                            "การประเมิน": st.column_config.TextColumn("ผลการผลิต", width=170),
                        },
                        hide_index=True,
                        use_container_width=True
                    )

                st.divider()

            # =====================================================
            # 4. ผังเวลาขึ้นงาน (Gantt Chart Timeline)
            # =====================================================
            if not df_gantt.empty:
                st.subheader("📊 ผังเวลาขึ้นงานที่กำลังผลิตและรอคิว (Gantt Chart Timeline)")
                
                today_date = get_bangkok_now().date()
                gantt_min_date = df_gantt["เวลาเริ่ม"].min().date()
                gantt_max_date = df_gantt["เวลาเสร็จ"].max().date()

                if st.session_state.gantt_date_range is None:
                    st.session_state.gantt_date_range = (today_date, max(today_date + timedelta(days=7), gantt_max_date))

                gantt_f1, gantt_f2, gantt_f3 = st.columns([2.2, 3.2, 1.8])
                with gantt_f1:
                    m_filter_mode = st.radio(
                        "🔍 กรองกลุ่มสถานีงาน:",
                        ["🌐 ทุกสถานี (17 เครื่อง)", "⚙️ CNC (No.1 - No.9)", "🔧 เจียร/มิลลิ่ง/กลึง/เชื่อม (No.10 - No.17)"],
                        horizontal=True
                    )

                with gantt_f2:
                    st.markdown("**📅 ช่วงวันที่ต้องการดูผังงาน:**")
                    btn_q1, btn_q2, btn_q3, btn_q4 = st.columns(4)
                    with btn_q1:
                        if st.button("🔍 วันนี้", use_container_width=True):
                            st.session_state.gantt_date_range = (today_date, today_date)
                            st.rerun()
                    with btn_q2:
                        if st.button("📅 3 วัน", use_container_width=True):
                            st.session_state.gantt_date_range = (today_date, today_date + timedelta(days=2))
                            st.rerun()
                    with btn_q3:
                        if st.button("📆 7 วัน", use_container_width=True):
                            st.session_state.gantt_date_range = (today_date, today_date + timedelta(days=6))
                            st.rerun()
                    with btn_q4:
                        if st.button("🌐 ทั้งหมด", use_container_width=True):
                            st.session_state.gantt_date_range = (min(today_date, gantt_min_date), max(today_date, gantt_max_date))
                            st.rerun()

                    selected_date_range = st.date_input(
                        "เลือกช่วงวันที่กำหนดเอง:",
                        value=st.session_state.gantt_date_range,
                        min_value=min(today_date, gantt_min_date) - timedelta(days=60),
                        max_value=max(today_date, gantt_max_date) + timedelta(days=60),
                        label_visibility="collapsed"
                    )
                    st.session_state.gantt_date_range = selected_date_range

                with gantt_f3:
                    color_by_option = st.selectbox("🎨 แยกสีตาม:", ["แผนงาน (Plan Code)", "กิจกรรม (Setup/ตัดเฉือน)"])

                if "CNC" in m_filter_mode:
                    display_machines = MACHINE_LIST[:9]
                elif "เจียร" in m_filter_mode:
                    display_machines = MACHINE_LIST[9:]
                else:
                    display_machines = MACHINE_LIST

                plot_gantt_df = df_gantt[df_gantt["เครื่องจักร"].isin(display_machines)].copy()
                plot_gantt_df["เริ่มแสดง"] = plot_gantt_df["เวลาเริ่ม"].dt.strftime("%d/%m/%Y %H:%M น.")
                plot_gantt_df["เสร็จแสดง"] = plot_gantt_df["เวลาเสร็จ"].dt.strftime("%d/%m/%Y %H:%M น.")

                color_target = "แผนงาน" if color_by_option == "แผนงาน (Plan Code)" else "กิจกรรม"
                distinct_plans = [p for p in plot_gantt_df["แผนงาน"].unique() if p != "⏳ รอรัน (เครื่องว่าง)"]
                plan_color_map = {}
                palette = px.colors.qualitative.Bold
                for idx, p_name in enumerate(distinct_plans):
                    plan_color_map[p_name] = palette[idx % len(palette)]
                plan_color_map["⏳ รอรัน (เครื่องว่าง)"] = "#CBD5E1"

                fig = px.timeline(
                    plot_gantt_df,
                    x_start="เวลาเริ่ม",
                    x_end="เวลาเสร็จ",
                    y="เครื่องจักร",
                    color=color_target,
                    text="ข้อความบนแท่งกราฟ",
                    custom_data=["แผนงาน", "ชื่อ Drawing.", "จำนวน", "ขั้นตอน (Step)", "วัสดุ", "เริ่มแสดง", "เสร็จแสดง", "ระยะเวลา", "กิจกรรม"],
                    category_orders={"เครื่องจักร": display_machines},
                    color_discrete_map=plan_color_map if color_target == "แผนงาน" else {
                        "🔧 ตั้งเครื่อง / เซ็ตศูนย์": "#FF7A00",
                        "⚙️ งานปกติ": "#0284C7",
                        "🔴 งานด่วน": "#EF4444",
                        "⏳ รอรัน (เครื่องว่าง)": "#CBD5E1"
                    }
                )
                
                fig.update_traces(
                    textposition="inside",
                    insidetextanchor="middle",
                    marker_line_color="#FFFFFF",
                    marker_line_width=1.2,
                    hovertemplate="""
                    <b>📌 แผนงาน: %{customdata[0]}</b> | %{customdata[1]}<br>
                    ⚙️ <b>ขั้นตอน:</b> %{customdata[3]} | 🔢 <b>จำนวน:</b> %{customdata[2]} ชิ้น (%{customdata[4]})<br>
                    🏷️ <b>ประเภท:</b> %{customdata[8]}<br>
                    ----------------------------------<br>
                    ⏱️ <b>เริ่ม:</b> %{customdata[5]}<br>
                    🏁 <b>เสร็จ:</b> %{customdata[6]}<br>
                    ⏳ <b>ระยะเวลารอบนี้:</b> %{customdata[7]}
                    <extra></extra>
                    """
                )
                
                fig.update_yaxes(autorange="reversed", type="category", categoryorder="array", categoryarray=display_machines, showgrid=True, gridcolor="#E2E8F0")
                
                if isinstance(selected_date_range, (list, tuple)) and len(selected_date_range) == 2:
                    start_view = datetime.combine(selected_date_range[0], dtime(7, 30))
                    end_view = datetime.combine(selected_date_range[1], dtime(20, 30))
                elif isinstance(selected_date_range, (list, tuple)) and len(selected_date_range) == 1:
                    start_view = datetime.combine(selected_date_range[0], dtime(7, 30))
                    end_view = datetime.combine(selected_date_range[1], dtime(20, 30))
                else:
                    start_view = datetime.combine(gantt_min_date, dtime(7, 30))
                    end_view = datetime.combine(gantt_max_date, dtime(20, 30))

                fig.update_xaxes(range=[start_view, end_view], showgrid=True, gridcolor="#E2E8F0")

                if not plot_gantt_df.empty:
                    cur_d = (start_view.date() - timedelta(days=2))
                    max_scan_d = (end_view.date() + timedelta(days=2))
                    
                    while cur_d <= max_scan_d:
                        if cur_d.weekday() == 6:
                            sun_start = datetime.combine(cur_d, dtime(0, 0))
                            sun_end = datetime.combine(cur_d + timedelta(days=1), dtime(0, 0))
                            fig.add_vrect(
                                x0=sun_start, x1=sun_end,
                                fillcolor="#F8FAFC", opacity=0.8,
                                layer="below", line_width=1, line_color="#E2E8F0",
                                annotation_text="🛑 วันอาทิตย์ (หยุด)", annotation_position="top left",
                                annotation_font_size=10, annotation_font_color="#94A3B8"
                            )
                        else:
                            lunch_start = datetime.combine(cur_d, dtime(12, 0))
                            lunch_end = datetime.combine(cur_d, dtime(13, 0))
                            fig.add_vrect(
                                x0=lunch_start, x1=lunch_end,
                                fillcolor="#FEF3C7", opacity=0.55,
                                layer="below", line_width=1, line_color="#FDE68A",
                                annotation_text="🍱 พักเที่ยง", annotation_position="top left",
                                annotation_font_size=9, annotation_font_color="#D97706"
                            )
                        cur_d += timedelta(days=1)

                fig.update_layout(
                    height=max(450, len(display_machines) * 35),
                    xaxis_title="วันและเวลาทำงาน",
                    yaxis_title="เครื่องจักร / แผนก",
                    uniformtext_minsize=8,
                    uniformtext_mode='hide',
                    plot_bgcolor="#FFFFFF",
                    paper_bgcolor="#FFFFFF",
                    margin=dict(l=40, r=40, t=30, b=30),
                    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
                )
                st.plotly_chart(fig, use_container_width=True)

                st.markdown("""
                <div class="schedule-info-box">
                    <div class="schedule-pill">
                        <span style="font-size:16px;">⏱️</span>
                        <span><b>จันทร์ – ศุกร์:</b> 08:00 – 12:00 น. และ 13:00 – 20:00 น. (11 ชม./วัน)</span>
                    </div>
                    <div class="schedule-pill">
                        <span style="font-size:16px;">⏱️</span>
                        <span><b>วันเสาร์:</b> 08:00 – 12:00 น. และ 13:00 – 17:00 น. (8 ชม./วัน)</span>
                    </div>
                    <div class="schedule-pill">
                        <span style="font-size:16px;">🍱</span>
                        <span style="color:#D97706;"><b>พักเบรกเที่ยง:</b> 12:00 – 13:00 น. (แถบสีส้มอ่อน)</span>
                    </div>
                    <div class="schedule-pill">
                        <span style="color:#DC2626;"><b>วันอาทิตย์:</b> หยุดทำการ (แถบสีเทาอ่อน)</span>
                    </div>
                </div>
                """, unsafe_allow_html=True)

                st.divider()

                # =====================================================
                # 5. อัตราการใช้งานเครื่องจักร (% Machine Utilization)
                # =====================================================
                st.subheader("📈 อัตราการใช้งานเครื่องจักรและแผนกผลิต (% Utilization)")
                fig_bar = px.bar(
                    df_util,
                    x="อัตราการใช้งาน (%)",
                    y="เครื่องจักร",
                    orientation="h",
                    color="อัตราการใช้งาน (%)",
                    color_continuous_scale=[[0, "#E0F2FE"], [0.4, "#38BDF8"], [0.8, "#0284C7"], [1, "#0369A1"]],
                    text="ข้อความแสดง",
                    range_x=[0, 105],
                    category_orders={"เครื่องจักร": MACHINE_LIST}
                )
                fig_bar.update_yaxes(autorange="reversed", type="category", categoryorder="array", categoryarray=MACHINE_LIST)
                fig_bar.update_traces(marker_line_color="#0F172A", marker_line_width=1.2, textposition="outside", cliponaxis=False)
                fig_bar.update_layout(
                    height=600,
                    margin=dict(l=40, r=40, t=10, b=30),
                    xaxis_title="อัตราการใช้งาน (%)",
                    yaxis_title="เครื่องจักร / แผนก",
                    xaxis=dict(showgrid=True, gridcolor="#F1F5F9"),
                    coloraxis_showscale=False,
                    plot_bgcolor="#FFFFFF",
                    paper_bgcolor="#FFFFFF"
                )
                fig_bar.add_vline(x=85, line_dash="dash", line_color="#EF4444", line_width=2, annotation_text="เป้าหมาย (85%)", annotation_position="top right", annotation_font_color="#EF4444")
                st.plotly_chart(fig_bar, use_container_width=True)

                st.divider()

            # =====================================================
            # 6. ตารางคำนวณมูลค่าและต้นทุนค่าเครื่องจักร
            # =====================================================
            st.subheader("💰 ตารางคำนวณมูลค่าและต้นทุนค่าเครื่องจักร (Machining Cost Calculation)")

            current_rates_df = pd.DataFrame([
                {"เครื่องจักร": m, "เรตราคา (บาท/ชม.)": DEFAULT_RATES.get(m, 500)}
                for m in MACHINE_LIST
            ])
            
            if "machine_rates" not in st.session_state or len(st.session_state.machine_rates) != len(MACHINE_LIST):
                st.session_state.machine_rates = current_rates_df
            else:
                existing_map = dict(zip(st.session_state.machine_rates["เครื่องจักร"], st.session_state.machine_rates["เรตราคา (บาท/ชม.)"]))
                for m in MACHINE_LIST:
                    if m not in existing_map:
                        existing_map[m] = DEFAULT_RATES.get(m, 500)
                st.session_state.machine_rates = pd.DataFrame([
                    {"เครื่องจักร": m, "เรตราคา (บาท/ชม.)": existing_map[m]} for m in MACHINE_LIST
                ])

            cost_col1, cost_col2 = st.columns([1.1, 2.9])

            with cost_col1:
                st.markdown("**⚙️ ตั้งค่าเรตราคาค่าเครื่องจักร (บาท/ชม.)**")
                if is_admin:
                    edited_rates = st.data_editor(
                        st.session_state.machine_rates,
                        key="editor_machine_rates_full_17_v12",
                        column_config={
                            "เครื่องจักร": st.column_config.TextColumn("เครื่องจักร / แผนก", disabled=True),
                            "เรตราคา (บาท/ชม.)": st.column_config.NumberColumn("เรตราคา (บาท/ชม.)", min_value=0, max_value=50000, step=50, format="%d ฿", required=True)
                        },
                        use_container_width=True,
                        hide_index=True
                    )
                    st.session_state.machine_rates = edited_rates
                    rate_map = dict(zip(edited_rates["เครื่องจักร"], edited_rates["เรตราคา (บาท/ชม.)"]))
                else:
                    st.dataframe(
                        st.session_state.machine_rates,
                        column_config={
                            "เครื่องจักร": st.column_config.TextColumn("เครื่องจักร / แผนก"),
                            "เรตราคา (บาท/ชม.)": st.column_config.NumberColumn("เรตราคา (บาท/ชม.)", format="%d ฿")
                        },
                        use_container_width=True,
                        hide_index=True
                    )
                    rate_map = dict(zip(st.session_state.machine_rates["เครื่องจักร"], st.session_state.machine_rates["เรตราคา (บาท/ชม.)"]))

            with cost_col2:
                if not finished_jobs_df.empty:
                    cost_df = finished_jobs_df.copy()
                    cost_df["รวม (ชม.)"] = ((cost_df["Setup (น.)"] + cost_df["Basic (น.)"] + cost_df["โปรแกรม (น.)"]) / 60.0).round(2)
                    cost_df["เรตราคา (บาท/ชม.)"] = cost_df["เลือกเครื่องจักร"].map(rate_map).fillna(500)
                    cost_df["มูลค่ารวม (บาท)"] = cost_df["รวม (ชม.)"] * cost_df["เรตราคา (บาท/ชม.)"]
                    
                    total_finished_cost = cost_df["มูลค่ารวม (บาท)"].sum()
                    total_finished_hrs = cost_df["รวม (ชม.)"].sum()
                    
                    st.markdown(f"**📊 รายการสรุปมูลค่างานที่เสร็จสิ้น (รวมทั้งหมด: :green[{total_finished_cost:,.2f} บาท] / {total_finished_hrs:.2f} ชม.)**")
                    st.dataframe(
                        cost_df.sort_values(by="แผนงาน", ascending=True)[["แผนงาน", "ชื่อ Drawing.", "จำนวน", "ขั้นตอน (Step)", "เลือกเครื่องจักร", "Setup (น.)", "Basic (น.)", "โปรแกรม (น.)", "รวม (ชม.)", "เรตราคา (บาท/ชม.)", "มูลค่ารวม (บาท)"]],
                        column_config={
                            "แผนงาน": st.column_config.TextColumn("แผนงาน", width=85),
                            "ชื่อ Drawing.": st.column_config.TextColumn("ชื่อ Drawing.", width=180),
                            "จำนวน": st.column_config.NumberColumn("จำนวน", width=65, format="%d"),
                            "ขั้นตอน (Step)": st.column_config.TextColumn("ขั้นตอน", width=120),
                            "เลือกเครื่องจักร": st.column_config.TextColumn("เครื่องจักร / แผนก", width=140),
                            "Setup (น.)": st.column_config.NumberColumn("Setup (น.)", width=85, format="%d"),
                            "Basic (น.)": st.column_config.NumberColumn("Basic (น.)", width=85, format="%d"),
                            "โปรแกรม (น.)": st.column_config.NumberColumn("โปรแกรม (น.)", width=95, format="%d"),
                            "รวม (ชม.)": st.column_config.NumberColumn("รวม (ชม.)", width=85, format="%.2f"),
                            "เรตราคา (บาท/ชม.)": st.column_config.NumberColumn("เรตราคา", width=110, format="%d ฿"),
                            "มูลค่ารวม (บาท)": st.column_config.NumberColumn("รวมเป็นเงิน", width=130, format="%.2f ฿"),
                        },
                        use_container_width=True,
                        hide_index=True
                    )
                else:
                    st.info("ℹ️ ยังไม่มีรายการที่ขึ้นสถานะ '✅ เสร็จสิ้นแล้ว' จึงยังไม่มีการคำนวณมูลค่าต้นทุน")

# ---------------------------------------------------------
# VIEW 3: รายงานสรุปประจำเดือน (Monthly Executive Report)
# ---------------------------------------------------------
elif st.session_state.current_view == "📑 รายงานสรุปประจำเดือน":
    if st.session_state.user_role is None:
        st.subheader("🔒 ยืนยันตัวตนสำหรับเข้าใช้งานรายงานสรุปประจำเดือน")
        st.info("กรุณากรอกรหัสผ่านเพื่อเข้าใช้งาน:\n* **ผู้บริหาร/วางแผน:** รหัสผ่านระดับ Admin หรือ `pes1234`")
        col_pwd, col_btn = st.columns([3, 1])
        with col_pwd:
            input_pwd = st.text_input("รหัสผ่าน (Password):", type="password", key="pwd_monthly_report")
        with col_btn:
            st.write("")
            st.write("")
            if st.button("🔓 เข้าสู่ระบบ", type="primary", use_container_width=True, key="btn_login_monthly"):
                if input_pwd == ADMIN_PASSWORD:
                    st.session_state.user_role = "admin"
                    st.rerun()
                elif input_pwd == VIEWER_PASSWORD:
                    st.session_state.user_role = "viewer"
                    st.rerun()
                else:
                    st.error("รหัสผ่านไม่ถูกต้อง")
    else:
        c_head, c_logout = st.columns([8, 2])
        with c_head:
            st.subheader("📑 รายงานสรุปผลการผลิตและประสิทธิภาพประจำเดือน (Monthly Production & Executive Report)")
        with c_logout:
            if st.button("🚪 ออกจากระบบ", use_container_width=True, key="btn_logout_monthly"):
                st.session_state.user_role = None
                st.rerun()

        df_db = fetch_jobs_from_supabase()

        if "machine_rates" in st.session_state:
            rate_map = dict(zip(st.session_state.machine_rates["เครื่องจักร"], st.session_state.machine_rates["เรตราคา (บาท/ชม.)"]))
        else:
            rate_map = DEFAULT_RATES

        current_now = get_bangkok_now()
        r_col1, r_col2, r_col_exp = st.columns([2, 2, 4])
        
        with r_col1:
            month_names = ["มกราคม (1)", "กุมภาพันธ์ (2)", "มีนาคม (3)", "เมษายน (4)", "พฤษภาคม (5)", "มิถุนายน (6)", "กรกฎาคม (7)", "สิงหาคม (8)", "กันยายน (9)", "ตุลาคม (10)", "พฤศจิกายน (11)", "ธันวาคม (12)"]
            selected_month_idx = st.selectbox("📅 เลือกเดือน:", range(1, 13), index=current_now.month - 1, format_func=lambda x: month_names[x-1])
        with r_col2:
            selected_year = st.selectbox("📆 เลือกปี (ค.ศ.):", [current_now.year - 1, current_now.year, current_now.year + 1], index=1)

        if not df_db.empty:
            finished_all = df_db[df_db["สถานะงาน"].isin(["🟩 เสร็จสิ้นแล้ว", "✅ เสร็จสิ้นแล้ว"])].copy()
            finished_all["เสร็จจริง_DT"] = pd.to_datetime(finished_all["เสร็จจริง"], errors='coerce')
            finished_all["วันขึ้นงาน_DT"] = pd.to_datetime(finished_all["วัน-เวลาขึ้นงาน"], errors='coerce')
            finished_all["Target_Date"] = finished_all["เสร็จจริง_DT"].fillna(finished_all["วันขึ้นงาน_DT"])
            
            monthly_jobs = finished_all[
                (finished_all["Target_Date"].dt.month == selected_month_idx) &
                (finished_all["Target_Date"].dt.year == selected_year)
            ].copy()

            # คำนวณเดือนก่อนหน้า สำหรับเทียบ MoM (Month-over-Month)
            prev_m = 12 if selected_month_idx == 1 else selected_month_idx - 1
            prev_y = selected_year - 1 if selected_month_idx == 1 else selected_year
            prev_monthly_jobs = finished_all[
                (finished_all["Target_Date"].dt.month == prev_m) &
                (finished_all["Target_Date"].dt.year == prev_y)
            ].copy()
        else:
            monthly_jobs = pd.DataFrame()
            prev_monthly_jobs = pd.DataFrame()

        if not monthly_jobs.empty:
            monthly_jobs["Setup (น.)"] = pd.to_numeric(monthly_jobs["Setup (น.)"], errors='coerce').fillna(10.0)
            monthly_jobs["Basic (น.)"] = pd.to_numeric(monthly_jobs["Basic (น.)"], errors='coerce').fillna(0.0)
            monthly_jobs["โปรแกรม (น.)"] = pd.to_numeric(monthly_jobs["โปรแกรม (น.)"], errors='coerce').fillna(0.0)
            monthly_jobs["จำนวน"] = pd.to_numeric(monthly_jobs["จำนวน"], errors='coerce').fillna(1).astype(int)
            monthly_jobs["เวลาแผน (ชม.)"] = ((monthly_jobs["Setup (น.)"] + monthly_jobs["Basic (น.)"] + monthly_jobs["โปรแกรม (น.)"]) / 60.0).round(2)
            
            actual_hrs_list, diff_hrs_list, on_time_list = [], [], []
            for _, r in monthly_jobs.iterrows():
                s_real, f_real = r.get("เริ่มจริง"), r.get("เสร็จจริง")
                if pd.notna(s_real) and pd.notna(f_real):
                    diff_sec = (pd.to_datetime(f_real) - pd.to_datetime(s_real)).total_seconds()
                    act_hrs = round(diff_sec / 3600.0, 2)
                    v_hrs = round(act_hrs - r["เวลาแผน (ชม.)"], 2)
                    actual_hrs_list.append(act_hrs)
                    diff_hrs_list.append(v_hrs)
                    on_time_list.append(1 if act_hrs <= r["เวลาแผน (ชม.)"] else 0)
                else:
                    actual_hrs_list.append(r["เวลาแผน (ชม.)"])
                    diff_hrs_list.append(0.0)
                    on_time_list.append(1)
                    
            monthly_jobs["เวลาจริง (ชม.)"] = actual_hrs_list
            monthly_jobs["ผลต่าง (ชม.)"] = diff_hrs_list
            monthly_jobs["เรตราคา (บาท/ชม.)"] = monthly_jobs["เลือกเครื่องจักร"].map(rate_map).fillna(500)
            monthly_jobs["มูลค่ารวม (บาท)"] = monthly_jobs["เวลาจริง (ชม.)"] * monthly_jobs["เรตราคา (บาท/ชม.)"]

            total_jobs_count = len(monthly_jobs)
            total_qty_pieces = monthly_jobs["จำนวน"].sum()
            total_running_hrs = monthly_jobs["เวลาจริง (ชม.)"].sum()
            total_plan_hrs_m = monthly_jobs["เวลาแผน (ชม.)"].sum()
            total_variance_hrs = monthly_jobs["ผลต่าง (ชม.)"].sum()
            total_output_val = monthly_jobs["มูลค่ารวม (บาท)"].sum()
            on_time_rate = (sum(on_time_list) / total_jobs_count * 100.0) if total_jobs_count > 0 else 100.0

            # คำนวณ MoM เทียบเดือนก่อนหน้า
            if not prev_monthly_jobs.empty:
                prev_qty = prev_monthly_jobs["จำนวน"].sum()
                prev_monthly_jobs["Setup (น.)"] = pd.to_numeric(prev_monthly_jobs["Setup (น.)"], errors='coerce').fillna(10.0)
                prev_monthly_jobs["Basic (น.)"] = pd.to_numeric(prev_monthly_jobs["Basic (น.)"], errors='coerce').fillna(0.0)
                prev_monthly_jobs["โปรแกรม (น.)"] = pd.to_numeric(prev_monthly_jobs["โปรแกรม (น.)"], errors='coerce').fillna(0.0)
                prev_monthly_jobs["เวลาแผน (ชม.)"] = ((prev_monthly_jobs["Setup (น.)"] + prev_monthly_jobs["Basic (น.)"] + prev_monthly_jobs["โปรแกรม (น.)"]) / 60.0).round(2)
                prev_val = sum([r.get("เวลาแผน (ชม.)", 0.0) * rate_map.get(r.get("เลือกเครื่องจักร"), 500) for _, r in prev_monthly_jobs.iterrows()])
                
                growth_qty = ((total_qty_pieces - prev_qty) / prev_qty * 100) if prev_qty > 0 else 0.0
                growth_val = ((total_output_val - prev_val) / prev_val * 100) if prev_val > 0 else 0.0
                growth_qty_str = f"{'+' if growth_qty >= 0 else ''}{growth_qty:.1f}% เทียบเดือนก่อน"
                growth_val_str = f"{'+' if growth_val >= 0 else ''}{growth_val:.1f}% เทียบเดือนก่อน"
            else:
                growth_qty_str = "ไม่มีข้อมูลเดือนก่อนหน้า"
                growth_val_str = "ไม่มีข้อมูลเดือนก่อนหน้า"

            # ---------------------------------------------------------
            # 1. การ์ด KPI หลักประจำเดือน (Executive KPI Cards)
            # ---------------------------------------------------------
            var_color_class = "kpi-green" if total_variance_hrs <= 0 else "kpi-red"
            var_title_txt = f"⚡ เร็วกว่าแผนรวม {abs(total_variance_hrs):.1f} ชม." if total_variance_hrs <= 0 else f"⚠️ ช้ากว่าแผนรวม +{total_variance_hrs:.1f} ชม."

            st.markdown(f"""
            <div class="kpi-container">
                <div class="kpi-card kpi-green">
                    <div class="kpi-title">✅ ชิ้นงานที่ผลิตเสร็จ</div>
                    <div class="kpi-value">{total_qty_pieces:,} <span style="font-size:15px; font-weight:600;">ชิ้น</span></div>
                    <div class="kpi-sub">📊 {growth_qty_str} ({total_jobs_count} คิว)</div>
                </div>
                <div class="kpi-card kpi-blue">
                    <div class="kpi-title">⏱️ ชั่วโมงเดินเครื่องจริง</div>
                    <div class="kpi-value">{total_running_hrs:,.1f} <span style="font-size:15px; font-weight:600;">ชม.</span></div>
                    <div class="kpi-sub">แผนที่ตั้งไว้: {total_plan_hrs_m:,.1f} ชม.</div>
                </div>
                <div class="kpi-card kpi-orange">
                    <div class="kpi-title">💰 มูลค่าผลผลิตรวม</div>
                    <div class="kpi-value">{total_output_val:,.2f} <span style="font-size:15px; font-weight:600;">฿</span></div>
                    <div class="kpi-sub">📈 {growth_val_str}</div>
                </div>
                <div class="kpi-card kpi-purple">
                    <div class="kpi-title">🎯 ส่งมอบตรงแผน (On-Time)</div>
                    <div class="kpi-value">{on_time_rate:.1f} %</div>
                    <div class="kpi-sub">{var_title_txt}</div>
                </div>
            </div>
            """, unsafe_allow_html=True)

            # ---------------------------------------------------------
            # 2. เครื่องจักร และ สัดส่วนการสร้างรายได้ (Machine Performance & Revenue Contribution)
            # ---------------------------------------------------------
            machine_summary = []
            for m in MACHINE_LIST:
                m_sub = monthly_jobs[monthly_jobs["เลือกเครื่องจักร"] == m]
                if not m_sub.empty:
                    m_qty = m_sub["จำนวน"].sum()
                    m_jobs = len(m_sub)
                    m_plan_hrs = m_sub["เวลาแผน (ชม.)"].sum()
                    m_act_hrs = m_sub["เวลาจริง (ชม.)"].sum()
                    m_val = m_sub["มูลค่ารวม (บาท)"].sum()
                    m_contrib = (m_val / total_output_val * 100.0) if total_output_val > 0 else 0.0
                    diff_hrs = round(m_act_hrs - m_plan_hrs, 2)
                    eval_txt = f"🟢 เร็วขึ้น {abs(diff_hrs):.2f} ชม." if diff_hrs <= 0 else f"🔴 ช้ากว่าแผน +{diff_hrs:.2f} ชม."
                    
                    machine_summary.append({
                        "เครื่องจักร / แผนก": m,
                        "จำนวนคิวงาน": m_jobs,
                        "ชิ้นงานรวม (ชิ้น)": m_qty,
                        "เวลาแผน (ชม.)": round(m_plan_hrs, 2),
                        "เวลาจริง (ชม.)": round(m_act_hrs, 2),
                        "ผลต่าง": eval_txt,
                        "เรตราคา": f"{rate_map.get(m, 500):,} ฿",
                        "มูลค่าผลผลิต (บาท)": round(m_val, 2),
                        "สัดส่วนมูลค่า (%)": round(m_contrib, 1)
                    })
            df_m_sum = pd.DataFrame(machine_summary).sort_values(by="มูลค่าผลผลิต (บาท)", ascending=False)

            # ---------------------------------------------------------
            # 3. วิเคราะห์ประสิทธิภาพแยกตามชนิดวัสดุ (Material Insights)
            # ---------------------------------------------------------
            mat_summary = []
            for mat_name, mat_sub in monthly_jobs.groupby("วัสดุ"):
                mat_qty = mat_sub["จำนวน"].sum()
                mat_jobs = len(mat_sub)
                mat_act_hrs = mat_sub["เวลาจริง (ชม.)"].sum()
                mat_val = mat_sub["มูลค่ารวม (บาท)"].sum()
                mat_summary.append({
                    "ชนิดวัสดุ": mat_name if str(mat_name).strip() != "" else "ไม่ระบุ",
                    "จำนวนคิว": mat_jobs,
                    "จำนวนชิ้นงาน (ชิ้น)": mat_qty,
                    "ชั่วโมงผลิตจริง (ชม.)": round(mat_act_hrs, 2),
                    "มูลค่าผลผลิต (บาท)": round(mat_val, 2),
                    "สัดส่วน (%)": round((mat_val / total_output_val * 100.0), 1) if total_output_val > 0 else 0.0
                })
            df_mat_sum = pd.DataFrame(mat_summary).sort_values(by="ชั่วโมงผลิตจริง (ชม.)", ascending=False)

            # ---------------------------------------------------------
            # 4. Top 5 งานที่ใช้เวลาเกินแผนสูงสุด (Top 5 Delays Analysis)
            # ---------------------------------------------------------
            delayed_jobs = monthly_jobs[monthly_jobs["ผลต่าง (ชม.)"] > 0].sort_values(by="ผลต่าง (ชม.)", ascending=False).head(5)

            # ---------------------------------------------------------
            # ส่วน HTML Export สำหรับสั่งพิมพ์ / PDF
            # ---------------------------------------------------------
            rows_m_html = "".join([f"<tr><td>{r['เครื่องจักร / แผนก']}</td><td style='text-align:center;'>{r['จำนวนคิวงาน']}</td><td style='text-align:center;'>{r['ชิ้นงานรวม (ชิ้น)']}</td><td style='text-align:center;'>{r['เวลาแผน (ชม.)']:.2f}</td><td style='text-align:center;'>{r['เวลาจริง (ชม.)']:.2f}</td><td style='text-align:center;'>{r['ผลต่าง']}</td><td style='text-align:right;'>{r['มูลค่าผลผลิต (บาท)']:,.2f} ฿</td><td style='text-align:right; font-weight:bold;'>{r['สัดส่วนมูลค่า (%)']:.1f}%</td></tr>" for _, r in df_m_sum.iterrows()])
            rows_mat_html = "".join([f"<tr><td>{r['ชนิดวัสดุ']}</td><td style='text-align:center;'>{r['จำนวนคิว']}</td><td style='text-align:center;'>{r['จำนวนชิ้นงาน (ชิ้น)']}</td><td style='text-align:center;'>{r['ชั่วโมงผลิตจริง (ชม.)']:.2f}</td><td style='text-align:right;'>{r['มูลค่าผลผลิต (บาท)']:,.2f} ฿</td><td style='text-align:right; font-weight:bold;'>{r['สัดส่วน (%)']:.1f}%</td></tr>" for _, r in df_mat_sum.iterrows()])
            rows_job_html = "".join([f"<tr><td>{r['แผนงาน']}</td><td>{r['ชื่อ Drawing.']}</td><td style='text-align:center;'>{r['จำนวน']}</td><td style='text-align:center;'>{r['วัสดุ']}</td><td>{r['ขั้นตอน (Step)']}</td><td>{r['เลือกเครื่องจักร']}</td><td style='text-align:center;'>{pd.to_datetime(r['เริ่มจริง']).strftime('%d/%m %H:%M') if pd.notna(r['เริ่มจริง']) else '-'}</td><td style='text-align:center;'>{pd.to_datetime(r['เสร็จจริง']).strftime('%d/%m %H:%M') if pd.notna(r['เสร็จจริง']) else '-'}</td><td style='text-align:center;'>{r['เวลาแผน (ชม.)']:.2f}</td><td style='text-align:center;'>{r['เวลาจริง (ชม.)']:.2f}</td><td style='text-align:right;'>{r['มูลค่ารวม (บาท)']:,.2f} ฿</td></tr>" for _, r in monthly_jobs.sort_values(by="Target_Date", ascending=True).iterrows()])

            report_html_full = f"""
            <html>
            <head>
                <meta charset="utf-8">
                <title>PES Executive Monthly Report - {month_names[selected_month_idx-1]} {selected_year}</title>
                <style>
                    @page {{ size: A4 portrait; margin: 8mm 10mm; }}
                    body {{ font-family: 'Tahoma', 'Sarabun', 'Arial', sans-serif; color: #1E293B; margin: 0; padding: 10px; font-size: 10.5px; line-height: 1.35; }}
                    .header-box {{ display: flex; justify-content: space-between; align-items: center; border-bottom: 2px solid #1E3E62; padding-bottom: 6px; margin-bottom: 10px; }}
                    .title-text h2 {{ margin: 0; color: #0B192C; font-size: 16px; }}
                    .title-text p {{ margin: 2px 0 0 0; color: #475569; font-size: 10px; }}
                    .kpi-grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 6px; margin-bottom: 10px; }}
                    .kpi-item {{ background: #F8FAFC; border: 1px solid #CBD5E1; border-radius: 6px; padding: 6px 8px; text-align: center; }}
                    .kpi-item-title {{ font-size: 9.5px; color: #64748B; font-weight: bold; }}
                    .kpi-item-val {{ font-size: 14px; color: #0F172A; font-weight: 800; margin-top: 2px; }}
                    h3 {{ color: #1E3E62; font-size: 11.5px; margin: 10px 0 4px 0; border-left: 4px solid #2563EB; padding-left: 6px; }}
                    table {{ width: 100%; border-collapse: collapse; margin-bottom: 10px; font-size: 9.5px; }}
                    th, td {{ border: 1px solid #CBD5E1; padding: 4px 5px; text-align: left; }}
                    th {{ background-color: #F1F5F9; color: #1E293B; font-weight: bold; }}
                    tr:nth-child(even) {{ background-color: #F8FAFC; }}
                    .sign-box {{ display: flex; justify-content: space-between; margin-top: 25px; padding-top: 10px; }}
                    .sign-col {{ width: 30%; text-align: center; border-top: 1px dashed #94A3B8; padding-top: 4px; font-size: 9.5px; }}
                </style>
            </head>
            <body>
                <div class="header-box">
                    <div class="title-text">
                        <h2>บจก. พลวัฒน์ เอ็นจิเนียริ่ง ซัพพลาย (PES)</h2>
                        <p>รายงานสรุปผลการผลิตและประสิทธิภาพประจำเดือน (Monthly Production & Executive Report)</p>
                    </div>
                    <div style="text-align: right; font-size: 10px;">
                        <b>ประจำเดือน:</b> {month_names[selected_month_idx-1]} {selected_year}<br>
                        <b>วันที่ออกรายงาน:</b> {get_bangkok_now().strftime('%d/%m/%Y %H:%M น.')}
                    </div>
                </div>

                <div class="kpi-grid">
                    <div class="kpi-item"><div class="kpi-item-title">ชิ้นงานที่ผลิตเสร็จ</div><div class="kpi-item-val">{total_qty_pieces:,} ชิ้น</div></div>
                    <div class="kpi-item"><div class="kpi-item-title">ชั่วโมงเดินเครื่องจริง</div><div class="kpi-item-val">{total_running_hrs:,.1f} ชม.</div></div>
                    <div class="kpi-item"><div class="kpi-item-title">มูลค่าผลผลิตรวม</div><div class="kpi-item-val">{total_output_val:,.2f} ฿</div></div>
                    <div class="kpi-item"><div class="kpi-item-title">ตรงตามแผน (On-Time)</div><div class="kpi-item-val">{on_time_rate:.1f} %</div></div>
                </div>

                <h3>1. สรุปผลการทำงานและสัดส่วนรายได้แยกตามเครื่องจักร / แผนก</h3>
                <table>
                    <thead><tr><th>เครื่องจักร / แผนก</th><th>คิว</th><th>ชิ้นงาน</th><th>แผน (ชม.)</th><th>จริง (ชม.)</th><th>ผลต่าง</th><th>มูลค่าผลผลิต (฿)</th><th>สัดส่วน (%)</th></tr></thead>
                    <tbody>{rows_m_html}</tbody>
                </table>

                <h3>2. สรุปการใช้วัสดุและเวลาผลิต (Material Insights)</h3>
                <table>
                    <thead><tr><th>ชนิดวัสดุ</th><th>คิว</th><th>ชิ้นงาน</th><th>ชั่วโมงผลิตจริง (ชม.)</th><th>มูลค่าผลผลิต (฿)</th><th>สัดส่วน (%)</th></tr></thead>
                    <tbody>{rows_mat_html}</tbody>
                </table>

                <h3>3. รายการชิ้นงานที่ผลิตเสร็จสิ้นทั้งหมด</h3>
                <table>
                    <thead><tr><th>แผนงาน</th><th>ชื่อ Drawing</th><th>จำนวน</th><th>วัสดุ</th><th>ขั้นตอน</th><th>สถานี</th><th>เริ่มจริง</th><th>เสร็จจริง</th><th>แผน (ชม.)</th><th>จริง (ชม.)</th><th>มูลค่า (฿)</th></tr></thead>
                    <tbody>{rows_job_html}</tbody>
                </table>

                <div class="sign-box">
                    <div class="sign-col">ผู้จัดทำรายงาน / ฝ่ายวางแผน<br><br><br>( .................................................... )</div>
                    <div class="sign-col">หัวหน้าแผนกผลิต / ผู้ตรวจสอบ<br><br><br>( .................................................... )</div>
                    <div class="sign-col">ผู้จัดการโรงงาน / ผู้อนุมัติ<br><br><br>( .................................................... )</div>
                </div>
            </body>
            </html>
            """
            json_report_html = json.dumps(report_html_full)

            with r_col_exp:
                st.write("")
                b_col_pdf, b_col_csv = st.columns(2)
                with b_col_pdf:
                    components.html(f"""
                    <button onclick="printReport()" style="width:100%; background:linear-gradient(135deg, #DC2626 0%, #EF4444 100%); color:white; border:none; padding:9px 14px; border-radius:8px; font-weight:bold; font-size:13px; cursor:pointer; box-shadow:0 3px 8px rgba(220,38,38,0.25);">
                        📄 พิมพ์ / บันทึก PDF รายงานผู้บริหาร
                    </button>
                    <script>
                        function printReport() {{
                            var reportHtml = {json_report_html};
                            var printWin = window.open('', '_blank');
                            printWin.document.open();
                            printWin.document.write(reportHtml);
                            printWin.document.close();
                            printWin.focus();
                            setTimeout(function() {{ printWin.print(); }}, 500);
                        }}
                    </script>
                    """, height=45)

                with b_col_csv:
                    csv_data = monthly_jobs[[
                        "แผนงาน", "ชื่อ Drawing.", "จำนวน", "วัสดุ", "ขั้นตอน (Step)", 
                        "เลือกเครื่องจักร", "เริ่มจริง", "เสร็จจริง", "เวลาแผน (ชม.)", 
                        "เวลาจริง (ชม.)", "ผลต่าง (ชม.)", "เรตราคา (บาท/ชม.)", "มูลค่ารวม (บาท)"
                    ]].to_csv(index=False).encode('utf-8-sig')
                    
                    st.download_button(
                        label="📥 ดาวน์โหลดเป็น CSV/Excel",
                        data=csv_data,
                        file_name=f"PES_Monthly_Report_{selected_year}_{selected_month_idx:02d}.csv",
                        mime="text/csv",
                        type="secondary",
                        use_container_width=True
                    )

            st.divider()

            # ---------------------------------------------------------
            # ส่วนแสดงตารางและกราฟวิเคราะห์เชิงลึก
            # ---------------------------------------------------------
            col_sec1, col_sec2 = st.columns([1.5, 1])

            with col_sec1:
                st.markdown("#### 🏭 สรุปประสิทธิภาพและสัดส่วนรายได้แยกตามเครื่องจักร (Machine ROI & Revenue)")
                st.dataframe(
                    df_m_sum,
                    column_config={
                        "เครื่องจักร / แผนก": st.column_config.TextColumn("เครื่องจักร", width=150),
                        "จำนวนคิวงาน": st.column_config.NumberColumn("คิว", width=70, format="%d"),
                        "ชิ้นงานรวม (ชิ้น)": st.column_config.NumberColumn("ชิ้นงาน", width=85, format="%d"),
                        "เวลาแผน (ชม.)": st.column_config.NumberColumn("แผน (ชม.)", width=85, format="%.2f"),
                        "เวลาจริง (ชม.)": st.column_config.NumberColumn("จริง (ชม.)", width=85, format="%.2f"),
                        "ผลต่าง": st.column_config.TextColumn("ผลต่างเวลา", width=125),
                        "มูลค่าผลผลิต (บาท)": st.column_config.NumberColumn("มูลค่ารวม (บาท)", width=130, format="%.2f ฿"),
                        "สัดส่วนมูลค่า (%)": st.column_config.ProgressColumn("สัดส่วน", width=110, min_value=0, max_value=100, format="%d%%")
                    },
                    hide_index=True,
                    use_container_width=True
                )

            with col_sec2:
                st.markdown("#### 🔩 ประสิทธิภาพแยกตามชนิดวัสดุ (Material Insights)")
                st.dataframe(
                    df_mat_sum,
                    column_config={
                        "ชนิดวัสดุ": st.column_config.TextColumn("วัสดุ", width=100),
                        "จำนวนคิว": st.column_config.NumberColumn("คิว", width=65),
                        "จำนวนชิ้นงาน (ชิ้น)": st.column_config.NumberColumn("ชิ้น", width=75),
                        "ชั่วโมงผลิตจริง (ชม.)": st.column_config.NumberColumn("ชั่วโมงจริง", width=100, format="%.1f ชม."),
                        "มูลค่าผลผลิต (บาท)": st.column_config.NumberColumn("มูลค่า (บาท)", width=120, format="%.2f ฿"),
                        "สัดส่วน (%)": st.column_config.ProgressColumn("สัดส่วน", width=95, min_value=0, max_value=100, format="%d%%")
                    },
                    hide_index=True,
                    use_container_width=True
                )

            st.divider()

            # ---------------------------------------------------------
            # กราฟวิเคราะห์และ Top 5 Delay Analysis
            # ---------------------------------------------------------
            chart_c1, chart_c2 = st.columns(2)
            with chart_c1:
                fig_m_val = px.bar(
                    df_m_sum.sort_values(by="มูลค่าผลผลิต (บาท)", ascending=True),
                    x="มูลค่าผลผลิต (บาท)",
                    y="เครื่องจักร / แผนก",
                    orientation="h",
                    title="💰 อันดับมูลค่าผลผลิตแยกตามเครื่องจักร (บาท)",
                    color="มูลค่าผลผลิต (บาท)",
                    color_continuous_scale="Blues"
                )
                fig_m_val.update_layout(height=360, plot_bgcolor="#FFFFFF", paper_bgcolor="#FFFFFF", margin=dict(l=20, r=20, t=40, b=20))
                st.plotly_chart(fig_m_val, use_container_width=True)

            with chart_c2:
                st.markdown("#### ⚠️ 5 อันดับงานที่ผลิตช้ากว่าแผนมากที่สุด (Top 5 Delays)")
                if not delayed_jobs.empty:
                    st.dataframe(
                        delayed_jobs[["แผนงาน", "ชื่อ Drawing.", "ขั้นตอน (Step)", "เลือกเครื่องจักร", "เวลาแผน (ชม.)", "เวลาจริง (ชม.)", "ผลต่าง (ชม.)"]],
                        column_config={
                            "แผนงาน": st.column_config.TextColumn("แผนงาน", width=80),
                            "ชื่อ Drawing.": st.column_config.TextColumn("Drawing", width=160),
                            "ขั้นตอน (Step)": st.column_config.TextColumn("ขั้นตอน", width=100),
                            "เลือกเครื่องจักร": st.column_config.TextColumn("สถานี", width=120),
                            "เวลาแผน (ชม.)": st.column_config.NumberColumn("แผน (ชม.)", width=85, format="%.2f"),
                            "เวลาจริง (ชม.)": st.column_config.NumberColumn("จริง (ชม.)", width=85, format="%.2f"),
                            "ผลต่าง (ชม.)": st.column_config.NumberColumn("เกินแผน (+ชม.)", width=110, format="+%.2f ชม."),
                        },
                        hide_index=True,
                        use_container_width=True
                    )
                else:
                    st.success("🎉 ไม่มีงานใดที่ผลิตช้ากว่าเวลาแผนที่ตั้งไว้")

            st.divider()

            # รายละเอียดงานทั้งหมด
            st.markdown(f"#### 📋 รายละเอียดชิ้นงานทั้งหมดที่เสร็จสิ้นในเดือน {month_names[selected_month_idx-1]}")
            st.dataframe(
                monthly_jobs.sort_values(by="Target_Date", ascending=True)[[
                    "แผนงาน", "ชื่อ Drawing.", "จำนวน", "วัสดุ", "ขั้นตอน (Step)", 
                    "เลือกเครื่องจักร", "เริ่มจริง", "เสร็จจริง", "เวลาแผน (ชม.)", 
                    "เวลาจริง (ชม.)", "ผลต่าง (ชม.)", "มูลค่ารวม (บาท)"
                ]],
                column_config={
                    "แผนงาน": st.column_config.TextColumn("แผนงาน", width=85),
                    "ชื่อ Drawing.": st.column_config.TextColumn("ชื่อ Drawing.", width=180),
                    "จำนวน": st.column_config.NumberColumn("จำนวน", width=70, format="%d"),
                    "วัสดุ": st.column_config.TextColumn("วัสดุ", width=80),
                    "ขั้นตอน (Step)": st.column_config.TextColumn("ขั้นตอน", width=120),
                    "เลือกเครื่องจักร": st.column_config.TextColumn("สถานีผลิต", width=140),
                    "เริ่มจริง": st.column_config.DatetimeColumn("เริ่มจริง", width=140, format="DD/MM HH:mm"),
                    "เสร็จจริง": st.column_config.DatetimeColumn("เสร็จจริง", width=140, format="DD/MM HH:mm"),
                    "เวลาแผน (ชม.)": st.column_config.NumberColumn("แผน (ชม.)", width=85, format="%.2f"),
                    "เวลาจริง (ชม.)": st.column_config.NumberColumn("จริง (ชม.)", width=85, format="%.2f"),
                    "ผลต่าง (ชม.)": st.column_config.NumberColumn("Diff", width=80, format="%.2f"),
                    "มูลค่ารวม (บาท)": st.column_config.NumberColumn("มูลค่า (บาท)", width=120, format="%.2f ฿"),
                },
                hide_index=True,
                use_container_width=True
            )

        else:
            st.info(f"ℹ️ ยังไม่มีประวัติงานที่ขึ้นสถานะ '✅ เสร็จสิ้นแล้ว' ในเดือน {month_names[selected_month_idx-1]} {selected_year}")

# ---------------------------------------------------------
# VIEW 4: จอทีวีกลางโรงงาน (Shop Floor TV Live Dashboard)
# ---------------------------------------------------------
elif st.session_state.current_view == "📺 จอทีวีกลางโรงงาน (TV Live)":
    st.cache_data.clear()
    df_live = fetch_jobs_from_supabase()

    now_bangkok = get_bangkok_now()
    cur_date_str = now_bangkok.strftime("%d/%m/%Y")

    planned_finish_map_tv = {}
    if not df_live.empty:
        _, df_summary_tv, _, _ = calculate_shop_schedule(df_live, now_bangkok.replace(tzinfo=None))
        if not df_summary_tv.empty:
            for _, s_row in df_summary_tv.iterrows():
                planned_finish_map_tv[(str(s_row["แผนงาน"]), str(s_row["ชื่อ Drawing."]))] = s_row.get("เวลาจบงาน_DT")

    machine_status_cards = []
    running_machines_count = 0
    hold_machines_count = 0
    idle_machines_count = 0

    for m in MACHINE_LIST:
        m_jobs = df_live[df_live["เลือกเครื่องจักร"] == m] if not df_live.empty else pd.DataFrame()
        
        running_job = m_jobs[m_jobs["สถานะงาน"].str.contains("กำลังผลิต")]
        hold_job = m_jobs[m_jobs["สถานะงาน"].str.contains("พักงาน")]
        waiting_jobs = m_jobs[m_jobs["สถานะงาน"].str.contains("รอคิว")]

        hold_alert_html = ""
        if not hold_job.empty:
            hold_machines_count += 1
            h_first = hold_job.iloc[0]
            h_start = h_first.get("เริ่มจริง")
            h_start_txt = ""
            if pd.notna(h_start):
                h_start_dt = pd.to_datetime(h_start)
                h_start_txt = f" [เริ่ม {h_start_dt.strftime('%H:%M น.')}]"
            hold_alert_html = f'<div style="margin-top:5px; padding:3px 6px; background:rgba(217, 119, 6, 0.35); border:1px dashed #FCD34D; border-radius:6px; font-size:11px; color:#FEF08A;">🛑 <b>พักงานรอ:</b> {h_first.get("แผนงาน", "-")} ({h_first.get("ชื่อ Drawing.", "-")}){h_start_txt}</div>'

        if not running_job.empty:
            running_machines_count += 1
            r_info = running_job.iloc[0]
            s_start = r_info.get("เริ่มจริง")
            p_code = str(r_info.get("แผนงาน", "-"))
            d_code = str(r_info.get("ชื่อ Drawing.", "-"))
            
            elapsed_txt = "-"
            start_disp_txt = "-"
            if pd.notna(s_start):
                start_dt = pd.to_datetime(s_start)
                start_disp_txt = start_dt.strftime("%H:%M น.")
                elapsed_min = int((now_bangkok.replace(tzinfo=None) - start_dt).total_seconds() / 60.0)
                elapsed_txt = f"{elapsed_min} นาที ({elapsed_min/60.0:.1f} ชม.)"
            
            tv_card_cls = "tv-card tv-card-running"
            badge_html = '<span class="tv-pulse-dot"></span> <b style="color:#A7F3D0; margin-left:6px;">กำลังรันงาน</b>'
            
            f_dt = planned_finish_map_tv.get((p_code, d_code))
            if f_dt is not None and pd.notna(f_dt):
                diff_mins = (f_dt - now_bangkok.replace(tzinfo=None)).total_seconds() / 60.0
                if diff_mins < 0:
                    tv_card_cls = "tv-card tv-card-late"
                    badge_html = '<span class="tv-pulse-dot" style="background-color:#F87171;"></span> <b style="color:#FFFFFF; margin-left:6px;">🔴 เกินเวลาแผน</b>'
                elif 0 <= diff_mins <= 60:
                    tv_card_cls = "tv-card tv-card-warning"
                    badge_html = '<span class="tv-pulse-dot" style="background-color:#FCD34D;"></span> <b style="color:#FFFFFF; margin-left:6px;">🟡 ใกล้เสร็จ (<1 ชม.)</b>'

            time_info_combined = f'<div style="font-size:12px; font-weight:700; color:#FFFFFF;">🚀 <b>เริ่ม:</b> <span style="color:#93C5FD;">{start_disp_txt}</span> | ⏱️ <b>รันแล้ว:</b> {elapsed_txt}</div>{hold_alert_html}'

            machine_status_cards.append({
                "machine": m,
                "status": "RUNNING",
                "card_class": tv_card_cls,
                "badge_html": badge_html,
                "plan": p_code,
                "drawing": d_code,
                "step": str(r_info.get("ขั้นตอน (Step)", "-")),
                "time_info": time_info_combined
            })
        elif not hold_job.empty:
            h_info = hold_job.iloc[0]
            h_start = h_info.get("เริ่มจริง")
            h_start_txt = ""
            if pd.notna(h_start):
                h_start_dt = pd.to_datetime(h_start)
                h_start_txt = f" (เริ่มไว้: {h_start_dt.strftime('%H:%M น.')})"
            machine_status_cards.append({
                "machine": m,
                "status": "HOLD",
                "card_class": "tv-card tv-card-hold",
                "badge_html": '<b style="color:#FDE68A;">🛑 พักงาน (รอวัสดุ)</b>',
                "plan": str(h_info.get("แผนงาน", "-")),
                "drawing": str(h_info.get("ชื่อ Drawing.", "-")),
                "step": str(h_info.get("ขั้นตอน (Step)", "-")),
                "time_info": f"<div style='font-size:12px; font-weight:700; color:#FEF3C7;'>⚠️ เครื่องหยุด: รอเบิกวัสดุใหม่{h_start_txt}</div>"
            })
        else:
            idle_machines_count += 1
            next_txt = "ไม่มีคิวรอ"
            if not waiting_jobs.empty:
                w_first = waiting_jobs.iloc[0]
                next_plan = f"{w_first.get('แผนงาน', '-')} ({w_first.get('ชื่อ Drawing.', '-')})"
                next_txt = f"คิวถัดไป: {next_plan}"

            machine_status_cards.append({
                "machine": m,
                "status": "IDLE",
                "card_class": "tv-card tv-card-idle",
                "badge_html": '<b style="color:#94A3B8;">⚪ เครื่องว่าง (IDLE)</b>',
                "plan": "พร้อมรับงาน",
                "drawing": next_txt,
                "step": "-",
                "time_info": f"<div style='font-size:12px; font-weight:600; color:#CBD5E1;'>📋 คิวรอ: {len(waiting_jobs)} งาน</div>"
            })

    st.markdown(f"""
    <div style="background:#0F172A; border:2px solid #1E3A8A; border-radius:16px; padding:14px 22px; color:white; display:flex; justify-content:space-between; align-items:center; margin-bottom:14px; box-shadow:0 8px 24px rgba(0,0,0,0.3);">
        <div>
            <div style="font-size:22px; font-weight:800; color:#38BDF8; display:flex; align-items:center; gap:10px;">
                <span>📺 PES SHOP FLOOR LIVE MONITOR</span>
                <span style="font-size:12px; background:#1E293B; border:1px solid #38BDF8; color:#38BDF8; padding:3px 10px; border-radius:20px;">Auto-Refresh 30s</span>
            </div>
            <div style="color:#94A3B8; font-size:13px; margin-top:2px;">
                สถานะการผลิต 17 สถานีงานแบบ Real-time | ประจำวันที่ <b>{cur_date_str}</b>
            </div>
        </div>
        <div style="text-align:right;">
            <div id="live-tv-clock" style="font-size:28px; font-weight:900; color:#F8FAFC; font-family:monospace; letter-spacing:1px;">--:--:-- น.</div>
            <div style="font-size:13px; font-weight:bold;">
                <span style="color:#34D399;">🟢 กำลังรัน {running_machines_count}</span> | 
                <span style="color:#FBBF24;">🟡 พักงาน {hold_machines_count}</span> | 
                <span style="color:#94A3B8;">⚪ ว่าง {idle_machines_count}</span>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    card_items = []
    for c in machine_status_cards:
        card_item = (
            f'<div class="{c["card_class"]}">'
            f'<div style="display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:6px;">'
            f'<div style="font-size:17px; font-weight:800; letter-spacing:0.3px;">{c["machine"]}</div>'
            f'<div style="font-size:11px;">{c["badge_html"]}</div>'
            f'</div>'
            f'<div style="margin: 4px 0;">'
            f'<div style="font-size:14px; font-weight:700; color:#FFFFFF; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">📌 {c["plan"]}</div>'
            f'<div style="font-size:12px; color:rgba(255,255,255,0.85); white-space:nowrap; overflow:hidden; text-overflow:ellipsis; margin-top:2px;">📄 {c["drawing"]}</div>'
            f'<div style="font-size:11.5px; color:rgba(255,255,255,0.7); margin-top:2px;">⚙️ ขั้นตอน: {c["step"]}</div>'
            f'</div>'
            f'<div style="margin-top:8px; padding-top:6px; border-top:1px solid rgba(255,255,255,0.15);">'
            f'{c["time_info"]}'
            f'</div>'
            f'</div>'
        )
        card_items.append(card_item)

    full_grid_html = '<div class="tv-grid-container">' + "".join(card_items) + '</div>'
    st.markdown(full_grid_html, unsafe_allow_html=True)

    components.html("""
    <script>
        function updateLiveClock() {
            const now = new Date();
            const hrs = String(now.getHours()).padStart(2, '0');
            const mins = String(now.getMinutes()).padStart(2, '0');
            const secs = String(now.getSeconds()).padStart(2, '0');
            const clockEl = window.parent.document.getElementById('live-tv-clock');
            if (clockEl) {
                clockEl.innerText = `${hrs}:${mins}:${secs} น.`;
            }
        }
        setInterval(updateLiveClock, 1000);
        updateLiveClock();

        setTimeout(function() {
            const radioBtns = window.parent.document.querySelectorAll('input[type="radio"]');
            if (radioBtns && radioBtns.length >= 4 && radioBtns[3].checked) {
                radioBtns[3].click();
            }
        }, 30000);
    </script>
    """, height=0)
