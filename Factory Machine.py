import streamlit as st
import pandas as pd
import plotly.express as px
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
    if s in ["", "None", "nan", "NaN", "null", "-", "NaT"]:
        return None
    
    s = s.replace('T', ' ').split('+')[0].split('Z')[0].strip()
    current_year = get_bangkok_now().year

    # กรณีรูปแบบมาตรฐานฐานข้อมูล YYYY-MM-DD
    if "-" in s:
        parts_dash = s.split(" ")[0].split("-")
        if len(parts_dash) == 3 and len(parts_dash[0]) == 4:
            dt_parsed = pd.to_datetime(s, errors='coerce')
            return dt_parsed.tz_localize(None) if (pd.notna(dt_parsed) and getattr(dt_parsed, 'tzinfo', None) is not None) else dt_parsed

    # บังคับอ่านแบบ วัน/เดือน/ปี (Day-First)
    if "/" in s:
        date_part = s.split(" ")[0]
        time_part = s.split(" ")[1] if len(s.split(" ")) > 1 else "08:30:00"
        parts = date_part.split("/")
        
        if len(parts) == 2:
            d, m = parts[0].zfill(2), parts[1].zfill(2)
            s_fixed = f"{current_year}-{m}-{d} {time_part}"
            dt_parsed = pd.to_datetime(s_fixed, format="%Y-%m-%d %H:%M:%S", errors='coerce')
            return dt_parsed
        elif len(parts) == 3:
            d, m, y = parts[0].zfill(2), parts[1].zfill(2), parts[2]
            if len(y) == 2: y = f"20{y}"
            s_fixed = f"{y}-{m}-{d} {time_part}"
            dt_parsed = pd.to_datetime(s_fixed, format="%Y-%m-%d %H:%M:%S", errors='coerce')
            return dt_parsed

    dt_parsed = pd.to_datetime(s, errors='coerce', dayfirst=True)
    if pd.notna(dt_parsed):
        if getattr(dt_parsed, 'tzinfo', None) is not None:
            return dt_parsed.tz_localize(None)
        return dt_parsed
    return None

def to_bangkok_epoch_ms(dt_val):
    if dt_val is None or pd.isna(dt_val):
        return 0
    dt_p = parse_flexible_datetime(dt_val)
    if dt_p is None or pd.isna(dt_p):
        return 0
    try:
        bkk_tz = zoneinfo.ZoneInfo("Asia/Bangkok")
        if dt_p.tzinfo is None:
            dt_p = dt_p.replace(tzinfo=bkk_tz)
        else:
            dt_p = dt_p.astimezone(bkk_tz)
        return int(dt_p.timestamp() * 1000)
    except Exception:
        return int((pd.to_datetime(dt_p) - pd.Timestamp("1970-01-01") - pd.Timedelta(hours=7)).total_seconds() * 1000)

def get_day_working_windows(dt_date):
    weekday = dt_date.weekday()
    if weekday == 6:
        return []
    elif weekday == 5:
        # วันเสาร์: 08:30 - 17:00 น.
        return [
            (datetime.combine(dt_date, dtime(8, 30)), datetime.combine(dt_date, dtime(10, 0))),
            (datetime.combine(dt_date, dtime(10, 10)), datetime.combine(dt_date, dtime(12, 0))),
            (datetime.combine(dt_date, dtime(13, 0)), datetime.combine(dt_date, dtime(15, 0))),
            (datetime.combine(dt_date, dtime(15, 10)), datetime.combine(dt_date, dtime(17, 0)))
        ]
    else:
        # วันจันทร์ - ศุกร์: 08:30 - 20:00 น.
        return [
            (datetime.combine(dt_date, dtime(8, 30)), datetime.combine(dt_date, dtime(10, 0))),
            (datetime.combine(dt_date, dtime(10, 10)), datetime.combine(dt_date, dtime(12, 0))),
            (datetime.combine(dt_date, dtime(13, 0)), datetime.combine(dt_date, dtime(15, 0))),
            (datetime.combine(dt_date, dtime(15, 10)), datetime.combine(dt_date, dtime(17, 0))),
            (datetime.combine(dt_date, dtime(17, 30)), datetime.combine(dt_date, dtime(20, 0)))
        ]

