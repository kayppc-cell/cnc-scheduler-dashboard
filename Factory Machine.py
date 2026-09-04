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
    status = str(row.get("เธชเธ–เธฒเธเธฐ", row.get("เธชเธ–เธฒเธเธฐเธเธฒเธ", "")))
    job_id = str(row.get("ID", ""))

    if "เธเธณเธฅเธฑเธเธเธฅเธดเธ•" in status:
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
# 1. เธเธฒเธฃเธเธฑเธ”เธเธฒเธฃเธฃเธนเธเธ เธฒเธ (App Icon & Header Logo)
# =========================================================
icon_file = "log_ cnc_1.png"
if not os.path.exists(icon_file):
    for alt_icon in ["log_cnc_1.png", "icon.png", "logo.png"]:
        if os.path.exists(alt_icon):
            icon_file = alt_icon
            break

favicon_img = Image.open(icon_file) if os.path.exists(icon_file) else "๐ญ"

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
logo_html = f'<img src="data:image/png;base64,{logo_base64}" class="header-logo" alt="Logo"/>' if logo_base64 else '<div class="header-logo-icon">๐ญ</div>'

# =========================================================
# 2. เธ•เธเนเธ•เนเธ UI
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

header_content = f'''<div class="main-header">{logo_html}<div class="header-text"><h1>เธฃเธฐเธเธเธ•เธดเธ”เธ•เธฒเธกเนเธฅเธฐเธเธฑเธเธ—เธถเธเธเธฒเธเธซเธเนเธฒเน€เธเธฃเธทเนเธญเธเนเธเธเธเธเธฅเธดเธ•</h1><p>เธ.-เธจ. (08:30-20:00 เธ.) | เธช. (08:30-17:00 เธ.) | เน€เธเธฃเธเน€เธเนเธฒ 10:00-10:10 เธ. | เธเธฑเธเน€เธ—เธตเนเธขเธ 12:00-13:00 เธ. | เน€เธเธฃเธเธเนเธฒเธข 15:00-15:10 เธ. | เธซเธขเธธเธ”เธงเธฑเธเธญเธฒเธ—เธดเธ•เธขเน</p></div></div>'''
st.markdown(header_content, unsafe_allow_html=True)

# =========================================================
# 3. เธเธณเธซเธเธ”เธชเธดเธ—เธเธดเนเนเธฅเธฐเธเธงเธฒเธกเธเธฅเธญเธ”เธ เธฑเธข & เธ•เธฑเธงเนเธเธฃเน€เธฃเธดเนเธกเธ•เนเธเธฃเธฐเธเธ
# =========================================================
ADMIN_PASSWORD = "pesadmin"
VIEWER_PASSWORD = "pes1234"

default_states = {
    "user_role": None,
    "current_view": "๐‘ท เนเธซเธกเธ”เธเนเธฒเธเธซเธเนเธฒเน€เธเธฃเธทเนเธญเธ",
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
    "No.10 เน€เธเธฃเธทเนเธญเธเน€เธเธตเธขเธฃเธฃเธฒเธ", "No.11 เน€เธเธฃเธทเนเธญเธเน€เธเธตเธขเธฃเธเธฅเธก",
    "No.12 เธกเธดเธฅเธฅเธดเนเธ 1", "No.13 เธกเธดเธฅเธฅเธดเนเธ 2", "No.14 เธกเธดเธฅเธฅเธดเนเธ 3", "No.15 เธกเธดเธฅเธฅเธดเนเธ 4",
    "No.16 เน€เธเธฃเธทเนเธญเธเธเธฅเธถเธ",
    "MIG CO2-No.01", "MIG CO2-No.02", "MIG CO2-No.03",
    "ARGON-No.01", "ARGON-No.02", "WELDING_ALUMINUM-No.01"
]

DEFAULT_RATES = {
    "No.1 Awea": 1200, "No.2 Awea": 1000, "No.3 Hartford": 1000, "No.4 Sanco": 1000,
    "No.5 Hartford": 1000, "No.6 Bridgeport": 600, "No.7 Bridgeport": 600, "No.8 Hartford": 600, "No.9 Mikron": 1300,
    "No.10 เน€เธเธฃเธทเนเธญเธเน€เธเธตเธขเธฃเธฃเธฒเธ": 500, "No.11 เน€เธเธฃเธทเนเธญเธเน€เธเธตเธขเธฃเธเธฅเธก": 500,
    "No.12 เธกเธดเธฅเธฅเธดเนเธ 1": 400, "No.13 เธกเธดเธฅเธฅเธดเนเธ 2": 400, "No.14 เธกเธดเธฅเธฅเธดเนเธ 3": 400, "No.15 เธกเธดเธฅเธฅเธดเนเธ 4": 400,
    "No.16 เน€เธเธฃเธทเนเธญเธเธเธฅเธถเธ": 400,
    "MIG CO2-No.01": 450, "MIG CO2-No.02": 450, "MIG CO2-No.03": 450,
    "ARGON-No.01": 450, "ARGON-No.02": 450, "WELDING_ALUMINUM-No.01": 500
}

ASSIGN_OPTIONS = ["เธญเธฑเธ•เนเธเธกเธฑเธ•เธด (เน€เธเธฃเธทเนเธญเธ 3 เนเธเธเนเธ”เธเนเนเธ”เน)"] + MACHINE_LIST
JOB_TYPES = ["๐ข เธเธฒเธเธเธเธ•เธด", "๐”ด เธเธฒเธเธ”เนเธงเธเนเธ—เธฃเธ"]
JOB_STATUS = ["๐ง เธฃเธญเธเธดเธงเธเธฅเธดเธ•", "๐ฆ เธเธณเธฅเธฑเธเธเธฅเธดเธ•", "๐จ เธเธฑเธเธเธฒเธ (เธฃเธญเธงเธฑเธชเธ”เธธ)", "๐ฉ เน€เธชเธฃเนเธเธชเธดเนเธเนเธฅเนเธง"]

# =========================================================
# 4. เธเธฑเธเธเนเธเธฑเธเน€เธเธทเนเธญเธกเธ•เนเธญ Supabase
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
    if "เธเธฑเธเธเธฒเธ" in s or "เธฃเธญเธงเธฑเธชเธ”เธธ" in s:
        return "๐จ เธเธฑเธเธเธฒเธ (เธฃเธญเธงเธฑเธชเธ”เธธ)"
    elif "เธเธณเธฅเธฑเธเธเธฅเธดเธ•" in s:
        return "๐ฆ เธเธณเธฅเธฑเธเธเธฅเธดเธ•"
    elif "เน€เธชเธฃเนเธเธชเธดเนเธ" in s:
        return "๐ฉ เน€เธชเธฃเนเธเธชเธดเนเธเนเธฅเนเธง"
    else:
        return "๐ง เธฃเธญเธเธดเธงเธเธฅเธดเธ•"

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
                    "id": "ID", "plan_code": "เนเธเธเธเธฒเธ", "drawing_name": "เธเธทเนเธญ Drawing.",
                    "qty": "เธเธณเธเธงเธ", "material": "เธงเธฑเธชเธ”เธธ", "job_type": "เธเธฃเธฐเน€เธ เธ—เธเธฒเธ",
                    "step_name": "เธเธฑเนเธเธ•เธญเธ (Step)", "machine_name": "เน€เธฅเธทเธญเธเน€เธเธฃเธทเนเธญเธเธเธฑเธเธฃ",
                    "ready_at": "เธงเธฑเธ-เน€เธงเธฅเธฒเธเธถเนเธเธเธฒเธ", "setup_mins": "Setup (เธ.)",
                    "basic_hrs": "Basic (เธ.)", "prog_hrs": "เนเธเธฃเนเธเธฃเธก (เธ.)",
                    "status": "เธชเธ–เธฒเธเธฐเธเธฒเธ", "actual_start": "เน€เธฃเธดเนเธกเธเธฃเธดเธ", "actual_finish": "เน€เธชเธฃเนเธเธเธฃเธดเธ"
                }
                return df.rename(columns=col_map)
        return pd.DataFrame()
    except Exception:
        return pd.DataFrame()

# ---------------------------------------------------------
# เนเธ—เนเธเน€เธกเธเธนเน€เธเธฅเธตเนเธขเธเธกเธธเธกเธกเธญเธเธซเธฅเธฑเธ
# ---------------------------------------------------------
nav_options = [
    "๐‘ท เนเธซเธกเธ”เธเนเธฒเธเธซเธเนเธฒเน€เธเธฃเธทเนเธญเธ", 
    "๐“ เนเธ”เธเธเธญเธฃเนเธ”เธ เธฒเธเธฃเธงเธกเนเธฃเธเธเธฒเธ", 
    "๐“ เธงเธดเน€เธเธฃเธฒเธฐเธซเนเธเธฃเธฐเธชเธดเธ—เธเธดเธ เธฒเธเธฃเธฒเธข Drawing", 
    "๐“‘ เธฃเธฒเธขเธเธฒเธเธชเธฃเธธเธเธเธฃเธฐเธเธณเน€เธ”เธทเธญเธ", 
    "๐“บ เธเธญเธ—เธตเธงเธตเธเธฅเธฒเธเนเธฃเธเธเธฒเธ (TV Live)"
]

cur_idx = nav_options.index(st.session_state.current_view) if st.session_state.current_view in nav_options else 0
selected_tab = st.radio("เน€เธฅเธทเธญเธเธกเธธเธกเธกเธญเธ:", nav_options, index=cur_idx, horizontal=True, label_visibility="collapsed")

if selected_tab != st.session_state.current_view:
    st.session_state.current_view = selected_tab
    st.rerun()

