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
            dt_val = dt_val.tz_localize(None)
        if dt_val.year > 2400:
            dt_val = dt_val.replace(year=dt_val.year - 543)
        return dt_val
        
    s = str(dt_val).strip()
    if s in ["", "None", "nan", "NaN", "null", "-", "NaT"]:
        return None
    
    s = s.replace('T', ' ').split('+')[0].split('Z')[0].strip()
    current_year = get_bangkok_now().year

    if "-" in s:
        parts_dash = s.split(" ")[0].split("-")
        if len(parts_dash) == 3 and len(parts_dash[0]) == 4:
            dt_parsed = pd.to_datetime(s, errors='coerce')
            if pd.notna(dt_parsed):
                if getattr(dt_parsed, 'tzinfo', None) is not None:
                    dt_parsed = dt_parsed.tz_localize(None)
                if dt_parsed.year > 2400:
                    dt_parsed = dt_parsed.replace(year=dt_parsed.year - 543)
                return dt_parsed

    if "/" in s:
        date_part = s.split(" ")[0]
        time_part = s.split(" ")[1] if len(s.split(" ")) > 1 else "08:30:00"
        if len(time_part.split(":")) == 2:
            time_part += ":00"
        parts = date_part.split("/")
        
        if len(parts) == 2:
            d, m = parts[0].zfill(2), parts[1].zfill(2)
            s_fixed = f"{current_year}-{m}-{d} {time_part}"
            dt_parsed = pd.to_datetime(s_fixed, format="%Y-%m-%d %H:%M:%S", errors='coerce')
            return dt_parsed
        elif len(parts) == 3:
            d, m = parts[0].zfill(2), parts[1].zfill(2)
            try:
                y = int(parts[2])
                if y > 2400:
                    y = y - 543
                elif y < 100:
                    y = 2000 + y
                s_fixed = f"{y:04d}-{m}-{d} {time_part}"
                dt_parsed = pd.to_datetime(s_fixed, format="%Y-%m-%d %H:%M:%S", errors='coerce')
                return dt_parsed
            except Exception:
                pass

    dt_parsed = pd.to_datetime(s, errors='coerce', dayfirst=True)
    if pd.notna(dt_parsed):
        if getattr(dt_parsed, 'tzinfo', None) is not None:
            dt_parsed = dt_parsed.tz_localize(None)
        if dt_parsed.year > 2400:
            dt_parsed = dt_parsed.replace(year=dt_parsed.year - 543)
        return dt_parsed
    return None

def to_bangkok_epoch_ms(dt_val):
    if dt_val is None or pd.isna(dt_val):
        return 0
    dt_p = parse_flexible_datetime(dt_val)
    if dt_p is None:
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
        return [
            (datetime.combine(dt_date, dtime(8, 30)), datetime.combine(dt_date, dtime(10, 0))),
            (datetime.combine(dt_date, dtime(10, 10)), datetime.combine(dt_date, dtime(12, 0))),
            (datetime.combine(dt_date, dtime(13, 0)), datetime.combine(dt_date, dtime(15, 0))),
            (datetime.combine(dt_date, dtime(15, 10)), datetime.combine(dt_date, dtime(17, 0)))
        ]
    else:
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
    remaining_hours = max(duration_hours, 0.25)
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

def highlight_running_deadlines(row, planned_finish_map):
    status = str(row.get("สถานะ", row.get("สถานะงาน", "")))
    job_id = str(row.get("ID", ""))

    if "กำลังผลิต" in status:
        finish_dt = planned_finish_map.get(job_id)
        if finish_dt is not None and pd.notna(finish_dt):
            now = get_bangkok_now().replace(tzinfo=None)
            diff_mins = (finish_dt - now).total_seconds() / 60.0

            if diff_mins < 0:
                return ['background-color: #FECACA; color: #991B1B; font-weight: bold;'] * len(row)
            elif 0 <= diff_mins <= 60:
                return ['background-color: #FEF08A; color: #854D0E; font-weight: bold;'] * len(row)

    return [''] * len(row)

