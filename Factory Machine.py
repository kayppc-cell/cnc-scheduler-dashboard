import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime, timedelta
import os
import base64
from PIL import Image
import requests
import streamlit.components.v1 as components

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
    page_title="PES CNC Monitor",
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

    .op-box {
        background: #FFFFFF;
        padding: 14px 16px;
        border-radius: 12px;
        border: 1.5px solid #E2E8F0;
        margin-bottom: 10px;
        box-shadow: 0 2px 6px rgba(0,0,0,0.03);
    }

    div.stButton > button:disabled {
        background-color: #E2E8F0 !important;
        color: #94A3B8 !important;
        border-color: #CBD5E1 !important;
        cursor: not-allowed !important;
    }
</style>
""", unsafe_allow_html=True)

header_content = f'''<div class="main-header">{logo_html}<div class="header-text"><h1>ระบบติดตามและบันทึกงานหน้าเครื่อง CNC</h1><p>Awea (2), Hartford (3), Sanco (1), Bridgeport (2), Mikron (1)</p></div></div>'''
st.markdown(header_content, unsafe_allow_html=True)

# =========================================================
# 3. กำหนดสิทธิ์และความปลอดภัย
# =========================================================
ADMIN_PASSWORD = "pesadmin"

if "is_admin" not in st.session_state:
    st.session_state.is_admin = False

if "current_view" not in st.session_state:
    st.session_state.current_view = "👷 โหมดช่างหน้าเครื่อง"

MACHINE_LIST = [
    "No.1 Awea", "No.2 Awea", "No.3 Hartford", "No.4 Sanco", "No.5 Hartford",
    "No.6 Bridgeport", "No.7 Bridgeport", "No.8 Hartford", "No.9 Mikron",
]

DEFAULT_RATES = {
    "No.1 Awea": 1200, "No.2 Awea": 1000, "No.3 Hartford": 1000, "No.4 Sanco": 1000,
    "No.5 Hartford": 1000, "No.6 Bridgeport": 600, "No.7 Bridgeport": 600, "No.8 Hartford": 600, "No.9 Mikron": 1300,
}

ASSIGN_OPTIONS = ["อัตโนมัติ (เครื่อง 3 แกนใดก็ได้)"] + MACHINE_LIST
JOB_TYPES = ["🟢 งานปกติ", "🔴 งานด่วนแทรก"]
JOB_STATUS = ["⏳ รอคิวผลิต", "⚙️ กำลังผลิต", "✅ เสร็จสิ้นแล้ว"]

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

def update_supabase_job(job_id: int, payload: dict) -> bool:
    try:
        base_url = st.secrets["SUPABASE_URL"].rstrip("/")
        endpoint = f"{base_url}/rest/v1/cnc_jobs?id=eq.{job_id}"
        res = requests.patch(endpoint, headers=get_supabase_headers(), json=payload, timeout=6)
        st.cache_data.clear()
        return res.status_code in [200, 204]
    except Exception:
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

def insert_supabase_job(payload: dict) -> bool:
    try:
        base_url = st.secrets["SUPABASE_URL"].rstrip("/")
        endpoint = f"{base_url}/rest/v1/cnc_jobs"
        res = requests.post(endpoint, headers=get_supabase_headers(), json=payload, timeout=6)
        st.cache_data.clear()
        return res.status_code in [200, 201]
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

@st.cache_data(ttl=4, show_spinner=False)
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
                    
                col_map = {
                    "id": "ID", "plan_code": "แผนงาน", "drawing_name": "ชื่อ Drawing.",
                    "material": "วัสดุ", "job_type": "ประเภทงาน", "step_name": "ขั้นตอน (Step)",
                    "machine_name": "เลือกเครื่องจักร", "ready_at": "วัน-เวลาขึ้นงาน",
                    "setup_mins": "เวลาตั้งเครื่อง (นาที)", "basic_hrs": "Basic Machine (ชม.)",
                    "prog_hrs": "รันโปรแกรม (ชม.)", "status": "สถานะงาน",
                    "actual_start": "เริ่มจริง", "actual_finish": "เสร็จจริง"
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
    
    active_mask = jobs_df["สถานะงาน"].isin(["⏳ รอคิวผลิต", "⚙️ กำลังผลิต"])
    valid_jobs = []
    for j in jobs_df[active_mask].to_dict("records"):
        try:
            basic_hrs = max(float(j.get("Basic Machine (ชม.)", 0.0)), 0.0)
            prog_hrs = max(float(j.get("รันโปรแกรม (ชม.)", 0.0)), 0.0)
            setup_mins = max(float(j.get("เวลาตั้งเครื่อง (นาที)", 15.0)), 0.0)
            cut_val = basic_hrs + prog_hrs
            j["basic_hrs"] = basic_hrs
            j["prog_hrs"] = prog_hrs
            j["cut_hrs"] = cut_val if cut_val > 0 else 0.1
            j["setup_mins"] = setup_mins
        except (ValueError, TypeError):
            j["basic_hrs"], j["prog_hrs"], j["cut_hrs"], j["setup_mins"] = 0.0, 0.0, 0.1, 15.0
            
        ready_time = j.get("วัน-เวลาขึ้นงาน")
        if pd.isna(ready_time):
            j["ready_at"] = default_start_datetime
        else:
            dt_val = pd.to_datetime(ready_time, errors='coerce')
            j["ready_at"] = default_start_datetime if pd.isna(dt_val) else dt_val.to_pydatetime()
            
        j["is_urgent"] = "ด่วนแทรก" in str(j.get("ประเภทงาน", ""))
        j["remain_cut_hrs"] = j["cut_hrs"]
        j["need_setup"] = j["สถานะงาน"] != "⚙️ กำลังผลิต"
        valid_jobs.append(j)
        
    gantt_records, summary_records = [], []
    
    while valid_jobs:
        pending_machines = set()
        for j in valid_jobs:
            target = j.get("เลือกเครื่องจักร", "")
            if target in MACHINE_LIST:
                pending_machines.add(target)
            elif target == "อัตโนมัติ (เครื่อง 3 แกนใดก็ได้)":
                for m in MACHINE_LIST:
                    if m != "No.9 Mikron": pending_machines.add(m)
                        
        if not pending_machines: break
        earliest_m = min(pending_machines, key=lambda m: m_available[m])
        cur_time = m_available[earliest_m]
        last_mat = m_last_mat[earliest_m]
        
        ready_candidates = [
            j for j in valid_jobs if (j.get("เลือกเครื่องจักร") == earliest_m or 
            (j.get("เลือกเครื่องจักร") == "อัตโนมัติ (เครื่อง 3 แกนใดก็ได้)" and earliest_m != "No.9 Mikron")) and j["ready_at"] <= cur_time
        ]
                    
        if not ready_candidates:
            future_candidates = [
                j["ready_at"] for j in valid_jobs if (j.get("เลือกเครื่องจักร") == earliest_m or 
                (j.get("เลือกเครื่องจักร") == "อัตโนมัติ (เครื่อง 3 แกนใดก็ได้)" and earliest_m != "No.9 Mikron")) and j["ready_at"] > cur_time
            ]
            if future_candidates:
                target_jump = min(future_candidates)
                idle_hrs = (target_jump - cur_time).total_seconds() / 3600.0
                if idle_hrs > 0.05:
                    gantt_records.append({
                        "ข้อความบนแท่งกราฟ": f"รอรันงาน ({idle_hrs:.1f} ชม.)",
                        "แผนงาน": "-",
                        "ชื่อ Drawing.": "รอคิวขึ้นงาน",
                        "ขั้นตอน (Step)": "รอรันงาน",
                        "กิจกรรม": "⚪ รอรันงาน",
                        "เครื่องจักร": earliest_m,
                        "วัสดุ": "-",
                        "เวลาเริ่ม": cur_time,
                        "เวลาเสร็จ": target_jump,
                        "ระยะเวลา": f"{idle_hrs:.1f} ชม.",
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
        
        step_raw = str(selected_job.get("ขั้นตอน (Step)", "OP10"))
        job_code = str(selected_job.get('แผนงาน', '-'))
        drawing_name = str(selected_job.get("ชื่อ Drawing.", "-"))
        
        if setup_mins > 0:
            gantt_records.append({
                "ข้อความบนแท่งกราฟ": "Setup", "แผนงาน": job_code, "ชื่อ Drawing.": drawing_name,
                "ขั้นตอน (Step)": step_raw, "กิจกรรม": "🔧 ตั้งเครื่อง / เซ็ตศูนย์", "เครื่องจักร": earliest_m,
                "วัสดุ": selected_job.get("วัสดุ", "-"), "เวลาเริ่ม": setup_start, "เวลาเสร็จ": setup_end, "ระยะเวลา": f"{setup_mins:.0f} นาที"
            })
            
        gantt_records.append({
            "ข้อความบนแท่งกราฟ": step_raw, "แผนงาน": job_code, "ชื่อ Drawing.": drawing_name,
            "ขั้นตอน (Step)": step_raw, "กิจกรรม": "🔴 งานด่วนตัดเฉือน" if selected_job["is_urgent"] else "⚙️ งานปกติกำลังกัดงาน",
            "เครื่องจักร": earliest_m, "วัสดุ": selected_job.get("วัสดุ", "-"), "เวลาเริ่ม": cut_start, "เวลาเสร็จ": cut_end, "ระยะเวลา": f"{actual_cut_hrs:.1f} ชม."
        })
        
        total_cycle = (setup_mins / 60.0) + actual_cut_hrs
        summary_records.append({
            "ID": selected_job.get("ID", ""), "เครื่องจักร": earliest_m, "สถานะ": selected_job["สถานะงาน"],
            "ประเภทงาน": "🔴 งานด่วนแทรก" if selected_job["is_urgent"] else "🟢 งานปกติ",
            "แผนงาน": job_code, "ชื่อ Drawing.": drawing_name, "วัสดุ": selected_job.get("วัสดุ", "-"),
            "ขั้นตอน (Step)": step_raw, "เวลาเริ่มจริง": setup_start,
            "เวลาเริ่ม Setup": setup_start.strftime("%d/%m %H:%M") if setup_mins > 0 else "-",
            "เวลาเริ่มขึ้นงาน": cut_start.strftime("%d/%m %H:%M"), "เวลาจบงาน": cut_end.strftime("%d/%m %H:%M"),
            "Setup (นาที)": int(setup_mins), "Basic Machine (ชม.)": round(selected_job["basic_hrs"], 1),
            "รันโปรแกรม (ชม.)": round(selected_job["prog_hrs"], 1), "เวลารวม (ชม.)": round(total_cycle, 2)
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
            "เครื่องจักร": m, "ชั่วโมงทำงาน (ชม.)": round(busy, 1),
            "อัตราการใช้งาน (%)": round(util_pct, 1), "ข้อความแสดง": f"{util_pct:.1f}% ({busy:.1f} ชม.)"
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
# VIEW 1: หน้าจอช่างหน้าเครื่อง
# ---------------------------------------------------------
if st.session_state.current_view == "👷 โหมดช่างหน้าเครื่อง":
    st.markdown("### 📱 บันทึกสถานะงานหน้าเครื่อง CNC")
    
    df_all = fetch_jobs_from_supabase()
    selected_m = st.selectbox("🏭 เลือกเครื่องจักร:", MACHINE_LIST, key="op_machine_select")
    
    if not df_all.empty:
        mask_active = (df_all["เลือกเครื่องจักร"] == selected_m) & (df_all["สถานะงาน"].isin(["⚙️ กำลังผลิต", "⏳ รอคิวผลิต"]))
        m_jobs_df = df_all[mask_active].sort_values(by="ID", ascending=True)
    else:
        m_jobs_df = pd.DataFrame()

    if not m_jobs_df.empty:
        curr = m_jobs_df.iloc[0]
        curr_status = str(curr.get('สถานะงาน', '⏳ รอคิวผลิต'))
        is_running = (curr_status == "⚙️ กำลังผลิต")
        
        total_cyc = (float(curr.get('เวลาตั้งเครื่อง (นาที)', 0))/60.0) + float(curr.get('Basic Machine (ชม.)', 0)) + float(curr.get('รันโปรแกรม (ชม.)', 0))
        status_color = "#10B981" if is_running else "#F59E0B"
        
        start_real_text = "-"
        if pd.notna(curr.get("เริ่มจริง")):
            start_real_text = pd.to_datetime(curr["เริ่มจริง"]).strftime("%d/%m %H:%M:%S")

        st.markdown(f"""
        <div class="op-box" style="border-left: 6px solid {status_color};">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">
                <span style="background:{status_color}; color:white; padding:3px 10px; border-radius:6px; font-weight:700; font-size:12px;">
                    {'⚙️ เครื่องกำลังเดิน' if is_running else '⏳ งานรอคิว'}
                </span>
                <span style="background:#F1F5F9; padding:3px 8px; border-radius:6px; font-weight:700; font-size:12px; color:#0F172A;">{curr_status}</span>
            </div>
            <h3 style="margin:4px 0; color:#1E3A8A; font-size:18px; font-weight:800;">📌 แผนงาน: {curr.get('แผนงาน', '-')}</h3>
            <p style="font-size:14px; margin:3px 0;"><b>📄 Drawing:</b> {curr.get('ชื่อ Drawing.', '-')}</p>
            <p style="margin:3px 0; font-size:13.5px;"><b>⚙️ ขั้นตอน:</b> {curr.get('ขั้นตอน (Step)', '-')} | <b>วัสดุ:</b> {curr.get('วัสดุ', '-')}</p>
            <p style="margin:3px 0; font-size:13.5px;"><b>⏱️ เวลารวม:</b> {total_cyc:.2f} ชม.</p>
            <p style="margin:3px 0 0 0; font-size:13.5px; color:#2563EB;"><b>🕒 เริ่มจริง:</b> {start_real_text}</p>
        </div>
        """, unsafe_allow_html=True)
        
        c_btn1, c_btn2 = st.columns(2)
        with c_btn1:
            if is_running:
                st.button("⚙️ กำลังเดินเครื่อง...", key=f"btn_s_{curr['ID']}", use_container_width=True, disabled=True)
            else:
                if st.button("🚀 เริ่มงาน (Start)", key=f"btn_s_{curr['ID']}", use_container_width=True, type="primary"):
                    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    if update_supabase_job(int(curr["ID"]), {"status": "⚙️ กำลังผลิต", "actual_start": now_str}):
                        st.rerun()
                
        with c_btn2:
            if not is_running:
                st.button("✅ จบงาน (Finish)", key=f"btn_f_{curr['ID']}", use_container_width=True, disabled=True)
            else:
                if st.button("✅ จบงาน (Finish)", key=f"btn_f_{curr['ID']}", use_container_width=True, type="primary"):
                    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    if update_supabase_job(int(curr["ID"]), {"status": "✅ เสร็จสิ้นแล้ว", "actual_finish": now_str}):
                        st.rerun()
                
        if len(m_jobs_df) > 1:
            st.divider()
            st.caption("📋 คิวงานถัดไป:")
            for i, (_, nxt) in enumerate(m_jobs_df.iloc[1:].iterrows(), 1):
                st.markdown(f"<small>{i}. <b>{nxt.get('แผนงาน', '-')}</b> | `{nxt.get('ชื่อ Drawing.', '-')}` ({nxt.get('ขั้นตอน (Step)', '-')})</small>", unsafe_allow_html=True)
    else:
        st.info(f"🎉 เครื่อง {selected_m} ไม่มีงานค้างในระบบ")

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

        if not df_db.empty:
            calc_df = df_db.copy()
            calc_df["รวม (ชม.)"] = ((calc_df["เวลาตั้งเครื่อง (นาที)"] / 60.0) + calc_df["Basic Machine (ชม.)"] + calc_df["รันโปรแกรม (ชม.)"]).round(2)

            column_order = [
                "ID", "แผนงาน", "ชื่อ Drawing.", "วัสดุ", "ประเภทงาน", "ขั้นตอน (Step)",
                "เลือกเครื่องจักร", "วัน-เวลาขึ้นงาน", "เวลาตั้งเครื่อง (นาที)",
                "Basic Machine (ชม.)", "รันโปรแกรม (ชม.)", "รวม (ชม.)", "สถานะงาน",
            ]
            calc_df = calc_df[[c for c in column_order if c in calc_df.columns]]

            # ตารางสั่งผลิตหลักแสดงเฉพาะงานที่ยังไม่จบ
            active_jobs_editor_df = calc_df[calc_df["สถานะงาน"].isin(["⏳ รอคิวผลิต", "⚙️ กำลังผลิต"])].copy()

            with st.expander("📝 จัดการรายการสั่งผลิต (เฉพาะงานที่ยังไม่จบ)", expanded=True):
                data_hash = hash(tuple(active_jobs_editor_df["สถานะงาน"]))
                edited_jobs = st.data_editor(
                    active_jobs_editor_df,
                    key=f"editor_cnc_jobs_{data_hash}",
                    column_config={
                        "ID": st.column_config.NumberColumn("ID", disabled=True, width=50),
                        "แผนงาน": st.column_config.TextColumn("📌 แผนงาน", width=85, required=True),
                        "ชื่อ Drawing.": st.column_config.TextColumn("📄 ชื่อ Drawing.", width=190, required=True),
                        "วัสดุ": st.column_config.TextColumn("🔩 วัสดุ", width=75, required=True),
                        "ประเภทงาน": st.column_config.SelectboxColumn("🏷️ ประเภทงาน", width=125, options=JOB_TYPES, required=True),
                        "ขั้นตอน (Step)": st.column_config.TextColumn("⚙️ ขั้นตอน (Step)", width=110, required=True),
                        "เลือกเครื่องจักร": st.column_config.SelectboxColumn("🏭 เลือกเครื่องจักร", width=140, options=ASSIGN_OPTIONS, required=True),
                        "วัน-เวลาขึ้นงาน": st.column_config.DatetimeColumn("📅 วัน-เวลาขึ้นงาน", width=145, format="YYYY-MM-DD HH:mm", required=True),
                        "เวลาตั้งเครื่อง (นาที)": st.column_config.NumberColumn("⏱️ Setup (น.)", width=95, min_value=0, max_value=720, step=5, format="%d", required=True),
                        "Basic Machine (ชม.)": st.column_config.NumberColumn("🛠️ Basic (ชม.)", width=95, min_value=0.0, max_value=100.0, step=0.5, format="%.1f", required=True),
                        "รันโปรแกรม (ชม.)": st.column_config.NumberColumn("💻 โปรแกรม (ชม.)", width=105, min_value=0.0, max_value=200.0, step=0.5, format="%.1f", required=True),
                        "รวม (ชม.)": st.column_config.NumberColumn("⏳ รวม (ชม.)", width=85, format="%.2f", disabled=True),
                        "สถานะงาน": st.column_config.SelectboxColumn("🚦 สถานะงาน", width=130, options=JOB_STATUS, required=True),
                    },
                    num_rows="dynamic",
                    use_container_width=True
                )
                
                c_save, _ = st.columns([2, 8])
                with c_save:
                    if st.button("💾 บันทึกข้อมูลลง Supabase", type="primary"):
                        for _, row in edited_jobs.iterrows():
                            ready_dt = pd.to_datetime(row["วัน-เวลาขึ้นงาน"], errors='coerce')
                            ready_str = ready_dt.strftime("%Y-%m-%d %H:%M:%S") if pd.notna(ready_dt) else datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            payload = {
                                "plan_code": str(row["แผนงาน"]), "drawing_name": str(row["ชื่อ Drawing."]), "material": str(row["วัสดุ"]),
                                "job_type": str(row["ประเภทงาน"]), "step_name": str(row["ขั้นตอน (Step)"]), "machine_name": str(row["เลือกเครื่องจักร"]),
                                "ready_at": ready_str, "setup_mins": float(row["เวลาตั้งเครื่อง (นาที)"]), "basic_hrs": float(row["Basic Machine (ชม.)"]),
                                "prog_hrs": float(row["รันโปรแกรม (ชม.)"]), "status": str(row["สถานะงาน"])
                            }
                            if pd.notna(row.get("ID")) and row["ID"] > 0: update_supabase_job(int(row["ID"]), payload)
                            else: insert_supabase_job(payload)
                        st.success("บันทึกข้อมูลลงฐานข้อมูลสำเร็จ!")
                        st.rerun()

            start_time = datetime(2026, 8, 20, 8, 0)
            df_gantt, df_summary, df_util, total_plan_hrs = calculate_shop_schedule(edited_jobs, start_time)

            finished_jobs_df = df_db[df_db["สถานะงาน"] == "✅ เสร็จสิ้นแล้ว"].copy()
            active_jobs_count = len(edited_jobs[edited_jobs["สถานะงาน"].isin(["⏳ รอคิวผลิต", "⚙️ กำลังผลิต"])])
            avg_util = df_util["อัตราการใช้งาน (%)"].mean() if not df_util.empty else 0.0

            # 1. แถบสรุป KPI
            kpi_html = f'''<div class="kpi-container"><div class="kpi-card kpi-green"><div class="kpi-title">✅ งานเสร็จสิ้น</div><div class="kpi-value">{len(finished_jobs_df)} <span style="font-size:15px; font-weight:600;">รายการ</span></div></div><div class="kpi-card kpi-blue"><div class="kpi-title">⚙️ งานในแผน</div><div class="kpi-value">{active_jobs_count} <span style="font-size:15px; font-weight:600;">รายการ</span></div></div><div class="kpi-card kpi-orange"><div class="kpi-title">⏱️ เวลาทั้งหมด</div><div class="kpi-value">{total_plan_hrs:.1f} <span style="font-size:15px; font-weight:600;">ชม.</span></div></div><div class="kpi-card kpi-purple"><div class="kpi-title">📊 การใช้เครื่อง</div><div class="kpi-value">{avg_util:.1f} %</div></div></div>'''
            st.markdown(kpi_html, unsafe_allow_html=True)

            # 2. ตารางงานที่ Finish แล้ว พร้อมคอลัมน์ "จัดการ (🗑️)" ในรูปแบบตารางมาตรฐาน
            if not finished_jobs_df.empty:
                st.subheader("📋 รายการงานที่ Finish แล้ว และเช็คเวลาวางแผนเทียบกับเวลาจริง (Plan vs Actual Performance)")
                perf_df = finished_jobs_df.copy()
                perf_df["เวลาแผน (ชม.)"] = (perf_df["เวลาตั้งเครื่อง (นาที)"] / 60.0) + perf_df["Basic Machine (ชม.)"] + perf_df["รันโปรแกรม (ชม.)"]
                
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
                perf_df["ลบ"] = False  # คอลัมน์จัดการรูปถังขยะสำหรับติ๊กเลือกลบ
                
                display_finish_df = perf_df[["ID", "แผนงาน", "ชื่อ Drawing.", "ขั้นตอน (Step)", "เลือกเครื่องจักร", "เริ่มจริง", "เสร็จจริง", "เวลาแผน (ชม.)", "เวลาจริง (ชม.)", "ผลต่าง (ชม.)", "การประเมิน", "ลบ"]].copy()

                edited_finish_table = st.data_editor(
                    display_finish_df,
                    key="editor_finish_jobs_table",
                    column_config={
                        "ID": st.column_config.NumberColumn("ID", disabled=True, width=50),
                        "แผนงาน": st.column_config.TextColumn("📌 PLAN NO.", disabled=True, width=85),
                        "ชื่อ Drawing.": st.column_config.TextColumn("📄 DRAWING NO.", disabled=True, width=180),
                        "ขั้นตอน (Step)": st.column_config.TextColumn("⚙️ ขั้นตอน", disabled=True, width=95),
                        "เลือกเครื่องจักร": st.column_config.TextColumn("🏭 สถานีผลิต", disabled=True, width=115),
                        "เริ่มจริง": st.column_config.DatetimeColumn("🕒 เริ่มจริง", disabled=True, width=145, format="DD/MM HH:mm"),
                        "เสร็จจริง": st.column_config.DatetimeColumn("🏁 เวลาจบจริง", disabled=True, width=145, format="DD/MM HH:mm"),
                        "เวลาแผน (ชม.)": st.column_config.NumberColumn("⏱️ แผน (ชม.)", disabled=True, width=90, format="%.2f"),
                        "เวลาจริง (ชม.)": st.column_config.NumberColumn("⏱️ จริง (ชม.)", disabled=True, width=90, format="%.2f"),
                        "ผลต่าง (ชม.)": st.column_config.NumberColumn("📊 Diff", disabled=True, width=80, format="%.2f"),
                        "การประเมิน": st.column_config.TextColumn("🚦 ผลการผลิต", disabled=True, width=160),
                        "ลบ": st.column_config.CheckboxColumn("🗑️ จัดการ", help="ติ๊กถูกช่องนี้เพื่อเลือกลบรายการ", default=False, width=70),
                    },
                    hide_index=True,
                    use_container_width=True
                )

                # ปุ่มกดยืนยันการลบรายการที่ติ๊กถูกไว้ในตาราง
                c_del_act, _ = st.columns([3, 7])
                with c_del_act:
                    selected_rows_to_delete = edited_finish_table[edited_finish_table["ลบ"] == True]
                    if st.button(f"🗑️ ลบรายการที่เลือก ({len(selected_rows_to_delete)} รายการ)", type="secondary", disabled=(len(selected_rows_to_delete) == 0)):
                        del_success = True
                        for _, row in selected_rows_to_delete.iterrows():
                            if not delete_supabase_job(int(row["ID"])):
                                del_success = False
                        if del_success:
                            st.toast("ลบรายการที่เลือกเรียบร้อยแล้ว", icon="🗑️")
                            st.rerun()
                        else:
                            st.error("เกิดข้อผิดพลาดในการลบข้อมูล")

                st.divider()

            if not df_summary.empty:
                # 3. กราฟ Utilization
                st.subheader("📈 อัตราการใช้งานเครื่องจักร (% Machine Utilization)")
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
                    height=370,
                    margin=dict(l=40, r=40, t=10, b=30),
                    xaxis_title="อัตราการใช้งาน (%)",
                    yaxis_title="เครื่องจักร",
                    xaxis=dict(showgrid=True, gridcolor="#F1F5F9"),
                    coloraxis_showscale=False,
                    plot_bgcolor="#FFFFFF",
                    paper_bgcolor="#FFFFFF"
                )
                fig_bar.add_vline(x=85, line_dash="dash", line_color="#EF4444", line_width=2, annotation_text="เป้าหมาย (85%)", annotation_position="top right", annotation_font_color="#EF4444")
                st.plotly_chart(fig_bar, use_container_width=True)

                st.divider()

                # 4. ผัง Gantt Chart Timeline
                st.subheader("📊 ผังเวลาขึ้นงานที่กำลังผลิตและรอคิว (Gantt Chart Timeline)")
                fig = px.timeline(
                    df_gantt,
                    x_start="เวลาเริ่ม",
                    x_end="เวลาเสร็จ",
                    y="เครื่องจักร",
                    color="กิจกรรม",
                    text="ข้อความบนแท่งกราฟ",
                    hover_data=["แผนงาน", "ชื่อ Drawing.", "ขั้นตอน (Step)", "วัสดุ", "ระยะเวลา"],
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
                    height=450,
                    xaxis_title="วันและเวลา",
                    yaxis_title="เครื่องจักร",
                    uniformtext_minsize=8,
                    uniformtext_mode='hide',
                    plot_bgcolor="#FFFFFF",
                    paper_bgcolor="#FFFFFF",
                    xaxis=dict(showgrid=True, gridcolor="#F1F5F9")
                )
                st.plotly_chart(fig, use_container_width=True)

                st.divider()

                # 5. ใบจ่ายคิวงานหน้าเครื่อง
                st.subheader("📋 ใบจ่ายคิวงานหน้าเครื่อง (Work Order Sheet)")
                f_c1, f_c2 = st.columns([1, 1])
                with f_c1:
                    filter_status = st.multiselect("🔍 กรองตามสถานะงาน:", ["ทั้งหมด"] + JOB_STATUS, default=["ทั้งหมด"])
                with f_c2:
                    filter_machine = st.multiselect("🏭 กรองตามเครื่องจักร:", ["ทั้งหมด"] + MACHINE_LIST, default=["ทั้งหมด"])

                df_display = df_summary.sort_values(by="เวลาเริ่มจริง", ascending=True)
                if "ทั้งหมด" not in filter_status and len(filter_status) > 0:
                    df_display = df_display[df_display["สถานะ"].isin(filter_status)]
                if "ทั้งหมด" not in filter_machine and len(filter_machine) > 0:
                    df_display = df_display[df_display["เครื่องจักร"].isin(filter_machine)]

                display_cols = [c for c in df_display.columns if c != "เวลาเริ่มจริง" and c != "ID"]

                st.dataframe(
                    df_display[display_cols],
                    column_config={
                        "เครื่องจักร": st.column_config.TextColumn("🏭 เครื่องจักร", width=115),
                        "สถานะ": st.column_config.TextColumn("🚦 สถานะ", width=105),
                        "ประเภทงาน": st.column_config.TextColumn("🏷️ ประเภทงาน", width=105),
                        "แผนงาน": st.column_config.TextColumn("📌 แผนงาน", width=80),
                        "ชื่อ Drawing.": st.column_config.TextColumn("📄 ชื่อ Drawing.", width=190),
                        "วัสดุ": st.column_config.TextColumn("🔩 วัสดุ", width=75),
                        "ขั้นตอน (Step)": st.column_config.TextColumn("⚙️ ขั้นตอน (Step)", width=110),
                        "เวลาเริ่ม Setup": st.column_config.TextColumn("🔧 เริ่ม Setup", width=105),
                        "เวลาเริ่มขึ้นงาน": st.column_config.TextColumn("▶️ เริ่มขึ้นงาน", width=105),
                        "เวลาจบงาน": st.column_config.TextColumn("⏹️ จบงาน", width=105),
                        "Setup (นาที)": st.column_config.NumberColumn("Setup (น.)", width=85, format="%d"),
                        "Basic Machine (ชม.)": st.column_config.NumberColumn("Basic (ชม.)", width=85, format="%.1f"),
                        "รันโปรแกรม (ชม.)": st.column_config.NumberColumn("โปรแกรม (ชม.)", width=95, format="%.1f"),
                        "เวลารวม (ชม.)": st.column_config.NumberColumn("⏳ รวม (ชม.)", width=85, format="%.2f"),
                    },
                    use_container_width=True,
                    hide_index=True
                )

            # 6. ตารางคำนวณราคาต้นทุนค่าเครื่องจักร
            st.subheader("💰 ตารางคำนวณมูลค่าและต้นทุนค่าเครื่องจักร (Machining Cost Calculation)")

            if "machine_rates" not in st.session_state:
                st.session_state.machine_rates = pd.DataFrame([{"เครื่องจักร": m, "เรตราคา (บาท/ชม.)": DEFAULT_RATES[m]} for m in MACHINE_LIST])

            cost_col1, cost_col2 = st.columns([1, 3])

            with cost_col1:
                st.markdown("**⚙️ ตั้งค่าเรตราคาค่าเครื่องจักร (บาท/ชม.)**")
                edited_rates = st.data_editor(
                    st.session_state.machine_rates,
                    column_config={
                        "เครื่องจักร": st.column_config.TextColumn("เครื่องจักร", disabled=True),
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
                    cost_df["รวม (ชม.)"] = (cost_df["เวลาตั้งเครื่อง (นาที)"] / 60.0) + cost_df["Basic Machine (ชม.)"] + cost_df["รันโปรแกรม (ชม.)"]
                    cost_df["เรตราคา (บาท/ชม.)"] = cost_df["เลือกเครื่องจักร"].map(rate_map).fillna(1000)
                    cost_df["มูลค่ารวม (บาท)"] = cost_df["รวม (ชม.)"] * cost_df["เรตราคา (บาท/ชม.)"]
                    
                    total_finished_cost = cost_df["มูลค่ารวม (บาท)"].sum()
                    total_finished_hrs = cost_df["รวม (ชม.)"].sum()
                    
                    st.markdown(f"**📊 รายการสรุปมูลค่างานที่เสร็จสิ้น (รวมทั้งหมด: :green[{total_finished_cost:,.2f} บาท] / {total_finished_hrs:.2f} ชม.)**")
                    st.dataframe(
                        cost_df[["แผนงาน", "ขั้นตอน (Step)", "ชื่อ Drawing.", "เลือกเครื่องจักร", "Basic Machine (ชม.)", "รันโปรแกรม (ชม.)", "รวม (ชม.)", "เรตราคา (บาท/ชม.)", "มูลค่ารวม (บาท)"]],
                        column_config={
                            "แผนงาน": st.column_config.TextColumn("📌 แผนงาน", width=85),
                            "ขั้นตอน (Step)": st.column_config.TextColumn("⚙️ ขั้นตอน", width=105),
                            "ชื่อ Drawing.": st.column_config.TextColumn("📄 ชื่อ Drawing.", width=180),
                            "เลือกเครื่องจักร": st.column_config.TextColumn("🏭 เครื่องจักร", width=120),
                            "Basic Machine (ชม.)": st.column_config.NumberColumn("Basic (ชม.)", width=85, format="%.1f"),
                            "รันโปรแกรม (ชม.)": st.column_config.NumberColumn("โปรแกรม (ชม.)", width=95, format="%.1f"),
                            "รวม (ชม.)": st.column_config.NumberColumn("⏳ รวม (ชม.)", width=85, format="%.2f"),
                            "เรตราคา (บาท/ชม.)": st.column_config.NumberColumn("💵 เรตราคา", width=110, format="%d ฿"),
                            "มูลค่ารวม (บาท)": st.column_config.NumberColumn("💰 รวมเป็นเงิน", width=130, format="%.2f ฿"),
                        },
                        use_container_width=True,
                        hide_index=True
                    )
                else:
                    st.info("ℹ️ ยังไม่มีรายการที่ขึ้นสถานะ '✅ เสร็จสิ้นแล้ว' จึงยังไม่มีการคำนวณมูลค่าต้นทุน")
