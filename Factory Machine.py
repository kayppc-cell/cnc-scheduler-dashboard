import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime, timedelta, time
import zoneinfo
import os
import base64
from PIL import Image
import requests
import streamlit.components.v1 as components

# =========================================================
# 0. Timezone Helper (GMT+7) & Factory Shift Rules
# =========================================================
def get_bangkok_now():
    try:
        return datetime.now(zoneinfo.ZoneInfo("Asia/Bangkok"))
    except Exception:
        return datetime.utcnow() + timedelta(hours=7)

def get_bangkok_str():
    return get_bangkok_now().strftime("%Y-%m-%d %H:%M:%S")

def parse_flexible_datetime(dt_val):
    """แปลงวันที่แบบยืดหยุ่นให้กลายเป็น Datetime แท้จริง 100%"""
    if pd.isna(dt_val):
        return None
    if isinstance(dt_val, (datetime, pd.Timestamp)):
        return dt_val
    s = str(dt_val).strip()
    if s in ["", "None", "nan", "-"]:
        return None
    
    current_year = get_bangkok_now().year
    # ถ้าระบุแค่วัน/เดือน (เช่น 28/08 17:30) ให้เติมปี ค.ศ. ปัจจุบันเข้าไป
    if "/" in s and len(s.split("/")[0]) <= 2:
        parts = s.split("/")
        if len(parts) == 2:
            s = f"{current_year}/{s}"
            
    dt_parsed = pd.to_datetime(s, errors='coerce', dayfirst=True)
    return dt_parsed if pd.notna(dt_parsed) else None