# =========================================================
# 1. UI Setup & Logo
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

    .step-card { background: #FFFFFF; padding: 14px 16px; border-radius: 14px; border: 1.5px solid #E2E8F0; margin-bottom: 12px; box-shadow: 0 2px 8px rgba(0,0,0,0.02); }
    div.stButton > button:disabled { background-color: #F1F5F9 !important; color: #94A3B8 !important; border-color: #CBD5E1 !important; cursor: not-allowed !important; }

    .tv-grid-container { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 10px; margin-top: 8px; }
    .tv-card { border-radius: 12px; padding: 12px 14px; color: #FFFFFF !important; box-shadow: 0 4px 14px rgba(0,0,0,0.12); display: flex; flex-direction: column; justify-content: space-between; min-height: 148px; border: 1px solid rgba(255,255,255,0.12); }
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
# 2. System States & Constants
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
    "wo_color_filter": "ALL"
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
# 3. Supabase REST API
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

# ---------------------------------------------------------
# แท็บเมนูเปลี่ยนมุมมองหลัก
# ---------------------------------------------------------
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
# VIEW 1: โหมดช่างหน้าเครื่อง
# ---------------------------------------------------------
if st.session_state.current_view == "👷 โหมดช่างหน้าเครื่อง":
    st.markdown("### 📱 บันทึกสถานะงานหน้าเครื่อง / แผนกผลิต")
    df_all = fetch_jobs_from_supabase()
    
    c_m_sel, c_mode_sel = st.columns([2, 2])
    with c_m_sel:
        selected_m = st.selectbox("🏭 เลือกเครื่องจักร / แผนก:", MACHINE_LIST, key="op_machine_select")
    with c_mode_sel:
        run_mode = st.radio("⚙️ รูปแบบการผลิต:", ["🔹 รันทีละคิว (Piece by Piece)", "📦 รันรวมหลายงานพร้อมกัน (Batch Processing)"], horizontal=True)

    if not df_all.empty:
        m_all_jobs = df_all[
            (df_all["เลือกเครื่องจักร"] == selected_m) &
            (df_all["สถานะงาน"].isin(["🟧 รอคิวผลิต", "🟦 กำลังผลิต", "🟨 พักงาน (รอวัสดุ)"]))
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

    if m_all_jobs.empty:
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

        def sort_op_jobs(x):
            st_val = str(x.get("สถานะงาน", ""))
            if "กำลังผลิต" in st_val:
                prio = 0
            elif "พักงาน" in st_val:
                prio = 1
            else:
                prio = 2
            r_dt = parse_flexible_datetime(x.get("วัน-เวลาขึ้นงาน"))
            return (prio, r_dt if r_dt is not None else pd.Timestamp.max, safe_int(x.get("ID")))

        m_active = m_all_jobs.copy()
        m_active["_sort_key"] = m_active.apply(sort_op_jobs, axis=1)
        m_active = m_active.sort_values(by="_sort_key").drop(columns=["_sort_key"]).reset_index(drop=True)

        cur_chain_time = None
        machine_any_running = any("กำลังผลิต" in str(r.get("สถานะงาน", "")) for _, r in m_all_jobs.iterrows())
        next_available_start_found = False

        for queue_idx, step_row in m_active.iterrows():
            target_id = safe_int(step_row["ID"])
            plan_code = str(step_row.get("แผนงาน", "-"))
            drawing_code = str(step_row.get("ชื่อ Drawing.", "-"))
            qty_val = int(step_row.get("จำนวน", 1) or 1)
            mat_val = str(step_row.get("วัสดุ", "-"))
            raw_s_name = str(step_row.get("ขั้นตอน (Step)", "รอหน้าเครื่องระบุ"))
            s_name = raw_s_name if raw_s_name not in ["", "None", "nan", "รอหน้าเครื่องระบุ"] else f"OP{(queue_idx+1)*10}"
            s_status = str(step_row.get("สถานะงาน", "🟧 รอคิวผลิต"))
            s_start = step_row.get("เริ่มจริง")
            s_finish = step_row.get("เสร็จจริง")

            is_step_running = "กำลังผลิต" in s_status
            is_step_hold = "พักงาน" in s_status
            is_step_finished = "เสร็จสิ้น" in s_status
            is_step_waiting = not is_step_running and not is_step_finished and not is_step_hold
            is_urgent = "ด่วนแทรก" in str(step_row.get("ประเภทงาน", ""))

            s_m = safe_float(step_row.get("Setup (น.)"), 10.0)
            b_m = safe_float(step_row.get("Basic (น.)"), 0.0)
            p_m = safe_float(step_row.get("โปรแกรม (น.)"), 120.0)
            tot_h = (s_m + b_m + p_m) / 60.0

            if cur_chain_time is None:
                r_parsed = parse_flexible_datetime(step_row.get("วัน-เวลาขึ้นงาน"))
                if r_parsed is None or pd.isna(r_parsed) or r_parsed.year < 2020:
                    r_parsed = get_bangkok_now().replace(tzinfo=None)
                start_w_dt = get_next_valid_work_time(r_parsed)
            else:
                start_w_dt = get_next_valid_work_time(cur_chain_time)

            _, finish_w_dt = add_work_time_with_shift(start_w_dt, tot_h)
            cur_chain_time = finish_w_dt

            ready_display_str = start_w_dt.strftime("%d/%m/%Y %H:%M น.")
            finish_plan_display_str = finish_w_dt.strftime("%d/%m/%Y %H:%M น.")

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

            card_header_html = f'''<div class="{header_box_class}"><div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px;"><div style="font-size:20px; font-weight:800; color:#1E1B4B; display:flex; align-items:center; gap:8px;"><span style="background:{badge_gradient}; color:white; padding:4px 12px; border-radius:10px; font-size:14px; box-shadow:0 3px 8px rgba(0,0,0,0.15);">คิวที่ {queue_idx+1}</span><span>แผนงาน: {plan_code}</span></div><span class="badge-chip badge-station">🏭 {selected_m}</span></div><div style="display:flex; flex-wrap:wrap; gap:6px; align-items:center;">{status_badge_html}<span class="badge-chip badge-date">📅 <b>กำหนดขึ้นงาน:</b> {ready_display_str}</span><span class="badge-chip badge-finish-date">🏁 <b>กำหนดจบงานตามแผน:</b> {finish_plan_display_str}</span><span class="badge-chip badge-drawing">📄 <b>Drawing:</b> {drawing_code}</span><span class="badge-chip badge-qty">🔢 <b>จำนวน:</b> {qty_val} ชิ้น</span><span class="badge-chip badge-mat">🔩 <b>วัสดุ:</b> {mat_val}</span></div></div>'''
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
                    if can_start:
                        st.caption(f"**ขั้นตอน:** <span style='color:#D97706; font-weight:800;'>🟧 พร้อมเริ่มงาน (Ready to Start)</span>", unsafe_allow_html=True)
                    else:
                        st.caption(f"**ขั้นตอน:** <span style='color:#64748B; font-weight:600;'>🔒 รอลำดับคิวก่อนหน้าตามแผน</span>", unsafe_allow_html=True)

                if not is_step_finished:
                    step_val = st.text_input(f"ชื่อขั้นตอนงาน (Step):", value=s_name, key=f"op_step_{target_id}")

                    if is_step_hold:
                        c_btn_save, c_btn_resume = st.columns([1.5, 4])
                        with c_btn_save:
                            if st.button("💾 บันทึกชื่อ", key=f"btn_save_edit_{target_id}", use_container_width=True):
                                update_supabase_job(target_id, {"step_name": safe_str(step_val, s_name)})
                                st.toast("บันทึกชื่อขั้นตอนเรียบร้อย!", icon="💾")
                                st.rerun()
                        with c_btn_resume:
                            if st.button("▶️ ได้วัสดุใหม่แล้ว (Resume เริ่มรันต่อ)", key=f"btn_resume_{target_id}", type="primary", use_container_width=True):
                                update_supabase_job(target_id, {"step_name": safe_str(step_val, s_name), "status": "🟦 กำลังผลิต", "actual_start": get_bangkok_str()})
                                st.toast("เริ่มรันงานต่อเรียบร้อย!", icon="🚀")
                                st.rerun()
                    elif is_step_running:
                        c_btn_save, c_btn_hold, c_btn_finish = st.columns([1.5, 2.5, 2])
                        with c_btn_save:
                            if st.button("💾 บันทึกชื่อ", key=f"btn_save_edit_{target_id}", use_container_width=True):
                                update_supabase_job(target_id, {"step_name": safe_str(step_val, s_name)})
                                st.toast("บันทึกชื่อขั้นตอนเรียบร้อย!", icon="💾")
                                st.rerun()
                        with c_btn_hold:
                            if st.button("🛑 พักงาน (รอวัสดุใหม่)", key=f"btn_hold_{target_id}", use_container_width=True):
                                update_supabase_job(target_id, {"step_name": safe_str(step_val, s_name), "status": "🟨 พักงาน (รอวัสดุ)"})
                                st.toast("พักงานเรียบร้อย!", icon="🛑")
                                st.rerun()
                        with c_btn_finish:
                            if st.button("🏁 Finish (จบงานจริง)", key=f"btn_finish_step_{target_id}", type="primary", use_container_width=True):
                                update_supabase_job(target_id, {"status": "🟩 เสร็จสิ้นแล้ว", "actual_finish": get_bangkok_str()})
                                st.toast("บันทึกเวลาจบจริงเรียบร้อย!", icon="🏁")
                                st.rerun()
                    else:
                        c_btn_save, c_btn_start, c_btn_finish = st.columns([1.5, 2, 2])
                        with c_btn_save:
                            if st.button("💾 บันทึกชื่อ", key=f"btn_save_edit_{target_id}", use_container_width=True):
                                update_supabase_job(target_id, {"step_name": safe_str(step_val, s_name)})
                                st.toast("บันทึกชื่อขั้นตอนเรียบร้อย!", icon="💾")
                                st.rerun()
                        with c_btn_start:
                            if can_start:
                                if st.button("🚀 Start (เริ่มจับเวลาจริง)", key=f"btn_start_step_{target_id}", type="primary", use_container_width=True):
                                    update_supabase_job(target_id, {"step_name": safe_str(step_val, s_name), "status": "🟦 กำลังผลิต", "actual_start": get_bangkok_str()})
                                    st.toast("เริ่มผลิตแล้ว!", icon="🚀")
                                    st.rerun()
                            else:
                                st.button("🚀 Start", key=f"btn_start_disabled_{target_id}", disabled=True, use_container_width=True)
                        with c_btn_finish:
                            st.button("🏁 Finish", key=f"btn_finish_disabled_{target_id}", disabled=True, use_container_width=True)

                st.markdown("</div>", unsafe_allow_html=True)

            with st.expander(f"➕ เพิ่ม Step ถัดไปสำหรับ {plan_code} ({drawing_code})", expanded=False):
                new_step_input = st.text_input("ชื่อ Step ถัดไป:", value=f"OP{(queue_idx+2)*10}", placeholder="เช่น OP20, กลึง, เจียร, เชื่อม", key=f"new_step_name_input_{target_id}")

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
                        "step_name": new_step_input.strip() if new_step_input.strip() != "" else f"OP{(queue_idx+2)*10}",
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
                const nowTs = new Date().getTime();
                const timerEls = window.parent.document.querySelectorAll('.pes-live-timer');
                timerEls.forEach(el => {
                    const startAttr = el.getAttribute('data-start-epoch');
                    const startTs = parseInt(startAttr, 10);
                    if (startTs && startTs > 0) {
                        const diffMs = Math.max(0, nowTs - startTs);
                        const totalSecs = Math.floor(diffMs / 1000);
                        const hrs = String(Math.floor(totalSecs / 3600)).padStart(2, '0');
                        const mins = String(Math.floor((totalSecs % 3600) / 60)).padStart(2, '0');
                        const secs = String(totalSecs % 60).padStart(2, '0');
                        el.innerText = hrs + ":" + mins + ":" + secs;
                    }
                });
            } catch (e) {}
        }
        setInterval(runLiveStopwatches, 1000);
        runLiveStopwatches();
    </script>
    """, height=0)

# ---------------------------------------------------------
# VIEW 2: แดชบอร์ดภาพรวมโรงงาน
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

            # =========================================================================
            # 1. รายการสั่งผลิตในระบบ (ตารางสั่งการผลิต - ล็อก Baseline วัน/เดือน/ปี)
            # =========================================================================
            column_order = [
                "ID", "แผนงาน", "ชื่อ Drawing.", "จำนวน", "วัสดุ", "ประเภทงาน", "ขั้นตอน (Step)",
                "เลือกเครื่องจักร", "วัน-เวลาขึ้นงาน", "Setup (น.)",
                "Basic (น.)", "โปรแกรม (น.)", "รวม (ชม.)", "สถานะงาน",
            ]
            calc_df = calc_df[[c for c in column_order if c in calc_df.columns]]
            active_jobs_editor_df = calc_df[calc_df["สถานะงาน"].isin(["🟧 รอคิวผลิต", "🟦 กำลังผลิต", "🟨 พักงาน (รอวัสดุ)"])].copy()

            def to_dmy_str(val):
                dt_p = parse_flexible_datetime(val)
                return dt_p.strftime("%d/%m/%Y %H:%M") if dt_p is not None and pd.notna(dt_p) else ""

            active_jobs_editor_df["วัน-เวลาขึ้นงาน"] = active_jobs_editor_df["วัน-เวลาขึ้นงาน"].apply(to_dmy_str)

            plan_finish_dates = []
            for _, r in active_jobs_editor_df.iterrows():
                dt_s = parse_flexible_datetime(r["วัน-เวลาขึ้นงาน"])
                if dt_s is None or pd.isna(dt_s) or dt_s.year < 2020:
                    dt_s = get_bangkok_now().replace(tzinfo=None)
                s_m = safe_float(r.get("Setup (น.)"), 10.0)
                b_m = safe_float(r.get("Basic (น.)"), 0.0)
                p_m = safe_float(r.get("โปรแกรม (น.)"), 120.0)
                tot_h = (s_m + b_m + p_m) / 60.0
                _, dt_f = add_work_time_with_shift(get_next_valid_work_time(dt_s), tot_h)
                plan_finish_dates.append(dt_f.strftime("%d/%m/%Y %H:%M"))

            active_jobs_editor_df["วัน-เวลาจบงาน"] = plan_finish_dates
            active_jobs_editor_df["รวม (ชม.)"] = ((active_jobs_editor_df["Setup (น.)"] + active_jobs_editor_df["Basic (น.)"] + active_jobs_editor_df["โปรแกรม (น.)"]) / 60.0).round(2)
            active_jobs_editor_df["ลบ"] = st.session_state.active_select_all

            with st.expander("📝 รายการสั่งผลิตในระบบ (ตารางสั่งการผลิต - แก้ไขเวลาตั้งต้น Baseline)", expanded=True):
                if is_admin:
                    tool_col1, tool_col2, tool_search = st.columns([2.5, 4.5, 3])
                    with tool_col1:
                        b_c1, b_c2 = st.columns(2)
                        with b_c1:
                            if st.button("✅ เลือกหมด", key="btn_sel_all_active", use_container_width=True):
                                st.session_state.active_select_all = True
                                st.rerun()
                        with b_c2:
                            if st.button("❌ ยกเลิก", key="btn_unsel_all_active", use_container_width=True):
                                st.session_state.active_select_all = False
                                st.rerun()
                    with tool_col2:
                        st.caption("🔒 **ล็อกเวลาตั้งต้น (Plan Baseline):** ดับเบิลคลิกแก้ไขช่อง 'วัน-เวลาขึ้นงาน' ในรูปแบบ 'วัน/เดือน/ปี ชม:นาที' (เช่น 04/09/2026 15:30) พอกดบันทึกจะจำค่านี้ไว้ถาวร")
                    with tool_search:
                        search_query_editor = st.text_input(
                            "🔍 ค้นหาในตารางสั่งผลิต (แผนงาน, Drawing, วัสดุ, เครื่องจักร, สถานะ):",
                            placeholder="พิมพ์เพื่อกรองข้อมูล เช่น SS400, No.1, รอคิวผลิต...",
                            key="search_active_editor_input"
                        )
                else:
                    search_query_editor = st.text_input(
                        "🔍 ค้นหาในตารางสั่งผลิต (แผนงาน, Drawing, วัสดุ, เครื่องจักร, สถานะ):",
                        placeholder="พิมพ์เพื่อกรองข้อมูล เช่น SS400, No.1, รอคิวผลิต...",
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

                display_editor_df["แผนงาน"] = display_editor_df["แผนงาน"].astype(str).fillna("")
                display_editor_df["ชื่อ Drawing."] = display_editor_df["ชื่อ Drawing."].astype(str).fillna("")
                display_editor_df["จำนวน"] = pd.to_numeric(display_editor_df["จำนวน"], errors='coerce').fillna(1).astype(int)
                display_editor_df["วัสดุ"] = display_editor_df["วัสดุ"].astype(str).fillna("SS400")
                display_editor_df["ประเภทงาน"] = display_editor_df["ประเภทงาน"].astype(str).replace({"nan": "🟢 งานปกติ", "": "🟢 งานปกติ", "None": "🟢 งานปกติ"})
                display_editor_df["ขั้นตอน (Step)"] = display_editor_df["ขั้นตอน (Step)"].astype(str).fillna("รอหน้าเครื่องระบุ")
                display_editor_df["เลือกเครื่องจักร"] = display_editor_df["เลือกเครื่องจักร"].astype(str).fillna("No.1 Awea")
                display_editor_df["วัน-เวลาขึ้นงาน"] = display_editor_df["วัน-เวลาขึ้นงาน"].astype(str).fillna("")
                display_editor_df["วัน-เวลาจบงาน"] = display_editor_df["วัน-เวลาจบงาน"].astype(str).fillna("")
                display_editor_df["Setup (น.)"] = pd.to_numeric(display_editor_df["Setup (น.)"], errors='coerce').fillna(10).astype(int)
                display_editor_df["Basic (น.)"] = pd.to_numeric(display_editor_df["Basic (น.)"], errors='coerce').fillna(0).astype(int)
                display_editor_df["โปรแกรม (น.)"] = pd.to_numeric(display_editor_df["โปรแกรม (น.)"], errors='coerce').fillna(120).astype(int)
                display_editor_df["รวม (ชม.)"] = pd.to_numeric(display_editor_df["รวม (ชม.)"], errors='coerce').fillna(0.0).astype(float)
                display_editor_df["สถานะงาน"] = display_editor_df["สถานะงาน"].astype(str).replace({"nan": "🟧 รอคิวผลิต", "": "🟧 รอคิวผลิต", "None": "🟧 รอคิวผลิต"})
                display_editor_df["ลบ"] = display_editor_df["ลบ"].fillna(False).astype(bool)

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
                                "วัน-เวลาขึ้นงาน (วัน/เดือน/ปี)", 
                                width=175,
                                help="รูปแบบ: วัน/เดือน/ปี ชั่วโมง:นาที เช่น 04/09/2026 15:30"
                            ),
                            "วัน-เวลาจบงาน": st.column_config.TextColumn(
                                "วัน-เวลาจบงานตามแผน",
                                width=175,
                                disabled=True,
                                help="เวลาจบคำนวณตามแผนและกะโรงงาน"
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
                            "วัน-เวลาขึ้นงาน": st.column_config.TextColumn("วัน-เวลาขึ้นงาน (วัน/เดือน/ปี)", width=175),
                            "วัน-เวลาจบงาน": st.column_config.TextColumn("วัน-เวลาจบงานตามแผน", width=175),
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
                            for idx_row, row in edited_jobs.iterrows():
                                p_code = safe_str(row.get("แผนงาน"), "")
                                if not p_code: 
                                    continue
                                
                                raw_ready = str(row.get("วัน-เวลาขึ้นงาน", "")).strip()
                                dt_parsed = parse_flexible_datetime(raw_ready)

                                if dt_parsed is not None and pd.notna(dt_parsed):
                                    ready_str = dt_parsed.strftime("%Y-%m-%d %H:%M:%S")
                                else:
                                    orig_id = row.get("ID")
                                    db_match = df_db[df_db["ID"] == orig_id] if pd.notna(orig_id) else pd.DataFrame()
                                    if not db_match.empty and pd.notna(db_match.iloc[0]["วัน-เวลาขึ้นงาน"]):
                                        ready_str = pd.to_datetime(db_match.iloc[0]["วัน-เวลาขึ้นงาน"]).strftime("%Y-%m-%d %H:%M:%S")
                                    else:
                                        ready_str = get_bangkok_str()

                                payload = {
                                    "plan_code": p_code,
                                    "drawing_name": safe_str(row.get("ชื่อ Drawing."), ""),
                                    "qty": safe_int(row.get("จำนวน"), 1),
                                    "material": safe_str(row.get("วัสดุ"), "SS400"),
                                    "job_type": safe_str(row.get("ประเภทงาน"), "🟢 งานปกติ"),
                                    "step_name": safe_str(row.get("ขั้นตอน (Step)"), "รอหน้าเครื่องระบุ"),
                                    "machine_name": safe_str(row.get("เลือกเครื่องจักร"), "No.1 Awea"),
                                    "ready_at": ready_str,
                                    "setup_mins": safe_float(row.get("Setup (น.)"), 10.0),
                                    "basic_hrs": safe_float(row.get("Basic (น.)"), 0.0),
                                    "prog_hrs": safe_float(row.get("โปรแกรม (น.)"), 120.0),
                                    "status": safe_str(row.get("สถานะงาน"), "🟧 รอคิวผลิต")
                                }

                                row_id = row.get("ID")
                                if pd.isna(row_id) or str(row_id).strip() in ["", "None", "nan"]:
                                    insert_supabase_job(payload)
                                else:
                                    update_supabase_job(int(float(row_id)), payload)

                            st.cache_data.clear()
                            st.session_state.scroll_to_bottom = True
                            st.toast("บันทึกข้อมูลและเวลาขึ้นงานเรียบร้อยแล้ว!", icon="💾")
                            st.rerun()

                    with c_del_top:
                        btn_del_label = f"🗑️ ลบรายการที่เลือก ({delete_count} รายการ)" if delete_count > 0 else "🗑️ ลบรายการที่เลือก (0 รายการ)"
                        if st.button(btn_del_label, type="secondary", disabled=(delete_count == 0), use_container_width=True):
                            for _, row in active_to_delete.iterrows():
                                row_id = row.get("ID")
                                if pd.notna(row_id) and str(row_id).strip() not in ["", "None", "nan"] and float(row_id) > 0:
                                    delete_supabase_job(int(float(row_id)))
                                        
                            st.session_state.active_select_all = False
                            st.cache_data.clear()
                            st.session_state.scroll_to_bottom = True
                            st.rerun()

            finished_jobs_df = df_db[df_db["สถานะงาน"].isin(["🟩 เสร็จสิ้นแล้ว", "✅ เสร็จสิ้นแล้ว"])].copy()
            active_jobs_count = len(edited_jobs[edited_jobs["สถานะงาน"].isin(["🟧 รอคิวผลิต", "🟦 กำลังผลิต", "🟨 พักงาน (รอวัสดุ)"])])
            total_plan_hrs = active_jobs_editor_df["รวม (ชม.)"].sum()

            kpi_html = f'''<div class="kpi-container"><div class="kpi-card kpi-green"><div class="kpi-title">✅ งานเสร็จสิ้น</div><div class="kpi-value">{len(finished_jobs_df)} <span style="font-size:15px; font-weight:600;">รายการ</span></div></div><div class="kpi-card kpi-blue"><div class="kpi-title">⚙️ งานในแผน</div><div class="kpi-value">{active_jobs_count} <span style="font-size:15px; font-weight:600;">รายการ</span></div></div><div class="kpi-card kpi-orange"><div class="kpi-title">⏱️ เวลาทำงานรวม</div><div class="kpi-value">{total_plan_hrs:.1f} <span style="font-size:15px; font-weight:600;">ชม.</span></div></div></div>'''
            st.markdown(kpi_html, unsafe_allow_html=True)

            st.divider()

            # =====================================================
            # 2. ใบจ่ายคิวงานหน้าเครื่อง (Work Order Sheet - ระบบลูกโซ่ Auto-Chain)
            # =====================================================
            st.subheader("📋 ใบจ่ายคิวงานหน้าเครื่อง (Work Order Sheet)")

            df_wo_direct = active_jobs_editor_df.copy()

            def get_wo_queue_order(r):
                st_val = str(r.get("สถานะงาน", r.get("สถานะ", "")))
                prio = 0 if "กำลังผลิต" in st_val else (1 if "พักงาน" in st_val else 2)
                dt_p = parse_flexible_datetime(r.get("วัน-เวลาขึ้นงาน"))
                return (prio, dt_p if dt_p is not None else pd.Timestamp.max, safe_int(r.get("ID")))

            df_wo_direct["_wo_order"] = df_wo_direct.apply(get_wo_queue_order, axis=1)
            df_wo_direct = df_wo_direct.sort_values(by=["เลือกเครื่องจักร", "_wo_order"]).drop(columns=["_wo_order"]).reset_index(drop=True)

            m_chain_tracker = {}
            wo_chained_start = []
            wo_chained_finish = []

            for _, r in df_wo_direct.iterrows():
                m_name = str(r["เลือกเครื่องจักร"])
                s_m = safe_float(r.get("Setup (น.)"), 10.0)
                b_m = safe_float(r.get("Basic (น.)"), 0.0)
                p_m = safe_float(r.get("โปรแกรม (น.)"), 120.0)
                tot_h = (s_m + b_m + p_m) / 60.0

                r_parsed = parse_flexible_datetime(r["วัน-เวลาขึ้นงาน"])
                if r_parsed is None or pd.isna(r_parsed) or r_parsed.year < 2020:
                    r_parsed = get_bangkok_now().replace(tzinfo=None)

                if m_name not in m_chain_tracker:
                    w_st = get_next_valid_work_time(r_parsed)
                else:
                    w_st = get_next_valid_work_time(m_chain_tracker[m_name])

                _, w_fn = add_work_time_with_shift(w_st, tot_h)
                m_chain_tracker[m_name] = w_fn

                wo_chained_start.append(w_st)
                wo_chained_finish.append(w_fn)

            df_wo_direct["_dt_start"] = wo_chained_start
            df_wo_direct["_dt_finish"] = wo_chained_finish

            df_wo_direct["ลำดับคิว"] = df_wo_direct.groupby("เลือกเครื่องจักร").cumcount() + 1
            df_wo_direct["ลำดับคิว"] = df_wo_direct["ลำดับคิว"].apply(lambda q: f"คิวที่ {q}")

            df_wo_direct["เครื่องจักร / แผนก"] = df_wo_direct["เลือกเครื่องจักร"]
            df_wo_direct["สถานะ"] = df_wo_direct["สถานะงาน"]
            
            df_wo_direct["กำหนดพร้อมขึ้นงาน"] = df_wo_direct["วัน-เวลาขึ้นงาน"]
            df_wo_direct["เริ่มขึ้นงานตามแผน"] = [d.strftime("%d/%m/%Y %H:%M") for d in wo_chained_start]
            df_wo_direct["จบงานตามแผน"] = [d.strftime("%d/%m/%Y %H:%M") for d in wo_chained_finish]

            wo_finish_map = dict(zip(df_wo_direct["ID"].astype(str), df_wo_direct["_dt_finish"]))

            now_check = get_bangkok_now().replace(tzinfo=None)
            warn_count = 0
            late_count = 0
            for _, r in df_wo_direct.iterrows():
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
                    if st.button("🌐 ทั้งหมด", type=btn_all_type, use_container_width=True, key="btn_wo_filter_all"):
                        st.session_state.wo_color_filter = "ALL"
                        st.rerun()
                with f_b2:
                    btn_warn_type = "primary" if cur_wo_filter == "WARN" else "secondary"
                    if st.button(f"🟡 ใกล้เสร็จ ({warn_count})", type=btn_warn_type, use_container_width=True, help="เหลือน้อยกว่า 1 ชม.", key="btn_wo_filter_warn"):
                        st.session_state.wo_color_filter = "WARN"
                        st.rerun()
                with f_b3:
                    btn_late_type = "primary" if cur_wo_filter == "LATE" else "secondary"
                    if st.button(f"🔴 เกินแผน ({late_count})", type=btn_late_type, use_container_width=True, help="เลยกำหนดเวลาแผน", key="btn_wo_filter_late"):
                        st.session_state.wo_color_filter = "LATE"
                        st.rerun()

            df_display = df_wo_direct.copy()

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
                    df_display["เครื่องจักร / แผนก"].astype(str).str.lower().str.contains(q_wo) |
                    df_display["สถานะ"].astype(str).str.lower().str.contains(q_wo)
                ]

            display_cols = [c for c in df_display.columns if c not in ["_dt_start", "_dt_finish", "_sort_key", "วัน-เวลาขึ้นงาน", "วัน-เวลาจบงาน"]]

            styled_df_display = df_display[display_cols].style.apply(
                highlight_running_deadlines,
                planned_finish_map=wo_finish_map,
                axis=1
            )

            st.dataframe(
                styled_df_display,
                column_order=[
                    "เครื่องจักร / แผนก", "ลำดับคิว", "สถานะ", "ประเภทงาน", "แผนงาน", "ชื่อ Drawing.", 
                    "จำนวน", "วัสดุ", "ขั้นตอน (Step)", "กำหนดพร้อมขึ้นงาน", 
                    "เริ่มขึ้นงานตามแผน", "จบงานตามแผน", "Setup (น.)", "Basic (น.)", "โปรแกรม (น.)", "รวม (ชม.)"
                ],
                column_config={
                    "ID": None,
                    "เครื่องจักร / แผนก": st.column_config.TextColumn("เครื่องจักร / แผนก", width=140),
                    "ลำดับคิว": st.column_config.TextColumn("ลำดับคิว", width=95),
                    "สถานะ": st.column_config.TextColumn("สถานะ", width=105),
                    "ประเภทงาน": st.column_config.TextColumn("ประเภทงาน", width=100),
                    "แผนงาน": st.column_config.TextColumn("แผนงาน", width=80),
                    "ชื่อ Drawing.": st.column_config.TextColumn("ชื่อ Drawing.", width=170),
                    "จำนวน": st.column_config.NumberColumn("จำนวน", width=65, format="%d"),
                    "วัสดุ": st.column_config.TextColumn("วัสดุ", width=70),
                    "ขั้นตอน (Step)": st.column_config.TextColumn("ขั้นตอน (Step)", width=120),
                    "กำหนดพร้อมขึ้นงาน": st.column_config.TextColumn("กำหนดพร้อมขึ้นงาน (Baseline)", width=165),
                    "เริ่มขึ้นงานตามแผน": st.column_config.TextColumn("เริ่มขึ้นงานตามแผน (ลูกโซ่)", width=155),
                    "จบงานตามแผน": st.column_config.TextColumn("จบงานตามแผน (ลูกโซ่)", width=155),
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
            # 3. ผังเวลาขึ้นงาน (Gantt Chart Timeline)
            # =====================================================
            today_date = get_bangkok_now().date()
            today_dt = get_bangkok_now().replace(tzinfo=None)

            gantt_records = []
            valid_start_dates = []
            valid_end_dates = []

            for _, r_g in df_wo_direct.iterrows():
                st_dt = r_g.get("_dt_start")
                fn_dt = r_g.get("_dt_finish")

                if st_dt is None or pd.isna(st_dt):
                    st_dt = today_dt
                if fn_dt is None or pd.isna(fn_dt) or fn_dt <= st_dt:
                    tot_mins = safe_float(r_g.get("โปรแกรม (น.)"), 120.0) + safe_float(r_g.get("Setup (น.)"), 10.0)
                    fn_dt = st_dt + timedelta(minutes=max(tot_mins, 30.0))

                p_name = str(r_g.get("แผนงาน", "-"))
                dw_name = str(r_g.get("ชื่อ Drawing.", "-"))
                step_name = str(r_g.get("ขั้นตอน (Step)", "-"))
                m_name = str(r_g.get("เลือกเครื่องจักร", "-"))
                mat_name = str(r_g.get("วัสดุ", "-"))
                qty_val = str(r_g.get("จำนวน", 1))
                tot_hrs = safe_float(r_g.get("รวม (ชม.)"), 0.0)

                valid_start_dates.append(st_dt.date())
                valid_end_dates.append(fn_dt.date())

                gantt_records.append({
                    "ข้อความบนแท่งกราฟ": f"{p_name}",
                    "แผนงาน": p_name,
                    "ชื่อ Drawing.": dw_name,
                    "จำนวน": qty_val,
                    "ขั้นตอน (Step)": step_name,
                    "เครื่องจักร": m_name,
                    "วัสดุ": mat_name,
                    "เวลาเริ่ม": st_dt.strftime("%Y-%m-%d %H:%M:%S"),
                    "เวลาเสร็จ": fn_dt.strftime("%Y-%m-%d %H:%M:%S"),
                    "ระยะเวลา": f"{tot_hrs:.2f} ชม.",
                    "กิจกรรม": "⚙️ งานปกติ" if "ปกติ" in str(r_g.get("ประเภทงาน", "")) else "🔴 งานด่วน"
                })

            df_gantt = pd.DataFrame(gantt_records)

            if not df_gantt.empty:
                st.subheader("📊 ผังเวลาขึ้นงานที่กำลังผลิตและรอคิว (Gantt Chart Timeline)")

                gantt_min_date = min(valid_start_dates) if valid_start_dates else today_date
                gantt_max_date = max(valid_end_dates) if valid_end_dates else (today_date + timedelta(days=14))

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
                        if st.button("🔍 วันนี้", key="btn_gantt_today", use_container_width=True):
                            st.session_state.gantt_date_range = (today_date, today_date)
                            st.rerun()
                    with btn_q2:
                        if st.button("📅 3 วัน", key="btn_gantt_3d", use_container_width=True):
                            st.session_state.gantt_date_range = (today_date, today_date + timedelta(days=2))
                            st.rerun()
                    with btn_q3:
                        if st.button("📆 7 วัน", key="btn_gantt_7d", use_container_width=True):
                            st.session_state.gantt_date_range = (today_date, today_date + timedelta(days=6))
                            st.rerun()
                    with btn_q4:
                        if st.button("🌐 ทั้งหมด", key="btn_gantt_all", use_container_width=True):
                            st.session_state.gantt_date_range = (gantt_min_date, gantt_max_date)
                            st.rerun()

                min_cal = min(gantt_min_date, today_date) - timedelta(days=15)
                max_cal = max(gantt_max_date, today_date) + timedelta(days=60)

                if st.session_state.gantt_date_range is None or not isinstance(st.session_state.gantt_date_range, (list, tuple)):
                    st.session_state.gantt_date_range = (gantt_min_date, gantt_max_date)

                selected_date_range = st.date_input(
                    "เลือกช่วงวันที่กำหนดเอง:",
                    value=st.session_state.gantt_date_range,
                    min_value=min_cal,
                    max_value=max_cal,
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

                if not plot_gantt_df.empty:
                    plot_gantt_df["เริ่มแสดง"] = pd.to_datetime(plot_gantt_df["เวลาเริ่ม"]).dt.strftime("%d/%m/%Y %H:%M น.")
                    plot_gantt_df["เสร็จแสดง"] = pd.to_datetime(plot_gantt_df["เวลาเสร็จ"]).dt.strftime("%d/%m/%Y %H:%M น.")

                    color_target = "แผนงาน" if color_by_option == "แผนงาน (Plan Code)" else "กิจกรรม"
                    distinct_plans = list(plot_gantt_df["แผนงาน"].unique())
                    palette = px.colors.qualitative.Bold
                    plan_color_map = {p_name: palette[i % len(palette)] for i, p_name in enumerate(distinct_plans)}

                    fig = px.timeline(
                        plot_gantt_df,
                        x_start="เวลาเริ่ม",
                        x_end="เวลาเสร็จ",
                        y="เครื่องจักร",
                        color=color_target,
                        text="ข้อความบนแท่งกราฟ",
                        custom_data=["แผนงาน", "ชื่อ Drawing.", "จำนวน", "ขั้นตอน (Step)", "วัสดุ", "เริ่มแสดง", "เสร็จแสดง", "ระยะเวลา"],
                        category_orders={"เครื่องจักร": display_machines},
                        color_discrete_map=plan_color_map if color_target == "แผนงาน" else {
                            "⚙️ งานปกติ": "#0284C7",
                            "🔴 งานด่วน": "#EF4444"
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
                        ⏱️ <b>เริ่ม:</b> %{customdata[5]}<br>
                        🏁 <b>เสร็จ:</b> %{customdata[6]} (รวม %{customdata[7]})
                        <extra></extra>
                        """
                    )
                    
                    fig.update_yaxes(autorange="reversed", type="category", categoryorder="array", categoryarray=display_machines, showgrid=True, gridcolor="#E2E8F0")

                    if isinstance(selected_date_range, (list, tuple)) and len(selected_date_range) == 2:
                        start_view = datetime.combine(selected_date_range[0], dtime(0, 0))
                        end_view = datetime.combine(selected_date_range[1], dtime(23, 59))
                    else:
                        start_view = datetime.combine(gantt_min_date, dtime(0, 0))
                        end_view = datetime.combine(gantt_max_date, dtime(23, 59))

                    fig.update_xaxes(range=[start_view, end_view], showgrid=True, gridcolor="#E2E8F0")

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
                else:
                    st.warning("⚠️ ไม่มีคิวงานในกลุ่มสถานีที่เลือกนี้")

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
            else:
                st.info("ℹ️ ยังไม่มีข้อมูลคิวงานสำหรับแสดงผังเวลา Gantt Chart")

            # =====================================================
            # 4. อัตราการใช้งานเครื่องจักร (% Machine Utilization)
            # =====================================================
            st.subheader("📈 อัตราการใช้งานเครื่องจักรและแผนกผลิต (% Utilization)")
            
            m_busy_map = {m: 0.0 for m in MACHINE_LIST}
            for _, r_u in active_jobs_editor_df.iterrows():
                m_name = str(r_u.get("เลือกเครื่องจักร", ""))
                tot_h = safe_float(r_u.get("รวม (ชม.)"), 0.0)
                if m_name in m_busy_map:
                    m_busy_map[m_name] += tot_h

            if valid_start_dates and valid_end_dates:
                total_factory_work_hours = 0.0
                i_d = min(valid_start_dates)
                m_d = max(valid_end_dates)
                while i_d <= m_d:
                    for ws, we in get_day_working_windows(i_d):
                        total_factory_work_hours += (we - ws).total_seconds() / 3600.0
                    i_d += timedelta(days=1)
                total_horizon_work_hrs = max(total_factory_work_hours, 8.83)
            else:
                total_horizon_work_hrs = 8.83

            util_list = []
            for m in MACHINE_LIST:
                busy = m_busy_map[m]
                util_pct = min((busy / total_horizon_work_hrs) * 100.0, 100.0) if total_horizon_work_hrs > 0 else 0.0
                util_list.append({
                    "เครื่องจักร": m,
                    "ชั่วโมงทำงาน (ชม.)": round(busy, 2),
                    "อัตราการใช้งาน (%)": round(util_pct, 1),
                    "ข้อความแสดง": f"{util_pct:.1f}% ({busy:.2f} ชม.)"
                })
            df_util = pd.DataFrame(util_list)

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
            # 5. ตารางสรุปประวัติงานที่เสร็จสิ้น (Finished Production History)
            # =====================================================
            st.subheader("✅ ตารางสรุปประวัติงานที่ผลิตเสร็จสิ้น (Finished History - เริ่มจริง / เสร็จจริง)")

            if not finished_jobs_df.empty:
                fin_display_df = finished_jobs_df.copy()
                fin_display_df["_sort_fin"] = fin_display_df["เสร็จจริง"].apply(parse_flexible_datetime)
                fin_display_df = fin_display_df.sort_values(by="_sort_fin", ascending=False).drop(columns=["_sort_fin"]).reset_index(drop=True)

                act_hrs_list = []
                for _, r in fin_display_df.iterrows():
                    st_p = parse_flexible_datetime(r.get("เริ่มจริง"))
                    fn_p = parse_flexible_datetime(r.get("เสร็จจริง"))
                    if st_p and fn_p:
                        act_hrs_list.append(round((fn_p - st_p).total_seconds() / 3600.0, 2))
                    else:
                        act_hrs_list.append(round((safe_float(r.get("Setup (น.)")) + safe_float(r.get("Basic (น.)")) + safe_float(r.get("โปรแกรม (น.)"))) / 60.0, 2))

                fin_display_df["เวลาจริง (ชม.)"] = act_hrs_list
                fin_display_df["ลบประวัติ"] = st.session_state.finish_select_all

                fin_tool1, fin_tool2 = st.columns([3, 4])
                with fin_tool1:
                    if is_admin:
                        fb_c1, fb_c2 = st.columns(2)
                        with fb_c1:
                            if st.button("✅ เลือกหมด (เสร็จ)", key="btn_sel_all_fin", use_container_width=True):
                                st.session_state.finish_select_all = True
                                st.rerun()
                        with fb_c2:
                            if st.button("❌ ยกเลิก (เสร็จ)", key="btn_unsel_all_fin", use_container_width=True):
                                st.session_state.finish_select_all = False
                                st.rerun()
                with fin_tool2:
                    search_fin = st.text_input("🔍 ค้นหาในประวัติงานเสร็จสิ้น (แผนงาน, Drawing, เครื่องจักร):", key="search_finished_history_input")

                if search_fin.strip() != "":
                    q_f = search_fin.strip().lower()
                    fin_display_df = fin_display_df[
                        fin_display_df["แผนงาน"].astype(str).str.lower().str.contains(q_f) |
                        fin_display_df["ชื่อ Drawing."].astype(str).str.lower().str.contains(q_f) |
                        fin_display_df["เลือกเครื่องจักร"].astype(str).str.lower().str.contains(q_f)
                    ]

                if is_admin:
                    edited_fin = st.data_editor(
                        fin_display_df,
                        key="editor_finished_jobs_history",
                        column_order=[
                            "แผนงาน", "ชื่อ Drawing.", "จำนวน", "วัสดุ", "ขั้นตอน (Step)",
                            "เลือกเครื่องจักร", "วัน-เวลาขึ้นงาน", "เริ่มจริง", "เสร็จจริง",
                            "Setup (น.)", "Basic (น.)", "โปรแกรม (น.)", "รวม (ชม.)", "เวลาจริง (ชม.)", "สถานะงาน", "ลบประวัติ"
                        ],
                        column_config={
                            "ID": None,
                            "แผนงาน": st.column_config.TextColumn("แผนงาน", width=85, disabled=True),
                            "ชื่อ Drawing.": st.column_config.TextColumn("ชื่อ Drawing.", width=180, disabled=True),
                            "จำนวน": st.column_config.NumberColumn("จำนวน", width=65, format="%d", disabled=True),
                            "วัสดุ": st.column_config.TextColumn("วัสดุ", width=75, disabled=True),
                            "ขั้นตอน (Step)": st.column_config.TextColumn("ขั้นตอน (Step)", width=120, disabled=True),
                            "เลือกเครื่องจักร": st.column_config.TextColumn("เครื่องจักร", width=140, disabled=True),
                            "วัน-เวลาขึ้นงาน": st.column_config.DatetimeColumn("กำหนดขึ้นงาน (แผน)", width=145, format="DD/MM/YYYY HH:mm", disabled=True),
                            "เริ่มจริง": st.column_config.DatetimeColumn("เริ่มขึ้นงานจริง", width=145, format="DD/MM/YYYY HH:mm"),
                            "เสร็จจริง": st.column_config.DatetimeColumn("เสร็จสิ้นจริง", width=145, format="DD/MM/YYYY HH:mm"),
                            "Setup (น.)": st.column_config.NumberColumn("Setup (น.)", width=80, format="%d", disabled=True),
                            "Basic (น.)": st.column_config.NumberColumn("Basic (น.)", width=80, format="%d", disabled=True),
                            "โปรแกรม (น.)": st.column_config.NumberColumn("โปรแกรม (น.)", width=95, format="%d", disabled=True),
                            "รวม (ชม.)": st.column_config.NumberColumn("แผน (ชม.)", width=85, format="%.2f", disabled=True),
                            "เวลาจริง (ชม.)": st.column_config.NumberColumn("จริง (ชม.)", width=85, format="%.2f", disabled=True),
                            "สถานะงาน": st.column_config.TextColumn("สถานะ", width=120, disabled=True),
                            "ลบประวัติ": st.column_config.CheckboxColumn("🗑️", width=55, default=False),
                        },
                        hide_index=True,
                        use_container_width=True
                    )

                    fin_to_del = edited_fin[edited_fin["ลบประวัติ"] == True]
                    del_fin_count = len(fin_to_del)
                    if st.button(f"🗑️ ลบรายการประวัติงานเสร็จสิ้น ({del_fin_count} รายการ)", key="btn_del_finished_records", type="secondary", disabled=(del_fin_count == 0)):
                        for _, r in fin_to_del.iterrows():
                            if pd.notna(r.get("ID")):
                                delete_supabase_job(int(float(r["ID"])))
                        st.session_state.finish_select_all = False
                        st.cache_data.clear()
                        st.toast("ลบประวัติงานเรียบร้อยแล้ว!", icon="🗑️")
                        st.rerun()
                else:
                    st.dataframe(
                        fin_display_df[[c for c in fin_display_df.columns if c not in ["ID", "ลบประวัติ"]]],
                        column_config={
                            "แผนงาน": st.column_config.TextColumn("แผนงาน", width=85),
                            "ชื่อ Drawing.": st.column_config.TextColumn("ชื่อ Drawing.", width=180),
                            "จำนวน": st.column_config.NumberColumn("จำนวน", width=65, format="%d"),
                            "วัสดุ": st.column_config.TextColumn("วัสดุ", width=75),
                            "ขั้นตอน (Step)": st.column_config.TextColumn("ขั้นตอน (Step)", width=120),
                            "เลือกเครื่องจักร": st.column_config.TextColumn("เครื่องจักร", width=140),
                            "วัน-เวลาขึ้นงาน": st.column_config.DatetimeColumn("กำหนดขึ้นงาน (แผน)", width=145, format="DD/MM/YYYY HH:mm"),
                            "เริ่มจริง": st.column_config.DatetimeColumn("เริ่มขึ้นงานจริง", width=145, format="DD/MM/YYYY HH:mm"),
                            "เสร็จจริง": st.column_config.DatetimeColumn("เสร็จสิ้นจริง", width=145, format="DD/MM/YYYY HH:mm"),
                            "รวม (ชม.)": st.column_config.NumberColumn("แผน (ชม.)", width=85, format="%.2f"),
                            "เวลาจริง (ชม.)": st.column_config.NumberColumn("จริง (ชม.)", width=85, format="%.2f"),
                            "สถานะงาน": st.column_config.TextColumn("สถานะ", width=120),
                        },
                        hide_index=True,
                        use_container_width=True
                    )
            else:
                st.info("ℹ️ ยังไม่มีรายการที่ขึ้นสถานะ '✅ เสร็จสิ้นแล้ว'")

            st.divider()

            # =====================================================
            # 6. ตารางคำนวณมูลค่าและต้นทุนค่าเครื่องจักร (Machining Cost Calculation)
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
# VIEW 3: วิเคราะห์ประสิทธิภาพราย Drawing
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
# VIEW 5: จอทีวีกลางโรงงาน (Shop Floor TV Live Dashboard - แสดงทั้งแผนเริ่มและแผนเสร็จ)
# ---------------------------------------------------------
elif st.session_state.current_view == "📺 จอทีวีกลางโรงงาน (TV Live)":
    st.cache_data.clear()
    df_live = fetch_jobs_from_supabase()

    now_bangkok = get_bangkok_now()
    cur_date_str = now_bangkok.strftime("%d/%m/%Y")
    now_check = now_bangkok.replace(tzinfo=None)

    machine_status_cards = []
    running_machines_count = 0
    hold_machines_count = 0
    idle_machines_count = 0

    for idx_m, m in enumerate(MACHINE_LIST):
        m_jobs = df_live[df_live["เลือกเครื่องจักร"] == m] if not df_live.empty else pd.DataFrame()
        
        running_job = m_jobs[m_jobs["สถานะงาน"].str.contains("กำลังผลิต")]
        hold_job = m_jobs[m_jobs["สถานะงาน"].str.contains("พักงาน")]
        waiting_jobs = m_jobs[m_jobs["สถานะงาน"].str.contains("รอคิว")]

        # จัดการแจ้งเตือนกรณีมีงานพักรอวัสดุ
        hold_alert_html = ""
        if not hold_job.empty:
            hold_machines_count += 1
            h_first = hold_job.iloc[0]
            h_start = h_first.get("เริ่มจริง")
            h_start_txt = ""
            h_dt_parsed = parse_flexible_datetime(h_start)
            if h_dt_parsed is not None and pd.notna(h_dt_parsed):
                h_start_txt = f" [เริ่ม {h_dt_parsed.strftime('%H:%M น.')}]"
            hold_alert_html = f'<div style="margin-top:4px; padding:3px 6px; background:rgba(217, 119, 6, 0.35); border:1px dashed #FCD34D; border-radius:6px; font-size:10.5px; color:#FEF08A;">🛑 <b>พักงานรอ:</b> {h_first.get("แผนงาน", "-")} ({h_first.get("ชื่อ Drawing.", "-")}){h_start_txt}</div>'

        if not running_job.empty:
            running_machines_count += 1
            r_info = running_job.iloc[0]
            s_start = r_info.get("เริ่มจริง")
            p_code = str(r_info.get("แผนงาน", "-"))
            d_code = str(r_info.get("ชื่อ Drawing.", "-"))
            step_name = str(r_info.get("ขั้นตอน (Step)", "-"))
            
            # คำนวณเวลาเริ่มและจบงานตามแผน
            s_m = safe_float(r_info.get("Setup (น.)"), 10.0)
            b_m = safe_float(r_info.get("Basic (น.)"), 0.0)
            p_m = safe_float(r_info.get("โปรแกรม (น.)"), 120.0)
            tot_h = (s_m + b_m + p_m) / 60.0

            act_st_parsed = parse_flexible_datetime(s_start)
            if act_st_parsed is None or pd.isna(act_st_parsed):
                act_st_parsed = parse_flexible_datetime(r_info.get("วัน-เวลาขึ้นงาน"))
            if act_st_parsed is None or pd.isna(act_st_parsed):
                act_st_parsed = now_check

            # แผนเริ่มตั้งต้น (Baseline)
            plan_st_parsed = parse_flexible_datetime(r_info.get("วัน-เวลาขึ้นงาน"))
            if plan_st_parsed is None or pd.isna(plan_st_parsed) or plan_st_parsed.year < 2020:
                plan_st_parsed = act_st_parsed

            plan_start_disp_txt = plan_st_parsed.strftime("%d/%m %H:%M")

            # แผนเสร็จคำนวณจากเวลาเริ่มจริง (หรือแผนเริ่ม) บวกกะงาน
            _, plan_finish_dt = add_work_time_with_shift(get_next_valid_work_time(act_st_parsed), tot_h)

            start_disp_txt = act_st_parsed.strftime("%H:%M น.")
            finish_disp_txt = plan_finish_dt.strftime("%d/%m %H:%M น.")
            start_epoch = to_bangkok_epoch_ms(act_st_parsed)

            # ตรวจสอบสถานะเตือนสี 3 ระดับ
            diff_mins = (plan_finish_dt - now_check).total_seconds() / 60.0
            if diff_mins < 0:
                tv_card_cls = "tv-card tv-card-late"
                badge_html = '<b style="color:#FCA5A5;">🔴 เกินแผน (' + f"{abs(int(diff_mins))} น.)</b>"
            elif 0 <= diff_mins <= 60:
                tv_card_cls = "tv-card tv-card-warning"
                badge_html = '<b style="color:#FDE047;">🟡 ใกล้เสร็จ (' + f"เหลือ {int(diff_mins)} น.)</b>"
            else:
                tv_card_cls = "tv-card tv-card-running"
                badge_html = '<span class="tv-pulse-dot" style="margin-right:6px;"></span> <b style="color:#A7F3D0;">กำลังผลิต ⏱️</b>'

            time_info_combined = f'''
            <div style="font-size:11.5px; font-weight:700; color:#FFFFFF; line-height:1.4;">
                <div style="display:flex; justify-content:space-between; align-items:center;">
                    <span>🚀 <b>เริ่มจริง:</b> <span style="color:#93C5FD;">{start_disp_txt}</span></span>
                    <span>⏱️ <span class="pes-live-timer" data-start-epoch="{start_epoch}" style="font-family:monospace; font-size:13px; font-weight:900; color:#FDE047;">00:00:00</span></span>
                </div>
                <div style="margin-top:3px; display:flex; justify-content:space-between; font-size:10.5px; opacity:0.95; background:rgba(0,0,0,0.28); padding:3px 6px; border-radius:5px;">
                    <span>📅 <b>แผนเริ่ม:</b> <span style="color:#E2E8F0;">{plan_start_disp_txt}</span></span>
                    <span>🏁 <b>แผนเสร็จ:</b> <span style="color:#A7F3D0; font-weight:800;">{finish_disp_txt}</span></span>
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
            hold_machines_count += 1
            h_info = hold_job.iloc[0]
            h_start = h_info.get("เริ่มจริง")
            p_code = str(h_info.get("แผนงาน", "-"))
            d_code = str(h_info.get("ชื่อ Drawing.", "-"))
            step_name = str(h_info.get("ขั้นตอน (Step)", "-"))
            
            h_ready_dt = parse_flexible_datetime(h_info.get("วัน-เวลาขึ้นงาน"))
            ready_display_txt = h_ready_dt.strftime("%d/%m %H:%M น.") if (h_ready_dt is not None and pd.notna(h_ready_dt)) else "-"

            h_start_txt = ""
            h_st_parsed = parse_flexible_datetime(h_start)
            if h_st_parsed is not None and pd.notna(h_st_parsed):
                h_start_txt = f" (เริ่มไว้: {h_st_parsed.strftime('%H:%M น.')})"

            time_info_combined = f'''
            <div style="font-size:11.5px; font-weight:700; color:#FEF3C7; line-height:1.4;">
                <div>⚠️ <b>เครื่องหยุด:</b> รอเบิกวัสดุใหม่{h_start_txt}</div>
                <div style="margin-top:3px; display:flex; justify-content:space-between; font-size:11px; opacity:0.9; background:rgba(0,0,0,0.25); padding:3px 6px; border-radius:5px;">
                    <span>📅 <b>แผนเริ่ม:</b> {ready_display_txt}</span>
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
                p_code = str(w_first.get('แผนงาน', '-'))
                d_code = str(w_first.get('ชื่อ Drawing.', '-'))
                step_name = str(w_first.get('ขั้นตอน (Step)', '-'))
                next_txt = f"คิวถัดไป: {p_code} ({d_code})"
                
                # คำนวณเวลาเริ่มและวันจบตามแผนของคิวถัดไป
                w_s_m = safe_float(w_first.get("Setup (น.)"), 10.0)
                w_b_m = safe_float(w_first.get("Basic (น.)"), 0.0)
                w_p_m = safe_float(w_first.get("โปรแกรม (น.)"), 120.0)
                w_tot_h = (w_s_m + w_b_m + w_p_m) / 60.0

                w_ready_dt = parse_flexible_datetime(w_first.get("วัน-เวลาขึ้นงาน"))
                if w_ready_dt is None or pd.isna(w_ready_dt) or w_ready_dt.year < 2020:
                    w_ready_dt = now_check
                
                w_start_valid = get_next_valid_work_time(w_ready_dt)
                _, w_finish_valid = add_work_time_with_shift(w_start_valid, w_tot_h)

                w_start_disp = w_start_valid.strftime("%d/%m %H:%M")
                w_finish_disp = w_finish_valid.strftime("%d/%m %H:%M น.")
                
                next_dates_html = f'''
                <div style="margin-top:3px; display:flex; justify-content:space-between; font-size:10.5px; color:#CBD5E1; background:rgba(0,0,0,0.3); padding:3px 6px; border-radius:5px;">
                    <span>📅 <b>เริ่ม:</b> {w_start_disp}</span>
                    <span>🏁 <b>เสร็จ:</b> <span style="color:#A7F3D0; font-weight:700;">{w_finish_disp}</span></span>
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

# =========================================================
# JavaScript ท้ายไฟล์: นาฬิกา + Live Stopwatch
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
        } catch (e) {}
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