# ---------------------------------------------------------
# VIEW 1: เนเธซเธกเธ”เธเนเธฒเธเธซเธเนเธฒเน€เธเธฃเธทเนเธญเธ
# ---------------------------------------------------------
if st.session_state.current_view == "๐‘ท เนเธซเธกเธ”เธเนเธฒเธเธซเธเนเธฒเน€เธเธฃเธทเนเธญเธ":
    st.markdown("### ๐“ฑ เธเธฑเธเธ—เธถเธเธชเธ–เธฒเธเธฐเธเธฒเธเธซเธเนเธฒเน€เธเธฃเธทเนเธญเธ / เนเธเธเธเธเธฅเธดเธ•")
    df_all = fetch_jobs_from_supabase()
    
    c_m_sel, c_mode_sel = st.columns([2, 2])
    with c_m_sel:
        selected_m = st.selectbox("๐ญ เน€เธฅเธทเธญเธเน€เธเธฃเธทเนเธญเธเธเธฑเธเธฃ / เนเธเธเธ:", MACHINE_LIST, key="op_machine_select")
    with c_mode_sel:
        run_mode = st.radio("โ๏ธ เธฃเธนเธเนเธเธเธเธฒเธฃเธเธฅเธดเธ•:", ["๐”น เธฃเธฑเธเธ—เธตเธฅเธฐเธเธดเธง (Piece by Piece)", "๐“ฆ เธฃเธฑเธเธฃเธงเธกเธซเธฅเธฒเธขเธเธฒเธเธเธฃเนเธญเธกเธเธฑเธ (Batch Processing)"], horizontal=True)

    if not df_all.empty:
        m_all_jobs = df_all[
            (df_all["เน€เธฅเธทเธญเธเน€เธเธฃเธทเนเธญเธเธเธฑเธเธฃ"] == selected_m) &
            (df_all["เธชเธ–เธฒเธเธฐเธเธฒเธ"].isin(["๐ง เธฃเธญเธเธดเธงเธเธฅเธดเธ•", "๐ฆ เธเธณเธฅเธฑเธเธเธฅเธดเธ•", "๐จ เธเธฑเธเธเธฒเธ (เธฃเธญเธงเธฑเธชเธ”เธธ)"]))
        ].copy()
    else:
        m_all_jobs = pd.DataFrame()

    if not m_all_jobs.empty:
        running_now = m_all_jobs[m_all_jobs["เธชเธ–เธฒเธเธฐเธเธฒเธ"].str.contains("เธเธณเธฅเธฑเธเธเธฅเธดเธ•")]
        hold_now = m_all_jobs[m_all_jobs["เธชเธ–เธฒเธเธฐเธเธฒเธ"].str.contains("เธเธฑเธเธเธฒเธ")]
        
        if not running_now.empty:
            r_cur = running_now.iloc[0]
            st_t = r_cur.get("เน€เธฃเธดเนเธกเธเธฃเธดเธ")
            st_txt = "-"
            start_epoch = to_bangkok_epoch_ms(st_t)
            act_dt = parse_flexible_datetime(st_t)
            if act_dt is not None:
                st_txt = act_dt.strftime("%H:%M เธ.")

            st.markdown(f"""
            <div class="shop-live-banner shop-live-running">
                <div style="display:flex; align-items:center; gap:10px;">
                    <span class="tv-pulse-dot"></span>
                    <span>๐ข <b>{selected_m}: เธเธณเธฅเธฑเธเธฃเธฑเธเธเธฒเธเธญเธขเธนเน</b> (เน€เธฃเธดเนเธก: {st_txt} | โฑ๏ธ เธเธณเธฅเธฑเธเธฃเธฑเธ: <span class="pes-live-timer" data-start-epoch="{start_epoch}" style="font-family:monospace; font-weight:900; font-size:15px; color:#065F46;">00:00:00</span>)</span>
                </div>
                <div style="font-size:12.5px; opacity:0.9;">
                    ๐“ <b>เนเธเธเธเธฒเธ:</b> {r_cur.get('เนเธเธเธเธฒเธ', '-')} | ๐“ <b>Drawing:</b> {r_cur.get('เธเธทเนเธญ Drawing.', '-')}
                </div>
            </div>
            """, unsafe_allow_html=True)
        elif not hold_now.empty:
            h_cur = hold_now.iloc[0]
            st.markdown(f"""
            <div class="shop-live-banner shop-live-hold">
                <div>๐‘ <b>{selected_m}: เน€เธเธฃเธทเนเธญเธเธซเธขเธธเธ”เธเธฑเธเธเธฒเธเธเธฑเนเธงเธเธฃเธฒเธง (เธฃเธญเน€เธเธดเธเธงเธฑเธชเธ”เธธเนเธซเธกเน)</b></div>
                <div style="font-size:12.5px;">๐“ <b>เนเธเธเธเธฒเธ:</b> {h_cur.get('เนเธเธเธเธฒเธ', '-')} | ๐“ <b>Drawing:</b> {h_cur.get('เธเธทเนเธญ Drawing.', '-')}</div>
            </div>
            """, unsafe_allow_html=True)
        else:
            st.markdown(f"""
            <div class="shop-live-banner shop-live-idle">
                <div>โช <b>{selected_m}: เน€เธเธฃเธทเนเธญเธเธงเนเธฒเธ (IDLE)</b> โ€” เธเธฃเนเธญเธกเธเธ” Start เน€เธฃเธดเนเธกเธเธฒเธเนเธซเธกเน</div>
            </div>
            """, unsafe_allow_html=True)

    if m_all_jobs.empty:
        st.info(f"๐ เธชเธ–เธฒเธเธต {selected_m} เนเธกเนเธกเธตเธเธดเธงเธเธฒเธเธเนเธฒเธเนเธเธฃเธฐเธเธ")
    else:
        if "Batch" in run_mode:
            st.markdown("""
            <div class="batch-toolbar">
                <div>
                    <b style="color:#1E3A8A; font-size:14.5px;">๐“ฆ เนเธเธเธเธงเธเธเธธเธกเธเธฒเธฃเธฃเธฑเธเธเธฒเธเนเธเธเธเธฅเธธเนเธก (Batch Processing Mode)</b><br>
                    <span style="font-size:12px; color:#64748B;">เน€เธซเธกเธฒเธฐเธชเธณเธซเธฃเธฑเธเธเธฒเธเธ—เธตเนเน€เธเนเธ•เธ—เธนเธฅเธเธฃเธฑเนเธเน€เธ”เธตเธขเธงเนเธฅเนเธงเธฃเธฑเธ Step เน€เธ”เธตเธขเธงเธเธฑเธเธ•เนเธญเน€เธเธทเนเธญเธเธซเธฅเธฒเธขเน เธเธดเธง</span>
                </div>
            </div>
            """, unsafe_allow_html=True)
            
            b_c1, b_c2 = st.columns(2)
            waiting_jobs = m_all_jobs[m_all_jobs["เธชเธ–เธฒเธเธฐเธเธฒเธ"].str.contains("เธฃเธญเธเธดเธง")]
            running_jobs = m_all_jobs[m_all_jobs["เธชเธ–เธฒเธเธฐเธเธฒเธ"].str.contains("เธเธณเธฅเธฑเธเธเธฅเธดเธ•")]

            with b_c1:
                if st.button(f"๐€ Start เธฃเธงเธกเธ—เธธเธเธเธฒเธเธ—เธตเนเธฃเธญเธเธดเธง ({len(waiting_jobs)} เธเธดเธง)", disabled=(len(waiting_jobs) == 0), type="primary", use_container_width=True):
                    now_str = get_bangkok_str()
                    for _, r in waiting_jobs.iterrows():
                        update_supabase_job(int(r["ID"]), {"status": "๐ฆ เธเธณเธฅเธฑเธเธเธฅเธดเธ•", "actual_start": now_str})
                    st.toast("เน€เธฃเธดเนเธกเธเธฑเธเน€เธงเธฅเธฒเธเธฃเธดเธเธ—เธธเธเธเธดเธงเธเธฃเนเธญเธกเธเธฑเธเน€เธฃเธตเธขเธเธฃเนเธญเธข!", icon="๐€")
                    st.rerun()

            with b_c2:
                if st.button(f"๐ Finish เธฃเธงเธกเธ—เธธเธเธเธฒเธเธ—เธตเนเธเธณเธฅเธฑเธเธฃเธฑเธ ({len(running_jobs)} เธเธดเธง)", disabled=(len(running_jobs) == 0), type="secondary", use_container_width=True):
                    now_str = get_bangkok_str()
                    for _, r in running_jobs.iterrows():
                        update_supabase_job(int(r["ID"]), {"status": "๐ฉ เน€เธชเธฃเนเธเธชเธดเนเธเนเธฅเนเธง", "actual_finish": now_str})
                    st.toast("เธเธฑเธเธ—เธถเธเธเธเธเธฒเธเธเธฃเธดเธเธ—เธธเธเธเธดเธงเน€เธฃเธตเธขเธเธฃเนเธญเธข!", icon="๐")
                    st.rerun()

        def sort_op_jobs(x):
            st_val = str(x.get("เธชเธ–เธฒเธเธฐเธเธฒเธ", ""))
            if "เธเธณเธฅเธฑเธเธเธฅเธดเธ•" in st_val:
                prio = 0
            elif "เธเธฑเธเธเธฒเธ" in st_val:
                prio = 1
            else:
                prio = 2
            r_dt = parse_flexible_datetime(x.get("เธงเธฑเธ-เน€เธงเธฅเธฒเธเธถเนเธเธเธฒเธ"))
            return (prio, r_dt if r_dt is not None else pd.Timestamp.max, safe_int(x.get("ID")))

        m_active = m_all_jobs.copy()
        m_active["_sort_key"] = m_active.apply(sort_op_jobs, axis=1)
        m_active = m_active.sort_values(by="_sort_key").drop(columns=["_sort_key"]).reset_index(drop=True)

        cur_chain_time = None
        machine_any_running = any("เธเธณเธฅเธฑเธเธเธฅเธดเธ•" in str(r.get("เธชเธ–เธฒเธเธฐเธเธฒเธ", "")) for _, r in m_all_jobs.iterrows())
        next_available_start_found = False

        for queue_idx, step_row in m_active.iterrows():
            target_id = safe_int(step_row["ID"])
            plan_code = str(step_row.get("เนเธเธเธเธฒเธ", "-"))
            drawing_code = str(step_row.get("เธเธทเนเธญ Drawing.", "-"))
            qty_val = int(step_row.get("เธเธณเธเธงเธ", 1) or 1)
            mat_val = str(step_row.get("เธงเธฑเธชเธ”เธธ", "-"))
            raw_s_name = str(step_row.get("เธเธฑเนเธเธ•เธญเธ (Step)", "เธฃเธญเธซเธเนเธฒเน€เธเธฃเธทเนเธญเธเธฃเธฐเธเธธ"))
            s_name = raw_s_name if raw_s_name not in ["", "None", "nan", "เธฃเธญเธซเธเนเธฒเน€เธเธฃเธทเนเธญเธเธฃเธฐเธเธธ"] else f"OP{(queue_idx+1)*10}"
            s_status = str(step_row.get("เธชเธ–เธฒเธเธฐเธเธฒเธ", "๐ง เธฃเธญเธเธดเธงเธเธฅเธดเธ•"))
            s_start = step_row.get("เน€เธฃเธดเนเธกเธเธฃเธดเธ")
            s_finish = step_row.get("เน€เธชเธฃเนเธเธเธฃเธดเธ")

            is_step_running = "เธเธณเธฅเธฑเธเธเธฅเธดเธ•" in s_status
            is_step_hold = "เธเธฑเธเธเธฒเธ" in s_status
            is_step_finished = "เน€เธชเธฃเนเธเธชเธดเนเธ" in s_status
            is_step_waiting = not is_step_running and not is_step_finished and not is_step_hold
            is_urgent = "เธ”เนเธงเธเนเธ—เธฃเธ" in str(step_row.get("เธเธฃเธฐเน€เธ เธ—เธเธฒเธ", ""))

            s_m = safe_float(step_row.get("Setup (เธ.)"), 10.0)
            b_m = safe_float(step_row.get("Basic (เธ.)"), 0.0)
            p_m = safe_float(step_row.get("เนเธเธฃเนเธเธฃเธก (เธ.)"), 120.0)
            tot_h = (s_m + b_m + p_m) / 60.0

            if cur_chain_time is None:
                r_parsed = parse_flexible_datetime(step_row.get("เธงเธฑเธ-เน€เธงเธฅเธฒเธเธถเนเธเธเธฒเธ"))
                if r_parsed is None or pd.isna(r_parsed) or r_parsed.year < 2020:
                    # เธขเธฑเธเนเธกเนเธกเธตเน€เธงเธฅเธฒเนเธเธ: เนเธชเธ”เธเธงเนเธฒเธเนเธฅเธฐเธฃเธญเนเธซเนเธเธนเนเธงเธฒเธเนเธเธเธเธณเธซเธเธ”
                    # เธซเนเธฒเธกเนเธเนเน€เธงเธฅเธฒเธเธฑเธเธเธธเธเธฑเธ เน€เธเธฃเธฒเธฐเธเนเธฒเนเธเธเธเธฐเน€เธเธฅเธตเนเธขเธเน€เธญเธเธ—เธธเธเธเธฃเธฑเนเธเธ—เธตเนเธซเธเนเธฒเน€เธงเนเธ rerun
                    start_w_dt = None
                else:
                    start_w_dt = get_next_valid_work_time(r_parsed)
            else:
                start_w_dt = get_next_valid_work_time(cur_chain_time)

            if start_w_dt is None:
                finish_w_dt = None
                ready_display_str = "-"
                finish_plan_display_str = "-"
            else:
                _, finish_w_dt = add_work_time_with_shift(start_w_dt, tot_h)
                cur_chain_time = finish_w_dt
                ready_display_str = start_w_dt.strftime("%d/%m/%Y %H:%M เธ.")
                finish_plan_display_str = finish_w_dt.strftime("%d/%m/%Y %H:%M เธ.")

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
                status_badge_html = '<span class="badge-chip badge-hold">๐‘ เธเธฑเธเธเธฒเธ (เธฃเธญเธงเธฑเธชเธ”เธธเนเธซเธกเน)</span>'
            elif is_step_running:
                header_box_class = "op-job-header op-job-header-running"
                badge_gradient = "linear-gradient(135deg, #059669 0%, #10B981 100%)"
                status_badge_html = '<span class="badge-chip badge-running"><span class="tv-pulse-dot" style="margin-right:6px;"></span> ๐ฆ เธเธณเธฅเธฑเธเธเธฅเธดเธ• (เธฃเธฑเธเธเธฒเธเธญเธขเธนเน โฑ๏ธ)</span>'
            elif is_urgent:
                header_box_class = "op-job-header op-job-header-urgent"
                badge_gradient = "linear-gradient(135deg, #DC2626 0%, #EF4444 100%)"
                status_badge_html = '<span class="badge-chip badge-urgent">๐”ฅ ๐”ด เธเธฒเธเธ”เนเธงเธเนเธ—เธฃเธ</span>'
            else:
                header_box_class = "op-job-header"
                badge_gradient = "linear-gradient(135deg, #4F46E5 0%, #7C3AED 100%)"
                status_badge_html = ''

            card_header_html = f'''<div class="{header_box_class}"><div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px;"><div style="font-size:20px; font-weight:800; color:#1E1B4B; display:flex; align-items:center; gap:8px;"><span style="background:{badge_gradient}; color:white; padding:4px 12px; border-radius:10px; font-size:14px; box-shadow:0 3px 8px rgba(0,0,0,0.15);">เธเธดเธงเธ—เธตเน {queue_idx+1}</span><span>เนเธเธเธเธฒเธ: {plan_code}</span></div><span class="badge-chip badge-station">๐ญ {selected_m}</span></div><div style="display:flex; flex-wrap:wrap; gap:6px; align-items:center;">{status_badge_html}<span class="badge-chip badge-date">๐“… <b>เธเธณเธซเธเธ”เธเธถเนเธเธเธฒเธ:</b> {ready_display_str}</span><span class="badge-chip badge-finish-date">๐ <b>เธเธณเธซเธเธ”เธเธเธเธฒเธเธ•เธฒเธกเนเธเธ:</b> {finish_plan_display_str}</span><span class="badge-chip badge-drawing">๐“ <b>Drawing:</b> {drawing_code}</span><span class="badge-chip badge-qty">๐”ข <b>เธเธณเธเธงเธ:</b> {qty_val} เธเธดเนเธ</span><span class="badge-chip badge-mat">๐”ฉ <b>เธงเธฑเธชเธ”เธธ:</b> {mat_val}</span></div></div>'''
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
                    st.caption(f"**เธเธฑเนเธเธ•เธญเธ:** <span style='color:#059669; font-weight:800;'>๐ฉ เน€เธชเธฃเนเธเธชเธดเนเธเนเธฅเนเธง (เธเธเธเธฒเธ: {finish_txt})</span>", unsafe_allow_html=True)
                elif is_step_running:
                    st_parsed = parse_flexible_datetime(s_start)
                    start_txt = st_parsed.strftime('%H:%M เธ.') if (st_parsed is not None and pd.notna(st_parsed)) else '-'
                    step_start_epoch = to_bangkok_epoch_ms(s_start)
                    st.caption(f"""**เธเธฑเนเธเธ•เธญเธ:** <span style='color:#059669; font-weight:800; font-size:14px;'><span class='tv-pulse-dot' style='margin-right:6px;'></span> ๐ฆ เธเธณเธฅเธฑเธเธเธฅเธดเธ• (เน€เธฃเธดเนเธกเธฃเธฑเธ: {start_txt}) | โฑ๏ธ เน€เธงเธฅเธฒเน€เธ”เธดเธเธเธฃเธดเธ: <span class='pes-live-timer' data-start-epoch='{step_start_epoch}' style='font-family:monospace; font-size:16px; font-weight:900; color:#047857;'>00:00:00</span></span>""", unsafe_allow_html=True)
                elif is_step_hold:
                    st.caption(f"**เธเธฑเนเธเธ•เธญเธ:** <span style='color:#D97706; font-weight:800; font-size:13.5px;'>๐จ เธเธฑเธเธเธฒเธเธเธฑเนเธงเธเธฃเธฒเธง (เธเธดเนเธเธเธฒเธเธกเธตเธเธฑเธเธซเธฒ / เธฃเธญเน€เธเธดเธเธงเธฑเธชเธ”เธธเนเธซเธกเน) ๐‘</span>", unsafe_allow_html=True)
                else:
                    if can_start:
                        st.caption(f"**เธเธฑเนเธเธ•เธญเธ:** <span style='color:#D97706; font-weight:800;'>๐ง เธเธฃเนเธญเธกเน€เธฃเธดเนเธกเธเธฒเธ (Ready to Start)</span>", unsafe_allow_html=True)
                    else:
                        st.caption(f"**เธเธฑเนเธเธ•เธญเธ:** <span style='color:#64748B; font-weight:600;'>๐”’ เธฃเธญเธฅเธณเธ”เธฑเธเธเธดเธงเธเนเธญเธเธซเธเนเธฒเธ•เธฒเธกเนเธเธ</span>", unsafe_allow_html=True)

                if not is_step_finished:
                    step_val = st.text_input(f"เธเธทเนเธญเธเธฑเนเธเธ•เธญเธเธเธฒเธ (Step):", value=s_name, key=f"op_step_{target_id}")

                    if is_step_hold:
                        c_btn_save, c_btn_resume = st.columns([1.5, 4])
                        with c_btn_save:
                            if st.button("๐’พ เธเธฑเธเธ—เธถเธเธเธทเนเธญ", key=f"btn_save_edit_{target_id}", use_container_width=True):
                                update_supabase_job(target_id, {"step_name": safe_str(step_val, s_name)})
                                st.toast("เธเธฑเธเธ—เธถเธเธเธทเนเธญเธเธฑเนเธเธ•เธญเธเน€เธฃเธตเธขเธเธฃเนเธญเธข!", icon="๐’พ")
                                st.rerun()
                        with c_btn_resume:
                            if st.button("โ–ถ๏ธ เนเธ”เนเธงเธฑเธชเธ”เธธเนเธซเธกเนเนเธฅเนเธง (Resume เน€เธฃเธดเนเธกเธฃเธฑเธเธ•เนเธญ)", key=f"btn_resume_{target_id}", type="primary", use_container_width=True):
                                update_supabase_job(target_id, {"step_name": safe_str(step_val, s_name), "status": "๐ฆ เธเธณเธฅเธฑเธเธเธฅเธดเธ•", "actual_start": get_bangkok_str()})
                                st.toast("เน€เธฃเธดเนเธกเธฃเธฑเธเธเธฒเธเธ•เนเธญเน€เธฃเธตเธขเธเธฃเนเธญเธข!", icon="๐€")
                                st.rerun()
                    elif is_step_running:
                        c_btn_save, c_btn_hold, c_btn_finish = st.columns([1.5, 2.5, 2])
                        with c_btn_save:
                            if st.button("๐’พ เธเธฑเธเธ—เธถเธเธเธทเนเธญ", key=f"btn_save_edit_{target_id}", use_container_width=True):
                                update_supabase_job(target_id, {"step_name": safe_str(step_val, s_name)})
                                st.toast("เธเธฑเธเธ—เธถเธเธเธทเนเธญเธเธฑเนเธเธ•เธญเธเน€เธฃเธตเธขเธเธฃเนเธญเธข!", icon="๐’พ")
                                st.rerun()
                        with c_btn_hold:
                            if st.button("๐‘ เธเธฑเธเธเธฒเธ (เธฃเธญเธงเธฑเธชเธ”เธธเนเธซเธกเน)", key=f"btn_hold_{target_id}", use_container_width=True):
                                update_supabase_job(target_id, {"step_name": safe_str(step_val, s_name), "status": "๐จ เธเธฑเธเธเธฒเธ (เธฃเธญเธงเธฑเธชเธ”เธธ)"})
                                st.toast("เธเธฑเธเธเธฒเธเน€เธฃเธตเธขเธเธฃเนเธญเธข!", icon="๐‘")
                                st.rerun()
                        with c_btn_finish:
                            if st.button("๐ Finish (เธเธเธเธฒเธเธเธฃเธดเธ)", key=f"btn_finish_step_{target_id}", type="primary", use_container_width=True):
                                update_supabase_job(target_id, {"status": "๐ฉ เน€เธชเธฃเนเธเธชเธดเนเธเนเธฅเนเธง", "actual_finish": get_bangkok_str()})
                                st.toast("เธเธฑเธเธ—เธถเธเน€เธงเธฅเธฒเธเธเธเธฃเธดเธเน€เธฃเธตเธขเธเธฃเนเธญเธข!", icon="๐")
                                st.rerun()
                    else:
                        c_btn_save, c_btn_start, c_btn_finish = st.columns([1.5, 2, 2])
                        with c_btn_save:
                            if st.button("๐’พ เธเธฑเธเธ—เธถเธเธเธทเนเธญ", key=f"btn_save_edit_{target_id}", use_container_width=True):
                                update_supabase_job(target_id, {"step_name": safe_str(step_val, s_name)})
                                st.toast("เธเธฑเธเธ—เธถเธเธเธทเนเธญเธเธฑเนเธเธ•เธญเธเน€เธฃเธตเธขเธเธฃเนเธญเธข!", icon="๐’พ")
                                st.rerun()
                        with c_btn_start:
                            if can_start:
                                if st.button("๐€ Start (เน€เธฃเธดเนเธกเธเธฑเธเน€เธงเธฅเธฒเธเธฃเธดเธ)", key=f"btn_start_step_{target_id}", type="primary", use_container_width=True):
                                    update_supabase_job(target_id, {"step_name": safe_str(step_val, s_name), "status": "๐ฆ เธเธณเธฅเธฑเธเธเธฅเธดเธ•", "actual_start": get_bangkok_str()})
                                    st.toast("เน€เธฃเธดเนเธกเธเธฅเธดเธ•เนเธฅเนเธง!", icon="๐€")
                                    st.rerun()
                            else:
                                st.button("๐€ Start", key=f"btn_start_disabled_{target_id}", disabled=True, use_container_width=True)
                        with c_btn_finish:
                            st.button("๐ Finish", key=f"btn_finish_disabled_{target_id}", disabled=True, use_container_width=True)

                st.markdown("</div>", unsafe_allow_html=True)

            with st.expander(f"โ• เน€เธเธดเนเธก Step เธ–เธฑเธ”เนเธเธชเธณเธซเธฃเธฑเธ {plan_code} ({drawing_code})", expanded=False):
                new_step_input = st.text_input("เธเธทเนเธญ Step เธ–เธฑเธ”เนเธ:", value=f"OP{(queue_idx+2)*10}", placeholder="เน€เธเนเธ OP20, เธเธฅเธถเธ, เน€เธเธตเธขเธฃ, เน€เธเธทเนเธญเธก", key=f"new_step_name_input_{target_id}")

                if st.button(f"โ• เธเธฑเธเธ—เธถเธเน€เธเธดเนเธกเธเธฑเนเธเธ•เธญเธเธ•เนเธญเธ—เนเธฒเธข", key=f"btn_add_step_{target_id}", type="secondary", use_container_width=True):
                    now_str = get_bangkok_str()
                    base_setup = safe_float(step_row.get("Setup (เธ.)"), 10.0)
                    base_basic = safe_float(step_row.get("Basic (เธ.)"), 0.0)
                    base_prog = safe_float(step_row.get("เนเธเธฃเนเธเธฃเธก (เธ.)"), 120.0)
                    
                    new_payload = {
                        "plan_code": str(plan_code),
                        "drawing_name": str(drawing_code),
                        "qty": int(qty_val),
                        "material": str(mat_val),
                        "job_type": str(step_row.get("เธเธฃเธฐเน€เธ เธ—เธเธฒเธ", "๐ข เธเธฒเธเธเธเธ•เธด")),
                        "step_name": new_step_input.strip() if new_step_input.strip() != "" else f"OP{(queue_idx+2)*10}",
                        "machine_name": selected_m,
                        "ready_at": now_str,
                        "setup_mins": base_setup,
                        "basic_hrs": base_basic,
                        "prog_hrs": base_prog,
                        "status": "๐ง เธฃเธญเธเธดเธงเธเธฅเธดเธ•"
                    }
                    if insert_supabase_job(new_payload):
                        st.cache_data.clear()
                        st.toast(f"เน€เธเธดเนเธกเธเธฑเนเธเธ•เธญเธ {new_step_input} เน€เธฃเธตเธขเธเธฃเนเธญเธขเนเธฅเนเธง!", icon="๐€")
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
# VIEW 2: เนเธ”เธเธเธญเธฃเนเธ”เธ เธฒเธเธฃเธงเธกเนเธฃเธเธเธฒเธ (เธฅเนเธญเธ Baseline + เธฃเธฑเธเธฅเธนเธเนเธเน 100%)
# ---------------------------------------------------------
elif st.session_state.current_view == "๐“ เนเธ”เธเธเธญเธฃเนเธ”เธ เธฒเธเธฃเธงเธกเนเธฃเธเธเธฒเธ":
    if st.session_state.user_role is None:
        st.subheader("๐”’ เธขเธทเธเธขเธฑเธเธ•เธฑเธงเธ•เธเธชเธณเธซเธฃเธฑเธเน€เธเนเธฒเนเธเนเธเธฒเธเนเธ”เธเธเธญเธฃเนเธ”เธ เธฒเธเธฃเธงเธกเนเธฃเธเธเธฒเธ")
        st.info("เธเธฃเธธเธ“เธฒเธเธฃเธญเธเธฃเธซเธฑเธชเธเนเธฒเธเน€เธเธทเนเธญเน€เธเนเธฒเนเธเนเธเธฒเธ:\n* **เธเธนเนเธเธฃเธดเธซเธฒเธฃ/เธงเธฒเธเนเธเธ (เนเธเนเนเธเนเธ”เน):** เธฃเธซเธฑเธชเธเนเธฒเธเธฃเธฐเธ”เธฑเธ Admin\n* **เน€เธเนเธฒเธเธกเธ—เธฑเนเธงเนเธ (เธ”เธนเธญเธขเนเธฒเธเน€เธ”เธตเธขเธง):** เธฃเธซเธฑเธชเธเนเธฒเธเธ—เธฑเนเธงเนเธ")
        col_pwd, col_btn = st.columns([3, 1])
        with col_pwd:
            input_pwd = st.text_input("เธฃเธซเธฑเธชเธเนเธฒเธ (Password):", type="password")
        with col_btn:
            st.write("")
            st.write("")
            if st.button("๐”“ เน€เธเนเธฒเธชเธนเนเธฃเธฐเธเธ", type="primary", use_container_width=True):
                if input_pwd == ADMIN_PASSWORD:
                    st.session_state.user_role = "admin"
                    st.rerun()
                elif input_pwd == VIEWER_PASSWORD:
                    st.session_state.user_role = "viewer"
                    st.rerun()
                else:
                    st.error("เธฃเธซเธฑเธชเธเนเธฒเธเนเธกเนเธ–เธนเธเธ•เนเธญเธ")
    else:
        is_admin = (st.session_state.user_role == "admin")

        c_head, c_logout = st.columns([8, 2])
        with c_head:
            if is_admin:
                st.subheader("๐“ เนเธ”เธเธเธญเธฃเนเธ”เธ เธฒเธเธฃเธงเธกเนเธฃเธเธเธฒเธเนเธฅเธฐเธเธฒเธฃเธเธณเธเธงเธ“เธ•เนเธเธ—เธธเธ ๐‘‘ (เนเธซเธกเธ”เธเธนเนเธเธฃเธดเธซเธฒเธฃ - เนเธเนเนเธเนเธ”เน)")
            else:
                st.subheader("๐“ เนเธ”เธเธเธญเธฃเนเธ”เธ เธฒเธเธฃเธงเธกเนเธฃเธเธเธฒเธเนเธฅเธฐเธเธฒเธฃเธเธณเธเธงเธ“เธ•เนเธเธ—เธธเธ ๐‘๏ธ (เนเธซเธกเธ”เน€เธเนเธฒเธเธกเธ—เธฑเนเธงเนเธ - เธ”เธนเธญเธขเนเธฒเธเน€เธ”เธตเธขเธง)")
        with c_logout:
            if st.button("๐ช เธญเธญเธเธเธฒเธเธฃเธฐเธเธ", use_container_width=True):
                st.session_state.user_role = None
                st.rerun()

        df_db = fetch_jobs_from_supabase()

        if is_admin:
            with st.expander("โ• เธชเธฑเนเธเธเธฅเธดเธ•เธเธฒเธเนเธซเธกเนเน€เธเนเธฒเธฃเธฐเธเธ (Add New Job)", expanded=False):
                with st.form("form_add_new_job_main", clear_on_submit=True):
                    f_c1, f_c2, f_c_qty, f_c3 = st.columns([1.5, 2.5, 1, 1.2])
                    with f_c1:
                        new_f_plan = st.text_input("เธฃเธซเธฑเธชเนเธเธเธเธฒเธ (Plan No.):", placeholder="เน€เธเนเธ 26-105")
                    with f_c2:
                        new_f_draw = st.text_input("เธเธทเนเธญ Drawing:", placeholder="เน€เธเนเธ P26-PES-105-001-Unit10")
                    with f_c_qty:
                        new_f_qty = st.number_input("เธเธณเธเธงเธ:", min_value=1, max_value=10000, value=1, step=1)
                    with f_c3:
                        new_f_mat = st.text_input("เธงเธฑเธชเธ”เธธ:", value="SS400")

                    f_c4, f_c5, f_c6 = st.columns([1.5, 2, 2])
                    with f_c4:
                        new_f_type = st.selectbox("เธเธฃเธฐเน€เธ เธ—เธเธฒเธ:", JOB_TYPES)
                    with f_c5:
                        st.text_input("เธเธฑเนเธเธ•เธญเธ (Step):", value="เธฃเธญเธซเธเนเธฒเน€เธเธฃเธทเนเธญเธเธฃเธฐเธเธธ", disabled=True, help="เธเนเธญเธเธเธตเนเธ–เธนเธเธฅเนเธญเธเนเธงเน เนเธซเนเธเนเธฒเธเธซเธเนเธฒเน€เธเธฃเธทเนเธญเธเน€เธเนเธเธเธนเนเธฃเธฐเธเธธเธเธทเนเธญเธเธฑเนเธเธ•เธญเธเธเธฃเธดเธ")
                    with f_c6:
                        new_f_machine = st.selectbox("เน€เธฅเธทเธญเธเน€เธเธฃเธทเนเธญเธเธเธฑเธเธฃ / เนเธเธเธ:", MACHINE_LIST)

                    f_c7, f_c8, f_c9 = st.columns([1.5, 1.5, 1.5])
                    with f_c7:
                        new_f_setup = st.number_input("เน€เธงเธฅเธฒเธ•เธฑเนเธเน€เธเธฃเธทเนเธญเธ Setup (เธเธฒเธ—เธต):", min_value=0, max_value=720, value=10, step=5)
                    with f_c8:
                        new_f_basic = st.number_input("Basic Machine (เธเธฒเธ—เธต):", min_value=0, max_value=6000, value=0, step=5)
                    with f_c9:
                        new_f_prog = st.number_input("เธฃเธฑเธเนเธเธฃเนเธเธฃเธก/เน€เธงเธฅเธฒเธ—เธณเธเธฒเธเธ•เธฒเธกเนเธเธ (เธเธฒเธ—เธต):", min_value=0, max_value=12000, value=120, step=10)

                    if st.form_submit_button("๐€ เธเธฑเธเธ—เธถเธเธชเธฑเนเธเธเธฅเธดเธ•เนเธซเธกเนเน€เธเนเธฒเธชเธนเนเธฃเธฐเธเธ", type="primary", use_container_width=True):
                        if new_f_plan.strip() != "":
                            payload = {
                                "plan_code": new_f_plan.strip(),
                                "drawing_name": new_f_draw.strip(),
                                "qty": int(new_f_qty),
                                "material": new_f_mat.strip(),
                                "job_type": new_f_type,
                                "step_name": "เธฃเธญเธซเธเนเธฒเน€เธเธฃเธทเนเธญเธเธฃเธฐเธเธธ",
                                "machine_name": new_f_machine,
                                "ready_at": get_bangkok_str(),
                                "setup_mins": float(new_f_setup),
                                "basic_hrs": float(new_f_basic),
                                "prog_hrs": float(new_f_prog),
                                "status": "๐ง เธฃเธญเธเธดเธงเธเธฅเธดเธ•"
                            }
                            if insert_supabase_job(payload):
                                st.cache_data.clear()
                                st.success(f"เน€เธเธดเนเธกเนเธเธเธเธฒเธ {new_f_plan} เน€เธเนเธฒเธชเธนเนเธฃเธฐเธเธเธชเธณเน€เธฃเนเธ!")
                                st.rerun()
                        else:
                            st.error("เธเธฃเธธเธ“เธฒเธฃเธฐเธเธธเธฃเธซเธฑเธชเนเธเธเธเธฒเธ")

        if not df_db.empty:
            calc_df = df_db.copy()
            calc_df["Setup (เธ.)"] = pd.to_numeric(calc_df["Setup (เธ.)"], errors='coerce').fillna(10.0)
            calc_df["Basic (เธ.)"] = pd.to_numeric(calc_df["Basic (เธ.)"], errors='coerce').fillna(0.0)
            calc_df["เนเธเธฃเนเธเธฃเธก (เธ.)"] = pd.to_numeric(calc_df["เนเธเธฃเนเธเธฃเธก (เธ.)"], errors='coerce').fillna(0.0)
            calc_df["เธฃเธงเธก (เธเธก.)"] = ((calc_df["Setup (เธ.)"] + calc_df["Basic (เธ.)"] + calc_df["เนเธเธฃเนเธเธฃเธก (เธ.)"]) / 60.0).round(2)

            st.markdown("### ๐ฏ เนเธเธเธชเธฃเธธเธเธ เธฒเธเธฃเธงเธกเนเธฅเธฐเธเธธเธ”เธงเธดเธเธคเธ•เธเธฒเธฃเธเธฅเธดเธ• (Executive Overview)")
            
            ov_col1, ov_col2 = st.columns([1.2, 1.8])

            with ov_col1:
                status_counts = calc_df["เธชเธ–เธฒเธเธฐเธเธฒเธ"].value_counts().reset_index()
                status_counts.columns = ["เธชเธ–เธฒเธเธฐ", "เธเธณเธเธงเธ"]
                donut_color_map = {
                    "๐ฉ เน€เธชเธฃเนเธเธชเธดเนเธเนเธฅเนเธง": "#10B981",
                    "๐ฆ เธเธณเธฅเธฑเธเธเธฅเธดเธ•": "#2563EB",
                    "๐จ เธเธฑเธเธเธฒเธ (เธฃเธญเธงเธฑเธชเธ”เธธ)": "#F59E0B",
                    "๐ง เธฃเธญเธเธดเธงเธเธฅเธดเธ•": "#94A3B8"
                }
                fig_donut = px.pie(
                    status_counts, 
                    values="เธเธณเธเธงเธ", 
                    names="เธชเธ–เธฒเธเธฐ", 
                    hole=0.55,
                    color="เธชเธ–เธฒเธเธฐ",
                    color_discrete_map=donut_color_map,
                    title="๐“ เธชเธฑเธ”เธชเนเธงเธเธชเธ–เธฒเธเธฐเธเธฒเธเธ—เธฑเนเธเธซเธกเธ”เนเธเธฃเธฐเธเธ"
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
                st.markdown("**โ ๏ธ 3 เธญเธฑเธเธ”เธฑเธเธชเธ–เธฒเธเธตเธเธญเธเธงเธ”เธชเธนเธเธชเธธเธ” (เธเธดเธงเธเธฒเธเธเนเธฒเธเธฃเธญเธเธฒเธเธ—เธตเนเธชเธธเธ”):**")
                waiting_sub = calc_df[calc_df["เธชเธ–เธฒเธเธฐเธเธฒเธ"] == "๐ง เธฃเธญเธเธดเธงเธเธฅเธดเธ•"]
                if not waiting_sub.empty:
                    m_load = waiting_sub.groupby("เน€เธฅเธทเธญเธเน€เธเธฃเธทเนเธญเธเธเธฑเธเธฃ").agg(
                        เธเธดเธงเธฃเธญ=('ID', 'count'),
                        เธเธฑเนเธงเนเธกเธเธฃเธงเธก=('เธฃเธงเธก (เธเธก.)', 'sum')
                    ).reset_index().sort_values(by="เธเธดเธงเธฃเธญ", ascending=False).head(3)

                    bn_cols = st.columns(3)
                    for idx_b, (_, b_row) in enumerate(m_load.iterrows()):
                        with bn_cols[idx_b]:
                            st.markdown(f"""
                            <div style="background:#FEF2F2; border:1.5px solid #FECACA; border-left:5px solid #DC2626; border-radius:10px; padding:10px 14px;">
                                <div style="font-size:11px; font-weight:bold; color:#991B1B;">เธญเธฑเธเธ”เธฑเธ {idx_b+1} เธเธฒเธเธเนเธฒเธเธชเธนเธเธชเธธเธ”</div>
                                <div style="font-size:14px; font-weight:800; color:#1E293B; margin:2px 0;">{b_row['เน€เธฅเธทเธญเธเน€เธเธฃเธทเนเธญเธเธเธฑเธเธฃ']}</div>
                                <div style="font-size:12px; color:#475569;">เธเธดเธงเธฃเธญ: <b style="color:#DC2626;">{b_row['เธเธดเธงเธฃเธญ']} เธเธฒเธ</b> ({b_row['เธเธฑเนเธงเนเธกเธเธฃเธงเธก']:.1f} เธเธก.)</div>
                            </div>
                            """, unsafe_allow_html=True)
                else:
                    st.success("๐ เธ—เธธเธเธชเธ–เธฒเธเธตเนเธกเนเธกเธตเธเธดเธงเธเธฒเธเธเธฑเนเธเธเนเธฒเธ")

                st.write("")
                hold_sub = calc_df[calc_df["เธชเธ–เธฒเธเธฐเธเธฒเธ"] == "๐จ เธเธฑเธเธเธฒเธ (เธฃเธญเธงเธฑเธชเธ”เธธ)"]
                total_hold_count = len(hold_sub)
                total_hold_hrs = hold_sub["เธฃเธงเธก (เธเธก.)"].sum()
                rate_map_quick = DEFAULT_RATES
                total_hold_val = sum([r.get("เธฃเธงเธก (เธเธก.)", 0.0) * rate_map_quick.get(r.get("เน€เธฅเธทเธญเธเน€เธเธฃเธทเนเธญเธเธเธฑเธเธฃ"), 500) for _, r in hold_sub.iterrows()])

                st.markdown(f"""
                <div style="background:#FFFBEB; border:1.5px dashed #F59E0B; border-radius:10px; padding:10px 16px; display:flex; justify-content:space-between; align-items:center;">
                    <div>
                        <span style="font-size:13px; font-weight:800; color:#B45309;">๐‘ เน€เธงเธฅเธฒเนเธฅเธฐเธกเธนเธฅเธเนเธฒเธชเธนเธเน€เธเธฅเนเธฒเธชเธฐเธชเธกเธเธฒเธเธเธฒเธเธ—เธตเนเธเธฑเธเนเธงเน (Downtime Loss):</span><br>
                        <span style="font-size:11.5px; color:#78350F;">เธกเธตเธเธฒเธเธ•เธดเธ”เธเธฑเธเธซเธฒเธเธฐเธเธฑเธเธฃเธญเน€เธเธดเธเธงเธฑเธชเธ”เธธ <b>{total_hold_count} เธเธฒเธ</b></span>
                    </div>
                    <div style="text-align:right;">
                        <span style="font-size:18px; font-weight:900; color:#D97706;">{total_hold_hrs:.1f} เธเธก.</span><br>
                        <span style="font-size:12px; font-weight:700; color:#B45309;">({total_hold_val:,.2f} เธฟ)</span>
                    </div>
                </div>
                """, unsafe_allow_html=True)

            with st.expander("๐“ เธ•เธฒเธฃเธฒเธเธ•เธดเธ”เธ•เธฒเธกเธเธงเธฒเธกเธเธทเธเธซเธเนเธฒเธฃเธฒเธข Drawing (Drawing Multi-Step Progress Tracker)", expanded=False):
                drawing_progress_list = []
                for (p_c, d_c), g_data in calc_df.groupby(["เนเธเธเธเธฒเธ", "เธเธทเนเธญ Drawing."]):
                    total_steps = len(g_data)
                    fin_steps = len(g_data[g_data["เธชเธ–เธฒเธเธฐเธเธฒเธ"] == "๐ฉ เน€เธชเธฃเนเธเธชเธดเนเธเนเธฅเนเธง"])
                    pct = int((fin_steps / total_steps * 100)) if total_steps > 0 else 0
                    
                    cur_run = g_data[g_data["เธชเธ–เธฒเธเธฐเธเธฒเธ"] == "๐ฆ เธเธณเธฅเธฑเธเธเธฅเธดเธ•"]
                    cur_hold = g_data[g_data["เธชเธ–เธฒเธเธฐเธเธฒเธ"] == "๐จ เธเธฑเธเธเธฒเธ (เธฃเธญเธงเธฑเธชเธ”เธธ)"]
                    if not cur_run.empty:
                        stage = f"๐ฆ เธเธณเธฅเธฑเธเธฃเธฑเธเธ—เธตเน {cur_run.iloc[0]['เน€เธฅเธทเธญเธเน€เธเธฃเธทเนเธญเธเธเธฑเธเธฃ']} ({cur_run.iloc[0]['เธเธฑเนเธเธ•เธญเธ (Step)']})"
                        cat_status = "RUNNING"
                    elif not cur_hold.empty:
                        stage = f"๐‘ เธเธฑเธเธเธฒเธเธ—เธตเน {cur_hold.iloc[0]['เน€เธฅเธทเธญเธเน€เธเธฃเธทเนเธญเธเธเธฑเธเธฃ']} (เธฃเธญเธงเธฑเธชเธ”เธธ)"
                        cat_status = "HOLD"
                    elif fin_steps == total_steps:
                        stage = "๐ฉ เธเธฅเธดเธ•เน€เธชเธฃเนเธเธเธฃเธเธ—เธธเธ Step เนเธฅเนเธง"
                        cat_status = "DONE"
                    else:
                        first_wait = g_data[g_data["เธชเธ–เธฒเธเธฐเธเธฒเธ"] == "๐ง เธฃเธญเธเธดเธงเธเธฅเธดเธ•"].iloc[0]
                        stage = f"๐ง เธฃเธญเธเธดเธงเธ—เธตเน {first_wait['เน€เธฅเธทเธญเธเน€เธเธฃเธทเนเธญเธเธเธฑเธเธฃ']}"
                        cat_status = "WAITING"

                    drawing_progress_list.append({
                        "เนเธเธเธเธฒเธ": p_c,
                        "เธเธทเนเธญ Drawing.": d_c,
                        "เธเธณเธเธงเธ (เธเธดเนเธ)": int(g_data.iloc[0].get("เธเธณเธเธงเธ", 1)),
                        "เธเธงเธฒเธกเธเธทเธเธซเธเนเธฒ (%)": pct,
                        "เธเธฑเนเธเธ•เธญเธ (เน€เธชเธฃเนเธ/เธ—เธฑเนเธเธซเธกเธ”)": f"{fin_steps}/{total_steps} Step",
                        "เธชเธ–เธฒเธเธฐเนเธฅเธฐเธชเธ–เธฒเธเธตเธเธฑเธเธเธธเธเธฑเธ": stage,
                        "status_category": cat_status
                    })
                
                df_dp_all = pd.DataFrame(drawing_progress_list).sort_values(by=["เธเธงเธฒเธกเธเธทเธเธซเธเนเธฒ (%)", "เนเธเธเธเธฒเธ"], ascending=[False, True])
                
                cnt_all = len(df_dp_all)
                cnt_done = len(df_dp_all[df_dp_all["status_category"] == "DONE"])
                cnt_run = len(df_dp_all[df_dp_all["status_category"] == "RUNNING"])
                cnt_wait = len(df_dp_all[df_dp_all["status_category"].isin(["WAITING", "HOLD"])])

                tk_btn_col, tk_search_col = st.columns([5.5, 4.5])
                with tk_btn_col:
                    st.caption("**๐ฏ เธ•เธฑเธงเธเธฃเธญเธเธ”เนเธงเธเธชเธ–เธฒเธเธฐ Drawing:**")
                    t_b1, t_b2, t_b3, t_b4 = st.columns(4)
                    cur_tracker_filter = st.session_state.get("drawing_tracker_filter", "ALL")
                    with t_b1:
                        b_type_all = "primary" if cur_tracker_filter == "ALL" else "secondary"
                        if st.button(f"๐ เธ—เธฑเนเธเธซเธกเธ” ({cnt_all})", type=b_type_all, use_container_width=True, key="btn_tk_all"):
                            st.session_state.drawing_tracker_filter = "ALL"
                            st.rerun()
                    with t_b2:
                        b_type_done = "primary" if cur_tracker_filter == "DONE" else "secondary"
                        if st.button(f"๐ข เธเธฅเธดเธ•เน€เธชเธฃเนเธ ({cnt_done})", type=b_type_done, use_container_width=True, key="btn_tk_done"):
                            st.session_state.drawing_tracker_filter = "DONE"
                            st.rerun()
                    with t_b3:
                        b_type_run = "primary" if cur_tracker_filter == "RUNNING" else "secondary"
                        if st.button(f"๐ฆ เธเธณเธฅเธฑเธเธฃเธฑเธ ({cnt_run})", type=b_type_run, use_container_width=True, key="btn_tk_run"):
                            st.session_state.drawing_tracker_filter = "RUNNING"
                            st.rerun()
                    with t_b4:
                        b_type_wait = "primary" if cur_tracker_filter == "WAITING" else "secondary"
                        if st.button(f"๐ง เธฃเธญเธเธดเธง ({cnt_wait})", type=b_type_wait, use_container_width=True, key="btn_tk_wait"):
                            st.session_state.drawing_tracker_filter = "WAITING"
                            st.rerun()

                with tk_search_col:
                    search_query_tracker = st.text_input(
                        "๐” เธเนเธเธซเธฒเนเธเธ•เธฒเธฃเธฒเธเธเธงเธฒเธกเธเธทเธเธซเธเนเธฒ (เนเธเธเธเธฒเธ, Drawing):",
                        placeholder="เธเธดเธกเธเนเน€เธเธทเนเธญเธเนเธเธซเธฒ เน€เธเนเธ 26-108, AS256...",
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
                        df_dp["เนเธเธเธเธฒเธ"].astype(str).str.lower().str.contains(q_tk) |
                        df_dp["เธเธทเนเธญ Drawing."].astype(str).str.lower().str.contains(q_tk)
                    ]

                st.dataframe(
                    df_dp[[c for c in df_dp.columns if c != "status_category"]],
                    column_config={
                        "เนเธเธเธเธฒเธ": st.column_config.TextColumn("เนเธเธเธเธฒเธ", width=90),
                        "เธเธทเนเธญ Drawing.": st.column_config.TextColumn("เธเธทเนเธญ Drawing.", width=200),
                        "เธเธณเธเธงเธ (เธเธดเนเธ)": st.column_config.NumberColumn("เธเธณเธเธงเธ", width=70),
                        "เธเธงเธฒเธกเธเธทเธเธซเธเนเธฒ (%)": st.column_config.ProgressColumn("เธเธงเธฒเธกเธเธทเธเธซเธเนเธฒ", width=150, min_value=0, max_value=100, format="%d%%"),
                        "เธเธฑเนเธเธ•เธญเธ (เน€เธชเธฃเนเธ/เธ—เธฑเนเธเธซเธกเธ”)": st.column_config.TextColumn("เธชเน€เธ•เนเธเธเธฒเธ", width=110),
                        "เธชเธ–เธฒเธเธฐเนเธฅเธฐเธชเธ–เธฒเธเธตเธเธฑเธเธเธธเธเธฑเธ": st.column_config.TextColumn("เธชเธ–เธฒเธเธฐเนเธฅเธฐเธชเธ–เธฒเธเธตเธเธฑเธเธเธธเธเธฑเธ", width=250),
                    },
                    hide_index=True,
                    use_container_width=True
                )

            st.divider()

            # =========================================================================
            # ๐”— เธฃเธฐเธเธเธฅเธนเธเนเธเนเธชเธกเธเธนเธฃเธ“เน: เธฅเนเธญเธ Baseline เธ•เธฑเนเธเธ•เนเธ + เธชเนเธเธ•เนเธญเน€เธงเธฅเธฒเธเธดเธงเธเธฒเธ (Auto-Chain)
            # =========================================================================
            column_order = [
                "ID", "เนเธเธเธเธฒเธ", "เธเธทเนเธญ Drawing.", "เธเธณเธเธงเธ", "เธงเธฑเธชเธ”เธธ", "เธเธฃเธฐเน€เธ เธ—เธเธฒเธ", "เธเธฑเนเธเธ•เธญเธ (Step)",
                "เน€เธฅเธทเธญเธเน€เธเธฃเธทเนเธญเธเธเธฑเธเธฃ", "เธงเธฑเธ-เน€เธงเธฅเธฒเธเธถเนเธเธเธฒเธ", "Setup (เธ.)",
                "Basic (เธ.)", "เนเธเธฃเนเธเธฃเธก (เธ.)", "เธฃเธงเธก (เธเธก.)", "เธชเธ–เธฒเธเธฐเธเธฒเธ",
            ]
            calc_df = calc_df[[c for c in column_order if c in calc_df.columns]]
            active_jobs_editor_df = calc_df[calc_df["เธชเธ–เธฒเธเธฐเธเธฒเธ"].isin(["๐ง เธฃเธญเธเธดเธงเธเธฅเธดเธ•", "๐ฆ เธเธณเธฅเธฑเธเธเธฅเธดเธ•", "๐จ เธเธฑเธเธเธฒเธ (เธฃเธญเธงเธฑเธชเธ”เธธ)"])].copy()

            # เน€เธเนเธเธเนเธฒเน€เธงเธฅเธฒเธ•เธฑเนเธเธ•เนเธเน€เธ”เธดเธกเนเธงเนเน€เธเนเธ Baseline เธชเธณเธซเธฃเธฑเธเธชเธญเธเธเธฅเธฑเธ เนเธกเนเนเธ•เธฐเธ•เนเธญเธ
            active_jobs_editor_df["เธเธณเธซเธเธ”เธเธฃเนเธญเธกเธเธถเนเธเธเธฒเธ (Baseline)"] = active_jobs_editor_df["เธงเธฑเธ-เน€เธงเธฅเธฒเธเธถเนเธเธเธฒเธ"]

            # เธเธฑเธ”เธฅเธณเธ”เธฑเธเธเธงเธฒเธกเธชเธณเธเธฑเธ: เธเธณเธฅเธฑเธเธเธฅเธดเธ• (0) -> เธเธฑเธเธเธฒเธ (1) -> เธฃเธญเธเธดเธง (2) เธ•เธฒเธกเน€เธงเธฅเธฒเธเธถเนเธเธเธฒเธเน€เธ”เธดเธก
            def get_queue_priority(r):
                st_val = str(r.get("เธชเธ–เธฒเธเธฐเธเธฒเธ", ""))
                prio = 0 if "เธเธณเธฅเธฑเธเธเธฅเธดเธ•" in st_val else (1 if "เธเธฑเธเธเธฒเธ" in st_val else 2)
                dt_p = parse_flexible_datetime(r.get("เธงเธฑเธ-เน€เธงเธฅเธฒเธเธถเนเธเธเธฒเธ"))
                return (str(r.get("เน€เธฅเธทเธญเธเน€เธเธฃเธทเนเธญเธเธเธฑเธเธฃ")), prio, dt_p if dt_p is not None else pd.Timestamp.max, safe_int(r.get("ID")))

            active_jobs_editor_df["_sort_key"] = active_jobs_editor_df.apply(get_queue_priority, axis=1)
            active_jobs_editor_df = active_jobs_editor_df.sort_values(by="_sort_key").drop(columns=["_sort_key"]).reset_index(drop=True)

            editor_state = st.session_state.get("editor_cnc_jobs_grid_main", {})
            edited_rows = editor_state.get("edited_rows", {})
            # edited_rows เนเธเนเน€เธฅเธเนเธ–เธงเธเธญเธเธ•เธฒเธฃเธฒเธเธ—เธตเนเธเธนเนเนเธเนเน€เธซเนเธ (เธเธถเนเธเธญเธฒเธเธเนเธฒเธเธเธฒเธฃเธเนเธเธซเธฒ/เธเธฃเธญเธเนเธฅเนเธง)
            # เธเธถเธเธ•เนเธญเธเนเธเธฅเธเธเธฅเธฑเธเธ”เนเธงเธข ID เธซเนเธฒเธกเธเธณเน€เธฅเธเนเธ–เธงเธเธฑเนเธเนเธเธเธตเน active_jobs_editor_df เนเธ”เธขเธ•เธฃเธ
            previous_editor_row_ids = st.session_state.get("editor_cnc_jobs_grid_main_row_ids", [])
            if edited_rows:
                for row_idx_str, changes in edited_rows.items():
                    r_i = int(row_idx_str)
                    target_idx = None
                    if r_i < len(previous_editor_row_ids):
                        edited_id = previous_editor_row_ids[r_i]
                        id_matches = active_jobs_editor_df.index[
                            active_jobs_editor_df["ID"].astype(str) == str(edited_id)
                        ].tolist()
                        if id_matches:
                            target_idx = id_matches[0]
                    # เธฃเธญเธเธฃเธฑเธเธซเธเนเธฒเนเธฃเธเธเนเธญเธเธ—เธตเนเธเธฐเธกเธตเธฃเธฒเธขเธเธฒเธฃ ID เนเธ session (เธเธฃเธ“เธตเนเธกเนเธเธฃเธญเธเธ•เธฒเธฃเธฒเธ)
                    elif r_i < len(active_jobs_editor_df):
                        target_idx = r_i

                    if target_idx is not None:
                        for col_name, new_val in changes.items():
                            if col_name in active_jobs_editor_df.columns:
                                active_jobs_editor_df.at[target_idx, col_name] = new_val

            # เธเธณเธเธงเธ“เธฃเธฐเธเธเธฅเธนเธเนเธเน (Auto-Chain): เธเธดเธงเนเธฃเธเธ•เธฑเนเธเธ•เนเธ -> เธเธดเธงเธ–เธฑเธ”เนเธเธฃเธฑเธเน€เธงเธฅเธฒเธเธเธเธฒเธเธเธดเธงเธเนเธญเธเธซเธเนเธฒ
            m_available_tracker = {}
            chained_start_dates = []
            chained_finish_dates = []

            for _, r in active_jobs_editor_df.iterrows():
                m_target = str(r["เน€เธฅเธทเธญเธเน€เธเธฃเธทเนเธญเธเธเธฑเธเธฃ"])
                s_m = safe_float(r.get("Setup (เธ.)"), 10.0)
                b_m = safe_float(r.get("Basic (เธ.)"), 0.0)
                p_m = safe_float(r.get("เนเธเธฃเนเธเธฃเธก (เธ.)"), 120.0)
                tot_h = (s_m + b_m + p_m) / 60.0

                if m_target not in m_available_tracker:
                    r_parsed = parse_flexible_datetime(r["เธงเธฑเธ-เน€เธงเธฅเธฒเธเธถเนเธเธเธฒเธ"])
                    # เธซเนเธฒเธกเนเธเนเน€เธงเธฅเธฒเธเธฑเธเธเธธเธเธฑเธเนเธ—เธเธเนเธฒ เน€เธเธฃเธฒเธฐเธเธฐเธ—เธณเนเธซเนเน€เธงเธฅเธฒเนเธเธเน€เธฅเธทเนเธญเธเน€เธญเธเธ—เธธเธเธเธฃเธฑเนเธเธ—เธตเน rerun
                    if r_parsed is None or pd.isna(r_parsed) or r_parsed.year < 2020:
                        m_available_tracker[m_target] = None
                        chained_start_dates.append("")
                        chained_finish_dates.append("")
                        continue
                    start_work_dt = get_next_valid_work_time(r_parsed)
                else:
                    previous_finish = m_available_tracker[m_target]
                    # เธ–เนเธฒเธเธดเธงเนเธฃเธเธขเธฑเธเนเธกเนเธกเธตเน€เธงเธฅเธฒ เธเธดเธงเธ–เธฑเธ”เนเธเธ•เนเธญเธเธฃเธญ เนเธกเนเธชเธฃเนเธฒเธเน€เธงเธฅเธฒเนเธซเธกเนเน€เธญเธ
                    if previous_finish is None:
                        chained_start_dates.append("")
                        chained_finish_dates.append("")
                        continue
                    start_work_dt = get_next_valid_work_time(previous_finish)

                _, finish_work_dt = add_work_time_with_shift(start_work_dt, tot_h)
                m_available_tracker[m_target] = finish_work_dt

                chained_start_dates.append(start_work_dt.strftime("%d/%m/%Y %H:%M"))
                chained_finish_dates.append(finish_work_dt.strftime("%d/%m/%Y %H:%M"))

            # เธญเธฑเธเน€เธ”เธ•เน€เธงเธฅเธฒเน€เธเนเธฒเธชเธนเนเธ•เธฒเธฃเธฒเธ (เธงเธฑเธ-เน€เธงเธฅเธฒเธเธถเนเธเธเธฒเธ/เธเธเธเธฒเธ เธเธฐเน€เธเนเธเน€เธงเธฅเธฒเธฅเธนเธเนเธเนเธเธฃเธดเธ)
            active_jobs_editor_df["เธงเธฑเธ-เน€เธงเธฅเธฒเธเธถเนเธเธเธฒเธ"] = chained_start_dates
            active_jobs_editor_df["เธงเธฑเธ-เน€เธงเธฅเธฒเธเธเธเธฒเธ"] = chained_finish_dates
            active_jobs_editor_df["เธฃเธงเธก (เธเธก.)"] = ((active_jobs_editor_df["Setup (เธ.)"] + active_jobs_editor_df["Basic (เธ.)"] + active_jobs_editor_df["เนเธเธฃเนเธเธฃเธก (เธ.)"]) / 60.0).round(2)
            active_jobs_editor_df["เธฅเธ"] = st.session_state.active_select_all

            with st.expander("๐“ เธฃเธฒเธขเธเธฒเธฃเธชเธฑเนเธเธเธฅเธดเธ•เนเธเธฃเธฐเธเธ (เธ•เธฒเธฃเธฒเธเธชเธฑเนเธเธเธฒเธฃเธเธฅเธดเธ• - เธฅเธดเธเธเนเน€เธงเธฅเธฒเธฅเธนเธเนเธเนเธญเธฑเธ•เนเธเธกเธฑเธ•เธด)", expanded=True):
                if is_admin:
                    tool_col1, tool_col2, tool_search = st.columns([2.5, 4.5, 3])
                    with tool_col1:
                        b_c1, b_c2 = st.columns(2)
                        with b_c1:
                            if st.button("โ… เน€เธฅเธทเธญเธเธซเธกเธ”", key="btn_sel_all_active", use_container_width=True):
                                st.session_state.active_select_all = True
                                st.rerun()
                        with b_c2:
                            if st.button("โ เธขเธเน€เธฅเธดเธ", key="btn_unsel_all_active", use_container_width=True):
                                st.session_state.active_select_all = False
                                st.rerun()
                    with tool_col2:
                        st.caption("๐”— **เธฃเธฐเธเธเธฅเธนเธเนเธเนเธ—เธณเธเธฒเธเธญเธขเธนเน:** เธเธดเธงเธ—เธตเน 1 เน€เธเนเธเธ•เธฑเธงเธ•เธฑเนเธ เธเธดเธงเธ–เธฑเธ”เนเธเธเธฐเธฃเธฑเธเน€เธงเธฅเธฒเธเธเธกเธฒเน€เธเนเธเน€เธงเธฅเธฒเน€เธฃเธดเนเธกเนเธซเนเธญเธฑเธ•เนเธเธกเธฑเธ•เธด เนเธ”เธขเธกเธตเน€เธงเธฅเธฒ Baseline เนเธงเนเธชเธญเธเธเธฅเธฑเธ")
                    with tool_search:
                        search_query_editor = st.text_input(
                            "๐” เธเนเธเธซเธฒเนเธเธ•เธฒเธฃเธฒเธเธชเธฑเนเธเธเธฅเธดเธ• (เนเธเธเธเธฒเธ, Drawing, เธงเธฑเธชเธ”เธธ, เน€เธเธฃเธทเนเธญเธเธเธฑเธเธฃ, เธชเธ–เธฒเธเธฐ):",
                            placeholder="เธเธดเธกเธเนเน€เธเธทเนเธญเธเธฃเธญเธเธเนเธญเธกเธนเธฅ เน€เธเนเธ SS400, No.1, เธฃเธญเธเธดเธงเธเธฅเธดเธ•...",
                            key="search_active_editor_input"
                        )
                else:
                    search_query_editor = st.text_input(
                        "๐” เธเนเธเธซเธฒเนเธเธ•เธฒเธฃเธฒเธเธชเธฑเนเธเธเธฅเธดเธ• (เนเธเธเธเธฒเธ, Drawing, เธงเธฑเธชเธ”เธธ, เน€เธเธฃเธทเนเธญเธเธเธฑเธเธฃ, เธชเธ–เธฒเธเธฐ):",
                        placeholder="เธเธดเธกเธเนเน€เธเธทเนเธญเธเธฃเธญเธเธเนเธญเธกเธนเธฅ เน€เธเนเธ SS400, No.1, เธฃเธญเธเธดเธงเธเธฅเธดเธ•...",
                        key="search_active_editor_input_viewer"
                    )

                if search_query_editor.strip() != "":
                    q = search_query_editor.strip().lower()
                    display_editor_df = active_jobs_editor_df[
                        active_jobs_editor_df["เนเธเธเธเธฒเธ"].astype(str).str.lower().str.contains(q) |
                        active_jobs_editor_df["เธเธทเนเธญ Drawing."].astype(str).str.lower().str.contains(q) |
                        active_jobs_editor_df["เธงเธฑเธชเธ”เธธ"].astype(str).str.lower().str.contains(q) |
                        active_jobs_editor_df["เน€เธฅเธทเธญเธเน€เธเธฃเธทเนเธญเธเธเธฑเธเธฃ"].astype(str).str.lower().str.contains(q) |
                        active_jobs_editor_df["เธชเธ–เธฒเธเธฐเธเธฒเธ"].astype(str).str.lower().str.contains(q)
                    ].copy().reset_index(drop=True)
                else:
                    display_editor_df = active_jobs_editor_df.copy().reset_index(drop=True)

                # เน€เธเนเธเธฅเธณเธ”เธฑเธ ID เธเธญเธเธ•เธฒเธฃเธฒเธเธ—เธตเนเนเธชเธ”เธเธเธฃเธดเธเนเธงเนเนเธเนเธเธฑเธเธเธนเน edited_rows เนเธเธฃเธญเธ rerun เธ–เธฑเธ”เนเธ
                st.session_state.editor_cnc_jobs_grid_main_row_ids = display_editor_df["ID"].tolist()

                if is_admin:
                    edited_jobs = st.data_editor(
                        display_editor_df,
                        key="editor_cnc_jobs_grid_main",
                        num_rows="dynamic",
                        column_order=[
                            "เนเธเธเธเธฒเธ", "เธเธทเนเธญ Drawing.", "เธเธณเธเธงเธ", "เธงเธฑเธชเธ”เธธ", "เธเธฃเธฐเน€เธ เธ—เธเธฒเธ", "เธเธฑเนเธเธ•เธญเธ (Step)",
                            "เน€เธฅเธทเธญเธเน€เธเธฃเธทเนเธญเธเธเธฑเธเธฃ", "เธงเธฑเธ-เน€เธงเธฅเธฒเธเธถเนเธเธเธฒเธ", "เธงเธฑเธ-เน€เธงเธฅเธฒเธเธเธเธฒเธ", "Setup (เธ.)",
                            "Basic (เธ.)", "เนเธเธฃเนเธเธฃเธก (เธ.)", "เธฃเธงเธก (เธเธก.)", "เธชเธ–เธฒเธเธฐเธเธฒเธ", "เธฅเธ"
                        ],
                        column_config={
                            "ID": None,
                            "เนเธเธเธเธฒเธ": st.column_config.TextColumn("เนเธเธเธเธฒเธ", width=85),
                            "เธเธทเนเธญ Drawing.": st.column_config.TextColumn("เธเธทเนเธญ Drawing.", width=180),
                            "เธเธณเธเธงเธ": st.column_config.NumberColumn("เธเธณเธเธงเธ", width=65, min_value=1, max_value=10000, step=1, format="%d", default=1),
                            "เธงเธฑเธชเธ”เธธ": st.column_config.TextColumn("เธงเธฑเธชเธ”เธธ", width=75, default="SS400"),
                            "เธเธฃเธฐเน€เธ เธ—เธเธฒเธ": st.column_config.SelectboxColumn("เธเธฃเธฐเน€เธ เธ—เธเธฒเธ", width=125, options=JOB_TYPES, default="๐ข เธเธฒเธเธเธเธ•เธด"),
                            "เธเธฑเนเธเธ•เธญเธ (Step)": st.column_config.TextColumn("เธเธฑเนเธเธ•เธญเธ (Step)", width=130, disabled=True, default="เธฃเธญเธซเธเนเธฒเน€เธเธฃเธทเนเธญเธเธฃเธฐเธเธธ"),
                            "เน€เธฅเธทเธญเธเน€เธเธฃเธทเนเธญเธเธเธฑเธเธฃ": st.column_config.SelectboxColumn("เน€เธฅเธทเธญเธเน€เธเธฃเธทเนเธญเธเธเธฑเธเธฃ", width=160, options=ASSIGN_OPTIONS, default="No.1 Awea"),
                            "เธงเธฑเธ-เน€เธงเธฅเธฒเธเธถเนเธเธเธฒเธ": st.column_config.TextColumn(
                                "เน€เธฃเธดเนเธกเธเธถเนเธเธเธฒเธ (เธฅเธนเธเนเธเน)", 
                                width=155,
                                help="เนเธ–เธงเนเธฃเธเธ•เธฑเนเธเธ•เนเธ เนเธ–เธงเธ–เธฑเธ”เนเธเธฃเธฑเธเน€เธงเธฅเธฒเธเธเธเธฒเธเนเธ–เธงเธเธเธกเธฒเธ•เนเธญเน€เธเธทเนเธญเธเธญเธฑเธ•เนเธเธกเธฑเธ•เธด"
                            ),
                            "เธงเธฑเธ-เน€เธงเธฅเธฒเธเธเธเธฒเธ": st.column_config.TextColumn(
                                "เธเธเธเธฒเธเธ•เธฒเธกเนเธเธ (เธฅเธนเธเนเธเน)",
                                width=155,
                                disabled=True,
                                help="เน€เธงเธฅเธฒเธเธเธเธณเธเธงเธ“เธ•เธฒเธกเนเธเธเนเธฅเธฐเธเธฐเนเธฃเธเธเธฒเธ"
                            ),
                            "Setup (เธ.)": st.column_config.NumberColumn("Setup (เธ.)", width=85, min_value=0, max_value=720, step=5, format="%d", default=10),
                            "Basic (เธ.)": st.column_config.NumberColumn("Basic (เธ.)", width=85, min_value=0, max_value=6000, step=5, format="%d", default=0),
                            "เนเธเธฃเนเธเธฃเธก (เธ.)": st.column_config.NumberColumn("เนเธเธฃเนเธเธฃเธก (เธ.)", width=100, min_value=0, max_value=12000, step=10, format="%d", default=120),
                            "เธฃเธงเธก (เธเธก.)": st.column_config.NumberColumn("เธฃเธงเธก (เธเธก.)", width=85, format="%.2f", disabled=True),
                            "เธชเธ–เธฒเธเธฐเธเธฒเธ": st.column_config.SelectboxColumn("เธชเธ–เธฒเธเธฐเธเธฒเธ", width=145, options=JOB_STATUS, default="๐ง เธฃเธญเธเธดเธงเธเธฅเธดเธ•"),
                            "เธฅเธ": st.column_config.CheckboxColumn("๐—‘๏ธ", width=55, default=False),
                        },
                        hide_index=True,
                        use_container_width=True
                    )
                else:
                    edited_jobs = display_editor_df.copy()
                    st.dataframe(
                        display_editor_df[[c for c in display_editor_df.columns if c not in ["ID", "เธฅเธ", "เธเธณเธซเธเธ”เธเธฃเนเธญเธกเธเธถเนเธเธเธฒเธ (Baseline)"]]],
                        column_config={
                            "เนเธเธเธเธฒเธ": st.column_config.TextColumn("เนเธเธเธเธฒเธ", width=85),
                            "เธเธทเนเธญ Drawing.": st.column_config.TextColumn("เธเธทเนเธญ Drawing.", width=180),
                            "เธเธณเธเธงเธ": st.column_config.NumberColumn("เธเธณเธเธงเธ", width=65, format="%d"),
                            "เธงเธฑเธชเธ”เธธ": st.column_config.TextColumn("เธงเธฑเธชเธ”เธธ", width=75),
                            "เธเธฃเธฐเน€เธ เธ—เธเธฒเธ": st.column_config.TextColumn("เธเธฃเธฐเน€เธ เธ—เธเธฒเธ", width=125),
                            "เธเธฑเนเธเธ•เธญเธ (Step)": st.column_config.TextColumn("เธเธฑเนเธเธ•เธญเธ (Step)", width=130),
                            "เน€เธฅเธทเธญเธเน€เธเธฃเธทเนเธญเธเธเธฑเธเธฃ": st.column_config.TextColumn("เน€เธฅเธทเธญเธเน€เธเธฃเธทเนเธญเธเธเธฑเธเธฃ", width=160),
                            "เธงเธฑเธ-เน€เธงเธฅเธฒเธเธถเนเธเธเธฒเธ": st.column_config.TextColumn("เน€เธฃเธดเนเธกเธเธถเนเธเธเธฒเธ (เธฅเธนเธเนเธเน)", width=155),
                            "เธงเธฑเธ-เน€เธงเธฅเธฒเธเธเธเธฒเธ": st.column_config.TextColumn("เธเธเธเธฒเธเธ•เธฒเธกเนเธเธ (เธฅเธนเธเนเธเน)", width=155),
                            "Setup (เธ.)": st.column_config.NumberColumn("Setup (เธ.)", width=85, format="%d"),
                            "Basic (เธ.)": st.column_config.NumberColumn("Basic (เธ.)", width=85, format="%d"),
                            "เนเธเธฃเนเธเธฃเธก (เธ.)": st.column_config.NumberColumn("เนเธเธฃเนเธเธฃเธก (เธ.)", width=100, format="%d"),
                            "เธฃเธงเธก (เธเธก.)": st.column_config.NumberColumn("เธฃเธงเธก (เธเธก.)", width=85, format="%.2f"),
                            "เธชเธ–เธฒเธเธฐเธเธฒเธ": st.column_config.TextColumn("เธชเธ–เธฒเธเธฐเธเธฒเธ", width=145),
                        },
                        hide_index=True,
                        use_container_width=True
                    )
                
                st.markdown('<div id="editor_table_bottom_mark"></div>', unsafe_allow_html=True)

                if is_admin:
                    active_to_delete = edited_jobs[
                        (edited_jobs["เธฅเธ"] == True) & 
                        (edited_jobs["เนเธเธเธเธฒเธ"].notna()) & 
                        (edited_jobs["เนเธเธเธเธฒเธ"].astype(str).str.strip() != "") & 
                        (edited_jobs["เนเธเธเธเธฒเธ"].astype(str).str.strip() != "None")
                    ]
                    delete_count = len(active_to_delete)

                    c_save, c_del_top, _ = st.columns([2.5, 3.5, 4])
                    with c_save:
                        if st.button("๐’พ เธเธฑเธเธ—เธถเธเธเนเธญเธกเธนเธฅเธฅเธ Supabase", type="primary", use_container_width=True):
                            for _, row in edited_jobs.iterrows():
                                p_code = safe_str(row.get("เนเธเธเธเธฒเธ"), "")
                                if not p_code: 
                                    continue
                                
                                # เธเนเธฒเธเธตเนเน€เธเนเธเน€เธงเธฅเธฒเน€เธฃเธดเนเธกเธ—เธตเนเธเนเธฒเธเธเธฒเธฃเธ•เนเธญเธฅเธนเธเนเธเนเนเธฅเนเธง เธเธถเธเธเธฑเธเธ—เธถเธเธ—เธธเธเนเธ–เธงเธฅเธ ready_at
                                # เน€เธกเธทเนเธญเน€เธเธดเธ”เธซเธเนเธฒเนเธซเธกเนเธเธฐเนเธ”เนเธเนเธฒเน€เธ”เธดเธก เนเธกเนเธญเธดเธเน€เธงเธฅเธฒเธเธฑเธเธเธธเธเธฑเธ
                                raw_ready = row.get("เธงเธฑเธ-เน€เธงเธฅเธฒเธเธถเนเธเธเธฒเธ")
                                dt_parsed = parse_flexible_datetime(raw_ready)
                                ready_str = dt_parsed.strftime("%Y-%m-%d %H:%M:%S") if (dt_parsed is not None and pd.notna(dt_parsed)) else None

                                payload = {
                                    "plan_code": p_code,
                                    "drawing_name": safe_str(row.get("เธเธทเนเธญ Drawing."), ""),
                                    "qty": safe_int(row.get("เธเธณเธเธงเธ"), 1),
                                    "material": safe_str(row.get("เธงเธฑเธชเธ”เธธ"), "SS400"),
                                    "job_type": safe_str(row.get("เธเธฃเธฐเน€เธ เธ—เธเธฒเธ"), "๐ข เธเธฒเธเธเธเธ•เธด"),
                                    "step_name": safe_str(row.get("เธเธฑเนเธเธ•เธญเธ (Step)"), "เธฃเธญเธซเธเนเธฒเน€เธเธฃเธทเนเธญเธเธฃเธฐเธเธธ"),
                                    "machine_name": safe_str(row.get("เน€เธฅเธทเธญเธเน€เธเธฃเธทเนเธญเธเธเธฑเธเธฃ"), "No.1 Awea"),
                                    "ready_at": ready_str,
                                    "setup_mins": safe_float(row.get("Setup (เธ.)"), 10.0),
                                    "basic_hrs": safe_float(row.get("Basic (เธ.)"), 0.0),
                                    "prog_hrs": safe_float(row.get("เนเธเธฃเนเธเธฃเธก (เธ.)"), 120.0),
                                    "status": safe_str(row.get("เธชเธ–เธฒเธเธฐเธเธฒเธ"), "๐ง เธฃเธญเธเธดเธงเธเธฅเธดเธ•")
                                }
                                
                                row_id = row.get("ID")
                                if pd.isna(row_id) or str(row_id).strip() in ["", "None", "nan"]:
                                    insert_supabase_job(payload)
                                else:
                                    update_supabase_job(int(float(row_id)), payload)

                            st.cache_data.clear()
                            st.session_state.scroll_to_bottom = True
                            st.toast("เธเธฑเธเธ—เธถเธเธเนเธญเธกเธนเธฅเธเธดเธงเธเธฒเธเธฅเธนเธเนเธเนเธชเธณเน€เธฃเนเธ!", icon="๐’พ")
                            st.rerun()

                    with c_del_top:
                        btn_del_label = f"๐—‘๏ธ เธฅเธเธฃเธฒเธขเธเธฒเธฃเธ—เธตเนเน€เธฅเธทเธญเธ ({delete_count} เธฃเธฒเธขเธเธฒเธฃ)" if delete_count > 0 else "๐—‘๏ธ เธฅเธเธฃเธฒเธขเธเธฒเธฃเธ—เธตเนเน€เธฅเธทเธญเธ (0 เธฃเธฒเธขเธเธฒเธฃ)"
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
                                st.toast("เธฅเธเธฃเธฒเธขเธเธฒเธฃเธ—เธตเนเน€เธฅเธทเธญเธเน€เธฃเธตเธขเธเธฃเนเธญเธขเนเธฅเนเธง", icon="๐—‘๏ธ")
                                st.rerun()
                            else:
                                st.error("เน€เธเธดเธ”เธเนเธญเธเธดเธ”เธเธฅเธฒเธ”เนเธเธเธฒเธฃเธฅเธเธเนเธญเธกเธนเธฅเธเธฒเธ Supabase")

            finished_jobs_df = df_db[df_db["เธชเธ–เธฒเธเธฐเธเธฒเธ"].isin(["๐ฉ เน€เธชเธฃเนเธเธชเธดเนเธเนเธฅเนเธง", "โ… เน€เธชเธฃเนเธเธชเธดเนเธเนเธฅเนเธง"])].copy()
            active_jobs_count = len(edited_jobs[edited_jobs["เธชเธ–เธฒเธเธฐเธเธฒเธ"].isin(["๐ง เธฃเธญเธเธดเธงเธเธฅเธดเธ•", "๐ฆ เธเธณเธฅเธฑเธเธเธฅเธดเธ•", "๐จ เธเธฑเธเธเธฒเธ (เธฃเธญเธงเธฑเธชเธ”เธธ)"])])
            total_plan_hrs = active_jobs_editor_df["เธฃเธงเธก (เธเธก.)"].sum()

            kpi_html = f'''<div class="kpi-container"><div class="kpi-card kpi-green"><div class="kpi-title">โ… เธเธฒเธเน€เธชเธฃเนเธเธชเธดเนเธ</div><div class="kpi-value">{len(finished_jobs_df)} <span style="font-size:15px; font-weight:600;">เธฃเธฒเธขเธเธฒเธฃ</span></div></div><div class="kpi-card kpi-blue"><div class="kpi-title">โ๏ธ เธเธฒเธเนเธเนเธเธ</div><div class="kpi-value">{active_jobs_count} <span style="font-size:15px; font-weight:600;">เธฃเธฒเธขเธเธฒเธฃ</span></div></div><div class="kpi-card kpi-orange"><div class="kpi-title">โฑ๏ธ เน€เธงเธฅเธฒเธ—เธณเธเธฒเธเธฃเธงเธก</div><div class="kpi-value">{total_plan_hrs:.1f} <span style="font-size:15px; font-weight:600;">เธเธก.</span></div></div></div>'''
            st.markdown(kpi_html, unsafe_allow_html=True)

            st.divider()

            # =====================================================
            # 2. เนเธเธเนเธฒเธขเธเธดเธงเธเธฒเธเธซเธเนเธฒเน€เธเธฃเธทเนเธญเธ (Work Order Sheet)
            # =====================================================
            st.subheader("๐“ เนเธเธเนเธฒเธขเธเธดเธงเธเธฒเธเธซเธเนเธฒเน€เธเธฃเธทเนเธญเธ (Work Order Sheet)")

            df_wo_direct = active_jobs_editor_df.copy()
            df_wo_direct["_dt_start"] = df_wo_direct["เธงเธฑเธ-เน€เธงเธฅเธฒเธเธถเนเธเธเธฒเธ"].apply(parse_flexible_datetime)
            df_wo_direct["_dt_finish"] = df_wo_direct["เธงเธฑเธ-เน€เธงเธฅเธฒเธเธเธเธฒเธ"].apply(parse_flexible_datetime)

            def get_wo_queue_order(r):
                st_val = str(r.get("เธชเธ–เธฒเธเธฐเธเธฒเธ", r.get("เธชเธ–เธฒเธเธฐ", "")))
                prio = 0 if "เธเธณเธฅเธฑเธเธเธฅเธดเธ•" in st_val else (1 if "เธเธฑเธเธเธฒเธ" in st_val else 2)
                dt_p = parse_flexible_datetime(r.get("เธงเธฑเธ-เน€เธงเธฅเธฒเธเธถเนเธเธเธฒเธ"))
                return (prio, dt_p if dt_p is not None else pd.Timestamp.max, safe_int(r.get("ID")))

            df_wo_direct["_wo_order"] = df_wo_direct.apply(get_wo_queue_order, axis=1)
            df_wo_direct = df_wo_direct.sort_values(by=["เน€เธฅเธทเธญเธเน€เธเธฃเธทเนเธญเธเธเธฑเธเธฃ", "_wo_order"]).drop(columns=["_wo_order"]).reset_index(drop=True)

            df_wo_direct["เธฅเธณเธ”เธฑเธเธเธดเธง"] = df_wo_direct.groupby("เน€เธฅเธทเธญเธเน€เธเธฃเธทเนเธญเธเธเธฑเธเธฃ").cumcount() + 1
            df_wo_direct["เธฅเธณเธ”เธฑเธเธเธดเธง"] = df_wo_direct["เธฅเธณเธ”เธฑเธเธเธดเธง"].apply(lambda q: f"เธเธดเธงเธ—เธตเน {q}")

            df_wo_direct["เน€เธเธฃเธทเนเธญเธเธเธฑเธเธฃ / เนเธเธเธ"] = df_wo_direct["เน€เธฅเธทเธญเธเน€เธเธฃเธทเนเธญเธเธเธฑเธเธฃ"]
            df_wo_direct["เธชเธ–เธฒเธเธฐ"] = df_wo_direct["เธชเธ–เธฒเธเธฐเธเธฒเธ"]
            
            # เธเนเธญเธเธเธตเนเนเธชเธ”เธเน€เธงเธฅเธฒ Baseline เน€เธ”เธดเธกเธ—เธตเนเธฅเนเธญเธเนเธงเนเน€เธเธทเนเธญเธชเธญเธเธเธฅเธฑเธ
            df_wo_direct["เธเธณเธซเธเธ”เธเธฃเนเธญเธกเธเธถเนเธเธเธฒเธ"] = df_wo_direct["เธเธณเธซเธเธ”เธเธฃเนเธญเธกเธเธถเนเธเธเธฒเธ (Baseline)"]
            
            # เธเนเธญเธเธเธตเนเนเธชเธ”เธเน€เธงเธฅเธฒเธฅเธนเธเนเธเนเธ—เธตเนเธ•เนเธญเน€เธเธทเนเธญเธเธเธฑเธเธเธฃเธดเธ
            df_wo_direct["เน€เธฃเธดเนเธกเธเธถเนเธเธเธฒเธเธ•เธฒเธกเนเธเธ"] = df_wo_direct["เธงเธฑเธ-เน€เธงเธฅเธฒเธเธถเนเธเธเธฒเธ"]
            df_wo_direct["เธเธเธเธฒเธเธ•เธฒเธกเนเธเธ"] = df_wo_direct["เธงเธฑเธ-เน€เธงเธฅเธฒเธเธเธเธฒเธ"]

            wo_finish_map = dict(zip(df_wo_direct["ID"].astype(str), df_wo_direct["_dt_finish"]))

            now_check = get_bangkok_now().replace(tzinfo=None)
            warn_count = 0
            late_count = 0
            for _, r in df_wo_direct.iterrows():
                if "เธเธณเธฅเธฑเธเธเธฅเธดเธ•" in str(r.get("เธชเธ–เธฒเธเธฐ", "")):
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
                    "๐” เธเนเธเธซเธฒเนเธเนเธเธเนเธฒเธขเธเธดเธงเธเธฒเธ (เนเธเธเธเธฒเธ, Drawing, เน€เธเธฃเธทเนเธญเธเธเธฑเธเธฃ, เธชเธ–เธฒเธเธฐ):",
                    placeholder="เธเธดเธกเธเนเน€เธเธทเนเธญเธเนเธเธซเธฒเธเธดเธงเธเธฒเธ เน€เธเนเธ เธฃเธญเธเธดเธงเธเธฅเธดเธ•, เธเธณเธฅเธฑเธเธเธฅเธดเธ•...",
                    key="search_wo_sheet_input"
                )

            with wo_filter_btn_col:
                st.caption("**๐ฏ เธ•เธฑเธงเธเธฃเธญเธเธ”เนเธงเธเธชเธ–เธฒเธเธฐเน€เธ•เธทเธญเธเน€เธงเธฅเธฒ:**")
                f_b1, f_b2, f_b3 = st.columns([1.5, 2.2, 2.2])
                cur_wo_filter = st.session_state.get("wo_color_filter", "ALL")
                with f_b1:
                    btn_all_type = "primary" if cur_wo_filter == "ALL" else "secondary"
                    if st.button("๐ เธ—เธฑเนเธเธซเธกเธ”", type=btn_all_type, use_container_width=True, key="btn_wo_filter_all"):
                        st.session_state.wo_color_filter = "ALL"
                        st.rerun()
                with f_b2:
                    btn_warn_type = "primary" if cur_wo_filter == "WARN" else "secondary"
                    if st.button(f"๐ก เนเธเธฅเนเน€เธชเธฃเนเธ ({warn_count})", type=btn_warn_type, use_container_width=True, help="เน€เธซเธฅเธทเธญเธเนเธญเธขเธเธงเนเธฒ 1 เธเธก.", key="btn_wo_filter_warn"):
                        st.session_state.wo_color_filter = "WARN"
                        st.rerun()
                with f_b3:
                    btn_late_type = "primary" if cur_wo_filter == "LATE" else "secondary"
                    if st.button(f"๐”ด เน€เธเธดเธเนเธเธ ({late_count})", type=btn_late_type, use_container_width=True, help="เน€เธฅเธขเธเธณเธซเธเธ”เน€เธงเธฅเธฒเนเธเธ", key="btn_wo_filter_late"):
                        st.session_state.wo_color_filter = "LATE"
                        st.rerun()

            df_display = df_wo_direct.copy()

            selected_wo_filter = st.session_state.get("wo_color_filter", "ALL")
            if selected_wo_filter == "WARN":
                def is_warn_row(r):
                    if "เธเธณเธฅเธฑเธเธเธฅเธดเธ•" not in str(r.get("เธชเธ–เธฒเธเธฐ", "")): return False
                    f_dt = wo_finish_map.get(str(r.get("ID")))
                    if pd.notna(f_dt):
                        diff_m = (f_dt - now_check).total_seconds() / 60.0
                        return 0 <= diff_m <= 60
                    return False
                df_display = df_display[df_display.apply(is_warn_row, axis=1)]

            elif selected_wo_filter == "LATE":
                def is_late_row(r):
                    if "เธเธณเธฅเธฑเธเธเธฅเธดเธ•" not in str(r.get("เธชเธ–เธฒเธเธฐ", "")): return False
                    f_dt = wo_finish_map.get(str(r.get("ID")))
                    if pd.notna(f_dt):
                        diff_m = (f_dt - now_check).total_seconds() / 60.0
                        return diff_m < 0
                    return False
                df_display = df_display[df_display.apply(is_late_row, axis=1)]

            if search_query_wo.strip() != "":
                q_wo = search_query_wo.strip().lower()
                df_display = df_display[
                    df_display["เนเธเธเธเธฒเธ"].astype(str).str.lower().str.contains(q_wo) |
                    df_display["เธเธทเนเธญ Drawing."].astype(str).str.lower().str.contains(q_wo) |
                    df_display["เน€เธเธฃเธทเนเธญเธเธเธฑเธเธฃ / เนเธเธเธ"].astype(str).str.lower().str.contains(q_wo) |
                    df_display["เธชเธ–เธฒเธเธฐ"].astype(str).str.lower().str.contains(q_wo)
                ]

            display_cols = [c for c in df_display.columns if c not in ["_dt_start", "_dt_finish", "_sort_key", "เธเธณเธซเธเธ”เธเธฃเนเธญเธกเธเธถเนเธเธเธฒเธ (Baseline)"]]

            styled_df_display = df_display[display_cols].style.apply(
                highlight_running_deadlines,
                planned_finish_map=wo_finish_map,
                axis=1
            )

            st.dataframe(
                styled_df_display,
                column_order=[
                    "เน€เธเธฃเธทเนเธญเธเธเธฑเธเธฃ / เนเธเธเธ", "เธฅเธณเธ”เธฑเธเธเธดเธง", "เธชเธ–เธฒเธเธฐ", "เธเธฃเธฐเน€เธ เธ—เธเธฒเธ", "เนเธเธเธเธฒเธ", "เธเธทเนเธญ Drawing.", 
                    "เธเธณเธเธงเธ", "เธงเธฑเธชเธ”เธธ", "เธเธฑเนเธเธ•เธญเธ (Step)", "เธเธณเธซเธเธ”เธเธฃเนเธญเธกเธเธถเนเธเธเธฒเธ", 
                    "เน€เธฃเธดเนเธกเธเธถเนเธเธเธฒเธเธ•เธฒเธกเนเธเธ", "เธเธเธเธฒเธเธ•เธฒเธกเนเธเธ", "Setup (เธ.)", "Basic (เธ.)", "เนเธเธฃเนเธเธฃเธก (เธ.)", "เธฃเธงเธก (เธเธก.)"
                ],
                column_config={
                    "ID": None,
                    "เน€เธเธฃเธทเนเธญเธเธเธฑเธเธฃ / เนเธเธเธ": st.column_config.TextColumn("เน€เธเธฃเธทเนเธญเธเธเธฑเธเธฃ / เนเธเธเธ", width=140),
                    "เธฅเธณเธ”เธฑเธเธเธดเธง": st.column_config.TextColumn("เธฅเธณเธ”เธฑเธเธเธดเธง", width=95),
                    "เธชเธ–เธฒเธเธฐ": st.column_config.TextColumn("เธชเธ–เธฒเธเธฐ", width=105),
                    "เธเธฃเธฐเน€เธ เธ—เธเธฒเธ": st.column_config.TextColumn("เธเธฃเธฐเน€เธ เธ—เธเธฒเธ", width=100),
                    "เนเธเธเธเธฒเธ": st.column_config.TextColumn("เนเธเธเธเธฒเธ", width=80),
                    "เธเธทเนเธญ Drawing.": st.column_config.TextColumn("เธเธทเนเธญ Drawing.", width=170),
                    "เธเธณเธเธงเธ": st.column_config.NumberColumn("เธเธณเธเธงเธ", width=65, format="%d"),
                    "เธงเธฑเธชเธ”เธธ": st.column_config.TextColumn("เธงเธฑเธชเธ”เธธ", width=70),
                    "เธเธฑเนเธเธ•เธญเธ (Step)": st.column_config.TextColumn("เธเธฑเนเธเธ•เธญเธ (Step)", width=120),
                    "เธเธณเธซเธเธ”เธเธฃเนเธญเธกเธเธถเนเธเธเธฒเธ": st.column_config.TextColumn("เธเธณเธซเธเธ”เธเธฃเนเธญเธกเธเธถเนเธเธเธฒเธ (Baseline)", width=165),
                    "เน€เธฃเธดเนเธกเธเธถเนเธเธเธฒเธเธ•เธฒเธกเนเธเธ": st.column_config.TextColumn("เน€เธฃเธดเนเธกเธเธถเนเธเธเธฒเธเธ•เธฒเธกเนเธเธ (เธฅเธนเธเนเธเน)", width=155),
                    "เธเธเธเธฒเธเธ•เธฒเธกเนเธเธ": st.column_config.TextColumn("เธเธเธเธฒเธเธ•เธฒเธกเนเธเธ (เธฅเธนเธเนเธเน)", width=155),
                    "Setup (เธ.)": st.column_config.NumberColumn("Setup (เธ.)", width=80, format="%d"),
                    "Basic (เธ.)": st.column_config.NumberColumn("Basic (เธ.)", width=80, format="%d"),
                    "เนเธเธฃเนเธเธฃเธก (เธ.)": st.column_config.NumberColumn("เนเธเธฃเนเธเธฃเธก (เธ.)", width=95, format="%d"),
                    "เธฃเธงเธก (เธเธก.)": st.column_config.NumberColumn("เธฃเธงเธก (เธเธก.)", width=85, format="%.2f"),
                },
                use_container_width=True,
                hide_index=True
            )

            st.divider()

            # =====================================================
            # 3. เธเธฑเธเน€เธงเธฅเธฒเธเธถเนเธเธเธฒเธ (Gantt Chart Timeline)
            # =====================================================
            today_date = get_bangkok_now().date()
            today_dt = get_bangkok_now().replace(tzinfo=None)

            gantt_records = []
            valid_start_dates = []
            valid_end_dates = []

            for _, r_g in active_jobs_editor_df.iterrows():
                st_raw = r_g.get("เธงเธฑเธ-เน€เธงเธฅเธฒเธเธถเนเธเธเธฒเธ")
                fn_raw = r_g.get("เธงเธฑเธ-เน€เธงเธฅเธฒเธเธเธเธฒเธ")
                
                st_dt = parse_flexible_datetime(st_raw)
                fn_dt = parse_flexible_datetime(fn_raw)

                if st_dt is None or pd.isna(st_dt):
                    st_dt = today_dt
                if fn_dt is None or pd.isna(fn_dt) or fn_dt <= st_dt:
                    tot_mins = safe_float(r_g.get("เนเธเธฃเนเธเธฃเธก (เธ.)"), 120.0) + safe_float(r_g.get("Setup (เธ.)"), 10.0)
                    fn_dt = st_dt + timedelta(minutes=max(tot_mins, 30.0))

                p_name = str(r_g.get("เนเธเธเธเธฒเธ", "-"))
                dw_name = str(r_g.get("เธเธทเนเธญ Drawing.", "-"))
                step_name = str(r_g.get("เธเธฑเนเธเธ•เธญเธ (Step)", "-"))
                m_name = str(r_g.get("เน€เธฅเธทเธญเธเน€เธเธฃเธทเนเธญเธเธเธฑเธเธฃ", "-"))
                mat_name = str(r_g.get("เธงเธฑเธชเธ”เธธ", "-"))
                qty_val = str(r_g.get("เธเธณเธเธงเธ", 1))
                tot_hrs = safe_float(r_g.get("เธฃเธงเธก (เธเธก.)"), 0.0)

                valid_start_dates.append(st_dt.date())
                valid_end_dates.append(fn_dt.date())

                gantt_records.append({
                    "เธเนเธญเธเธงเธฒเธกเธเธเนเธ—เนเธเธเธฃเธฒเธ": f"{p_name}",
                    "เนเธเธเธเธฒเธ": p_name,
                    "เธเธทเนเธญ Drawing.": dw_name,
                    "เธเธณเธเธงเธ": qty_val,
                    "เธเธฑเนเธเธ•เธญเธ (Step)": step_name,
                    "เน€เธเธฃเธทเนเธญเธเธเธฑเธเธฃ": m_name,
                    "เธงเธฑเธชเธ”เธธ": mat_name,
                    "เน€เธงเธฅเธฒเน€เธฃเธดเนเธก": st_dt.strftime("%Y-%m-%d %H:%M:%S"),
                    "เน€เธงเธฅเธฒเน€เธชเธฃเนเธ": fn_dt.strftime("%Y-%m-%d %H:%M:%S"),
                    "เธฃเธฐเธขเธฐเน€เธงเธฅเธฒ": f"{tot_hrs:.2f} เธเธก.",
                    "เธเธดเธเธเธฃเธฃเธก": "โ๏ธ เธเธฒเธเธเธเธ•เธด" if "เธเธเธ•เธด" in str(r_g.get("เธเธฃเธฐเน€เธ เธ—เธเธฒเธ", "")) else "๐”ด เธเธฒเธเธ”เนเธงเธ"
                })

            df_gantt = pd.DataFrame(gantt_records)

            if not df_gantt.empty:
                st.subheader("๐“ เธเธฑเธเน€เธงเธฅเธฒเธเธถเนเธเธเธฒเธเธ—เธตเนเธเธณเธฅเธฑเธเธเธฅเธดเธ•เนเธฅเธฐเธฃเธญเธเธดเธง (Gantt Chart Timeline)")

                gantt_min_date = min(valid_start_dates) if valid_start_dates else today_date
                gantt_max_date = max(valid_end_dates) if valid_end_dates else (today_date + timedelta(days=14))

                gantt_f1, gantt_f2, gantt_f3 = st.columns([2.2, 3.2, 1.8])
                with gantt_f1:
                    m_filter_mode = st.radio(
                        "๐” เธเธฃเธญเธเธเธฅเธธเนเธกเธชเธ–เธฒเธเธตเธเธฒเธ:",
                        ["๐ เธ—เธธเธเธชเธ–เธฒเธเธต (22 เน€เธเธฃเธทเนเธญเธ)", "โ๏ธ CNC (No.1 - No.9)", "๐”ง เน€เธเธตเธขเธฃ/เธกเธดเธฅเธฅเธดเนเธ/เธเธฅเธถเธ (No.10 - No.16)", "๐”ฅ เนเธเธเธเน€เธเธทเนเธญเธก (6 เน€เธเธฃเธทเนเธญเธ)"],
                        horizontal=True
                    )

                with gantt_f2:
                    st.markdown("**๐“… เธเนเธงเธเธงเธฑเธเธ—เธตเนเธ•เนเธญเธเธเธฒเธฃเธ”เธนเธเธฑเธเธเธฒเธ:**")
                    btn_q1, btn_q2, btn_q3, btn_q4 = st.columns(4)
                    with btn_q1:
                        if st.button("๐” เธงเธฑเธเธเธตเน", key="btn_gantt_today", use_container_width=True):
                            st.session_state.gantt_date_range = (today_date, today_date)
                            st.rerun()
                    with btn_q2:
                        if st.button("๐“… 3 เธงเธฑเธ", key="btn_gantt_3d", use_container_width=True):
                            st.session_state.gantt_date_range = (today_date, today_date + timedelta(days=2))
                            st.rerun()
                    with btn_q3:
                        if st.button("๐“ 7 เธงเธฑเธ", key="btn_gantt_7d", use_container_width=True):
                            st.session_state.gantt_date_range = (today_date, today_date + timedelta(days=6))
                            st.rerun()
                    with btn_q4:
                        if st.button("๐ เธ—เธฑเนเธเธซเธกเธ”", key="btn_gantt_all", use_container_width=True):
                            st.session_state.gantt_date_range = (gantt_min_date, gantt_max_date)
                            st.rerun()

                min_cal = min(gantt_min_date, today_date) - timedelta(days=15)
                max_cal = max(gantt_max_date, today_date) + timedelta(days=60)

                if st.session_state.gantt_date_range is None or not isinstance(st.session_state.gantt_date_range, (list, tuple)):
                    st.session_state.gantt_date_range = (gantt_min_date, gantt_max_date)

                selected_date_range = st.date_input(
                    "เน€เธฅเธทเธญเธเธเนเธงเธเธงเธฑเธเธ—เธตเนเธเธณเธซเธเธ”เน€เธญเธ:",
                    value=st.session_state.gantt_date_range,
                    min_value=min_cal,
                    max_value=max_cal,
                    label_visibility="collapsed"
                )
                st.session_state.gantt_date_range = selected_date_range

                with gantt_f3:
                    color_by_option = st.selectbox("๐จ เนเธขเธเธชเธตเธ•เธฒเธก:", ["เนเธเธเธเธฒเธ (Plan Code)", "เธเธดเธเธเธฃเธฃเธก (Setup/เธ•เธฑเธ”เน€เธเธทเธญเธ)"])

                if "CNC" in m_filter_mode:
                    display_machines = MACHINE_LIST[:9]
                elif "เน€เธเธตเธขเธฃ" in m_filter_mode:
                    display_machines = MACHINE_LIST[9:16]
                elif "เน€เธเธทเนเธญเธก" in m_filter_mode:
                    display_machines = MACHINE_LIST[16:]
                else:
                    display_machines = MACHINE_LIST

                plot_gantt_df = df_gantt[df_gantt["เน€เธเธฃเธทเนเธญเธเธเธฑเธเธฃ"].isin(display_machines)].copy()

                if not plot_gantt_df.empty:
                    plot_gantt_df["เน€เธฃเธดเนเธกเนเธชเธ”เธ"] = pd.to_datetime(plot_gantt_df["เน€เธงเธฅเธฒเน€เธฃเธดเนเธก"]).dt.strftime("%d/%m/%Y %H:%M เธ.")
                    plot_gantt_df["เน€เธชเธฃเนเธเนเธชเธ”เธ"] = pd.to_datetime(plot_gantt_df["เน€เธงเธฅเธฒเน€เธชเธฃเนเธ"]).dt.strftime("%d/%m/%Y %H:%M เธ.")

                    color_target = "เนเธเธเธเธฒเธ" if color_by_option == "เนเธเธเธเธฒเธ (Plan Code)" else "เธเธดเธเธเธฃเธฃเธก"
                    distinct_plans = list(plot_gantt_df["เนเธเธเธเธฒเธ"].unique())
                    palette = px.colors.qualitative.Bold
                    plan_color_map = {p_name: palette[i % len(palette)] for i, p_name in enumerate(distinct_plans)}

                    fig = px.timeline(
                        plot_gantt_df,
                        x_start="เน€เธงเธฅเธฒเน€เธฃเธดเนเธก",
                        x_end="เน€เธงเธฅเธฒเน€เธชเธฃเนเธ",
                        y="เน€เธเธฃเธทเนเธญเธเธเธฑเธเธฃ",
                        color=color_target,
                        text="เธเนเธญเธเธงเธฒเธกเธเธเนเธ—เนเธเธเธฃเธฒเธ",
                        custom_data=["เนเธเธเธเธฒเธ", "เธเธทเนเธญ Drawing.", "เธเธณเธเธงเธ", "เธเธฑเนเธเธ•เธญเธ (Step)", "เธงเธฑเธชเธ”เธธ", "เน€เธฃเธดเนเธกเนเธชเธ”เธ", "เน€เธชเธฃเนเธเนเธชเธ”เธ", "เธฃเธฐเธขเธฐเน€เธงเธฅเธฒ"],
                        category_orders={"เน€เธเธฃเธทเนเธญเธเธเธฑเธเธฃ": display_machines},
                        color_discrete_map=plan_color_map if color_target == "เนเธเธเธเธฒเธ" else {
                            "โ๏ธ เธเธฒเธเธเธเธ•เธด": "#0284C7",
                            "๐”ด เธเธฒเธเธ”เนเธงเธ": "#EF4444"
                        }
                    )
                    
                    fig.update_traces(
                        textposition="inside",
                        insidetextanchor="middle",
                        marker_line_color="#FFFFFF",
                        marker_line_width=1.2,
                        hovertemplate="""
                        <b>๐“ เนเธเธเธเธฒเธ: %{customdata[0]}</b> | %{customdata[1]}<br>
                        โ๏ธ <b>เธเธฑเนเธเธ•เธญเธ:</b> %{customdata[3]} | ๐”ข <b>เธเธณเธเธงเธ:</b> %{customdata[2]} เธเธดเนเธ (%{customdata[4]})<br>
                        โฑ๏ธ <b>เน€เธฃเธดเนเธก:</b> %{customdata[5]}<br>
                        ๐ <b>เน€เธชเธฃเนเธ:</b> %{customdata[6]} (เธฃเธงเธก %{customdata[7]})
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
                        xaxis_title="เธงเธฑเธเนเธฅเธฐเน€เธงเธฅเธฒเธ—เธณเธเธฒเธ",
                        yaxis_title="เน€เธเธฃเธทเนเธญเธเธเธฑเธเธฃ / เนเธเธเธ",
                        uniformtext_minsize=8,
                        uniformtext_mode='hide',
                        plot_bgcolor="#FFFFFF",
                        paper_bgcolor="#FFFFFF",
                        margin=dict(l=40, r=40, t=30, b=30),
                        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
                    )
                    st.plotly_chart(fig, use_container_width=True)
                else:
                    st.warning("โ ๏ธ เนเธกเนเธกเธตเธเธดเธงเธเธฒเธเนเธเธเธฅเธธเนเธกเธชเธ–เธฒเธเธตเธ—เธตเนเน€เธฅเธทเธญเธเธเธตเน")

                st.markdown("""
                <div class="schedule-info-box">
                    <div class="schedule-pill">
                        <span style="font-size:16px;">โฑ๏ธ</span>
                        <span><b>เธเธฑเธเธ—เธฃเน โ€“ เธจเธธเธเธฃเน:</b> 08:30 โ€“ 12:00 เธ. เนเธฅเธฐ 13:00 โ€“ 20:00 เธ. (เธเธฑเธเน€เธขเนเธ 17:00 โ€“ 17:30 เธ.)</span>
                    </div>
                    <div class="schedule-pill">
                        <span style="font-size:16px;">โฑ๏ธ</span>
                        <span><b>เธงเธฑเธเน€เธชเธฒเธฃเน:</b> 08:30 โ€“ 12:00 เธ. เนเธฅเธฐ 13:00 โ€“ 17:00 เธ. (7.17 เธเธก./เธงเธฑเธ)</span>
                    </div>
                    <div class="schedule-pill">
                        <span style="font-size:16px;">โ•</span>
                        <span style="color:#D97706;"><b>เน€เธเธฃเธเน€เธเนเธฒ/เธเนเธฒเธข (เธ.-เธช.):</b> 10:00 โ€“ 10:10 เธ. เนเธฅเธฐ 15:00 โ€“ 15:10 เธ.</span>
                    </div>
                    <div class="schedule-pill">
                        <span style="font-size:16px;">๐ฑ</span>
                        <span style="color:#D97706;"><b>เธเธฑเธเน€เธ—เธตเนเธขเธ:</b> 12:00 โ€“ 13:00 เธ.</span>
                    </div>
                    <div class="schedule-pill">
                        <span style="color:#DC2626;"><b>เธงเธฑเธเธญเธฒเธ—เธดเธ•เธขเน:</b> เธซเธขเธธเธ”เธ—เธณเธเธฒเธฃ</span>
                    </div>
                </div>
                """, unsafe_allow_html=True)

                st.divider()
            else:
                st.info("โน๏ธ เธขเธฑเธเนเธกเนเธกเธตเธเนเธญเธกเธนเธฅเธเธดเธงเธเธฒเธเธชเธณเธซเธฃเธฑเธเนเธชเธ”เธเธเธฑเธเน€เธงเธฅเธฒ Gantt Chart")

            # =====================================================
            # 4. เธญเธฑเธ•เธฃเธฒเธเธฒเธฃเนเธเนเธเธฒเธเน€เธเธฃเธทเนเธญเธเธเธฑเธเธฃ (% Machine Utilization)
            # =====================================================
            st.subheader("๐“ เธญเธฑเธ•เธฃเธฒเธเธฒเธฃเนเธเนเธเธฒเธเน€เธเธฃเธทเนเธญเธเธเธฑเธเธฃเนเธฅเธฐเนเธเธเธเธเธฅเธดเธ• (% Utilization)")
            
            m_busy_map = {m: 0.0 for m in MACHINE_LIST}
            for _, r_u in active_jobs_editor_df.iterrows():
                m_name = str(r_u.get("เน€เธฅเธทเธญเธเน€เธเธฃเธทเนเธญเธเธเธฑเธเธฃ", ""))
                tot_h = safe_float(r_u.get("เธฃเธงเธก (เธเธก.)"), 0.0)
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
                    "เน€เธเธฃเธทเนเธญเธเธเธฑเธเธฃ": m,
                    "เธเธฑเนเธงเนเธกเธเธ—เธณเธเธฒเธ (เธเธก.)": round(busy, 2),
                    "เธญเธฑเธ•เธฃเธฒเธเธฒเธฃเนเธเนเธเธฒเธ (%)": round(util_pct, 1),
                    "เธเนเธญเธเธงเธฒเธกเนเธชเธ”เธ": f"{util_pct:.1f}% ({busy:.2f} เธเธก.)"
                })
            df_util = pd.DataFrame(util_list)

            fig_bar = px.bar(
                df_util,
                x="เธญเธฑเธ•เธฃเธฒเธเธฒเธฃเนเธเนเธเธฒเธ (%)",
                y="เน€เธเธฃเธทเนเธญเธเธเธฑเธเธฃ",
                orientation="h",
                color="เธญเธฑเธ•เธฃเธฒเธเธฒเธฃเนเธเนเธเธฒเธ (%)",
                color_continuous_scale=[[0, "#E0F2FE"], [0.4, "#38BDF8"], [0.8, "#0284C7"], [1, "#0369A1"]],
                text="เธเนเธญเธเธงเธฒเธกเนเธชเธ”เธ",
                range_x=[0, 105],
                category_orders={"เน€เธเธฃเธทเนเธญเธเธเธฑเธเธฃ": MACHINE_LIST}
            )
            fig_bar.update_yaxes(autorange="reversed", type="category", categoryorder="array", categoryarray=MACHINE_LIST)
            fig_bar.update_traces(marker_line_color="#0F172A", marker_line_width=1.2, textposition="outside", cliponaxis=False)
            fig_bar.update_layout(
                height=max(600, len(MACHINE_LIST) * 30),
                margin=dict(l=40, r=40, t=10, b=30),
                xaxis_title="เธญเธฑเธ•เธฃเธฒเธเธฒเธฃเนเธเนเธเธฒเธ (%)",
                yaxis_title="เน€เธเธฃเธทเนเธญเธเธเธฑเธเธฃ / เนเธเธเธ",
                xaxis=dict(showgrid=True, gridcolor="#F1F5F9"),
                coloraxis_showscale=False,
                plot_bgcolor="#FFFFFF",
                paper_bgcolor="#FFFFFF"
            )
            fig_bar.add_vline(x=85, line_dash="dash", line_color="#EF4444", line_width=2, annotation_text="เน€เธเนเธฒเธซเธกเธฒเธข (85%)", annotation_position="top right", annotation_font_color="#EF4444")
            st.plotly_chart(fig_bar, use_container_width=True)

            st.divider()

            # =====================================================
            # 5. เธ•เธฒเธฃเธฒเธเธชเธฃเธธเธเธเธฃเธฐเธงเธฑเธ•เธดเธเธฒเธเธ—เธตเนเน€เธชเธฃเนเธเธชเธดเนเธ (Finished Production History)
            # =====================================================
            st.subheader("โ… เธ•เธฒเธฃเธฒเธเธชเธฃเธธเธเธเธฃเธฐเธงเธฑเธ•เธดเธเธฒเธเธ—เธตเนเธเธฅเธดเธ•เน€เธชเธฃเนเธเธชเธดเนเธ (Finished History - เน€เธฃเธดเนเธกเธเธฃเธดเธ / เน€เธชเธฃเนเธเธเธฃเธดเธ)")

            if not finished_jobs_df.empty:
                fin_display_df = finished_jobs_df.copy()
                fin_display_df["_sort_fin"] = fin_display_df["เน€เธชเธฃเนเธเธเธฃเธดเธ"].apply(parse_flexible_datetime)
                fin_display_df = fin_display_df.sort_values(by="_sort_fin", ascending=False).drop(columns=["_sort_fin"]).reset_index(drop=True)

                act_hrs_list = []
                for _, r in fin_display_df.iterrows():
                    st_p = parse_flexible_datetime(r.get("เน€เธฃเธดเนเธกเธเธฃเธดเธ"))
                    fn_p = parse_flexible_datetime(r.get("เน€เธชเธฃเนเธเธเธฃเธดเธ"))
                    if st_p and fn_p:
                        act_hrs_list.append(round((fn_p - st_p).total_seconds() / 3600.0, 2))
                    else:
                        act_hrs_list.append(round((safe_float(r.get("Setup (เธ.)")) + safe_float(r.get("Basic (เธ.)")) + safe_float(r.get("เนเธเธฃเนเธเธฃเธก (เธ.)"))) / 60.0, 2))

                fin_display_df["เน€เธงเธฅเธฒเธเธฃเธดเธ (เธเธก.)"] = act_hrs_list
                fin_display_df["เธฅเธเธเธฃเธฐเธงเธฑเธ•เธด"] = st.session_state.finish_select_all

                fin_tool1, fin_tool2 = st.columns([3, 4])
                with fin_tool1:
                    if is_admin:
                        fb_c1, fb_c2 = st.columns(2)
                        with fb_c1:
                            if st.button("โ… เน€เธฅเธทเธญเธเธซเธกเธ” (เน€เธชเธฃเนเธ)", key="btn_sel_all_fin", use_container_width=True):
                                st.session_state.finish_select_all = True
                                st.rerun()
                        with fb_c2:
                            if st.button("โ เธขเธเน€เธฅเธดเธ (เน€เธชเธฃเนเธ)", key="btn_unsel_all_fin", use_container_width=True):
                                st.session_state.finish_select_all = False
                                st.rerun()
                with fin_tool2:
                    search_fin = st.text_input("๐” เธเนเธเธซเธฒเนเธเธเธฃเธฐเธงเธฑเธ•เธดเธเธฒเธเน€เธชเธฃเนเธเธชเธดเนเธ (เนเธเธเธเธฒเธ, Drawing, เน€เธเธฃเธทเนเธญเธเธเธฑเธเธฃ):", key="search_finished_history_input")

                if search_fin.strip() != "":
                    q_f = search_fin.strip().lower()
                    fin_display_df = fin_display_df[
                        fin_display_df["เนเธเธเธเธฒเธ"].astype(str).str.lower().str.contains(q_f) |
                        fin_display_df["เธเธทเนเธญ Drawing."].astype(str).str.lower().str.contains(q_f) |
                        fin_display_df["เน€เธฅเธทเธญเธเน€เธเธฃเธทเนเธญเธเธเธฑเธเธฃ"].astype(str).str.lower().str.contains(q_f)
                    ]

                if is_admin:
                    edited_fin = st.data_editor(
                        fin_display_df,
                        key="editor_finished_jobs_history",
                        column_order=[
                            "เนเธเธเธเธฒเธ", "เธเธทเนเธญ Drawing.", "เธเธณเธเธงเธ", "เธงเธฑเธชเธ”เธธ", "เธเธฑเนเธเธ•เธญเธ (Step)",
                            "เน€เธฅเธทเธญเธเน€เธเธฃเธทเนเธญเธเธเธฑเธเธฃ", "เธงเธฑเธ-เน€เธงเธฅเธฒเธเธถเนเธเธเธฒเธ", "เน€เธฃเธดเนเธกเธเธฃเธดเธ", "เน€เธชเธฃเนเธเธเธฃเธดเธ",
                            "Setup (เธ.)", "Basic (เธ.)", "เนเธเธฃเนเธเธฃเธก (เธ.)", "เธฃเธงเธก (เธเธก.)", "เน€เธงเธฅเธฒเธเธฃเธดเธ (เธเธก.)", "เธชเธ–เธฒเธเธฐเธเธฒเธ", "เธฅเธเธเธฃเธฐเธงเธฑเธ•เธด"
                        ],
                        column_config={
                            "ID": None,
                            "เนเธเธเธเธฒเธ": st.column_config.TextColumn("เนเธเธเธเธฒเธ", width=85, disabled=True),
                            "เธเธทเนเธญ Drawing.": st.column_config.TextColumn("เธเธทเนเธญ Drawing.", width=180, disabled=True),
                            "เธเธณเธเธงเธ": st.column_config.NumberColumn("เธเธณเธเธงเธ", width=65, format="%d", disabled=True),
                            "เธงเธฑเธชเธ”เธธ": st.column_config.TextColumn("เธงเธฑเธชเธ”เธธ", width=75, disabled=True),
                            "เธเธฑเนเธเธ•เธญเธ (Step)": st.column_config.TextColumn("เธเธฑเนเธเธ•เธญเธ (Step)", width=120, disabled=True),
                            "เน€เธฅเธทเธญเธเน€เธเธฃเธทเนเธญเธเธเธฑเธเธฃ": st.column_config.TextColumn("เน€เธเธฃเธทเนเธญเธเธเธฑเธเธฃ", width=140, disabled=True),
                            "เธงเธฑเธ-เน€เธงเธฅเธฒเธเธถเนเธเธเธฒเธ": st.column_config.DatetimeColumn("เธเธณเธซเธเธ”เธเธถเนเธเธเธฒเธ (เนเธเธ)", width=145, format="DD/MM/YYYY HH:mm", disabled=True),
                            "เน€เธฃเธดเนเธกเธเธฃเธดเธ": st.column_config.DatetimeColumn("เน€เธฃเธดเนเธกเธเธถเนเธเธเธฒเธเธเธฃเธดเธ", width=145, format="DD/MM/YYYY HH:mm"),
                            "เน€เธชเธฃเนเธเธเธฃเธดเธ": st.column_config.DatetimeColumn("เน€เธชเธฃเนเธเธชเธดเนเธเธเธฃเธดเธ", width=145, format="DD/MM/YYYY HH:mm"),
                            "Setup (เธ.)": st.column_config.NumberColumn("Setup (เธ.)", width=80, format="%d", disabled=True),
                            "Basic (เธ.)": st.column_config.NumberColumn("Basic (เธ.)", width=80, format="%d", disabled=True),
                            "เนเธเธฃเนเธเธฃเธก (เธ.)": st.column_config.NumberColumn("เนเธเธฃเนเธเธฃเธก (เธ.)", width=95, format="%d", disabled=True),
                            "เธฃเธงเธก (เธเธก.)": st.column_config.NumberColumn("เนเธเธ (เธเธก.)", width=85, format="%.2f", disabled=True),
                            "เน€เธงเธฅเธฒเธเธฃเธดเธ (เธเธก.)": st.column_config.NumberColumn("เธเธฃเธดเธ (เธเธก.)", width=85, format="%.2f", disabled=True),
                            "เธชเธ–เธฒเธเธฐเธเธฒเธ": st.column_config.TextColumn("เธชเธ–เธฒเธเธฐ", width=120, disabled=True),
                            "เธฅเธเธเธฃเธฐเธงเธฑเธ•เธด": st.column_config.CheckboxColumn("๐—‘๏ธ", width=55, default=False),
                        },
                        hide_index=True,
                        use_container_width=True
                    )

                    fin_to_del = edited_fin[edited_fin["เธฅเธเธเธฃเธฐเธงเธฑเธ•เธด"] == True]
                    del_fin_count = len(fin_to_del)
                    if st.button(f"๐—‘๏ธ เธฅเธเธฃเธฒเธขเธเธฒเธฃเธเธฃเธฐเธงเธฑเธ•เธดเธเธฒเธเน€เธชเธฃเนเธเธชเธดเนเธ ({del_fin_count} เธฃเธฒเธขเธเธฒเธฃ)", key="btn_del_finished_records", type="secondary", disabled=(del_fin_count == 0)):
                        for _, r in fin_to_del.iterrows():
                            if pd.notna(r.get("ID")):
                                delete_supabase_job(int(float(r["ID"])))
                        st.session_state.finish_select_all = False
                        st.cache_data.clear()
                        st.toast("เธฅเธเธเธฃเธฐเธงเธฑเธ•เธดเธเธฒเธเน€เธฃเธตเธขเธเธฃเนเธญเธขเนเธฅเนเธง!", icon="๐—‘๏ธ")
                        st.rerun()
                else:
                    st.dataframe(
                        fin_display_df[[c for c in fin_display_df.columns if c not in ["ID", "เธฅเธเธเธฃเธฐเธงเธฑเธ•เธด"]]],
                        column_config={
                            "เนเธเธเธเธฒเธ": st.column_config.TextColumn("เนเธเธเธเธฒเธ", width=85),
                            "เธเธทเนเธญ Drawing.": st.column_config.TextColumn("เธเธทเนเธญ Drawing.", width=180),
                            "เธเธณเธเธงเธ": st.column_config.NumberColumn("เธเธณเธเธงเธ", width=65, format="%d"),
                            "เธงเธฑเธชเธ”เธธ": st.column_config.TextColumn("เธงเธฑเธชเธ”เธธ", width=75),
                            "เธเธฑเนเธเธ•เธญเธ (Step)": st.column_config.TextColumn("เธเธฑเนเธเธ•เธญเธ (Step)", width=120),
                            "เน€เธฅเธทเธญเธเน€เธเธฃเธทเนเธญเธเธเธฑเธเธฃ": st.column_config.TextColumn("เน€เธเธฃเธทเนเธญเธเธเธฑเธเธฃ", width=140),
                            "เธงเธฑเธ-เน€เธงเธฅเธฒเธเธถเนเธเธเธฒเธ": st.column_config.DatetimeColumn("เธเธณเธซเธเธ”เธเธถเนเธเธเธฒเธ (เนเธเธ)", width=145, format="DD/MM/YYYY HH:mm"),
                            "เน€เธฃเธดเนเธกเธเธฃเธดเธ": st.column_config.DatetimeColumn("เน€เธฃเธดเนเธกเธเธถเนเธเธเธฒเธเธเธฃเธดเธ", width=145, format="DD/MM/YYYY HH:mm"),
                            "เน€เธชเธฃเนเธเธเธฃเธดเธ": st.column_config.DatetimeColumn("เน€เธชเธฃเนเธเธชเธดเนเธเธเธฃเธดเธ", width=145, format="DD/MM/YYYY HH:mm"),
                            "เธฃเธงเธก (เธเธก.)": st.column_config.NumberColumn("เนเธเธ (เธเธก.)", width=85, format="%.2f"),
                            "เน€เธงเธฅเธฒเธเธฃเธดเธ (เธเธก.)": st.column_config.NumberColumn("เธเธฃเธดเธ (เธเธก.)", width=85, format="%.2f"),
                            "เธชเธ–เธฒเธเธฐเธเธฒเธ": st.column_config.TextColumn("เธชเธ–เธฒเธเธฐ", width=120),
                        },
                        hide_index=True,
                        use_container_width=True
                    )
            else:
                st.info("โน๏ธ เธขเธฑเธเนเธกเนเธกเธตเธฃเธฒเธขเธเธฒเธฃเธ—เธตเนเธเธถเนเธเธชเธ–เธฒเธเธฐ 'โ… เน€เธชเธฃเนเธเธชเธดเนเธเนเธฅเนเธง'")

            st.divider()

            # =====================================================
            # 6. เธ•เธฒเธฃเธฒเธเธเธณเธเธงเธ“เธกเธนเธฅเธเนเธฒเนเธฅเธฐเธ•เนเธเธ—เธธเธเธเนเธฒเน€เธเธฃเธทเนเธญเธเธเธฑเธเธฃ (Machining Cost Calculation)
            # =====================================================
            st.subheader("๐’ฐ เธ•เธฒเธฃเธฒเธเธเธณเธเธงเธ“เธกเธนเธฅเธเนเธฒเนเธฅเธฐเธ•เนเธเธ—เธธเธเธเนเธฒเน€เธเธฃเธทเนเธญเธเธเธฑเธเธฃ (Machining Cost Calculation)")

            current_rates_df = pd.DataFrame([
                {"เน€เธเธฃเธทเนเธญเธเธเธฑเธเธฃ": m, "เน€เธฃเธ•เธฃเธฒเธเธฒ (เธเธฒเธ—/เธเธก.)": DEFAULT_RATES.get(m, 500)}
                for m in MACHINE_LIST
            ])
            
            if "machine_rates" not in st.session_state or len(st.session_state.machine_rates) != len(MACHINE_LIST):
                st.session_state.machine_rates = current_rates_df
            else:
                existing_map = dict(zip(st.session_state.machine_rates["เน€เธเธฃเธทเนเธญเธเธเธฑเธเธฃ"], st.session_state.machine_rates["เน€เธฃเธ•เธฃเธฒเธเธฒ (เธเธฒเธ—/เธเธก.)"]))
                for m in MACHINE_LIST:
                    if m not in existing_map:
                        existing_map[m] = DEFAULT_RATES.get(m, 500)
                st.session_state.machine_rates = pd.DataFrame([
                    {"เน€เธเธฃเธทเนเธญเธเธเธฑเธเธฃ": m, "เน€เธฃเธ•เธฃเธฒเธเธฒ (เธเธฒเธ—/เธเธก.)": existing_map[m]} for m in MACHINE_LIST
                ])

            cost_col1, cost_col2 = st.columns([1.1, 2.9])

            with cost_col1:
                st.markdown("**โ๏ธ เธ•เธฑเนเธเธเนเธฒเน€เธฃเธ•เธฃเธฒเธเธฒเธเนเธฒเน€เธเธฃเธทเนเธญเธเธเธฑเธเธฃ (เธเธฒเธ—/เธเธก.)**")
                if is_admin:
                    edited_rates = st.data_editor(
                        st.session_state.machine_rates,
                        key="editor_machine_rates_full_22_v14",
                        column_config={
                            "เน€เธเธฃเธทเนเธญเธเธเธฑเธเธฃ": st.column_config.TextColumn("เน€เธเธฃเธทเนเธญเธเธเธฑเธเธฃ / เนเธเธเธ", disabled=True),
                            "เน€เธฃเธ•เธฃเธฒเธเธฒ (เธเธฒเธ—/เธเธก.)": st.column_config.NumberColumn("เน€เธฃเธ•เธฃเธฒเธเธฒ (เธเธฒเธ—/เธเธก.)", min_value=0, max_value=50000, step=50, format="%d เธฟ", required=True)
                        },
                        use_container_width=True,
                        hide_index=True
                    )
                    st.session_state.machine_rates = edited_rates
                    rate_map = dict(zip(edited_rates["เน€เธเธฃเธทเนเธญเธเธเธฑเธเธฃ"], edited_rates["เน€เธฃเธ•เธฃเธฒเธเธฒ (เธเธฒเธ—/เธเธก.)"]))
                else:
                    st.dataframe(
                        st.session_state.machine_rates,
                        column_config={
                            "เน€เธเธฃเธทเนเธญเธเธเธฑเธเธฃ": st.column_config.TextColumn("เน€เธเธฃเธทเนเธญเธเธเธฑเธเธฃ / เนเธเธเธ"),
                            "เน€เธฃเธ•เธฃเธฒเธเธฒ (เธเธฒเธ—/เธเธก.)": st.column_config.NumberColumn("เน€เธฃเธ•เธฃเธฒเธเธฒ (เธเธฒเธ—/เธเธก.)", format="%d เธฟ")
                        },
                        use_container_width=True,
                        hide_index=True
                    )
                    rate_map = dict(zip(st.session_state.machine_rates["เน€เธเธฃเธทเนเธญเธเธเธฑเธเธฃ"], st.session_state.machine_rates["เน€เธฃเธ•เธฃเธฒเธเธฒ (เธเธฒเธ—/เธเธก.)"]))

            with cost_col2:
                if not finished_jobs_df.empty:
                    cost_df = finished_jobs_df.copy()
                    cost_df["เธฃเธงเธก (เธเธก.)"] = ((cost_df["Setup (เธ.)"] + cost_df["Basic (เธ.)"] + cost_df["เนเธเธฃเนเธเธฃเธก (เธ.)"]) / 60.0).round(2)
                    cost_df["เน€เธฃเธ•เธฃเธฒเธเธฒ (เธเธฒเธ—/เธเธก.)"] = cost_df["เน€เธฅเธทเธญเธเน€เธเธฃเธทเนเธญเธเธเธฑเธเธฃ"].map(rate_map).fillna(500)
                    cost_df["เธกเธนเธฅเธเนเธฒเธฃเธงเธก (เธเธฒเธ—)"] = cost_df["เธฃเธงเธก (เธเธก.)"] * cost_df["เน€เธฃเธ•เธฃเธฒเธเธฒ (เธเธฒเธ—/เธเธก.)"]
                    
                    total_finished_cost = cost_df["เธกเธนเธฅเธเนเธฒเธฃเธงเธก (เธเธฒเธ—)"].sum()
                    total_finished_hrs = cost_df["เธฃเธงเธก (เธเธก.)"].sum()
                    
                    st.markdown(f"**๐“ เธฃเธฒเธขเธเธฒเธฃเธชเธฃเธธเธเธกเธนเธฅเธเนเธฒเธเธฒเธเธ—เธตเนเน€เธชเธฃเนเธเธชเธดเนเธ (เธฃเธงเธกเธ—เธฑเนเธเธซเธกเธ”: :green[{total_finished_cost:,.2f} เธเธฒเธ—] / {total_finished_hrs:.2f} เธเธก.)**")
                    st.dataframe(
                        cost_df.sort_values(by="เนเธเธเธเธฒเธ", ascending=True)[["เนเธเธเธเธฒเธ", "เธเธทเนเธญ Drawing.", "เธเธณเธเธงเธ", "เธเธฑเนเธเธ•เธญเธ (Step)", "เน€เธฅเธทเธญเธเน€เธเธฃเธทเนเธญเธเธเธฑเธเธฃ", "Setup (เธ.)", "Basic (เธ.)", "เนเธเธฃเนเธเธฃเธก (เธ.)", "เธฃเธงเธก (เธเธก.)", "เน€เธฃเธ•เธฃเธฒเธเธฒ (เธเธฒเธ—/เธเธก.)", "เธกเธนเธฅเธเนเธฒเธฃเธงเธก (เธเธฒเธ—)"]],
                        column_config={
                            "เนเธเธเธเธฒเธ": st.column_config.TextColumn("เนเธเธเธเธฒเธ", width=85),
                            "เธเธทเนเธญ Drawing.": st.column_config.TextColumn("เธเธทเนเธญ Drawing.", width=180),
                            "เธเธณเธเธงเธ": st.column_config.NumberColumn("เธเธณเธเธงเธ", width=65, format="%d"),
                            "เธเธฑเนเธเธ•เธญเธ (Step)": st.column_config.TextColumn("เธเธฑเนเธเธ•เธญเธ", width=120),
                            "เน€เธฅเธทเธญเธเน€เธเธฃเธทเนเธญเธเธเธฑเธเธฃ": st.column_config.TextColumn("เน€เธเธฃเธทเนเธญเธเธเธฑเธเธฃ / เนเธเธเธ", width=140),
                            "Setup (เธ.)": st.column_config.NumberColumn("Setup (เธ.)", width=85, format="%d"),
                            "Basic (เธ.)": st.column_config.NumberColumn("Basic (เธ.)", width=85, format="%d"),
                            "เนเธเธฃเนเธเธฃเธก (เธ.)": st.column_config.NumberColumn("เนเธเธฃเนเธเธฃเธก (เธ.)", width=95, format="%d"),
                            "เธฃเธงเธก (เธเธก.)": st.column_config.NumberColumn("เธฃเธงเธก (เธเธก.)", width=85, format="%.2f"),
                            "เน€เธฃเธ•เธฃเธฒเธเธฒ (เธเธฒเธ—/เธเธก.)": st.column_config.NumberColumn("เน€เธฃเธ•เธฃเธฒเธเธฒ", width=110, format="%d เธฟ"),
                            "เธกเธนเธฅเธเนเธฒเธฃเธงเธก (เธเธฒเธ—)": st.column_config.NumberColumn("เธฃเธงเธกเน€เธเนเธเน€เธเธดเธ", width=130, format="%.2f เธฟ"),
                        },
                        use_container_width=True,
                        hide_index=True
                    )
                else:
                    st.info("โน๏ธ เธขเธฑเธเนเธกเนเธกเธตเธฃเธฒเธขเธเธฒเธฃเธ—เธตเนเธเธถเนเธเธชเธ–เธฒเธเธฐ 'โ… เน€เธชเธฃเนเธเธชเธดเนเธเนเธฅเนเธง' เธเธถเธเธขเธฑเธเนเธกเนเธกเธตเธเธฒเธฃเธเธณเธเธงเธ“เธกเธนเธฅเธเนเธฒเธ•เนเธเธ—เธธเธ")

# ---------------------------------------------------------
# VIEW 3: เธงเธดเน€เธเธฃเธฒเธฐเธซเนเธเธฃเธฐเธชเธดเธ—เธเธดเธ เธฒเธเธฃเธฒเธข Drawing
# ---------------------------------------------------------
elif st.session_state.current_view == "๐“ เธงเธดเน€เธเธฃเธฒเธฐเธซเนเธเธฃเธฐเธชเธดเธ—เธเธดเธ เธฒเธเธฃเธฒเธข Drawing":
    st.subheader("๐“ เธงเธดเน€เธเธฃเธฒเธฐเธซเนเนเธฅเธฐเน€เธเธฃเธตเธขเธเน€เธ—เธตเธขเธเน€เธงเธฅเธฒเธ—เธณเธเธฒเธเธเธฃเธดเธเธฃเธฒเธข Drawing (Drawing Performance Analysis)")
    
    df_db = fetch_jobs_from_supabase()

    current_now = get_bangkok_now()
    month_names = ["เธกเธเธฃเธฒเธเธก (1)", "เธเธธเธกเธ เธฒเธเธฑเธเธเน (2)", "เธกเธตเธเธฒเธเธก (3)", "เน€เธกเธฉเธฒเธขเธ (4)", "เธเธคเธฉเธ เธฒเธเธก (5)", "เธกเธดเธ–เธธเธเธฒเธขเธ (6)", "เธเธฃเธเธเธฒเธเธก (7)", "เธชเธดเธเธซเธฒเธเธก (8)", "เธเธฑเธเธขเธฒเธขเธ (9)", "เธ•เธธเธฅเธฒเธเธก (10)", "เธเธคเธจเธเธดเธเธฒเธขเธ (11)", "เธเธฑเธเธงเธฒเธเธก (12)"]

    m_col1, m_col2, m_col3 = st.columns([2, 2, 3])
    with m_col1:
        sel_dw_month = st.selectbox("๐“… เน€เธฅเธทเธญเธเน€เธ”เธทเธญเธเธ—เธตเนเธ•เนเธญเธเธเธฒเธฃเธงเธดเน€เธเธฃเธฒเธฐเธซเน:", range(1, 13), index=current_now.month - 1, format_func=lambda x: month_names[x-1], key="dw_month_sel")
    with m_col2:
        sel_dw_year = st.selectbox("๐“ เน€เธฅเธทเธญเธเธเธต (เธ.เธจ.):", [current_now.year - 1, current_now.year, current_now.year + 1], index=1, key="dw_year_sel")
    with m_col3:
        sel_dw_limit = st.selectbox("๐ฏ เธเธฒเธฃเนเธชเธ”เธเธเธฅเธเธฃเธฒเธเนเธ—เนเธเธเธนเน:", ["๐ เนเธชเธ”เธเธ—เธฑเนเธเธซเธกเธ”เนเธเน€เธ”เธทเธญเธเธเธตเน", "๐”ด Top 10 เธเนเธฒเธเธงเนเธฒเนเธเธเธชเธนเธเธชเธธเธ” (Critical Delays)", "๐ข Top 10 เน€เธฃเนเธงเธเธงเนเธฒเนเธเธเธชเธนเธเธชเธธเธ” (High Efficiency)"])

    if not df_db.empty:
        finished_all = df_db[df_db["เธชเธ–เธฒเธเธฐเธเธฒเธ"].isin(["๐ฉ เน€เธชเธฃเนเธเธชเธดเนเธเนเธฅเนเธง", "โ… เน€เธชเธฃเนเธเธชเธดเนเธเนเธฅเนเธง"])].copy()
        
        if not finished_all.empty:
            finished_all["เน€เธชเธฃเนเธเธเธฃเธดเธ_DT"] = pd.to_datetime(finished_all["เน€เธชเธฃเนเธเธเธฃเธดเธ"], errors='coerce')
            finished_all["เธงเธฑเธเธเธถเนเธเธเธฒเธ_DT"] = pd.to_datetime(finished_all["เธงเธฑเธ-เน€เธงเธฅเธฒเธเธถเนเธเธเธฒเธ"], errors='coerce')
            finished_all["Target_Date"] = finished_all["เน€เธชเธฃเนเธเธเธฃเธดเธ_DT"].fillna(finished_all["เธงเธฑเธเธเธถเนเธเธเธฒเธ_DT"])
            
            monthly_dw_jobs = finished_all[
                (finished_all["Target_Date"].dt.month == sel_dw_month) &
                (finished_all["Target_Date"].dt.year == sel_dw_year)
            ].copy()

            if not monthly_dw_jobs.empty:
                monthly_dw_jobs["Setup (เธ.)"] = pd.to_numeric(monthly_dw_jobs["Setup (เธ.)"], errors='coerce').fillna(10.0)
                monthly_dw_jobs["Basic (เธ.)"] = pd.to_numeric(monthly_dw_jobs["Basic (เธ.)"], errors='coerce').fillna(0.0)
                monthly_dw_jobs["เนเธเธฃเนเธเธฃเธก (เธ.)"] = pd.to_numeric(monthly_dw_jobs["เนเธเธฃเนเธเธฃเธก (เธ.)"], errors='coerce').fillna(0.0)
                monthly_dw_jobs["เน€เธงเธฅเธฒเนเธเธ (เธเธก.)"] = ((monthly_dw_jobs["Setup (เธ.)"] + monthly_dw_jobs["Basic (เธ.)"] + monthly_dw_jobs["เนเธเธฃเนเธเธฃเธก (เธ.)"]) / 60.0).round(2)
                
                actual_hrs_list = []
                for _, r in monthly_dw_jobs.iterrows():
                    s_real, f_real = r.get("เน€เธฃเธดเนเธกเธเธฃเธดเธ"), r.get("เน€เธชเธฃเนเธเธเธฃเธดเธ")
                    act_st = parse_flexible_datetime(s_real)
                    act_fn = parse_flexible_datetime(f_real)
                    if act_st is not None and act_fn is not None:
                        diff_sec = (act_fn - act_st).total_seconds()
                        actual_hrs_list.append(round(diff_sec / 3600.0, 2))
                    else:
                        actual_hrs_list.append(r["เน€เธงเธฅเธฒเนเธเธ (เธเธก.)"])
                monthly_dw_jobs["เน€เธงเธฅเธฒเธเธฃเธดเธ (เธเธก.)"] = actual_hrs_list

                drawing_agg = []
                for (p_c, d_c), g_data in monthly_dw_jobs.groupby(["เนเธเธเธเธฒเธ", "เธเธทเนเธญ Drawing."]):
                    d_plan = g_data["เน€เธงเธฅเธฒเนเธเธ (เธเธก.)"].sum()
                    d_act = g_data["เน€เธงเธฅเธฒเธเธฃเธดเธ (เธเธก.)"].sum()
                    d_qty = int(g_data.iloc[0].get("เธเธณเธเธงเธ", 1)) or 1
                    d_mat = g_data.iloc[0].get("เธงเธฑเธชเธ”เธธ", "-")
                    d_diff = round(d_act - d_plan, 2)
                    d_diff_mins = round(d_diff * 60)
                    
                    d_plan_per_pc = round(d_plan / d_qty, 2)
                    d_act_per_pc = round(d_act / d_qty, 2)
                    accuracy_pct = round((d_plan / d_act * 100), 1) if d_act > 0 else 100.0

                    machines_used = g_data["เน€เธฅเธทเธญเธเน€เธเธฃเธทเนเธญเธเธเธฑเธเธฃ"].dropna().unique()
                    machines_str = ", ".join([str(m) for m in machines_used if str(m).strip() != ""])
                    if not machines_str:
                        machines_str = "-"
                    
                    pct_diff = ((d_act - d_plan) / d_plan * 100) if d_plan > 0 else 0
                    if pct_diff < -5:
                        cat_status = "FAST"
                        eval_str = f"๐ข เน€เธฃเนเธงเธเธถเนเธ {abs(d_diff_mins)} เธเธฒเธ—เธต"
                    elif -5 <= pct_diff <= 5:
                        cat_status = "ON_TARGET"
                        eval_str = f"๐ก เธ•เธฃเธเธ•เธฒเธกเนเธเธ (ยฑ5%)"
                    else:
                        cat_status = "LATE"
                        eval_str = f"๐”ด เธเนเธฒเธเธงเนเธฒเนเธเธ +{d_diff_mins} เธเธฒเธ—เธต"

                    drawing_agg.append({
                        "เนเธเธเธเธฒเธ": p_c,
                        "เธเธทเนเธญ Drawing.": d_c,
                        "เธซเธฑเธงเธเนเธญ Drawing": f"[{p_c}] {d_c} ({machines_str})",
                        "เธเธณเธเธงเธ": d_qty,
                        "เธงเธฑเธชเธ”เธธ": d_mat,
                        "เน€เธเธฃเธทเนเธญเธเธเธฑเธเธฃเธ—เธตเนเธเธฅเธดเธ•": machines_str,
                        "เธเธณเธเธงเธ Step": len(g_data),
                        "เน€เธงเธฅเธฒเนเธเธ (เธเธก.)": round(d_plan, 2),
                        "เน€เธงเธฅเธฒเธเธฃเธดเธ (เธเธก.)": round(d_act, 2),
                        "เนเธเธ/เธเธดเนเธ (เธเธก.)": d_plan_per_pc,
                        "เธเธฃเธดเธ/เธเธดเนเธ (เธเธก.)": d_act_per_pc,
                        "เธเธงเธฒเธกเนเธกเนเธเธขเธณ (%)": accuracy_pct,
                        "เธเธฅเธ•เนเธฒเธ (เธเธก.)": d_diff,
                        "เธชเธ–เธฒเธเธฐเธเธฅเธธเนเธก": cat_status,
                        "เธเธฒเธฃเธเธฃเธฐเน€เธกเธดเธ": eval_str
                    })
                df_draw_full = pd.DataFrame(drawing_agg)

                count_fast = len(df_draw_full[df_draw_full["เธชเธ–เธฒเธเธฐเธเธฅเธธเนเธก"] == "FAST"])
                count_target = len(df_draw_full[df_draw_full["เธชเธ–เธฒเธเธฐเธเธฅเธธเนเธก"] == "ON_TARGET"])
                count_late = len(df_draw_full[df_draw_full["เธชเธ–เธฒเธเธฐเธเธฅเธธเนเธก"] == "LATE"])
                total_late_hrs = df_draw_full[df_draw_full["เธเธฅเธ•เนเธฒเธ (เธเธก.)"] > 0]["เธเธฅเธ•เนเธฒเธ (เธเธก.)"].sum()

                st.markdown(f"""
                <div class="kpi-container">
                    <div class="kpi-card kpi-green">
                        <div class="kpi-title">๐ข เธเธฅเธดเธ•เน€เธฃเนเธงเธเธงเนเธฒเนเธเธ (>5%)</div>
                        <div class="kpi-value">{count_fast} <span style="font-size:15px; font-weight:600;">Drawings</span></div>
                        <div class="kpi-sub">เธเธฃเธฐเธชเธดเธ—เธเธดเธ เธฒเธเธเธฒเธฃเธ•เธฑเธ”เน€เธเธทเธญเธเธชเธนเธเธเธงเนเธฒเน€เธเธ“เธ‘เน</div>
                    </div>
                    <div class="kpi-card kpi-orange">
                        <div class="kpi-title">๐ก เธ•เธฃเธเธ•เธฒเธกเน€เธเธ“เธ‘เนเน€เธเนเธฒเธซเธกเธฒเธข (ยฑ5%)</div>
                        <div class="kpi-value">{count_target} <span style="font-size:15px; font-weight:600;">Drawings</span></div>
                        <div class="kpi-sub">เธเธฒเธฃเธเธฃเธฐเธกเธฒเธ“เน€เธงเธฅเธฒเนเธกเนเธเธขเธณเธกเธฒเธ•เธฃเธเธฒเธ</div>
                    </div>
                    <div class="kpi-card kpi-red">
                        <div class="kpi-title">๐”ด เธเธฅเธดเธ•เธเนเธฒเธเธงเนเธฒเนเธเธ (>5%)</div>
                        <div class="kpi-value">{count_late} <span style="font-size:15px; font-weight:600;">Drawings</span></div>
                        <div class="kpi-sub">เธเนเธฒเธชเธฐเธชเธกเธฃเธงเธก +{total_late_hrs:.2f} เธเธก.</div>
                    </div>
                </div>
                """, unsafe_allow_html=True)

                f_col1, f_col2 = st.columns([2.5, 4])
                with f_col1:
                    plan_list = ["๐ เธ—เธธเธเนเธเธเธเธฒเธ"] + sorted(list(df_draw_full["เนเธเธเธเธฒเธ"].unique()))
                    selected_plan_filter = st.selectbox("๐” เธเธฃเธญเธเธ•เธฒเธกเธฃเธซเธฑเธชเนเธเธเธเธฒเธ (เนเธเธเธ เธนเธกเธดเธเธฃเธฒเธ):", plan_list)
                with f_col2:
                    search_dw = st.text_input("๐” เธเนเธเธซเธฒเธเธทเนเธญ Drawing เธซเธฃเธทเธญ เน€เธเธฃเธทเนเธญเธเธเธฑเธเธฃ (เนเธเธเธ เธนเธกเธดเธเธฃเธฒเธ):", placeholder="เธเธดเธกเธเนเธเธทเนเธญ Drawing เธซเธฃเธทเธญเธเธทเนเธญเน€เธเธฃเธทเนเธญเธเธเธฑเธเธฃเน€เธเธทเนเธญเธเธฃเธญเธเธเธฃเธฒเธ...")

                df_draw_filtered = df_draw_full.copy()
                if selected_plan_filter != "๐ เธ—เธธเธเนเธเธเธเธฒเธ":
                    df_draw_filtered = df_draw_filtered[df_draw_filtered["เนเธเธเธเธฒเธ"] == selected_plan_filter]
                if search_dw.strip() != "":
                    q_dw_s = search_dw.strip().lower()
                    df_draw_filtered = df_draw_filtered[
                        df_draw_filtered["เธเธทเนเธญ Drawing."].str.lower().str.contains(q_dw_s) |
                        df_draw_filtered["เน€เธเธฃเธทเนเธญเธเธเธฑเธเธฃเธ—เธตเนเธเธฅเธดเธ•"].str.lower().str.contains(q_dw_s)
                    ]

                if "Top 10 เธเนเธฒเธเธงเนเธฒเนเธเธ" in sel_dw_limit:
                    df_draw_filtered = df_draw_filtered.sort_values(by="เธเธฅเธ•เนเธฒเธ (เธเธก.)", ascending=False).head(10).sort_values(by="เน€เธงเธฅเธฒเธเธฃเธดเธ (เธเธก.)", ascending=True)
                elif "Top 10 เน€เธฃเนเธงเธเธงเนเธฒเนเธเธ" in sel_dw_limit:
                    df_draw_filtered = df_draw_filtered.sort_values(by="เธเธฅเธ•เนเธฒเธ (เธเธก.)", ascending=True).head(10).sort_values(by="เน€เธงเธฅเธฒเธเธฃเธดเธ (เธเธก.)", ascending=True)
                else:
                    df_draw_filtered = df_draw_filtered.sort_values(by="เน€เธงเธฅเธฒเธเธฃเธดเธ (เธเธก.)", ascending=True)

                if not df_draw_filtered.empty:
                    chart_h = max(420, len(df_draw_filtered) * 36)
                    fig_dw = px.bar(
                        df_draw_filtered,
                        y="เธซเธฑเธงเธเนเธญ Drawing",
                        x=["เน€เธงเธฅเธฒเนเธเธ (เธเธก.)", "เน€เธงเธฅเธฒเธเธฃเธดเธ (เธเธก.)"],
                        orientation="h",
                        barmode="group",
                        title=f"โฑ๏ธ เน€เธเธฃเธตเธขเธเน€เธ—เธตเธขเธเน€เธงเธฅเธฒเธ—เธณเธเธฒเธเนเธเธ vs เน€เธงเธฅเธฒเธเธฃเธดเธ เธเธฃเธฐเธเธณเน€เธ”เธทเธญเธ {month_names[sel_dw_month-1]} {sel_dw_year} ({len(df_draw_filtered)} เธฃเธฒเธขเธเธฒเธฃ)",
                        color_discrete_map={"เน€เธงเธฅเธฒเนเธเธ (เธเธก.)": "#94A3B8", "เน€เธงเธฅเธฒเธเธฃเธดเธ (เธเธก.)": "#2563EB"},
                        text_auto='.2f'
                    )
                    fig_dw.update_traces(textposition='outside', cliponaxis=False)
                    fig_dw.update_layout(
                        height=chart_h,
                        plot_bgcolor="#FFFFFF",
                        paper_bgcolor="#FFFFFF",
                        margin=dict(l=20, r=20, t=40, b=20),
                        yaxis_title="[เธฃเธซเธฑเธชเนเธเธเธเธฒเธ] เธเธทเนเธญ Drawing (เน€เธเธฃเธทเนเธญเธเธเธฑเธเธฃเธ—เธตเนเธเธฅเธดเธ•)",
                        xaxis_title="เน€เธงเธฅเธฒเนเธเธเธฒเธฃเธเธฅเธดเธ• (เธเธฑเนเธงเนเธกเธ)",
                        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
                    )
                    st.plotly_chart(fig_dw, use_container_width=True)

                    st.divider()

                    st.markdown(f"#### ๐“ เธ•เธฒเธฃเธฒเธเธชเธฃเธธเธเน€เธงเธฅเธฒเน€เธเธฃเธตเธขเธเน€เธ—เธตเธขเธเธฃเธฒเธข Drawing เธเธฃเธฐเธเธณเน€เธ”เธทเธญเธ {month_names[sel_dw_month-1]} {sel_dw_year}")
                    
                    search_dw_table = st.text_input(
                        "๐” เธเนเธเธซเธฒเนเธเธ•เธฒเธฃเธฒเธเน€เธเธฃเธตเธขเธเน€เธ—เธตเธขเธเธฃเธฒเธข Drawing (เนเธเธเธเธฒเธ, Drawing, เธงเธฑเธชเธ”เธธ, เน€เธเธฃเธทเนเธญเธเธเธฑเธเธฃ, เธเธฅเธเธฃเธฐเน€เธกเธดเธ):",
                        placeholder="เธเธดเธกเธเนเน€เธเธทเนเธญเธเนเธเธซเธฒเธเนเธญเธกเธนเธฅเนเธเธ•เธฒเธฃเธฒเธ เน€เธเนเธ SS400, No.1, เน€เธฃเนเธงเธเธถเนเธ, เธเนเธฒเธเธงเนเธฒเนเธเธ...",
                        key="search_drawing_table_input"
                    )

                    df_table_display = df_draw_full.copy().sort_values(by="เนเธเธเธเธฒเธ")
                    if search_dw_table.strip() != "":
                        q_dt = search_dw_table.strip().lower()
                        df_table_display = df_table_display[
                            df_table_display["เนเธเธเธเธฒเธ"].astype(str).str.lower().str.contains(q_dt) |
                            df_table_display["เธเธทเนเธญ Drawing."].astype(str).str.lower().str.contains(q_dt) |
                            df_table_display["เธงเธฑเธชเธ”เธธ"].astype(str).str.lower().str.contains(q_dt) |
                            df_table_display["เน€เธเธฃเธทเนเธญเธเธเธฑเธเธฃเธ—เธตเนเธเธฅเธดเธ•"].astype(str).str.lower().str.contains(q_dt) |
                            df_table_display["เธเธฒเธฃเธเธฃเธฐเน€เธกเธดเธ"].astype(str).str.lower().str.contains(q_dt)
                        ]

                    st.dataframe(
                        df_table_display[[
                            "เนเธเธเธเธฒเธ", "เธเธทเนเธญ Drawing.", "เธเธณเธเธงเธ", "เธงเธฑเธชเธ”เธธ", "เน€เธเธฃเธทเนเธญเธเธเธฑเธเธฃเธ—เธตเนเธเธฅเธดเธ•", 
                            "เธเธณเธเธงเธ Step", "เน€เธงเธฅเธฒเนเธเธ (เธเธก.)", "เน€เธงเธฅเธฒเธเธฃเธดเธ (เธเธก.)", "เนเธเธ/เธเธดเนเธ (เธเธก.)", "เธเธฃเธดเธ/เธเธดเนเธ (เธเธก.)",
                            "เธเธงเธฒเธกเนเธกเนเธเธขเธณ (%)", "เธเธฅเธ•เนเธฒเธ (เธเธก.)", "เธเธฒเธฃเธเธฃเธฐเน€เธกเธดเธ"
                        ]],
                        column_config={
                            "เนเธเธเธเธฒเธ": st.column_config.TextColumn("เนเธเธเธเธฒเธ", width=80),
                            "เธเธทเนเธญ Drawing.": st.column_config.TextColumn("เธเธทเนเธญ Drawing.", width=170),
                            "เธเธณเธเธงเธ": st.column_config.NumberColumn("เธเธณเธเธงเธ", width=60, format="%d"),
                            "เธงเธฑเธชเธ”เธธ": st.column_config.TextColumn("เธงเธฑเธชเธ”เธธ", width=75),
                            "เน€เธเธฃเธทเนเธญเธเธเธฑเธเธฃเธ—เธตเนเธเธฅเธดเธ•": st.column_config.TextColumn("เน€เธเธฃเธทเนเธญเธเธเธฑเธเธฃ / เนเธเธเธ", width=140),
                            "เธเธณเธเธงเธ Step": st.column_config.NumberColumn("Step", width=60, format="%d"),
                            "เน€เธงเธฅเธฒเนเธเธ (เธเธก.)": st.column_config.NumberColumn("เนเธเธ (เธเธก.)", width=85, format="%.2f"),
                            "เน€เธงเธฅเธฒเธเธฃเธดเธ (เธเธก.)": st.column_config.NumberColumn("เธเธฃเธดเธ (เธเธก.)", width=85, format="%.2f"),
                            "เนเธเธ/เธเธดเนเธ (เธเธก.)": st.column_config.NumberColumn("เนเธเธ/เธเธดเนเธ", width=80, format="%.2f"),
                            "เธเธฃเธดเธ/เธเธดเนเธ (เธเธก.)": st.column_config.NumberColumn("เธเธฃเธดเธ/เธเธดเนเธ", width=80, format="%.2f"),
                            "เธเธงเธฒเธกเนเธกเนเธเธขเธณ (%)": st.column_config.ProgressColumn("เธเธงเธฒเธกเนเธกเนเธเธขเธณ", width=100, min_value=0, max_value=150, format="%d%%"),
                            "เธเธฅเธ•เนเธฒเธ (เธเธก.)": st.column_config.NumberColumn("เธเธฅเธ•เนเธฒเธ (เธเธก.)", width=85, format="%.2f"),
                            "เธเธฒเธฃเธเธฃเธฐเน€เธกเธดเธ": st.column_config.TextColumn("เธเธฅเธเธฃเธฐเน€เธกเธดเธ", width=145),
                        },
                        hide_index=True,
                        use_container_width=True
                    )

                    st.divider()

                    st.markdown("#### ๐”ฌ เน€เธเธฒเธฐเธฅเธถเธเธเธงเธฒเธกเธ•เนเธฒเธเธฃเธฐเธ”เธฑเธเธเธฑเนเธเธ•เธญเธเธขเนเธญเธข (Step Breakdown Inspector)")
                    drawing_options = [f"[{r['เนเธเธเธเธฒเธ']}] {r['เธเธทเนเธญ Drawing.']}" for _, r in df_draw_full.iterrows()]
                    selected_inspect = st.selectbox("เน€เธฅเธทเธญเธ Drawing เธ—เธตเนเธ•เนเธญเธเธเธฒเธฃเน€เธเธฒเธฐเธฅเธถเธเธ”เธนเธฃเธฒเธขเธเธฑเนเธเธ•เธญเธ:", drawing_options)

                    if selected_inspect:
                        ins_plan = selected_inspect.split("] ")[0].replace("[", "").strip()
                        ins_dw = selected_inspect.split("] ")[1].strip()
                        step_details = monthly_dw_jobs[(monthly_dw_jobs["เนเธเธเธเธฒเธ"] == ins_plan) & (monthly_dw_jobs["เธเธทเนเธญ Drawing."] == ins_dw)].copy()

                        if not step_details.empty:
                            step_diffs, step_evals = [], []
                            for _, sr in step_details.iterrows():
                                s_st, s_fn = sr.get("เน€เธฃเธดเนเธกเธเธฃเธดเธ"), sr.get("เน€เธชเธฃเนเธเธเธฃเธดเธ")
                                act_st = parse_flexible_datetime(s_st)
                                act_fn = parse_flexible_datetime(s_fn)
                                if act_st is not None and act_fn is not None:
                                    d_sec = (act_fn - act_st).total_seconds()
                                    a_h = round(d_sec / 3600.0, 2)
                                    v_h = round(a_h - sr["เน€เธงเธฅเธฒเนเธเธ (เธเธก.)"], 2)
                                    step_diffs.append(v_h)
                                    d_mins = round(v_h * 60)
                                    step_evals.append(f"๐ข เน€เธฃเนเธงเธเธถเนเธ {abs(d_mins)} เธเธฒเธ—เธต" if v_h <= 0 else f"๐”ด เธเนเธฒเธเธงเนเธฒเนเธเธ +{d_mins} เธเธฒเธ—เธต")
                                else:
                                    step_diffs.append(0.0)
                                    step_evals.append("-")
                            
                            step_details["เธเธฅเธ•เนเธฒเธ (เธเธก.)"] = step_diffs
                            step_details["เธเธฒเธฃเธเธฃเธฐเน€เธกเธดเธ"] = step_evals

                            st.dataframe(
                                step_details[["เธเธฑเนเธเธ•เธญเธ (Step)", "เน€เธฅเธทเธญเธเน€เธเธฃเธทเนเธญเธเธเธฑเธเธฃ", "เน€เธฃเธดเนเธกเธเธฃเธดเธ", "เน€เธชเธฃเนเธเธเธฃเธดเธ", "Setup (เธ.)", "Basic (เธ.)", "เนเธเธฃเนเธเธฃเธก (เธ.)", "เน€เธงเธฅเธฒเนเธเธ (เธเธก.)", "เน€เธงเธฅเธฒเธเธฃเธดเธ (เธเธก.)", "เธเธฅเธ•เนเธฒเธ (เธเธก.)", "เธเธฒเธฃเธเธฃเธฐเน€เธกเธดเธ"]],
                                column_config={
                                    "เธเธฑเนเธเธ•เธญเธ (Step)": st.column_config.TextColumn("เธเธฑเนเธเธ•เธญเธ (Step)", width=120),
                                    "เน€เธฅเธทเธญเธเน€เธเธฃเธทเนเธญเธเธเธฑเธเธฃ": st.column_config.TextColumn("เธชเธ–เธฒเธเธตเธเธฅเธดเธ•", width=140),
                                    "เน€เธฃเธดเนเธกเธเธฃเธดเธ": st.column_config.DatetimeColumn("เน€เธฃเธดเนเธกเธเธฃเธดเธ", width=130, format="DD/MM HH:mm"),
                                    "เน€เธชเธฃเนเธเธเธฃเธดเธ": st.column_config.DatetimeColumn("เน€เธชเธฃเนเธเธเธฃเธดเธ", width=130, format="DD/MM HH:mm"),
                                    "Setup (เธ.)": st.column_config.NumberColumn("Setup", width=70, format="%d เธ."),
                                    "Basic (เธ.)": st.column_config.NumberColumn("Basic", width=70, format="%d เธ."),
                                    "เนเธเธฃเนเธเธฃเธก (เธ.)": st.column_config.NumberColumn("เนเธเธฃเนเธเธฃเธก", width=75, format="%d เธ."),
                                    "เน€เธงเธฅเธฒเนเธเธ (เธเธก.)": st.column_config.NumberColumn("เนเธเธ (เธเธก.)", width=85, format="%.2f"),
                                    "เน€เธงเธฅเธฒเธเธฃเธดเธ (เธเธก.)": st.column_config.NumberColumn("เธเธฃเธดเธ (เธเธก.)", width=85, format="%.2f"),
                                    "เธเธฅเธ•เนเธฒเธ (เธเธก.)": st.column_config.NumberColumn("Diff", width=75, format="%.2f"),
                                    "เธเธฒเธฃเธเธฃเธฐเน€เธกเธดเธ": st.column_config.TextColumn("เธเธฅเธเธฃเธฐเน€เธกเธดเธ", width=140),
                                },
                                hide_index=True,
                                use_container_width=True
                            )
                else:
                    st.warning("โ ๏ธ เนเธกเนเธเธเธเนเธญเธกเธนเธฅ Drawing เธ•เธฒเธกเน€เธเธทเนเธญเธเนเธเธ—เธตเนเธเนเธเธซเธฒ")
            else:
                st.info(f"โน๏ธ เธขเธฑเธเนเธกเนเธกเธตเธฃเธฒเธขเธเธฒเธฃ Drawing เธ—เธตเนเธเธฅเธดเธ•เน€เธชเธฃเนเธเธชเธดเนเธเนเธเน€เธ”เธทเธญเธ {month_names[sel_dw_month-1]} {sel_dw_year}")
        else:
            st.info("โน๏ธ เธขเธฑเธเนเธกเนเธกเธต Drawing เธ—เธตเนเธเธถเนเธเธชเธ–เธฒเธเธฐ 'โ… เน€เธชเธฃเนเธเธชเธดเนเธเนเธฅเนเธง'")
    else:
        st.info("โน๏ธ เธขเธฑเธเนเธกเนเธกเธตเธเนเธญเธกเธนเธฅเนเธเธฃเธฐเธเธ")

# ---------------------------------------------------------
# VIEW 4: เธฃเธฒเธขเธเธฒเธเธชเธฃเธธเธเธเธฃเธฐเธเธณเน€เธ”เธทเธญเธ
# ---------------------------------------------------------
elif st.session_state.current_view == "๐“‘ เธฃเธฒเธขเธเธฒเธเธชเธฃเธธเธเธเธฃเธฐเธเธณเน€เธ”เธทเธญเธ":
    if st.session_state.user_role is None:
        st.subheader("๐”’ เธขเธทเธเธขเธฑเธเธ•เธฑเธงเธ•เธเธชเธณเธซเธฃเธฑเธเน€เธเนเธฒเนเธเนเธเธฒเธเธฃเธฒเธขเธเธฒเธเธชเธฃเธธเธเธเธฃเธฐเธเธณเน€เธ”เธทเธญเธ")
        st.info("เธเธฃเธธเธ“เธฒเธเธฃเธญเธเธฃเธซเธฑเธชเธเนเธฒเธเน€เธเธทเนเธญเน€เธเนเธฒเนเธเนเธเธฒเธ:\n* **เธเธนเนเธเธฃเธดเธซเธฒเธฃ/เธงเธฒเธเนเธเธ:** เธฃเธซเธฑเธชเธเนเธฒเธเธฃเธฐเธ”เธฑเธ Admin เธซเธฃเธทเธญ เธฃเธซเธฑเธชเธเนเธฒเธเธ—เธฑเนเธงเนเธ")
        col_pwd, col_btn = st.columns([3, 1])
        with col_pwd:
            input_pwd = st.text_input("เธฃเธซเธฑเธชเธเนเธฒเธ (Password):", type="password", key="pwd_monthly_report")
        with col_btn:
            st.write("")
            st.write("")
            if st.button("๐”“ เน€เธเนเธฒเธชเธนเนเธฃเธฐเธเธ", type="primary", use_container_width=True, key="btn_login_monthly"):
                if input_pwd == ADMIN_PASSWORD:
                    st.session_state.user_role = "admin"
                    st.rerun()
                elif input_pwd == VIEWER_PASSWORD:
                    st.session_state.user_role = "viewer"
                    st.rerun()
                else:
                    st.error("เธฃเธซเธฑเธชเธเนเธฒเธเนเธกเนเธ–เธนเธเธ•เนเธญเธ")
    else:
        c_head, c_logout = st.columns([8, 2])
        with c_head:
            st.subheader("๐“‘ เธฃเธฒเธขเธเธฒเธเธชเธฃเธธเธเธเธฅเธเธฒเธฃเธเธฅเธดเธ•เนเธฅเธฐเธเธฃเธฐเธชเธดเธ—เธเธดเธ เธฒเธเธเธฃเธฐเธเธณเน€เธ”เธทเธญเธ (Monthly Production Report)")
        with c_logout:
            if st.button("๐ช เธญเธญเธเธเธฒเธเธฃเธฐเธเธ", use_container_width=True, key="btn_logout_monthly"):
                st.session_state.user_role = None
                st.rerun()

        df_db = fetch_jobs_from_supabase()
        rate_map = DEFAULT_RATES

        current_now = get_bangkok_now()
        r_col1, r_col2, r_col_exp = st.columns([2, 2, 4])
        
        with r_col1:
            month_names = ["เธกเธเธฃเธฒเธเธก (1)", "เธเธธเธกเธ เธฒเธเธฑเธเธเน (2)", "เธกเธตเธเธฒเธเธก (3)", "เน€เธกเธฉเธฒเธขเธ (4)", "เธเธคเธฉเธ เธฒเธเธก (5)", "เธกเธดเธ–เธธเธเธฒเธขเธ (6)", "เธเธฃเธเธเธฒเธเธก (7)", "เธชเธดเธเธซเธฒเธเธก (8)", "เธเธฑเธเธขเธฒเธขเธ (9)", "เธ•เธธเธฅเธฒเธเธก (10)", "เธเธคเธจเธเธดเธเธฒเธขเธ (11)", "เธเธฑเธเธงเธฒเธเธก (12)"]
            selected_month_idx = st.selectbox("๐“… เน€เธฅเธทเธญเธเน€เธ”เธทเธญเธ:", range(1, 13), index=current_now.month - 1, format_func=lambda x: month_names[x-1])
        with r_col2:
            selected_year = st.selectbox("๐“ เน€เธฅเธทเธญเธเธเธต (เธ.เธจ.):", [current_now.year - 1, current_now.year, current_now.year + 1], index=1)

        if not df_db.empty:
            finished_all = df_db[df_db["เธชเธ–เธฒเธเธฐเธเธฒเธ"].isin(["๐ฉ เน€เธชเธฃเนเธเธชเธดเนเธเนเธฅเนเธง", "โ… เน€เธชเธฃเนเธเธชเธดเนเธเนเธฅเนเธง"])].copy()
            finished_all["เน€เธชเธฃเนเธเธเธฃเธดเธ_DT"] = pd.to_datetime(finished_all["เน€เธชเธฃเนเธเธเธฃเธดเธ"], errors='coerce')
            finished_all["เธงเธฑเธเธเธถเนเธเธเธฒเธ_DT"] = pd.to_datetime(finished_all["เธงเธฑเธ-เน€เธงเธฅเธฒเธเธถเนเธเธเธฒเธ"], errors='coerce')
            finished_all["Target_Date"] = finished_all["เน€เธชเธฃเนเธเธเธฃเธดเธ_DT"].fillna(finished_all["เธงเธฑเธเธเธถเนเธเธเธฒเธ_DT"])
            
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
            monthly_jobs["Setup (เธ.)"] = pd.to_numeric(monthly_jobs["Setup (เธ.)"], errors='coerce').fillna(10.0)
            monthly_jobs["Basic (เธ.)"] = pd.to_numeric(monthly_jobs["Basic (เธ.)"], errors='coerce').fillna(0.0)
            monthly_jobs["เนเธเธฃเนเธเธฃเธก (เธ.)"] = pd.to_numeric(monthly_jobs["เนเธเธฃเนเธเธฃเธก (เธ.)"], errors='coerce').fillna(0.0)
            monthly_jobs["เธเธณเธเธงเธ"] = pd.to_numeric(monthly_jobs["เธเธณเธเธงเธ"], errors='coerce').fillna(1).astype(int)
            monthly_jobs["เน€เธงเธฅเธฒเนเธเธ (เธเธก.)"] = ((monthly_jobs["Setup (เธ.)"] + monthly_jobs["Basic (เธ.)"] + monthly_jobs["เนเธเธฃเนเธเธฃเธก (เธ.)"]) / 60.0).round(2)
            
            actual_hrs_list, diff_hrs_list, on_time_list = [], [], []
            for _, r in monthly_jobs.iterrows():
                s_real, f_real = r.get("เน€เธฃเธดเนเธกเธเธฃเธดเธ"), r.get("เน€เธชเธฃเนเธเธเธฃเธดเธ")
                act_st = parse_flexible_datetime(s_real)
                act_fn = parse_flexible_datetime(f_real)
                if act_st is not None and act_fn is not None:
                    diff_sec = (act_fn - act_st).total_seconds()
                    act_hrs = round(diff_sec / 3600.0, 2)
                    v_hrs = round(act_hrs - r["เน€เธงเธฅเธฒเนเธเธ (เธเธก.)"], 2)
                    actual_hrs_list.append(act_hrs)
                    diff_hrs_list.append(v_hrs)
                    on_time_list.append(1 if act_hrs <= r["เน€เธงเธฅเธฒเนเธเธ (เธเธก.)"] else 0)
                else:
                    actual_hrs_list.append(r["เน€เธงเธฅเธฒเนเธเธ (เธเธก.)"])
                    diff_hrs_list.append(0.0)
                    on_time_list.append(1)
                    
            monthly_jobs["เน€เธงเธฅเธฒเธเธฃเธดเธ (เธเธก.)"] = actual_hrs_list
            monthly_jobs["เธเธฅเธ•เนเธฒเธ (เธเธก.)"] = diff_hrs_list
            monthly_jobs["เน€เธฃเธ•เธฃเธฒเธเธฒ (เธเธฒเธ—/เธเธก.)"] = monthly_jobs["เน€เธฅเธทเธญเธเน€เธเธฃเธทเนเธญเธเธเธฑเธเธฃ"].map(rate_map).fillna(500)
            monthly_jobs["เธกเธนเธฅเธเนเธฒเธฃเธงเธก (เธเธฒเธ—)"] = monthly_jobs["เน€เธงเธฅเธฒเธเธฃเธดเธ (เธเธก.)"] * monthly_jobs["เน€เธฃเธ•เธฃเธฒเธเธฒ (เธเธฒเธ—/เธเธก.)"]

            total_jobs_count = len(monthly_jobs)
            total_qty_pieces = monthly_jobs["เธเธณเธเธงเธ"].sum()
            total_running_hrs = monthly_jobs["เน€เธงเธฅเธฒเธเธฃเธดเธ (เธเธก.)"].sum()
            total_plan_hrs_m = monthly_jobs["เน€เธงเธฅเธฒเนเธเธ (เธเธก.)"].sum()
            total_variance_hrs = monthly_jobs["เธเธฅเธ•เนเธฒเธ (เธเธก.)"].sum()
            total_output_val = monthly_jobs["เธกเธนเธฅเธเนเธฒเธฃเธงเธก (เธเธฒเธ—)"].sum()
            on_time_rate = (sum(on_time_list) / total_jobs_count * 100.0) if total_jobs_count > 0 else 100.0

            if not prev_monthly_jobs.empty:
                prev_qty = prev_monthly_jobs["เธเธณเธเธงเธ"].sum()
                prev_monthly_jobs["Setup (เธ.)"] = pd.to_numeric(prev_monthly_jobs["Setup (เธ.)"], errors='coerce').fillna(10.0)
                prev_monthly_jobs["Basic (เธ.)"] = pd.to_numeric(prev_monthly_jobs["Basic (เธ.)"], errors='coerce').fillna(0.0)
                prev_monthly_jobs["เนเธเธฃเนเธเธฃเธก (เธ.)"] = pd.to_numeric(prev_monthly_jobs["เนเธเธฃเนเธเธฃเธก (เธ.)"], errors='coerce').fillna(0.0)
                prev_monthly_jobs["เน€เธงเธฅเธฒเนเธเธ (เธเธก.)"] = ((prev_monthly_jobs["Setup (เธ.)"] + prev_monthly_jobs["Basic (เธ.)"] + prev_monthly_jobs["เนเธเธฃเนเธเธฃเธก (เธ.)"]) / 60.0).round(2)
                prev_val = sum([r.get("เน€เธงเธฅเธฒเนเธเธ (เธเธก.)", 0.0) * rate_map.get(r.get("เน€เธฅเธทเธญเธเน€เธเธฃเธทเนเธญเธเธเธฑเธเธฃ"), 500) for _, r in prev_monthly_jobs.iterrows()])
                
                growth_qty = ((total_qty_pieces - prev_qty) / prev_qty * 100) if prev_qty > 0 else 0.0
                growth_val = ((total_output_val - prev_val) / prev_val * 100) if prev_val > 0 else 0.0
                growth_qty_str = f"{'+' if growth_qty >= 0 else ''}{growth_qty:.1f}% เน€เธ—เธตเธขเธเน€เธ”เธทเธญเธเธเนเธญเธ"
                growth_val_str = f"{'+' if growth_val >= 0 else ''}{growth_val:.1f}% เน€เธ—เธตเธขเธเน€เธ”เธทเธญเธเธเนเธญเธ"
            else:
                growth_qty_str = "เนเธกเนเธกเธตเธเนเธญเธกเธนเธฅเน€เธ”เธทเธญเธเธเนเธญเธเธซเธเนเธฒ"
                growth_val_str = "เนเธกเนเธกเธตเธเนเธญเธกเธนเธฅเน€เธ”เธทเธญเธเธเนเธญเธเธซเธเนเธฒ"

            var_title_txt = f"โก เน€เธฃเนเธงเธเธงเนเธฒเนเธเธเธฃเธงเธก {abs(total_variance_hrs):.1f} เธเธก." if total_variance_hrs <= 0 else f"โ ๏ธ เธเนเธฒเธเธงเนเธฒเนเธเธเธฃเธงเธก +{total_variance_hrs:.1f} เธเธก."

            st.markdown(f"""
            <div class="kpi-container">
                <div class="kpi-card kpi-green">
                    <div class="kpi-title">โ… เธเธดเนเธเธเธฒเธเธ—เธตเนเธเธฅเธดเธ•เน€เธชเธฃเนเธ</div>
                    <div class="kpi-value">{total_qty_pieces:,} <span style="font-size:15px; font-weight:600;">เธเธดเนเธ</span></div>
                    <div class="kpi-sub">๐“ {growth_qty_str} ({total_jobs_count} เธเธดเธง)</div>
                </div>
                <div class="kpi-card kpi-blue">
                    <div class="kpi-title">โฑ๏ธ เธเธฑเนเธงเนเธกเธเน€เธ”เธดเธเน€เธเธฃเธทเนเธญเธเธเธฃเธดเธ</div>
                    <div class="kpi-value">{total_running_hrs:,.1f} <span style="font-size:15px; font-weight:600;">เธเธก.</span></div>
                    <div class="kpi-sub">เนเธเธเธ—เธตเนเธ•เธฑเนเธเนเธงเน: {total_plan_hrs_m:,.1f} เธเธก.</div>
                </div>
                <div class="kpi-card kpi-orange">
                    <div class="kpi-title">๐’ฐ เธกเธนเธฅเธเนเธฒเธเธฅเธเธฅเธดเธ•เธฃเธงเธก</div>
                    <div class="kpi-value">{total_output_val:,.2f} <span style="font-size:15px; font-weight:600;">เธฟ</span></div>
                    <div class="kpi-sub">๐“ {growth_val_str}</div>
                </div>
                <div class="kpi-card kpi-purple">
                    <div class="kpi-title">๐ฏ เธชเนเธเธกเธญเธเธ•เธฃเธเนเธเธ (On-Time)</div>
                    <div class="kpi-value">{on_time_rate:.1f} %</div>
                    <div class="kpi-sub">{var_title_txt}</div>
                </div>
            </div>
            """, unsafe_allow_html=True)

            machine_summary = []
            for m in MACHINE_LIST:
                m_sub = monthly_jobs[monthly_jobs["เน€เธฅเธทเธญเธเน€เธเธฃเธทเนเธญเธเธเธฑเธเธฃ"] == m]
                if not m_sub.empty:
                    m_qty = m_sub["เธเธณเธเธงเธ"].sum()
                    m_jobs = len(m_sub)
                    m_plan_hrs = m_sub["เน€เธงเธฅเธฒเนเธเธ (เธเธก.)"].sum()
                    m_act_hrs = m_sub["เน€เธงเธฅเธฒเธเธฃเธดเธ (เธเธก.)"].sum()
                    m_val = m_sub["เธกเธนเธฅเธเนเธฒเธฃเธงเธก (เธเธฒเธ—)"].sum()
                    m_contrib = (m_val / total_output_val * 100.0) if total_output_val > 0 else 0.0
                    diff_hrs = round(m_act_hrs - m_plan_hrs, 2)
                    eval_txt = f"๐ข เน€เธฃเนเธงเธเธถเนเธ {abs(diff_hrs):.2f} เธเธก." if diff_hrs <= 0 else f"๐”ด เธเนเธฒเธเธงเนเธฒเนเธเธ +{diff_hrs:.2f} เธเธก."
                    
                    machine_summary.append({
                        "เน€เธเธฃเธทเนเธญเธเธเธฑเธเธฃ / เนเธเธเธ": m,
                        "เธเธณเธเธงเธเธเธดเธงเธเธฒเธ": m_jobs,
                        "เธเธดเนเธเธเธฒเธเธฃเธงเธก (เธเธดเนเธ)": m_qty,
                        "เน€เธงเธฅเธฒเนเธเธ (เธเธก.)": round(m_plan_hrs, 2),
                        "เน€เธงเธฅเธฒเธเธฃเธดเธ (เธเธก.)": round(m_act_hrs, 2),
                        "เธเธฅเธ•เนเธฒเธ": eval_txt,
                        "เน€เธฃเธ•เธฃเธฒเธเธฒ": f"{rate_map.get(m, 500):,} เธฟ",
                        "เธกเธนเธฅเธเนเธฒเธเธฅเธเธฅเธดเธ• (เธเธฒเธ—)": round(m_val, 2),
                        "เธชเธฑเธ”เธชเนเธงเธเธกเธนเธฅเธเนเธฒ (%)": round(m_contrib, 1)
                    })
            df_m_sum = pd.DataFrame(machine_summary).sort_values(by="เธกเธนเธฅเธเนเธฒเธเธฅเธเธฅเธดเธ• (เธเธฒเธ—)", ascending=False)

            mat_summary = []
            for mat_name, mat_sub in monthly_jobs.groupby("เธงเธฑเธชเธ”เธธ"):
                mat_qty = mat_sub["เธเธณเธเธงเธ"].sum()
                mat_jobs = len(mat_sub)
                mat_act_hrs = mat_sub["เน€เธงเธฅเธฒเธเธฃเธดเธ (เธเธก.)"].sum()
                mat_val = mat_sub["เธกเธนเธฅเธเนเธฒเธฃเธงเธก (เธเธฒเธ—)"].sum()
                mat_summary.append({
                    "เธเธเธดเธ”เธงเธฑเธชเธ”เธธ": mat_name if str(mat_name).strip() != "" else "เนเธกเนเธฃเธฐเธเธธ",
                    "เธเธณเธเธงเธเธเธดเธง": mat_jobs,
                    "เธเธณเธเธงเธเธเธดเนเธเธเธฒเธ (เธเธดเนเธ)": mat_qty,
                    "เธเธฑเนเธงเนเธกเธเธเธฅเธดเธ•เธเธฃเธดเธ (เธเธก.)": round(mat_act_hrs, 2),
                    "เธกเธนเธฅเธเนเธฒเธเธฅเธเธฅเธดเธ• (เธเธฒเธ—)": round(mat_val, 2),
                    "เธชเธฑเธ”เธชเนเธงเธ (%)": round((mat_val / total_output_val * 100.0), 1) if total_output_val > 0 else 0.0
                })
            df_mat_sum = pd.DataFrame(mat_summary).sort_values(by="เธเธฑเนเธงเนเธกเธเธเธฅเธดเธ•เธเธฃเธดเธ (เธเธก.)", ascending=False)

            delayed_jobs = monthly_jobs[monthly_jobs["เธเธฅเธ•เนเธฒเธ (เธเธก.)"] > 0].sort_values(by="เธเธฅเธ•เนเธฒเธ (เธเธก.)", ascending=False).head(5)

            fig_m_val = px.bar(
                df_m_sum.sort_values(by="เธกเธนเธฅเธเนเธฒเธเธฅเธเธฅเธดเธ• (เธเธฒเธ—)", ascending=True),
                x="เธกเธนเธฅเธเนเธฒเธเธฅเธเธฅเธดเธ• (เธเธฒเธ—)",
                y="เน€เธเธฃเธทเนเธญเธเธเธฑเธเธฃ / เนเธเธเธ",
                orientation="h",
                title="๐’ฐ เธญเธฑเธเธ”เธฑเธเธกเธนเธฅเธเนเธฒเธเธฅเธเธฅเธดเธ•เนเธขเธเธ•เธฒเธกเน€เธเธฃเธทเนเธญเธเธเธฑเธเธฃ (เธเธฒเธ—)",
                color="เธกเธนเธฅเธเนเธฒเธเธฅเธเธฅเธดเธ• (เธเธฒเธ—)",
                color_continuous_scale="Blues",
                text_auto='.2f'
            )
            fig_m_val.update_traces(textposition='outside', cliponaxis=False)
            fig_m_val.update_layout(height=max(380, len(df_m_sum) * 26), plot_bgcolor="#FFFFFF", paper_bgcolor="#FFFFFF", margin=dict(l=20, r=20, t=40, b=20))

            fig_compare = px.bar(
                df_m_sum.sort_values(by="เน€เธงเธฅเธฒเธเธฃเธดเธ (เธเธก.)", ascending=True),
                x=["เน€เธงเธฅเธฒเนเธเธ (เธเธก.)", "เน€เธงเธฅเธฒเธเธฃเธดเธ (เธเธก.)"],
                y="เน€เธเธฃเธทเนเธญเธเธเธฑเธเธฃ / เนเธเธเธ",
                orientation="h",
                barmode="group",
                title="โฑ๏ธ เน€เธเธฃเธตเธขเธเน€เธ—เธตเธขเธเน€เธงเธฅเธฒเธ—เธณเธเธฒเธ: เนเธเธเธเธฒเธ vs เธ—เธณเธเธฒเธเธเธฃเธดเธ เนเธ•เนเธฅเธฐเน€เธเธฃเธทเนเธญเธเธเธฑเธเธฃ (เธเธก.)",
                color_discrete_map={"เน€เธงเธฅเธฒเนเธเธ (เธเธก.)": "#94A3B8", "เน€เธงเธฅเธฒเธเธฃเธดเธ (เธเธก.)": "#2563EB"},
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

            rows_m_html = "".join([f"<tr><td>{r['เน€เธเธฃเธทเนเธญเธเธเธฑเธเธฃ / เนเธเธเธ']}</td><td style='text-align:center;'>{r['เธเธณเธเธงเธเธเธดเธงเธเธฒเธ']}</td><td style='text-align:center;'>{r['เธเธดเนเธเธเธฒเธเธฃเธงเธก (เธเธดเนเธ)']}</td><td style='text-align:center;'>{r['เน€เธงเธฅเธฒเนเธเธ (เธเธก.)']:.2f}</td><td style='text-align:center;'>{r['เน€เธงเธฅเธฒเธเธฃเธดเธ (เธเธก.)']:.2f}</td><td style='text-align:center;'>{r['เธเธฅเธ•เนเธฒเธ']}</td><td style='text-align:right;'>{r['เธกเธนเธฅเธเนเธฒเธเธฅเธเธฅเธดเธ• (เธเธฒเธ—)']:,.2f} เธฟ</td><td style='text-align:right; font-weight:bold;'>{r['เธชเธฑเธ”เธชเนเธงเธเธกเธนเธฅเธเนเธฒ (%)']:.1f}%</td></tr>" for _, r in df_m_sum.iterrows()])
            rows_mat_html = "".join([f"<tr><td>{r['เธเธเธดเธ”เธงเธฑเธชเธ”เธธ']}</td><td style='text-align:center;'>{r['เธเธณเธเธงเธเธเธดเธง']}</td><td style='text-align:center;'>{r['เธเธณเธเธงเธเธเธดเนเธเธเธฒเธ (เธเธดเนเธ)']}</td><td style='text-align:center;'>{r['เธเธฑเนเธงเนเธกเธเธเธฅเธดเธ•เธเธฃเธดเธ (เธเธก.)']:.2f}</td><td style='text-align:right;'>{r['เธกเธนเธฅเธเนเธฒเธเธฅเธเธฅเธดเธ• (เธเธฒเธ—)']:,.2f} เธฟ</td><td style='text-align:right; font-weight:bold;'>{r['เธชเธฑเธ”เธชเนเธงเธ (%)']:.1f}%</td></tr>" for _, r in df_mat_sum.iterrows()])
            rows_job_html = "".join([f"<tr><td>{r['เนเธเธเธเธฒเธ']}</td><td>{r['เธเธทเนเธญ Drawing.']}</td><td style='text-align:center;'>{r['เธเธณเธเธงเธ']}</td><td style='text-align:center;'>{r['เธงเธฑเธชเธ”เธธ']}</td><td>{r['เธเธฑเนเธเธ•เธญเธ (Step)']}</td><td>{r['เน€เธฅเธทเธญเธเน€เธเธฃเธทเนเธญเธเธเธฑเธเธฃ']}</td><td style='text-align:center;'>{pd.to_datetime(r['เน€เธฃเธดเนเธกเธเธฃเธดเธ']).strftime('%d/%m %H:%M') if pd.notna(r['เน€เธฃเธดเนเธกเธเธฃเธดเธ']) else '-'}</td><td style='text-align:center;'>{pd.to_datetime(r['เน€เธชเธฃเนเธเธเธฃเธดเธ']).strftime('%d/%m %H:%M') if pd.notna(r['เน€เธชเธฃเนเธเธเธฃเธดเธ']) else '-'}</td><td style='text-align:center;'>{r['เน€เธงเธฅเธฒเนเธเธ (เธเธก.)']:.2f}</td><td style='text-align:center;'>{r['เน€เธงเธฅเธฒเธเธฃเธดเธ (เธเธก.)']:.2f}</td><td style='text-align:right;'>{r['เธกเธนเธฅเธเนเธฒเธฃเธงเธก (เธเธฒเธ—)']:,.2f} เธฟ</td></tr>" for _, r in monthly_jobs.sort_values(by="Target_Date", ascending=True).iterrows()])

            report_data_dict = {
                "month_str": f"{month_names[selected_month_idx-1]} {selected_year}",
                "print_date": get_bangkok_now().strftime('%d/%m/%Y %H:%M เธ.'),
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
                        ๐“ เธเธดเธกเธเน / เธเธฑเธเธ—เธถเธ PDF (เธเธฃเนเธญเธกเธฃเธนเธเธเธฃเธฒเธ)
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
                                        <h2>เธเธเธ. เธเธฅเธงเธฑเธ’เธเน เน€เธญเนเธเธเธดเน€เธเธตเธขเธฃเธดเนเธ เธเธฑเธเธเธฅเธฒเธข (PES)</h2>
                                        <p>เธฃเธฒเธขเธเธฒเธเธชเธฃเธธเธเธเธฅเธเธฒเธฃเธเธฅเธดเธ•เนเธฅเธฐเธเธฃเธฐเธชเธดเธ—เธเธดเธ เธฒเธเธเธฃเธฐเธเธณเน€เธ”เธทเธญเธ (Monthly Production Report)</p>
                                    </div>
                                    <div style="text-align: right; font-size: 10px;">
                                        <b>เธเธฃเธฐเธเธณเน€เธ”เธทเธญเธ:</b> ${{reportData.month_str}}<br>
                                        <b>เธงเธฑเธเธ—เธตเนเธญเธญเธเธฃเธฒเธขเธเธฒเธ:</b> ${{reportData.print_date}}
                                    </div>
                                </div>

                                <div class="kpi-grid">
                                    <div class="kpi-item"><div class="kpi-item-title">เธเธดเนเธเธเธฒเธเธ—เธตเนเธเธฅเธดเธ•เน€เธชเธฃเนเธ</div><div class="kpi-item-val">${{reportData.total_qty}} เธเธดเนเธ</div></div>
                                    <div class="kpi-item"><div class="kpi-item-title">เธเธฑเนเธงเนเธกเธเน€เธ”เธดเธเน€เธเธฃเธทเนเธญเธเธเธฃเธดเธ</div><div class="kpi-item-val">${{reportData.total_hours}} เธเธก.</div></div>
                                    <div class="kpi-item"><div class="kpi-item-title">เธกเธนเธฅเธเนเธฒเธเธฅเธเธฅเธดเธ•เธฃเธงเธก</div><div class="kpi-item-val">${{reportData.total_value}} เธฟ</div></div>
                                    <div class="kpi-item"><div class="kpi-item-title">เธ•เธฃเธเธ•เธฒเธกเนเธเธ (On-Time)</div><div class="kpi-item-val">${{reportData.on_time}} %</div></div>
                                </div>

                                <h3>1. เธเธฃเธฒเธเธงเธดเน€เธเธฃเธฒเธฐเธซเนเธเธฃเธฐเธชเธดเธ—เธเธดเธ เธฒเธเนเธฅเธฐเธกเธนเธฅเธเนเธฒเธเธฅเธเธฅเธดเธ•</h3>
                                <div class="chart-grid">
                                    <div>${{chart1Html}}</div>
                                    <div>${{chart2Html}}</div>
                                </div>

                                <h3>2. เธชเธฃเธธเธเธเธฅเธเธฒเธฃเธ—เธณเธเธฒเธเนเธฅเธฐเธชเธฑเธ”เธชเนเธงเธเธฃเธฒเธขเนเธ”เนเนเธขเธเธ•เธฒเธกเน€เธเธฃเธทเนเธญเธเธเธฑเธเธฃ / เนเธเธเธ</h3>
                                <table>
                                    <thead><tr><th>เน€เธเธฃเธทเนเธญเธเธเธฑเธเธฃ / เนเธเธเธ</th><th>เธเธดเธง</th><th>เธเธดเนเธเธเธฒเธ</th><th>เนเธเธ (เธเธก.)</th><th>เธเธฃเธดเธ (เธเธก.)</th><th>เธเธฅเธ•เนเธฒเธ</th><th>เธกเธนเธฅเธเนเธฒเธเธฅเธเธฅเธดเธ• (เธฟ)</th><th>เธชเธฑเธ”เธชเนเธงเธ (%)</th></tr></thead>
                                    <tbody>${{reportData.rows_m}}</tbody>
                                </table>

                                <h3>3. เธชเธฃเธธเธเธเธฒเธฃเนเธเนเธงเธฑเธชเธ”เธธเนเธฅเธฐเน€เธงเธฅเธฒเธเธฅเธดเธ• (Material Insights)</h3>
                                <table>
                                    <thead><tr><th>เธเธเธดเธ”เธงเธฑเธชเธ”เธธ</th><th>เธเธดเธง</th><th>เธเธดเนเธเธเธฒเธ</th><th>เธเธฑเนเธงเนเธกเธเธเธฅเธดเธ•เธเธฃเธดเธ (เธเธก.)</th><th>เธกเธนเธฅเธเนเธฒเธเธฅเธเธฅเธดเธ• (เธฟ)</th><th>เธชเธฑเธ”เธชเนเธงเธ (%)</th></tr></thead>
                                    <tbody>${{reportData.rows_mat}}</tbody>
                                </table>

                                <h3>4. เธฃเธฒเธขเธเธฒเธฃเธเธดเนเธเธเธฒเธเธ—เธตเนเธเธฅเธดเธ•เน€เธชเธฃเนเธเธชเธดเนเธเธ—เธฑเนเธเธซเธกเธ”</h3>
                                <table>
                                    <thead><tr><th>เนเธเธเธเธฒเธ</th><th>เธเธทเนเธญ Drawing</th><th>เธเธณเธเธงเธ</th><th>เธงเธฑเธชเธ”เธธ</th><th>เธเธฑเนเธเธ•เธญเธ</th><th>เธชเธ–เธฒเธเธต</th><th>เน€เธฃเธดเนเธกเธเธฃเธดเธ</th><th>เน€เธชเธฃเนเธเธเธฃเธดเธ</th><th>เนเธเธ (เธเธก.)</th><th>เธเธฃเธดเธ (เธเธก.)</th><th>เธกเธนเธฅเธเนเธฒ (เธฟ)</th></tr></thead>
                                    <tbody>${{reportData.rows_job}}</tbody>
                                </table>

                                <div class="sign-box">
                                    <div class="sign-col">เธเธนเนเธเธฑเธ”เธ—เธณเธฃเธฒเธขเธเธฒเธ / เธเนเธฒเธขเธงเธฒเธเนเธเธ<br><br><br>( .................................................... )</div>
                                    <div class="sign-col">เธซเธฑเธงเธซเธเนเธฒเนเธเธเธเธเธฅเธดเธ• / เธเธนเนเธ•เธฃเธงเธเธชเธญเธ<br><br><br>( .................................................... )</div>
                                    <div class="sign-col">เธเธนเนเธเธฑเธ”เธเธฒเธฃเนเธฃเธเธเธฒเธ / เธเธนเนเธญเธเธธเธกเธฑเธ•เธด<br><br><br>( .................................................... )</div>
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
                        "เนเธเธเธเธฒเธ", "เธเธทเนเธญ Drawing.", "เธเธณเธเธงเธ", "เธงเธฑเธชเธ”เธธ", "เธเธฑเนเธเธ•เธญเธ (Step)", 
                        "เน€เธฅเธทเธญเธเน€เธเธฃเธทเนเธญเธเธเธฑเธเธฃ", "เน€เธฃเธดเนเธกเธเธฃเธดเธ", "เน€เธชเธฃเนเธเธเธฃเธดเธ", "เน€เธงเธฅเธฒเนเธเธ (เธเธก.)", 
                        "เน€เธงเธฅเธฒเธเธฃเธดเธ (เธเธก.)", "เธเธฅเธ•เนเธฒเธ (เธเธก.)", "เน€เธฃเธ•เธฃเธฒเธเธฒ (เธเธฒเธ—/เธเธก.)", "เธกเธนเธฅเธเนเธฒเธฃเธงเธก (เธเธฒเธ—)"
                    ]].to_csv(index=False).encode('utf-8-sig')
                    
                    st.download_button(
                        label="๐“ฅ เธ”เธฒเธงเธเนเนเธซเธฅเธ”เน€เธเนเธ CSV/Excel",
                        data=csv_data,
                        file_name=f"PES_Monthly_Report_{selected_year}_{selected_month_idx:02d}.csv",
                        mime="text/csv",
                        type="secondary",
                        use_container_width=True
                    )

            st.divider()

            col_sec1, col_sec2 = st.columns([1.5, 1])

            with col_sec1:
                st.markdown("#### ๐ญ เธชเธฃเธธเธเธเธฃเธฐเธชเธดเธ—เธเธดเธ เธฒเธเนเธฅเธฐเธชเธฑเธ”เธชเนเธงเธเธฃเธฒเธขเนเธ”เนเนเธขเธเธ•เธฒเธกเน€เธเธฃเธทเนเธญเธเธเธฑเธเธฃ (Machine ROI & Revenue)")
                st.dataframe(
                    df_m_sum,
                    column_config={
                        "เน€เธเธฃเธทเนเธญเธเธเธฑเธเธฃ / เนเธเธเธ": st.column_config.TextColumn("เน€เธเธฃเธทเนเธญเธเธเธฑเธเธฃ", width=150),
                        "เธเธณเธเธงเธเธเธดเธงเธเธฒเธ": st.column_config.NumberColumn("เธเธดเธง", width=70, format="%d"),
                        "เธเธดเนเธเธเธฒเธเธฃเธงเธก (เธเธดเนเธ)": st.column_config.NumberColumn("เธเธดเนเธเธเธฒเธ", width=85, format="%d"),
                        "เน€เธงเธฅเธฒเนเธเธ (เธเธก.)": st.column_config.NumberColumn("เนเธเธ (เธเธก.)", width=85, format="%.2f"),
                        "เน€เธงเธฅเธฒเธเธฃเธดเธ (เธเธก.)": st.column_config.NumberColumn("เธเธฃเธดเธ (เธเธก.)", width=85, format="%.2f"),
                        "เธเธฅเธ•เนเธฒเธ": st.column_config.TextColumn("เธเธฅเธ•เนเธฒเธเน€เธงเธฅเธฒ", width=125),
                        "เธกเธนเธฅเธเนเธฒเธเธฅเธเธฅเธดเธ• (เธเธฒเธ—)": st.column_config.NumberColumn("เธกเธนเธฅเธเนเธฒเธฃเธงเธก (เธเธฒเธ—)", width=130, format="%.2f เธฟ"),
                        "เธชเธฑเธ”เธชเนเธงเธเธกเธนเธฅเธเนเธฒ (%)": st.column_config.ProgressColumn("เธชเธฑเธ”เธชเนเธงเธ", width=110, min_value=0, max_value=100, format="%d%%")
                    },
                    hide_index=True,
                    use_container_width=True
                )

            with col_sec2:
                st.markdown("#### ๐”ฉ เธเธฃเธฐเธชเธดเธ—เธเธดเธ เธฒเธเนเธขเธเธ•เธฒเธกเธเธเธดเธ”เธงเธฑเธชเธ”เธธ (Material Insights)")
                st.dataframe(
                    df_mat_sum,
                    column_config={
                        "เธเธเธดเธ”เธงเธฑเธชเธ”เธธ": st.column_config.TextColumn("เธงเธฑเธชเธ”เธธ", width=100),
                        "เธเธณเธเธงเธเธเธดเธง": st.column_config.NumberColumn("เธเธดเธง", width=65),
                        "เธเธณเธเธงเธเธเธดเนเธเธเธฒเธ (เธเธดเนเธ)": st.column_config.NumberColumn("เธเธดเนเธ", width=75),
                        "เธเธฑเนเธงเนเธกเธเธเธฅเธดเธ•เธเธฃเธดเธ (เธเธก.)": st.column_config.NumberColumn("เธเธฑเนเธงเนเธกเธเธเธฃเธดเธ", width=100, format="%.1f เธเธก."),
                        "เธกเธนเธฅเธเนเธฒเธเธฅเธเธฅเธดเธ• (เธเธฒเธ—)": st.column_config.NumberColumn("เธกเธนเธฅเธเนเธฒ (เธเธฒเธ—)", width=120, format="%.2f เธฟ"),
                        "เธชเธฑเธ”เธชเนเธงเธ (%)": st.column_config.ProgressColumn("เธชเธฑเธ”เธชเนเธงเธ", width=95, min_value=0, max_value=100, format="%d%%")
                    },
                    hide_index=True,
                    use_container_width=True
                )

            st.divider()

            st.markdown("#### ๐“ เธเธฃเธฒเธเธงเธดเน€เธเธฃเธฒเธฐเธซเนเธกเธนเธฅเธเนเธฒเนเธฅเธฐเน€เธงเธฅเธฒเธเธฒเธฃเธเธฅเธดเธ•เนเธขเธเธ•เธฒเธกเน€เธเธฃเธทเนเธญเธเธเธฑเธเธฃ")
            chart_c1, chart_c2 = st.columns(2)
            with chart_c1:
                st.plotly_chart(fig_m_val, use_container_width=True)
            with chart_c2:
                st.plotly_chart(fig_compare, use_container_width=True)

            st.divider()

            st.markdown("#### โ ๏ธ 5 เธญเธฑเธเธ”เธฑเธเธเธฒเธเธ—เธตเนเธเธฅเธดเธ•เธเนเธฒเธเธงเนเธฒเนเธเธเธกเธฒเธเธ—เธตเนเธชเธธเธ” (Top 5 Delays)")
            if not delayed_jobs.empty:
                st.dataframe(
                    delayed_jobs[["เนเธเธเธเธฒเธ", "เธเธทเนเธญ Drawing.", "เธเธฑเนเธเธ•เธญเธ (Step)", "เน€เธฅเธทเธญเธเน€เธเธฃเธทเนเธญเธเธเธฑเธเธฃ", "เน€เธงเธฅเธฒเนเธเธ (เธเธก.)", "เน€เธงเธฅเธฒเธเธฃเธดเธ (เธเธก.)", "เธเธฅเธ•เนเธฒเธ (เธเธก.)"]],
                    column_config={
                        "เนเธเธเธเธฒเธ": st.column_config.TextColumn("เนเธเธเธเธฒเธ", width=85),
                        "เธเธทเนเธญ Drawing.": st.column_config.TextColumn("Drawing", width=180),
                        "เธเธฑเนเธเธ•เธญเธ (Step)": st.column_config.TextColumn("เธเธฑเนเธเธ•เธญเธ", width=120),
                        "เน€เธฅเธทเธญเธเน€เธเธฃเธทเนเธญเธเธเธฑเธเธฃ": st.column_config.TextColumn("เธชเธ–เธฒเธเธต", width=140),
                        "เน€เธงเธฅเธฒเนเธเธ (เธเธก.)": st.column_config.NumberColumn("เนเธเธ (เธเธก.)", width=90, format="%.2f"),
                        "เน€เธงเธฅเธฒเธเธฃเธดเธ (เธเธก.)": st.column_config.NumberColumn("เธเธฃเธดเธ (เธเธก.)", width=90, format="%.2f"),
                        "เธเธฅเธ•เนเธฒเธ (เธเธก.)": st.column_config.NumberColumn("เน€เธเธดเธเนเธเธ (+เธเธก.)", width=110, format="+%.2f เธเธก."),
                    },
                    hide_index=True,
                    use_container_width=True
                )
            else:
                st.success("๐ เนเธกเนเธกเธตเธเธฒเธเนเธ”เธ—เธตเนเธเธฅเธดเธ•เธเนเธฒเธเธงเนเธฒเน€เธงเธฅเธฒเนเธเธเธ—เธตเนเธ•เธฑเนเธเนเธงเนเนเธเน€เธ”เธทเธญเธเธเธตเน")

            st.divider()

            st.markdown(f"#### ๐“ เธฃเธฒเธขเธฅเธฐเน€เธญเธตเธขเธ”เธเธดเนเธเธเธฒเธเธ—เธฑเนเธเธซเธกเธ”เธ—เธตเนเน€เธชเธฃเนเธเธชเธดเนเธเนเธเน€เธ”เธทเธญเธ {month_names[selected_month_idx-1]} {selected_year}")
            st.dataframe(
                monthly_jobs.sort_values(by="Target_Date", ascending=True)[[
                    "เนเธเธเธเธฒเธ", "เธเธทเนเธญ Drawing.", "เธเธณเธเธงเธ", "เธงเธฑเธชเธ”เธธ", "เธเธฑเนเธเธ•เธญเธ (Step)", 
                    "เน€เธฅเธทเธญเธเน€เธเธฃเธทเนเธญเธเธเธฑเธเธฃ", "เน€เธฃเธดเนเธกเธเธฃเธดเธ", "เน€เธชเธฃเนเธเธเธฃเธดเธ", "เน€เธงเธฅเธฒเนเธเธ (เธเธก.)", 
                    "เน€เธงเธฅเธฒเธเธฃเธดเธ (เธเธก.)", "เธเธฅเธ•เนเธฒเธ (เธเธก.)", "เธกเธนเธฅเธเนเธฒเธฃเธงเธก (เธเธฒเธ—)"
                ]],
                column_config={
                    "เนเธเธเธเธฒเธ": st.column_config.TextColumn("เนเธเธเธเธฒเธ", width=85),
                    "เธเธทเนเธญ Drawing.": st.column_config.TextColumn("เธเธทเนเธญ Drawing.", width=180),
                    "เธเธณเธเธงเธ": st.column_config.NumberColumn("เธเธณเธเธงเธ", width=70, format="%d"),
                    "เธงเธฑเธชเธ”เธธ": st.column_config.TextColumn("เธงเธฑเธชเธ”เธธ", width=80),
                    "เธเธฑเนเธเธ•เธญเธ (Step)": st.column_config.TextColumn("เธเธฑเนเธเธ•เธญเธ", width=120),
                    "เน€เธฅเธทเธญเธเน€เธเธฃเธทเนเธญเธเธเธฑเธเธฃ": st.column_config.TextColumn("เธชเธ–เธฒเธเธตเธเธฅเธดเธ•", width=140),
                    "เน€เธฃเธดเนเธกเธเธฃเธดเธ": st.column_config.DatetimeColumn("เน€เธฃเธดเนเธกเธเธฃเธดเธ", width=140, format="DD/MM HH:mm"),
                    "เน€เธชเธฃเนเธเธเธฃเธดเธ": st.column_config.DatetimeColumn("เน€เธชเธฃเนเธเธเธฃเธดเธ", width=140, format="DD/MM HH:mm"),
                    "เน€เธงเธฅเธฒเนเธเธ (เธเธก.)": st.column_config.NumberColumn("เนเธเธ (เธเธก.)", width=85, format="%.2f"),
                    "เน€เธงเธฅเธฒเธเธฃเธดเธ (เธเธก.)": st.column_config.NumberColumn("เธเธฃเธดเธ (เธเธก.)", width=85, format="%.2f"),
                    "เธเธฅเธ•เนเธฒเธ (เธเธก.)": st.column_config.NumberColumn("Diff", width=80, format="%.2f"),
                    "เธกเธนเธฅเธเนเธฒเธฃเธงเธก (เธเธฒเธ—)": st.column_config.NumberColumn("เธกเธนเธฅเธเนเธฒ (เธเธฒเธ—)", width=120, format="%.2f เธฟ"),
                },
                hide_index=True,
                use_container_width=True
            )

        else:
            st.info(f"โน๏ธ เธขเธฑเธเนเธกเนเธกเธตเธเธฃเธฐเธงเธฑเธ•เธดเธเธฒเธเธ—เธตเนเธเธถเนเธเธชเธ–เธฒเธเธฐ 'โ… เน€เธชเธฃเนเธเธชเธดเนเธเนเธฅเนเธง' เนเธเน€เธ”เธทเธญเธ {month_names[selected_month_idx-1]} {selected_year}")

# ---------------------------------------------------------
# VIEW 5: เธเธญเธ—เธตเธงเธตเธเธฅเธฒเธเนเธฃเธเธเธฒเธ (Shop Floor TV Live Dashboard)
# ---------------------------------------------------------
elif st.session_state.current_view == "๐“บ เธเธญเธ—เธตเธงเธตเธเธฅเธฒเธเนเธฃเธเธเธฒเธ (TV Live)":
    st.cache_data.clear()
    df_live = fetch_jobs_from_supabase()

    now_bangkok = get_bangkok_now()
    cur_date_str = now_bangkok.strftime("%d/%m/%Y")

    machine_status_cards = []
    running_machines_count = 0
    hold_machines_count = 0
    idle_machines_count = 0

    for idx_m, m in enumerate(MACHINE_LIST):
        m_jobs = df_live[df_live["เน€เธฅเธทเธญเธเน€เธเธฃเธทเนเธญเธเธเธฑเธเธฃ"] == m] if not df_live.empty else pd.DataFrame()
        
        running_job = m_jobs[m_jobs["เธชเธ–เธฒเธเธฐเธเธฒเธ"].str.contains("เธเธณเธฅเธฑเธเธเธฅเธดเธ•")]
        hold_job = m_jobs[m_jobs["เธชเธ–เธฒเธเธฐเธเธฒเธ"].str.contains("เธเธฑเธเธเธฒเธ")]
        waiting_jobs = m_jobs[m_jobs["เธชเธ–เธฒเธเธฐเธเธฒเธ"].str.contains("เธฃเธญเธเธดเธง")]

        hold_alert_html = ""
        if not hold_job.empty:
            hold_machines_count += 1
            h_first = hold_job.iloc[0]
            h_start = h_first.get("เน€เธฃเธดเนเธกเธเธฃเธดเธ")
            h_start_txt = ""
            h_dt_parsed = parse_flexible_datetime(h_start)
            if h_dt_parsed is not None and pd.notna(h_dt_parsed):
                h_start_txt = f" [เน€เธฃเธดเนเธก {h_dt_parsed.strftime('%H:%M เธ.')}]"
            hold_alert_html = f'<div style="margin-top:4px; padding:3px 6px; background:rgba(217, 119, 6, 0.35); border:1px dashed #FCD34D; border-radius:6px; font-size:10.5px; color:#FEF08A;">๐‘ <b>เธเธฑเธเธเธฒเธเธฃเธญ:</b> {h_first.get("เนเธเธเธเธฒเธ", "-")} ({h_first.get("เธเธทเนเธญ Drawing.", "-")}){h_start_txt}</div>'

        if not running_job.empty:
            running_machines_count += 1
            r_info = running_job.iloc[0]
            s_start = r_info.get("เน€เธฃเธดเนเธกเธเธฃเธดเธ")
            p_code = str(r_info.get("เนเธเธเธเธฒเธ", "-"))
            d_code = str(r_info.get("เธเธทเนเธญ Drawing.", "-"))
            step_name = str(r_info.get("เธเธฑเนเธเธ•เธญเธ (Step)", "-"))
            
            r_ready_dt = parse_flexible_datetime(r_info.get("เธงเธฑเธ-เน€เธงเธฅเธฒเธเธถเนเธเธเธฒเธ"))
            ready_display_txt = r_ready_dt.strftime("%d/%m %H:%M") if (r_ready_dt is not None and pd.notna(r_ready_dt)) else "-"

            start_disp_txt = "-"
            start_epoch = to_bangkok_epoch_ms(s_start)
            r_start_parsed = parse_flexible_datetime(s_start)

            if r_start_parsed is None and r_ready_dt is not None and pd.notna(r_ready_dt):
                r_start_parsed = r_ready_dt
                start_epoch = to_bangkok_epoch_ms(r_ready_dt)

            if r_start_parsed is not None and pd.notna(r_start_parsed):
                start_disp_txt = r_start_parsed.strftime("%H:%M เธ.")
            
            tv_card_cls = "tv-card tv-card-running"
            badge_html = '<span class="tv-pulse-dot" style="margin-right:6px;"></span> <b style="color:#A7F3D0;">เธเธณเธฅเธฑเธเธฃเธฑเธเธเธฒเธ</b>'

            time_info_combined = f'''
            <div style="font-size:11.5px; font-weight:700; color:#FFFFFF; line-height:1.4;">
                <div style="display:flex; justify-content:space-between; align-items:center;">
                    <span>๐€ <b>เน€เธฃเธดเนเธก:</b> <span style="color:#93C5FD;">{start_disp_txt}</span></span>
                    <span>โฑ๏ธ <span class="pes-live-timer" data-start-epoch="{start_epoch}" style="font-family:monospace; font-size:13px; font-weight:900; color:#FDE047;">00:00:00</span></span>
                </div>
                <div style="margin-top:2px; display:flex; justify-content:space-between; font-size:11px; opacity:0.95; background:rgba(0,0,0,0.2); padding:2px 6px; border-radius:4px;">
                    <span>๐“… <b>เธเธถเนเธ:</b> {ready_display_txt}</span>
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
            h_start = h_info.get("เน€เธฃเธดเนเธกเธเธฃเธดเธ")
            p_code = str(h_info.get("เนเธเธเธเธฒเธ", "-"))
            d_code = str(h_info.get("เธเธทเนเธญ Drawing.", "-"))
            step_name = str(h_info.get("เธเธฑเนเธเธ•เธญเธ (Step)", "-"))
            
            h_ready_dt = parse_flexible_datetime(h_info.get("เธงเธฑเธ-เน€เธงเธฅเธฒเธเธถเนเธเธเธฒเธ"))
            ready_display_txt = h_ready_dt.strftime("%d/%m %H:%M") if (h_ready_dt is not None and pd.notna(h_ready_dt)) else "-"

            h_start_txt = ""
            h_st_parsed = parse_flexible_datetime(h_start)
            if h_st_parsed is not None and pd.notna(h_st_parsed):
                h_start_txt = f" (เน€เธฃเธดเนเธกเนเธงเน: {h_st_parsed.strftime('%H:%M เธ.')})"

            time_info_combined = f'''
            <div style="font-size:11.5px; font-weight:700; color:#FEF3C7; line-height:1.4;">
                <div>โ ๏ธ <b>เน€เธเธฃเธทเนเธญเธเธซเธขเธธเธ”:</b> เธฃเธญเน€เธเธดเธเธงเธฑเธชเธ”เธธเนเธซเธกเน{h_start_txt}</div>
                <div style="margin-top:2px; display:flex; justify-content:space-between; font-size:11px; opacity:0.9; background:rgba(0,0,0,0.25); padding:2px 6px; border-radius:4px;">
                    <span>๐“… <b>เธเธถเนเธ:</b> {ready_display_txt}</span>
                </div>
            </div>
            '''

            machine_status_cards.append({
                "machine": m,
                "status": "HOLD",
                "card_class": "tv-card tv-card-hold",
                "badge_html": '<b style="color:#FDE68A;">๐‘ เธเธฑเธเธเธฒเธ (เธฃเธญเธงเธฑเธชเธ”เธธ)</b>',
                "plan": p_code,
                "drawing": d_code,
                "step": step_name,
                "time_info": time_info_combined
            })
        else:
            idle_machines_count += 1
            next_txt = "เนเธกเนเธกเธตเธเธดเธงเธฃเธญ"
            next_dates_html = ""
            if not waiting_jobs.empty:
                w_first = waiting_jobs.iloc[0]
                p_code = str(w_first.get('เนเธเธเธเธฒเธ', '-'))
                d_code = str(w_first.get('เธเธทเนเธญ Drawing.', '-'))
                step_name = str(w_first.get('เธเธฑเนเธเธ•เธญเธ (Step)', '-'))
                next_txt = f"เธเธดเธงเธ–เธฑเธ”เนเธ: {p_code} ({d_code})"
                
                w_ready_dt = parse_flexible_datetime(w_first.get("เธงเธฑเธ-เน€เธงเธฅเธฒเธเธถเนเธเธเธฒเธ"))
                ready_display_txt = w_ready_dt.strftime("%d/%m %H:%M") if (w_ready_dt is not None and pd.notna(w_ready_dt)) else "-"
                
                next_dates_html = f'''
                <div style="margin-top:3px; display:flex; justify-content:space-between; font-size:10.5px; color:#94A3B8; background:rgba(0,0,0,0.25); padding:2px 6px; border-radius:4px;">
                    <span>๐“… <b>เธเธถเนเธ:</b> {ready_display_txt}</span>
                </div>
                '''

            machine_status_cards.append({
                "machine": m,
                "status": "IDLE",
                "card_class": "tv-card tv-card-idle",
                "badge_html": '<b style="color:#94A3B8;">โช เน€เธเธฃเธทเนเธญเธเธงเนเธฒเธ (IDLE)</b>',
                "plan": "เธเธฃเนเธญเธกเธฃเธฑเธเธเธฒเธ",
                "drawing": next_txt,
                "step": "-",
                "time_info": f"<div style='font-size:11.5px; font-weight:600; color:#CBD5E1;'>๐“ เธเธดเธงเธฃเธญ: {len(waiting_jobs)} เธเธฒเธ</div>{next_dates_html}"
            })

    st.markdown(f"""
    <div style="background:#0F172A; border:2px solid #1E3A8A; border-radius:16px; padding:12px 20px; color:white; display:flex; justify-content:space-between; align-items:center; margin-bottom:12px; box-shadow:0 8px 24px rgba(0,0,0,0.3);">
        <div>
            <div style="font-size:21px; font-weight:800; color:#38BDF8; display:flex; align-items:center; gap:10px;">
                <span>๐“บ PES SHOP FLOOR LIVE MONITOR (22 เธชเธ–เธฒเธเธต)</span>
                <span style="font-size:11.5px; background:#1E293B; border:1px solid #38BDF8; color:#38BDF8; padding:2px 8px; border-radius:16px;">Auto 30s</span>
            </div>
            <div style="color:#94A3B8; font-size:12.5px; margin-top:2px;">
                เธชเธ–เธฒเธเธฐเธเธฒเธฃเธเธฅเธดเธ• 22 เธชเธ–เธฒเธเธตเธเธฒเธเนเธเธ Real-time | เธเธฃเธฐเธเธณเธงเธฑเธเธ—เธตเน <b>{cur_date_str}</b>
            </div>
        </div>
        <div style="text-align:right;">
            <div id="live-tv-clock" style="font-size:26px; font-weight:900; color:#F8FAFC; font-family:monospace; letter-spacing:1px;">--:--:-- เธ.</div>
            <div style="font-size:12.5px; font-weight:bold;">
                <span style="color:#34D399;">๐ข เธเธณเธฅเธฑเธเธฃเธฑเธ {running_machines_count}</span> | 
                <span style="color:#FBBF24;">๐ก เธเธฑเธเธเธฒเธ {hold_machines_count}</span> | 
                <span style="color:#94A3B8;">โช เธงเนเธฒเธ {idle_machines_count}</span>
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
            f'<div style="font-size:13px; font-weight:700; color:#FFFFFF; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">๐“ {c["plan"]}</div>'
            f'<div style="font-size:11.5px; color:rgba(255,255,255,0.88); white-space:nowrap; overflow:hidden; text-overflow:ellipsis; margin-top:1px;">๐“ {c["drawing"]}</div>'
            f'<div style="font-size:11px; color:rgba(255,255,255,0.72); margin-top:1px;">โ๏ธ เธเธฑเนเธเธ•เธญเธ: {c["step"]}</div>'
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
# JavaScript เธ—เนเธฒเธขเนเธเธฅเน: เธเธฒเธฌเธดเธเธฒ + Live Stopwatch
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
                clockEl.innerText = hrs + ":" + mins + ":" + secs + " เธ.";
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
