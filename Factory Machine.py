import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime, timedelta
import os
import base64
from PIL import Image
import requests

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
# 2. ปรับแต่ง UI ให้สะอาด ปลอดภัย ไม่ทำให้จอขาว
# =========================================================
st.markdown("""
<style>
    .block-container {
        padding-top: 1.5rem !important;
        padding-bottom: 2rem !important;
        padding-left: 1rem !important;
        padding-right: 1rem !important;
        max-width: 100% !important;
    }
    .main-header {
        background: linear-gradient(135deg, #1E3C72 0%, #2A5298 100%);
        padding: 12px 16px;
        border-radius: 12px;
        color: white;
        margin-bottom: 12px;
        display: flex;
        align-items: center;
        gap: 12px;
    }
    .header-logo {
        width: 70px;
        max-height: 45px;
        height: auto;
        object-fit: contain;
        flex-shrink: 0;
    }
    .header-logo-icon {
        font-size: 26px;
        background: rgba(255, 255, 255, 0.15);
        padding: 4px 10px;
        border-radius: 8px;
        flex-shrink: 0;
    }
    .header-text h1 {
        color: white !important;
        font-size: 15px !important;
        margin: 0 !important;
        font-weight: 700 !important;
        line-height: 1.2 !important;
    }
    .header-text p {
        color: #E0E8F9 !important;
        margin: 2px 0 0 0 !important;
        font-size: 11px !important;
    }
    .op-box {
        background: white;
        padding: 14px 16px;
        border-radius: 12px;
        border: 1.5px solid #E2E8F0;
        margin-bottom: 12px;
        box-shadow: 0 2px 6px rgba(0,0,0,0.03);
    }
    .kpi-container {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(135px, 1fr));
        gap: 8px;
        margin-bottom: 12px;
    }
    .kpi-card {
        padding: 10px 12px;
        border-radius: 10px;
        color: white;
    }
    .kpi-green { background: linear-gradient(135deg, #11998e 0%, #38ef7d 100%); }
    .kpi-blue { background: linear-gradient(135deg, #2193b0 0%, #6dd5ed 100%); }
    .kpi-orange { background: linear-gradient(135deg, #f12711 0%, #f5af19 100%); }
    .kpi-purple { background: linear-gradient(135deg, #8A2387 0%, #E94057 50%, #F27121 100%); }
    .kpi-title { font-size: 11px; font-weight: 600; opacity: 0.9; }
    .kpi-value { font-size: 17px; font-weight: 700; margin-top: 2px; }

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
# 3. กำหนดสิทธิ์และความปลอดภัย (Session State)
# =========================================================
ADMIN_PASSWORD = "pesadmin"

if "is_admin" not in st.session_state:
    st.session_state.is_admin = False

if "current_view" not in st.session_state:
    st.session_state.current_view = "👷 โหมดช่างหน้าเครื่อง"

# =========================================================
# 4. ค่าคงที่
# =========================================================
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
# 5. การเชื่อมต่อ Supabase
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
        res = requests.patch(endpoint, headers=get_supabase_headers(), json=payload, timeout=8)
        st.cache_data.clear()
        return res.status_code in [200, 204]
    except Exception:
        return False

def insert_supabase_job(payload: dict) -> bool:
    try:
        base_url = st.secrets["SUPABASE_URL"].rstrip("/")
        endpoint = f"{base_url}/rest/v1/cnc_jobs"
        res = requests.post(endpoint, headers=get_supabase_headers(), json=payload, timeout=8)
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
# 6. Scheduling Engine
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
                m_available[earliest_m] = min(future_candidates)
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
# 7. เมนูเปลี่ยนโหมด (Navigation)
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
    st.subheader("📱 บันทึกสถานะงานหน้าเครื่อง CNC")
    
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
                <span style="background:{status_color}; color:white; padding:3px 8px; border-radius:5px; font-weight:700; font-size:12px;">
                    {'⚙️ เครื่องกำลังเดิน' if is_running else '⏳ งานรอคิว'}
                </span>
                <span style="background:#F1F5F9; padding:3px 6px; border-radius:5px; font-weight:700; font-size:11.5px; color:#0F172A;">{curr_status}</span>
            </div>
            <h3 style="margin:4px 0; color:#1E3A8A; font-size:17px;">📌 แผนงาน: {curr.get('แผนงาน', '-')}</h3>
            <p style="font-size:14px; margin:2px 0;"><b>📄 Drawing:</b> {curr.get('ชื่อ Drawing.', '-')}</p>
            <p style="margin:2px 0; font-size:13px;"><b>⚙️ ขั้นตอน:</b> {curr.get('ขั้นตอน (Step)', '-')} | <b>วัสดุ:</b> {curr.get('วัสดุ', '-')}</p>
            <p style="margin:2px 0; font-size:13px;"><b>⏱️ เวลารวม:</b> {total_cyc:.2f} ชม.</p>
            <p style="margin:2px 0 0 0; font-size:13px; color:#2563EB;"><b>🕒 เริ่มจริง:</b> {start_real_text}</p>
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
# VIEW 2: Dashboard สำหรับผู้บริหาร
# ---------------------------------------------------------
elif st.session_state.current_view == "📊 แดชบอร์ดภาพรวมโรงงาน":
    if not st.session_state.is_admin:
        st.subheader("🔒 ยืนยันตัวตนผู้บริหาร")
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
            st.subheader("📊 แดชบอร์ดภาพรวมโรงงาน (Admin)")
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

            with st.expander("📝 จัดการรายการสั่งผลิต (Supabase)", expanded=False):
                data_hash = hash(tuple(df_db["สถานะงาน"]))
                edited_jobs = st.data_editor(
                    calc_df,
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
                if st.button("💾 บันทึกข้อมูล", type="primary"):
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
                    st.success("บันทึกสำเร็จ!")
                    st.rerun()

            start_time = datetime(2026, 8, 20, 8, 0)
            df_gantt, df_summary, df_util, total_plan_hrs = calculate_shop_schedule(edited_jobs, start_time)

            finished_jobs_df = df_db[df_db["สถานะงาน"] == "✅ เสร็จสิ้นแล้ว"].copy()
            active_jobs_count = len(edited_jobs[edited_jobs["สถานะงาน"].isin(["⏳ รอคิวผลิต", "⚙️ กำลังผลิต"])])
            avg_util = df_util["อัตราการใช้งาน (%)"].mean() if not df_util.empty else 0.0

            # 1. แถบ KPI
            kpi_html = f'''<div class="kpi-container"><div class="kpi-card kpi-green"><div class="kpi-title">✅ เสร็จสิ้น</div><div class="kpi-value">{len(finished_jobs_df)}</div></div><div class="kpi-card kpi-blue"><div class="kpi-title">⚙️ งานในแผน</div><div class="kpi-value">{active_jobs_count}</div></div><div class="kpi-card kpi-orange"><div class="kpi-title">⏱️ เวลาทั้งหมด</div><div class="kpi-value">{total_plan_hrs:.1f} ชม.</div></div><div class="kpi-card kpi-purple"><div class="kpi-title">📊 การใช้เครื่อง</div><div class="kpi-value">{avg_util:.1f} %</div></div></div>'''
            st.markdown(kpi_html, unsafe_allow_html=True)

            # 2. ผัง Gantt Timeline
            if not df_summary.empty:
                st.subheader("📊 ผังการผลิต (Gantt Chart Timeline)")
                fig = px.timeline(
                    df_gantt, x_start="เวลาเริ่ม", x_end="เวลาเสร็จ", y="เครื่องจักร", color="กิจกรรม",
                    text="ข้อความบนแท่งกราฟ", category_orders={"เครื่องจักร": MACHINE_LIST},
                    color_discrete_map={"🔧 ตั้งเครื่อง / เซ็ตศูนย์": "#FF7A00", "⚙️ งานปกติกำลังกัดงาน": "#007AFF", "🔴 งานด่วนตัดเฉือน": "#FF2D55"}
                )
                fig.update_yaxes(autorange="reversed")
                fig.update_layout(height=400, margin=dict(l=20, r=20, t=20, b=20), plot_bgcolor="#FFFFFF", paper_bgcolor="#FFFFFF")
                st.plotly_chart(fig, use_container_width=True)
