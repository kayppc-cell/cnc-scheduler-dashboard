import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime, timedelta
import os
import base64
from supabase import create_client, Client

st.set_page_config(
    page_title="ระบบวางแผนผลิตและติดตามสถานะงาน CNC 9 เครื่อง",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# =========================================================
# การเชื่อมต่อ Supabase Database
# =========================================================
def get_supabase() -> Client:
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    return create_client(url, key)

def fetch_jobs_from_supabase() -> pd.DataFrame:
    try:
        client = get_supabase()
        res = client.table("cnc_jobs").select("*").order("id").execute()
        if res.data and len(res.data) > 0:
            df = pd.DataFrame(res.data)
            df["ready_at"] = pd.to_datetime(df["ready_at"])
            col_map = {
                "id": "ID",
                "plan_code": "แผนงาน",
                "drawing_name": "ชื่อ Drawing.",
                "material": "วัสดุ",
                "job_type": "ประเภทงาน",
                "step_name": "ขั้นตอน (Step)",
                "machine_name": "เลือกเครื่องจักร",
                "ready_at": "วัน-เวลาขึ้นงาน",
                "setup_mins": "เวลาตั้งเครื่อง (นาที)",
                "basic_hrs": "Basic Machine (ชม.)",
                "prog_hrs": "รันโปรแกรม (ชม.)",
                "status": "สถานะงาน"
            }
            return df.rename(columns=col_map)
        else:
            return pd.DataFrame()
    except Exception as e:
        st.error(f"❌ ดึงข้อมูลจาก Supabase ไม่สำเร็จ: {e}")
        return pd.DataFrame()

# =========================================================
# การจัดการโลโก้และสไตล์ตกแต่ง UI (CSS)
# =========================================================
def get_image_base64(image_path):
    if os.path.exists(image_path):
        with open(image_path, "rb") as img_file:
            return base64.b64encode(img_file.read()).decode("utf-8")
    return None

logo_base64 = None
for fname in ["Logo_Pes.png", "logo.png", "logo.jpg", r"D:\Python\Logo_Pes.png"]:
    if os.path.exists(fname):
        logo_base64 = get_image_base64(fname)
        break

if logo_base64:
    logo_html = f'<img src="data:image/png;base64,{logo_base64}" class="header-logo" alt="Logo"/>'
else:
    logo_html = '<div class="header-logo-icon">🏭</div>'

st.markdown("""
<style>
    .main-header {
        background: linear-gradient(135deg, #1E3C72 0%, #2A5298 100%);
        padding: 20px 28px;
        border-radius: 12px;
        color: white;
        margin-bottom: 20px;
        box-shadow: 0 4px 15px rgba(30, 60, 114, 0.2);
        display: flex;
        align-items: center;
        gap: 25px;
        text-align: left;
    }
    .header-logo {
        width: 200px;
        height: auto;
        max-height: 80px;
        object-fit: contain;
        background: transparent !important;
        padding: 0 !important;
        border: none !important;
        flex-shrink: 0;
    }
    .header-logo-icon {
        font-size: 42px;
        background: rgba(255, 255, 255, 0.15);
        border: 1.5px solid rgba(255, 255, 255, 0.3);
        padding: 6px 16px;
        border-radius: 10px;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        flex-shrink: 0;
    }
    .header-text { flex: 1; }
    .header-text h1 {
        color: white !important;
        font-size: 24px !important;
        margin: 0 !important;
        padding: 0 !important;
        font-weight: 700 !important;
        line-height: 1.2 !important;
    }
    .header-text p {
        color: #E0E8F9 !important;
        margin: 6px 0 0 0 !important;
        padding: 0 !important;
        font-size: 13px !important;
    }
    .kpi-container {
        display: grid;
        grid-template-columns: repeat(4, 1fr);
        gap: 15px;
        margin-bottom: 20px;
    }
    .kpi-card {
        padding: 16px 20px;
        border-radius: 12px;
        color: white;
        box-shadow: 0 4px 12px rgba(0,0,0,0.08);
    }
    .kpi-green { background: linear-gradient(135deg, #11998e 0%, #38ef7d 100%); }
    .kpi-blue { background: linear-gradient(135deg, #2193b0 0%, #6dd5ed 100%); }
    .kpi-orange { background: linear-gradient(135deg, #f12711 0%, #f5af19 100%); }
    .kpi-purple { background: linear-gradient(135deg, #8A2387 0%, #E94057 50%, #F27121 100%); }
    .kpi-title { font-size: 13px; font-weight: 600; opacity: 0.9; text-transform: uppercase; letter-spacing: 0.5px; }
    .kpi-value { font-size: 24px; font-weight: 700; margin-top: 4px; }
    .op-box {
        background: white;
        padding: 22px;
        border-radius: 14px;
        border: 2px solid #E2E8F0;
        box-shadow: 0 4px 15px rgba(0,0,0,0.05);
        margin-bottom: 15px;
    }
</style>
""", unsafe_allow_html=True)

header_content = f'''<div class="main-header">{logo_html}<div class="header-text"><h1>ระบบวางแผนผลิตและติดตามสถานะงาน CNC 9 เครื่อง</h1><p>Awea (2 เครื่อง), Hartford (3 เครื่อง), Sanco (1 เครื่อง), Bridgeport (2 เครื่อง), Mikron 5 แกน (1 เครื่อง)</p></div></div>'''
st.markdown(header_content, unsafe_allow_html=True)

# =========================================================
# ค่าคงที่และระบบคำนวณการจัดตารางผลิต (Scheduling Engine)
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

def calculate_shop_schedule(jobs_df, default_start_datetime):
    m_available = {m: default_start_datetime for m in MACHINE_LIST}
    m_last_mat = {m: None for m in MACHINE_LIST}
    m_busy_hrs = {m: 0.0 for m in MACHINE_LIST}
    
    active_mask = jobs_df["สถานะงาน"].isin(["⏳ รอคิวผลิต", "⚙️ กำลังผลิต"])
    
    valid_jobs = []
    for j in jobs_df[active_mask].to_dict("records"):
        try:
            basic_val = float(j.get("Basic Machine (ชม.)", 0.0))
            prog_val = float(j.get("รันโปรแกรม (ชม.)", 0.0))
            setup_val = float(j.get("เวลาตั้งเครื่อง (นาที)", 15.0))
            basic_hrs = basic_val if basic_val >= 0 else 0.0
            prog_hrs = prog_val if prog_val >= 0 else 0.0
            cut_val = basic_hrs + prog_hrs
            j["basic_hrs"] = basic_hrs
            j["prog_hrs"] = prog_hrs
            j["cut_hrs"] = cut_val if cut_val > 0 else 0.1
            j["setup_mins"] = setup_val if setup_val >= 0 else 0.0
        except (ValueError, TypeError):
            j["basic_hrs"] = 0.0
            j["prog_hrs"] = 0.0
            j["cut_hrs"] = 0.1
            j["setup_mins"] = 15.0
            
        ready_time = j.get("วัน-เวลาขึ้นงาน")
        if pd.isna(ready_time) or not isinstance(ready_time, (datetime, pd.Timestamp)):
            j["ready_at"] = default_start_datetime
        else:
            j["ready_at"] = pd.to_datetime(ready_time).to_pydatetime()
            
        j["is_urgent"] = True if "ด่วนแทรก" in str(j.get("ประเภทงาน", "")) else False
        j["remain_cut_hrs"] = j["cut_hrs"]
        j["need_setup"] = True if j["สถานะงาน"] != "⚙️ กำลังผลิต" else False
        valid_jobs.append(j)
        
    gantt_records = []
    summary_records = []
    
    while valid_jobs:
        pending_machines = set()
        for j in valid_jobs:
            target = j.get("เลือกเครื่องจักร", "")
            if target in MACHINE_LIST:
                pending_machines.add(target)
            elif target == "อัตโนมัติ (เครื่อง 3 แกนใดก็ได้)":
                for m in MACHINE_LIST:
                    if m != "No.9 Mikron":
                        pending_machines.add(m)
                        
        if not pending_machines:
            break
            
        earliest_m = min(pending_machines, key=lambda m: m_available[m])
        cur_time = m_available[earliest_m]
        last_mat = m_last_mat[earliest_m]
        
        ready_candidates = []
        for j in valid_jobs:
            target = j.get("เลือกเครื่องจักร", "")
            if target == earliest_m or (target == "อัตโนมัติ (เครื่อง 3 แกนใดก็ได้)" and earliest_m != "No.9 Mikron"):
                if j["ready_at"] <= cur_time:
                    ready_candidates.append(j)
                    
        if not ready_candidates:
            future_candidates = [
                j["ready_at"] for j in valid_jobs 
                if (j.get("เลือกเครื่องจักร") == earliest_m or (j.get("เลือกเครื่องจักร") == "อัตโนมัติ (เครื่อง 3 แกนใดก็ได้)" and earliest_m != "No.9 Mikron")) 
                and j["ready_at"] > cur_time
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
        
        future_urgents = [
            j for j in valid_jobs if j["is_urgent"] and (j.get("เลือกเครื่องจักร") == earliest_m or (j.get("เลือกเครื่องจักร") == "อัตโนมัติ (เครื่อง 3 แกนใดก็ได้)" and earliest_m != "No.9 Mikron")) and j["ready_at"] > setup_end
        ]
        
        planned_cut_hrs = selected_job["remain_cut_hrs"]
        cut_start = setup_end
        is_preempted = False
        
        if future_urgents and not selected_job["is_urgent"]:
            earliest_urgent_time = min(j["ready_at"] for j in future_urgents)
            possible_run_hrs = (earliest_urgent_time - cut_start).total_seconds() / 3600.0
            if possible_run_hrs < planned_cut_hrs:
                actual_cut_hrs = max(possible_run_hrs, 0.1)
                is_preempted = True
            else:
                actual_cut_hrs = planned_cut_hrs
        else:
            actual_cut_hrs = planned_cut_hrs
            
        cut_end = cut_start + timedelta(hours=actual_cut_hrs)
        step_raw = str(selected_job.get("ขั้นตอน (Step)", "OP10"))
        job_code = str(selected_job.get('แผนงาน', '-'))
        drawing_name = str(selected_job.get("ชื่อ Drawing.", "-"))
        job_type = "🔴 งานด่วนแทรก" if selected_job["is_urgent"] else "🟢 งานปกติ"
        
        if setup_mins > 0:
            gantt_records.append({
                "ข้อความบนแท่งกราฟ": "Setup",
                "แผนงาน": job_code,
                "ชื่อ Drawing.": drawing_name,
                "ขั้นตอน (Step)": step_raw,
                "กิจกรรม": "🔧 ตั้งเครื่อง / เซ็ตศูนย์",
                "เครื่องจักร": earliest_m,
                "วัสดุ": selected_job.get("วัสดุ", "-"),
                "เวลาเริ่ม": setup_start,
                "เวลาเสร็จ": setup_end,
                "ระยะเวลา": f"{setup_mins:.0f} นาที",
            })
            
        act_name = "🔴 งานด่วนตัดเฉือน" if selected_job["is_urgent"] else "⚙️ งานปกติกำลังกัดงาน"
        bar_text = step_raw if not is_preempted else f"{step_raw} (ช่วงที่ 1)"
        gantt_records.append({
            "ข้อความบนแท่งกราฟ": bar_text,
            "แผนงาน": job_code,
            "ชื่อ Drawing.": drawing_name,
            "ขั้นตอน (Step)": step_raw,
            "กิจกรรม": act_name,
            "เครื่องจักร": earliest_m,
            "วัสดุ": selected_job.get("วัสดุ", "-"),
            "เวลาเริ่ม": cut_start,
            "เวลาเสร็จ": cut_end,
            "ระยะเวลา": f"{actual_cut_hrs:.1f} ชม.",
        })
        
        total_cycle = (setup_mins / 60.0) + actual_cut_hrs
        
        summary_records.append({
            "ID": selected_job.get("ID", ""),
            "เครื่องจักร": earliest_m,
            "สถานะ": selected_job["สถานะงาน"],
            "ประเภทงาน": job_type,
            "แผนงาน": job_code,
            "ชื่อ Drawing.": drawing_name,
            "วัสดุ": selected_job.get("วัสดุ", "-"),
            "ขั้นตอน (Step)": step_raw if not is_preempted else f"{step_raw} (ช่วงที่ 1)",
            "เวลาเริ่มจริง": setup_start,
            "เวลาเริ่ม Setup": setup_start.strftime("%d/%m %H:%M") if setup_mins > 0 else "-",
            "เวลาเริ่มขึ้นงาน": cut_start.strftime("%d/%m %H:%M"),
            "เวลาจบงาน": cut_end.strftime("%d/%m %H:%M"),
            "Setup (นาที)": int(setup_mins),
            "Basic Machine (ชม.)": round(selected_job["basic_hrs"], 1),
            "รันโปรแกรม (ชม.)": round(selected_job["prog_hrs"], 1),
            "เวลารวม (ชม.)": round(total_cycle, 2),
        })
        
        m_available[earliest_m] = cut_end
        m_last_mat[earliest_m] = selected_job["วัสดุ"]
        m_busy_hrs[earliest_m] += total_cycle
        
        if is_preempted:
            selected_job["remain_cut_hrs"] -= actual_cut_hrs
            selected_job["ready_at"] = cut_end
            selected_job["need_setup"] = True
        else:
            valid_jobs.remove(selected_job)
            
    start_anchor = min((j["เวลาเริ่มจริง"] for j in summary_records), default=default_start_datetime)
    max_finish = max(m_available.values()) if summary_records else default_start_datetime
    total_horizon_hrs = max((max_finish - start_anchor).total_seconds() / 3600.0, 1.0)
    
    util_list = []
    for m in MACHINE_LIST:
        busy = m_busy_hrs[m]
        util_pct = min((busy / total_horizon_hrs) * 100.0, 100.0) if total_horizon_hrs > 0 else 0.0
        util_list.append({
            "เครื่องจักร": m,
            "ชั่วโมงทำงาน (ชม.)": round(busy, 1),
            "ชั่วโมงว่างรอ (ชม.)": round(max(total_horizon_hrs - busy, 0.0), 1),
            "อัตราการใช้งาน (%)": round(util_pct, 1),
            "ข้อความแสดง": f"{util_pct:.1f}% ({busy:.1f} ชม.)"
        })
        
    return pd.DataFrame(gantt_records), pd.DataFrame(summary_records), pd.DataFrame(util_list), total_horizon_hrs

# =========================================================
# การแสดงผล: แยกแท็บช่างหน้าเครื่อง และ Dashboard
# =========================================================
tab_op, tab_dash = st.tabs(["👷 โหมดช่างหน้าเครื่อง (Operator)", "📊 แดชบอร์ดภาพรวมโรงงาน (Dashboard)"])

# ---------------------------------------------------------
# TAB 1: หน้าจอใช้งานของช่างหน้าเครื่อง (Mobile Responsive)
# ---------------------------------------------------------
with tab_op:
    st.subheader("📱 บันทึกสถานะงานหน้าเครื่อง CNC")
    
    df_all = fetch_jobs_from_supabase()
    selected_m = st.selectbox("🏭 เลือกเครื่องจักรที่ท่านปฏิบัติงาน:", MACHINE_LIST, key="op_machine_select")
    
    if not df_all.empty:
        mask_active = (df_all["เลือกเครื่องจักร"] == selected_m) & (df_all["สถานะงาน"].isin(["⚙️ กำลังผลิต", "⏳ รอคิวผลิต"]))
        m_jobs_df = df_all[mask_active].sort_values(by="ID", ascending=True)
    else:
        m_jobs_df = pd.DataFrame()

    if not m_jobs_df.empty:
        curr = m_jobs_df.iloc[0]
        total_cyc = (float(curr.get('เวลาตั้งเครื่อง (นาที)', 0))/60.0) + float(curr.get('Basic Machine (ชม.)', 0)) + float(curr.get('รันโปรแกรม (ชม.)', 0))
        
        st.markdown(f"""
        <div class="op-box">
            <span style="background:#2563EB; color:white; padding:4px 12px; border-radius:6px; font-weight:700; font-size:14px;">งานปัจจุบัน</span>
            <h3 style="margin:12px 0 6px 0; color:#1E3A8A; font-size:22px;">📌 แผนงาน: {curr.get('แผนงาน', '-')}</h3>
            <p style="font-size:18px; margin:4px 0;"><b>📄 ชื่อ Drawing:</b> {curr.get('ชื่อ Drawing.', '-')}</p>
            <p style="margin:4px 0; font-size:15px;"><b>⚙️ ขั้นตอน:</b> {curr.get('ขั้นตอน (Step)', '-')} | <b>วัสดุ:</b> {curr.get('วัสดุ', '-')}</p>
            <p style="margin:4px 0; font-size:15px;"><b>⏱️ เวลารวม:</b> {total_cyc:.2f} ชม. (Setup {int(curr.get('เวลาตั้งเครื่อง (นาที)', 0))} น. / Basic {curr.get('Basic Machine (ชม.)', 0)} ชม. / โปรแกรม {curr.get('รันโปรแกรม (ชม.)', 0)} ชม.)</p>
            <p style="font-size:16px; margin:8px 0 0 0;"><b>🚦 สถานะ:</b> <span style="background:#EEF2FF; padding:4px 10px; border-radius:6px; font-weight:700; color:#1E3A8A;">{curr.get('สถานะงาน', '-')}</span></p>
        </div>
        """, unsafe_allow_html=True)
        
        c_btn1, c_btn2 = st.columns(2)
        with c_btn1:
            if st.button("⚙️ เริ่มขึ้นงาน (Start)", key=f"btn_start_{curr['ID']}", use_container_width=True, type="primary"):
                try:
                    client = get_supabase()
                    target_id = int(curr["ID"])
                    client.table("cnc_jobs").update({
                        "status": "⚙️ กำลังผลิต",
                        "actual_start": datetime.now().isoformat()
                    }).eq("id", target_id).execute()
                    st.toast("✅ บันทึก: กำลังผลิต สำเร็จ!", icon="⚙️")
                    st.rerun()
                except Exception as e:
                    st.error(f"เกิดข้อผิดพลาด: {e}")
                
        with c_btn2:
            if st.button("✅ จบงาน (Finish)", key=f"btn_finish_{curr['ID']}", use_container_width=True):
                try:
                    client = get_supabase()
                    target_id = int(curr["ID"])
                    client.table("cnc_jobs").update({
                        "status": "✅ เสร็จสิ้นแล้ว",
                        "actual_finish": datetime.now().isoformat()
                    }).eq("id", target_id).execute()
                    st.toast("🎉 บันทึก: จบงานเรียบร้อย!", icon="✅")
                    st.rerun()
                except Exception as e:
                    st.error(f"เกิดข้อผิดพลาด: {e}")
                
        if len(m_jobs_df) > 1:
            st.divider()
            st.markdown("**📋 คิวงานรอผลิตถัดไปของเครื่องนี้:**")
            for i, (_, nxt) in enumerate(m_jobs_df.iloc[1:].iterrows(), 1):
                st.markdown(f"{i}. แผนงาน **{nxt.get('แผนงาน', '-')}** | Drawing: `{nxt.get('ชื่อ Drawing.', '-')}` ({nxt.get('ขั้นตอน (Step)', '-')})")
    else:
        st.info(f"🎉 เครื่อง {selected_m} ไม่มีงานค้างในระบบ ทุกรายการผลิตเสร็จสิ้นแล้ว")

# ---------------------------------------------------------
# TAB 2: หน้าจอ Dashboard ภาพรวมโรงงาน
# ---------------------------------------------------------
with tab_dash:
    df_db = fetch_jobs_from_supabase()

    if df_db.empty:
        st.warning("⚠️ ไม่พบข้อมูลในตาราง cnc_jobs บน Supabase กรุณาตรวจสอบตารางข้อมูล")
    else:
        calc_df = df_db.copy()
        calc_df["รวม (ชม.)"] = (calc_df["เวลาตั้งเครื่อง (นาที)"] / 60.0) + calc_df["Basic Machine (ชม.)"] + calc_df["รันโปรแกรม (ชม.)"]
        calc_df["รวม (ชม.)"] = calc_df["รวม (ชม.)"].round(2)

        column_order = [
            "ID", "แผนงาน", "ชื่อ Drawing.", "วัสดุ", "ประเภทงาน", "ขั้นตอน (Step)",
            "เลือกเครื่องจักร", "วัน-เวลาขึ้นงาน", "เวลาตั้งเครื่อง (นาที)",
            "Basic Machine (ชม.)", "รันโปรแกรม (ชม.)", "รวม (ชม.)", "สถานะงาน",
        ]
        calc_df = calc_df[[c for c in column_order if c in calc_df.columns]]

        with st.expander("📝 จัดการรายการสั่งผลิต (เชื่อมต่อ Supabase Database)", expanded=True):
            data_hash = hash(tuple(df_db["สถานะงาน"])) if not df_db.empty else 0
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
            
            c_save, c_refresh = st.columns([2, 8])
            with c_save:
                if st.button("💾 บันทึกข้อมูลลง Supabase", type="primary"):
                    try:
                        client = get_supabase()
                        for _, row in edited_jobs.iterrows():
                            payload = {
                                "plan_code": str(row["แผนงาน"]),
                                "drawing_name": str(row["ชื่อ Drawing."]),
                                "material": str(row["วัสดุ"]),
                                "job_type": str(row["ประเภทงาน"]),
                                "step_name": str(row["ขั้นตอน (Step)"]),
                                "machine_name": str(row["เลือกเครื่องจักร"]),
                                "ready_at": pd.to_datetime(row["วัน-เวลาขึ้นงาน"]).isoformat(),
                                "setup_mins": float(row["เวลาตั้งเครื่อง (นาที)"]),
                                "basic_hrs": float(row["Basic Machine (ชม.)"]),
                                "prog_hrs": float(row["รันโปรแกรม (ชม.)"]),
                                "status": str(row["สถานะงาน"])
                            }
                            if pd.notna(row.get("ID")) and row["ID"] > 0:
                                client.table("cnc_jobs").update(payload).eq("id", int(row["ID"])).execute()
                            else:
                                client.table("cnc_jobs").insert(payload).execute()
                        st.success("บันทึกข้อมูลลงฐานข้อมูลสำเร็จ!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"เกิดข้อผิดพลาดในการบันทึก: {e}")

        # คำนวณตารางเวลาผลิต
        start_time = datetime(2026, 8, 20, 8, 0)
        df_gantt, df_summary, df_util, total_plan_hrs = calculate_shop_schedule(edited_jobs, start_time)

        finished_jobs_df = edited_jobs[edited_jobs["สถานะงาน"] == "✅ เสร็จสิ้นแล้ว"]
        active_jobs_count = len(edited_jobs[edited_jobs["สถานะงาน"].isin(["⏳ รอคิวผลิต", "⚙️ กำลังผลิต"])])
        avg_util = df_util["อัตราการใช้งาน (%)"].mean() if not df_util.empty else 0.0

        # 1. แถบสรุป KPI
        kpi_html = f'''<div class="kpi-container"><div class="kpi-card kpi-green"><div class="kpi-title">✅ งานที่เสร็จสิ้นแล้ว</div><div class="kpi-value">{len(finished_jobs_df)} <span style="font-size:16px;">รายการ</span></div></div><div class="kpi-card kpi-blue"><div class="kpi-title">⚙️ งานในแผนผลิต (Active)</div><div class="kpi-value">{active_jobs_count} <span style="font-size:16px;">รายการ</span></div></div><div class="kpi-card kpi-orange"><div class="kpi-title">⏱️ เวลาเคลียร์งานทั้งหมด</div><div class="kpi-value">{total_plan_hrs:.1f} <span style="font-size:16px;">ชม.</span></div></div><div class="kpi-card kpi-purple"><div class="kpi-title">📊 เฉลี่ยอัตราการใช้เครื่อง</div><div class="kpi-value">{avg_util:.1f} %</div></div></div>'''
        st.markdown(kpi_html, unsafe_allow_html=True)

        if not df_summary.empty:
            # 2. กราฟ Utilization
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

            # 3. ผัง Gantt Chart Timeline
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
                    "⚪ รอรันงาน": "#E2E8F0"
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

            # 4. ใบจ่ายคิวงานหน้าเครื่อง
            st.subheader("📋 ใบจ่ายคิวงานหน้าเครื่อง (Work Order Sheet)")
            df_display = df_summary.sort_values(by="เวลาเริ่มจริง", ascending=True)
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
        else:
            st.info("🎉 ทุกรายการผลิตเสร็จสิ้นทั้งหมดแล้ว ไม่มีงานตกค้างในแผนก")

        # 5. ประวัติรายการที่ผลิตเสร็จแล้ว
        if not finished_jobs_df.empty:
            with st.expander("📦 ประวัติรายการที่ผลิตเสร็จสิ้นแล้ว (Finished History)", expanded=True):
                fin_show = finished_jobs_df.copy()
                fin_show["รวม (ชม.)"] = (fin_show["เวลาตั้งเครื่อง (นาที)"] / 60.0) + fin_show["Basic Machine (ชม.)"] + fin_show["รันโปรแกรม (ชม.)"]
                st.dataframe(
                    fin_show[["สถานะงาน", "แผนงาน", "ชื่อ Drawing.", "วัสดุ", "ขั้นตอน (Step)", "เลือกเครื่องจักร", "Basic Machine (ชม.)", "รันโปรแกรม (ชม.)", "รวม (ชม.)"]],
                    column_config={
                        "สถานะงาน": st.column_config.TextColumn("🚦 สถานะ", width=110),
                        "แผนงาน": st.column_config.TextColumn("📌 แผนงาน", width=85),
                        "ชื่อ Drawing.": st.column_config.TextColumn("📄 ชื่อ Drawing.", width=190),
                        "วัสดุ": st.column_config.TextColumn("🔩 วัสดุ", width=75),
                        "ขั้นตอน (Step)": st.column_config.TextColumn("⚙️ ขั้นตอน (Step)", width=110),
                        "เลือกเครื่องจักร": st.column_config.TextColumn("🏭 เครื่องจักร", width=120),
                        "Basic Machine (ชม.)": st.column_config.NumberColumn("Basic (ชม.)", width=85, format="%.1f"),
                        "รันโปรแกรม (ชม.)": st.column_config.NumberColumn("โปรแกรม (ชม.)", width=95, format="%.1f"),
                        "รวม (ชม.)": st.column_config.NumberColumn("⏳ รวม (ชม.)", width=85, format="%.2f"),
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
