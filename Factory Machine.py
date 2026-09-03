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
# 1. App Icon & Header Logo
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
# โครงสร้างหน้าเว็บหลัก
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

    m_all_jobs = df_all[df_all["เลือกเครื่องจักร"] == selected_m].copy() if not df_all.empty else pd.DataFrame()

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

        # คำนวณคิวต่อเนื่องของเครื่องนี้
        m_active = m_all_jobs[m_all_jobs["สถานะงาน"].isin(["🟧 รอคิวผลิต", "🟦 กำลังผลิต", "🟨 พักงาน (รอวัสดุ)"])].copy()
        m_active["temp_ready"] = m_active["วัน-เวลาขึ้นงาน"].apply(parse_flexible_datetime)
        m_active = m_active.sort_values(by=["temp_ready", "ID"], ascending=[True, True], na_position="last").drop(columns=["temp_ready"]).reset_index(drop=True)

        cur_chain_time = None
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
            is_urgent = "ด่วนแทรก" in str(step_row.get("ประเภทงาน", ""))

            s_m = safe_float(step_row.get("Setup (น.)"), 10.0)
            b_m = safe_float(step_row.get("Basic (น.)"), 0.0)
            p_m = safe_float(step_row.get("โปรแกรม (น.)"), 120.0)
            tot_h = (s_m + b_m + p_m) / 60.0

            if cur_chain_time is None:
                r_parsed = parse_flexible_datetime(step_row.get("วัน-เวลาขึ้นงาน"))
                if r_parsed is None or pd.isna(r_parsed):
                    r_parsed = get_bangkok_now().replace(tzinfo=None)
                start_w_dt = get_next_valid_work_time(r_parsed)
            else:
                start_w_dt = get_next_valid_work_time(cur_chain_time)

            _, finish_w_dt = add_work_time_with_shift(start_w_dt, tot_h)
            cur_chain_time = finish_w_dt

            ready_display_str = start_w_dt.strftime("%d/%m/%Y %H:%M น.")
            finish_plan_display_str = finish_w_dt.strftime("%d/%m/%Y %H:%M น.")

            card_style_class = "step-card"
            if is_step_running:
                card_style_class += " step-card-running"
            elif is_step_hold:
                card_style_class += " step-card-hold"

            st.markdown(f"""
            <div class="op-job-header">
                <div style="font-size:18px; font-weight:bold; color:#1E1B4B;">คิวที่ {queue_idx+1}: {plan_code} - {drawing_code}</div>
                <div style="display:flex; gap:8px; margin-top:4px;">
                    <span class="badge-chip badge-date">📅 เริ่ม: {ready_display_str}</span>
                    <span class="badge-chip badge-finish-date">🏁 จบแผน: {finish_plan_display_str}</span>
                    <span class="badge-chip badge-qty">🔢 {qty_val} ชิ้น</span>
                </div>
            </div>
            """, unsafe_allow_html=True)

            with st.container():
                st.markdown(f"<div class='{card_style_class}'>", unsafe_allow_html=True)
                step_val = st.text_input(f"ชื่อขั้นตอนงาน (Step):", value=s_name, key=f"op_step_{target_id}")
                
                c_b1, c_b2, c_b3 = st.columns(3)
                with c_b1:
                    if st.button("💾 บันทึกชื่อ", key=f"btn_s_{target_id}"):
                        update_supabase_job(target_id, {"step_name": step_val})
                        st.rerun()
                with c_b2:
                    if not is_step_running and st.button("🚀 Start", key=f"btn_st_{target_id}"):
                        update_supabase_job(target_id, {"status": "🟦 กำลังผลิต", "actual_start": get_bangkok_str()})
                        st.rerun()
                with c_b3:
                    if is_step_running and st.button("🏁 Finish", key=f"btn_fn_{target_id}"):
                        update_supabase_job(target_id, {"status": "🟩 เสร็จสิ้นแล้ว", "actual_finish": get_bangkok_str()})
                        st.rerun()
                st.markdown("</div>", unsafe_allow_html=True)

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
# VIEW 2: แดชบอร์ดภาพรวมโรงงาน (จุดแก้ปัญหาเวลาไม่สอดคล้องกัน)
# ---------------------------------------------------------
elif st.session_state.current_view == "📊 แดชบอร์ดภาพรวมโรงงาน":
    is_admin = (st.session_state.user_role == "admin")
    c_head, c_logout = st.columns([8, 2])
    with c_head:
        st.subheader("📊 แดชบอร์ดภาพรวมโรงงานและการคำนวณต้นทุน 👑 (โหมดผู้บริหาร)" if is_admin else "📊 แดชบอร์ดภาพรวมโรงงานและการคำนวณต้นทุน 👁️ (โหมดเข้าชมทั่วไป)")
    with c_logout:
        if st.session_state.user_role is not None and st.button("🚪 ออกจากระบบ", use_container_width=True):
            st.session_state.user_role = None
            st.rerun()

    df_db = fetch_jobs_from_supabase()

    if not df_db.empty:
        calc_df = df_db.copy()
        calc_df["Setup (น.)"] = pd.to_numeric(calc_df["Setup (น.)"], errors='coerce').fillna(10.0)
        calc_df["Basic (น.)"] = pd.to_numeric(calc_df["Basic (น.)"], errors='coerce').fillna(0.0)
        calc_df["โปรแกรม (น.)"] = pd.to_numeric(calc_df["โปรแกรม (น.)"], errors='coerce').fillna(0.0)
        calc_df["รวม (ชม.)"] = ((calc_df["Setup (น.)"] + calc_df["Basic (น.)"] + calc_df["โปรแกรม (น.)"]) / 60.0).round(2)

        column_order = [
            "ID", "แผนงาน", "ชื่อ Drawing.", "จำนวน", "วัสดุ", "ประเภทงาน", "ขั้นตอน (Step)",
            "เลือกเครื่องจักร", "วัน-เวลาขึ้นงาน", "Setup (น.)",
            "Basic (น.)", "โปรแกรม (น.)", "รวม (ชม.)", "สถานะงาน",
        ]
        calc_df = calc_df[[c for c in column_order if c in calc_df.columns]]
        active_jobs_editor_df = calc_df[calc_df["สถานะงาน"].isin(["🟧 รอคิวผลิต", "🟦 กำลังผลิต", "🟨 พักงาน (รอวัสดุ)"])].copy()

        # แปลงวัน-เวลาเดิม และจัดลำดับ
        active_jobs_editor_df["temp_ready_dt"] = active_jobs_editor_df["วัน-เวลาขึ้นงาน"].apply(parse_flexible_datetime)
        active_jobs_editor_df = active_jobs_editor_df.sort_values(by=["temp_ready_dt", "ID"], ascending=[True, True], na_position="last").drop(columns=["temp_ready_dt"]).reset_index(drop=True)

        # ดักจับค่าที่ผู้ใช้แก้ไขในตารางแบบสดๆ
        editor_state = st.session_state.get("editor_cnc_jobs_grid_main", {})
        edited_rows = editor_state.get("edited_rows", {})
        if edited_rows:
            for row_idx_str, changes in edited_rows.items():
                r_i = int(row_idx_str)
                if r_i < len(active_jobs_editor_df):
                    for col_name, new_val in changes.items():
                        if col_name in active_jobs_editor_df.columns:
                            active_jobs_editor_df.at[r_i, col_name] = new_val

        # =========================================================================
        # 🔗 คำนวณคิวลูกโซ่ (Auto-Chain) แบบแม่นยำ แยกตามเครื่องจักร
        # =========================================================================
        m_available_tracker = {}
        chained_ready_dates = []
        chained_finish_dates = []
        chained_start_dts = []
        chained_finish_dts = []

        for _, r in active_jobs_editor_df.iterrows():
            m_target = str(r["เลือกเครื่องจักร"])
            s_m = safe_float(r.get("Setup (น.)"), 10.0)
            b_m = safe_float(r.get("Basic (น.)"), 0.0)
            p_m = safe_float(r.get("โปรแกรม (น.)"), 120.0)
            tot_h = (s_m + b_m + p_m) / 60.0

            if m_target not in m_available_tracker:
                r_parsed = parse_flexible_datetime(r["วัน-เวลาขึ้นงาน"])
                if r_parsed is None or pd.isna(r_parsed) or r_parsed.year < 2020:
                    r_parsed = get_bangkok_now().replace(tzinfo=None)
                start_work_dt = get_next_valid_work_time(r_parsed)
            else:
                start_work_dt = get_next_valid_work_time(m_available_tracker[m_target])

            _, finish_work_dt = add_work_time_with_shift(start_work_dt, tot_h)
            m_available_tracker[m_target] = finish_work_dt

            chained_start_dts.append(start_work_dt)
            chained_finish_dts.append(finish_work_dt)
            chained_ready_dates.append(start_work_dt.strftime("%d/%m/%Y %H:%M"))
            chained_finish_dates.append(finish_work_dt.strftime("%d/%m/%Y %H:%M"))

        active_jobs_editor_df["วัน-เวลาขึ้นงาน"] = chained_ready_dates
        active_jobs_editor_df["วัน-เวลาจบงาน"] = chained_finish_dates
        active_jobs_editor_df["_dt_start"] = chained_start_dts
        active_jobs_editor_df["_dt_finish"] = chained_finish_dts
        active_jobs_editor_df["รวม (ชม.)"] = ((active_jobs_editor_df["Setup (น.)"] + active_jobs_editor_df["Basic (น.)"] + active_jobs_editor_df["โปรแกรม (น.)"]) / 60.0).round(2)
        active_jobs_editor_df["ลบ"] = st.session_state.active_select_all

        with st.expander("📝 รายการสั่งผลิตในระบบ (ตารางสั่งการผลิต - ลิงก์เวลาลูกโซ่อัตโนมัติ)", expanded=True):
            display_editor_df = active_jobs_editor_df.drop(columns=["_dt_start", "_dt_finish"]).copy()
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
                    "วัน-เวลาขึ้นงาน": st.column_config.TextColumn("วัน-เวลาขึ้นงาน", width=155),
                    "วัน-เวลาจบงาน": st.column_config.TextColumn("วัน-เวลาจบงาน", width=135, disabled=True),
                    "รวม (ชม.)": st.column_config.NumberColumn("รวม (ชม.)", width=85, format="%.2f", disabled=True),
                    "ลบ": st.column_config.CheckboxColumn("🗑️", width=55, default=False),
                },
                hide_index=True,
                use_container_width=True
            )

            c_save, c_del_top, _ = st.columns([2.5, 3.5, 4])
            with c_save:
                if st.button("💾 บันทึกข้อมูลลง Supabase", type="primary", use_container_width=True):
                    for _, row in edited_jobs.iterrows():
                        p_code = safe_str(row.get("แผนงาน"), "")
                        if not p_code: continue
                        raw_ready = row.get("วัน-เวลาขึ้นงาน")
                        dt_parsed = parse_flexible_datetime(raw_ready)
                        ready_str = dt_parsed.strftime("%Y-%m-%d %H:%M:%S") if dt_parsed is not None else None

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
                    st.toast("บันทึกข้อมูลคิวงานสำเร็จ!", icon="💾")
                    st.rerun()

        st.divider()

        # =========================================================================
        # 📋 ใบจ่ายคิวงานหน้าเครื่อง (ดึงจาก active_jobs_editor_df ตรงๆ เพื่อให้เวลาตรงกัน 100%)
        # =========================================================================
        st.subheader("📋 ใบจ่ายคิวงานหน้าเครื่อง (Work Order Sheet)")

        df_wo_direct = active_jobs_editor_df.copy()
        df_wo_direct = df_wo_direct.sort_values(by=["_dt_start"], ascending=True).reset_index(drop=True)
        df_wo_direct["ลำดับคิว"] = df_wo_direct.groupby("เลือกเครื่องจักร").cumcount() + 1
        df_wo_direct["ลำดับคิว"] = df_wo_direct["ลำดับคิว"].apply(lambda q: f"คิวที่ {q}")

        df_wo_direct["เครื่องจักร / แผนก"] = df_wo_direct["เลือกเครื่องจักร"]
        df_wo_direct["สถานะ"] = df_wo_direct["สถานะงาน"]
        df_wo_direct["เริ่มขึ้นงานตามแผน"] = df_wo_direct["วัน-เวลาขึ้นงาน"]
        df_wo_direct["จบงานตามแผน"] = df_wo_direct["วัน-เวลาจบงาน"]
        df_wo_direct["กำหนดพร้อมขึ้นงาน"] = df_wo_direct["วัน-เวลาขึ้นงาน"]

        wo_finish_map = dict(zip(df_wo_direct["ID"].astype(str), df_wo_direct["_dt_finish"]))

        styled_df_display = df_wo_direct.style.apply(
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
                "เครื่องจักร / แผนก": st.column_config.TextColumn("เครื่องจักร / แผนก", width=140),
                "ลำดับคิว": st.column_config.TextColumn("ลำดับคิว", width=95),
                "สถานะ": st.column_config.TextColumn("สถานะ", width=105),
                "ประเภทงาน": st.column_config.TextColumn("ประเภทงาน", width=100),
                "แผนงาน": st.column_config.TextColumn("แผนงาน", width=80),
                "ชื่อ Drawing.": st.column_config.TextColumn("ชื่อ Drawing.", width=170),
                "จำนวน": st.column_config.NumberColumn("จำนวน", width=65, format="%d"),
                "วัสดุ": st.column_config.TextColumn("วัสดุ", width=70),
                "ขั้นตอน (Step)": st.column_config.TextColumn("ขั้นตอน (Step)", width=120),
                "กำหนดพร้อมขึ้นงาน": st.column_config.TextColumn("กำหนดพร้อมขึ้นงาน", width=155),
                "เริ่มขึ้นงานตามแผน": st.column_config.TextColumn("เริ่มขึ้นงานตามแผน", width=155),
                "จบงานตามแผน": st.column_config.TextColumn("จบงานตามแผน", width=155),
                "Setup (น.)": st.column_config.NumberColumn("Setup (น.)", width=80, format="%d"),
                "Basic (น.)": st.column_config.NumberColumn("Basic (น.)", width=80, format="%d"),
                "โปรแกรม (น.)": st.column_config.NumberColumn("โปรแกรม (น.)", width=95, format="%d"),
                "รวม (ชม.)": st.column_config.NumberColumn("รวม (ชม.)", width=85, format="%.2f"),
            },
            use_container_width=True,
            hide_index=True
        )

        st.divider()

        # =========================================================================
        # 4. ผังเวลาขึ้นงาน (Gantt Chart Timeline)
        # =========================================================================
        gantt_records = []
        for _, r_g in active_jobs_editor_df.iterrows():
            gantt_records.append({
                "ข้อความบนแท่งกราฟ": str(r_g["แผนงาน"]),
                "แผนงาน": str(r_g["แผนงาน"]),
                "ชื่อ Drawing.": str(r_g["ชื่อ Drawing."]),
                "จำนวน": str(r_g["จำนวน"]),
                "ขั้นตอน (Step)": str(r_g["ขั้นตอน (Step)"]),
                "เครื่องจักร": str(r_g["เลือกเครื่องจักร"]),
                "วัสดุ": str(r_g["วัสดุ"]),
                "เวลาเริ่ม": r_g["_dt_start"],
                "เวลาเสร็จ": r_g["_dt_finish"],
                "ระยะเวลา": f"{r_g['รวม (ชม.)']} ชม.",
                "กิจกรรม": "⚙️ งานปกติ" if "ปกติ" in str(r_g["ประเภทงาน"]) else "🔴 งานด่วน"
            })

        df_gantt = pd.DataFrame(gantt_records)
        if not df_gantt.empty:
            st.subheader("📊 ผังเวลาขึ้นงานที่กำลังผลิตและรอคิว (Gantt Chart Timeline)")
            
            fig = px.timeline(
                df_gantt,
                x_start="เวลาเริ่ม",
                x_end="เวลาเสร็จ",
                y="เครื่องจักร",
                color="แผนงาน",
                text="ข้อความบนแท่งกราฟ",
                category_orders={"เครื่องจักร": MACHINE_LIST}
            )
            fig.update_yaxes(autorange="reversed", type="category", categoryorder="array", categoryarray=MACHINE_LIST)
            fig.update_layout(height=max(450, len(MACHINE_LIST) * 30), plot_bgcolor="#FFFFFF", paper_bgcolor="#FFFFFF")
            st.plotly_chart(fig, use_container_width=True)

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
# JavaScript ท้ายไฟล์
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
</script>
""", height=0)
