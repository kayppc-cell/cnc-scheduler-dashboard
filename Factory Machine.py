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

    # กรณีรูปแบบ YYYY-MM-DD
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
        # วันเสาร์: 08:30 - 17:00 น. (หักเบรกเช้า 10:00-10:10, เที่ยง 12:00-13:00, บ่าย 15:00-15:10)
        return [
            (datetime.combine(dt_date, dtime(8, 30)), datetime.combine(dt_date, dtime(10, 0))),
            (datetime.combine(dt_date, dtime(10, 10)), datetime.combine(dt_date, dtime(12, 0))),
            (datetime.combine(dt_date, dtime(13, 0)), datetime.combine(dt_date, dtime(15, 0))),
            (datetime.combine(dt_date, dtime(15, 10)), datetime.combine(dt_date, dtime(17, 0)))
        ]
    else:
        # วันจันทร์ - ศุกร์: 08:30 - 20:00 น. (หักเบรกเช้า 10:00-10:10, เที่ยง 12:00-13:00, บ่าย 15:00-15:10, เย็นก่อน OT 17:00-17:30)
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
# 2. ตกแต่ง UI & ไฟกระพริบนีออนชัดเจนระดับโรงงาน
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
    
    .kpi-title { font-size: 13.5px !important; font-weight: 700 !important; margin-bottom: 4px; opacity: 0.95; }
    .kpi-value { font-size: 23px !important; font-weight: 800 !important; }
    .kpi-sub { font-size: 11.5px; margin-top: 4px; opacity: 0.9; font-weight: 500; }

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
    .shop-live-running { background: linear-gradient(135deg, #ECFDF5 0%, #D1FAE5 100%); border: 2px solid #10B981; color: #065F46; }
    .shop-live-hold { background: linear-gradient(135deg, #FFFBEB 0%, #FEF3C7 100%); border: 2px dashed #F59E0B; color: #92400E; }
    .shop-live-idle { background: #F8FAFC; border: 2px solid #CBD5E1; color: #475569; }

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
    .badge-chip { display: inline-flex; align-items: center; padding: 4px 12px; border-radius: 8px; font-weight: 700; font-size: 12.5px; margin-right: 8px; margin-bottom: 4px; }
    .badge-station { background: #EEF2FF; color: #4338CA; border: 1px solid #C7D2FE; }
    .badge-drawing { background: #F0F9FF; color: #0369A1; border: 1px solid #BAE6FD; }
    .badge-qty { background: #ECFDF5; color: #047857; border: 1px solid #A7F3D0; font-weight: 800; }
    .badge-mat { background: #FFFBEB; color: #B45309; border: 1px solid #FDE68A; }
    .badge-date { background: #F3E8FF; color: #6B21A8; border: 1px solid #E9D5FF; font-weight: 800; }
    .badge-finish-date { background: #ECFDF5; color: #065F46; border: 1px solid #A7F3D0; font-weight: 800; }

    .step-card { background: #FFFFFF; padding: 14px 16px; border-radius: 14px; border: 1.5px solid #E2E8F0; margin-bottom: 12px; }
    div.stButton > button:disabled { background-color: #F1F5F9 !important; color: #94A3B8 !important; border-color: #CBD5E1 !important; cursor: not-allowed !important; }

    .tv-grid-container { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 10px; margin-top: 8px; }
    .tv-card { border-radius: 12px; padding: 12px 14px; color: #FFFFFF !important; box-shadow: 0 4px 14px rgba(0,0,0,0.12); display: flex; flex-direction: column; justify-content: space-between; min-height: 140px; border: 1px solid rgba(255,255,255,0.12); }
    .tv-card-running { background: linear-gradient(135deg, #065F46 0%, #059669 100%) !important; border-left: 7px solid #34D399 !important; }
    .tv-card-warning { background: linear-gradient(135deg, #9A3412 0%, #C2410C 100%) !important; border-left: 7px solid #FDE047 !important; }
    .tv-card-late { background: linear-gradient(135deg, #7F1D1D 0%, #991B1B 100%) !important; border-left: 7px solid #EF4444 !important; }
    .tv-card-hold { background: linear-gradient(135deg, #92400E 0%, #D97706 100%) !important; border-left: 7px solid #FBBF24 !important; }
    .tv-card-idle { background: linear-gradient(135deg, #1E293B 0%, #334155 100%) !important; border-left: 7px solid #64748B !important; opacity: 0.92; }

    .tv-pulse-dot {
        width: 13px !important;
        height: 13px !important;
        border-radius: 50% !important;
        background-color: #10B981 !important;
        border: 2px solid #FFFFFF !important;
        display: inline-block;
        vertical-align: middle !important;
        box-shadow: 0 0 8px #10B981, 0 0 16px rgba(16, 185, 129, 0.8) !important;
    }
</style>
""", unsafe_allow_html=True)

header_content = f'''<div class="main-header">{logo_html}<div class="header-text"><h1>ระบบติดตามและบันทึกงานหน้าเครื่องแผนกผลิต</h1><p>จ.-ศ. (08:30-20:00 น.) | ส. (08:30-17:00 น.) | เบรกเช้า 10:00-10:10 น. | พักเที่ยง 12:00-13:00 น. | เบรกบ่าย 15:00-15:10 น. | หยุดวันอาทิตย์</p></div></div>'''
st.markdown(header_content, unsafe_allow_html=True)

# =========================================================
# 3. กำหนดสิทธิ์ & Session Defaults
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
# 4. ฟังก์ชัน Supabase
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
            return False
    except Exception:
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
            return False
    except Exception:
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

        job_ready_time = selected_job["ready_at"]
        if cur_time < job_ready_time:
            cur_time = get_next_valid_work_time(job_ready_time)

        setup_mins = selected_job["setup_mins"] if selected_job["need_setup"] else 0
        setup_hrs = setup_mins / 60.0
        actual_cut_hrs = selected_job["remain_cut_hrs"]
        
        raw_step = safe_str(selected_job.get("ขั้นตอน (Step)"), "รอหน้าเครื่องระบุ")
        step_raw = "รอหน้าเครื่องระบุ" if raw_step in ["", "None", "nan", "รันงาน"] else raw_step
            
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
                    "แผนงาน": job_code, "ชื่อ Drawing.": drawing_name,
                    "จำนวน": qty_val, "ขั้นตอน (Step)": "Setup ตั้งเครื่อง", 
                    "กิจกรรม": "🔧 ตั้งเครื่อง / เซ็ตศูนย์",
                    "เครื่องจักร": earliest_m, "วัสดุ": selected_job.get("วัสดุ", "-"),
                    "เวลาเริ่ม": s_st, "เวลาเสร็จ": s_en, "ระยะเวลา": f"{setup_mins:.0f} นาที"
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
                "แผนงาน": job_code, "ชื่อ Drawing.": drawing_name,
                "จำนวน": qty_val, "ขั้นตอน (Step)": step_raw,
                "กิจกรรม": "🔴 งานด่วน" if selected_job["is_urgent"] else "⚙️ งานปกติ",
                "เครื่องจักร": earliest_m, "วัสดุ": selected_job.get("วัสดุ", "-"),
                "เวลาเริ่ม": c_st, "เวลาเสร็จ": c_en, "ระยะเวลา": f"{seg_hrs:.2f} ชม."
            })
        
        total_cycle = setup_hrs + actual_cut_hrs
        orig_ready_dt = parse_flexible_datetime(selected_job.get("วัน-เวลาขึ้นงาน"))

        summary_records.append({
            "ID": selected_job.get("ID", ""), 
            "เครื่องจักร": earliest_m, 
            "สถานะ": selected_job["สถานะงาน"],
            "ประเภทงาน": "🔴 งานด่วนแทรก" if selected_job["is_urgent"] else "🟢 งานปกติ",
            "แผนงาน": job_code, "ชื่อ Drawing.": drawing_name, 
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
# 6. เมนูเปลี่ยนโหมด (5 มุมมอง)
# =========================================================
nav_options = [
    "👷 โหมดช่างหน้าเครื่อง", 
    "📊 แดชบอร์ดภาพรวมโรงงาน", 
    "📈 วิเคราะห์ประสิทธิภาพราย Drawing", 
    "📑 รายงานสรุปประจำเดือน", 
    "📺 จอทีวีกลางโรงงาน (TV Live)"
]

cur_idx = nav_options.index(st.session_state.current_view) if st.session_state.current_view in nav_options else 0
selected_tab = st.radio("เลือกมุมมอง:", nav_options, index=cur_idx, horizontal=True, label_visibility="collapsed")

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
        run_mode = st.radio("⚙️ รูปแบบการผลิต:", ["🔹 รันทีละคิว (Piece by Piece)", "📦 รันรวมหลายงานพร้อมกัน (Batch Processing)"], horizontal=True)

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
            if act_dt is not None: st_txt = act_dt.strftime("%H:%M น.")

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
                        update_supabase_job(int(r["ID"]), {"status": "🟩 เสร็จสิ้นแล้ว", "actual_finish": now_str})
                    st.toast("บันทึกจบงานจริงทุกคิวเรียบร้อย!", icon="🏁")
                    st.rerun()

        machine_any_running = any("กำลังผลิต" in str(r.get("สถานะงาน", "")) for _, r in m_all_jobs.iterrows())
        next_available_start_found = False

        for queue_idx, (_, wo_item) in enumerate(m_wo_summary.iterrows(), 1):
            target_id = safe_int(wo_item["ID"])
            step_record = m_all_jobs[m_all_jobs["ID"] == target_id]
            if step_record.empty: continue
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

            can_start = is_step_waiting if "Batch" in run_mode else (is_step_waiting and not machine_any_running and not next_available_start_found)
            if can_start and "Batch" not in run_mode:
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
            if is_step_running: card_style_class += " step-card-running"
            elif is_step_hold: card_style_class += " step-card-hold"
            elif can_start: card_style_class += " step-card-ready"
            elif is_step_finished: card_style_class += " step-card-finished"

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
                    st.caption(f"**ขั้นตอน:** <span style='color:#D97706; font-weight:800;'>🟧 พร้อมเริ่มงาน (Ready to Start)</span>" if can_start else f"**ขั้นตอน:** <span style='color:#64748B; font-weight:600;'>🔒 รอลำดับคิวก่อนหน้าตามแผน</span>", unsafe_allow_html=True)

                if not is_step_finished:
                    step_val = st.text_input(f"ชื่อขั้นตอนงาน (Step):", value=s_name, placeholder="เช่น OP10, ปาดผิวเจาะรู...", key=f"input_step_name_{target_id}")

                    if is_step_hold:
                        c_btn_save, c_btn_resume = st.columns([1.5, 4])
                        with c_btn_save:
                            if st.button("💾 บันทึกชื่อ", key=f"btn_save_edit_{target_id}", use_container_width=True):
                                if update_supabase_job(target_id, {"step_name": safe_str(step_val, s_name)}):
                                    st.toast(f"บันทึกชื่อขั้นตอนเรียบร้อย!", icon="💾")
                                    st.rerun()
                        with c_btn_resume:
                            if st.button("▶️ ได้วัสดุใหม่แล้ว (Resume)", key=f"btn_resume_{target_id}", type="primary", use_container_width=True):
                                if update_supabase_job(target_id, {"step_name": safe_str(step_val, s_name), "status": "🟦 กำลังผลิต", "actual_start": get_bangkok_str()}):
                                    st.toast("เริ่มรันงานต่อเรียบร้อย!", icon="🚀")
                                    st.rerun()
                    elif is_step_running:
                        c_btn_save, c_btn_hold, c_btn_finish = st.columns([1.5, 2.5, 2])
                        with c_btn_save:
                            if st.button("💾 บันทึกชื่อ", key=f"btn_save_edit_{target_id}", use_container_width=True):
                                if update_supabase_job(target_id, {"step_name": safe_str(step_val, s_name)}):
                                    st.toast(f"บันทึกชื่อขั้นตอนเรียบร้อย!", icon="💾")
                                    st.rerun()
                        with c_btn_hold:
                            if st.button("🛑 พักงาน (รอวัสดุ)", key=f"btn_hold_{target_id}", use_container_width=True):
                                if update_supabase_job(target_id, {"step_name": safe_str(step_val, s_name), "status": "🟨 พักงาน (รอวัสดุ)"}):
                                    st.toast("พักงานเรียบร้อย สามารถรันงานอื่นต่อได้ทันที!", icon="🛑")
                                    st.rerun()
                        with c_btn_finish:
                            if st.button("🏁 Finish", key=f"btn_finish_step_{target_id}", type="primary", use_container_width=True):
                                if update_supabase_job(target_id, {"status": "🟩 เสร็จสิ้นแล้ว", "actual_finish": get_bangkok_str()}):
                                    st.toast(f"บันทึกเวลาจบจริงเรียบร้อย!", icon="🏁")
                                    st.rerun()
                    else:
                        c_btn_save, c_btn_start, c_btn_finish = st.columns([1.5, 2, 2])
                        with c_btn_save:
                            if st.button("💾 บันทึกชื่อ", key=f"btn_save_edit_{target_id}", use_container_width=True):
                                if update_supabase_job(target_id, {"step_name": safe_str(step_val, s_name)}):
                                    st.toast(f"บันทึกชื่อขั้นตอนเรียบร้อย!", icon="💾")
                                    st.rerun()
                        with c_btn_start:
                            if can_start:
                                if st.button("🚀 Start", key=f"btn_start_step_{target_id}", type="primary", use_container_width=True):
                                    if update_supabase_job(target_id, {"step_name": safe_str(step_val, s_name), "status": "🟦 กำลังผลิต", "actual_start": get_bangkok_str()}):
                                        st.toast(f"เริ่มผลิตแล้ว!", icon="🚀")
                                        st.rerun()
                            else:
                                st.button("🚀 Start", key=f"btn_start_disabled_{target_id}", disabled=True, use_container_width=True)
                        with c_btn_finish:
                            st.button("🏁 Finish", key=f"btn_finish_disabled_{target_id}", disabled=True, use_container_width=True)
                st.markdown("</div>", unsafe_allow_html=True)

# ---------------------------------------------------------
# VIEW 2: Dashboard ภาพรวมโรงงาน (ฉบับสมบูรณ์ กราฟและตารางครบ 100%)
# ---------------------------------------------------------
elif st.session_state.current_view == "📊 แดชบอร์ดภาพรวมโรงงาน":
    is_admin = (st.session_state.user_role == "admin")
    c_head, c_logout = st.columns([8, 2])
    with c_head:
        st.subheader("📊 แดชบอร์ดภาพรวมโรงงานและการคำนวณต้นทุน 👑 (โหมดผู้บริหาร)" if is_admin else "📊 แดชบอร์ดภาพรวมโรงงานและการคำนวณต้นทุน 👁️ (โหมดเข้าชมทั่วไป)")
    with c_logout:
        if st.button("🚪 ออกจากระบบ", use_container_width=True):
            st.session_state.user_role = None
            st.rerun()

    df_db = fetch_jobs_from_supabase()

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
                "🟩 เสร็จสิ้นแล้ว": "#10B981", "🟦 กำลังผลิต": "#2563EB",
                "🟨 พักงาน (รอวัสดุ)": "#F59E0B", "🟧 รอคิวผลิต": "#94A3B8"
            }
            fig_donut = px.pie(
                status_counts, values="จำนวน", names="สถานะ", hole=0.55,
                color="สถานะ", color_discrete_map=donut_color_map, title="📊 สัดส่วนสถานะงานทั้งหมดในระบบ"
            )
            fig_donut.update_traces(textposition='inside', textinfo='percent+value')
            fig_donut.update_layout(height=260, margin=dict(l=10, r=10, t=35, b=10), plot_bgcolor="#FFFFFF", paper_bgcolor="#FFFFFF")
            st.plotly_chart(fig_donut, use_container_width=True)

        with ov_col2:
            st.markdown("**⚠️ 3 อันดับสถานีคอขวดสูงสุด (คิวงานค้างรอนานที่สุด):**")
            waiting_sub = calc_df[calc_df["สถานะงาน"] == "🟧 รอคิวผลิต"]
            if not waiting_sub.empty:
                m_load = waiting_sub.groupby("เลือกเครื่องจักร").agg(คิวรอ=('ID', 'count'), ชั่วโมงรวม=('รวม (ชม.)', 'sum')).reset_index().sort_values(by="คิวรอ", ascending=False).head(3)
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
            rate_map_quick = DEFAULT_RATES
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

        st.divider()

        df_gantt, df_summary, df_util, total_plan_hrs = calculate_shop_schedule(calc_df)

        editor_finish_map = {}
        if not df_summary.empty:
            for _, s_row in df_summary.iterrows():
                editor_finish_map[str(s_row.get("ID", ""))] = s_row.get("เวลาจบงาน", "-")

        column_order = [
            "ID", "แผนงาน", "ชื่อ Drawing.", "จำนวน", "วัสดุ", "ประเภทงาน", "ขั้นตอน (Step)",
            "เลือกเครื่องจักร", "วัน-เวลาขึ้นงาน", "Setup (น.)", "Basic (น.)", "โปรแกรม (น.)", "รวม (ชม.)", "สถานะงาน"
        ]
        calc_df = calc_df[[c for c in column_order if c in calc_df.columns]]
        active_jobs_editor_df = calc_df[calc_df["สถานะงาน"].isin(["🟧 รอคิวผลิต", "🟦 กำลังผลิต", "🟨 พักงาน (รอวัสดุ)"])].copy()

        active_jobs_editor_df["temp_ready_dt"] = active_jobs_editor_df["วัน-เวลาขึ้นงาน"].apply(parse_flexible_datetime)
        active_jobs_editor_df = active_jobs_editor_df.sort_values(by=["temp_ready_dt", "ID"], ascending=[True, True], na_position="last").drop(columns=["temp_ready_dt"]).reset_index(drop=True)

        calculated_finish_dates = []
        for _, row_item in active_jobs_editor_df.iterrows():
            row_id_str = str(row_item["ID"])
            if row_id_str in st.session_state.cleared_finish_jobs:
                calculated_finish_dates.append("")
                continue
            mapped_val = editor_finish_map.get(row_id_str)
            if mapped_val and mapped_val != "-":
                calculated_finish_dates.append(mapped_val)
            else:
                ready_parsed = parse_flexible_datetime(row_item.get("วัน-เวลาขึ้นงาน"))
                if ready_parsed is None or pd.isna(ready_parsed): ready_parsed = get_bangkok_now().replace(tzinfo=None)
                s_m = safe_float(row_item.get("Setup (น.)"), 10.0)
                b_m = safe_float(row_item.get("Basic (น.)"), 0.0)
                p_m = safe_float(row_item.get("โปรแกรม (น.)"), 120.0)
                tot_hrs = (s_m + b_m + p_m) / 60.0
                try:
                    _, fallback_end_dt = add_work_time_with_shift(ready_parsed, tot_hrs)
                    calculated_finish_dates.append(fallback_end_dt.strftime("%d/%m/%Y %H:%M"))
                except Exception:
                    calculated_finish_dates.append("-")

        active_jobs_editor_df["วัน-เวลาจบงาน"] = calculated_finish_dates
        active_jobs_editor_df["วัน-เวลาขึ้นงาน"] = active_jobs_editor_df["วัน-เวลาขึ้นงาน"].apply(
            lambda x: x.strftime("%d/%m/%Y %H:%M") if (pd.notna(x) and isinstance(x, (datetime, pd.Timestamp))) else ("" if (pd.isna(x) or str(x).strip() in ["None", "nan", "NaT"]) else str(x))
        )
        active_jobs_editor_df["ลบ"] = st.session_state.active_select_all

        with st.expander("📝 รายการสั่งผลิตในระบบ (ตารางสั่งการผลิต)", expanded=True):
            if is_admin:
                tool_col1, tool_col2, tool_search = st.columns([2.5, 4.5, 3])
                with tool_col1:
                    b_c1, b_c2 = st.columns(2)
                    with b_c1:
                        if st.button("✅ เลือกหมด", use_container_width=True):
                            st.session_state.active_select_all = True
                            st.rerun()
                    with b_c2:
                        if st.button("❌ ยกเลิก", use_container_width=True):
                            st.session_state.active_select_all = False
                            st.rerun()
                with tool_col2:
                    if st.button("⚡ รันคิวลูกโซ่อัตโนมัติ (Auto Chain Queue)", help="ล้างวันที่มั่ว แล้วนำเวลาจบงานของแถวบนมาต่อเป็นวันขึ้นงานแถวล่างให้ทันที", type="secondary", use_container_width=True):
                        m_chain_tracker = {}
                        for _, r in active_jobs_editor_df.iterrows():
                            j_id = safe_int(r["ID"])
                            m_target = str(r["เลือกเครื่องจักร"])
                            if m_target not in m_chain_tracker:
                                r_dt = parse_flexible_datetime(r["วัน-เวลาขึ้นงาน"])
                                if r_dt is None or pd.isna(r_dt): r_dt = get_bangkok_now().replace(tzinfo=None)
                            else:
                                r_dt = m_chain_tracker[m_target]
                            s_m = safe_float(r.get("Setup (น.)"), 10.0)
                            b_m = safe_float(r.get("Basic (น.)"), 0.0)
                            p_m = safe_float(r.get("โปรแกรม (น.)"), 120.0)
                            tot_h = (s_m + b_m + p_m) / 60.0
                            _, f_dt = add_work_time_with_shift(r_dt, tot_h)
                            m_chain_tracker[m_target] = f_dt
                            update_supabase_job(j_id, {"ready_at": r_dt.strftime("%Y-%m-%d %H:%M:%S")})
                        st.cache_data.clear()
                        st.toast("รันคิวลูกโซ่อัตโนมัติสำเร็จ!", icon="⚡")
                        st.rerun()

                with tool_search:
                    search_query = st.text_input("🔍 ค้นหา:", placeholder="ค้นหา เช่น no.7, 26-107...", key="search_active_editor_input")
            else:
                search_query = st.text_input("🔍 ค้นหา:", placeholder="ค้นหา...", key="search_active_editor_input_viewer")

            display_df = active_jobs_editor_df.copy()
            if search_query.strip():
                q = search_query.strip().lower()
                display_df = display_df[display_df["แผนงาน"].astype(str).str.lower().str.contains(q) | display_df["ชื่อ Drawing."].astype(str).str.lower().str.contains(q) | display_df["เลือกเครื่องจักร"].astype(str).str.lower().str.contains(q)]

            if is_admin:
                edited_jobs = st.data_editor(
                    display_df,
                    key="editor_cnc_jobs_grid_main",
                    column_order=["แผนงาน", "ชื่อ Drawing.", "จำนวน", "วัสดุ", "ประเภทงาน", "ขั้นตอน (Step)", "เลือกเครื่องจักร", "วัน-เวลาขึ้นงาน", "วัน-เวลาจบงาน", "Setup (น.)", "Basic (น.)", "โปรแกรม (น.)", "รวม (ชม.)", "สถานะงาน", "ลบ"],
                    column_config={
                        "ID": None,
                        "วัน-เวลาขึ้นงาน": st.column_config.TextColumn("วัน-เวลาขึ้นงาน", width=155),
                        "วัน-เวลาจบงาน": st.column_config.TextColumn("วัน-เวลาจบงาน", width=135, disabled=False),
                        "ลบ": st.column_config.CheckboxColumn("🗑️", width=55, default=False)
                    },
                    hide_index=True,
                    use_container_width=True
                )
                
                c_save, c_del, _ = st.columns([2.5, 3.5, 4])
                with c_save:
                    if st.button("💾 บันทึกข้อมูลลง Supabase", type="primary", use_container_width=True):
                        for _, row in edited_jobs.iterrows():
                            p_code = safe_str(row.get("แผนงาน"), "")
                            if not p_code: continue
                            raw_ready = row.get("วัน-เวลาขึ้นงาน")
                            dt_parsed = parse_flexible_datetime(raw_ready)
                            ready_str = dt_parsed.strftime("%Y-%m-%d %H:%M:%S") if (dt_parsed is not None and pd.notna(dt_parsed)) else None
                            payload = {
                                "plan_code": p_code, "drawing_name": safe_str(row.get("ชื่อ Drawing."), ""),
                                "qty": safe_int(row.get("จำนวน"), 1), "material": safe_str(row.get("วัสดุ"), "SS400"),
                                "job_type": safe_str(row.get("ประเภทงาน"), "🟢 งานปกติ"), "step_name": safe_str(row.get("ขั้นตอน (Step)"), "รอหน้าเครื่องระบุ"),
                                "machine_name": safe_str(row.get("เลือกเครื่องจักร"), "No.1 Awea"), "ready_at": ready_str,
                                "setup_mins": safe_float(row.get("Setup (น.)"), 10.0), "basic_hrs": safe_float(row.get("Basic (น.)"), 0.0),
                                "prog_hrs": safe_float(row.get("โปรแกรม (น.)"), 120.0), "status": safe_str(row.get("สถานะงาน"), "🟧 รอคิวผลิต")
                            }
                            row_id = row.get("ID")
                            if pd.isna(row_id) or str(row_id).strip() in ["", "None", "nan"]:
                                insert_supabase_job(payload)
                            else:
                                update_supabase_job(int(float(row_id)), payload)
                        st.cache_data.clear()
                        st.toast("บันทึกข้อมูลสำเร็จ!", icon="💾")
                        st.rerun()

                with c_del:
                    active_del = edited_jobs[edited_jobs["ลบ"] == True]
                    if st.button(f"🗑️ ลบรายการที่เลือก ({len(active_del)})", disabled=(len(active_del) == 0), type="secondary", use_container_width=True):
                        for _, row in active_del.iterrows():
                            if pd.notna(row.get("ID")): delete_supabase_job(int(float(row["ID"])))
                        st.cache_data.clear()
                        st.rerun()
            else:
                st.dataframe(display_df[[c for c in display_df.columns if c not in ["ID", "ลบ"]]], hide_index=True, use_container_width=True)

        st.divider()

        # =====================================================
        # 2. ใบจ่ายคิวงานหน้าเครื่อง (Work Order Sheet)
        # =====================================================
        if not df_summary.empty:
            st.subheader("📋 ใบจ่ายคิวงานหน้าเครื่อง (Work Order Sheet)")
            df_display = df_summary.sort_values(by="เวลาเริ่มจริง", ascending=True).copy()
            df_display["ลำดับคิว"] = df_display.groupby("เครื่องจักร").cumcount() + 1
            df_display["ลำดับคิว"] = df_display["ลำดับคิว"].apply(lambda q: f"คิวที่ {q}")
            display_cols = [c for c in df_display.columns if c not in ["เวลาเริ่มจริง", "เวลาจบงาน_DT"]]
            styled_df_display = df_display[display_cols].style.apply(
                highlight_running_deadlines, planned_finish_map=dict(zip(df_summary["ID"].astype(str), df_summary["เวลาจบงาน_DT"])), axis=1
            )
            st.dataframe(styled_df_display, use_container_width=True, hide_index=True)
            st.divider()

        # =====================================================
        # 3. ผังเวลาขึ้นงาน (Gantt Chart Timeline)
        # =====================================================
        if not df_gantt.empty:
            st.subheader("📊 ผังเวลาขึ้นงานที่กำลังผลิตและรอคิว (Gantt Chart Timeline)")
            plot_gantt_df = df_gantt.copy()
            plot_gantt_df["เริ่มแสดง"] = plot_gantt_df["เวลาเริ่ม"].dt.strftime("%d/%m/%Y %H:%M น.")
            plot_gantt_df["เสร็จแสดง"] = plot_gantt_df["เวลาเสร็จ"].dt.strftime("%d/%m/%Y %H:%M น.")

            fig = px.timeline(
                plot_gantt_df, x_start="เวลาเริ่ม", x_end="เวลาเสร็จ", y="เครื่องจักร", color="แผนงาน",
                text="ข้อความบนแท่งกราฟ", category_orders={"เครื่องจักร": MACHINE_LIST}
            )
            fig.update_yaxes(autorange="reversed", type="category", categoryorder="array", categoryarray=MACHINE_LIST)
            fig.update_layout(height=max(450, len(MACHINE_LIST) * 32), plot_bgcolor="#FFFFFF", paper_bgcolor="#FFFFFF")
            st.plotly_chart(fig, use_container_width=True)
            st.divider()

        # =====================================================
        # 4. อัตราการใช้งานเครื่องจักร (% Machine Utilization)
        # =====================================================
        st.subheader("📈 อัตราการใช้งานเครื่องจักรและแผนกผลิต (% Utilization)")
        fig_bar = px.bar(
            df_util, x="อัตราการใช้งาน (%)", y="เครื่องจักร", orientation="h",
            color="อัตราการใช้งาน (%)", color_continuous_scale="Blues", text="ข้อความแสดง",
            range_x=[0, 105], category_orders={"เครื่องจักร": MACHINE_LIST}
        )
        fig_bar.update_yaxes(autorange="reversed", type="category", categoryorder="array", categoryarray=MACHINE_LIST)
        fig_bar.update_layout(height=max(500, len(MACHINE_LIST) * 28), plot_bgcolor="#FFFFFF", paper_bgcolor="#FFFFFF")
        fig_bar.add_vline(x=85, line_dash="dash", line_color="#EF4444", annotation_text="เป้าหมาย 85%")
        st.plotly_chart(fig_bar, use_container_width=True)
        st.divider()

        # =====================================================
        # 5. ตารางคำนวณมูลค่าและต้นทุนค่าเครื่องจักร (Cost Calculation)
        # =====================================================
        st.subheader("💰 ตารางคำนวณมูลค่าและต้นทุนค่าเครื่องจักร (Machining Cost Calculation)")
        finished_jobs_df = df_db[df_db["สถานะงาน"].isin(["🟩 เสร็จสิ้นแล้ว", "✅ เสร็จสิ้นแล้ว"])].copy()
        if not finished_jobs_df.empty:
            cost_df = finished_jobs_df.copy()
            cost_df["รวม (ชม.)"] = ((cost_df["Setup (น.)"] + cost_df["Basic (น.)"] + cost_df["โปรแกรม (น.)"]) / 60.0).round(2)
            cost_df["เรตราคา (บาท/ชม.)"] = cost_df["เลือกเครื่องจักร"].map(DEFAULT_RATES).fillna(500)
            cost_df["มูลค่ารวม (บาท)"] = cost_df["รวม (ชม.)"] * cost_df["เรตราคา (บาท/ชม.)"]
            st.dataframe(cost_df[["แผนงาน", "ชื่อ Drawing.", "จำนวน", "ขั้นตอน (Step)", "เลือกเครื่องจักร", "รวม (ชม.)", "เรตราคา (บาท/ชม.)", "มูลค่ารวม (บาท)"]], use_container_width=True, hide_index=True)
        else:
            st.info("ℹ️ ยังไม่มีรายการที่ขึ้นสถานะ '✅ เสร็จสิ้นแล้ว' จึงยังไม่มีการคำนวณมูลค่าต้นทุน")

# ---------------------------------------------------------
# VIEW 3: วิเคราะห์ Drawing
# ---------------------------------------------------------
elif st.session_state.current_view == "📈 วิเคราะห์ประสิทธิภาพราย Drawing":
    st.subheader("📈 วิเคราะห์และเปรียบเทียบเวลาทำงานจริงราย Drawing")
    df_db = fetch_jobs_from_supabase()
    if not df_db.empty:
        finished_jobs = df_db[df_db["สถานะงาน"].isin(["🟩 เสร็จสิ้นแล้ว", "✅ เสร็จสิ้นแล้ว"])].copy()
        if not finished_jobs.empty:
            st.dataframe(finished_jobs[["แผนงาน", "ชื่อ Drawing.", "ขั้นตอน (Step)", "เลือกเครื่องจักร", "เริ่มจริง", "เสร็จจริง"]], use_container_width=True, hide_index=True)
        else:
            st.info("ℹ️ ยังไม่มีงานที่ขึ้นสถานะเสร็จสิ้น")

# ---------------------------------------------------------
# VIEW 4: รายงานสรุปประจำเดือน
# ---------------------------------------------------------
elif st.session_state.current_view == "📑 รายงานสรุปประจำเดือน":
    st.subheader("📑 รายงานสรุปผลการผลิตประจำเดือน")
    st.info("พร้อมออกรายงานและสรุปข้อมูลประจำเดือน")

# ---------------------------------------------------------
# VIEW 5: จอทีวีกลางโรงงาน (Shop Floor TV Live Dashboard)
# ---------------------------------------------------------
elif st.session_state.current_view == "📺 จอทีวีกลางโรงงาน (TV Live)":
    st.cache_data.clear()
    df_live = fetch_jobs_from_supabase()
    now_bangkok = get_bangkok_now()
    cur_date_str = now_bangkok.strftime("%d/%m/%Y")

    machine_cards = []
    r_count, h_count, i_count = 0, 0, 0

    for m in MACHINE_LIST:
        m_jobs = df_live[df_live["เลือกเครื่องจักร"] == m] if not df_live.empty else pd.DataFrame()
        running_job = m_jobs[m_jobs["สถานะงาน"].str.contains("กำลังผลิต")]
        hold_job = m_jobs[m_jobs["สถานะงาน"].str.contains("พักงาน")]
        waiting_jobs = m_jobs[m_jobs["สถานะงาน"].str.contains("รอคิว")]

        if not running_job.empty:
            r_count += 1
            r_info = running_job.iloc[0]
            start_epoch = to_bangkok_epoch_ms(r_info.get("เริ่มจริง"))
            machine_cards.append(f"""
            <div class="tv-card tv-card-running">
                <div style="font-size:15px; font-weight:800;">{m}</div>
                <div><b>{r_info.get('แผนงาน', '-')}</b> | {r_info.get('ชื่อ Drawing.', '-')}</div>
                <div style="font-size:12px; opacity:0.9;">⏱️ เดินเวลา: <span class="pes-live-timer" data-start-epoch="{start_epoch}" style="font-family:monospace; font-weight:bold; color:#FEF08A;">00:00:00</span></div>
            </div>
            """)
        elif not hold_job.empty:
            h_count += 1
            machine_cards.append(f"""
            <div class="tv-card tv-card-hold">
                <div style="font-size:15px; font-weight:800;">{m}</div>
                <div>🛑 พักงาน (รอวัสดุ)</div>
            </div>
            """)
        else:
            i_count += 1
            next_txt = f"คิวถัดไป: {waiting_jobs.iloc[0].get('แผนงาน')}" if not waiting_jobs.empty else "ไม่มีคิวรอ"
            machine_cards.append(f"""
            <div class="tv-card tv-card-idle">
                <div style="font-size:15px; font-weight:800;">{m}</div>
                <div style="color:#94A3B8;">⚪ เครื่องว่าง ({next_txt})</div>
            </div>
            """)

    st.markdown(f"""
    <div style="background:#0F172A; padding:12px 20px; border-radius:16px; margin-bottom:12px; display:flex; justify-content:space-between; align-items:center; color:white;">
        <div>
            <div style="font-size:20px; font-weight:800; color:#38BDF8;">📺 PES SHOP FLOOR LIVE MONITOR (22 สถานี)</div>
            <div style="font-size:12px; color:#94A3B8;">ประจำวันที่ {cur_date_str}</div>
        </div>
        <div style="text-align:right;">
            <div id="live-tv-clock" style="font-size:24px; font-weight:bold; font-family:monospace;">--:--:-- น.</div>
            <div style="font-size:12px;"><span style="color:#34D399;">🟢 รัน {r_count}</span> | <span style="color:#FBBF24;">🟡 พัก {h_count}</span> | <span style="color:#94A3B8;">⚪ ว่าง {i_count}</span></div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown('<div class="tv-grid-container">' + "".join(machine_cards) + '</div>', unsafe_allow_html=True)

# =========================================================
# JavaScript ท้ายไฟล์: ควบคุมนาฬิกา + เวลาเดินเครื่องสด + Auto Refresh
# =========================================================
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
