import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime, timedelta
import zoneinfo
import os
import base64
from PIL import Image
import requests
import streamlit.components.v1 as components

# =========================================================
# 0. Timezone Helper (เวลาประเทศไทย GMT+7)
# =========================================================
def get_bangkok_now():
    try:
        return datetime.now(zoneinfo.ZoneInfo("Asia/Bangkok"))
    except Exception:
        return datetime.utcnow() + timedelta(hours=7)

def get_bangkok_str():
    return get_bangkok_now().strftime("%Y-%m-%d %H:%M:%S")

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

logo_base64 = None
for fname in ["Logo_Pes.png", "logo.png", "logo.jpg", r"D:\Python\Logo_Pes.png"]:
    if os.path.exists(fname):
        with open(fname, "rb") as f:
            logo_base64 = base64.b64encode(f.read()).decode("utf-8")
        break

if logo_base64:
    logo_html = f'<img src="data:image/png;base64,{logo_base64}" class="header-logo" alt="Logo"/>'
else:
    logo_html = '<div class="header-logo-icon">🏭</div>'

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
        background: linear-gradient(135deg, #0F2B5C 0%, #1E4E8C 100%);
        padding: 14px 18px;
        border-radius: 14px;
        color: white;
        margin-bottom: 12px;
        display: flex;
        align-items: center;
        gap: 16px;
        box-shadow: 0 4px 14px rgba(15, 43, 92, 0.25);
    }
    .header-logo {
        width: 110px;
        max-height: 75px;
        height: auto;
        object-fit: contain;
        display: block;
        flex-shrink: 0;
        background: transparent !important;
        filter: drop-shadow(0 2px 5px rgba(0,0,0,0.25));
    }
    .header-text h1 {
        color: #FFFFFF !important;
        font-size: 16.5px !important;
        margin: 0 !important;
        font-weight: 800 !important;
        line-height: 1.25 !important;
    }
    .header-text p {
        color: #D6E4FF !important;
        margin: 4px 0 0 0 !important;
        font-size: 11px !important;
    }

    .kpi-container {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
        gap: 10px;
        margin-bottom: 16px;
    }
    .kpi-card {
        padding: 14px 16px;
        border-radius: 12px;
        color: white;
        box-shadow: 0 3px 8px rgba(0,0,0,0.08);
    }
    .kpi-green { background: linear-gradient(135deg, #11998e 0%, #38ef7d 100%); }
    .kpi-blue { background: linear-gradient(135deg, #2193b0 0%, #6dd5ed 100%); }
    .kpi-orange { background: linear-gradient(135deg, #f12711 0%, #f5af19 100%); }
    .kpi-purple { background: linear-gradient(135deg, #8A2387 0%, #E94057 50%, #F27121 100%); }
    
    .kpi-title { 
        font-size: 13.5px !important; 
        font-weight: 700 !important; 
        margin-bottom: 4px;
        opacity: 0.95;
    }
    .kpi-value { 
        font-size: 22px !important; 
        font-weight: 800 !important; 
    }

    .op-job-header {
        background: #FFFFFF;
        padding: 14px 16px;
        border-radius: 12px;
        border-left: 6px solid #2563EB;
        border-top: 1.5px solid #E2E8F0;
        border-right: 1.5px solid #E2E8F0;
        border-bottom: 1.5px solid #E2E8F0;
        margin-top: 16px;
        margin-bottom: 14px;
        box-shadow: 0 2px 6px rgba(0,0,0,0.03);
    }

    .step-card {
        background: #FFFFFF;
        padding: 12px 14px;
        border-radius: 10px;
        border: 1.5px solid #E2E8F0;
        margin-bottom: 12px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.02);
    }

    div.stButton > button:disabled {
        background-color: #F1F5F9 !important;
        color: #94A3B8 !important;
        border-color: #CBD5E1 !important;
        cursor: not-allowed !important;
    }

    [data-testid="data-grid-canvas"] {
        outline: none !important;
    }
</style>
""", unsafe_allow_html=True)

header_content = f'''<div class="main-header">{logo_html}<div class="header-text"><h1>ระบบติดตามและบันทึกงานหน้าเครื่องแผนกผลิต</h1><p>CNC (9 เครื่อง), เครื่องเจียร (2 เครื่อง), มิลลิ่ง (4 เครื่อง), เครื่องกลึง (1 เครื่อง) และแผนกเชื่อม (1 แผนก)</p></div></div>'''
st.markdown(header_content, unsafe_allow_html=True)

# =========================================================
# 3. กำหนดสิทธิ์และความปลอดภัย & รายชื่อเครื่องจักรและแผนก
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
JOB_STATUS = ["🟧 รอคิวผลิต", "🟦 กำลังผลิต", "🟩 เสร็จสิ้นแล้ว"]

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
        res = requests.post(endpoint, headers=get_supabase_headers(), json=payload, timeout=6)
        if res.status_code in [200, 201]:
            st.cache_data.clear()
            return True
        else:
            if "qty" in payload:
                payload_no_qty = {k: v for k, v in payload.items() if k != "qty"}
                res2 = requests.post(endpoint, headers=get_supabase_headers(), json=payload_no_qty, timeout=6)
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
        res = requests.patch(endpoint, headers=get_supabase_headers(), json=payload, timeout=6)
        if res.status_code in [200, 204]:
            st.cache_data.clear()
            return True
        else:
            if "qty" in payload:
                payload_no_qty = {k: v for k, v in payload.items() if k != "qty"}
                res2 = requests.patch(endpoint, headers=get_supabase_headers(), json=payload_no_qty, timeout=6)
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
        res = requests.delete(endpoint, headers=get_supabase_headers(), timeout=6)
        st.cache_data.clear()
        return res.status_code in [200, 204]
    except Exception:
        return False

def safe_parse_datetime(series):
    dt = pd.to_datetime(series, format='ISO8601', errors='coerce')
    try:
        return dt.dt.tz_localize(None)
    except Exception:
        try:
            return dt.dt.tz_convert(None)
        except Exception:
            return dt

def normalize_status(status_str: str) -> str:
    s = str(status_str)
    if "กำลังผลิต" in s:
        return "🟦 กำลังผลิต"
    elif "เสร็จสิ้น" in s:
        return "🟩 เสร็จสิ้นแล้ว"
    else:
        return "🟧 รอคิวผลิต"

@st.cache_data(ttl=2, show_spinner=False)
def fetch_jobs_from_supabase() -> pd.DataFrame:
    try:
        base_url = st.secrets["SUPABASE_URL"].rstrip("/")
        endpoint = f"{base_url}/rest/v1/cnc_jobs?select=*&order=id.asc"
        res = requests.get(endpoint, headers=get_supabase_headers(), timeout=6)
        
        if res.status_code == 200:
            data = res.json()
            if isinstance(data, list) and len(data) > 0:
                df = pd.DataFrame(data)
                df["ready_at"] = safe_parse_datetime(df["ready_at"])
                if "actual_start" in df.columns:
                    df["actual_start"] = safe_parse_datetime(df["actual_start"])
                if "actual_finish" in df.columns:
                    df["actual_finish"] = safe_parse_datetime(df["actual_finish"])
                
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
    m_available = {m: default_start_datetime for m in MACHINE_LIST}
    m_last_mat = {m: None for m in MACHINE_LIST}
    m_busy_hrs = {m: 0.0 for m in MACHINE_LIST}
    
    active_mask = jobs_df["สถานะงาน"].isin(["🟧 รอคิวผลิต", "🟦 กำลังผลิต", "⏳ รอคิวผลิต", "⚙️ กำลังผลิต"])
    valid_jobs = []
    for j in jobs_df[active_mask].to_dict("records"):
        try:
            basic_mins = max(float(j.get("Basic (น.)", 0.0)), 0.0)
            prog_mins = max(float(j.get("โปรแกรม (น.)", 0.0)), 0.0)
            setup_mins = max(float(j.get("Setup (น.)", 15.0)), 0.0)
            
            cut_mins = basic_mins + prog_mins
            cut_hrs = (cut_mins / 60.0) if cut_mins > 0 else 0.01
            
            j["basic_mins"] = basic_mins
            j["prog_mins"] = prog_mins
            j["setup_mins"] = setup_mins
            j["cut_hrs"] = cut_hrs
        except (ValueError, TypeError):
            j["basic_mins"], j["prog_mins"], j["setup_mins"], j["cut_hrs"] = 0.0, 0.0, 15.0, 0.01
            
        ready_time = j.get("วัน-เวลาขึ้นงาน")
        if pd.isna(ready_time):
            j["ready_at"] = default_start_datetime
        else:
            dt_val = pd.to_datetime(ready_time, errors='coerce')
            j["ready_at"] = default_start_datetime if pd.isna(dt_val) else dt_val.to_pydatetime()
            
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
        cur_time = m_available[earliest_m]
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
                target_jump = min(future_candidates)
                idle_hrs = (target_jump - cur_time).total_seconds() / 3600.0
                if idle_hrs > 0.05:
                    gantt_records.append({
                        "ข้อความบนแท่งกราฟ": f"รอรันงาน ({idle_hrs:.2f} ชม.)",
                        "แผนงาน": "-",
                        "ชื่อ Drawing.": "รอคิวขึ้นงาน",
                        "จำนวน": "-",
                        "ขั้นตอน (Step)": "รอรันงาน",
                        "กิจกรรม": "⚪ รอรันงาน",
                        "เครื่องจักร": earliest_m,
                        "วัสดุ": "-",
                        "เวลาเริ่ม": cur_time,
                        "เวลาเสร็จ": target_jump,
                        "ระยะเวลา": f"{idle_hrs:.2f} ชม.",
                    })
                m_available[earliest_m] = target_jump
            else:
                m_available[earliest_m] = cur_time + timedelta(minutes=15)
            continue
            
        urgent_pool = [j for j in ready_candidates if j["is_urgent"]]
        if urgent_pool:
            selected_job = urgent_pool[0]
        else:
            same_mat = [j for j in ready_candidates if j["วัสดุ"] == last_mat]
            selected_job = same_mat[0] if same_mat else ready_candidates[0]

        setup_mins = selected_job["setup_mins"] if selected_job["need_setup"] else 0
        setup_start = cur_time
        setup_end = setup_start + timedelta(minutes=setup_mins)
        cut_start = setup_end
        actual_cut_hrs = selected_job["remain_cut_hrs"]
        cut_end = cut_start + timedelta(hours=actual_cut_hrs)
        
        step_raw = str(selected_job.get("ขั้นตอน (Step)", "รอหน้าเครื่องระบุ"))
        job_code = str(selected_job.get('แผนงาน', '-'))
        drawing_name = str(selected_job.get("ชื่อ Drawing.", "-"))
        qty_val = str(selected_job.get("จำนวน", 1))
        
        if setup_mins > 0:
            gantt_records.append({
                "ข้อความบนแท่งกราฟ": "Setup", "แผนงาน": job_code, "ชื่อ Drawing.": drawing_name,
                "จำนวน": qty_val, "ขั้นตอน (Step)": step_raw, "กิจกรรม": "🔧 ตั้งเครื่อง / เซ็ตศูนย์",
                "เครื่องจักร": earliest_m, "วัสดุ": selected_job.get("วัสดุ", "-"),
                "เวลาเริ่ม": setup_start, "เวลาเสร็จ": setup_end, "ระยะเวลา": f"{setup_mins:.0f} นาที"
            })
            
        gantt_records.append({
            "ข้อความบนแท่งกราฟ": step_raw, "แผนงาน": job_code, "ชื่อ Drawing.": drawing_name,
            "จำนวน": qty_val, "ขั้นตอน (Step)": step_raw,
            "กิจกรรม": "🔴 งานด่วนตัดเฉือน" if selected_job["is_urgent"] else "⚙️ งานปกติกำลังกัดงาน",
            "เครื่องจักร": earliest_m, "วัสดุ": selected_job.get("วัสดุ", "-"),
            "เวลาเริ่ม": cut_start, "เวลาเสร็จ": cut_end, "ระยะเวลา": f"{actual_cut_hrs:.2f} ชม."
        })
        
        total_cycle = (setup_mins / 60.0) + actual_cut_hrs
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
            
    start_anchor = min((j["เวลาเริ่มจริง"] for j in summary_records), default=default_start_datetime)
    max_finish = max(m_available.values()) if summary_records else default_start_datetime
    total_horizon_hrs = max((max_finish - start_anchor).total_seconds() / 3600.0, 1.0)
    
    util_list = []
    for m in MACHINE_LIST:
        busy = m_busy_hrs[m]
        util_pct = min((busy / total_horizon_hrs) * 100.0, 100.0) if total_horizon_hrs > 0 else 0.0
        util_list.append({
            "เครื่องจักร": m, "ชั่วโมงทำงาน (ชม.)": round(busy, 2),
            "อัตราการใช้งาน (%)": round(util_pct, 1), "ข้อความแสดง": f"{util_pct:.1f}% ({busy:.2f} ชม.)"
        })
        
    return pd.DataFrame(gantt_records), pd.DataFrame(summary_records), pd.DataFrame(util_list), total_horizon_hrs

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
# VIEW 1: หน้าจอช่างหน้าเครื่อง (ระบุและแก้ไขขั้นตอนได้ที่นี่)
# ---------------------------------------------------------
if st.session_state.current_view == "👷 โหมดช่างหน้าเครื่อง":
    st.markdown("### 📱 บันทึกสถานะงานหน้าเครื่อง / แผนกผลิต")
    
    df_all = fetch_jobs_from_supabase()
    selected_m = st.selectbox("🏭 เลือกเครื่องจักร / แผนก:", MACHINE_LIST, key="op_machine_select")
    
    if not df_all.empty:
        m_all_jobs = df_all[df_all["เลือกเครื่องจักร"] == selected_m].sort_values(by="ID", ascending=True)
        m_active_jobs = m_all_jobs[m_all_jobs["สถานะงาน"].isin(["🟦 กำลังผลิต", "🟧 รอคิวผลิต", "⚙️ กำลังผลิต", "⏳ รอคิวผลิต"])]
    else:
        m_all_jobs = pd.DataFrame()
        m_active_jobs = pd.DataFrame()

    if not m_active_jobs.empty:
        unique_plan_codes = sorted(list(m_active_jobs["แผนงาน"].dropna().unique()))

        machine_any_running = any("กำลังผลิต" in str(r.get("สถานะงาน", "")) for _, r in m_all_jobs.iterrows())
        next_available_start_found = False

        for plan_idx, plan_code in enumerate(unique_plan_codes, 1):
            plan_steps = m_all_jobs[m_all_jobs["แผนงาน"] == plan_code]
            first_step_info = plan_steps.iloc[0]

            st.markdown(f"""
            <div class="op-job-header">
                <div style="display:flex; justify-content:space-between; align-items:center;">
                    <h3 style="margin:0; color:#1E3A8A; font-size:19px; font-weight:800;">📌 แผนงาน {plan_idx}: {plan_code}</h3>
                    <span style="background:#EFF6FF; color:#1D4ED8; padding:3px 10px; border-radius:6px; font-weight:700; font-size:12px;">สถานี: {selected_m}</span>
                </div>
                <p style="font-size:14.5px; margin:5px 0 2px 0;"><b>📄 Drawing:</b> {first_step_info.get('ชื่อ Drawing.', '-')} | <b>🔢 จำนวน:</b> {int(first_step_info.get('จำนวน', 1) or 1)} ชิ้น | <b>🔩 วัสดุ:</b> {first_step_info.get('วัสดุ', '-')}</p>
            </div>
            """, unsafe_allow_html=True)

            st.markdown(f"**📋 รายการขั้นตอนและปุ่มควบคุม (แผนงาน: {plan_code}):**")

            for idx, (_, step_row) in enumerate(plan_steps.iterrows(), 1):
                s_id = int(step_row["ID"])
                raw_s_name = str(step_row.get("ขั้นตอน (Step)", f"OP{idx*10}"))
                s_name = raw_s_name if raw_s_name not in ["", "None", "nan", "รอหน้าเครื่องระบุ"] else f"OP{idx*10}"
                s_status = str(step_row.get("สถานะงาน", "🟧 รอคิวผลิต"))
                s_start = step_row.get("เริ่มจริง")
                s_finish = step_row.get("เสร็จจริง")
                
                is_step_running = "กำลังผลิต" in s_status
                is_step_finished = "เสร็จสิ้น" in s_status
                is_step_waiting = not is_step_running and not is_step_finished

                can_start = False
                if is_step_waiting and not machine_any_running and not next_available_start_found:
                    can_start = True
                    next_available_start_found = True

                with st.container():
                    st.markdown("<div class='step-card'>", unsafe_allow_html=True)
                    
                    if is_step_finished:
                        finish_txt = pd.to_datetime(s_finish).strftime('%d/%m %H:%M') if pd.notna(s_finish) else '-'
                        st.caption(f"**Step {idx}:** <span style='color:#059669; font-weight:700;'>🟩 เสร็จสิ้นแล้ว (จบงาน: {finish_txt})</span>", unsafe_allow_html=True)
                    elif is_step_running:
                        start_txt = pd.to_datetime(s_start).strftime('%d/%m %H:%M') if pd.notna(s_start) else '-'
                        st.caption(f"**Step {idx}:** <span style='color:#2563EB; font-weight:800;'>🟦 กำลังผลิต (เริ่มรัน: {start_txt})</span>", unsafe_allow_html=True)
                    else:
                        if can_start:
                            st.caption(f"**Step {idx}:** <span style='color:#D97706; font-weight:700;'>🟧 พร้อมเริ่มงาน (Ready)</span>", unsafe_allow_html=True)
                        else:
                            st.caption(f"**Step {idx}:** <span style='color:#64748B; font-weight:600;'>🔒 รอลำดับขั้นตอนก่อนหน้า</span>", unsafe_allow_html=True)

                    if not is_step_finished:
                        step_val = st.text_input(
                            f"ชื่อขั้นตอน Step {idx}:", 
                            value=s_name, 
                            placeholder="เช่น OP10, ปาดผิวเจาะรู, กลึง, เชื่อมประกอบ, เจียร", 
                            key=f"input_step_name_{s_id}"
                        )

                        c_btn_save, c_btn_start, c_btn_finish = st.columns([1.5, 2, 2])

                        with c_btn_save:
                            if st.button("💾 บันทึกชื่อ", key=f"btn_save_edit_{s_id}", use_container_width=True, help="บันทึกชื่อขั้นตอนใหม่"):
                                update_payload = {
                                    "step_name": step_val.strip() if step_val.strip() != "" else f"OP{idx*10}"
                                }
                                if update_supabase_job(s_id, update_payload):
                                    st.toast(f"บันทึกชื่อ Step {idx} เรียบร้อย!", icon="💾")
                                    st.rerun()

                        with c_btn_start:
                            if can_start:
                                if st.button("🚀 Start (เริ่มจับเวลาจริง)", key=f"btn_start_step_{s_id}", type="primary", use_container_width=True):
                                    now_str = get_bangkok_str()
                                    update_payload = {
                                        "step_name": step_val.strip() if step_val.strip() != "" else f"OP{idx*10}",
                                        "status": "🟦 กำลังผลิต",
                                        "actual_start": now_str
                                    }
                                    if update_supabase_job(s_id, update_payload):
                                        st.toast(f"เริ่มผลิตและบันทึกเวลาเริ่มจริงแล้ว!", icon="🚀")
                                        st.rerun()
                            else:
                                st.button("🚀 Start", key=f"btn_start_disabled_{s_id}", disabled=True, use_container_width=True)

                        with c_btn_finish:
                            if is_step_running:
                                if st.button("🏁 Finish (จบงานจริง)", key=f"btn_finish_step_{s_id}", type="primary", use_container_width=True):
                                    now_dt = get_bangkok_now()
                                    now_str = now_dt.strftime("%Y-%m-%d %H:%M:%S")
                                    
                                    calc_prog_mins = 0.0
                                    if pd.notna(s_start):
                                        st_dt = pd.to_datetime(s_start)
                                        st_dt = st_dt.tz_localize(None) if st_dt.tzinfo else st_dt
                                        cur_dt = now_dt.replace(tzinfo=None)
                                        calc_prog_mins = round((cur_dt - st_dt).total_seconds() / 60.0, 1)
                                    
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
            
            with st.expander(f"➕ เพิ่ม Step ถัดไปสำหรับแผนงาน {plan_code} (Step {next_step_num})", expanded=False):
                new_step_input = st.text_input("ชื่อ Step ถัดไป:", value=default_next_step_label, placeholder="เช่น OP20, กลึง, เจียร, เชื่อม", key=f"new_step_name_input_{plan_code}_{plan_idx}")

                if st.button(f"➕ บันทึกเพิ่ม Step {next_step_num} เข้าคิวแผน {plan_code}", key=f"btn_add_step_{plan_code}_{plan_idx}", type="secondary", use_container_width=True):
                    now_str = get_bangkok_str()
                    new_payload = {
                        "plan_code": str(plan_code),
                        "drawing_name": str(first_step_info.get("ชื่อ Drawing.", "")),
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
                        st.toast(f"เพิ่มขั้นตอน {new_step_input} เข้าสู่แผนงาน {plan_code} แล้ว!", icon="🚀")
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
        # =====================================================
        # 1. แดชบอร์ดภาพรวมโรงงานและการคำนวณต้นทุน (Management Only)
        # =====================================================
        c_head, c_logout = st.columns([8, 2])
        with c_head:
            st.subheader("📊 แดชบอร์ดภาพรวมโรงงานและการคำนวณต้นทุน (Management Only)")
        with c_logout:
            if st.button("🚪 ออกจากระบบ", use_container_width=True):
                st.session_state.is_admin = False
                st.session_state.current_view = "👷 โหมดช่างหน้าเครื่อง"
                st.rerun()

        df_db = fetch_jobs_from_supabase()

        # ส่วนเพิ่มงานใหม่เข้าระบบ (Form นาที) -> ระบุเป็น "รอหน้าเครื่องระบุ"
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
            
            calc_df["Setup (น.)"] = calc_df["Setup (น.)"].apply(lambda x: float(x) if pd.notna(x) else 0.0)
            calc_df["Basic (น.)"] = calc_df["Basic (น.)"].apply(lambda x: float(x) * 60.0 if (pd.notna(x) and float(x) < 10 and float(x) > 0 and float(x) != int(float(x))) else (float(x) if pd.notna(x) else 0.0))
            calc_df["โปรแกรม (น.)"] = calc_df["โปรแกรม (น.)"].apply(lambda x: float(x) * 60.0 if (pd.notna(x) and float(x) < 10 and float(x) > 0 and float(x) != int(float(x))) else (float(x) if pd.notna(x) else 0.0))
            
            calc_df["รวม (ชม.)"] = ((calc_df["Setup (น.)"] + calc_df["Basic (น.)"] + calc_df["โปรแกรม (น.)"]) / 60.0).round(2)

            column_order = [
                "ID", "แผนงาน", "ชื่อ Drawing.", "จำนวน", "วัสดุ", "ประเภทงาน", "ขั้นตอน (Step)",
                "เลือกเครื่องจักร", "วัน-เวลาขึ้นงาน", "Setup (น.)",
                "Basic (น.)", "โปรแกรม (น.)", "รวม (ชม.)", "สถานะงาน",
            ]
            calc_df = calc_df[[c for c in column_order if c in calc_df.columns]]

            active_jobs_editor_df = calc_df[calc_df["สถานะงาน"].isin(["🟧 รอคิวผลิต", "🟦 กำลังผลิต", "⏳ รอคิวผลิต", "⚙️ กำลังผลิต"])].sort_values(by="แผนงาน", ascending=True).copy().reset_index(drop=True)
            
            for idx_row in active_jobs_editor_df.index:
                row_status = str(active_jobs_editor_df.at[idx_row, "สถานะงาน"])
                row_step = str(active_jobs_editor_df.at[idx_row, "ขั้นตอน (Step)"])
                if "รอคิวผลิต" in row_status and (row_step in ["", "None", "nan", "OP10", "OP20", "OP30", "OP40", "OP50", "(รอช่างหน้าเครื่องระบุ)"]):
                    active_jobs_editor_df.at[idx_row, "ขั้นตอน (Step)"] = "รอหน้าเครื่องระบุ"

            active_jobs_editor_df["ลบ"] = st.session_state.active_select_all

            with st.expander("📝 รายการสั่งผลิตในระบบ (ตารางแก้ไข/เพิ่มแถวข้อมูล)", expanded=True):
                st.markdown("**📌 เครื่องมือจัดการตาราง:**")
                tool_col1, tool_col2, tool_col3 = st.columns([2.5, 4, 3.5])
                
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
                                    st.toast("แทรกแถวใหม่เข้าระบบสำเร็จ!", icon="🚀")
                                    st.rerun()

                grid_hash = f"{len(active_jobs_editor_df)}_{hash(tuple(active_jobs_editor_df['ID'].fillna(0)))}"
                edited_jobs = st.data_editor(
                    active_jobs_editor_df,
                    key=f"editor_cnc_jobs_grid_{grid_hash}_{st.session_state.active_select_all}",
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
                        "ขั้นตอน (Step)": st.column_config.TextColumn("ขั้นตอน (Step)", width=130, disabled=True, default="รอหน้าเครื่องระบุ", help="ช่องนี้ถูกล็อกไว้ ข้อมูลจะรับมาจากโหมดช่างหน้าเครื่องโดยตรง"),
                        "เลือกเครื่องจักร": st.column_config.SelectboxColumn("เลือกเครื่องจักร", width=160, options=ASSIGN_OPTIONS, default="No.1 Awea"),
                        "วัน-เวลาขึ้นงาน": st.column_config.DatetimeColumn("วัน-เวลาขึ้นงาน", width=145, format="YYYY-MM-DD HH:mm"),
                        "Setup (น.)": st.column_config.NumberColumn("Setup (น.)", width=85, min_value=0, max_value=720, step=5, format="%d", default=15),
                        "Basic (น.)": st.column_config.NumberColumn("Basic (น.)", width=85, min_value=0, max_value=6000, step=5, format="%d", default=0),
                        "โปรแกรม (น.)": st.column_config.NumberColumn("โปรแกรม (น.)", width=100, min_value=0, max_value=12000, step=10, format="%d", default=120),
                        "รวม (ชม.)": st.column_config.NumberColumn("รวม (ชม.)", width=85, format="%.2f", disabled=True),
                        "สถานะงาน": st.column_config.SelectboxColumn("สถานะงาน", width=130, options=JOB_STATUS, default="🟧 รอคิวผลิต"),
                        "ลบ": st.column_config.CheckboxColumn("🗑️", help="ติ๊กถูกช่องนี้เพื่อเลือกลบรายการ", width=55, default=False),
                    },
                    hide_index=True,
                    use_container_width=True
                )
                
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
                            
                            ready_dt = pd.to_datetime(row.get("วัน-เวลาขึ้นงาน"), errors='coerce')
                            ready_str = ready_dt.strftime("%Y-%m-%d %H:%M:%S") if pd.notna(ready_dt) else get_bangkok_str()
                            
                            step_val = str(row.get("ขั้นตอน (Step)", "รอหน้าเครื่องระบุ"))
                            if step_val in ["", "None", "nan"]:
                                step_val = "รอหน้าเครื่องระบุ"

                            try:
                                qty_int = int(row.get("จำนวน", 1) or 1)
                            except (ValueError, TypeError):
                                qty_int = 1

                            payload = {
                                "plan_code": p_code,
                                "drawing_name": d_name,
                                "qty": qty_int,
                                "material": str(row.get("วัสดุ", "SS400")),
                                "job_type": str(row.get("ประเภทงาน", "🟢 งานปกติ")),
                                "step_name": step_val,
                                "machine_name": str(row.get("เลือกเครื่องจักร", "No.1 Awea")),
                                "ready_at": ready_str,
                                "setup_mins": float(row.get("Setup (น.)", 15.0) or 15.0),
                                "basic_hrs": float(row.get("Basic (น.)", 0.0) or 0.0),
                                "prog_hrs": float(row.get("โปรแกรม (น.)", 0.0) or 0.0),
                                "status": str(row.get("สถานะงาน", "🟧 รอคิวผลิต"))
                            }
                            
                            row_id = row.get("ID")
                            if pd.notna(row_id) and str(row_id).strip() not in ["", "None", "nan"] and float(row_id) > 0:
                                update_supabase_job(int(row_id), payload)
                            else:
                                insert_supabase_job(payload)
                            save_count += 1

                        st.cache_data.clear()
                        st.success(f"บันทึกข้อมูลเรียบร้อยแล้ว ({save_count} รายการ)")
                        st.rerun()

                with c_del_top:
                    active_to_delete = edited_jobs[edited_jobs["ลบ"] == True]
                    if st.button(f"🗑️ ลบรายการที่เลือก ({len(active_to_delete)} รายการ)", type="secondary", disabled=(len(active_to_delete) == 0), use_container_width=True):
                        del_success = True
                        for _, row in active_to_delete.iterrows():
                            row_id = row.get("ID")
                            if pd.notna(row_id) and str(row_id).strip() not in ["", "None", "nan"] and float(row_id) > 0:
                                if not delete_supabase_job(int(row_id)):
                                    del_success = False
                        if del_success:
                            st.session_state.active_select_all = False
                            st.cache_data.clear()
                            st.toast("ลบรายการที่เลือกเรียบร้อยแล้ว", icon="🗑️")
                            st.rerun()
                        else:
                            st.error("เกิดข้อผิดพลาดในการลบข้อมูล")

            start_time = datetime(2026, 8, 20, 8, 0)
            df_gantt, df_summary, df_util, total_plan_hrs = calculate_shop_schedule(edited_jobs, start_time)

            finished_jobs_df = df_db[df_db["สถานะงาน"].isin(["🟩 เสร็จสิ้นแล้ว", "✅ เสร็จสิ้นแล้ว"])].copy()
            active_jobs_count = len(edited_jobs[edited_jobs["สถานะงาน"].isin(["🟧 รอคิวผลิต", "🟦 กำลังผลิต", "⏳ รอคิวผลิต", "⚙️ กำลังผลิต"])])
            avg_util = df_util["อัตราการใช้งาน (%)"].mean() if not df_util.empty else 0.0

            # แถบสรุป KPI
            kpi_html = f'''<div class="kpi-container"><div class="kpi-card kpi-green"><div class="kpi-title">✅ งานเสร็จสิ้น</div><div class="kpi-value">{len(finished_jobs_df)} <span style="font-size:15px; font-weight:600;">รายการ</span></div></div><div class="kpi-card kpi-blue"><div class="kpi-title">⚙️ งานในแผน</div><div class="kpi-value">{active_jobs_count} <span style="font-size:15px; font-weight:600;">รายการ</span></div></div><div class="kpi-card kpi-orange"><div class="kpi-title">⏱️ เวลาทั้งหมด</div><div class="kpi-value">{total_plan_hrs:.1f} <span style="font-size:15px; font-weight:600;">ชม.</span></div></div><div class="kpi-card kpi-purple"><div class="kpi-title">📊 การใช้เครื่อง</div><div class="kpi-value">{avg_util:.1f} %</div></div></div>'''
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
            if not df_summary.empty and not df_gantt.empty:
                st.subheader("📊 ผังเวลาขึ้นงานที่กำลังผลิตและรอคิว (Gantt Chart Timeline)")
                fig = px.timeline(
                    df_gantt,
                    x_start="เวลาเริ่ม",
                    x_end="เวลาเสร็จ",
                    y="เครื่องจักร",
                    color="กิจกรรม",
                    text="ข้อความบนแท่งกราฟ",
                    hover_data=["แผนงาน", "ชื่อ Drawing.", "จำนวน", "ขั้นตอน (Step)", "วัสดุ", "ระยะเวลา"],
                    category_orders={"เครื่องจักร": MACHINE_LIST},
                    color_discrete_map={
                        "🔧 ตั้งเครื่อง / เซ็ตศูนย์": "#FF7A00",
                        "⚙️ งานปกติกำลังกัดงาน": "#007AFF",
                        "🔴 งานด่วนตัดเฉือน": "#FF2D55",
                        "⚪ รอรันงาน": "#CBD5E1"
                    }
                )
                fig.update_yaxes(autorange="reversed")
                fig.update_traces(
                    textposition="inside",
                    insidetextanchor="middle",
                    marker_line_color="#FFFFFF",
                    marker_line_width=1
                )
                fig.update_layout(
                    height=650,
                    xaxis_title="วันและเวลา",
                    yaxis_title="เครื่องจักร / แผนก",
                    uniformtext_minsize=8,
                    uniformtext_mode='hide',
                    plot_bgcolor="#FFFFFF",
                    paper_bgcolor="#FFFFFF",
                    xaxis=dict(showgrid=True, gridcolor="#F1F5F9")
                )
                st.plotly_chart(fig, use_container_width=True)

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
                fig_bar.update_yaxes(autorange="reversed")
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
                    key="editor_machine_rates_full_17_v4",
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