def get_day_working_windows(dt_date):
    weekday = dt_date.weekday()
    if weekday == 6:  # วันอาทิตย์
        return []
    elif weekday == 5:  # วันเสาร์
        return [
            (datetime.combine(dt_date, time(8, 0)), datetime.combine(dt_date, time(12, 0))),
            (datetime.combine(dt_date, time(13, 0)), datetime.combine(dt_date, time(17, 0)))
        ]
    else:  # จันทร์ - ศุกร์
        return [
            (datetime.combine(dt_date, time(8, 0)), datetime.combine(dt_date, time(12, 0))),
            (datetime.combine(dt_date, time(13, 0)), datetime.combine(dt_date, time(20, 0)))
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
        dt = datetime.combine(cur_date, time(8, 0))
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
    .badge-date { background: #F3E8FF; color: #6B21A8; border: 1px solid #E9D5FF; font-weight: 700; }
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
        border-color: #60A5FA !important;
        background: linear-gradient(145deg, #FFFFFF 0%, #EFF6FF 100%) !important;
        box-shadow: 0 4px 14px rgba(37, 99, 235, 0.12) !important;
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
</style>
""", unsafe_allow_html=True)

header_content = f'''<div class="main-header">{logo_html}<div class="header-text"><h1>ระบบติดตามและบันทึกงานหน้าเครื่องแผนกผลิต</h1><p>จ.-ศ. (08:00-20:00 น.) | ส. (08:00-17:00 น.) | พักเที่ยง 12:00-13:00 น. | หยุดวันอาทิตย์</p></div></div>'''
st.markdown(header_content, unsafe_allow_html=True)

# =========================================================
# 3. กำหนดสิทธิ์และความปลอดภัย & รายชื่อเครื่องจักร
# =========================================================
ADMIN_PASSWORD = "pesadmin"

if "is_admin" not in st.session_state:
    st.session_state.is_admin = False

if "current_view" not in st.session_state:
    st.session_state.current_view = "👷 โหมดช่างหน้าเครื่อง"

if "active_select_all" not in st.session_state:
    st.session_state.active_select_all = False

if "finish_select_all" not in st.session_state:
    st.session_state.finish_select_all = False

if "scroll_to_bottom" not in st.session_state:
    st.session_state.scroll_to_bottom = False

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
                
                # แปลงวัน-เวลาขึ้นงานให้เป็น Datetime แท้ๆ เพื่อใช้ Sort และจำลองคิวได้อย่างแม่นยำ
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

        try:
            basic_mins = max(float(j.get("Basic (น.)", 0.0) or 0.0), 0.0)
            prog_mins = max(float(j.get("โปรแกรม (น.)", 0.0) or 0.0), 0.0)
            setup_mins = max(float(j.get("Setup (น.)", 15.0) or 15.0), 0.0)
            
            cut_mins = basic_mins + prog_mins
            cut_hrs = (cut_mins / 60.0) if cut_mins > 0 else 0.01
            
            j["basic_mins"] = basic_mins
            j["prog_mins"] = prog_mins
            j["setup_mins"] = setup_mins
            j["cut_hrs"] = cut_hrs
        except (ValueError, TypeError):
            j["basic_mins"], j["prog_mins"], j["setup_mins"], j["cut_hrs"] = 0.0, 0.0, 15.0, 0.01
            
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
                m_available[earliest_m] = get_next_valid_work_time(min(future_candidates))
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
        
        raw_step = str(selected_job.get("ขั้นตอน (Step)", "รอหน้าเครื่องระบุ"))
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
            "แผนงาน": job_code, "ชื่อ Drawing.": drawing_name, "จำนวน": int(selected_job.get("จำนวน", 1) or 1),
            "วัสดุ": selected_job.get("วัสดุ", "-"), "ขั้นตอน (Step)": step_raw, "เวลาเริ่มจริง": setup_start,
            "เวลาเริ่ม Setup": setup_start.strftime("%d/%m %H:%M") if setup_mins > 0 else "-",
            "เวลาเริ่มขึ้นงาน": cut_start.strftime("%d/%m %H:%M"), "เวลาจบงาน": cut_end.strftime("%d/%m %H:%M"),
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
# 6. เมนูเปลี่ยนโหมด
# =========================================================
nav_options = ["👷 โหมดช่างหน้าเครื่อง", "📊 แดชบอร์ดภาพรวมโรงงาน"]
selected_tab = st.radio(
    "เลือกมุมมอง:",
    nav_options,
    index=nav_options.index(st.session_state.current_view),
    horizontal=True,
    label_visibility="collapsed"
)

if selected_tab != st.session_state.current_view:
    st.session_state.current_view = selected_tab
    st.rerun()

# ---------------------------------------------------------
# VIEW 1: หน้าจอช่างหน้าเครื่อง (แสดงป้ายวัน-เวลาขึ้นงานบนหัวการ์ด)
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

    if not df_all.empty:
        # กรองเฉพาะงานของเครื่องนี้ที่มีวัน-เวลาขึ้นงาน หรือกำลังรัน/พักงาน
        m_all_jobs = df_all[
            (df_all["เลือกเครื่องจักร"] == selected_m) &
            (df_all["วัน-เวลาขึ้นงาน"].notna() | df_all["สถานะงาน"].isin(["🟦 กำลังผลิต", "🟨 พักงาน (รอวัสดุ)"]))
        ].copy()
    else:
        m_all_jobs = pd.DataFrame()

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
                
                # หาเวลาขึ้นงานที่เร็วที่สุดของชุดงานนี้
                valid_ready_times = steps["วัน-เวลาขึ้นงาน"].dropna()
                earliest_ready = valid_ready_times.min() if not valid_ready_times.empty else pd.to_datetime("2099-01-01")
                min_id = steps["ID"].min()
                
                # ลำดับความสำคัญ: กำลังรัน (0) > ด่วน (1) > คิวปกติเรียงตามวันเวลา (2) > พักงาน (3)
                if is_running:
                    prio = 0
                elif is_urgent and not is_hold:
                    prio = 1
                elif not is_hold:
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

        # เรียงตาม ความสำคัญ -> วัน-เวลาขึ้นงาน (เดือน/วัน/เวลา) -> ID
        sorted_groups = sorted(group_meta, key=lambda x: (x["priority"], x["ready_at"], x["min_id"]))

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
                    now_dt = get_bangkok_now()
                    now_str = now_dt.strftime("%Y-%m-%d %H:%M:%S")
                    for _, r in running_jobs.iterrows():
                        s_start = r.get("เริ่มจริง")
                        calc_prog = 0.0
                        if pd.notna(s_start):
                            st_dt = pd.to_datetime(s_start)
                            calc_prog = round((now_dt.replace(tzinfo=None) - st_dt).total_seconds() / 60.0, 1)
                        p = {"status": "🟩 เสร็จสิ้นแล้ว", "actual_finish": now_str}
                        if calc_prog > 0: p["prog_hrs"] = calc_prog
                        update_supabase_job(int(r["ID"]), p)
                    st.toast("บันทึกจบงานจริงทุกคิวเรียบร้อย!", icon="🏁")
                    st.rerun()

        machine_any_running = any("กำลังผลิต" in str(r.get("สถานะงาน", "")) for _, r in m_all_jobs.iterrows())
        next_available_start_found = False

        if len(sorted_groups) == 0:
            st.info(f"🎉 สถานี {selected_m} ไม่มีคิวงานค้างในระบบ (ทุกงานเสร็จสิ้นครบหมดแล้ว หรือยังไม่มีการระบุวันขึ้นงาน)")
        else:
            for group_idx, g_info in enumerate(sorted_groups, 1):
                plan_code = g_info["plan_code"]
                drawing_code = g_info["drawing_name"]
                is_urgent = g_info["is_urgent"]
                is_hold = g_info["is_hold"]
                ready_at_dt = g_info["ready_at"]
                
                plan_steps = m_all_jobs[(m_all_jobs["แผนงาน"] == plan_code) & (m_all_jobs["ชื่อ Drawing."] == drawing_code)].sort_values(by="ID", ascending=True)
                first_step_info = plan_steps.iloc[0]
                mat_val = first_step_info.get('วัสดุ', '-')
                qty_val = int(first_step_info.get('จำนวน', 1) or 1)

                # จัดรูปแบบวันที่ขึ้นงานสำหรับแสดงบนหัวการ์ด
                if pd.notna(ready_at_dt) and ready_at_dt < pd.to_datetime("2099-01-01"):
                    ready_display_str = ready_at_dt.strftime("%d/%m/%Y %H:%M น.")
                else:
                    ready_display_str = "ยังไม่ระบุเวลา"

                if is_hold:
                    header_box_class = "op-job-header op-job-header-hold"
                    badge_gradient = "linear-gradient(135deg, #D97706 0%, #F59E0B 100%)"
                    status_badge_html = '<span class="badge-chip badge-hold">🛑 พักงาน (รอวัสดุใหม่)</span>'
                elif is_urgent:
                    header_box_class = "op-job-header op-job-header-urgent"
                    badge_gradient = "linear-gradient(135deg, #DC2626 0%, #EF4444 100%)"
                    status_badge_html = '<span class="badge-chip badge-urgent">🔥 🔴 งานด่วนแทรก</span>'
                else:
                    header_box_class = "op-job-header"
                    badge_gradient = "linear-gradient(135deg, #4F46E5 0%, #7C3AED 100%)"
                    status_badge_html = ''

                card_header_html = f'''<div class="{header_box_class}"><div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px;"><div style="font-size:20px; font-weight:800; color:#1E1B4B; display:flex; align-items:center; gap:8px;"><span style="background:{badge_gradient}; color:white; padding:4px 12px; border-radius:10px; font-size:14px; box-shadow:0 3px 8px rgba(0,0,0,0.15);">คิวที่ {group_idx}</span><span>แผนงาน: {plan_code}</span></div><span class="badge-chip badge-station">🏭 {selected_m}</span></div><div style="display:flex; flex-wrap:wrap; gap:6px; align-items:center;">{status_badge_html}<span class="badge-chip badge-date">📅 <b>กำหนดขึ้นงาน:</b> {ready_display_str}</span><span class="badge-chip badge-drawing">📄 <b>Drawing:</b> {drawing_code}</span><span class="badge-chip badge-qty">🔢 <b>จำนวน:</b> {qty_val} ชิ้น</span><span class="badge-chip badge-mat">🔩 <b>วัสดุ:</b> {mat_val}</span></div></div>'''
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
                            st.caption(f"**Step {idx}:** <span style='color:#2563EB; font-weight:800; font-size:13.5px;'>🟦 กำลังผลิต (เริ่มรัน: {start_txt}) ⏱️</span>", unsafe_allow_html=True)
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
                                        update_payload = {"step_name": step_val.strip() if step_val.strip() != "" else f"OP{idx*10}"}
                                        if update_supabase_job(s_id, update_payload):
                                            st.toast(f"บันทึกชื่อ Step {idx} เรียบร้อย!", icon="💾")
                                            st.rerun()
                                with c_btn_resume:
                                    if st.button("▶️ ได้วัสดุใหม่แล้ว (Resume เริ่มรันต่อ)", key=f"btn_resume_{s_id}", type="primary", use_container_width=True):
                                        now_str = get_bangkok_str()
                                        update_payload = {
                                            "step_name": step_val.strip() if step_val.strip() != "" else f"OP{idx*10}" if s_name in ["", "รอหน้าเครื่องระบุ"] else s_name,
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
                                        update_payload = {"step_name": step_val.strip() if step_val.strip() != "" else f"OP{idx*10}"}
                                        if update_supabase_job(s_id, update_payload):
                                            st.toast(f"บันทึกชื่อ Step {idx} เรียบร้อย!", icon="💾")
                                            st.rerun()
                                with c_btn_hold:
                                    if st.button("🛑 พักงาน (รอวัสดุใหม่)", key=f"btn_hold_{s_id}", use_container_width=True):
                                        update_payload = {
                                            "step_name": step_val.strip() if step_val.strip() != "" else f"OP{idx*10}",
                                            "status": "🟨 พักงาน (รอวัสดุ)"
                                        }
                                        if update_supabase_job(s_id, update_payload):
                                            st.toast("พักงานเรียบร้อย สามารถรันงานอื่นต่อได้ทันที!", icon="🛑")
                                            st.rerun()
                                with c_btn_finish:
                                    if st.button("🏁 Finish (จบงานจริง)", key=f"btn_finish_step_{s_id}", type="primary", use_container_width=True):
                                        now_dt = get_bangkok_now()
                                        now_str = now_dt.strftime("%Y-%m-%d %H:%M:%S")
                                        calc_prog_mins = 0.0
                                        if pd.notna(s_start):
                                            st_dt = pd.to_datetime(s_start)
                                            calc_prog_mins = round((now_dt.replace(tzinfo=None) - st_dt).total_seconds() / 60.0, 1)
                                        
                                        finish_payload = {
                                            "status": "🟩 เสร็จสิ้นแล้ว",
                                            "actual_finish": now_str
                                        }
                                        if calc_prog_mins > 0:
                                            finish_payload["prog_hrs"] = calc_prog_mins

                                        if update_supabase_job(s_id, finish_payload):
                                            st.toast(f"บันทึกเวลาจบจริง {s_name} เรียบร้อย!", icon="🏁")
                                            st.rerun()
                            else:
                                c_btn_save, c_btn_start, c_btn_finish = st.columns([1.5, 2, 2])
                                with c_btn_save:
                                    if st.button("💾 บันทึกชื่อ", key=f"btn_save_edit_{s_id}", use_container_width=True):
                                        update_payload = {"step_name": step_val.strip() if step_val.strip() != "" else f"OP{idx*10}"}
                                        if update_supabase_job(s_id, update_payload):
                                            st.toast(f"บันทึกชื่อ Step {idx} เรียบร้อย!", icon="💾")
                                            st.rerun()
                                with c_btn_start:
                                    if can_start:
                                        if st.button("🚀 Start (เริ่มจับเวลาจริง)", key=f"btn_start_step_{s_id}", type="primary", use_container_width=True):
                                            now_str = get_bangkok_str()
                                            update_payload = {
                                                "step_name": step_val.strip() if step_val.strip() != "" else f"OP{idx*10}" if s_name in ["", "รอหน้าเครื่องระบุ"] else s_name,
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
                        new_payload = {
                            "plan_code": str(plan_code),
                            "drawing_name": str(drawing_code),
                            "qty": int(first_step_info.get("จำนวน", 1) or 1),
                            "material": str(first_step_info.get("วัสดุ", "SS400")),
                            "job_type": str(first_step_info.get("ประเภทงาน", "🟢 งานปกติ")),
                            "step_name": new_step_input.strip() if new_step_input.strip() != "" else default_next_step_label,
                            "machine_name": selected_m,
                            "ready_at": now_str,
                            "setup_mins": 0.0,
                            "basic_hrs": 0.0,
                            "prog_hrs": 0.0,
                            "status": "🟧 รอคิวผลิต"
                        }
                        if insert_supabase_job(new_payload):
                            st.cache_data.clear()
                            st.toast(f"เพิ่มขั้นตอน {new_step_input} เรียบร้อยแล้ว!", icon="🚀")
                            st.rerun()
                
                st.write("")

    else:
        st.info(f"🎉 สถานี {selected_m} ไม่มีคิวงานค้างในระบบ")

# ---------------------------------------------------------
# VIEW 2: Dashboard ภาพรวมโรงงาน
# ---------------------------------------------------------
elif st.session_state.current_view == "📊 แดชบอร์ดภาพรวมโรงงาน":
    if not st.session_state.is_admin:
        st.subheader("🔒 ยืนยันตัวตนสำหรับผู้บริหารและผู้วางแผน")
        st.info("ส่วนของแดชบอร์ดภาพรวมและต้นทุนค่าเครื่องจักร ถูกสงวนสิทธิ์เฉพาะผู้บริหาร")
        col_pwd, col_btn = st.columns([3, 1])
        with col_pwd:
            input_pwd = st.text_input("รหัสผ่าน (Password):", type="password")
        with col_btn:
            st.write("")
            st.write("")
            if st.button("🔓 เข้าสู่ระบบ", type="primary", use_container_width=True):
                if input_pwd == ADMIN_PASSWORD:
                    st.session_state.is_admin = True
                    st.rerun()
                else:
                    st.error("รหัสผ่านไม่ถูกต้อง")
    else:
        c_head, c_logout = st.columns([8, 2])
        with c_head:
            st.subheader("📊 แดชบอร์ดภาพรวมโรงงานและการคำนวณต้นทุน (Management Only)")
        with c_logout:
            if st.button("🚪 ออกจากระบบ", use_container_width=True):
                st.session_state.is_admin = False
                st.session_state.current_view = "👷 โหมดช่างหน้าเครื่อง"
                st.rerun()

        df_db = fetch_jobs_from_supabase()

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
                    new_f_setup = st.number_input("เวลาตั้งเครื่อง Setup (นาที):", min_value=0, max_value=720, value=15, step=5)
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
            
            calc_df["Setup (น.)"] = pd.to_numeric(calc_df["Setup (น.)"], errors='coerce').fillna(15.0)
            calc_df["Basic (น.)"] = pd.to_numeric(calc_df["Basic (น.)"], errors='coerce').fillna(0.0)
            calc_df["โปรแกรม (น.)"] = pd.to_numeric(calc_df["โปรแกรม (น.)"], errors='coerce').fillna(0.0)
            
            calc_df["รวม (ชม.)"] = ((calc_df["Setup (น.)"] + calc_df["Basic (น.)"] + calc_df["โปรแกรม (น.)"]) / 60.0).round(2)

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

            # แปลงวัน-เวลาขึ้นงานเป็น String format สากล YYYY-MM-DD HH:MM
            active_jobs_editor_df["วัน-เวลาขึ้นงาน"] = active_jobs_editor_df["วัน-เวลาขึ้นงาน"].apply(
                lambda x: x.strftime("%Y-%m-%d %H:%M") if pd.notna(x) else ""
            )

            if "ลบ" not in active_jobs_editor_df.columns:
                active_jobs_editor_df["ลบ"] = st.session_state.active_select_all
            else:
                if st.session_state.active_select_all:
                    active_jobs_editor_df["ลบ"] = True

            with st.expander("📝 รายการสั่งผลิตในระบบ (ตารางแก้ไข/เพิ่มแถวข้อมูล)", expanded=True):
                st.markdown("**📌 เครื่องมือจัดการตาราง:**")
                tool_col1, tool_col2, _ = st.columns([2.5, 4, 3.5])
                
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
                            ins_setup = st.number_input("Setup (น.):", value=15, step=5)
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

                edited_jobs = st.data_editor(
                    active_jobs_editor_df,
                    key="editor_cnc_jobs_grid_main",
                    num_rows="dynamic",
                    column_order=[
                        "แผนงาน", "ชื่อ Drawing.", "จำนวน", "วัสดุ", "ประเภทงาน", "ขั้นตอน (Step)",
                        "เลือกเครื่องจักร", "วัน-เวลาขึ้นงาน", "Setup (น.)",
                        "Basic (น.)", "โปรแกรม (น.)", "รวม (ชม.)", "สถานะงาน", "ลบ"
                    ],
                    column_config={
                        "ID": st.column_config.Column(required=False),
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
                            help="พิมพ์เวลา เช่น 2026-08-28 17:30 หรือ 28/08 17:30 ถ้าลบว่างจะไม่ขึ้นคิว"
                        ),
                        "Setup (น.)": st.column_config.NumberColumn("Setup (น.)", width=85, min_value=0, max_value=720, step=5, format="%d", default=15),
                        "Basic (น.)": st.column_config.NumberColumn("Basic (น.)", width=85, min_value=0, max_value=6000, step=5, format="%d", default=0),
                        "โปรแกรม (น.)": st.column_config.NumberColumn("โปรแกรม (น.)", width=100, min_value=0, max_value=12000, step=10, format="%d", default=120),
                        "รวม (ชม.)": st.column_config.NumberColumn("รวม (ชม.)", width=85, format="%.2f", disabled=True),
                        "สถานะงาน": st.column_config.SelectboxColumn("สถานะงาน", width=145, options=JOB_STATUS, default="🟧 รอคิวผลิต"),
                        "ลบ": st.column_config.CheckboxColumn("🗑️", width=55, default=False),
                    },
                    hide_index=True,
                    use_container_width=True
                )
                
                st.markdown('<div id="editor_table_bottom_mark"></div>', unsafe_allow_html=True)

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
                        save_count = 0
                        for _, row in edited_jobs.iterrows():
                            raw_plan = row.get("แผนงาน")
                            if pd.isna(raw_plan) or str(raw_plan).strip() in ["", "None", "nan"]:
                                continue
                            
                            p_code = str(raw_plan).strip()
                            raw_draw = row.get("ชื่อ Drawing.")
                            d_name = "" if pd.isna(raw_draw) or str(raw_draw).strip() in ["None", "nan"] else str(raw_draw).strip()
                            
                            # แปลงวัน-เวลาให้เป็น ISO String ชัดเจน ป้องกันการหลุด format
                            raw_ready = row.get("วัน-เวลาขึ้นงาน")
                            dt_parsed = parse_flexible_datetime(raw_ready)
                            ready_str = dt_parsed.strftime("%Y-%m-%d %H:%M:%S") if dt_parsed is not None else None
                            
                            step_val = str(row.get("ขั้นตอน (Step)", "รอหน้าเครื่องระบุ"))
                            if step_val in ["", "None", "nan"]:
                                step_val = "รอหน้าเครื่องระบุ"

                            try: qty_int = int(row.get("จำนวน", 1) or 1)
                            except: qty_int = 1

                            try: s_val = float(row.get("Setup (น.)", 15.0) or 15.0)
                            except: s_val = 15.0
                            
                            try: b_val = float(row.get("Basic (น.)", 0.0) or 0.0)
                            except: b_val = 0.0
                            
                            try: p_val = float(row.get("โปรแกรม (น.)", 0.0) or 0.0)
                            except: p_val = 0.0

                            payload = {
                                "plan_code": p_code,
                                "drawing_name": d_name,
                                "qty": qty_int,
                                "material": str(row.get("วัสดุ", "SS400")),
                                "job_type": str(row.get("ประเภทงาน", "🟢 งานปกติ")),
                                "step_name": step_val,
                                "machine_name": str(row.get("เลือกเครื่องจักร", "No.1 Awea")),
                                "ready_at": ready_str,
                                "setup_mins": s_val,
                                "basic_hrs": b_val,
                                "prog_hrs": p_val,
                                "status": str(row.get("สถานะงาน", "🟧 รอคิวผลิต"))
                            }
                            
                            row_id = row.get("ID")
                            if pd.notna(row_id) and str(row_id).strip() not in ["", "None", "nan"] and float(row_id) > 0:
                                update_supabase_job(int(row_id), payload)
                            else:
                                insert_supabase_job(payload)
                            save_count += 1

                        st.cache_data.clear()
                        st.session_state.scroll_to_bottom = True
                        st.success(f"บันทึกข้อมูลเรียบร้อยแล้ว ({save_count} รายการ)")
                        st.rerun()

                with c_del_top:
                    btn_del_label = f"🗑️ ลบรายการที่เลือก ({delete_count} รายการ)" if delete_count > 0 else "🗑️ ลบรายการที่เลือก (0 รายการ)"
                    if st.button(btn_del_label, type="secondary", disabled=(delete_count == 0), use_container_width=True):
                        del_success = True
                        for _, row in active_to_delete.iterrows():
                            row_id = row.get("ID")
                            if pd.notna(row_id) and str(row_id).strip() not in ["", "None", "nan"] and float(row_id) > 0:
                                if not delete_supabase_job(int(row_id)):
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
            # 2. ใบจ่ายคิวงานหน้าเครื่อง (Work Order Sheet)
            # =====================================================
            if not df_summary.empty:
                st.subheader("📋 ใบจ่ายคิวงานหน้าเครื่อง (Work Order Sheet)")

                df_display = df_summary.sort_values(by="เวลาเริ่มจริง", ascending=True)
                display_cols = [c for c in df_display.columns if c != "เวลาเริ่มจริง" and c != "ID"]

                st.dataframe(
                    df_display[display_cols],
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
            # 3. รายการงานที่ Finish แล้ว และเช็คเวลาวางแผนเทียบกับเวลาจริง
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
                        variance = round(act_hrs - r["เวลาแผน (ชม.)"], 2)
                        actual_hrs_list.append(act_hrs)
                        diff_list.append(variance)
                        status_eval_list.append(f"🟢 เร็วกว่าแผน {abs(variance):.2f} ชม." if variance <= 0 else f"🔴 ช้ากว่าแผน +{variance:.2f} ชม.")
                    else:
                        actual_hrs_list.append(None)
                        diff_list.append(None)
                        status_eval_list.append("⚪ รอกดบันทึกเวลาจริง")
                        
                perf_df["เวลาจริง (ชม.)"] = actual_hrs_list
                perf_df["ผลต่าง (ชม.)"] = diff_list
                perf_df["การประเมิน"] = status_eval_list
                perf_df["ลบ"] = st.session_state.finish_select_all
                
                display_finish_df = perf_df.sort_values(by="แผนงาน", ascending=True)[["ID", "แผนงาน", "ชื่อ Drawing.", "จำนวน", "ขั้นตอน (Step)", "เลือกเครื่องจักร", "เริ่มจริง", "เสร็จจริง", "เวลาแผน (ชม.)", "เวลาจริง (ชม.)", "ผลต่าง (ชม.)", "การประเมิน", "ลบ"]].copy().reset_index(drop=True)

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
                        "เลือกเครื่องจักร": st.column_config.TextColumn("สถานีผลิต", disabled=True, width=140),
                        "เริ่มจริง": st.column_config.DatetimeColumn("เริ่มจริง", disabled=True, width=145, format="DD/MM HH:mm"),
                        "เสร็จจริง": st.column_config.DatetimeColumn("เวลาจบจริง", disabled=True, width=145, format="DD/MM HH:mm"),
                        "เวลาแผน (ชม.)": st.column_config.NumberColumn("แผน (ชม.)", disabled=True, width=90, format="%.2f"),
                        "เวลาจริง (ชม.)": st.column_config.NumberColumn("จริง (ชม.)", disabled=True, width=90, format="%.2f"),
                        "ผลต่าง (ชม.)": st.column_config.NumberColumn("Diff", disabled=True, width=80, format="%.2f"),
                        "การประเมิน": st.column_config.TextColumn("ผลการผลิต", disabled=True, width=160),
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
                                if not delete_supabase_job(int(row_id)):
                                    del_success = False
                        if del_success:
                            st.session_state.finish_select_all = False
                            st.cache_data.clear()
                            st.toast("ลบรายการที่เลือกเรียบร้อยแล้ว", icon="🗑️")
                            st.rerun()
                        else:
                            st.error("เกิดข้อผิดพลาดในการลบข้อมูล")

                st.divider()

            # =====================================================
            # 4. ผังเวลาขึ้นงานที่กำลังผลิตและรอคิว (Gantt Chart Timeline)
            # =====================================================
            if not df_gantt.empty:
                st.subheader("📊 ผังเวลาขึ้นงานที่กำลังผลิตและรอคิว (Gantt Chart Timeline)")
                
                gantt_f1, gantt_f2 = st.columns([3, 1])
                with gantt_f1:
                    m_filter_mode = st.radio(
                        "🔍 กรองกลุ่มสถานีงาน:",
                        ["🌐 ทุกสถานี (17 เครื่อง)", "⚙️ CNC (No.1 - No.9)", "🔧 เจียร/มิลลิ่ง/กลึง/เชื่อม (No.10 - No.17)"],
                        horizontal=True
                    )
                with gantt_f2:
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

                fig = px.timeline(
                    plot_gantt_df,
                    x_start="เวลาเริ่ม",
                    x_end="เวลาเสร็จ",
                    y="เครื่องจักร",
                    color=color_target,
                    text="ข้อความบนแท่งกราฟ",
                    custom_data=["แผนงาน", "ชื่อ Drawing.", "จำนวน", "ขั้นตอน (Step)", "วัสดุ", "เริ่มแสดง", "เสร็จแสดง", "ระยะเวลา", "กิจกรรม"],
                    category_orders={"เครื่องจักร": display_machines},
                    color_discrete_sequence=px.colors.qualitative.Bold if color_target == "แผนงาน" else None,
                    color_discrete_map={
                        "🔧 ตั้งเครื่อง / เซ็ตศูนย์": "#FF7A00",
                        "⚙️ งานปกติ": "#0284C7",
                        "🔴 งานด่วน": "#EF4444"
                    } if color_target == "กิจกรรม" else None
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
                
                fig.update_yaxes(
                    autorange="reversed",
                    type="category",
                    categoryorder="array",
                    categoryarray=display_machines,
                    showgrid=True,
                    gridcolor="#E2E8F0"
                )
                
                fig.update_xaxes(
                    showgrid=True,
                    gridcolor="#E2E8F0",
                    rangeselector=dict(
                        buttons=list([
                            dict(count=1, label="🔍 วันนี้", step="day", stepmode="backward"),
                            dict(count=3, label="📅 3 วัน", step="day", stepmode="backward"),
                            dict(count=7, label="📆 7 วัน", step="day", stepmode="backward"),
                            dict(step="all", label="🌐 ทั้งหมด")
                        ]),
                        font=dict(size=12, color="#1E293B"),
                        bgcolor="#F1F5F9",
                        activecolor="#DBEAFE"
                    )
                )

                if not plot_gantt_df.empty:
                    min_dt = plot_gantt_df["เวลาเริ่ม"].min()
                    max_dt = plot_gantt_df["เวลาเสร็จ"].max()
                    cur_d = min_dt.date()
                    while cur_d <= max_dt.date() + timedelta(days=1):
                        if cur_d.weekday() == 6:
                            sun_start = datetime.combine(cur_d, time(0, 0))
                            sun_end = datetime.combine(cur_d + timedelta(days=1), time(0, 0))
                            fig.add_vrect(
                                x0=sun_start, x1=sun_end,
                                fillcolor="#F8FAFC", opacity=0.8,
                                layer="below", line_width=1, line_color="#E2E8F0",
                                annotation_text="🛑 วันอาทิตย์ (หยุด)", annotation_position="top left",
                                annotation_font_size=10, annotation_font_color="#94A3B8"
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
                        <span style="color:#D97706;"><b>พักเบรกเที่ยง:</b> 12:00 – 13:00 น. (หยุดพักเครื่อง)</span>
                    </div>
                    <div class="schedule-pill">
                        <span style="font-size:16px;">🛑</span>
                        <span style="color:#DC2626;"><b>วันอาทิตย์:</b> หยุดทำการ (ข้ามไปวันจันทร์ 08:00 น.)</span>
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
                fig_bar.update_yaxes(
                    autorange="reversed",
                    type="category",
                    categoryorder="array",
                    categoryarray=MACHINE_LIST
                )
                fig_bar.update_traces(
                    marker_line_color="#0F172A",
                    marker_line_width=1.2,
                    textposition="outside",
                    cliponaxis=False
                )
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