def get_next_valid_work_time(dt: datetime) -> datetime:
    cur_date = dt.date()
    for _ in range(14):
        windows = get_day_working_windows(cur_date)
        for w_start, w_end in windows:
            if dt <= w_start:
                return w_start
            elif w_start < dt < w_end:
                return dt
        cur_date += timedelta(days=1)
        dt = datetime.combine(cur_date, dtime(8, 30))
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
            current_dt = get_next_valid_work_time(current_dt + timedelta(minutes=5))
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
    step_code = str(row.get("ขั้นตอน (Step)", ""))
    job_id = str(row.get("ID", ""))

    if "กำลังผลิต" in status:
        finish_dt = planned_finish_map.get(job_id) or planned_finish_map.get((p_code, d_code, step_code)) or planned_finish_map.get((p_code, d_code))
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
    .kpi-red { background: linear-gradient(135deg, #991B1B 0%, #DC2626 100%); }
    
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

    .step-card {
        background: #FFFFFF;
        padding: 14px 16px;
        border-radius: 14px;
        border: 1.5px solid #E2E8F0;
        margin-bottom: 12px;
        box-shadow: 0 2px 8px rgba(0,0,0,0.02);
    }

    div.stButton > button:disabled {
        background-color: #F1F5F9 !important;
        color: #94A3B8 !important;
        border-color: #CBD5E1 !important;
        cursor: not-allowed !important;
    }

    .tv-grid-container {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
        gap: 10px;
        margin-top: 8px;
    }
    .tv-card {
        border-radius: 12px;
        padding: 12px 14px;
        color: #FFFFFF !important;
        box-shadow: 0 4px 14px rgba(0,0,0,0.12);
        display: flex;
        flex-direction: column;
        justify-content: space-between;
        min-height: 140px;
        border: 1px solid rgba(255,255,255,0.12);
    }
    .tv-card-running {
        background: linear-gradient(135deg, #065F46 0%, #059669 100%) !important;
        border-left: 7px solid #34D399 !important;
    }
    
    @keyframes pulse-card-warning {
        0% { box-shadow: 0 0 6px rgba(245, 158, 11, 0.4); }
        50% { box-shadow: 0 0 20px rgba(245, 158, 11, 0.9); }
        100% { box-shadow: 0 0 6px rgba(245, 158, 11, 0.4); }
    }
    @keyframes pulse-card-late {
        0% { box-shadow: 0 0 6px rgba(239, 68, 68, 0.5); }
        50% { box-shadow: 0 0 25px rgba(239, 68, 68, 1); }
        100% { box-shadow: 0 0 6px rgba(239, 68, 68, 0.5); }
    }
    
    .tv-card-warning {
        background: linear-gradient(135deg, #9A3412 0%, #C2410C 100%) !important;
        border-left: 7px solid #FDE047 !important;
        border-top: 1px solid rgba(253, 224, 71, 0.4) !important;
        animation: pulse-card-warning 1.8s infinite ease-in-out !important;
    }
    .tv-card-late {
        background: linear-gradient(135deg, #7F1D1D 0%, #991B1B 100%) !important;
        border-left: 7px solid #EF4444 !important;
        border-top: 1px solid rgba(239, 68, 68, 0.5) !important;
        animation: pulse-card-late 1.2s infinite ease-in-out !important;
    }

    .tv-card-hold {
        background: linear-gradient(135deg, #92400E 0%, #D97706 100%) !important;
        border-left: 7px solid #FBBF24 !important;
    }
    .tv-card-idle {
        background: linear-gradient(135deg, #1E293B 0%, #334155 100%) !important;
        border-left: 7px solid #64748B !important;
        opacity: 0.92;
    }

    .tv-pulse-dot {
        width: 13px !important;
        height: 13px !important;
        border-radius: 50% !important;
        background-color: #10B981 !important;
        border: 2px solid #FFFFFF !important;
        display: inline-block !important;
        vertical-align: middle !important;
        box-shadow: 0 0 8px #10B981, 0 0 16px rgba(16, 185, 129, 0.8) !important;
        animation: tv-pulse-green 1.5s infinite ease-in-out !important;
    }
    @keyframes tv-pulse-green {
        0% { transform: scale(0.9); box-shadow: 0 0 4px #10B981, 0 0 0 0 rgba(16, 185, 129, 0.9); }
        50% { transform: scale(1.15); box-shadow: 0 0 12px #34D399, 0 0 0 8px rgba(16, 185, 129, 0); }
        100% { transform: scale(0.9); box-shadow: 0 0 4px #10B981, 0 0 0 0 rgba(16, 185, 129, 0); }
    }

    .tv-pulse-dot-warning {
        width: 13px !important;
        height: 13px !important;
        border-radius: 50% !important;
        background-color: #FACC15 !important;
        border: 2px solid #FFFFFF !important;
        display: inline-block !important;
        vertical-align: middle !important;
        box-shadow: 0 0 10px #FACC15, 0 0 18px rgba(250, 204, 21, 0.9) !important;
        animation: tv-pulse-yellow 1.1s infinite ease-in-out !important;
    }
    @keyframes tv-pulse-yellow {
        0% { transform: scale(0.9); box-shadow: 0 0 4px #FACC15, 0 0 0 0 rgba(250, 204, 21, 0.9); }
        50% { transform: scale(1.2); box-shadow: 0 0 14px #FEF08A, 0 0 0 9px rgba(250, 204, 21, 0); }
        100% { transform: scale(0.9); box-shadow: 0 0 4px #FACC15, 0 0 0 0 rgba(250, 204, 21, 0); }
    }

    .tv-pulse-dot-late {
        width: 13px !important;
        height: 13px !important;
        border-radius: 50% !important;
        background-color: #EF4444 !important;
        border: 2px solid #FFFFFF !important;
        display: inline-block !important;
        vertical-align: middle !important;
        box-shadow: 0 0 10px #EF4444, 0 0 20px rgba(239, 68, 68, 1) !important;
        animation: tv-pulse-red 0.8s infinite ease-in-out !important;
    }
    @keyframes tv-pulse-red {
        0% { transform: scale(0.9); box-shadow: 0 0 6px #EF4444, 0 0 0 0 rgba(239, 68, 68, 1); }
        50% { transform: scale(1.25); box-shadow: 0 0 18px #F87171, 0 0 0 11px rgba(239, 68, 68, 0); }
        100% { transform: scale(0.9); box-shadow: 0 0 6px #EF4444, 0 0 0 0 rgba(239, 68, 68, 0); }
    }
</style>
""", unsafe_allow_html=True)

header_content = f'''<div class="main-header">{logo_html}<div class="header-text"><h1>ระบบติดตามและบันทึกงานหน้าเครื่องแผนกผลิต</h1><p>จ.-ศ. (08:30-20:00 น.) | ส. (08:30-17:00 น.) | เบรกเช้า 10:00-10:10 น. | พักเที่ยง 12:00-13:00 น. | เบรกบ่าย 15:00-15:10 น. | หยุดวันอาทิตย์</p></div></div>'''
st.markdown(header_content, unsafe_allow_html=True)

# =========================================================
# 3. กำหนดสิทธิ์และความปลอดภัย & ตัวแปรเริ่มต้นระบบ
# =========================================================
ADMIN_PASSWORD = "pesadmin"
VIEWER_PASSWORD = "pes1234"

default_states = {
    "user_role": None,
    "current_view": "👷 โหมดช่างหน้าเครื่อง",
    "active_select_all": False,
    "finish_select_all": False,
    "scroll_to_bottom": False,
    "gantt_date_range": None,
    "drawing_tracker_filter": "ALL",
    "wo_color_filter": "ALL",
    "cleared_finish_jobs": set()
}
for k, v in default_states.items():
    if k not in st.session_state:
        st.session_state[k] = v

query_params = st.query_params
if query_params.get("view") == "tv":
    st.session_state.current_view = "📺 จอทีวีกลางโรงงาน (TV Live)"

MACHINE_LIST = [
    "No.1 Awea", "No.2 Awea", "No.3 Hartford", "No.4 Sanco", "No.5 Hartford",
    "No.6 Bridgeport", "No.7 Bridgeport", "No.8 Hartford", "No.9 Mikron",
    "No.10 เครื่องเจียรราบ", "No.11 เครื่องเจียรกลม",
    "No.12 มิลลิ่ง 1", "No.13 มิลลิ่ง 2", "No.14 มิลลิ่ง 3", "No.15 มิลลิ่ง 4",
    "No.16 เครื่องกลึง",
    "MIG CO2-No.01", "MIG CO2-No.02", "MIG CO2-No.03",
    "ARGON-No.01", "ARGON-No.02", "WELDING_ALUMINUM-No.01"
]

DEFAULT_RATES = {
    "No.1 Awea": 1200, "No.2 Awea": 1000, "No.3 Hartford": 1000, "No.4 Sanco": 1000,
    "No.5 Hartford": 1000, "No.6 Bridgeport": 600, "No.7 Bridgeport": 600, "No.8 Hartford": 600, "No.9 Mikron": 1300,
    "No.10 เครื่องเจียรราบ": 500, "No.11 เครื่องเจียรกลม": 500,
    "No.12 มิลลิ่ง 1": 400, "No.13 มิลลิ่ง 2": 400, "No.14 มิลลิ่ง 3": 400, "No.15 มิลลิ่ง 4": 400,
    "No.16 เครื่องกลึง": 400,
    "MIG CO2-No.01": 450, "MIG CO2-No.02": 450, "MIG CO2-No.03": 450,
    "ARGON-No.01": 450, "ARGON-No.02": 450, "WELDING_ALUMINUM-No.01": 500
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
                    df["actual_start"] = df["actual_start"].apply(parse_flexible_datetime)
                if "actual_finish" in df.columns:
                    df["actual_finish"] = df["actual_finish"].apply(parse_flexible_datetime)
                
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
def calculate_shop_schedule(jobs_df, default_start_datetime=None):
    active_mask = jobs_df["สถานะงาน"].isin(["🟧 รอคิวผลิต", "🟦 กำลังผลิต", "🟨 พักงาน (รอวัสดุ)", "⏳ รอคิวผลิต", "⚙️ กำลังผลิต"])
    valid_jobs = []
    
    all_ready_candidates = []
    for j in jobs_df[active_mask].to_dict("records"):
        is_running_job = "กำลังผลิต" in str(j.get("สถานะงาน", ""))
        
        ready_time = j.get("วัน-เวลาขึ้นงาน")
        dt_val = parse_flexible_datetime(ready_time)

        if dt_val is None and is_running_job and pd.notna(j.get("เริ่มจริง")):
            dt_val = parse_flexible_datetime(j.get("เริ่มจริง"))
            
        if dt_val is None:
            dt_val = default_start_datetime if default_start_datetime is not None else get_bangkok_now().replace(tzinfo=None)
            
        j["ready_at"] = get_next_valid_work_time(dt_val.to_pydatetime() if isinstance(dt_val, pd.Timestamp) else dt_val)
        all_ready_candidates.append(j["ready_at"])

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
        j["need_setup"] = not is_running_job
        valid_jobs.append(j)
        
    earliest_plan_start = min(all_ready_candidates) if all_ready_candidates else get_bangkok_now().replace(tzinfo=None)
    m_available = {m: get_next_valid_work_time(earliest_plan_start) for m in MACHINE_LIST}
    m_busy_hrs = {m: 0.0 for m in MACHINE_LIST}
    
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
        
        ready_candidates = [
            j for j in valid_jobs if (j.get("เลือกเครื่องจักร") == earliest_m or 
            (j.get("เลือกเครื่องจักร") == "อัตโนมัติ (เครื่อง 3 แกนใดก็ได้)" and earliest_m in MACHINE_LIST[:8]))
        ]
        
        if not ready_candidates:
            break
            
        def job_priority_key(x):
            is_run = 0 if "กำลังผลิต" in str(x["สถานะงาน"]) else 1
            is_urg = 0 if x["is_urgent"] else 1
            r_dt = x["ready_at"] if pd.notna(x["ready_at"]) else pd.Timestamp.max
            return (is_run, is_urg, r_dt, safe_int(x.get("ID")))

        ready_candidates.sort(key=job_priority_key)
        selected_job = ready_candidates[0]

        # หากเครื่องว่างช้ากว่าเวลาขึ้นงานเดิม ให้เริ่มเมื่อเครื่องว่าง (Chain Logic)
        job_ready_time = selected_job["ready_at"]
        if cur_time < job_ready_time:
            cur_time = get_next_valid_work_time(job_ready_time)

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
        orig_ready_dt = parse_flexible_datetime(selected_job.get("วัน-เวลาขึ้นงาน"))

        summary_records.append({
            "ID": selected_job.get("ID", ""), 
            "เครื่องจักร": earliest_m, 
            "สถานะ": selected_job["สถานะงาน"],
            "ประเภทงาน": "🔴 งานด่วนแทรก" if selected_job["is_urgent"] else "🟢 งานปกติ",
            "แผนงาน": job_code, 
            "ชื่อ Drawing.": drawing_name, 
            "จำนวน": safe_int(selected_job.get("จำนวน"), 1),
            "วัสดุ": selected_job.get("วัสดุ", "-"), 
            "ขั้นตอน (Step)": step_raw, 
            "กำหนดพร้อมขึ้นงาน": orig_ready_dt.strftime("%d/%m/%Y %H:%M") if (orig_ready_dt is not None and pd.notna(orig_ready_dt)) else "-",
            "เวลาเริ่มจริง": setup_start,
            "เวลาเริ่ม Setup": setup_start.strftime("%d/%m %H:%M") if setup_mins > 0 else "-",
            "เวลาเริ่มขึ้นงาน": cut_start.strftime("%d/%m %H:%M"), 
            "เวลาจบงาน": cut_end.strftime("%d/%m/%Y %H:%M"),
            "เวลาจบงาน_DT": cut_end,
            "Setup (น.)": int(setup_mins), 
            "Basic (น.)": int(selected_job["basic_mins"]), 
            "โปรแกรม (น.)": int(selected_job["prog_mins"]), 
            "รวม (ชม.)": round(total_cycle, 2)
        })
        
        m_available[earliest_m] = cut_end
        m_busy_hrs[earliest_m] += total_cycle
        valid_jobs.remove(selected_job)
            
    start_anchor = earliest_plan_start
    max_finish = max(m_available.values()) if summary_records else (start_anchor + timedelta(hours=11))
    
    total_factory_work_hours = 0.0
    iter_date = start_anchor.date()
    while iter_date <= max_finish.date():
        w_list = get_day_working_windows(iter_date)
        for ws, we in w_list:
            total_factory_work_hours += (we - ws).total_seconds() / 3600.0
        iter_date += timedelta(days=1)
        
    total_horizon_work_hrs = max(total_factory_work_hours, 8.83)
    
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
# 6. เมนูเปลี่ยนโหมด (5 หมวดการใช้งาน)
# =========================================================
nav_options = [
    "👷 โหมดช่างหน้าเครื่อง", 
    "📊 แดชบอร์ดภาพรวมโรงงาน", 
    "📈 วิเคราะห์ประสิทธิภาพราย Drawing", 
    "📑 รายงานสรุปประจำเดือน", 
    "📺 จอทีวีกลางโรงงาน (TV Live)"
]

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
    m_wo_summary = pd.DataFrame()
    
    if not df_all.empty:
        _, df_summary_plan, _, _ = calculate_shop_schedule(df_all)
        if not df_summary_plan.empty:
            for _, s_row in df_summary_plan.iterrows():
                j_id = str(s_row.get("ID", ""))
                p_cd = str(s_row.get("แผนงาน", ""))
                d_cd = str(s_row.get("ชื่อ Drawing.", ""))
                s_cd = str(s_row.get("ขั้นตอน (Step)", ""))
                f_dt = s_row.get("เวลาจบงาน_DT")

                planned_finish_map[j_id] = f_dt
                planned_finish_map[(p_cd, d_cd, s_cd)] = f_dt

            m_wo_summary = df_summary_plan[df_summary_plan["เครื่องจักร"] == selected_m].sort_values(by="เวลาเริ่มจริง", ascending=True).copy().reset_index(drop=True)

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
            start_epoch = to_bangkok_epoch_ms(st_t)
            act_dt = parse_flexible_datetime(st_t)
            if act_dt is not None:
                st_txt = act_dt.strftime("%H:%M น.")

            st.markdown(f"""
            <div class="shop-live-banner shop-live-running">
                <div style="display:flex; align-items:center; gap:10px;">
                    <span class="tv-pulse-dot"></span>
                    <span>🟢 <b>{selected_m}: กำลังรันงานอยู่</b> (เริ่ม: {st_txt} | ⏱️ กำลังรัน: <span class="pes-live-timer" data-start-epoch="{start_epoch}" style="font-family:monospace; font-weight:900; font-size:15px; color:#065F46;">00:00:00</span>)</span>
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

    if m_wo_summary.empty:
        st.info(f"🎉 สถานี {selected_m} ไม่มีคิวงานค้างในระบบ")
    else:
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

        for queue_idx, (_, wo_item) in enumerate(m_wo_summary.iterrows(), 1):
            target_id = safe_int(wo_item["ID"])
            step_record = m_all_jobs[m_all_jobs["ID"] == target_id]
            if step_record.empty:
                continue
            step_row = step_record.iloc[0]

            plan_code = str(step_row.get("แผนงาน", "-"))
            drawing_code = str(step_row.get("ชื่อ Drawing.", "-"))
            qty_val = int(step_row.get("จำนวน", 1) or 1)
            mat_val = str(step_row.get("วัสดุ", "-"))
            raw_s_name = str(step_row.get("ขั้นตอน (Step)", "รอหน้าเครื่องระบุ"))
            s_name = raw_s_name if raw_s_name not in ["", "None", "nan", "รอหน้าเครื่องระบุ"] else f"OP{queue_idx*10}"
            s_status = str(step_row.get("สถานะงาน", "🟧 รอคิวผลิต"))
            s_start = step_row.get("เริ่มจริง")
            s_finish = step_row.get("เสร็จจริง")

            is_step_running = "กำลังผลิต" in s_status
            is_step_hold = "พักงาน" in s_status
            is_step_finished = "เสร็จสิ้น" in s_status
            is_step_waiting = not is_step_running and not is_step_finished and not is_step_hold
            is_urgent = "ด่วนแทรก" in str(step_row.get("ประเภทงาน", ""))

            dt_ready = parse_flexible_datetime(step_row.get("วัน-เวลาขึ้นงาน"))
            ready_display_str = dt_ready.strftime("%d/%m/%Y %H:%M น.") if (dt_ready is not None and pd.notna(dt_ready)) else "ยังไม่ระบุเวลา"

            plan_finish_dt = wo_item.get("เวลาจบงาน_DT")
            finish_plan_display_str = plan_finish_dt.strftime("%d/%m/%Y %H:%M น.") if pd.notna(plan_finish_dt) else str(wo_item.get("เวลาจบงาน", "-"))

            if "Batch" in run_mode:
                can_start = is_step_waiting
            else:
                can_start = False
                if is_step_waiting and not machine_any_running and not next_available_start_found:
                    can_start = True
                    next_available_start_found = True

            if is_step_hold:
                header_box_class = "op-job-header op-job-header-hold"
                badge_gradient = "linear-gradient(135deg, #D97706 0%, #F59E0B 100%)"
                status_badge_html = '<span class="badge-chip badge-hold">🛑 พักงาน (รอวัสดุใหม่)</span>'
            elif is_step_running:
                header_box_class = "op-job-header op-job-header-running"
                badge_gradient = "linear-gradient(135deg, #059669 0%, #10B981 100%)"
                status_badge_html = '<span class="badge-chip badge-running"><span class="tv-pulse-dot" style="margin-right:6px;"></span> 🟦 กำลังผลิต (รันงานอยู่ ⏱️)</span>'
            elif is_urgent:
                header_box_class = "op-job-header op-job-header-urgent"
                badge_gradient = "linear-gradient(135deg, #DC2626 0%, #EF4444 100%)"
                status_badge_html = '<span class="badge-chip badge-urgent">🔥 🔴 งานด่วนแทรก</span>'
            else:
                header_box_class = "op-job-header"
                badge_gradient = "linear-gradient(135deg, #4F46E5 0%, #7C3AED 100%)"
                status_badge_html = ''

            card_header_html = f'''<div class="{header_box_class}"><div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px;"><div style="font-size:20px; font-weight:800; color:#1E1B4B; display:flex; align-items:center; gap:8px;"><span style="background:{badge_gradient}; color:white; padding:4px 12px; border-radius:10px; font-size:14px; box-shadow:0 3px 8px rgba(0,0,0,0.15);">คิวที่ {queue_idx}</span><span>แผนงาน: {plan_code}</span></div><span class="badge-chip badge-station">🏭 {selected_m}</span></div><div style="display:flex; flex-wrap:wrap; gap:6px; align-items:center;">{status_badge_html}<span class="badge-chip badge-date">📅 <b>กำหนดขึ้นงาน:</b> {ready_display_str}</span><span class="badge-chip badge-finish-date">🏁 <b>กำหนดจบงานตามแผน:</b> {finish_plan_display_str}</span><span class="badge-chip badge-drawing">📄 <b>Drawing:</b> {drawing_code}</span><span class="badge-chip badge-qty">🔢 <b>จำนวน:</b> {qty_val} ชิ้น</span><span class="badge-chip badge-mat">🔩 <b>วัสดุ:</b> {mat_val}</span></div></div>'''
            st.markdown(card_header_html, unsafe_allow_html=True)

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
                    fin_dt = parse_flexible_datetime(s_finish)
                    finish_txt = fin_dt.strftime('%d/%m %H:%M') if (fin_dt is not None and pd.notna(fin_dt)) else '-'
                    st.caption(f"**ขั้นตอน:** <span style='color:#059669; font-weight:800;'>🟩 เสร็จสิ้นแล้ว (จบงาน: {finish_txt})</span>", unsafe_allow_html=True)
                elif is_step_running:
                    st_parsed = parse_flexible_datetime(s_start)
                    start_txt = st_parsed.strftime('%H:%M น.') if (st_parsed is not None and pd.notna(st_parsed)) else '-'
                    step_start_epoch = to_bangkok_epoch_ms(s_start)
                    st.caption(f"""**ขั้นตอน:** <span style='color:#059669; font-weight:800; font-size:14px;'><span class='tv-pulse-dot' style='margin-right:6px;'></span> 🟦 กำลังผลิต (เริ่มรัน: {start_txt}) | ⏱️ เวลาเดินจริง: <span class='pes-live-timer' data-start-epoch='{step_start_epoch}' style='font-family:monospace; font-size:16px; font-weight:900; color:#047857;'>00:00:00</span></span>""", unsafe_allow_html=True)
                elif is_step_hold:
                    st.caption(f"**ขั้นตอน:** <span style='color:#D97706; font-weight:800; font-size:13.5px;'>🟨 พักงานชั่วคราว (ชิ้นงานมีปัญหา / รอเบิกวัสดุใหม่) 🛑</span>", unsafe_allow_html=True)
                else:
                    if can_start:
                        st.caption(f"**ขั้นตอน:** <span style='color:#D97706; font-weight:800;'>🟧 พร้อมเริ่มงาน (Ready to Start)</span>", unsafe_allow_html=True)
                    else:
                        st.caption(f"**ขั้นตอน:** <span style='color:#64748B; font-weight:600;'>🔒 รอลำดับคิวก่อนหน้าตามแผน</span>", unsafe_allow_html=True)

                if not is_step_finished:
                    step_val = st.text_input(
                        f"ชื่อขั้นตอนงาน (Step):", 
                        value=s_name, 
                        placeholder="เช่น OP10, ปาดผิวเจาะรู, กลึง, เชื่อมประกอบ, เจียร", 
                        key=f"input_step_name_{target_id}"
                    )

                    if is_step_hold:
                        c_btn_save, c_btn_resume = st.columns([1.5, 4])
                        with c_btn_save:
                            if st.button("💾 บันทึกชื่อ", key=f"btn_save_edit_{target_id}", use_container_width=True):
                                update_payload = {"step_name": safe_str(step_val, s_name)}
                                if update_supabase_job(target_id, update_payload):
                                    st.toast(f"บันทึกชื่อขั้นตอนเรียบร้อย!", icon="💾")
                                    st.rerun()
                        with c_btn_resume:
                            if st.button("▶️ ได้วัสดุใหม่แล้ว (Resume เริ่มรันต่อ)", key=f"btn_resume_{target_id}", type="primary", use_container_width=True):
                                now_str = get_bangkok_str()
                                update_payload = {
                                    "step_name": safe_str(step_val, s_name),
                                    "status": "🟦 กำลังผลิต",
                                    "actual_start": now_str
                                }
                                if update_supabase_job(target_id, update_payload):
                                    st.toast("เริ่มรันงานต่อเรียบร้อย!", icon="🚀")
                                    st.rerun()
                    elif is_step_running:
                        c_btn_save, c_btn_hold, c_btn_finish = st.columns([1.5, 2.5, 2])
                        with c_btn_save:
                            if st.button("💾 บันทึกชื่อ", key=f"btn_save_edit_{target_id}", use_container_width=True):
                                update_payload = {"step_name": safe_str(step_val, s_name)}
                                if update_supabase_job(target_id, update_payload):
                                    st.toast(f"บันทึกชื่อขั้นตอนเรียบร้อย!", icon="💾")
                                    st.rerun()
                        with c_btn_hold:
                            if st.button("🛑 พักงาน (รอวัสดุใหม่)", key=f"btn_hold_{target_id}", use_container_width=True):
                                update_payload = {
                                    "step_name": safe_str(step_val, s_name),
                                    "status": "🟨 พักงาน (รอวัสดุ)"
                                }
                                if update_supabase_job(target_id, update_payload):
                                    st.toast("พักงานเรียบร้อย สามารถรันงานอื่นต่อได้ทันที!", icon="🛑")
                                    st.rerun()
                        with c_btn_finish:
                            if st.button("🏁 Finish (จบงานจริง)", key=f"btn_finish_step_{target_id}", type="primary", use_container_width=True):
                                now_str = get_bangkok_str()
                                finish_payload = {
                                    "status": "🟩 เสร็จสิ้นแล้ว", 
                                    "actual_finish": now_str
                                }
                                if update_supabase_job(target_id, finish_payload):
                                    st.toast(f"บันทึกเวลาจบจริง {s_name} เรียบร้อย!", icon="🏁")
                                    st.rerun()
                    else:
                        c_btn_save, c_btn_start, c_btn_finish = st.columns([1.5, 2, 2])
                        with c_btn_save:
                            if st.button("💾 บันทึกชื่อ", key=f"btn_save_edit_{target_id}", use_container_width=True):
                                update_payload = {"step_name": safe_str(step_val, s_name)}
                                if update_supabase_job(target_id, update_payload):
                                    st.toast(f"บันทึกชื่อขั้นตอนเรียบร้อย!", icon="💾")
                                    st.rerun()
                        with c_btn_start:
                            if can_start:
                                if st.button("🚀 Start (เริ่มจับเวลาจริง)", key=f"btn_start_step_{target_id}", type="primary", use_container_width=True):
                                    now_str = get_bangkok_str()
                                    update_payload = {
                                        "step_name": safe_str(step_val, s_name),
                                        "status": "🟦 กำลังผลิต",
                                        "actual_start": now_str
                                    }
                                    if update_supabase_job(target_id, update_payload):
                                        st.toast(f"เริ่มผลิตและบันทึกเวลาเริ่มจริงแล้ว!", icon="🚀")
                                        st.rerun()
                            else:
                                st.button("🚀 Start", key=f"btn_start_disabled_{target_id}", disabled=True, use_container_width=True)
                        with c_btn_finish:
                            st.button("🏁 Finish", key=f"btn_finish_disabled_{target_id}", disabled=True, use_container_width=True)

                else:
                    st.markdown(f"**ขั้นตอน:** {s_name}")
                    c_btn_done, c_btn_edit_done = st.columns([2, 2])
                    with c_btn_done:
                        st.button("✅ Finish แล้ว", key=f"btn_finished_done_{target_id}", disabled=True, use_container_width=True)
                    
                    with c_btn_edit_done:
                        with st.popover("✏️ แก้ไขชื่อขั้นตอน"):
                            re_step = st.text_input("แก้ชื่อขั้นตอน:", value=s_name, key=f"re_name_{target_id}")
                            if st.button("💾 บันทึกทับชื่อ", key=f"btn_re_save_{target_id}", type="primary", use_container_width=True):
                                if update_supabase_job(target_id, {"step_name": re_step.strip()}):
                                    st.toast("อัปเดตชื่อ Step สำเร็จ!", icon="💾")
                                    st.rerun()

                st.markdown("</div>", unsafe_allow_html=True)

            with st.expander(f"➕ เพิ่ม Step ถัดไปสำหรับ {plan_code} ({drawing_code})", expanded=False):
                new_step_input = st.text_input("ชื่อ Step ถัดไป:", value=f"OP{(queue_idx+1)*10}", placeholder="เช่น OP20, กลึง, เจียร, เชื่อม", key=f"new_step_name_input_{target_id}")

                if st.button(f"➕ บันทึกเพิ่มขั้นตอนต่อท้าย", key=f"btn_add_step_{target_id}", type="secondary", use_container_width=True):
                    now_str = get_bangkok_str()
                    base_setup = safe_float(step_row.get("Setup (น.)"), 10.0)
                    base_basic = safe_float(step_row.get("Basic (น.)"), 0.0)
                    base_prog = safe_float(step_row.get("โปรแกรม (น.)"), 120.0)
                    
                    new_payload = {
                        "plan_code": str(plan_code),
                        "drawing_name": str(drawing_code),
                        "qty": int(qty_val),
                        "material": str(mat_val),
                        "job_type": str(step_row.get("ประเภทงาน", "🟢 งานปกติ")),
                        "step_name": new_step_input.strip() if new_step_input.strip() != "" else f"OP{(queue_idx+1)*10}",
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

    components.html("""
    <script>
        function runLiveStopwatches() {
            try {
                const now = new Date().getTime();
                const timerEls = window.parent.document.querySelectorAll('.pes-live-timer');
                timerEls.forEach(el => {
                    const startAttr = el.getAttribute('data-start-epoch');
                    const startTs = parseInt(startAttr, 10);
                    if (startTs && startTs > 0) {
                        const diffMs = Math.max(0, now - startTs);
                        const totalSecs = Math.floor(diffMs / 1000);
                        const hrs = String(Math.floor(totalSecs / 3600)).padStart(2, '0');
                        const mins = String(Math.floor((totalSecs % 3600) / 60)).padStart(2, '0');
                        const secs = String(totalSecs % 60).padStart(2, '0');
                        el.innerText = hrs + ":" + mins + ":" + secs;
                    }
                });
            } catch (e) {
                console.error(e);
            }
        }
        setInterval(runLiveStopwatches, 1000);
        runLiveStopwatches();
    </script>
    """, height=0)

# ---------------------------------------------------------
# VIEW 2: Dashboard ภาพรวมโรงงาน
# ---------------------------------------------------------
elif st.session_state.current_view == "📊 แดชบอร์ดภาพรวมโรงงาน":
    if st.session_state.user_role is None:
        st.subheader("🔒 ยืนยันตัวตนสำหรับเข้าใช้งานแดชบอร์ดภาพรวมโรงงาน")
        st.info("กรุณากรอกรหัสผ่านเพื่อเข้าใช้งาน:\n* **ผู้บริหาร/วางแผน (แก้ไขได้):** รหัสผ่านระดับ Admin\n* **เข้าชมทั่วไป (ดูอย่างเดียว):** รหัสผ่านทั่วไป")
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
                        cat_status = "RUNNING"
                    elif not cur_hold.empty:
                        stage = f"🛑 พักงานที่ {cur_hold.iloc[0]['เลือกเครื่องจักร']} (รอวัสดุ)"
                        cat_status = "HOLD"
                    elif fin_steps == total_steps:
                        stage = "🟩 ผลิตเสร็จครบทุก Step แล้ว"
                        cat_status = "DONE"
                    else:
                        first_wait = g_data[g_data["สถานะงาน"] == "🟧 รอคิวผลิต"].iloc[0]
                        stage = f"🟧 รอคิวที่ {first_wait['เลือกเครื่องจักร']}"
                        cat_status = "WAITING"

                    drawing_progress_list.append({
                        "แผนงาน": p_c,
                        "ชื่อ Drawing.": d_c,
                        "จำนวน (ชิ้น)": int(g_data.iloc[0].get("จำนวน", 1)),
                        "ความคืบหน้า (%)": pct,
                        "ขั้นตอน (เสร็จ/ทั้งหมด)": f"{fin_steps}/{total_steps} Step",
                        "สถานะและสถานีปัจจุบัน": stage,
                        "status_category": cat_status
                    })
                
                df_dp_all = pd.DataFrame(drawing_progress_list).sort_values(by=["ความคืบหน้า (%)", "แผนงาน"], ascending=[False, True])
                
                cnt_all = len(df_dp_all)
                cnt_done = len(df_dp_all[df_dp_all["status_category"] == "DONE"])
                cnt_run = len(df_dp_all[df_dp_all["status_category"] == "RUNNING"])
                cnt_wait = len(df_dp_all[df_dp_all["status_category"].isin(["WAITING", "HOLD"])])

                tk_btn_col, tk_search_col = st.columns([5.5, 4.5])
                with tk_btn_col:
                    st.caption("**🎯 ตัวกรองด่วนสถานะ Drawing:**")
                    t_b1, t_b2, t_b3, t_b4 = st.columns(4)
                    cur_tracker_filter = st.session_state.get("drawing_tracker_filter", "ALL")
                    with t_b1:
                        b_type_all = "primary" if cur_tracker_filter == "ALL" else "secondary"
                        if st.button(f"🌐 ทั้งหมด ({cnt_all})", type=b_type_all, use_container_width=True, key="btn_tk_all"):
                            st.session_state.drawing_tracker_filter = "ALL"
                            st.rerun()
                    with t_b2:
                        b_type_done = "primary" if cur_tracker_filter == "DONE" else "secondary"
                        if st.button(f"🟢 ผลิตเสร็จ ({cnt_done})", type=b_type_done, use_container_width=True, key="btn_tk_done"):
                            st.session_state.drawing_tracker_filter = "DONE"
                            st.rerun()
                    with t_b3:
                        b_type_run = "primary" if cur_tracker_filter == "RUNNING" else "secondary"
                        if st.button(f"🟦 กำลังรัน ({cnt_run})", type=b_type_run, use_container_width=True, key="btn_tk_run"):
                            st.session_state.drawing_tracker_filter = "RUNNING"
                            st.rerun()
                    with t_b4:
                        b_type_wait = "primary" if cur_tracker_filter == "WAITING" else "secondary"
                        if st.button(f"🟧 รอคิว ({cnt_wait})", type=b_type_wait, use_container_width=True, key="btn_tk_wait"):
                            st.session_state.drawing_tracker_filter = "WAITING"
                            st.rerun()

                with tk_search_col:
                    search_query_tracker = st.text_input(
                        "🔍 ค้นหาในตารางความคืบหน้า (แผนงาน, Drawing):",
                        placeholder="พิมพ์เพื่อค้นหา เช่น 26-108, AS256...",
                        key="search_drawing_tracker_input"
                    )

                df_dp = df_dp_all.copy()
                selected_filter = st.session_state.get("drawing_tracker_filter", "ALL")
                if selected_filter == "DONE":
                    df_dp = df_dp[df_dp["status_category"] == "DONE"]
                elif selected_filter == "RUNNING":
                    df_dp = df_dp[df_dp["status_category"] == "RUNNING"]
                elif selected_filter == "WAITING":
                    df_dp = df_dp[df_dp["status_category"].isin(["WAITING", "HOLD"])]

                if search_query_tracker.strip() != "":
                    q_tk = search_query_tracker.strip().lower()
                    df_dp = df_dp[
                        df_dp["แผนงาน"].astype(str).str.lower().str.contains(q_tk) |
                        df_dp["ชื่อ Drawing."].astype(str).str.lower().str.contains(q_tk)
                    ]

                st.dataframe(
                    df_dp[[c for c in df_dp.columns if c != "status_category"]],
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

            # -------------------------------------------------------------------------------------------------
            # ปรับปรุง: จำลองและต่อเวลาแบบ Chain (สลับฟันปลา) ล่วงหน้าก่อนคำนวณ เพื่อให้ตารางได้รับเวลาครบ 100%
            # -------------------------------------------------------------------------------------------------
            calc_df["temp_ready_dt"] = calc_df["วัน-เวลาขึ้นงาน"].apply(parse_flexible_datetime)
            calc_df = calc_df.sort_values(by=["temp_ready_dt", "ID"], ascending=[True, True], na_position="last").drop(columns=["temp_ready_dt"]).reset_index(drop=True)

            machine_sim_tracker = {}
            for r_idx, r_val in calc_df.iterrows():
                m_target = str(r_val.get("เลือกเครื่องจักร", ""))
                ready_dt = parse_flexible_datetime(r_val.get("วัน-เวลาขึ้นงาน"))
                
                # หากไม่มีวันขึ้นงาน ให้รับค่าเวลาจบงานจากคิวก่อนหน้าในเครื่องเดียวกัน
                if (ready_dt is None or pd.isna(ready_dt)) and m_target in machine_sim_tracker:
                    ready_dt = machine_sim_tracker[m_target]
                    calc_df.at[r_idx, "วัน-เวลาขึ้นงาน"] = ready_dt.strftime("%d/%m/%Y %H:%M")
                
                if ready_dt is not None and pd.notna(ready_dt):
                    s_mins = safe_float(r_val.get("Setup (น.)"), 10.0)
                    b_mins = safe_float(r_val.get("Basic (น.)"), 0.0)
                    p_mins = safe_float(r_val.get("โปรแกรม (น.)"), 120.0)
                    total_dur_hrs = (s_mins + b_mins + p_mins) / 60.0
                    try:
                        _, f_end_dt = add_work_time_with_shift(ready_dt, total_dur_hrs)
                        machine_sim_tracker[m_target] = f_end_dt
                    except Exception:
                        pass

            # คำนวณตารางตามเวลาแผนงานแม่นยำ
            df_gantt, df_summary, df_util, total_plan_hrs = calculate_shop_schedule(calc_df)

            editor_finish_map = {}
            if not df_summary.empty:
                for _, s_row in df_summary.iterrows():
                    editor_finish_map[str(s_row.get("ID", ""))] = s_row.get("เวลาจบงาน", "-")

            column_order = [
                "ID", "แผนงาน", "ชื่อ Drawing.", "จำนวน", "วัสดุ", "ประเภทงาน", "ขั้นตอน (Step)",
                "เลือกเครื่องจักร", "วัน-เวลาขึ้นงาน", "Setup (น.)",
                "Basic (น.)", "โปรแกรม (น.)", "รวม (ชม.)", "สถานะงาน",
            ]
            calc_df = calc_df[[c for c in column_order if c in calc_df.columns]]

            active_jobs_editor_df = calc_df[
                calc_df["สถานะงาน"].isin(["🟧 รอคิวผลิต", "🟦 กำลังผลิต", "🟨 พักงาน (รอวัสดุ)", "⏳ รอคิวผลิต", "⚙️ กำลังผลิต"])
            ].copy()

            active_jobs_editor_df["temp_ready_dt"] = active_jobs_editor_df["วัน-เวลาขึ้นงาน"].apply(parse_flexible_datetime)
            active_jobs_editor_df = active_jobs_editor_df.sort_values(
                by=["temp_ready_dt", "ID"], 
                ascending=[True, True], 
                na_position="last"
            ).drop(columns=["temp_ready_dt"]).reset_index(drop=True)
            
            for idx_row in active_jobs_editor_df.index:
                row_status = str(active_jobs_editor_df.at[idx_row, "สถานะงาน"])
                row_step = str(active_jobs_editor_df.at[idx_row, "ขั้นตอน (Step)"])
                if "รอคิวผลิต" in row_status and (row_step in ["", "None", "nan", "OP10", "OP20", "OP30", "OP40", "OP50", "(รอช่างหน้าเครื่องระบุ)", "รันงาน"]):
                    active_jobs_editor_df.at[idx_row, "ขั้นตอน (Step)"] = "รอหน้าเครื่องระบุ"

            # คำนวณวัน-เวลาจบงาน พร้อมระบบ Chain และ Clear Mask
            calculated_finish_dates = []
            machine_last_finish_sim = {}

            for row_idx, row_item in active_jobs_editor_df.iterrows():
                row_id_str = str(row_item["ID"])
                m_target = str(row_item.get("เลือกเครื่องจักร", ""))

                current_ready_parsed = parse_flexible_datetime(row_item.get("วัน-เวลาขึ้นงาน"))
                if (current_ready_parsed is None or pd.isna(current_ready_parsed)) and m_target in machine_last_finish_sim:
                    current_ready_parsed = machine_last_finish_sim[m_target]
                    if current_ready_parsed is not None and pd.notna(current_ready_parsed):
                        active_jobs_editor_df.at[row_idx, "วัน-เวลาขึ้นงาน"] = current_ready_parsed.strftime("%d/%m/%Y %H:%M")

                if row_id_str in st.session_state.cleared_finish_jobs:
                    calculated_finish_dates.append("")
                    continue

                mapped_val = editor_finish_map.get(row_id_str)
                if mapped_val and mapped_val != "-":
                    calculated_finish_dates.append(mapped_val)
                    m_f_dt = parse_flexible_datetime(mapped_val)
                    if m_f_dt is not None and pd.notna(m_f_dt):
                        machine_last_finish_sim[m_target] = m_f_dt
                else:
                    ready_parsed = current_ready_parsed
                    if ready_parsed is None or pd.isna(ready_parsed):
                        ready_parsed = get_bangkok_now().replace(tzinfo=None)
                    
                    s_m = safe_float(row_item.get("Setup (น.)"), 10.0)
                    b_m = safe_float(row_item.get("Basic (น.)"), 0.0)
                    p_m = safe_float(row_item.get("โปรแกรม (น.)"), 120.0)
                    tot_hrs = (s_m + b_m + p_m) / 60.0
                    
                    try:
                        _, fallback_end_dt = add_work_time_with_shift(ready_parsed, tot_hrs)
                        calculated_finish_dates.append(fallback_end_dt.strftime("%d/%m/%Y %H:%M"))
                        machine_last_finish_sim[m_target] = fallback_end_dt
                    except Exception:
                        calculated_finish_dates.append("-")

            active_jobs_editor_df["วัน-เวลาจบงาน"] = calculated_finish_dates

            # แปลงแสดงผล
            active_jobs_editor_df["วัน-เวลาขึ้นงาน"] = active_jobs_editor_df["วัน-เวลาขึ้นงาน"].apply(
                lambda x: x.strftime("%d/%m/%Y %H:%M") if (pd.notna(x) and isinstance(x, (datetime, pd.Timestamp))) else ("" if (pd.isna(x) or str(x).strip() in ["None", "nan", "NaT"]) else str(x))
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
                            "เลือกเครื่องจักร", "วัน-เวลาขึ้นงาน", "วัน-เวลาจบงาน", "Setup (น.)",
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
                                width=155,
                                help="พิมพ์วันขึ้นก่อนเสมอ เช่น 31/08/2026 10:50 หรือ 31/08 10:50"
                            ),
                            "วัน-เวลาจบงาน": st.column_config.TextColumn(
                                "วัน-เวลาจบงาน",
                                width=135,
                                disabled=False,
                                help="สามารถลบตัวเลขทิ้งได้ หากลบแล้วระบบจะคงค่าว่างไว้"
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

                    # ตรวจจับการสั่งลบค่าในช่องวัน-เวลาจบงาน
                    for _, edit_r in edited_jobs.iterrows():
                        r_id_str = str(edit_r.get("ID", ""))
                        cur_fin_val = str(edit_r.get("วัน-เวลาจบงาน", "")).strip()
                        if r_id_str and r_id_str not in ["", "None", "nan"]:
                            if cur_fin_val in ["", "-", "None"]:
                                st.session_state.cleared_finish_jobs.add(r_id_str)
                            else:
                                if r_id_str in st.session_state.cleared_finish_jobs and len(cur_fin_val) >= 10:
                                    st.session_state.cleared_finish_jobs.discard(r_id_str)

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
                            "วัน-เวลาขึ้นงาน": st.column_config.TextColumn("วัน-เวลาขึ้นงาน", width=155),
                            "วัน-เวลาจบงาน": st.column_config.TextColumn("วัน-เวลาจบงาน", width=135),
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
                                
                                # แก้ไขจุด NaT Error อย่างปลอดภัย 100%
                                ready_str = dt_parsed.strftime("%Y-%m-%d %H:%M:%S") if (dt_parsed is not None and pd.notna(dt_parsed)) else None
                                
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
                                            orig_ready_str = orig_ready_dt.strftime("%Y-%m-%d %H:%M:%S") if (orig_ready_dt is not None and pd.notna(orig_ready_dt)) else None
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

            finished_jobs_df = df_db[df_db["สถานะงาน"].isin(["🟩 เสร็จสิ้นแล้ว", "✅ เสร็จสิ้นแล้ว"])].copy()
            active_jobs_count = len(edited_jobs[edited_jobs["สถานะงาน"].isin(["🟧 รอคิวผลิต", "🟦 กำลังผลิต", "🟨 พักงาน (รอวัสดุ)", "⏳ รอคิวผลิต", "⚙️ กำลังผลิต"])])
            avg_util = df_util["อัตราการใช้งาน (%)"].mean() if not df_util.empty else 0.0

            kpi_html = f'''<div class="kpi-container"><div class="kpi-card kpi-green"><div class="kpi-title">✅ งานเสร็จสิ้น</div><div class="kpi-value">{len(finished_jobs_df)} <span style="font-size:15px; font-weight:600;">รายการ</span></div></div><div class="kpi-card kpi-blue"><div class="kpi-title">⚙️ งานในแผน</div><div class="kpi-value">{active_jobs_count} <span style="font-size:15px; font-weight:600;">รายการ</span></div></div><div class="kpi-card kpi-orange"><div class="kpi-title">⏱️ เวลาทำงานรวม</div><div class="kpi-value">{total_plan_hrs:.1f} <span style="font-size:15px; font-weight:600;">ชม.</span></div></div><div class="kpi-card kpi-purple"><div class="kpi-title">📊 การใช้เครื่อง</div><div class="kpi-value">{avg_util:.1f} %</div></div></div>'''
            st.markdown(kpi_html, unsafe_allow_html=True)

            st.divider()

            # =====================================================
            # 2. ใบจ่ายคิวงานหน้าเครื่อง (Work Order Sheet)
            # =====================================================
            if not df_summary.empty:
                st.subheader("📋 ใบจ่ายคิวงานหน้าเครื่อง (Work Order Sheet)")

                wo_finish_map = dict(
                    zip(
                        df_summary["ID"].astype(str),
                        df_summary["เวลาจบงาน_DT"]
                    )
                )

                now_check = get_bangkok_now().replace(tzinfo=None)
                warn_count = 0
                late_count = 0
                for _, r in df_summary.iterrows():
                    if "กำลังผลิต" in str(r.get("สถานะ", "")):
                        f_dt = wo_finish_map.get(str(r.get("ID")))
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
                    cur_wo_filter = st.session_state.get("wo_color_filter", "ALL")
                    with f_b1:
                        btn_all_type = "primary" if cur_wo_filter == "ALL" else "secondary"
                        if st.button("🌐 ทั้งหมด", type=btn_all_type, use_container_width=True):
                            st.session_state.wo_color_filter = "ALL"
                            st.rerun()
                    with f_b2:
                        btn_warn_type = "primary" if cur_wo_filter == "WARN" else "secondary"
                        if st.button(f"🟡 ใกล้เสร็จ ({warn_count})", type=btn_warn_type, use_container_width=True, help="เหลือน้อยกว่า 1 ชม."):
                            st.session_state.wo_color_filter = "WARN"
                            st.rerun()
                    with f_b3:
                        btn_late_type = "primary" if cur_wo_filter == "LATE" else "secondary"
                        if st.button(f"🔴 เกินแผน ({late_count})", type=btn_late_type, use_container_width=True, help="เลยกำหนดเวลาแผน"):
                            st.session_state.wo_color_filter = "LATE"
                            st.rerun()

                df_display = df_summary.sort_values(by="เวลาเริ่มจริง", ascending=True).copy()
                df_display["ลำดับคิว"] = df_display.groupby("เครื่องจักร").cumcount() + 1
                df_display["ลำดับคิว"] = df_display["ลำดับคิว"].apply(lambda q: f"คิวที่ {q}")

                selected_wo_filter = st.session_state.get("wo_color_filter", "ALL")
                if selected_wo_filter == "WARN":
                    def is_warn_row(r):
                        if "กำลังผลิต" not in str(r.get("สถานะ", "")): return False
                        f_dt = wo_finish_map.get(str(r.get("ID")))
                        if pd.notna(f_dt):
                            diff_m = (f_dt - now_check).total_seconds() / 60.0
                            return 0 <= diff_m <= 60
                        return False
                    df_display = df_display[df_display.apply(is_warn_row, axis=1)]

                elif selected_wo_filter == "LATE":
                    def is_late_row(r):
                        if "กำลังผลิต" not in str(r.get("สถานะ", "")): return False
                        f_dt = wo_finish_map.get(str(r.get("ID")))
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

                display_cols = [c for c in df_display.columns if c not in ["เวลาเริ่มจริง", "เวลาจบงาน_DT"]]

                styled_df_display = df_display[display_cols].style.apply(
                    highlight_running_deadlines,
                    planned_finish_map=wo_finish_map,
                    axis=1
                )

                st.dataframe(
                    styled_df_display,
                    column_order=[
                        "เครื่องจักร", "ลำดับคิว", "สถานะ", "ประเภทงาน", "แผนงาน", "ชื่อ Drawing.", 
                        "จำนวน", "วัสดุ", "ขั้นตอน (Step)", "กำหนดพร้อมขึ้นงาน", "เริ่ม Setup", 
                        "เวลาเริ่มขึ้นงาน", "เวลาจบงาน", "Setup (น.)", "Basic (น.)", "โปรแกรม (น.)", "รวม (ชม.)"
                    ],
                    column_config={
                        "ID": None,
                        "เครื่องจักร": st.column_config.TextColumn("เครื่องจักร / แผนก", width=140),
                        "ลำดับคิว": st.column_config.TextColumn("ลำดับคิว", width=95),
                        "สถานะ": st.column_config.TextColumn("สถานะ", width=105),
                        "ประเภทงาน": st.column_config.TextColumn("ประเภทงาน", width=100),
                        "แผนงาน": st.column_config.TextColumn("แผนงาน", width=80),
                        "ชื่อ Drawing.": st.column_config.TextColumn("ชื่อ Drawing.", width=170),
                        "จำนวน": st.column_config.NumberColumn("จำนวน", width=65, format="%d"),
                        "วัสดุ": st.column_config.TextColumn("วัสดุ", width=70),
                        "ขั้นตอน (Step)": st.column_config.TextColumn("ขั้นตอน (Step)", width=120),
                        "กำหนดพร้อมขึ้นงาน": st.column_config.TextColumn("กำหนดพร้อมขึ้นงาน", width=155, help="วัน-เวลาขึ้นงานเดิมที่ระบุไว้ในตารางสั่งผลิต"),
                        "เวลาเริ่ม Setup": st.column_config.TextColumn("เริ่ม Setup", width=105),
                        "เวลาเริ่มขึ้นงาน": st.column_config.TextColumn("เริ่มขึ้นงานตามแผน", width=120),
                        "เวลาจบงาน": st.column_config.TextColumn("จบงานตามแผน", width=135),
                        "Setup (น.)": st.column_config.NumberColumn("Setup (น.)", width=80, format="%d"),
                        "Basic (น.)": st.column_config.NumberColumn("Basic (น.)", width=80, format="%d"),
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
                    act_st = parse_flexible_datetime(s_real)
                    act_fn = parse_flexible_datetime(f_real)
                    if act_st is not None and act_fn is not None:
                        diff_seconds = (act_fn - act_st).total_seconds()
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
                        ["🌐 ทุกสถานี (22 เครื่อง)", "⚙️ CNC (No.1 - No.9)", "🔧 เจียร/มิลลิ่ง/กลึง (No.10 - No.16)", "🔥 แผนกเชื่อม (6 เครื่อง)"],
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
                    display_machines = MACHINE_LIST[9:16]
                elif "เชื่อม" in m_filter_mode:
                    display_machines = MACHINE_LIST[16:]
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
                    start_view = datetime.combine(selected_date_range[0], dtime(8, 0))
                    end_view = datetime.combine(selected_date_range[1], dtime(20, 30))
                elif isinstance(selected_date_range, (list, tuple)) and len(selected_date_range) == 1:
                    start_view = datetime.combine(selected_date_range[0], dtime(8, 0))
                    end_view = datetime.combine(selected_date_range[1], dtime(20, 30))
                else:
                    start_view = datetime.combine(gantt_min_date, dtime(8, 0))
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
                            b1_start = datetime.combine(cur_d, dtime(10, 0))
                            b1_end = datetime.combine(cur_d, dtime(10, 10))
                            fig.add_vrect(x0=b1_start, x1=b1_end, fillcolor="#FEF3C7", opacity=0.6, layer="below", line_width=0)
                            
                            lunch_start = datetime.combine(cur_d, dtime(12, 0))
                            lunch_end = datetime.combine(cur_d, dtime(13, 0))
                            fig.add_vrect(
                                x0=lunch_start, x1=lunch_end,
                                fillcolor="#FEF3C7", opacity=0.6,
                                layer="below", line_width=1, line_color="#FDE68A",
                                annotation_text="🍱 พักเที่ยง", annotation_position="top left",
                                annotation_font_size=9, annotation_font_color="#D97706"
                            )
                            
                            b2_start = datetime.combine(cur_d, dtime(15, 0))
                            b2_end = datetime.combine(cur_d, dtime(15, 10))
                            fig.add_vrect(x0=b2_start, x1=b2_end, fillcolor="#FEF3C7", opacity=0.6, layer="below", line_width=0)

                            if cur_d.weekday() < 5:
                                ot_b_start = datetime.combine(cur_d, dtime(17, 0))
                                ot_b_end = datetime.combine(cur_d, dtime(17, 30))
                                fig.add_vrect(x0=ot_b_start, x1=ot_b_end, fillcolor="#FEF3C7", opacity=0.5, layer="below", line_width=0)

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
                        <span><b>จันทร์ – ศุกร์:</b> 08:30 – 12:00 น. และ 13:00 – 20:00 น. (พักเย็น 17:00 – 17:30 น.)</span>
                    </div>
                    <div class="schedule-pill">
                        <span style="font-size:16px;">⏱️</span>
                        <span><b>วันเสาร์:</b> 08:30 – 12:00 น. และ 13:00 – 17:00 น. (7.17 ชม./วัน)</span>
                    </div>
                    <div class="schedule-pill">
                        <span style="font-size:16px;">☕</span>
                        <span style="color:#D97706;"><b>เบรกเช้า/บ่าย (จ.-ส.):</b> 10:00 – 10:10 น. และ 15:00 – 15:10 น.</span>
                    </div>
                    <div class="schedule-pill">
                        <span style="font-size:16px;">🍱</span>
                        <span style="color:#D97706;"><b>พักเที่ยง:</b> 12:00 – 13:00 น.</span>
                    </div>
                    <div class="schedule-pill">
                        <span style="color:#DC2626;"><b>วันอาทิตย์:</b> หยุดทำการ</span>
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
                    height=max(600, len(MACHINE_LIST) * 30),
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
                        key="editor_machine_rates_full_22_v14",
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
# VIEW 3: หมวดวิเคราะห์ประสิทธิภาพราย Drawing
# ---------------------------------------------------------
elif st.session_state.current_view == "📈 วิเคราะห์ประสิทธิภาพราย Drawing":
    st.subheader("📈 วิเคราะห์และเปรียบเทียบเวลาทำงานจริงราย Drawing (Drawing Performance Analysis)")
    
    df_db = fetch_jobs_from_supabase()

    current_now = get_bangkok_now()
    month_names = ["มกราคม (1)", "กุมภาพันธ์ (2)", "มีนาคม (3)", "เมษายน (4)", "พฤษภาคม (5)", "มิถุนายน (6)", "กรกฎาคม (7)", "สิงหาคม (8)", "กันยายน (9)", "ตุลาคม (10)", "พฤศจิกายน (11)", "ธันวาคม (12)"]

    m_col1, m_col2, m_col3 = st.columns([2, 2, 3])
    with m_col1:
        sel_dw_month = st.selectbox("📅 เลือกเดือนที่ต้องการวิเคราะห์:", range(1, 13), index=current_now.month - 1, format_func=lambda x: month_names[x-1], key="dw_month_sel")
    with m_col2:
        sel_dw_year = st.selectbox("📆 เลือกปี (ค.ศ.):", [current_now.year - 1, current_now.year, current_now.year + 1], index=1, key="dw_year_sel")
    with m_col3:
        sel_dw_limit = st.selectbox("🎯 การแสดงผลกราฟแท่งคู่:", ["🌐 แสดงทั้งหมดในเดือนนี้", "🔴 Top 10 ช้ากว่าแผนสูงสุด (Critical Delays)", "🟢 Top 10 เร็วกว่าแผนสูงสุด (High Efficiency)"])

    if not df_db.empty:
        finished_all = df_db[df_db["สถานะงาน"].isin(["🟩 เสร็จสิ้นแล้ว", "✅ เสร็จสิ้นแล้ว"])].copy()
        
        if not finished_all.empty:
            finished_all["เสร็จจริง_DT"] = pd.to_datetime(finished_all["เสร็จจริง"], errors='coerce')
            finished_all["วันขึ้นงาน_DT"] = pd.to_datetime(finished_all["วัน-เวลาขึ้นงาน"], errors='coerce')
            finished_all["Target_Date"] = finished_all["เสร็จจริง_DT"].fillna(finished_all["วันขึ้นงาน_DT"])
            
            monthly_dw_jobs = finished_all[
                (finished_all["Target_Date"].dt.month == sel_dw_month) &
                (finished_all["Target_Date"].dt.year == sel_dw_year)
            ].copy()

            if not monthly_dw_jobs.empty:
                monthly_dw_jobs["Setup (น.)"] = pd.to_numeric(monthly_dw_jobs["Setup (น.)"], errors='coerce').fillna(10.0)
                monthly_dw_jobs["Basic (น.)"] = pd.to_numeric(monthly_dw_jobs["Basic (น.)"], errors='coerce').fillna(0.0)
                monthly_dw_jobs["โปรแกรม (น.)"] = pd.to_numeric(monthly_dw_jobs["โปรแกรม (น.)"], errors='coerce').fillna(0.0)
                monthly_dw_jobs["เวลาแผน (ชม.)"] = ((monthly_dw_jobs["Setup (น.)"] + monthly_dw_jobs["Basic (น.)"] + monthly_dw_jobs["โปรแกรม (น.)"]) / 60.0).round(2)
                
                actual_hrs_list = []
                for _, r in monthly_dw_jobs.iterrows():
                    s_real, f_real = r.get("เริ่มจริง"), r.get("เสร็จจริง")
                    act_st = parse_flexible_datetime(s_real)
                    act_fn = parse_flexible_datetime(f_real)
                    if act_st is not None and act_fn is not None:
                        diff_sec = (act_fn - act_st).total_seconds()
                        actual_hrs_list.append(round(diff_sec / 3600.0, 2))
                    else:
                        actual_hrs_list.append(r["เวลาแผน (ชม.)"])
                monthly_dw_jobs["เวลาจริง (ชม.)"] = actual_hrs_list

                drawing_agg = []
                for (p_c, d_c), g_data in monthly_dw_jobs.groupby(["แผนงาน", "ชื่อ Drawing."]):
                    d_plan = g_data["เวลาแผน (ชม.)"].sum()
                    d_act = g_data["เวลาจริง (ชม.)"].sum()
                    d_qty = int(g_data.iloc[0].get("จำนวน", 1)) or 1
                    d_mat = g_data.iloc[0].get("วัสดุ", "-")
                    d_diff = round(d_act - d_plan, 2)
                    d_diff_mins = round(d_diff * 60)
                    
                    d_plan_per_pc = round(d_plan / d_qty, 2)
                    d_act_per_pc = round(d_act / d_qty, 2)
                    accuracy_pct = round((d_plan / d_act * 100), 1) if d_act > 0 else 100.0

                    machines_used = g_data["เลือกเครื่องจักร"].dropna().unique()
                    machines_str = ", ".join([str(m) for m in machines_used if str(m).strip() != ""])
                    if not machines_str:
                        machines_str = "-"
                    
                    pct_diff = ((d_act - d_plan) / d_plan * 100) if d_plan > 0 else 0
                    if pct_diff < -5:
                        cat_status = "FAST"
                        eval_str = f"🟢 เร็วขึ้น {abs(d_diff_mins)} นาที"
                    elif -5 <= pct_diff <= 5:
                        cat_status = "ON_TARGET"
                        eval_str = f"🟡 ตรงตามแผน (±5%)"
                    else:
                        cat_status = "LATE"
                        eval_str = f"🔴 ช้ากว่าแผน +{d_diff_mins} นาที"

                    drawing_agg.append({
                        "แผนงาน": p_c,
                        "ชื่อ Drawing.": d_c,
                        "หัวข้อ Drawing": f"[{p_c}] {d_c} ({machines_str})",
                        "จำนวน": d_qty,
                        "วัสดุ": d_mat,
                        "เครื่องจักรที่ผลิต": machines_str,
                        "จำนวน Step": len(g_data),
                        "เวลาแผน (ชม.)": round(d_plan, 2),
                        "เวลาจริง (ชม.)": round(d_act, 2),
                        "แผน/ชิ้น (ชม.)": d_plan_per_pc,
                        "จริง/ชิ้น (ชม.)": d_act_per_pc,
                        "ความแม่นยำ (%)": accuracy_pct,
                        "ผลต่าง (ชม.)": d_diff,
                        "สถานะกลุ่ม": cat_status,
                        "การประเมิน": eval_str
                    })
                df_draw_full = pd.DataFrame(drawing_agg)

                count_fast = len(df_draw_full[df_draw_full["สถานะกลุ่ม"] == "FAST"])
                count_target = len(df_draw_full[df_draw_full["สถานะกลุ่ม"] == "ON_TARGET"])
                count_late = len(df_draw_full[df_draw_full["สถานะกลุ่ม"] == "LATE"])
                total_late_hrs = df_draw_full[df_draw_full["ผลต่าง (ชม.)"] > 0]["ผลต่าง (ชม.)"].sum()

                st.markdown(f"""
                <div class="kpi-container">
                    <div class="kpi-card kpi-green">
                        <div class="kpi-title">🟢 ผลิตเร็วกว่าแผน (>5%)</div>
                        <div class="kpi-value">{count_fast} <span style="font-size:15px; font-weight:600;">Drawings</span></div>
                        <div class="kpi-sub">ประสิทธิภาพการตัดเฉือนสูงกว่าเกณฑ์</div>
                    </div>
                    <div class="kpi-card kpi-orange">
                        <div class="kpi-title">🟡 ตรงตามเกณฑ์เป้าหมาย (±5%)</div>
                        <div class="kpi-value">{count_target} <span style="font-size:15px; font-weight:600;">Drawings</span></div>
                        <div class="kpi-sub">การประมาณเวลาแม่นยำมาตรฐาน</div>
                    </div>
                    <div class="kpi-card kpi-red">
                        <div class="kpi-title">🔴 ผลิตช้ากว่าแผน (>5%)</div>
                        <div class="kpi-value">{count_late} <span style="font-size:15px; font-weight:600;">Drawings</span></div>
                        <div class="kpi-sub">ช้าสะสมรวม +{total_late_hrs:.2f} ชม.</div>
                    </div>
                </div>
                """, unsafe_allow_html=True)

                f_col1, f_col2 = st.columns([2.5, 4])
                with f_col1:
                    plan_list = ["🌐 ทุกแผนงาน"] + sorted(list(df_draw_full["แผนงาน"].unique()))
                    selected_plan_filter = st.selectbox("🔍 กรองตามรหัสแผนงาน (แผนภูมิกราฟ):", plan_list)
                with f_col2:
                    search_dw = st.text_input("🔍 ค้นหาชื่อ Drawing หรือ เครื่องจักร (แผนภูมิกราฟ):", placeholder="พิมพ์ชื่อ Drawing หรือชื่อเครื่องจักรเพื่อกรองกราฟ...")

                df_draw_filtered = df_draw_full.copy()
                if selected_plan_filter != "🌐 ทุกแผนงาน":
                    df_draw_filtered = df_draw_filtered[df_draw_filtered["แผนงาน"] == selected_plan_filter]
                if search_dw.strip() != "":
                    q_dw_s = search_dw.strip().lower()
                    df_draw_filtered = df_draw_filtered[
                        df_draw_filtered["ชื่อ Drawing."].str.lower().str.contains(q_dw_s) |
                        df_draw_filtered["เครื่องจักรที่ผลิต"].str.lower().str.contains(q_dw_s)
                    ]

                if "Top 10 ช้ากว่าแผน" in sel_dw_limit:
                    df_draw_filtered = df_draw_filtered.sort_values(by="ผลต่าง (ชม.)", ascending=False).head(10).sort_values(by="เวลาจริง (ชม.)", ascending=True)
                elif "Top 10 เร็วกว่าแผน" in sel_dw_limit:
                    df_draw_filtered = df_draw_filtered.sort_values(by="ผลต่าง (ชม.)", ascending=True).head(10).sort_values(by="เวลาจริง (ชม.)", ascending=True)
                else:
                    df_draw_filtered = df_draw_filtered.sort_values(by="เวลาจริง (ชม.)", ascending=True)

                if not df_draw_filtered.empty:
                    chart_h = max(420, len(df_draw_filtered) * 36)
                    fig_dw = px.bar(
                        df_draw_filtered,
                        y="หัวข้อ Drawing",
                        x=["เวลาแผน (ชม.)", "เวลาจริง (ชม.)"],
                        orientation="h",
                        barmode="group",
                        title=f"⏱️ เปรียบเทียบเวลาทำงานแผน vs เวลาจริง ประจำเดือน {month_names[sel_dw_month-1]} {sel_dw_year} ({len(df_draw_filtered)} รายการ)",
                        color_discrete_map={"เวลาแผน (ชม.)": "#94A3B8", "เวลาจริง (ชม.)": "#2563EB"},
                        text_auto='.2f'
                    )
                    fig_dw.update_traces(textposition='outside', cliponaxis=False)
                    fig_dw.update_layout(
                        height=chart_h,
                        plot_bgcolor="#FFFFFF",
                        paper_bgcolor="#FFFFFF",
                        margin=dict(l=20, r=20, t=40, b=20),
                        yaxis_title="[รหัสแผนงาน] ชื่อ Drawing (เครื่องจักรที่ผลิต)",
                        xaxis_title="เวลาในการผลิต (ชั่วโมง)",
                        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
                    )
                    st.plotly_chart(fig_dw, use_container_width=True)

                    st.divider()

                    st.markdown(f"#### 📋 ตารางสรุปเวลาเปรียบเทียบราย Drawing ประจำเดือน {month_names[sel_dw_month-1]} {sel_dw_year}")
                    
                    search_dw_table = st.text_input(
                        "🔍 ค้นหาในตารางเปรียบเทียบราย Drawing (แผนงาน, Drawing, วัสดุ, เครื่องจักร, ผลประเมิน):",
                        placeholder="พิมพ์เพื่อค้นหาข้อมูลในตาราง เช่น SS400, No.1, เร็วขึ้น, ช้ากว่าแผน...",
                        key="search_drawing_table_input"
                    )

                    df_table_display = df_draw_full.copy().sort_values(by="แผนงาน")
                    if search_dw_table.strip() != "":
                        q_dt = search_dw_table.strip().lower()
                        df_table_display = df_table_display[
                            df_table_display["แผนงาน"].astype(str).str.lower().str.contains(q_dt) |
                            df_table_display["ชื่อ Drawing."].astype(str).str.lower().str.contains(q_dt) |
                            df_table_display["วัสดุ"].astype(str).str.lower().str.contains(q_dt) |
                            df_table_display["เครื่องจักรที่ผลิต"].astype(str).str.lower().str.contains(q_dt) |
                            df_table_display["การประเมิน"].astype(str).str.lower().str.contains(q_dt)
                        ]

                    st.dataframe(
                        df_table_display[[
                            "แผนงาน", "ชื่อ Drawing.", "จำนวน", "วัสดุ", "เครื่องจักรที่ผลิต", 
                            "จำนวน Step", "เวลาแผน (ชม.)", "เวลาจริง (ชม.)", "แผน/ชิ้น (ชม.)", "จริง/ชิ้น (ชม.)",
                            "ความแม่นยำ (%)", "ผลต่าง (ชม.)", "การประเมิน"
                        ]],
                        column_config={
                            "แผนงาน": st.column_config.TextColumn("แผนงาน", width=80),
                            "ชื่อ Drawing.": st.column_config.TextColumn("ชื่อ Drawing.", width=170),
                            "จำนวน": st.column_config.NumberColumn("จำนวน", width=60, format="%d"),
                            "วัสดุ": st.column_config.TextColumn("วัสดุ", width=75),
                            "เครื่องจักรที่ผลิต": st.column_config.TextColumn("เครื่องจักร / แผนก", width=140),
                            "จำนวน Step": st.column_config.NumberColumn("Step", width=60, format="%d"),
                            "เวลาแผน (ชม.)": st.column_config.NumberColumn("แผน (ชม.)", width=85, format="%.2f"),
                            "เวลาจริง (ชม.)": st.column_config.NumberColumn("จริง (ชม.)", width=85, format="%.2f"),
                            "แผน/ชิ้น (ชม.)": st.column_config.NumberColumn("แผน/ชิ้น", width=80, format="%.2f"),
                            "จริง/ชิ้น (ชม.)": st.column_config.NumberColumn("จริง/ชิ้น", width=80, format="%.2f"),
                            "ความแม่นยำ (%)": st.column_config.ProgressColumn("ความแม่นยำ", width=100, min_value=0, max_value=150, format="%d%%"),
                            "ผลต่าง (ชม.)": st.column_config.NumberColumn("ผลต่าง (ชม.)", width=85, format="%.2f"),
                            "การประเมิน": st.column_config.TextColumn("ผลประเมิน", width=145),
                        },
                        hide_index=True,
                        use_container_width=True
                    )

                    st.divider()

                    st.markdown("#### 🔬 เจาะลึกความต่างระดับขั้นตอนย่อย (Step Breakdown Inspector)")
                    drawing_options = [f"[{r['แผนงาน']}] {r['ชื่อ Drawing.']}" for _, r in df_draw_full.iterrows()]
                    selected_inspect = st.selectbox("เลือก Drawing ที่ต้องการเจาะลึกดูรายขั้นตอน:", drawing_options)

                    if selected_inspect:
                        ins_plan = selected_inspect.split("] ")[0].replace("[", "").strip()
                        ins_dw = selected_inspect.split("] ")[1].strip()
                        step_details = monthly_dw_jobs[(monthly_dw_jobs["แผนงาน"] == ins_plan) & (monthly_dw_jobs["ชื่อ Drawing."] == ins_dw)].copy()

                        if not step_details.empty:
                            step_diffs, step_evals = [], []
                            for _, sr in step_details.iterrows():
                                s_st, s_fn = sr.get("เริ่มจริง"), sr.get("เสร็จจริง")
                                act_st = parse_flexible_datetime(s_st)
                                act_fn = parse_flexible_datetime(s_fn)
                                if act_st is not None and act_fn is not None:
                                    d_sec = (act_fn - act_st).total_seconds()
                                    a_h = round(d_sec / 3600.0, 2)
                                    v_h = round(a_h - sr["เวลาแผน (ชม.)"], 2)
                                    step_diffs.append(v_h)
                                    d_mins = round(v_h * 60)
                                    step_evals.append(f"🟢 เร็วขึ้น {abs(d_mins)} นาที" if v_h <= 0 else f"🔴 ช้ากว่าแผน +{d_mins} นาที")
                                else:
                                    step_diffs.append(0.0)
                                    step_evals.append("-")
                            
                            step_details["ผลต่าง (ชม.)"] = step_diffs
                            step_details["การประเมิน"] = step_evals

                            st.dataframe(
                                step_details[["ขั้นตอน (Step)", "เลือกเครื่องจักร", "เริ่มจริง", "เสร็จจริง", "Setup (น.)", "Basic (น.)", "โปรแกรม (น.)", "เวลาแผน (ชม.)", "เวลาจริง (ชม.)", "ผลต่าง (ชม.)", "การประเมิน"]],
                                column_config={
                                    "ขั้นตอน (Step)": st.column_config.TextColumn("ขั้นตอน (Step)", width=120),
                                    "เลือกเครื่องจักร": st.column_config.TextColumn("สถานีผลิต", width=140),
                                    "เริ่มจริง": st.column_config.DatetimeColumn("เริ่มจริง", width=130, format="DD/MM HH:mm"),
                                    "เสร็จจริง": st.column_config.DatetimeColumn("เสร็จจริง", width=130, format="DD/MM HH:mm"),
                                    "Setup (น.)": st.column_config.NumberColumn("Setup", width=70, format="%d น."),
                                    "Basic (น.)": st.column_config.NumberColumn("Basic", width=70, format="%d น."),
                                    "โปรแกรม (น.)": st.column_config.NumberColumn("โปรแกรม", width=75, format="%d น."),
                                    "เวลาแผน (ชม.)": st.column_config.NumberColumn("แผน (ชม.)", width=85, format="%.2f"),
                                    "เวลาจริง (ชม.)": st.column_config.NumberColumn("จริง (ชม.)", width=85, format="%.2f"),
                                    "ผลต่าง (ชม.)": st.column_config.NumberColumn("Diff", width=75, format="%.2f"),
                                    "การประเมิน": st.column_config.TextColumn("ผลประเมิน", width=140),
                                },
                                hide_index=True,
                                use_container_width=True
                            )
                else:
                    st.warning("⚠️ ไม่พบข้อมูล Drawing ตามเงื่อนไขที่ค้นหา")
            else:
                st.info(f"ℹ️ ยังไม่มีรายการ Drawing ที่ผลิตเสร็จสิ้นในเดือน {month_names[sel_dw_month-1]} {sel_dw_year}")
        else:
            st.info("ℹ️ ยังไม่มี Drawing ที่ขึ้นสถานะ '✅ เสร็จสิ้นแล้ว'")
    else:
        st.info("ℹ️ ยังไม่มีข้อมูลในระบบ")

# ---------------------------------------------------------
# VIEW 4: รายงานสรุปประจำเดือน
# ---------------------------------------------------------
elif st.session_state.current_view == "📑 รายงานสรุปประจำเดือน":
    if st.session_state.user_role is None:
        st.subheader("🔒 ยืนยันตัวตนสำหรับเข้าใช้งานรายงานสรุปประจำเดือน")
        st.info("กรุณากรอกรหัสผ่านเพื่อเข้าใช้งาน:\n* **ผู้บริหาร/วางแผน:** รหัสผ่านระดับ Admin หรือ รหัสผ่านทั่วไป")
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
            st.subheader("📑 รายงานสรุปผลการผลิตและประสิทธิภาพประจำเดือน (Monthly Production Report)")
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
                act_st = parse_flexible_datetime(s_real)
                act_fn = parse_flexible_datetime(f_real)
                if act_st is not None and act_fn is not None:
                    diff_sec = (act_fn - act_st).total_seconds()
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

            delayed_jobs = monthly_jobs[monthly_jobs["ผลต่าง (ชม.)"] > 0].sort_values(by="ผลต่าง (ชม.)", ascending=False).head(5)

            fig_m_val = px.bar(
                df_m_sum.sort_values(by="มูลค่าผลผลิต (บาท)", ascending=True),
                x="มูลค่าผลผลิต (บาท)",
                y="เครื่องจักร / แผนก",
                orientation="h",
                title="💰 อันดับมูลค่าผลผลิตแยกตามเครื่องจักร (บาท)",
                color="มูลค่าผลผลิต (บาท)",
                color_continuous_scale="Blues",
                text_auto='.2f'
            )
            fig_m_val.update_traces(textposition='outside', cliponaxis=False)
            fig_m_val.update_layout(height=max(380, len(df_m_sum) * 26), plot_bgcolor="#FFFFFF", paper_bgcolor="#FFFFFF", margin=dict(l=20, r=20, t=40, b=20))

            fig_compare = px.bar(
                df_m_sum.sort_values(by="เวลาจริง (ชม.)", ascending=True),
                x=["เวลาแผน (ชม.)", "เวลาจริง (ชม.)"],
                y="เครื่องจักร / แผนก",
                orientation="h",
                barmode="group",
                title="⏱️ เปรียบเทียบเวลาทำงาน: แผนงาน vs ทำงานจริง แต่ละเครื่องจักร (ชม.)",
                color_discrete_map={"เวลาแผน (ชม.)": "#94A3B8", "เวลาจริง (ชม.)": "#2563EB"},
                text_auto='.2f'
            )
            fig_compare.update_traces(textposition='outside', cliponaxis=False)
            fig_compare.update_layout(
                height=max(380, len(df_m_sum) * 26), 
                plot_bgcolor="#FFFFFF", 
                paper_bgcolor="#FFFFFF", 
                margin=dict(l=20, r=20, t=40, b=20), 
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
            )

            rows_m_html = "".join([f"<tr><td>{r['เครื่องจักร / แผนก']}</td><td style='text-align:center;'>{r['จำนวนคิวงาน']}</td><td style='text-align:center;'>{r['ชิ้นงานรวม (ชิ้น)']}</td><td style='text-align:center;'>{r['เวลาแผน (ชม.)']:.2f}</td><td style='text-align:center;'>{r['เวลาจริง (ชม.)']:.2f}</td><td style='text-align:center;'>{r['ผลต่าง']}</td><td style='text-align:right;'>{r['มูลค่าผลผลิต (บาท)']:,.2f} ฿</td><td style='text-align:right; font-weight:bold;'>{r['สัดส่วนมูลค่า (%)']:.1f}%</td></tr>" for _, r in df_m_sum.iterrows()])
            rows_mat_html = "".join([f"<tr><td>{r['ชนิดวัสดุ']}</td><td style='text-align:center;'>{r['จำนวนคิว']}</td><td style='text-align:center;'>{r['จำนวนชิ้นงาน (ชิ้น)']}</td><td style='text-align:center;'>{r['ชั่วโมงผลิตจริง (ชม.)']:.2f}</td><td style='text-align:right;'>{r['มูลค่าผลผลิต (บาท)']:,.2f} ฿</td><td style='text-align:right; font-weight:bold;'>{r['สัดส่วน (%)']:.1f}%</td></tr>" for _, r in df_mat_sum.iterrows()])
            rows_job_html = "".join([f"<tr><td>{r['แผนงาน']}</td><td>{r['ชื่อ Drawing.']}</td><td style='text-align:center;'>{r['จำนวน']}</td><td style='text-align:center;'>{r['วัสดุ']}</td><td>{r['ขั้นตอน (Step)']}</td><td>{r['เลือกเครื่องจักร']}</td><td style='text-align:center;'>{pd.to_datetime(r['เริ่มจริง']).strftime('%d/%m %H:%M') if pd.notna(r['เริ่มจริง']) else '-'}</td><td style='text-align:center;'>{pd.to_datetime(r['เสร็จจริง']).strftime('%d/%m %H:%M') if pd.notna(r['เสร็จจริง']) else '-'}</td><td style='text-align:center;'>{r['เวลาแผน (ชม.)']:.2f}</td><td style='text-align:center;'>{r['เวลาจริง (ชม.)']:.2f}</td><td style='text-align:right;'>{r['มูลค่ารวม (บาท)']:,.2f} ฿</td></tr>" for _, r in monthly_jobs.sort_values(by="Target_Date", ascending=True).iterrows()])

            report_data_dict = {
                "month_str": f"{month_names[selected_month_idx-1]} {selected_year}",
                "print_date": get_bangkok_now().strftime('%d/%m/%Y %H:%M น.'),
                "total_qty": f"{total_qty_pieces:,}",
                "total_hours": f"{total_running_hrs:,.1f}",
                "total_value": f"{total_output_val:,.2f}",
                "on_time": f"{on_time_rate:.1f}",
                "rows_m": rows_m_html,
                "rows_mat": rows_mat_html,
                "rows_job": rows_job_html
            }
            json_report_payload = json.dumps(report_data_dict)

            with r_col_exp:
                st.write("")
                b_col_pdf, b_col_csv = st.columns(2)
                with b_col_pdf:
                    components.html(f"""
                    <button onclick="captureAndPrint()" style="width:100%; background:linear-gradient(135deg, #DC2626 0%, #EF4444 100%); color:white; border:none; padding:9px 14px; border-radius:8px; font-weight:bold; font-size:13px; cursor:pointer; box-shadow:0 3px 8px rgba(220,38,38,0.25);">
                        📄 พิมพ์ / บันทึก PDF (พร้อมรูปกราฟ)
                    </button>
                    <script>
                        async function captureAndPrint() {{
                            const reportData = {json_report_payload};
                            const pDoc = window.parent.document;
                            
                            const plotEls = pDoc.querySelectorAll('.js-plotly-plot');
                            let img1Src = '', img2Src = '';
                            
                            if (window.parent.Plotly && plotEls.length >= 2) {{
                                try {{
                                    img1Src = await window.parent.Plotly.toImage(plotEls[0], {{format: 'png', width: 700, height: 320}});
                                    img2Src = await window.parent.Plotly.toImage(plotEls[1], {{format: 'png', width: 700, height: 320}});
                                }} catch(e) {{
                                    console.error("Error capturing charts:", e);
                                }}
                            }}

                            const chart1Html = img1Src ? `<img src="${{img1Src}}" style="width:100%; max-height:260px; object-fit:contain; border:1px solid #E2E8F0; border-radius:6px;"/>` : '';
                            const chart2Html = img2Src ? `<img src="${{img2Src}}" style="width:100%; max-height:260px; object-fit:contain; border:1px solid #E2E8F0; border-radius:6px;"/>` : '';

                            const fullHtml = `
                            <html>
                            <head>
                                <meta charset="utf-8">
                                <title>PES Monthly Report - ${{reportData.month_str}}</title>
                                <style>
                                    @page {{ size: A4 portrait; margin: 8mm 10mm; }}
                                    body {{ font-family: 'Tahoma', 'Sarabun', 'Arial', sans-serif; color: #1E293B; margin: 0; padding: 10px; font-size: 10px; line-height: 1.35; }}
                                    .header-box {{ display: flex; justify-content: space-between; align-items: center; border-bottom: 2px solid #1E3E62; padding-bottom: 6px; margin-bottom: 10px; }}
                                    .title-text h2 {{ margin: 0; color: #0B192C; font-size: 16px; }}
                                    .title-text p {{ margin: 2px 0 0 0; color: #475569; font-size: 10px; }}
                                    .kpi-grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 6px; margin-bottom: 10px; }}
                                    .kpi-item {{ background: #F8FAFC; border: 1px solid #CBD5E1; border-radius: 6px; padding: 6px 8px; text-align: center; }}
                                    .kpi-item-title {{ font-size: 9.5px; color: #64748B; font-weight: bold; }}
                                    .kpi-item-val {{ font-size: 14px; color: #0F172A; font-weight: 800; margin-top: 2px; }}
                                    h3 {{ color: #1E3E62; font-size: 11px; margin: 10px 0 4px 0; border-left: 4px solid #2563EB; padding-left: 6px; }}
                                    table {{ width: 100%; border-collapse: collapse; margin-bottom: 10px; font-size: 9.5px; }}
                                    th, td {{ border: 1px solid #CBD5E1; padding: 4px 5px; text-align: left; }}
                                    th {{ background-color: #F1F5F9; color: #1E293B; font-weight: bold; }}
                                    tr:nth-child(even) {{ background-color: #F8FAFC; }}
                                    .chart-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-bottom: 10px; }}
                                    .sign-box {{ display: flex; justify-content: space-between; margin-top: 20px; padding-top: 10px; }}
                                    .sign-col {{ width: 30%; text-align: center; border-top: 1px dashed #94A3B8; padding-top: 4px; font-size: 9.5px; }}
                                </style>
                            </head>
                            <body>
                                <div class="header-box">
                                    <div class="title-text">
                                        <h2>บจก. พลวัฒน์ เอ็นจิเนียริ่ง ซัพพลาย (PES)</h2>
                                        <p>รายงานสรุปผลการผลิตและประสิทธิภาพประจำเดือน (Monthly Production Report)</p>
                                    </div>
                                    <div style="text-align: right; font-size: 10px;">
                                        <b>ประจำเดือน:</b> ${{reportData.month_str}}<br>
                                        <b>วันที่ออกรายงาน:</b> ${{reportData.print_date}}
                                    </div>
                                </div>

                                <div class="kpi-grid">
                                    <div class="kpi-item"><div class="kpi-item-title">ชิ้นงานที่ผลิตเสร็จ</div><div class="kpi-item-val">${{reportData.total_qty}} ชิ้น</div></div>
                                    <div class="kpi-item"><div class="kpi-item-title">ชั่วโมงเดินเครื่องจริง</div><div class="kpi-item-val">${{reportData.total_hours}} ชม.</div></div>
                                    <div class="kpi-item"><div class="kpi-item-title">มูลค่าผลผลิตรวม</div><div class="kpi-item-val">${{reportData.total_value}} ฿</div></div>
                                    <div class="kpi-item"><div class="kpi-item-title">ตรงตามแผน (On-Time)</div><div class="kpi-item-val">${{reportData.on_time}} %</div></div>
                                </div>

                                <h3>1. กราฟวิเคราะห์ประสิทธิภาพและมูลค่าผลผลิต</h3>
                                <div class="chart-grid">
                                    <div>${{chart1Html}}</div>
                                    <div>${{chart2Html}}</div>
                                </div>

                                <h3>2. สรุปผลการทำงานและสัดส่วนรายได้แยกตามเครื่องจักร / แผนก</h3>
                                <table>
                                    <thead><tr><th>เครื่องจักร / แผนก</th><th>คิว</th><th>ชิ้นงาน</th><th>แผน (ชม.)</th><th>จริง (ชม.)</th><th>ผลต่าง</th><th>มูลค่าผลผลิต (฿)</th><th>สัดส่วน (%)</th></tr></thead>
                                    <tbody>${{reportData.rows_m}}</tbody>
                                </table>

                                <h3>3. สรุปการใช้วัสดุและเวลาผลิต (Material Insights)</h3>
                                <table>
                                    <thead><tr><th>ชนิดวัสดุ</th><th>คิว</th><th>ชิ้นงาน</th><th>ชั่วโมงผลิตจริง (ชม.)</th><th>มูลค่าผลผลิต (฿)</th><th>สัดส่วน (%)</th></tr></thead>
                                    <tbody>${{reportData.rows_mat}}</tbody>
                                </table>

                                <h3>4. รายการชิ้นงานที่ผลิตเสร็จสิ้นทั้งหมด</h3>
                                <table>
                                    <thead><tr><th>แผนงาน</th><th>ชื่อ Drawing</th><th>จำนวน</th><th>วัสดุ</th><th>ขั้นตอน</th><th>สถานี</th><th>เริ่มจริง</th><th>เสร็จจริง</th><th>แผน (ชม.)</th><th>จริง (ชม.)</th><th>มูลค่า (฿)</th></tr></thead>
                                    <tbody>${{reportData.rows_job}}</tbody>
                                </table>

                                <div class="sign-box">
                                    <div class="sign-col">ผู้จัดทำรายงาน / ฝ่ายวางแผน<br><br><br>( .................................................... )</div>
                                    <div class="sign-col">หัวหน้าแผนกผลิต / ผู้ตรวจสอบ<br><br><br>( .................................................... )</div>
                                    <div class="sign-col">ผู้จัดการโรงงาน / ผู้อนุมัติ<br><br><br>( .................................................... )</div>
                                </div>
                            </body>
                            </html>
                            `;

                            const printWin = window.open('', '_blank');
                            printWin.document.open();
                            printWin.document.write(fullHtml);
                            printWin.document.close();
                            printWin.focus();
                            setTimeout(function() {{ printWin.print(); }}, 600);
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

            st.markdown("#### 📈 กราฟวิเคราะห์มูลค่าและเวลาการผลิตแยกตามเครื่องจักร")
            chart_c1, chart_c2 = st.columns(2)
            with chart_c1:
                st.plotly_chart(fig_m_val, use_container_width=True)
            with chart_c2:
                st.plotly_chart(fig_compare, use_container_width=True)

            st.divider()

            st.markdown("#### ⚠️ 5 อันดับงานที่ผลิตช้ากว่าแผนมากที่สุด (Top 5 Delays)")
            if not delayed_jobs.empty:
                st.dataframe(
                    delayed_jobs[["แผนงาน", "ชื่อ Drawing.", "ขั้นตอน (Step)", "เลือกเครื่องจักร", "เวลาแผน (ชม.)", "เวลาจริง (ชม.)", "ผลต่าง (ชม.)"]],
                    column_config={
                        "แผนงาน": st.column_config.TextColumn("แผนงาน", width=85),
                        "ชื่อ Drawing.": st.column_config.TextColumn("Drawing", width=180),
                        "ขั้นตอน (Step)": st.column_config.TextColumn("ขั้นตอน", width=120),
                        "เลือกเครื่องจักร": st.column_config.TextColumn("สถานี", width=140),
                        "เวลาแผน (ชม.)": st.column_config.NumberColumn("แผน (ชม.)", width=90, format="%.2f"),
                        "เวลาจริง (ชม.)": st.column_config.NumberColumn("จริง (ชม.)", width=90, format="%.2f"),
                        "ผลต่าง (ชม.)": st.column_config.NumberColumn("เกินแผน (+ชม.)", width=110, format="+%.2f ชม."),
                    },
                    hide_index=True,
                    use_container_width=True
                )
            else:
                st.success("🎉 ไม่มีงานใดที่ผลิตช้ากว่าเวลาแผนที่ตั้งไว้ในเดือนนี้")

            st.divider()

            st.markdown(f"#### 📋 รายละเอียดชิ้นงานทั้งหมดที่เสร็จสิ้นในเดือน {month_names[selected_month_idx-1]} {selected_year}")
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
# VIEW 5: จอทีวีกลางโรงงาน (Shop Floor TV Live Dashboard - 22 สถานี)
# ---------------------------------------------------------
elif st.session_state.current_view == "📺 จอทีวีกลางโรงงาน (TV Live)":
    st.cache_data.clear()
    df_live = fetch_jobs_from_supabase()

    now_bangkok = get_bangkok_now()
    cur_date_str = now_bangkok.strftime("%d/%m/%Y")

    planned_finish_map_tv = {}
    if not df_live.empty:
        _, df_summary_tv, _, _ = calculate_shop_schedule(df_live)
        if not df_summary_tv.empty:
            for _, s_row in df_summary_tv.iterrows():
                planned_finish_map_tv[str(s_row.get("ID", ""))] = s_row.get("เวลาจบงาน_DT")
                planned_finish_map_tv[(str(s_row["แผนงาน"]), str(s_row["ชื่อ Drawing."]), str(s_row.get("ขั้นตอน (Step)", "")))] = s_row.get("เวลาจบงาน_DT")
                planned_finish_map_tv[(str(s_row["แผนงาน"]), str(s_row["ชื่อ Drawing."]))] = s_row.get("เวลาจบงาน_DT")

    machine_status_cards = []
    running_machines_count = 0
    hold_machines_count = 0
    idle_machines_count = 0

    for idx_m, m in enumerate(MACHINE_LIST):
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
            h_dt_parsed = parse_flexible_datetime(h_start)
            if h_dt_parsed is not None:
                h_start_txt = f" [เริ่ม {h_dt_parsed.strftime('%H:%M น.')}]"
            hold_alert_html = f'<div style="margin-top:4px; padding:3px 6px; background:rgba(217, 119, 6, 0.35); border:1px dashed #FCD34D; border-radius:6px; font-size:10.5px; color:#FEF08A;">🛑 <b>พักงานรอ:</b> {h_first.get("แผนงาน", "-")} ({h_first.get("ชื่อ Drawing.", "-")}){h_start_txt}</div>'

        if not running_job.empty:
            running_machines_count += 1
            r_info = running_job.iloc[0]
            r_id = str(r_info.get("ID", ""))
            s_start = r_info.get("เริ่มจริง")
            p_code = str(r_info.get("แผนงาน", "-"))
            d_code = str(r_info.get("ชื่อ Drawing.", "-"))
            step_name = str(r_info.get("ขั้นตอน (Step)", "-"))
            
            r_ready_dt = parse_flexible_datetime(r_info.get("วัน-เวลาขึ้นงาน"))
            ready_display_txt = r_ready_dt.strftime("%d/%m %H:%M") if r_ready_dt is not None else "-"

            f_dt = planned_finish_map_tv.get(r_id) or planned_finish_map_tv.get((p_code, d_code, step_name)) or planned_finish_map_tv.get((p_code, d_code))
            finish_display_txt = f_dt.strftime("%d/%m %H:%M") if (f_dt is not None and pd.notna(f_dt)) else "-"
            
            start_disp_txt = "-"
            start_epoch = to_bangkok_epoch_ms(s_start)
            r_start_parsed = parse_flexible_datetime(s_start)

            if r_start_parsed is None and r_ready_dt is not None:
                r_start_parsed = r_ready_dt
                start_epoch = to_bangkok_epoch_ms(r_ready_dt)

            if r_start_parsed is not None:
                start_disp_txt = r_start_parsed.strftime("%H:%M น.")
            
            tv_card_cls = "tv-card tv-card-running"
            badge_html = '<span class="tv-pulse-dot" style="margin-right:6px;"></span> <b style="color:#A7F3D0;">กำลังรันงาน</b>'
            
            if f_dt is not None and pd.notna(f_dt):
                diff_mins = (f_dt - now_bangkok.replace(tzinfo=None)).total_seconds() / 60.0
                if diff_mins < 0:
                    tv_card_cls = "tv-card tv-card-late"
                    badge_html = '<span class="tv-pulse-dot-late" style="margin-right:6px;"></span> <b style="color:#FFFFFF; text-shadow:0 0 4px #000;">🔴 เกินเวลาแผน</b>'
                elif 0 <= diff_mins <= 60:
                    tv_card_cls = "tv-card tv-card-warning"
                    badge_html = '<span class="tv-pulse-dot-warning" style="margin-right:6px;"></span> <b style="color:#FFFFFF; text-shadow:0 0 4px #000;">🟡 ใกล้เสร็จ (<1 ชม.)</b>'

            time_info_combined = f'''
            <div style="font-size:11.5px; font-weight:700; color:#FFFFFF; line-height:1.4;">
                <div style="display:flex; justify-content:space-between; align-items:center;">
                    <span>🚀 <b>เริ่ม:</b> <span style="color:#93C5FD;">{start_disp_txt}</span></span>
                    <span>⏱️ <span class="pes-live-timer" data-start-epoch="{start_epoch}" style="font-family:monospace; font-size:13px; font-weight:900; color:#FDE047;">00:00:00</span></span>
                </div>
                <div style="margin-top:2px; display:flex; justify-content:space-between; font-size:11px; opacity:0.95; background:rgba(0,0,0,0.2); padding:2px 6px; border-radius:4px;">
                    <span>📅 <b>ขึ้น:</b> {ready_display_txt}</span>
                    <span>🏁 <b>จบแผน:</b> <b style="color:#FEF08A;">{finish_display_txt}</b></span>
                </div>
            </div>{hold_alert_html}
            '''

            machine_status_cards.append({
                "machine": m,
                "status": "RUNNING",
                "card_class": tv_card_cls,
                "badge_html": badge_html,
                "plan": p_code,
                "drawing": d_code,
                "step": step_name,
                "time_info": time_info_combined
            })
        elif not hold_job.empty:
            h_info = hold_job.iloc[0]
            h_id = str(h_info.get("ID", ""))
            h_start = h_info.get("เริ่มจริง")
            p_code = str(h_info.get("แผนงาน", "-"))
            d_code = str(h_info.get("ชื่อ Drawing.", "-"))
            step_name = str(h_info.get("ขั้นตอน (Step)", "-"))
            
            h_ready_dt = parse_flexible_datetime(h_info.get("วัน-เวลาขึ้นงาน"))
            ready_display_txt = h_ready_dt.strftime("%d/%m %H:%M") if h_ready_dt is not None else "-"
            
            f_dt = planned_finish_map_tv.get(h_id) or planned_finish_map_tv.get((p_code, d_code, step_name)) or planned_finish_map_tv.get((p_code, d_code))
            finish_display_txt = f_dt.strftime("%d/%m %H:%M") if (f_dt is not None and pd.notna(f_dt)) else "-"

            h_start_txt = ""
            h_st_parsed = parse_flexible_datetime(h_start)
            if h_st_parsed is not None:
                h_start_txt = f" (เริ่มไว้: {h_st_parsed.strftime('%H:%M น.')})"

            time_info_combined = f'''
            <div style="font-size:11.5px; font-weight:700; color:#FEF3C7; line-height:1.4;">
                <div>⚠️ <b>เครื่องหยุด:</b> รอเบิกวัสดุใหม่{h_start_txt}</div>
                <div style="margin-top:2px; display:flex; justify-content:space-between; font-size:11px; opacity:0.9; background:rgba(0,0,0,0.25); padding:2px 6px; border-radius:4px;">
                    <span>📅 <b>ขึ้น:</b> {ready_display_txt}</span>
                    <span>🏁 <b>จบแผน:</b> {finish_display_txt}</span>
                </div>
            </div>
            '''

            machine_status_cards.append({
                "machine": m,
                "status": "HOLD",
                "card_class": "tv-card tv-card-hold",
                "badge_html": '<b style="color:#FDE68A;">🛑 พักงาน (รอวัสดุ)</b>',
                "plan": p_code,
                "drawing": d_code,
                "step": step_name,
                "time_info": time_info_combined
            })
        else:
            idle_machines_count += 1
            next_txt = "ไม่มีคิวรอ"
            next_dates_html = ""
            if not waiting_jobs.empty:
                w_first = waiting_jobs.iloc[0]
                w_id = str(w_first.get("ID", ""))
                p_code = str(w_first.get('แผนงาน', '-'))
                d_code = str(w_first.get('ชื่อ Drawing.', '-'))
                step_name = str(w_first.get('ขั้นตอน (Step)', '-'))
                next_txt = f"คิวถัดไป: {p_code} ({d_code})"
                
                w_ready_dt = parse_flexible_datetime(w_first.get("วัน-เวลาขึ้นงาน"))
                ready_display_txt = w_ready_dt.strftime("%d/%m %H:%M") if w_ready_dt is not None else "-"
                
                f_dt = planned_finish_map_tv.get(w_id) or planned_finish_map_tv.get((p_code, d_code, step_name)) or planned_finish_map_tv.get((p_code, d_code))
                finish_display_txt = f_dt.strftime("%d/%m %H:%M") if (f_dt is not None and pd.notna(f_dt)) else "-"
                
                next_dates_html = f'''
                <div style="margin-top:3px; display:flex; justify-content:space-between; font-size:10.5px; color:#94A3B8; background:rgba(0,0,0,0.25); padding:2px 6px; border-radius:4px;">
                    <span>📅 <b>ขึ้น:</b> {ready_display_txt}</span>
                    <span>🏁 <b>จบแผน:</b> {finish_display_txt}</span>
                </div>
                '''

            machine_status_cards.append({
                "machine": m,
                "status": "IDLE",
                "card_class": "tv-card tv-card-idle",
                "badge_html": '<b style="color:#94A3B8;">⚪ เครื่องว่าง (IDLE)</b>',
                "plan": "พร้อมรับงาน",
                "drawing": next_txt,
                "step": "-",
                "time_info": f"<div style='font-size:11.5px; font-weight:600; color:#CBD5E1;'>📋 คิวรอ: {len(waiting_jobs)} งาน</div>{next_dates_html}"
            })

    st.markdown(f"""
    <div style="background:#0F172A; border:2px solid #1E3A8A; border-radius:16px; padding:12px 20px; color:white; display:flex; justify-content:space-between; align-items:center; margin-bottom:12px; box-shadow:0 8px 24px rgba(0,0,0,0.3);">
        <div>
            <div style="font-size:21px; font-weight:800; color:#38BDF8; display:flex; align-items:center; gap:10px;">
                <span>📺 PES SHOP FLOOR LIVE MONITOR (22 สถานี)</span>
                <span style="font-size:11.5px; background:#1E293B; border:1px solid #38BDF8; color:#38BDF8; padding:2px 8px; border-radius:16px;">Auto 30s</span>
            </div>
            <div style="color:#94A3B8; font-size:12.5px; margin-top:2px;">
                สถานะการผลิต 22 สถานีงานแบบ Real-time | ประจำวันที่ <b>{cur_date_str}</b>
            </div>
        </div>
        <div style="text-align:right;">
            <div id="live-tv-clock" style="font-size:26px; font-weight:900; color:#F8FAFC; font-family:monospace; letter-spacing:1px;">--:--:-- น.</div>
            <div style="font-size:12.5px; font-weight:bold;">
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
            f'<div style="display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:4px;">'
            f'<div style="font-size:14.5px; font-weight:800; letter-spacing:0.2px;">{c["machine"]}</div>'
            f'<div style="font-size:10.5px;">{c["badge_html"]}</div>'
            f'</div>'
            f'<div style="margin: 3px 0;">'
            f'<div style="font-size:13px; font-weight:700; color:#FFFFFF; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">📌 {c["plan"]}</div>'
            f'<div style="font-size:11.5px; color:rgba(255,255,255,0.88); white-space:nowrap; overflow:hidden; text-overflow:ellipsis; margin-top:1px;">📄 {c["drawing"]}</div>'
            f'<div style="font-size:11px; color:rgba(255,255,255,0.72); margin-top:1px;">⚙️ ขั้นตอน: {c["step"]}</div>'
            f'</div>'
            f'<div style="margin-top:6px; padding-top:4px; border-top:1px solid rgba(255,255,255,0.15);">'
            f'{c["time_info"]}'
            f'</div>'
            f'</div>'
        )
        card_items.append(card_item)

    full_grid_html = '<div class="tv-grid-container">' + "".join(card_items) + '</div>'
    st.markdown(full_grid_html, unsafe_allow_html=True)

    components.html("""
    <script>
        function updateTvDashboard() {
            try {
                const now = new Date();
                const nowTs = now.getTime();

                const hrs = String(now.getHours()).padStart(2, '0');
                const mins = String(now.getMinutes()).padStart(2, '0');
                const secs = String(now.getSeconds()).padStart(2, '0');
                const clockEl = window.parent.document.getElementById('live-tv-clock');
                if (clockEl) {
                    clockEl.innerText = hrs + ":" + mins + ":" + secs + " น.";
                }

                const timerEls = window.parent.document.querySelectorAll('.pes-live-timer');
                timerEls.forEach(el => {
                    const startAttr = el.getAttribute('data-start-epoch');
                    const startTs = parseInt(startAttr, 10);
                    if (startTs && startTs > 0) {
                        const diffMs = Math.max(0, nowTs - startTs);
                        const totalSecs = Math.floor(diffMs / 1000);
                        const tHrs = String(Math.floor(totalSecs / 3600)).padStart(2, '0');
                        const tMins = String(Math.floor((totalSecs % 3600) / 60)).padStart(2, '0');
                        const tSecs = String(totalSecs % 60).padStart(2, '0');
                        el.innerText = tHrs + ":" + tMins + ":" + tSecs;
                    } else {
                        el.innerText = "-";
                    }
                });
            } catch (e) {
                console.error(e);
            }
        }

        setInterval(updateTvDashboard, 1000);
        updateTvDashboard();

        setTimeout(function() {
            try {
                const radioBtns = window.parent.document.querySelectorAll('input[type="radio"]');
                if (radioBtns && radioBtns.length >= 5 && radioBtns[4].checked) {
                    radioBtns[4].click();
                }
            } catch(err) {}
        }, 30000);
    </script>
    """, height=0)
