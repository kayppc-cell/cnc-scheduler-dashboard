import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime, timedelta, time as dtime
import zoneinfo
import os
import base64
import json
import html
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

def normalize_filter_key(val):
    """ทำค่าที่ใช้กรองให้เป็นมาตรฐาน เพื่อตัดปัญหาช่องว่าง/ตัวพิมพ์ไม่ตรงกัน"""
    return " ".join(safe_str(val, "").split()).casefold()

def build_performance_metrics(source_df):
    """สร้างเวลามาตรฐานชุดเดียวสำหรับหน้า Drawing และรายงานเดือน โดยไม่ปลอมเวลาจริงที่ขาดหาย"""
    result = source_df.copy()
    for col_name, default_value in [("Setup (น.)", 10.0), ("Basic (น.)", 0.0), ("โปรแกรม (น.)", 0.0)]:
        if col_name not in result.columns:
            result[col_name] = default_value
        result[col_name] = pd.to_numeric(result[col_name], errors="coerce").fillna(default_value).clip(lower=0)
    if "จำนวน" not in result.columns:
        result["จำนวน"] = 1
    result["จำนวน"] = pd.to_numeric(result["จำนวน"], errors="coerce").fillna(1).clip(lower=1).astype(int)
    result["เวลาแผน (ชม.)"] = (
        (result["Setup (น.)"] + result["Basic (น.)"] + result["โปรแกรม (น.)"]) / 60.0
    ).round(2)

    actual_hours, variances, time_sources, schedule_results = [], [], [], []
    actual_starts, actual_finishes, plan_finishes = [], [], []
    for _, row in result.iterrows():
        actual_start = parse_flexible_datetime(row.get("เริ่มจริง"))
        actual_finish = parse_flexible_datetime(row.get("เสร็จจริง"))
        plan_finish = parse_flexible_datetime(row.get("วัน-เวลาจบงาน"))
        actual_starts.append(actual_start)
        actual_finishes.append(actual_finish)
        plan_finishes.append(plan_finish)

        if actual_start is not None and actual_finish is not None and actual_finish >= actual_start:
            paused_seconds = max(0.0, safe_float(row.get("เวลาพักสะสม (วินาที)"), 0.0))
            net_seconds = max(0.0, (actual_finish - actual_start).total_seconds() - paused_seconds)
            actual_value = round(net_seconds / 3600.0, 2)
            actual_hours.append(actual_value)
            variances.append(round(actual_value - safe_float(row.get("เวลาแผน (ชม.)"), 0.0), 2))
            time_sources.append("✅ เวลาจริง")
        else:
            actual_hours.append(float("nan"))
            variances.append(float("nan"))
            time_sources.append("⚠️ เวลาไม่ครบ")

        if actual_finish is not None and plan_finish is not None:
            schedule_results.append(actual_finish <= plan_finish)
        else:
            schedule_results.append(pd.NA)

    result["_actual_start_dt"] = actual_starts
    result["_actual_finish_dt"] = actual_finishes
    result["_plan_finish_dt"] = plan_finishes
    result["เวลาจริง (ชม.)"] = actual_hours
    result["ผลต่าง (ชม.)"] = variances
    result["แหล่งเวลา"] = time_sources
    result["_schedule_on_time"] = pd.Series(schedule_results, index=result.index, dtype="boolean")
    return result

def unique_drawing_quantity(source_df, extra_group_cols=None):
    """นับจำนวนชิ้นหนึ่งครั้งต่อแผนงาน+Drawing ป้องกันการบวกซ้ำตามจำนวน Step"""
    if source_df.empty:
        return 0
    group_cols = list(extra_group_cols or []) + ["แผนงาน", "ชื่อ Drawing."]
    valid_cols = [c for c in group_cols if c in source_df.columns]
    if not valid_cols:
        return int(pd.to_numeric(source_df.get("จำนวน", 1), errors="coerce").fillna(1).max())
    qty_series = pd.to_numeric(source_df["จำนวน"], errors="coerce").fillna(1).clip(lower=1)
    qty_frame = source_df[valid_cols].copy()
    qty_frame["_qty"] = qty_series
    return int(qty_frame.groupby(valid_cols, dropna=False)["_qty"].max().sum())

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
        # ตารางแสดงเวลาเป็น HH:MM แต่รูปแบบเดิมบังคับ HH:MM:SS จึงได้ NaT ตอนบันทึก
        if len(time_part.split(":")) == 2:
            time_part = f"{time_part}:00"
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

def format_thai_datetime(dt_val):
    """แปลงวันเวลาเป็นข้อความ DD/MM/YYYY HH:MM ก่อนเข้า data_editor เพื่อกัน pandas สลับวัน/เดือน"""
    dt_parsed = parse_flexible_datetime(dt_val)
    if dt_parsed is None or pd.isna(dt_parsed):
        return ""
    return dt_parsed.strftime("%d/%m/%Y %H:%M")

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

def get_work_capacity_between(range_start: datetime, range_end: datetime) -> float:
    """ชั่วโมงที่โรงงานเปิดจริงภายในช่วงเวลา (หักพักและวันหยุด)"""
    if range_end <= range_start:
        return 0.0
    total_hours = 0.0
    cur_date = range_start.date()
    while cur_date <= range_end.date():
        for window_start, window_end in get_day_working_windows(cur_date):
            overlap_start = max(window_start, range_start)
            overlap_end = min(window_end, range_end)
            if overlap_end > overlap_start:
                total_hours += (overlap_end - overlap_start).total_seconds() / 3600.0
        cur_date += timedelta(days=1)
    return total_hours

def get_planned_busy_hours_in_range(start_dt: datetime, duration_hours: float, range_start: datetime, range_end: datetime) -> float:
    """ชั่วโมงแผนของงานที่ทับกับช่วงวิเคราะห์ โดยใช้กะเดียวกับ Auto-Chain"""
    if start_dt is None or duration_hours <= 0 or range_end <= range_start:
        return 0.0
    segments, _ = add_work_time_with_shift(start_dt, duration_hours)
    busy_hours = 0.0
    for seg_start, seg_end in segments:
        overlap_start = max(seg_start, range_start)
        overlap_end = min(seg_end, range_end)
        if overlap_end > overlap_start:
            busy_hours += (overlap_end - overlap_start).total_seconds() / 3600.0
    return busy_hours

def is_deadline_active_status(status_val):
    """เกณฑ์กลางเดียวกันสำหรับ TV Live และใบจ่ายคิว: ทุกงานที่ยังไม่เสร็จ"""
    status = str(status_val)
    if "เสร็จสิ้น" in status:
        return False
    return any(keyword in status for keyword in ["กำลังผลิต", "พักงาน", "รอวัสดุ", "รอคิว"])

def highlight_running_deadlines(row, planned_finish_map):
    status = str(row.get("สถานะ", row.get("สถานะงาน", "")))
    job_id = str(row.get("ID", ""))

    if is_deadline_active_status(status):
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
    @keyframes operatorOverduePulse {
        0%, 100% { box-shadow: 0 0 0 2px #FCA5A5, 0 3px 10px rgba(220,38,38,0.30); background:#FFF7F7; }
        50% { box-shadow: 0 0 0 5px #EF4444, 0 0 24px rgba(239,68,68,0.80); background:#FEE2E2; }
    }
    .step-card-overdue { border: 2px solid #DC2626 !important; animation: operatorOverduePulse 1.15s ease-in-out infinite; }
    .op-job-header-overdue { border: 2px solid #DC2626 !important; background: linear-gradient(135deg, #FFF1F2 0%, #FEE2E2 100%) !important; }
    .badge-overdue {
        background:#FFFFFF !important;
        color:#DC2626 !important;
        -webkit-text-fill-color:#DC2626 !important;
        border:2px solid #DC2626 !important;
        font-weight:900 !important;
        text-shadow:none !important;
        box-shadow:0 0 0 2px rgba(220,38,38,0.18);
        animation: operatorOverduePulse 1.15s ease-in-out infinite;
    }
    div.stButton > button:disabled { background-color: #F1F5F9 !important; color: #94A3B8 !important; border-color: #CBD5E1 !important; cursor: not-allowed !important; }

    .tv-grid-container { display: grid; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr)); gap: 14px; margin-top: 10px; }
    .tv-card { border-radius: 14px; padding: 16px 18px; color: #FFFFFF !important; box-shadow: 0 6px 18px rgba(0,0,0,0.16); display: flex; flex-direction: column; justify-content: space-between; min-height: 180px; border: 1px solid rgba(255,255,255,0.12); }
    .tv-card-running { background: linear-gradient(135deg, #065F46 0%, #059669 100%) !important; border-left: 7px solid #34D399 !important; }
    .tv-card-warning { background: linear-gradient(135deg, #9A3412 0%, #C2410C 100%) !important; border-left: 7px solid #FDE047 !important; }
    .tv-card-late { background: linear-gradient(135deg, #7F1D1D 0%, #991B1B 100%) !important; border-left: 7px solid #EF4444 !important; }
    @keyframes tvOverduePulse {
        0%, 100% { transform: scale(1); box-shadow: 0 0 0 2px #FDE047, 0 4px 14px rgba(239,68,68,0.45); filter: brightness(1); }
        50% { transform: scale(1.012); box-shadow: 0 0 0 5px #EF4444, 0 0 26px rgba(239,68,68,0.95); filter: brightness(1.35); }
    }
    .tv-card-overdue {
        background: linear-gradient(135deg, #7F1D1D 0%, #DC2626 100%) !important;
        border: 2px solid #FDE047 !important;
        border-left: 7px solid #FDE047 !important;
        animation: tvOverduePulse 1.2s ease-in-out infinite;
    }
    .tv-overdue-badge { color:#FFFFFF; background:#DC2626; border:1px solid #FDE047; padding:2px 6px; border-radius:6px; font-weight:900; }
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

    /* มาตรฐานหน้าตาตารางทั้งระบบ */
    div[data-testid="stDataFrame"] {
        border: 1px solid #DCE3EC;
        border-radius: 10px;
        overflow: hidden;
        box-shadow: 0 2px 8px rgba(15, 23, 42, 0.05);
    }
    div[data-testid="stDataFrame"] [role="columnheader"] {
        font-size: 12px !important;
        font-weight: 700 !important;
        color: #334155 !important;
    }
    div[data-testid="stDataFrame"] [role="gridcell"] {
        font-size: 12px !important;
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

def verify_supabase_ready_at(job_id: int, expected_dt: datetime) -> bool:
    """อ่านค่ากลับหลังบันทึก ป้องกันการรีเฟรชหน้าถ้าฐานข้อมูลไม่ได้เก็บเวลาจริง"""
    try:
        base_url = st.secrets["SUPABASE_URL"].rstrip("/")
        endpoint = f"{base_url}/rest/v1/cnc_jobs?id=eq.{job_id}&select=ready_at"
        res = requests.get(endpoint, headers=get_supabase_headers(), timeout=8)
        if res.status_code != 200 or not res.json():
            return False
        actual_dt = parse_flexible_datetime(res.json()[0].get("ready_at"))
        if actual_dt is None or pd.isna(actual_dt):
            return False
        return actual_dt.replace(second=0, microsecond=0) == expected_dt.replace(second=0, microsecond=0)
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
                if "hold_started_at" in df.columns:
                    df["hold_started_at"] = df["hold_started_at"].apply(parse_flexible_datetime)
                else:
                    df["hold_started_at"] = None
                if "paused_seconds" in df.columns:
                    df["paused_seconds"] = pd.to_numeric(df["paused_seconds"], errors="coerce").fillna(0.0)
                else:
                    df["paused_seconds"] = 0.0
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
                    "status": "สถานะงาน", "actual_start": "เริ่มจริง", "actual_finish": "เสร็จจริง",
                    "hold_started_at": "เริ่มพักจริง", "paused_seconds": "เวลาพักสะสม (วินาที)"
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
            banner_paused_seconds = int(safe_float(r_cur.get("เวลาพักสะสม (วินาที)"), 0.0))
            st_txt = "-"
            start_epoch = to_bangkok_epoch_ms(st_t)
            act_dt = parse_flexible_datetime(st_t)
            if act_dt is not None:
                st_txt = act_dt.strftime("%H:%M น.")

            st.markdown(f"""
            <div class="shop-live-banner shop-live-running">
                <div style="display:flex; align-items:center; gap:10px;">
                    <span class="tv-pulse-dot"></span>
                    <span>🟢 <b>{selected_m}: กำลังรันงานอยู่</b> (เริ่ม: {st_txt} | ⏱️ เดินสุทธิ: <span class="pes-live-timer" data-start-epoch="{start_epoch}" data-paused-seconds="{banner_paused_seconds}" style="font-family:monospace; font-weight:900; font-size:15px; color:#065F46;">00:00:00</span>)</span>
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
                    update_results = [
                        update_supabase_job(int(r["ID"]), {
                            "status": "🟦 กำลังผลิต", "actual_start": now_str, "actual_finish": None,
                            "hold_started_at": None, "paused_seconds": 0
                        })
                        for _, r in waiting_jobs.iterrows()
                    ]
                    if update_results and all(update_results):
                        st.toast("เริ่มจับเวลาจริงทุกคิวพร้อมกันเรียบร้อย!", icon="🚀")
                        st.rerun()
                    else:
                        st.error("Start แบบกลุ่มไม่สำเร็จครบทุกรายการ กรุณาตรวจสอบการเชื่อมต่อ Supabase")

            with b_c2:
                if st.button(f"🏁 Finish รวมทุกงานที่กำลังรัน ({len(running_jobs)} คิว)", disabled=(len(running_jobs) == 0), type="secondary", use_container_width=True):
                    now_str = get_bangkok_str()
                    update_results = [
                        update_supabase_job(int(r["ID"]), {"status": "🟩 เสร็จสิ้นแล้ว", "actual_finish": now_str})
                        for _, r in running_jobs.iterrows()
                    ]
                    if update_results and all(update_results):
                        st.toast("บันทึกจบงานจริงทุกคิวเรียบร้อย!", icon="🏁")
                        st.rerun()
                    else:
                        st.error("Finish แบบกลุ่มไม่สำเร็จครบทุกรายการ กรุณาตรวจสอบการเชื่อมต่อ Supabase")

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
            s_hold_started = step_row.get("เริ่มพักจริง")
            s_paused_seconds = safe_float(step_row.get("เวลาพักสะสม (วินาที)"), 0.0)

            is_step_running = "กำลังผลิต" in s_status
            is_step_hold = "พักงาน" in s_status
            is_step_finished = "เสร็จสิ้น" in s_status
            is_step_waiting = not is_step_running and not is_step_finished and not is_step_hold
            is_urgent = "ด่วนแทรก" in str(step_row.get("ประเภทงาน", ""))

            s_m = safe_float(step_row.get("Setup (น.)"), 10.0)
            b_m = safe_float(step_row.get("Basic (น.)"), 0.0)
            p_m = safe_float(step_row.get("โปรแกรม (น.)"), 120.0)
            tot_h = (s_m + b_m + p_m) / 60.0

            # หน้าช่างต้องแสดงเวลาแผนที่ล็อกและ Auto-save ไว้โดยตรง
            # ห้ามต่อลูกโซ่ใหม่หลังเรียงสถานะ เพราะจะทำให้เวลาแผนขยับจากหน้าวางแผน
            r_parsed = parse_flexible_datetime(step_row.get("วัน-เวลาขึ้นงาน"))
            if r_parsed is None or pd.isna(r_parsed) or r_parsed.year < 2020:
                start_w_dt = None
            else:
                start_w_dt = get_next_valid_work_time(r_parsed)

            stored_finish_w_dt = parse_flexible_datetime(step_row.get("วัน-เวลาจบงาน"))
            if start_w_dt is None:
                finish_w_dt = None
                ready_display_str = "-"
                finish_plan_display_str = "-"
            else:
                # ใช้เวลาจบแผนที่บันทึกไว้เป็นหลัก เพื่อให้ทุกหน้าตรวจหลุดแผนจากค่าเดียวกัน
                if stored_finish_w_dt is not None and pd.notna(stored_finish_w_dt):
                    finish_w_dt = stored_finish_w_dt
                else:
                    _, finish_w_dt = add_work_time_with_shift(start_w_dt, tot_h)
                ready_display_str = start_w_dt.strftime("%d/%m/%Y %H:%M น.")
                finish_plan_display_str = finish_w_dt.strftime("%d/%m/%Y %H:%M น.")

            operator_now = get_bangkok_now().replace(tzinfo=None)
            is_running_overdue = bool(
                is_step_running and finish_w_dt is not None and pd.notna(finish_w_dt) and operator_now > finish_w_dt
            )
            overdue_minutes = int((operator_now - finish_w_dt).total_seconds() // 60) if is_running_overdue else 0

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
                if is_running_overdue:
                    header_box_class = "op-job-header op-job-header-overdue"
                    badge_gradient = "linear-gradient(135deg, #B91C1C 0%, #EF4444 100%)"
                    status_badge_html = f'<span class="badge-chip badge-overdue">🚨 หลุดแผน {overdue_minutes // 60:02d}:{overdue_minutes % 60:02d} ชม.</span>'
                else:
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
            if is_running_overdue: card_style_class += " step-card-overdue"
            elif is_step_running: card_style_class += " step-card-running"
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
                    st.caption(f"""**ขั้นตอน:** <span style='color:#059669; font-weight:800; font-size:14px;'><span class='tv-pulse-dot' style='margin-right:6px;'></span> 🟦 กำลังผลิต (เริ่มรัน: {start_txt}) | ⏱️ เวลาเดินสุทธิ: <span class='pes-live-timer' data-start-epoch='{step_start_epoch}' data-paused-seconds='{int(s_paused_seconds)}' style='font-family:monospace; font-size:16px; font-weight:900; color:#047857;'>00:00:00</span></span>""", unsafe_allow_html=True)
                    if is_running_overdue:
                        st.error(f"🚨 งานนี้กำลังผลิตและเกินเวลาจบตามแผนแล้ว {overdue_minutes // 60} ชม. {overdue_minutes % 60} นาที")
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
                                if update_supabase_job(target_id, {"step_name": safe_str(step_val, s_name)}):
                                    st.toast("บันทึกชื่อขั้นตอนเรียบร้อย!", icon="💾")
                                    st.rerun()
                                else:
                                    st.error("บันทึกชื่อขั้นตอนไม่สำเร็จ")
                        with c_btn_resume:
                            if st.button("▶️ ได้วัสดุใหม่แล้ว (Resume เริ่มรันต่อ)", key=f"btn_resume_{target_id}", type="primary", use_container_width=True):
                                resume_payload = {"step_name": safe_str(step_val, s_name), "status": "🟦 กำลังผลิต"}
                                hold_started_dt = parse_flexible_datetime(s_hold_started)
                                if hold_started_dt is not None:
                                    pause_delta = max(0.0, (get_bangkok_now().replace(tzinfo=None) - hold_started_dt).total_seconds())
                                    resume_payload["paused_seconds"] = s_paused_seconds + pause_delta
                                resume_payload["hold_started_at"] = None
                                # รักษาเวลาเริ่มจริงครั้งแรกไว้ ไม่เขียนทับทุกครั้งที่ Resume
                                if parse_flexible_datetime(s_start) is None:
                                    resume_payload["actual_start"] = get_bangkok_str()
                                if update_supabase_job(target_id, resume_payload):
                                    st.toast("เริ่มรันงานต่อเรียบร้อย!", icon="🚀")
                                    st.rerun()
                                else:
                                    st.error("Resume ไม่สำเร็จ")
                    elif is_step_running:
                        c_btn_save, c_btn_hold, c_btn_finish = st.columns([1.5, 2.5, 2])
                        with c_btn_save:
                            if st.button("💾 บันทึกชื่อ", key=f"btn_save_edit_{target_id}", use_container_width=True):
                                if update_supabase_job(target_id, {"step_name": safe_str(step_val, s_name)}):
                                    st.toast("บันทึกชื่อขั้นตอนเรียบร้อย!", icon="💾")
                                    st.rerun()
                                else:
                                    st.error("บันทึกชื่อขั้นตอนไม่สำเร็จ")
                        with c_btn_hold:
                            if st.button("🛑 พักงาน (รอวัสดุใหม่)", key=f"btn_hold_{target_id}", use_container_width=True):
                                if update_supabase_job(target_id, {
                                    "step_name": safe_str(step_val, s_name),
                                    "status": "🟨 พักงาน (รอวัสดุ)",
                                    "hold_started_at": get_bangkok_str()
                                }):
                                    st.toast("พักงานเรียบร้อย!", icon="🛑")
                                    st.rerun()
                                else:
                                    st.error("เปลี่ยนสถานะพักงานไม่สำเร็จ")
                        with c_btn_finish:
                            if st.button("🏁 Finish (จบงานจริง)", key=f"btn_finish_step_{target_id}", type="primary", use_container_width=True):
                                if update_supabase_job(target_id, {"status": "🟩 เสร็จสิ้นแล้ว", "actual_finish": get_bangkok_str()}):
                                    st.toast("บันทึกเวลาจบจริงเรียบร้อย!", icon="🏁")
                                    st.rerun()
                                else:
                                    st.error("บันทึกจบงานจริงไม่สำเร็จ")
                    else:
                        c_btn_save, c_btn_start, c_btn_finish = st.columns([1.5, 2, 2])
                        with c_btn_save:
                            if st.button("💾 บันทึกชื่อ", key=f"btn_save_edit_{target_id}", use_container_width=True):
                                if update_supabase_job(target_id, {"step_name": safe_str(step_val, s_name)}):
                                    st.toast("บันทึกชื่อขั้นตอนเรียบร้อย!", icon="💾")
                                    st.rerun()
                                else:
                                    st.error("บันทึกชื่อขั้นตอนไม่สำเร็จ")
                        with c_btn_start:
                            if can_start:
                                if st.button("🚀 Start (เริ่มจับเวลาจริง)", key=f"btn_start_step_{target_id}", type="primary", use_container_width=True):
                                    start_payload = {
                                        "step_name": safe_str(step_val, s_name),
                                        "status": "🟦 กำลังผลิต",
                                        "actual_start": get_bangkok_str(),
                                        "actual_finish": None,
                                        "hold_started_at": None,
                                        "paused_seconds": 0
                                    }
                                    if update_supabase_job(target_id, start_payload):
                                        st.toast("เริ่มผลิตแล้ว!", icon="🚀")
                                        st.rerun()
                                    else:
                                        st.error("เริ่มงานไม่สำเร็จ")
                            else:
                                st.button("🚀 Start", key=f"btn_start_disabled_{target_id}", disabled=True, use_container_width=True)
                        with c_btn_finish:
                            st.button("🏁 Finish", key=f"btn_finish_disabled_{target_id}", disabled=True, use_container_width=True)

                st.markdown("</div>", unsafe_allow_html=True)

            with st.expander(f"➕ เพิ่ม Step ถัดไปสำหรับ {plan_code} ({drawing_code})", expanded=False):
                new_step_input = st.text_input("ชื่อ Step ถัดไป:", value=f"OP{(queue_idx+2)*10}", placeholder="เช่น OP20, กลึง, เจียร, เชื่อม", key=f"new_step_name_input_{target_id}")

                if st.button(f"➕ บันทึกเพิ่มขั้นตอนต่อท้าย", key=f"btn_add_step_{target_id}", type="secondary", use_container_width=True):
                    base_setup = safe_float(step_row.get("Setup (น.)"), 10.0)
                    base_basic = safe_float(step_row.get("Basic (น.)"), 0.0)
                    base_prog = safe_float(step_row.get("โปรแกรม (น.)"), 120.0)
                    # Step ถัดไปต้องเริ่มต่อจากเวลาจบตามแผนของ Step นี้ ไม่ใช่เวลาปัจจุบัน
                    next_ready_str = finish_w_dt.strftime("%Y-%m-%d %H:%M:%S") if finish_w_dt is not None else None
                    
                    new_payload = {
                        "plan_code": str(plan_code),
                        "drawing_name": str(drawing_code),
                        "qty": int(qty_val),
                        "material": str(mat_val),
                        "job_type": str(step_row.get("ประเภทงาน", "🟢 งานปกติ")),
                        "step_name": new_step_input.strip() if new_step_input.strip() != "" else f"OP{(queue_idx+2)*10}",
                        "machine_name": selected_m,
                        "ready_at": next_ready_str,
                        "setup_mins": base_setup,
                        "basic_hrs": base_basic,
                        "prog_hrs": base_prog,
                        "status": "🟧 รอคิวผลิต"
                    }
                    if insert_supabase_job(new_payload):
                        st.cache_data.clear()
                        st.toast(f"เพิ่มขั้นตอน {new_step_input} เรียบร้อยแล้ว!", icon="🚀")
                        st.rerun()
                    else:
                        st.error("เพิ่ม Step ไม่สำเร็จ กรุณาตรวจสอบการเชื่อมต่อ Supabase")
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
                        const pausedSecs = parseFloat(el.getAttribute('data-paused-seconds') || '0') || 0;
                        const diffMs = Math.max(0, nowTs - startTs - (pausedSecs * 1000));
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
# VIEW 2: แดชบอร์ดภาพรวมโรงงาน (ล็อก Baseline + รันลูกโซ่ 100%)
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
                tracker_source = calc_df.copy()
                # ไม่ปล่อยให้ groupby ตัดรายการที่รหัสแผนงานหรือ Drawing ว่างทิ้งไปเงียบ ๆ
                tracker_source["แผนงาน"] = tracker_source["แผนงาน"].map(lambda v: safe_str(v, "ไม่ระบุแผนงาน"))
                tracker_source["ชื่อ Drawing."] = tracker_source["ชื่อ Drawing."].map(lambda v: safe_str(v, "ไม่ระบุ Drawing"))
                tracker_source["สถานะงาน"] = tracker_source["สถานะงาน"].map(safe_str)

                for (p_c, d_c), g_data in tracker_source.groupby(["แผนงาน", "ชื่อ Drawing."], dropna=False):
                    total_steps = len(g_data)
                    fin_steps = len(g_data[g_data["สถานะงาน"] == "🟩 เสร็จสิ้นแล้ว"])
                    pct = round(fin_steps / total_steps * 100) if total_steps > 0 else 0
                    
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
                        waiting_rows = g_data[g_data["สถานะงาน"] == "🟧 รอคิวผลิต"]
                        if not waiting_rows.empty:
                            first_wait = waiting_rows.iloc[0]
                            stage = f"🟧 รอคิวที่ {safe_str(first_wait.get('เลือกเครื่องจักร'), 'ยังไม่ระบุเครื่อง')}"
                            cat_status = "WAITING"
                        else:
                            # ป้องกันระบบล่มเมื่อฐานข้อมูลมีสถานะว่างหรือสถานะเก่าที่ไม่อยู่ในมาตรฐาน
                            stage = "⚠️ กรุณาตรวจสอบสถานะงาน"
                            cat_status = "UNKNOWN"

                    qty_values = pd.to_numeric(g_data["จำนวน"], errors="coerce").dropna()
                    drawing_qty = safe_int(qty_values.max(), 1) if not qty_values.empty else 1

                    drawing_progress_list.append({
                        "แผนงาน": p_c,
                        "ชื่อ Drawing.": d_c,
                        "จำนวน (ชิ้น)": drawing_qty,
                        "ความคืบหน้า (%)": pct,
                        "ขั้นตอน (เสร็จ/ทั้งหมด)": f"{fin_steps}/{total_steps} Step",
                        "สถานะและสถานีปัจจุบัน": stage,
                        "status_category": cat_status
                    })
                
                tracker_columns = [
                    "แผนงาน", "ชื่อ Drawing.", "จำนวน (ชิ้น)", "ความคืบหน้า (%)",
                    "ขั้นตอน (เสร็จ/ทั้งหมด)", "สถานะและสถานีปัจจุบัน", "status_category"
                ]
                df_dp_all = pd.DataFrame(drawing_progress_list, columns=tracker_columns)
                if not df_dp_all.empty:
                    status_order = {"RUNNING": 0, "HOLD": 1, "WAITING": 2, "UNKNOWN": 3, "DONE": 4}
                    df_dp_all["_status_order"] = df_dp_all["status_category"].map(status_order).fillna(3)
                    df_dp_all = df_dp_all.sort_values(
                        by=["_status_order", "ความคืบหน้า (%)", "แผนงาน", "ชื่อ Drawing."],
                        ascending=[True, False, True, True]
                    ).drop(columns=["_status_order"])
                
                cnt_all = len(df_dp_all)
                cnt_done = len(df_dp_all[df_dp_all["status_category"] == "DONE"])
                cnt_run = len(df_dp_all[df_dp_all["status_category"] == "RUNNING"])
                cnt_wait = len(df_dp_all[df_dp_all["status_category"] == "WAITING"])
                cnt_hold = len(df_dp_all[df_dp_all["status_category"] == "HOLD"])
                cnt_unknown = len(df_dp_all[df_dp_all["status_category"] == "UNKNOWN"])

                tk_btn_col, tk_search_col = st.columns([5.5, 4.5])
                with tk_btn_col:
                    st.caption("**🎯 ตัวกรองด่วนสถานะ Drawing:**")
                    t_b1, t_b2, t_b3, t_b4, t_b5 = st.columns(5)
                    cur_tracker_filter = st.session_state.get("drawing_tracker_filter", "ALL")
                    with t_b1:
                        b_type_all = "primary" if cur_tracker_filter == "ALL" else "secondary"
                        if st.button(f"🌐 ทั้งหมด ({cnt_all})", type=b_type_all, use_container_width=True, key="btn_tk_all"):
                            st.session_state.drawing_tracker_filter = "ALL"
                            cur_tracker_filter = "ALL"
                    with t_b2:
                        b_type_done = "primary" if cur_tracker_filter == "DONE" else "secondary"
                        if st.button(f"🟢 ผลิตเสร็จ ({cnt_done})", type=b_type_done, use_container_width=True, key="btn_tk_done"):
                            st.session_state.drawing_tracker_filter = "DONE"
                            cur_tracker_filter = "DONE"
                    with t_b3:
                        b_type_run = "primary" if cur_tracker_filter == "RUNNING" else "secondary"
                        if st.button(f"🟦 กำลังรัน ({cnt_run})", type=b_type_run, use_container_width=True, key="btn_tk_run"):
                            st.session_state.drawing_tracker_filter = "RUNNING"
                            cur_tracker_filter = "RUNNING"
                    with t_b4:
                        b_type_wait = "primary" if cur_tracker_filter == "WAITING" else "secondary"
                        if st.button(f"🟧 รอคิว ({cnt_wait})", type=b_type_wait, use_container_width=True, key="btn_tk_wait"):
                            st.session_state.drawing_tracker_filter = "WAITING"
                            cur_tracker_filter = "WAITING"
                    with t_b5:
                        b_type_hold = "primary" if cur_tracker_filter == "HOLD" else "secondary"
                        if st.button(f"🟨 พักงาน ({cnt_hold})", type=b_type_hold, use_container_width=True, key="btn_tk_hold"):
                            st.session_state.drawing_tracker_filter = "HOLD"
                            cur_tracker_filter = "HOLD"

                with tk_search_col:
                    search_query_tracker = st.text_input(
                        "🔍 ค้นหาในตารางความคืบหน้า (แผนงาน, Drawing):",
                        placeholder="พิมพ์เพื่อค้นหา เช่น 26-108, AS256...",
                        key="search_drawing_tracker_input"
                    )

                df_dp = df_dp_all.copy()
                selected_filter = cur_tracker_filter
                if selected_filter == "DONE":
                    df_dp = df_dp[df_dp["status_category"] == "DONE"]
                elif selected_filter == "RUNNING":
                    df_dp = df_dp[df_dp["status_category"] == "RUNNING"]
                elif selected_filter == "WAITING":
                    df_dp = df_dp[df_dp["status_category"] == "WAITING"]
                elif selected_filter == "HOLD":
                    df_dp = df_dp[df_dp["status_category"] == "HOLD"]

                if search_query_tracker.strip() != "":
                    q_tk = search_query_tracker.strip().lower()
                    df_dp = df_dp[
                        df_dp["แผนงาน"].astype(str).str.lower().str.contains(q_tk, regex=False, na=False) |
                        df_dp["ชื่อ Drawing."].astype(str).str.lower().str.contains(q_tk, regex=False, na=False)
                    ]

                if cnt_unknown > 0:
                    st.warning(f"⚠️ พบ Drawing ที่มีสถานะงานไม่ถูกต้องหรือว่าง {cnt_unknown} รายการ กรุณาตรวจสอบสถานะในตารางสั่งผลิต")

                tracker_view = df_dp[[c for c in df_dp.columns if c != "status_category"]]
                tracker_styled = tracker_view.style.bar(
                    subset=["ความคืบหน้า (%)"], color="#86EFAC", vmin=0, vmax=100
                )

                st.dataframe(
                    tracker_styled,
                    column_config={
                        "แผนงาน": st.column_config.TextColumn("แผนงาน", width=75),
                        "ชื่อ Drawing.": st.column_config.TextColumn("Drawing", width=155),
                        "จำนวน (ชิ้น)": st.column_config.NumberColumn("จำนวน", width=55),
                        "ความคืบหน้า (%)": st.column_config.NumberColumn("ความคืบหน้า", width=125, min_value=0, max_value=100, format="%d%%"),
                        "ขั้นตอน (เสร็จ/ทั้งหมด)": st.column_config.TextColumn("สเต็ปงาน", width=95),
                        "สถานะและสถานีปัจจุบัน": st.column_config.TextColumn("สถานะ/สถานีปัจจุบัน", width=190),
                    },
                    hide_index=True,
                    width=980,
                    row_height=30
                )

            st.divider()

            # =========================================================================
            # 🔗 ระบบลูกโซ่สมบูรณ์: ล็อก Baseline ตั้งต้น + ส่งต่อเวลาคิวงาน (Auto-Chain)
            # =========================================================================
            column_order = [
                "ID", "แผนงาน", "ชื่อ Drawing.", "จำนวน", "วัสดุ", "ประเภทงาน", "ขั้นตอน (Step)",
                "เลือกเครื่องจักร", "วัน-เวลาขึ้นงาน", "Setup (น.)",
                "Basic (น.)", "โปรแกรม (น.)", "รวม (ชม.)", "สถานะงาน",
            ]
            calc_df = calc_df[[c for c in column_order if c in calc_df.columns]]
            active_jobs_editor_df = calc_df[calc_df["สถานะงาน"].isin(["🟧 รอคิวผลิต", "🟦 กำลังผลิต", "🟨 พักงาน (รอวัสดุ)"])].copy()

            # ต้องเปลี่ยน dtype จาก datetime64 เป็น string ก่อนรับค่าจาก data_editor
            # ไม่เช่นนั้น pandas อาจแปลง 03/09/2026 เป็น 9 มีนาคมแบบ month-first ทันทีที่แก้เซลล์
            active_jobs_editor_df["วัน-เวลาขึ้นงาน"] = active_jobs_editor_df["วัน-เวลาขึ้นงาน"].apply(format_thai_datetime).astype("object")

            # เก็บค่าเวลาตั้งต้นเดิมไว้เป็น Baseline สำหรับสอบกลับ ไม่แตะต้อง
            active_jobs_editor_df["กำหนดพร้อมขึ้นงาน (Baseline)"] = active_jobs_editor_df["วัน-เวลาขึ้นงาน"]

            # จัดลำดับความสำคัญ: กำลังผลิต (0) -> พักงาน (1) -> รอคิว (2) ตามเวลาขึ้นงานเดิม
            def get_queue_priority(r):
                st_val = str(r.get("สถานะงาน", ""))
                prio = 0 if "กำลังผลิต" in st_val else (1 if "พักงาน" in st_val else 2)
                dt_p = parse_flexible_datetime(r.get("วัน-เวลาขึ้นงาน"))
                return (str(r.get("เลือกเครื่องจักร")), prio, dt_p if dt_p is not None else pd.Timestamp.max, safe_int(r.get("ID")))

            active_jobs_editor_df["_sort_key"] = active_jobs_editor_df.apply(get_queue_priority, axis=1)
            active_jobs_editor_df = active_jobs_editor_df.sort_values(by="_sort_key").drop(columns=["_sort_key"]).reset_index(drop=True)

            # ล้าง event เดิมหลัง Auto-save สำเร็จ ก่อนสร้าง widget รอบใหม่
            if st.session_state.pop("reset_cnc_editor_after_autosave", False):
                st.session_state.pop("editor_cnc_jobs_grid_main", None)

            editor_state = st.session_state.get("editor_cnc_jobs_grid_main", {})
            edited_rows = editor_state.get("edited_rows", {})
            autosave_requested = False
            affected_machines = set()
            # edited_rows ใช้เลขแถวของตารางที่ผู้ใช้เห็น (ซึ่งอาจผ่านการค้นหา/กรองแล้ว)
            # จึงต้องแปลงกลับด้วย ID ห้ามนำเลขแถวนั้นไปชี้ active_jobs_editor_df โดยตรง
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
                    # รองรับหน้าแรกก่อนที่จะมีรายการ ID ใน session (กรณีไม่กรองตาราง)
                    elif r_i < len(active_jobs_editor_df):
                        target_idx = r_i

                    if target_idx is not None:
                        old_machine = safe_str(active_jobs_editor_df.at[target_idx, "เลือกเครื่องจักร"], "")
                        for col_name, new_val in changes.items():
                            if col_name in active_jobs_editor_df.columns:
                                active_jobs_editor_df.at[target_idx, col_name] = new_val
                            if col_name != "ลบ":
                                autosave_requested = True
                        if autosave_requested:
                            if old_machine:
                                affected_machines.add(old_machine)
                            new_machine = safe_str(active_jobs_editor_df.at[target_idx, "เลือกเครื่องจักร"], "")
                            if new_machine:
                                affected_machines.add(new_machine)

            # คำนวณระบบลูกโซ่ (Auto-Chain): คิวแรกตั้งต้น -> คิวถัดไปรับเวลาจบจากคิวก่อนหน้า
            m_available_tracker = {}
            chained_start_dates = []
            chained_finish_dates = []

            for _, r in active_jobs_editor_df.iterrows():
                m_target = str(r["เลือกเครื่องจักร"])
                s_m = safe_float(r.get("Setup (น.)"), 10.0)
                b_m = safe_float(r.get("Basic (น.)"), 0.0)
                p_m = safe_float(r.get("โปรแกรม (น.)"), 120.0)
                tot_h = (s_m + b_m + p_m) / 60.0

                if m_target not in m_available_tracker:
                    r_parsed = parse_flexible_datetime(r["วัน-เวลาขึ้นงาน"])
                    # ห้ามใช้เวลาปัจจุบันแทนค่า เพราะจะทำให้เวลาแผนเลื่อนเองทุกครั้งที่ rerun
                    if r_parsed is None or pd.isna(r_parsed) or r_parsed.year < 2020:
                        m_available_tracker[m_target] = None
                        chained_start_dates.append("")
                        chained_finish_dates.append("")
                        continue
                    start_work_dt = get_next_valid_work_time(r_parsed)
                else:
                    previous_finish = m_available_tracker[m_target]
                    # ถ้าคิวแรกยังไม่มีเวลา คิวถัดไปต้องรอ ไม่สร้างเวลาใหม่เอง
                    if previous_finish is None:
                        chained_start_dates.append("")
                        chained_finish_dates.append("")
                        continue
                    start_work_dt = get_next_valid_work_time(previous_finish)

                _, finish_work_dt = add_work_time_with_shift(start_work_dt, tot_h)
                m_available_tracker[m_target] = finish_work_dt

                chained_start_dates.append(start_work_dt.strftime("%d/%m/%Y %H:%M"))
                chained_finish_dates.append(finish_work_dt.strftime("%d/%m/%Y %H:%M"))

            # อัปเดตเวลาเข้าสู่ตาราง (วัน-เวลาขึ้นงาน/จบงาน จะเป็นเวลาลูกโซ่จริง)
            active_jobs_editor_df["วัน-เวลาขึ้นงาน"] = chained_start_dates
            active_jobs_editor_df["วัน-เวลาจบงาน"] = chained_finish_dates
            active_jobs_editor_df["รวม (ชม.)"] = ((active_jobs_editor_df["Setup (น.)"] + active_jobs_editor_df["Basic (น.)"] + active_jobs_editor_df["โปรแกรม (น.)"]) / 60.0).round(2)
            active_jobs_editor_df["ลบ"] = st.session_state.active_select_all

            with st.expander("📝 รายการสั่งผลิตในระบบ (ตารางสั่งการผลิต - ลิงก์เวลาลูกโซ่อัตโนมัติ)", expanded=True):
                if is_admin:
                    tool_col1, tool_col2 = st.columns([2.5, 7.5])
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
                        st.caption("🔗 **ระบบลูกโซ่ทำงานอยู่:** คิวที่ 1 เป็นตัวตั้ง คิวถัดไปจะรับเวลาจบมาเป็นเวลาเริ่มให้อัตโนมัติ โดยมีเวลา Baseline ไว้สอบกลับ")

                st.markdown("**🔎 ค้นหาด่วนด้วยปุ่ม:**")
                active_quick_filter = st.session_state.get("active_jobs_quick_filter", "ALL")
                active_filter_buttons = [
                    ("ALL", "🌐 ทั้งหมด"), ("RUNNING", "🟦 กำลังผลิต"),
                    ("WAITING", "🟧 รอคิว"), ("HOLD", "🟨 พักงาน"),
                    ("URGENT", "🔥 งานด่วน"), ("LATE", "🚨 หลุดแผน")
                ]
                for btn_col, (filter_key, filter_label) in zip(st.columns(6), active_filter_buttons):
                    with btn_col:
                        if st.button(
                            filter_label,
                            key=f"btn_active_quick_{filter_key}",
                            type="primary" if active_quick_filter == filter_key else "secondary",
                            use_container_width=True
                        ):
                            st.session_state.active_jobs_quick_filter = filter_key
                            # การคลิกปุ่มทำให้ Streamlit rerun อยู่แล้ว จึงต้องทำงานต่อจน render
                            # selectbox ครบ มิฉะนั้น widget state ของเครื่อง/แผนงานจะถูกล้าง
                            active_quick_filter = filter_key

                active_machine_options = ["🌐 ทุกเครื่อง"] + sorted(active_jobs_editor_df["เลือกเครื่องจักร"].dropna().astype(str).unique().tolist())
                active_plan_options = ["🌐 ทุกแผนงาน"] + sorted(active_jobs_editor_df["แผนงาน"].dropna().astype(str).unique().tolist())
                active_drawing_options = ["🌐 ทุก Drawing"] + sorted(active_jobs_editor_df["ชื่อ Drawing."].dropna().astype(str).unique().tolist())
                active_material_options = ["🌐 ทุกวัสดุ"] + sorted(active_jobs_editor_df["วัสดุ"].dropna().astype(str).unique().tolist())

                a_sel1, a_sel2, a_sel3, a_sel4 = st.columns([1.2, 1, 1.5, 0.9])
                with a_sel1:
                    selected_active_machine = st.selectbox("🏭 เครื่องจักร:", active_machine_options, key="active_jobs_machine_select")
                with a_sel2:
                    selected_active_plan = st.selectbox("📌 แผนงาน:", active_plan_options, key="active_jobs_plan_select")
                with a_sel3:
                    selected_active_drawing = st.selectbox("📄 Drawing:", active_drawing_options, key="active_jobs_drawing_select")
                with a_sel4:
                    selected_active_material = st.selectbox("🔩 วัสดุ:", active_material_options, key="active_jobs_material_select")

                # อ่านค่าจริงจาก widget state ทุกครั้ง ป้องกันตัวแปรเดิมค้างหลังผู้ใช้เปลี่ยนตัวเลือก
                selected_active_machine = st.session_state.get("active_jobs_machine_select", "🌐 ทุกเครื่อง")
                selected_active_plan = st.session_state.get("active_jobs_plan_select", "🌐 ทุกแผนงาน")
                selected_active_drawing = st.session_state.get("active_jobs_drawing_select", "🌐 ทุก Drawing")
                selected_active_material = st.session_state.get("active_jobs_material_select", "🌐 ทุกวัสดุ")

                display_editor_df = active_jobs_editor_df.copy()
                active_status_text = display_editor_df["สถานะงาน"].astype(str)
                if active_quick_filter == "RUNNING":
                    display_editor_df = display_editor_df[active_status_text.str.contains("กำลังผลิต")]
                elif active_quick_filter == "WAITING":
                    display_editor_df = display_editor_df[active_status_text.str.contains("รอคิว")]
                elif active_quick_filter == "HOLD":
                    display_editor_df = display_editor_df[active_status_text.str.contains("พักงาน|รอวัสดุ", regex=True)]
                elif active_quick_filter == "URGENT":
                    display_editor_df = display_editor_df[display_editor_df["ประเภทงาน"].astype(str).str.contains("ด่วน")]
                elif active_quick_filter == "LATE":
                    late_now = get_bangkok_now().replace(tzinfo=None)
                    display_editor_df = display_editor_df[
                        display_editor_df["วัน-เวลาจบงาน"].apply(
                            lambda value: (lambda dt: dt is not None and dt < late_now)(parse_flexible_datetime(value))
                        )
                    ]

                if normalize_filter_key(selected_active_machine) != normalize_filter_key("🌐 ทุกเครื่อง"):
                    display_editor_df = display_editor_df[
                        display_editor_df["เลือกเครื่องจักร"].map(normalize_filter_key) == normalize_filter_key(selected_active_machine)
                    ]
                if normalize_filter_key(selected_active_plan) != normalize_filter_key("🌐 ทุกแผนงาน"):
                    display_editor_df = display_editor_df[
                        display_editor_df["แผนงาน"].map(normalize_filter_key) == normalize_filter_key(selected_active_plan)
                    ]
                if normalize_filter_key(selected_active_drawing) != normalize_filter_key("🌐 ทุก Drawing"):
                    display_editor_df = display_editor_df[
                        display_editor_df["ชื่อ Drawing."].map(normalize_filter_key) == normalize_filter_key(selected_active_drawing)
                    ]
                if normalize_filter_key(selected_active_material) != normalize_filter_key("🌐 ทุกวัสดุ"):
                    display_editor_df = display_editor_df[
                        display_editor_df["วัสดุ"].map(normalize_filter_key) == normalize_filter_key(selected_active_material)
                    ]

                display_editor_df = display_editor_df.reset_index(drop=True)
                st.caption(f"แสดงผล {len(display_editor_df):,} จากทั้งหมด {len(active_jobs_editor_df):,} รายการ")

                # เก็บลำดับ ID ของตารางที่แสดงจริงไว้ใช้จับคู่ edited_rows ในรอบ rerun ถัดไป
                st.session_state.editor_cnc_jobs_grid_main_row_ids = display_editor_df["ID"].tolist()

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
                            "แผนงาน": st.column_config.TextColumn("แผนงาน", width=75),
                            "ชื่อ Drawing.": st.column_config.TextColumn("Drawing", width=145),
                            "จำนวน": st.column_config.NumberColumn("จำนวน", width=55, min_value=1, max_value=10000, step=1, format="%d", default=1),
                            "วัสดุ": st.column_config.TextColumn("วัสดุ", width=60, default="SS400"),
                            "ประเภทงาน": st.column_config.SelectboxColumn("ประเภทงาน", width=105, options=JOB_TYPES, default="🟢 งานปกติ"),
                            "ขั้นตอน (Step)": st.column_config.TextColumn("ขั้นตอน", width=125, disabled=True, default="รอหน้าเครื่องระบุ"),
                            "เลือกเครื่องจักร": st.column_config.SelectboxColumn("เครื่องจักร", width=130, options=ASSIGN_OPTIONS, default="No.1 Awea"),
                            "วัน-เวลาขึ้นงาน": st.column_config.TextColumn(
                                "เริ่มขึ้นงาน (ลูกโซ่)", 
                                width=135,
                                help="แถวแรกตั้งต้น แถวถัดไปรับเวลาจบจากแถวบนมาต่อเนื่องอัตโนมัติ"
                            ),
                            "วัน-เวลาจบงาน": st.column_config.TextColumn(
                                "จบงานตามแผน (ลูกโซ่)",
                                width=135,
                                disabled=True,
                                help="เวลาจบคำนวณตามแผนและกะโรงงาน"
                            ),
                            "Setup (น.)": st.column_config.NumberColumn("Setup", width=65, min_value=0, max_value=720, step=5, format="%d", default=10),
                            "Basic (น.)": st.column_config.NumberColumn("Basic", width=65, min_value=0, max_value=6000, step=5, format="%d", default=0),
                            "โปรแกรม (น.)": st.column_config.NumberColumn("โปรแกรม", width=75, min_value=0, max_value=12000, step=10, format="%d", default=120),
                            "รวม (ชม.)": st.column_config.NumberColumn("รวม ชม.", width=70, format="%.2f", disabled=True),
                            "สถานะงาน": st.column_config.SelectboxColumn("สถานะ", width=115, options=JOB_STATUS, default="🟧 รอคิวผลิต"),
                            "ลบ": st.column_config.CheckboxColumn("🗑️", width=45, default=False),
                        },
                        hide_index=True,
                        width=1540,
                        row_height=30
                    )
                else:
                    edited_jobs = display_editor_df.copy()
                    st.dataframe(
                        display_editor_df[[c for c in display_editor_df.columns if c not in ["ID", "ลบ", "กำหนดพร้อมขึ้นงาน (Baseline)"]]],
                        column_config={
                            "แผนงาน": st.column_config.TextColumn("แผนงาน", width=85),
                            "ชื่อ Drawing.": st.column_config.TextColumn("ชื่อ Drawing.", width=180),
                            "จำนวน": st.column_config.NumberColumn("จำนวน", width=65, format="%d"),
                            "วัสดุ": st.column_config.TextColumn("วัสดุ", width=75),
                            "ประเภทงาน": st.column_config.TextColumn("ประเภทงาน", width=125),
                            "ขั้นตอน (Step)": st.column_config.TextColumn("ขั้นตอน (Step)", width=130),
                            "เลือกเครื่องจักร": st.column_config.TextColumn("เลือกเครื่องจักร", width=160),
                            "วัน-เวลาขึ้นงาน": st.column_config.TextColumn("เริ่มขึ้นงาน (ลูกโซ่)", width=155),
                            "วัน-เวลาจบงาน": st.column_config.TextColumn("จบงานตามแผน (ลูกโซ่)", width=155),
                            "Setup (น.)": st.column_config.NumberColumn("Setup (น.)", width=85, format="%d"),
                            "Basic (น.)": st.column_config.NumberColumn("Basic (น.)", width=85, format="%d"),
                            "โปรแกรม (น.)": st.column_config.NumberColumn("โปรแกรม (น.)", width=100, format="%d"),
                            "รวม (ชม.)": st.column_config.NumberColumn("รวม (ชม.)", width=85, format="%.2f"),
                            "สถานะงาน": st.column_config.TextColumn("สถานะงาน", width=145),
                        },
                        hide_index=True,
                        width=1540
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

                    # Auto-save เฉพาะคิวของเครื่องที่มีการแก้ไข และใช้ค่าหลังคำนวณลูกโซ่แล้ว
                    if autosave_requested and affected_machines:
                        rows_to_save = active_jobs_editor_df[
                            active_jobs_editor_df["เลือกเครื่องจักร"].astype(str).isin(affected_machines)
                        ].copy()
                        save_success = True
                        save_errors = []
                        parsed_ready_by_id = {}

                        # ตรวจทุกค่าก่อน ห้ามเริ่มส่งข้อมูลหากมีเวลาแถวใดว่าง/ผิดรูปแบบ
                        for _, row in rows_to_save.iterrows():
                            p_code = safe_str(row.get("แผนงาน"), "")
                            raw_ready = row.get("วัน-เวลาขึ้นงาน")
                            dt_parsed = parse_flexible_datetime(raw_ready)
                            if dt_parsed is None or pd.isna(dt_parsed):
                                save_success = False
                                save_errors.append(f"{p_code}: กรุณากำหนดเวลาเริ่มแถวแรก")
                            else:
                                row_id = row.get("ID")
                                if pd.notna(row_id) and str(row_id).strip() not in ["", "None", "nan"]:
                                    parsed_ready_by_id[int(float(row_id))] = dt_parsed

                        if save_success:
                            for _, row in rows_to_save.iterrows():
                                p_code = safe_str(row.get("แผนงาน"), "")
                                if not p_code:
                                    continue
                                raw_ready = row.get("วัน-เวลาขึ้นงาน")
                                dt_parsed = parse_flexible_datetime(raw_ready)
                                ready_str = dt_parsed.strftime("%Y-%m-%d %H:%M:%S")
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
                                    row_saved = insert_supabase_job(payload)
                                else:
                                    row_saved = update_supabase_job(int(float(row_id)), payload)
                                if not row_saved:
                                    save_success = False
                                    save_errors.append(f"{p_code}: Supabase ไม่รับข้อมูล")

                        # อ่านค่ากลับมายืนยันก่อนรีเฟรช ป้องกันตารางหายหลัง Auto-save
                        if save_success:
                            for row_id, expected_dt in parsed_ready_by_id.items():
                                if not verify_supabase_ready_at(row_id, expected_dt):
                                    save_success = False
                                    save_errors.append(f"ID {row_id}: ตรวจสอบเวลาใน Supabase ไม่ผ่าน")

                        if save_success:
                            st.cache_data.clear()
                            st.session_state.reset_cnc_editor_after_autosave = True
                            st.toast("บันทึกอัตโนมัติเรียบร้อย", icon="✅")
                            st.rerun()
                        else:
                            st.error("Auto-save ไม่สำเร็จ จึงยังไม่รีเฟรชตาราง: " + " | ".join(save_errors[:5]))
                    else:
                        st.caption("✅ Auto-save เปิดใช้งาน — แก้ไขข้อมูลแล้วระบบจะบันทึกให้อัตโนมัติ")

                    _, c_del_top, _ = st.columns([2.5, 3.5, 4])
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

            finished_jobs_df = df_db[df_db["สถานะงาน"].isin(["🟩 เสร็จสิ้นแล้ว", "✅ เสร็จสิ้นแล้ว"])].copy()
            active_jobs_count = len(edited_jobs[edited_jobs["สถานะงาน"].isin(["🟧 รอคิวผลิต", "🟦 กำลังผลิต", "🟨 พักงาน (รอวัสดุ)"])])
            total_plan_hrs = active_jobs_editor_df["รวม (ชม.)"].sum()

            kpi_html = f'''<div class="kpi-container"><div class="kpi-card kpi-green"><div class="kpi-title">✅ งานเสร็จสิ้น</div><div class="kpi-value">{len(finished_jobs_df)} <span style="font-size:15px; font-weight:600;">รายการ</span></div></div><div class="kpi-card kpi-blue"><div class="kpi-title">⚙️ งานในแผน</div><div class="kpi-value">{active_jobs_count} <span style="font-size:15px; font-weight:600;">รายการ</span></div></div><div class="kpi-card kpi-orange"><div class="kpi-title">⏱️ เวลาทำงานรวม</div><div class="kpi-value">{total_plan_hrs:.1f} <span style="font-size:15px; font-weight:600;">ชม.</span></div></div></div>'''
            st.markdown(kpi_html, unsafe_allow_html=True)

            st.divider()

            # =====================================================
            # 2. ใบจ่ายคิวงานหน้าเครื่อง (Work Order Sheet)
            # =====================================================
            st.subheader("📋 ใบจ่ายคิวงานหน้าเครื่อง (Work Order Sheet)")

            df_wo_direct = active_jobs_editor_df.copy()
            df_wo_direct["_dt_start"] = df_wo_direct["วัน-เวลาขึ้นงาน"].apply(parse_flexible_datetime)
            df_wo_direct["_dt_finish"] = df_wo_direct["วัน-เวลาจบงาน"].apply(parse_flexible_datetime)

            def get_wo_queue_order(r):
                st_val = str(r.get("สถานะงาน", r.get("สถานะ", "")))
                prio = 0 if "กำลังผลิต" in st_val else (1 if "พักงาน" in st_val else 2)
                dt_p = parse_flexible_datetime(r.get("วัน-เวลาขึ้นงาน"))
                return (prio, dt_p if dt_p is not None else pd.Timestamp.max, safe_int(r.get("ID")))

            df_wo_direct["_wo_order"] = df_wo_direct.apply(get_wo_queue_order, axis=1)
            df_wo_direct = df_wo_direct.sort_values(by=["เลือกเครื่องจักร", "_wo_order"]).drop(columns=["_wo_order"]).reset_index(drop=True)

            df_wo_direct["ลำดับคิว"] = df_wo_direct.groupby("เลือกเครื่องจักร").cumcount() + 1
            df_wo_direct["ลำดับคิว"] = df_wo_direct["ลำดับคิว"].apply(lambda q: f"คิวที่ {q}")

            df_wo_direct["เครื่องจักร / แผนก"] = df_wo_direct["เลือกเครื่องจักร"]
            df_wo_direct["สถานะ"] = df_wo_direct["สถานะงาน"]
            
            # ช่องนี้แสดงเวลา Baseline เดิมที่ล็อกไว้เพื่อสอบกลับ
            df_wo_direct["กำหนดพร้อมขึ้นงาน"] = df_wo_direct["กำหนดพร้อมขึ้นงาน (Baseline)"]
            
            # ช่องนี้แสดงเวลาลูกโซ่ที่ต่อเนื่องกันจริง
            df_wo_direct["เริ่มขึ้นงานตามแผน"] = df_wo_direct["วัน-เวลาขึ้นงาน"]
            df_wo_direct["จบงานตามแผน"] = df_wo_direct["วัน-เวลาจบงาน"]

            wo_finish_map = dict(zip(df_wo_direct["ID"].astype(str), df_wo_direct["_dt_finish"]))

            now_check = get_bangkok_now().replace(tzinfo=None)
            warn_count = 0
            late_count = 0
            for _, r in df_wo_direct.iterrows():
                if is_deadline_active_status(r.get("สถานะ", "")):
                    f_dt = wo_finish_map.get(str(r.get("ID")))
                    if pd.notna(f_dt):
                        diff_m = (f_dt - now_check).total_seconds() / 60.0
                        if diff_m < 0:
                            late_count += 1
                        elif 0 <= diff_m <= 60:
                            warn_count += 1

            st.markdown("**🔎 ค้นหาด่วนด้วยปุ่ม:**")
            selected_wo_filter = st.session_state.get("wo_color_filter", "ALL")
            wo_filter_buttons = [
                ("ALL", "🌐 ทั้งหมด"), ("RUNNING", "🟦 กำลังผลิต"),
                ("WAITING", "🟧 รอคิว"), ("HOLD", "🟨 พักงาน"),
                ("WARN", f"🟡 ใกล้เสร็จ {warn_count}"), ("LATE", f"🔴 เกินแผน {late_count}")
            ]
            for btn_col, (filter_key, filter_label) in zip(st.columns(6), wo_filter_buttons):
                with btn_col:
                    if st.button(
                        filter_label,
                        key=f"btn_wo_quick_{filter_key}",
                        type="primary" if selected_wo_filter == filter_key else "secondary",
                        use_container_width=True
                    ):
                        st.session_state.wo_color_filter = filter_key
                        # คงค่าตัวกรอง dropdown ไว้ และนำปุ่มสถานะมากรองร่วมกันในรอบนี้
                        selected_wo_filter = filter_key

            wo_machine_options = ["🌐 ทุกเครื่อง"] + sorted(df_wo_direct["เครื่องจักร / แผนก"].dropna().astype(str).unique().tolist())
            wo_plan_options = ["🌐 ทุกแผนงาน"] + sorted(df_wo_direct["แผนงาน"].dropna().astype(str).unique().tolist())
            wo_drawing_options = ["🌐 ทุก Drawing"] + sorted(df_wo_direct["ชื่อ Drawing."].dropna().astype(str).unique().tolist())
            wo_material_options = ["🌐 ทุกวัสดุ"] + sorted(df_wo_direct["วัสดุ"].dropna().astype(str).unique().tolist())

            wo_sel1, wo_sel2, wo_sel3, wo_sel4 = st.columns([1.2, 1, 1.5, 0.9])
            with wo_sel1:
                selected_wo_machine = st.selectbox("🏭 เครื่องจักร:", wo_machine_options, key="wo_machine_select")
            with wo_sel2:
                selected_wo_plan = st.selectbox("📌 แผนงาน:", wo_plan_options, key="wo_plan_select")
            with wo_sel3:
                selected_wo_drawing = st.selectbox("📄 Drawing:", wo_drawing_options, key="wo_drawing_select")
            with wo_sel4:
                selected_wo_material = st.selectbox("🔩 วัสดุ:", wo_material_options, key="wo_material_select")

            selected_wo_machine = st.session_state.get("wo_machine_select", "🌐 ทุกเครื่อง")
            selected_wo_plan = st.session_state.get("wo_plan_select", "🌐 ทุกแผนงาน")
            selected_wo_drawing = st.session_state.get("wo_drawing_select", "🌐 ทุก Drawing")
            selected_wo_material = st.session_state.get("wo_material_select", "🌐 ทุกวัสดุ")

            df_display = df_wo_direct.copy()
            wo_status_text = df_display["สถานะ"].astype(str)

            if selected_wo_filter == "RUNNING":
                df_display = df_display[wo_status_text.str.contains("กำลังผลิต")]
            elif selected_wo_filter == "WAITING":
                df_display = df_display[wo_status_text.str.contains("รอคิว")]
            elif selected_wo_filter == "HOLD":
                df_display = df_display[wo_status_text.str.contains("พักงาน|รอวัสดุ", regex=True)]
            elif selected_wo_filter == "WARN":
                def is_warn_row(r):
                    if not is_deadline_active_status(r.get("สถานะ", "")): return False
                    f_dt = wo_finish_map.get(str(r.get("ID")))
                    if pd.notna(f_dt):
                        diff_m = (f_dt - now_check).total_seconds() / 60.0
                        return 0 <= diff_m <= 60
                    return False
                df_display = df_display[df_display.apply(is_warn_row, axis=1)]

            elif selected_wo_filter == "LATE":
                def is_late_row(r):
                    if not is_deadline_active_status(r.get("สถานะ", "")): return False
                    f_dt = wo_finish_map.get(str(r.get("ID")))
                    if pd.notna(f_dt):
                        diff_m = (f_dt - now_check).total_seconds() / 60.0
                        return diff_m < 0
                    return False
                df_display = df_display[df_display.apply(is_late_row, axis=1)]

            if normalize_filter_key(selected_wo_machine) != normalize_filter_key("🌐 ทุกเครื่อง"):
                df_display = df_display[
                    df_display["เครื่องจักร / แผนก"].map(normalize_filter_key) == normalize_filter_key(selected_wo_machine)
                ]
            if normalize_filter_key(selected_wo_plan) != normalize_filter_key("🌐 ทุกแผนงาน"):
                df_display = df_display[
                    df_display["แผนงาน"].map(normalize_filter_key) == normalize_filter_key(selected_wo_plan)
                ]
            if normalize_filter_key(selected_wo_drawing) != normalize_filter_key("🌐 ทุก Drawing"):
                df_display = df_display[
                    df_display["ชื่อ Drawing."].map(normalize_filter_key) == normalize_filter_key(selected_wo_drawing)
                ]
            if normalize_filter_key(selected_wo_material) != normalize_filter_key("🌐 ทุกวัสดุ"):
                df_display = df_display[
                    df_display["วัสดุ"].map(normalize_filter_key) == normalize_filter_key(selected_wo_material)
                ]

            st.caption(f"แสดงผล {len(df_display):,} จากทั้งหมด {len(df_wo_direct):,} รายการ")

            display_cols = [c for c in df_display.columns if c not in ["_dt_start", "_dt_finish", "_sort_key", "กำหนดพร้อมขึ้นงาน (Baseline)"]]

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
                    "เครื่องจักร / แผนก": st.column_config.TextColumn("เครื่องจักร", width=115),
                    "ลำดับคิว": st.column_config.TextColumn("คิว", width=60),
                    "สถานะ": st.column_config.TextColumn("สถานะ", width=105),
                    "ประเภทงาน": st.column_config.TextColumn("ประเภท", width=90),
                    "แผนงาน": st.column_config.TextColumn("แผนงาน", width=75),
                    "ชื่อ Drawing.": st.column_config.TextColumn("Drawing", width=145),
                    "จำนวน": st.column_config.NumberColumn("จำนวน", width=55, format="%d"),
                    "วัสดุ": st.column_config.TextColumn("วัสดุ", width=60),
                    "ขั้นตอน (Step)": st.column_config.TextColumn("ขั้นตอน", width=125),
                    "กำหนดพร้อมขึ้นงาน": st.column_config.TextColumn("Baseline", width=130),
                    "เริ่มขึ้นงานตามแผน": st.column_config.TextColumn("เริ่มแผน", width=130),
                    "จบงานตามแผน": st.column_config.TextColumn("จบแผน", width=130),
                    "Setup (น.)": st.column_config.NumberColumn("Setup", width=65, format="%d"),
                    "Basic (น.)": st.column_config.NumberColumn("Basic", width=65, format="%d"),
                    "โปรแกรม (น.)": st.column_config.NumberColumn("โปรแกรม", width=75, format="%d"),
                    "รวม (ชม.)": st.column_config.NumberColumn("รวม ชม.", width=70, format="%.2f"),
                },
                width=1500,
                hide_index=True,
                row_height=30
            )

            st.divider()

            # =====================================================
            # 3. ผังเวลาขึ้นงาน (Gantt Chart Timeline)
            # =====================================================
            today_date = get_bangkok_now().date()
            today_dt = get_bangkok_now().replace(tzinfo=None)
            util_period_start = datetime.combine(today_date, dtime(0, 0))
            util_period_end = datetime.combine(today_date, dtime(23, 59, 59))

            gantt_records = []
            valid_start_dates = []
            valid_end_dates = []

            for _, r_g in active_jobs_editor_df.iterrows():
                st_raw = r_g.get("วัน-เวลาขึ้นงาน")
                fn_raw = r_g.get("วัน-เวลาจบงาน")
                
                st_dt = parse_flexible_datetime(st_raw)
                fn_dt = parse_flexible_datetime(fn_raw)

                # ไม่มีเวลาเริ่มจริงให้ข้าม ห้ามสร้างแท่งงานโดยใช้เวลาปัจจุบัน
                if st_dt is None or pd.isna(st_dt):
                    continue
                if fn_dt is None or pd.isna(fn_dt) or fn_dt <= st_dt:
                    tot_mins = (
                        safe_float(r_g.get("Setup (น.)"), 10.0)
                        + safe_float(r_g.get("Basic (น.)"), 0.0)
                        + safe_float(r_g.get("โปรแกรม (น.)"), 120.0)
                    )
                    _, fn_dt = add_work_time_with_shift(st_dt, max(tot_mins, 0.0) / 60.0)

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
                    "เวลาเริ่ม": st_dt,
                    "เวลาเสร็จ": fn_dt,
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

                if isinstance(selected_date_range, (list, tuple)) and len(selected_date_range) == 2:
                    util_period_start = datetime.combine(selected_date_range[0], dtime(0, 0))
                    util_period_end = datetime.combine(selected_date_range[1], dtime(23, 59, 59))
                elif isinstance(selected_date_range, (datetime, pd.Timestamp)):
                    one_date = selected_date_range.date()
                    util_period_start = datetime.combine(one_date, dtime(0, 0))
                    util_period_end = datetime.combine(one_date, dtime(23, 59, 59))
                else:
                    util_period_start = datetime.combine(gantt_min_date, dtime(0, 0))
                    util_period_end = datetime.combine(gantt_max_date, dtime(23, 59, 59))

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

            # ใช้ช่วงวันที่เดียวกับ Gantt และนับเฉพาะเวลาทำงานจริงในกะ
            m_busy_map = {m: 0.0 for m in MACHINE_LIST}
            for _, r_u in active_jobs_editor_df.iterrows():
                m_name = str(r_u.get("เลือกเครื่องจักร", ""))
                start_dt_u = parse_flexible_datetime(r_u.get("วัน-เวลาขึ้นงาน"))
                total_minutes_u = (
                    safe_float(r_u.get("Setup (น.)"), 10.0)
                    + safe_float(r_u.get("Basic (น.)"), 0.0)
                    + safe_float(r_u.get("โปรแกรม (น.)"), 120.0)
                )
                if m_name in m_busy_map and start_dt_u is not None and pd.notna(start_dt_u):
                    m_busy_map[m_name] += get_planned_busy_hours_in_range(
                        start_dt_u,
                        total_minutes_u / 60.0,
                        util_period_start,
                        util_period_end
                    )

            total_horizon_work_hrs = get_work_capacity_between(util_period_start, util_period_end)
            util_period_txt = f"{util_period_start.strftime('%d/%m/%Y')} – {util_period_end.strftime('%d/%m/%Y')}"
            st.caption(
                f"ช่วงคำนวณเดียวกับ Gantt: {util_period_txt} | "
                f"เวลาที่เครื่องพร้อมทำงานตามกะ: {total_horizon_work_hrs:.2f} ชม./เครื่อง "
                "(หักเบรก พักเที่ยง และวันอาทิตย์แล้ว)"
            )

            util_list = []
            for m in MACHINE_LIST:
                busy = m_busy_map[m]
                # ไม่ตัดที่ 100% เพื่อให้เห็นข้อมูลคิวซ้อนหรือโหลดเกินกำลังจริง
                util_pct = (busy / total_horizon_work_hrs) * 100.0 if total_horizon_work_hrs > 0 else 0.0
                util_list.append({
                    "เครื่องจักร": m,
                    "ชั่วโมงทำงาน (ชม.)": round(busy, 2),
                    "อัตราการใช้งาน (%)": round(util_pct, 1),
                    "ข้อความแสดง": f"{util_pct:.1f}% ({busy:.2f} ชม.)"
                })
            df_util = pd.DataFrame(util_list)
            util_axis_max = max(105.0, float(df_util["อัตราการใช้งาน (%)"].max()) + 10.0)

            fig_bar = px.bar(
                df_util,
                x="อัตราการใช้งาน (%)",
                y="เครื่องจักร",
                orientation="h",
                color="อัตราการใช้งาน (%)",
                color_continuous_scale=[[0, "#E0F2FE"], [0.4, "#38BDF8"], [0.8, "#0284C7"], [1, "#0369A1"]],
                text="ข้อความแสดง",
                range_x=[0, util_axis_max],
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
                pause_hrs_list = []
                plan_finish_list = []
                start_variance_list = []
                finish_variance_list = []
                plan_result_list = []
                for _, r in fin_display_df.iterrows():
                    st_p = parse_flexible_datetime(r.get("เริ่มจริง"))
                    fn_p = parse_flexible_datetime(r.get("เสร็จจริง"))
                    plan_st = parse_flexible_datetime(r.get("วัน-เวลาขึ้นงาน"))
                    pause_seconds = max(0.0, safe_float(r.get("เวลาพักสะสม (วินาที)"), 0.0))
                    plan_minutes = (
                        safe_float(r.get("Setup (น.)"), 10.0)
                        + safe_float(r.get("Basic (น.)"), 0.0)
                        + safe_float(r.get("โปรแกรม (น.)"), 120.0)
                    )
                    plan_fn = None
                    if plan_st is not None:
                        _, plan_fn = add_work_time_with_shift(plan_st, plan_minutes / 60.0)

                    if st_p and fn_p:
                        net_seconds = max(0.0, (fn_p - st_p).total_seconds() - pause_seconds)
                        act_hrs_list.append(round(net_seconds / 3600.0, 2))
                    else:
                        act_hrs_list.append(round(plan_minutes / 60.0, 2))

                    pause_hrs_list.append(round(pause_seconds / 3600.0, 2))
                    plan_finish_list.append(plan_fn)
                    start_diff = ((st_p - plan_st).total_seconds() / 60.0) if (st_p is not None and plan_st is not None) else None
                    finish_diff = ((fn_p - plan_fn).total_seconds() / 60.0) if (fn_p is not None and plan_fn is not None) else None
                    start_variance_list.append(round(start_diff, 1) if start_diff is not None else None)
                    finish_variance_list.append(round(finish_diff, 1) if finish_diff is not None else None)
                    if finish_diff is None:
                        plan_result_list.append("⚪ ข้อมูลเวลาไม่ครบ")
                    elif finish_diff > 0:
                        plan_result_list.append(f"🔴 จบช้า {finish_diff:.0f} นาที")
                    else:
                        plan_result_list.append(f"🟢 จบเร็ว/ตรงแผน {abs(finish_diff):.0f} นาที")

                fin_display_df["จบตามแผน"] = plan_finish_list
                fin_display_df["เริ่มคลาดเคลื่อน (น.)"] = start_variance_list
                fin_display_df["จบคลาดเคลื่อน (น.)"] = finish_variance_list
                fin_display_df["พักสะสม (ชม.)"] = pause_hrs_list
                fin_display_df["เวลาจริงสุทธิ (ชม.)"] = act_hrs_list
                fin_display_df["ผลเทียบแผน"] = plan_result_list
                fin_display_df["ลบประวัติ"] = st.session_state.finish_select_all

                st.markdown("**🔎 ค้นหาด่วนด้วยปุ่ม:**")
                quick_filter = st.session_state.get("finished_history_quick_filter", "ALL")
                q_cols = st.columns(6)
                quick_buttons = [
                    ("ALL", "🌐 ทั้งหมด"),
                    ("TODAY", "📅 วันนี้"),
                    ("7D", "🗓️ 7 วัน"),
                    ("LATE", "🔴 จบช้า"),
                    ("ONTIME", "🟢 ตรง/เร็ว"),
                    ("PAUSED", "⏸️ มีพัก"),
                ]
                for q_col, (filter_key, filter_label) in zip(q_cols, quick_buttons):
                    with q_col:
                        if st.button(
                            filter_label,
                            key=f"btn_finished_quick_{filter_key}",
                            type="primary" if quick_filter == filter_key else "secondary",
                            use_container_width=True
                        ):
                            st.session_state.finished_history_quick_filter = filter_key
                            quick_filter = filter_key

                machine_options = ["🌐 ทุกเครื่อง"] + sorted(fin_display_df["เลือกเครื่องจักร"].dropna().astype(str).unique().tolist())
                plan_options = ["🌐 ทุกแผนงาน"] + sorted(fin_display_df["แผนงาน"].dropna().astype(str).unique().tolist())
                drawing_options = ["🌐 ทุก Drawing"] + sorted(fin_display_df["ชื่อ Drawing."].dropna().astype(str).unique().tolist())

                sel_c1, sel_c2, sel_c3 = st.columns([1.2, 1, 1.5])
                with sel_c1:
                    selected_fin_machine = st.selectbox("🏭 เลือกเครื่องจักร:", machine_options, key="finished_history_machine_select")
                with sel_c2:
                    selected_fin_plan = st.selectbox("📌 เลือกแผนงาน:", plan_options, key="finished_history_plan_select")
                with sel_c3:
                    selected_fin_drawing = st.selectbox("📄 เลือก Drawing:", drawing_options, key="finished_history_drawing_select")

                selected_fin_machine = st.session_state.get("finished_history_machine_select", "🌐 ทุกเครื่อง")
                selected_fin_plan = st.session_state.get("finished_history_plan_select", "🌐 ทุกแผนงาน")
                selected_fin_drawing = st.session_state.get("finished_history_drawing_select", "🌐 ทุก Drawing")

                total_finished_before_filter = len(fin_display_df)
                finish_dates = fin_display_df["เสร็จจริง"].apply(parse_flexible_datetime)
                today_finished = get_bangkok_now().date()

                if quick_filter == "TODAY":
                    fin_display_df = fin_display_df[finish_dates.apply(lambda x: x is not None and x.date() == today_finished)]
                elif quick_filter == "7D":
                    start_7d = today_finished - timedelta(days=6)
                    fin_display_df = fin_display_df[finish_dates.apply(lambda x: x is not None and start_7d <= x.date() <= today_finished)]
                elif quick_filter == "LATE":
                    fin_display_df = fin_display_df[pd.to_numeric(fin_display_df["จบคลาดเคลื่อน (น.)"], errors="coerce") > 0]
                elif quick_filter == "ONTIME":
                    finish_diff_series = pd.to_numeric(fin_display_df["จบคลาดเคลื่อน (น.)"], errors="coerce")
                    fin_display_df = fin_display_df[finish_diff_series.notna() & (finish_diff_series <= 0)]
                elif quick_filter == "PAUSED":
                    fin_display_df = fin_display_df[pd.to_numeric(fin_display_df["พักสะสม (ชม.)"], errors="coerce") > 0]

                if normalize_filter_key(selected_fin_machine) != normalize_filter_key("🌐 ทุกเครื่อง"):
                    fin_display_df = fin_display_df[
                        fin_display_df["เลือกเครื่องจักร"].map(normalize_filter_key) == normalize_filter_key(selected_fin_machine)
                    ]
                if normalize_filter_key(selected_fin_plan) != normalize_filter_key("🌐 ทุกแผนงาน"):
                    fin_display_df = fin_display_df[
                        fin_display_df["แผนงาน"].map(normalize_filter_key) == normalize_filter_key(selected_fin_plan)
                    ]
                if normalize_filter_key(selected_fin_drawing) != normalize_filter_key("🌐 ทุก Drawing"):
                    fin_display_df = fin_display_df[
                        fin_display_df["ชื่อ Drawing."].map(normalize_filter_key) == normalize_filter_key(selected_fin_drawing)
                    ]

                st.caption(f"แสดงผล {len(fin_display_df):,} จากทั้งหมด {total_finished_before_filter:,} รายการ")

                if is_admin:
                    fb_c1, fb_c2, _ = st.columns([1.5, 1.5, 4])
                    with fb_c1:
                        if st.button("✅ เลือกหมด (เสร็จ)", key="btn_sel_all_fin", use_container_width=True):
                            st.session_state.finish_select_all = True
                            st.rerun()
                    with fb_c2:
                        if st.button("❌ ยกเลิก (เสร็จ)", key="btn_unsel_all_fin", use_container_width=True):
                            st.session_state.finish_select_all = False
                            st.rerun()

                if is_admin:
                    edited_fin = st.data_editor(
                        fin_display_df,
                        key="editor_finished_jobs_history",
                        column_order=[
                            "แผนงาน", "ชื่อ Drawing.", "จำนวน", "วัสดุ", "ขั้นตอน (Step)",
                            "เลือกเครื่องจักร", "วัน-เวลาขึ้นงาน", "จบตามแผน", "เริ่มจริง", "เสร็จจริง",
                            "เริ่มคลาดเคลื่อน (น.)", "จบคลาดเคลื่อน (น.)", "พักสะสม (ชม.)",
                            "Setup (น.)", "Basic (น.)", "โปรแกรม (น.)", "รวม (ชม.)", "เวลาจริงสุทธิ (ชม.)", "ผลเทียบแผน", "สถานะงาน", "ลบประวัติ"
                        ],
                        column_config={
                            "ID": None,
                            "แผนงาน": st.column_config.TextColumn("แผนงาน", width=75, disabled=True),
                            "ชื่อ Drawing.": st.column_config.TextColumn("Drawing", width=180, disabled=True),
                            "จำนวน": st.column_config.NumberColumn("จำนวน", width=55, format="%d", disabled=True),
                            "วัสดุ": st.column_config.TextColumn("วัสดุ", width=60, disabled=True),
                            "ขั้นตอน (Step)": st.column_config.TextColumn("ขั้นตอน", width=240, disabled=True),
                            "เลือกเครื่องจักร": st.column_config.TextColumn("เครื่องจักร", width=140, disabled=True),
                            "วัน-เวลาขึ้นงาน": st.column_config.DatetimeColumn("เริ่มแผน", width=130, format="DD/MM/YYYY HH:mm", disabled=True),
                            "จบตามแผน": st.column_config.DatetimeColumn("จบแผน", width=130, format="DD/MM/YYYY HH:mm", disabled=True),
                            "เริ่มจริง": st.column_config.DatetimeColumn("เริ่มจริง", width=130, format="DD/MM/YYYY HH:mm", disabled=True),
                            "เสร็จจริง": st.column_config.DatetimeColumn("จบจริง", width=130, format="DD/MM/YYYY HH:mm", disabled=True),
                            "เริ่มคลาดเคลื่อน (น.)": st.column_config.NumberColumn("Start +/-", width=85, format="%.1f น.", disabled=True),
                            "จบคลาดเคลื่อน (น.)": st.column_config.NumberColumn("Finish +/-", width=85, format="%.1f น.", disabled=True),
                            "พักสะสม (ชม.)": st.column_config.NumberColumn("พัก", width=70, format="%.2f ชม.", disabled=True),
                            "Setup (น.)": st.column_config.NumberColumn("Setup", width=65, format="%d", disabled=True),
                            "Basic (น.)": st.column_config.NumberColumn("Basic", width=65, format="%d", disabled=True),
                            "โปรแกรม (น.)": st.column_config.NumberColumn("โปรแกรม", width=75, format="%d", disabled=True),
                            "รวม (ชม.)": st.column_config.NumberColumn("แผน", width=65, format="%.2f", disabled=True),
                            "เวลาจริงสุทธิ (ชม.)": st.column_config.NumberColumn("จริงสุทธิ", width=80, format="%.2f", disabled=True),
                            "ผลเทียบแผน": st.column_config.TextColumn("ผลเทียบแผน", width=145, disabled=True),
                            "สถานะงาน": st.column_config.TextColumn("สถานะ", width=100, disabled=True),
                            "ลบประวัติ": st.column_config.CheckboxColumn("🗑️", width=45, default=False),
                        },
                        hide_index=True,
                        width=2100,
                        height=420,
                        row_height=34
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
                            "ชื่อ Drawing.": st.column_config.TextColumn("ชื่อ Drawing.", width=190),
                            "จำนวน": st.column_config.NumberColumn("จำนวน", width=65, format="%d"),
                            "วัสดุ": st.column_config.TextColumn("วัสดุ", width=75),
                            "ขั้นตอน (Step)": st.column_config.TextColumn("ขั้นตอน (Step)", width=240),
                            "เลือกเครื่องจักร": st.column_config.TextColumn("เครื่องจักร", width=140),
                            "วัน-เวลาขึ้นงาน": st.column_config.DatetimeColumn("กำหนดขึ้นงาน (แผน)", width=145, format="DD/MM/YYYY HH:mm"),
                            "จบตามแผน": st.column_config.DatetimeColumn("จบตามแผน", width=145, format="DD/MM/YYYY HH:mm"),
                            "เริ่มจริง": st.column_config.DatetimeColumn("เริ่มขึ้นงานจริง", width=145, format="DD/MM/YYYY HH:mm"),
                            "เสร็จจริง": st.column_config.DatetimeColumn("เสร็จสิ้นจริง", width=145, format="DD/MM/YYYY HH:mm"),
                            "เริ่มคลาดเคลื่อน (น.)": st.column_config.NumberColumn("Start +/- (น.)", width=105, format="%.1f"),
                            "จบคลาดเคลื่อน (น.)": st.column_config.NumberColumn("Finish +/- (น.)", width=105, format="%.1f"),
                            "พักสะสม (ชม.)": st.column_config.NumberColumn("พักสะสม", width=85, format="%.2f ชม."),
                            "รวม (ชม.)": st.column_config.NumberColumn("แผน (ชม.)", width=85, format="%.2f"),
                            "เวลาจริงสุทธิ (ชม.)": st.column_config.NumberColumn("จริงสุทธิ (ชม.)", width=105, format="%.2f"),
                            "ผลเทียบแผน": st.column_config.TextColumn("ผลเทียบแผน", width=155),
                            "สถานะงาน": st.column_config.TextColumn("สถานะ", width=120),
                        },
                        hide_index=True,
                        width=2100,
                        row_height=34
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

            cost_col1, cost_col2 = st.columns([0.8, 3.2])

            with cost_col1:
                st.markdown("**⚙️ ตั้งค่าเรตราคาค่าเครื่องจักร (บาท/ชม.)**")
                if is_admin:
                    edited_rates = st.data_editor(
                        st.session_state.machine_rates,
                        key="editor_machine_rates_full_22_v14",
                        column_config={
                            "เครื่องจักร": st.column_config.TextColumn("เครื่องจักร", width=125, disabled=True),
                            "เรตราคา (บาท/ชม.)": st.column_config.NumberColumn("บาท/ชม.", width=80, min_value=0, max_value=50000, step=50, format="%d ฿", required=True)
                        },
                        width=330,
                        hide_index=True,
                        height=440,
                        row_height=28
                    )
                    st.session_state.machine_rates = edited_rates
                    rate_map = dict(zip(edited_rates["เครื่องจักร"], edited_rates["เรตราคา (บาท/ชม.)"]))
                else:
                    st.dataframe(
                        st.session_state.machine_rates,
                        column_config={
                            "เครื่องจักร": st.column_config.TextColumn("เครื่องจักร", width=125),
                            "เรตราคา (บาท/ชม.)": st.column_config.NumberColumn("บาท/ชม.", width=80, format="%d ฿")
                        },
                        width=330,
                        hide_index=True,
                        height=440,
                        row_height=28
                    )
                    rate_map = dict(zip(st.session_state.machine_rates["เครื่องจักร"], st.session_state.machine_rates["เรตราคา (บาท/ชม.)"]))

            with cost_col2:
                if not finished_jobs_df.empty:
                    cost_df = finished_jobs_df.copy()
                    for time_col, default_val in [("Setup (น.)", 10.0), ("Basic (น.)", 0.0), ("โปรแกรม (น.)", 0.0)]:
                        cost_df[time_col] = pd.to_numeric(cost_df[time_col], errors="coerce").fillna(default_val)
                    cost_df["เวลาแผน (ชม.)"] = ((cost_df["Setup (น.)"] + cost_df["Basic (น.)"] + cost_df["โปรแกรม (น.)"]) / 60.0).round(2)

                    actual_net_hours = []
                    time_sources = []
                    for _, cost_row in cost_df.iterrows():
                        actual_start = parse_flexible_datetime(cost_row.get("เริ่มจริง"))
                        actual_finish = parse_flexible_datetime(cost_row.get("เสร็จจริง"))
                        paused_seconds = max(0.0, safe_float(cost_row.get("เวลาพักสะสม (วินาที)"), 0.0))
                        if actual_start is not None and actual_finish is not None and actual_finish >= actual_start:
                            net_seconds = max(0.0, (actual_finish - actual_start).total_seconds() - paused_seconds)
                            actual_net_hours.append(round(net_seconds / 3600.0, 2))
                            time_sources.append("✅ เวลาจริง")
                        else:
                            # ข้อมูลเก่าที่ไม่มี Start/Finish ให้ใช้แผนชั่วคราวและติดป้ายเตือนชัดเจน
                            actual_net_hours.append(safe_float(cost_row.get("เวลาแผน (ชม.)"), 0.0))
                            time_sources.append("⚠️ ใช้เวลาแผน")

                    cost_df["เวลาจริงสุทธิ (ชม.)"] = actual_net_hours
                    cost_df["แหล่งเวลา"] = time_sources
                    cost_df["เรตราคา (บาท/ชม.)"] = pd.to_numeric(cost_df["เลือกเครื่องจักร"].map(rate_map), errors="coerce").fillna(500.0)
                    cost_df["ต้นทุนตามแผน (บาท)"] = (cost_df["เวลาแผน (ชม.)"] * cost_df["เรตราคา (บาท/ชม.)"]).round(2)
                    cost_df["ต้นทุนจริงสุทธิ (บาท)"] = (cost_df["เวลาจริงสุทธิ (ชม.)"] * cost_df["เรตราคา (บาท/ชม.)"]).round(2)
                    cost_df["ผลต่างต้นทุน (บาท)"] = (cost_df["ต้นทุนจริงสุทธิ (บาท)"] - cost_df["ต้นทุนตามแผน (บาท)"]).round(2)

                    total_plan_cost = cost_df["ต้นทุนตามแผน (บาท)"].sum()
                    total_actual_cost = cost_df["ต้นทุนจริงสุทธิ (บาท)"].sum()
                    total_actual_hrs = cost_df["เวลาจริงสุทธิ (ชม.)"].sum()

                    st.markdown(
                        f"**📊 งานเสร็จสิ้น — ต้นทุนจริงสุทธิ: :green[{total_actual_cost:,.2f} บาท] "
                        f"| เวลาเดินสุทธิ {total_actual_hrs:,.2f} ชม. | ต้นทุนตามแผน {total_plan_cost:,.2f} บาท**"
                    )

                    cost_display_df = cost_df.copy()
                    cost_quick_filter = st.session_state.get("cost_table_quick_filter", "ALL")
                    cost_missing_mask = cost_display_df["แหล่งเวลา"].astype(str).str.contains("⚠️", regex=False)
                    cost_valid_mask = ~cost_missing_mask
                    cost_over_count = int((cost_valid_mask & (cost_display_df["ผลต่างต้นทุน (บาท)"] > 0)).sum())
                    cost_saving_count = int((cost_valid_mask & (cost_display_df["ผลต่างต้นทุน (บาท)"] < 0)).sum())
                    cost_equal_count = int((cost_valid_mask & (cost_display_df["ผลต่างต้นทุน (บาท)"].abs() < 0.01)).sum())
                    cost_missing_count = int(cost_missing_mask.sum())

                    st.markdown("**🔎 ค้นหาด่วนด้วยปุ่ม:**")
                    cost_quick_buttons = [
                        ("ALL", f"🌐 ทั้งหมด ({len(cost_display_df)})"),
                        ("OVER", f"🔴 เกินแผน ({cost_over_count})"),
                        ("SAVING", f"🟢 ต่ำกว่าแผน ({cost_saving_count})"),
                        ("EQUAL", f"🟡 เท่าแผน ({cost_equal_count})"),
                        ("MISSING", f"⚠️ เวลาไม่ครบ ({cost_missing_count})"),
                    ]
                    for cost_btn_col, (cost_filter_key, cost_filter_label) in zip(st.columns(5), cost_quick_buttons):
                        with cost_btn_col:
                            if st.button(
                                cost_filter_label,
                                key=f"btn_cost_quick_{cost_filter_key}",
                                type="primary" if cost_quick_filter == cost_filter_key else "secondary",
                                use_container_width=True
                            ):
                                st.session_state.cost_table_quick_filter = cost_filter_key
                                cost_quick_filter = cost_filter_key

                    cost_machine_options = ["🌐 ทุกเครื่อง"] + sorted(cost_df["เลือกเครื่องจักร"].dropna().astype(str).unique().tolist())
                    cost_plan_options = ["🌐 ทุกแผนงาน"] + sorted(cost_df["แผนงาน"].dropna().astype(str).unique().tolist())
                    cost_drawing_options = ["🌐 ทุก Drawing"] + sorted(cost_df["ชื่อ Drawing."].dropna().astype(str).unique().tolist())
                    cf1, cf2, cf3, cf4 = st.columns([1.1, 1, 1.4, 1.7])
                    with cf1:
                        cost_machine_filter = st.selectbox("🏭 เครื่องจักร:", cost_machine_options, key="cost_machine_filter")
                    with cf2:
                        cost_plan_filter = st.selectbox("📌 แผนงาน:", cost_plan_options, key="cost_plan_filter")
                    with cf3:
                        cost_drawing_filter = st.selectbox("📄 Drawing:", cost_drawing_options, key="cost_drawing_filter")
                    with cf4:
                        cost_search = st.text_input(
                            "🔍 ค้นหา Drawing / Step / วัสดุ:",
                            placeholder="พิมพ์รหัสงาน, Drawing, ขั้นตอน, วัสดุ...",
                            key="cost_table_search"
                        )

                    if cost_quick_filter == "OVER":
                        cost_display_df = cost_display_df[
                            ~cost_display_df["แหล่งเวลา"].astype(str).str.contains("⚠️", regex=False)
                            & (cost_display_df["ผลต่างต้นทุน (บาท)"] > 0)
                        ]
                    elif cost_quick_filter == "SAVING":
                        cost_display_df = cost_display_df[
                            ~cost_display_df["แหล่งเวลา"].astype(str).str.contains("⚠️", regex=False)
                            & (cost_display_df["ผลต่างต้นทุน (บาท)"] < 0)
                        ]
                    elif cost_quick_filter == "EQUAL":
                        cost_display_df = cost_display_df[
                            ~cost_display_df["แหล่งเวลา"].astype(str).str.contains("⚠️", regex=False)
                            & (cost_display_df["ผลต่างต้นทุน (บาท)"].abs() < 0.01)
                        ]
                    elif cost_quick_filter == "MISSING":
                        cost_display_df = cost_display_df[cost_display_df["แหล่งเวลา"].astype(str).str.contains("⚠️", regex=False)]

                    if normalize_filter_key(cost_machine_filter) != normalize_filter_key("🌐 ทุกเครื่อง"):
                        cost_display_df = cost_display_df[
                            cost_display_df["เลือกเครื่องจักร"].map(normalize_filter_key) == normalize_filter_key(cost_machine_filter)
                        ]
                    if normalize_filter_key(cost_plan_filter) != normalize_filter_key("🌐 ทุกแผนงาน"):
                        cost_display_df = cost_display_df[
                            cost_display_df["แผนงาน"].map(normalize_filter_key) == normalize_filter_key(cost_plan_filter)
                        ]
                    if normalize_filter_key(cost_drawing_filter) != normalize_filter_key("🌐 ทุก Drawing"):
                        cost_display_df = cost_display_df[
                            cost_display_df["ชื่อ Drawing."].map(normalize_filter_key) == normalize_filter_key(cost_drawing_filter)
                        ]
                    if cost_search.strip():
                        cost_query = cost_search.strip().casefold()
                        cost_search_mask = pd.Series(False, index=cost_display_df.index)
                        for cost_search_col in ["แผนงาน", "ชื่อ Drawing.", "ขั้นตอน (Step)", "เลือกเครื่องจักร", "วัสดุ", "แหล่งเวลา"]:
                            cost_search_mask |= cost_display_df[cost_search_col].astype(str).str.casefold().str.contains(cost_query, regex=False, na=False)
                        cost_display_df = cost_display_df[cost_search_mask]

                    filtered_actual_cost = cost_display_df["ต้นทุนจริงสุทธิ (บาท)"].sum()
                    filtered_plan_cost = cost_display_df["ต้นทุนตามแผน (บาท)"].sum()
                    filtered_actual_hours = cost_display_df["เวลาจริงสุทธิ (ชม.)"].sum()
                    filtered_cost_diff = filtered_actual_cost - filtered_plan_cost
                    filtered_cost_diff_pct = (
                        (filtered_cost_diff / filtered_plan_cost) * 100.0
                        if filtered_plan_cost > 0 else None
                    )
                    if filtered_cost_diff_pct is None:
                        filtered_cost_pct_label = "ไม่มีฐานแผน"
                    elif filtered_cost_diff_pct > 0.005:
                        filtered_cost_pct_label = f"เกินแผน {abs(filtered_cost_diff_pct):,.2f}%"
                    elif filtered_cost_diff_pct < -0.005:
                        filtered_cost_pct_label = f"ต่ำกว่าแผน {abs(filtered_cost_diff_pct):,.2f}%"
                    else:
                        filtered_cost_pct_label = "เท่ากับแผน 0.00%"

                    cost_summary_cols = st.columns(4)
                    cost_summary_cols[0].metric(
                        "💰 ต้นทุนจริงสุทธิที่เลือก",
                        f"{filtered_actual_cost:,.2f} บาท"
                    )
                    cost_summary_cols[1].metric(
                        "📋 ต้นทุนตามแผนที่เลือก",
                        f"{filtered_plan_cost:,.2f} บาท"
                    )
                    cost_summary_cols[2].metric(
                        "📊 ผลต่างต้นทุน",
                        f"{filtered_cost_diff:+,.2f} บาท",
                        delta=(f"{filtered_cost_diff_pct:+,.2f}%" if filtered_cost_diff_pct is not None else "ไม่มีฐานแผน"),
                        delta_color="inverse"
                    )
                    cost_summary_cols[3].metric(
                        "⏱️ เวลาเดินจริงสุทธิที่เลือก",
                        f"{filtered_actual_hours:,.2f} ชม."
                    )
                    st.caption(
                        f"แสดงผล {len(cost_display_df):,} จากทั้งหมด {len(cost_df):,} รายการ | "
                        f"ต้นทุนจริงที่แสดง {filtered_actual_cost:,.2f} บาท | แผน {filtered_plan_cost:,.2f} บาท"
                    )
                    st.dataframe(
                        cost_display_df.sort_values(by="เสร็จจริง", ascending=False)[[
                            "แผนงาน", "ชื่อ Drawing.", "จำนวน", "ขั้นตอน (Step)", "เลือกเครื่องจักร",
                            "เวลาแผน (ชม.)", "เวลาจริงสุทธิ (ชม.)", "แหล่งเวลา", "เรตราคา (บาท/ชม.)",
                            "ต้นทุนตามแผน (บาท)", "ต้นทุนจริงสุทธิ (บาท)", "ผลต่างต้นทุน (บาท)"
                        ]],
                        column_config={
                            "แผนงาน": st.column_config.TextColumn("แผนงาน", width=70),
                            "ชื่อ Drawing.": st.column_config.TextColumn("Drawing", width=135),
                            "จำนวน": st.column_config.NumberColumn("จำนวน", width=50, format="%d"),
                            "ขั้นตอน (Step)": st.column_config.TextColumn("ขั้นตอน", width=170),
                            "เลือกเครื่องจักร": st.column_config.TextColumn("เครื่องจักร", width=110),
                            "เวลาแผน (ชม.)": st.column_config.NumberColumn("แผน ชม.", width=70, format="%.2f"),
                            "เวลาจริงสุทธิ (ชม.)": st.column_config.NumberColumn("จริงสุทธิ", width=75, format="%.2f"),
                            "แหล่งเวลา": st.column_config.TextColumn("ที่มาของเวลา", width=95),
                            "เรตราคา (บาท/ชม.)": st.column_config.NumberColumn("บาท/ชม.", width=75, format="%d ฿"),
                            "ต้นทุนตามแผน (บาท)": st.column_config.NumberColumn("ต้นทุนแผน", width=90, format="%.2f ฿"),
                            "ต้นทุนจริงสุทธิ (บาท)": st.column_config.NumberColumn("ต้นทุนจริง", width=90, format="%.2f ฿"),
                            "ผลต่างต้นทุน (บาท)": st.column_config.NumberColumn("ผลต่าง", width=85, format="%+.2f ฿"),
                        },
                        width=1380,
                        hide_index=True,
                        height=440,
                        row_height=28
                    )

                    cost_pdf_rows = "".join([
                        "<tr>"
                        f"<td>{html.escape(safe_str(r.get('แผนงาน'), '-'))}</td>"
                        f"<td>{html.escape(safe_str(r.get('ชื่อ Drawing.'), '-'))}</td>"
                        f"<td style='text-align:center'>{safe_int(r.get('จำนวน'), 1)}</td>"
                        f"<td>{html.escape(safe_str(r.get('ขั้นตอน (Step)'), '-'))}</td>"
                        f"<td>{html.escape(safe_str(r.get('เลือกเครื่องจักร'), '-'))}</td>"
                        f"<td style='text-align:right'>{safe_float(r.get('เวลาแผน (ชม.)')):,.2f}</td>"
                        f"<td style='text-align:right'>{safe_float(r.get('เวลาจริงสุทธิ (ชม.)')):,.2f}</td>"
                        f"<td style='text-align:right'>{safe_float(r.get('เรตราคา (บาท/ชม.)')):,.0f}</td>"
                        f"<td style='text-align:right'>{safe_float(r.get('ต้นทุนตามแผน (บาท)')):,.2f}</td>"
                        f"<td style='text-align:right'>{safe_float(r.get('ต้นทุนจริงสุทธิ (บาท)')):,.2f}</td>"
                        f"<td style='text-align:right'>{safe_float(r.get('ผลต่างต้นทุน (บาท)')):+,.2f}</td>"
                        "</tr>"
                        for _, r in cost_display_df.sort_values(by="เสร็จจริง", ascending=False).iterrows()
                    ])
                    cost_pdf_payload = json.dumps({
                        "print_date": get_bangkok_now().strftime("%d/%m/%Y %H:%M น."),
                        "machine": safe_str(cost_machine_filter, "ทุกเครื่อง"),
                        "plan": safe_str(cost_plan_filter, "ทุกแผนงาน"),
                        "drawing": safe_str(cost_drawing_filter, "ทุก Drawing"),
                        "search": safe_str(cost_search, "-"),
                        "rows_count": len(cost_display_df),
                        "actual_cost": f"{filtered_actual_cost:,.2f}",
                        "plan_cost": f"{filtered_plan_cost:,.2f}",
                        "cost_diff": f"{filtered_cost_diff:+,.2f}",
                        "cost_diff_pct": filtered_cost_pct_label,
                        "actual_hours": f"{filtered_actual_hours:,.2f}",
                        "rows": cost_pdf_rows,
                    }, ensure_ascii=False).replace("<", "\\u003c")

                    components.html(f"""
                    <button onclick="printCostReport()" style="width:100%; background:linear-gradient(135deg,#B91C1C,#EF4444); color:white; border:0; padding:10px 16px; border-radius:8px; font-weight:700; font-size:13px; cursor:pointer;">
                        📄 พิมพ์ / บันทึก PDF รายงานต้นทุนตามข้อมูลที่เลือก
                    </button>
                    <script>
                    function printCostReport() {{
                        const d = {cost_pdf_payload};
                        const reportHtml = `<!doctype html><html><head><meta charset="utf-8">
                        <title>PES Machining Cost Report</title>
                        <style>
                        @page {{ size:A4 landscape; margin:9mm; }}
                        body {{ font-family:Tahoma,'Sarabun',Arial,sans-serif; color:#172033; margin:0; font-size:9px; }}
                        .head {{ display:flex; justify-content:space-between; border-bottom:3px solid #B91C1C; padding-bottom:7px; margin-bottom:8px; }}
                        h1 {{ font-size:17px; margin:0; }} .sub {{ color:#64748B; margin-top:3px; }}
                        .filters {{ background:#F8FAFC; border:1px solid #CBD5E1; border-radius:6px; padding:6px 8px; margin-bottom:8px; }}
                        .kpis {{ display:grid; grid-template-columns:repeat(4,1fr); gap:6px; margin-bottom:9px; }}
                        .kpi {{ border:1px solid #CBD5E1; border-radius:6px; padding:7px; text-align:center; background:#FFF; }}
                        .kpi b {{ display:block; font-size:14px; margin-top:3px; }}
                        table {{ width:100%; border-collapse:collapse; table-layout:fixed; }}
                        th,td {{ border:1px solid #CBD5E1; padding:3px 4px; overflow-wrap:anywhere; }}
                        th {{ background:#E2E8F0; font-weight:700; }} tr:nth-child(even) {{ background:#F8FAFC; }}
                        thead {{ display:table-header-group; }} tr {{ break-inside:avoid; }}
                        .foot {{ margin-top:8px; color:#64748B; text-align:right; }}
                        </style></head><body>
                        <div class="head"><div><h1>ตารางคำนวณมูลค่าและต้นทุนค่าเครื่องจักร</h1><div class="sub">Machining Cost Calculation - งานเสร็จสิ้น / ต้นทุนจริงสุทธิ</div></div><div>วันที่ออกรายงาน: ${{d.print_date}}</div></div>
                        <div class="filters"><b>เงื่อนไข:</b> เครื่องจักร ${{d.machine}} | แผนงาน ${{d.plan}} | Drawing ${{d.drawing}} | ค้นหา ${{d.search}} | จำนวน ${{d.rows_count}} รายการ</div>
                        <div class="kpis">
                          <div class="kpi">ต้นทุนจริงสุทธิ<b>${{d.actual_cost}} บาท</b></div>
                          <div class="kpi">ต้นทุนตามแผน<b>${{d.plan_cost}} บาท</b></div>
                          <div class="kpi">ผลต่างต้นทุน<b>${{d.cost_diff}} บาท</b><span>${{d.cost_diff_pct}}</span></div>
                          <div class="kpi">เวลาเดินจริงสุทธิ<b>${{d.actual_hours}} ชม.</b></div>
                        </div>
                        <table><thead><tr><th>แผนงาน</th><th>Drawing</th><th style="width:4%">จำนวน</th><th style="width:15%">ขั้นตอน</th><th>เครื่องจักร</th><th>แผน ชม.</th><th>จริงสุทธิ</th><th>บาท/ชม.</th><th>ต้นทุนแผน</th><th>ต้นทุนจริง</th><th>ผลต่าง</th></tr></thead><tbody>${{d.rows}}</tbody></table>
                        <div class="foot">PES Production Monitoring System</div></body></html>`;
                        const w = window.open('', '_blank');
                        if (!w) {{ alert('กรุณาอนุญาต Pop-up เพื่อพิมพ์รายงาน PDF'); return; }}
                        w.document.open(); w.document.write(reportHtml); w.document.close(); w.focus();
                        setTimeout(function() {{ w.print(); }}, 600);
                    }}
                    </script>
                    """, height=50)
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
            finished_all["Target_Date"] = pd.to_datetime(
                finished_all["เสร็จจริง"].apply(parse_flexible_datetime), errors="coerce"
            )
            missing_finish_date_count = int(finished_all["Target_Date"].isna().sum())
            if missing_finish_date_count:
                st.warning(f"⚠️ งานที่ระบุว่าเสร็จแล้วแต่ไม่มีเวลา Finish จริง {missing_finish_date_count} รายการ จะไม่ถูกนำไปลงเดือนใดจนกว่าจะมีเวลา Finish")
            
            monthly_dw_jobs = finished_all[
                (finished_all["Target_Date"].dt.month == sel_dw_month) &
                (finished_all["Target_Date"].dt.year == sel_dw_year)
            ].copy()

            if not monthly_dw_jobs.empty:
                monthly_dw_jobs = build_performance_metrics(monthly_dw_jobs)
                monthly_dw_jobs["แผนงาน"] = monthly_dw_jobs["แผนงาน"].map(lambda v: safe_str(v, "ไม่ระบุแผนงาน"))
                monthly_dw_jobs["ชื่อ Drawing."] = monthly_dw_jobs["ชื่อ Drawing."].map(lambda v: safe_str(v, "ไม่ระบุ Drawing"))

                drawing_agg = []
                for (p_c, d_c), g_data in monthly_dw_jobs.groupby(["แผนงาน", "ชื่อ Drawing."], dropna=False):
                    d_plan = g_data["เวลาแผน (ชม.)"].sum()
                    d_act = g_data["เวลาจริง (ชม.)"].sum(min_count=len(g_data))
                    d_qty = max(1, safe_int(pd.to_numeric(g_data["จำนวน"], errors="coerce").max(), 1))
                    d_mat = safe_str(g_data.iloc[0].get("วัสดุ"), "ไม่ระบุ")
                    has_complete_actual = pd.notna(d_act)
                    d_diff = round(d_act - d_plan, 2) if has_complete_actual else float("nan")
                    d_diff_mins = round(d_diff * 60) if has_complete_actual else 0
                    
                    d_plan_per_pc = round(d_plan / d_qty, 2)
                    d_act_per_pc = round(d_act / d_qty, 2) if has_complete_actual else float("nan")
                    accuracy_pct = max(0.0, round(100.0 - abs(d_diff) / d_plan * 100.0, 1)) if has_complete_actual and d_plan > 0 else float("nan")

                    machines_used = g_data["เลือกเครื่องจักร"].dropna().unique()
                    machines_str = ", ".join([str(m) for m in machines_used if str(m).strip() != ""])
                    if not machines_str:
                        machines_str = "-"
                    
                    pct_diff = ((d_act - d_plan) / d_plan * 100) if has_complete_actual and d_plan > 0 else float("nan")
                    if not has_complete_actual:
                        cat_status = "MISSING"
                        eval_str = "⚠️ เวลา Start/Finish ไม่ครบ"
                    elif pct_diff < -5:
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
                count_missing = len(df_draw_full[df_draw_full["สถานะกลุ่ม"] == "MISSING"])
                total_late_hrs = df_draw_full[df_draw_full["ผลต่าง (ชม.)"] > 0]["ผลต่าง (ชม.)"].sum()
                avg_accuracy = df_draw_full["ความแม่นยำ (%)"].mean()

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
                    <div class="kpi-card kpi-blue">
                        <div class="kpi-title">🎯 ความแม่นยำเฉลี่ยของเวลาแผน</div>
                        <div class="kpi-value">{avg_accuracy if pd.notna(avg_accuracy) else 0:.1f} %</div>
                        <div class="kpi-sub">ข้อมูลเวลาไม่ครบ {count_missing} Drawings</div>
                    </div>
                </div>
                """, unsafe_allow_html=True)

                valid_drawings = df_draw_full.dropna(subset=["ผลต่าง (ชม.)"])
                if not valid_drawings.empty:
                    worst_drawing = valid_drawings.sort_values("ผลต่าง (ชม.)", ascending=False).iloc[0]
                    best_drawing = valid_drawings.sort_values("ผลต่าง (ชม.)", ascending=True).iloc[0]
                    i1, i2, i3 = st.columns(3)
                    i1.info(f"📌 วิเคราะห์แล้ว **{len(valid_drawings):,} Drawings** จากทั้งหมด {len(df_draw_full):,}")
                    if worst_drawing["ผลต่าง (ชม.)"] > 0:
                        i2.error(
                            f"🔴 ช้าสุด: **{worst_drawing['ชื่อ Drawing.']}** "
                            f"({worst_drawing['ผลต่าง (ชม.)']:+.2f} ชม.)"
                        )
                    else:
                        i2.success("🎉 ไม่มี Drawing ที่ใช้เวลาจริงเกินเวลาแผน")
                    i3.success(
                        f"🟢 เร็วสุด: **{best_drawing['ชื่อ Drawing.']}** "
                        f"({best_drawing['ผลต่าง (ชม.)']:+.2f} ชม.)"
                    )
                st.caption("ℹ️ เวลาจริงสุทธิ = Finish − Start − เวลาพักสะสม | ความแม่นยำ = 100 − %ความคลาดเคลื่อนจากเวลาแผน")

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
                        df_draw_filtered["ชื่อ Drawing."].astype(str).str.lower().str.contains(q_dw_s, regex=False, na=False) |
                        df_draw_filtered["เครื่องจักรที่ผลิต"].astype(str).str.lower().str.contains(q_dw_s, regex=False, na=False)
                    ]

                if "Top 10 ช้ากว่าแผน" in sel_dw_limit:
                    df_draw_filtered = df_draw_filtered.sort_values(by="ผลต่าง (ชม.)", ascending=False).head(10).sort_values(by="เวลาจริง (ชม.)", ascending=True)
                elif "Top 10 เร็วกว่าแผน" in sel_dw_limit:
                    df_draw_filtered = df_draw_filtered.sort_values(by="ผลต่าง (ชม.)", ascending=True).head(10).sort_values(by="เวลาจริง (ชม.)", ascending=True)
                else:
                    df_draw_filtered = df_draw_filtered.sort_values(by="เวลาจริง (ชม.)", ascending=True)

                chart_source = df_draw_filtered.dropna(subset=["เวลาจริง (ชม.)"])
                if not chart_source.empty:
                    chart_h = max(420, len(chart_source) * 36)
                    fig_dw = px.bar(
                        chart_source,
                        y="หัวข้อ Drawing",
                        x=["เวลาแผน (ชม.)", "เวลาจริง (ชม.)"],
                        orientation="h",
                        barmode="group",
                        title=f"⏱️ เปรียบเทียบเวลาแผน vs เวลาจริงสุทธิ ประจำเดือน {month_names[sel_dw_month-1]} {sel_dw_year} ({len(chart_source)} Drawings)",
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
                            df_table_display["แผนงาน"].astype(str).str.lower().str.contains(q_dt, regex=False, na=False) |
                            df_table_display["ชื่อ Drawing."].astype(str).str.lower().str.contains(q_dt, regex=False, na=False) |
                            df_table_display["วัสดุ"].astype(str).str.lower().str.contains(q_dt, regex=False, na=False) |
                            df_table_display["เครื่องจักรที่ผลิต"].astype(str).str.lower().str.contains(q_dt, regex=False, na=False) |
                            df_table_display["การประเมิน"].astype(str).str.lower().str.contains(q_dt, regex=False, na=False)
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
                            "ความแม่นยำ (%)": st.column_config.ProgressColumn("ความแม่นยำ", width=100, min_value=0, max_value=100, format="%.1f%%"),
                            "ผลต่าง (ชม.)": st.column_config.NumberColumn("ผลต่าง (ชม.)", width=85, format="%.2f"),
                            "การประเมิน": st.column_config.TextColumn("ผลประเมิน", width=145),
                        },
                        hide_index=True,
                        width=1430
                    )

                    st.divider()

                    st.markdown("#### 🔬 เจาะลึกความต่างระดับขั้นตอนย่อย (Step Breakdown Inspector)")
                    drawing_options = list(df_draw_full.index)
                    selected_inspect_idx = st.selectbox(
                        "เลือก Drawing ที่ต้องการเจาะลึกดูรายขั้นตอน:",
                        drawing_options,
                        format_func=lambda idx: f"[{df_draw_full.loc[idx, 'แผนงาน']}] {df_draw_full.loc[idx, 'ชื่อ Drawing.']}"
                    )

                    if selected_inspect_idx is not None:
                        ins_plan = df_draw_full.loc[selected_inspect_idx, "แผนงาน"]
                        ins_dw = df_draw_full.loc[selected_inspect_idx, "ชื่อ Drawing."]
                        step_details = monthly_dw_jobs[(monthly_dw_jobs["แผนงาน"] == ins_plan) & (monthly_dw_jobs["ชื่อ Drawing."] == ins_dw)].copy()

                        if not step_details.empty:
                            step_diffs, step_evals = [], []
                            for _, sr in step_details.iterrows():
                                s_st, s_fn = sr.get("เริ่มจริง"), sr.get("เสร็จจริง")
                                act_st = parse_flexible_datetime(s_st)
                                act_fn = parse_flexible_datetime(s_fn)
                                if act_st is not None and act_fn is not None:
                                    d_sec = max(0.0, (act_fn - act_st).total_seconds() - safe_float(sr.get("เวลาพักสะสม (วินาที)"), 0.0))
                                    a_h = round(d_sec / 3600.0, 2)
                                    v_h = round(a_h - sr["เวลาแผน (ชม.)"], 2)
                                    step_diffs.append(v_h)
                                    d_mins = round(v_h * 60)
                                    plan_h = max(0.0, safe_float(sr.get("เวลาแผน (ชม.)"), 0.0))
                                    pct_v = (v_h / plan_h * 100.0) if plan_h > 0 else 0.0
                                    if pct_v < -5:
                                        step_evals.append(f"🟢 เร็วขึ้น {abs(d_mins)} นาที")
                                    elif pct_v <= 5:
                                        step_evals.append("🟡 ตรงตามแผน (±5%)")
                                    else:
                                        step_evals.append(f"🔴 ช้ากว่าแผน +{d_mins} นาที")
                                else:
                                    step_diffs.append(float("nan"))
                                    step_evals.append("⚠️ เวลา Start/Finish ไม่ครบ")
                            
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
                                width=1210
                            )
                else:
                    st.warning("⚠️ ไม่พบ Drawing ที่มีเวลา Start/Finish จริงครบตามเงื่อนไขที่เลือก")
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
            finished_all["Target_Date"] = pd.to_datetime(
                finished_all["เสร็จจริง"].apply(parse_flexible_datetime), errors="coerce"
            )
            undated_finished_count = int(finished_all["Target_Date"].isna().sum())
            
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
            monthly_jobs = build_performance_metrics(monthly_jobs)
            monthly_jobs["แผนงาน"] = monthly_jobs["แผนงาน"].map(lambda v: safe_str(v, "ไม่ระบุแผนงาน"))
            monthly_jobs["ชื่อ Drawing."] = monthly_jobs["ชื่อ Drawing."].map(lambda v: safe_str(v, "ไม่ระบุ Drawing"))
            monthly_jobs["เลือกเครื่องจักร"] = monthly_jobs["เลือกเครื่องจักร"].map(lambda v: safe_str(v, "ไม่ระบุเครื่อง"))
            monthly_jobs["วัสดุ"] = monthly_jobs["วัสดุ"].map(lambda v: safe_str(v, "ไม่ระบุ"))
            monthly_jobs["เรตราคา (บาท/ชม.)"] = monthly_jobs["เลือกเครื่องจักร"].map(rate_map).fillna(500)
            monthly_jobs["มูลค่ารวม (บาท)"] = (monthly_jobs["เวลาจริง (ชม.)"] * monthly_jobs["เรตราคา (บาท/ชม.)"]).round(2)
            monthly_jobs["ผลตามกำหนด"] = monthly_jobs["_schedule_on_time"].map(
                {True: "🟢 จบไม่เกินแผน", False: "🔴 จบเกินแผน"}
            ).fillna("⚠️ ไม่มีเวลาจบแผน")

            total_jobs_count = len(monthly_jobs)
            total_qty_pieces = unique_drawing_quantity(monthly_jobs)
            total_running_hrs = monthly_jobs["เวลาจริง (ชม.)"].sum()
            total_plan_hrs_m = monthly_jobs["เวลาแผน (ชม.)"].sum()
            total_variance_hrs = monthly_jobs["ผลต่าง (ชม.)"].sum()
            total_output_val = monthly_jobs["มูลค่ารวม (บาท)"].sum()
            valid_actual_count = int(monthly_jobs["เวลาจริง (ชม.)"].notna().sum())
            missing_actual_count = total_jobs_count - valid_actual_count
            valid_schedule = monthly_jobs["_schedule_on_time"].dropna()
            on_time_rate = float(valid_schedule.mean() * 100.0) if not valid_schedule.empty else float("nan")
            data_complete_rate = valid_actual_count / total_jobs_count * 100.0 if total_jobs_count else 0.0

            if undated_finished_count or missing_actual_count:
                st.warning(
                    f"⚠️ คุณภาพข้อมูล: งานเสร็จที่ไม่มี Finish จึงไม่ถูกจัดเข้าเดือน {undated_finished_count} รายการ | "
                    f"รายการในเดือนนี้ที่ Start/Finish ไม่ครบ {missing_actual_count} รายการ (ไม่นำไปคำนวณเวลาจริง; "
                    "ผลจบตามกำหนดยังคำนวณได้เฉพาะรายการที่มี Finish จริงและเวลาจบแผน)"
                )

            if not prev_monthly_jobs.empty:
                prev_monthly_jobs = build_performance_metrics(prev_monthly_jobs)
                prev_qty = unique_drawing_quantity(prev_monthly_jobs)
                prev_rates = prev_monthly_jobs["เลือกเครื่องจักร"].map(rate_map).fillna(500)
                prev_val = (prev_monthly_jobs["เวลาจริง (ชม.)"] * prev_rates).sum()
                
                growth_qty = ((total_qty_pieces - prev_qty) / prev_qty * 100) if prev_qty > 0 else 0.0
                growth_val = ((total_output_val - prev_val) / prev_val * 100) if prev_val > 0 else 0.0
                growth_qty_str = f"{'+' if growth_qty >= 0 else ''}{growth_qty:.1f}% เทียบเดือนก่อน"
                growth_val_str = f"{'+' if growth_val >= 0 else ''}{growth_val:.1f}% เทียบเดือนก่อน"
            else:
                growth_qty_str = "ไม่มีข้อมูลเดือนก่อนหน้า"
                growth_val_str = "ไม่มีข้อมูลเดือนก่อนหน้า"

            var_title_txt = f"⚡ ผลต่างสุทธิเร็วกว่าแผน {abs(total_variance_hrs):.1f} ชม." if total_variance_hrs <= 0 else f"⚠️ ผลต่างสุทธิช้ากว่าแผน +{total_variance_hrs:.1f} ชม."

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
                    <div class="kpi-title">💰 ต้นทุนเวลาเครื่องจักรจริง</div>
                    <div class="kpi-value">{total_output_val:,.2f} <span style="font-size:15px; font-weight:600;">฿</span></div>
                    <div class="kpi-sub">📈 {growth_val_str}</div>
                </div>
                <div class="kpi-card kpi-purple">
                    <div class="kpi-title">🎯 จบไม่เกินเวลาตามแผน</div>
                    <div class="kpi-value">{f'{on_time_rate:.1f} %' if pd.notna(on_time_rate) else 'ไม่มีข้อมูล'}</div>
                    <div class="kpi-sub">{var_title_txt} | ข้อมูลครบ {data_complete_rate:.0f}%</div>
                </div>
            </div>
            """, unsafe_allow_html=True)

            valid_month_rows = monthly_jobs.dropna(subset=["ผลต่าง (ชม.)"])
            if not valid_month_rows.empty:
                worst_month_row = valid_month_rows.sort_values("ผลต่าง (ชม.)", ascending=False).iloc[0]
                delayed_month_rows = valid_month_rows[valid_month_rows["ผลต่าง (ชม.)"] > 0]
                machine_delay = delayed_month_rows.groupby("เลือกเครื่องจักร", dropna=False)["ผลต่าง (ชม.)"].sum().sort_values(ascending=False)
                bottleneck_machine = safe_str(machine_delay.index[0], "ไม่ระบุเครื่อง") if not machine_delay.empty else "ไม่มี"
                bottleneck_text = f"{machine_delay.iloc[0]:+.2f} ชม." if not machine_delay.empty else "ไม่พบงานช้ากว่าแผน"
                insight_c1, insight_c2, insight_c3 = st.columns(3)
                insight_c1.info(f"📋 งานเสร็จ **{total_jobs_count:,} Steps** / **{total_qty_pieces:,} ชิ้นไม่ซ้ำ Step**")
                insight_c2.warning(f"🏭 เครื่องที่มีเวลาช้าสะสมสูงสุด: **{bottleneck_machine}** ({bottleneck_text})")
                if worst_month_row["ผลต่าง (ชม.)"] > 0:
                    insight_c3.error(f"🔎 Step ช้าสุด: **{safe_str(worst_month_row.get('ชื่อ Drawing.'), '-')}** ({worst_month_row['ผลต่าง (ชม.)']:+.2f} ชม.)")
                else:
                    insight_c3.success("🎉 ไม่มี Step ที่ใช้เวลาจริงเกินเวลาแผน")
            st.caption("ℹ️ จำนวนชิ้นนับเพียงครั้งเดียวต่อแผนงาน+Drawing ส่วนจำนวนคิวหมายถึงจำนวน Step ที่ผลิตเสร็จ")

            machine_summary = []
            for m, m_sub in monthly_jobs.groupby("เลือกเครื่องจักร", dropna=False):
                if not m_sub.empty:
                    m_qty = unique_drawing_quantity(m_sub, ["เลือกเครื่องจักร"])
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
                mat_qty = unique_drawing_quantity(mat_sub, ["วัสดุ"])
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
                title="💰 อันดับต้นทุนเวลาเครื่องจักรตามชั่วโมงเดินจริง (บาท)",
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

            def report_escape(value):
                return html.escape(safe_str(value, "-"))

            def report_number(value, digits=2, suffix=""):
                """จัดรูปตัวเลขในรายงาน HTML และคืน '-' เมื่อเป็นค่าว่าง/NaN"""
                if value is None or pd.isna(value):
                    return "-"
                return f"{safe_float(value):,.{digits}f}{suffix}"

            rows_m_html = "".join([f"<tr><td>{report_escape(r['เครื่องจักร / แผนก'])}</td><td style='text-align:center;'>{r['จำนวนคิวงาน']}</td><td style='text-align:center;'>{r['ชิ้นงานรวม (ชิ้น)']}</td><td style='text-align:center;'>{r['เวลาแผน (ชม.)']:.2f}</td><td style='text-align:center;'>{r['เวลาจริง (ชม.)']:.2f}</td><td style='text-align:center;'>{report_escape(r['ผลต่าง'])}</td><td style='text-align:right;'>{r['มูลค่าผลผลิต (บาท)']:,.2f} ฿</td><td style='text-align:right; font-weight:bold;'>{r['สัดส่วนมูลค่า (%)']:.1f}%</td></tr>" for _, r in df_m_sum.iterrows()])
            rows_mat_html = "".join([f"<tr><td>{report_escape(r['ชนิดวัสดุ'])}</td><td style='text-align:center;'>{r['จำนวนคิว']}</td><td style='text-align:center;'>{r['จำนวนชิ้นงาน (ชิ้น)']}</td><td style='text-align:center;'>{r['ชั่วโมงผลิตจริง (ชม.)']:.2f}</td><td style='text-align:right;'>{r['มูลค่าผลผลิต (บาท)']:,.2f} ฿</td><td style='text-align:right; font-weight:bold;'>{r['สัดส่วน (%)']:.1f}%</td></tr>" for _, r in df_mat_sum.iterrows()])
            rows_job_html = "".join([
                f"<tr><td>{report_escape(r['แผนงาน'])}</td>"
                f"<td>{report_escape(r['ชื่อ Drawing.'])}</td>"
                f"<td style='text-align:center;'>{safe_int(r['จำนวน'], 1)}</td>"
                f"<td style='text-align:center;'>{report_escape(r['วัสดุ'])}</td>"
                f"<td>{report_escape(r['ขั้นตอน (Step)'])}</td>"
                f"<td>{report_escape(r['เลือกเครื่องจักร'])}</td>"
                f"<td style='text-align:center;'>{format_thai_datetime(r['เริ่มจริง']) or '-'}</td>"
                f"<td style='text-align:center;'>{format_thai_datetime(r['เสร็จจริง']) or '-'}</td>"
                f"<td style='text-align:center;'>{report_number(r['เวลาแผน (ชม.)'])}</td>"
                f"<td style='text-align:center;'>{report_number(r['เวลาจริง (ชม.)'])}</td>"
                f"<td style='text-align:right;'>{report_number(r['มูลค่ารวม (บาท)'], 2, ' ฿')}</td></tr>"
                for _, r in monthly_jobs.sort_values(by="Target_Date", ascending=True).iterrows()
            ])

            report_data_dict = {
                "month_str": f"{month_names[selected_month_idx-1]} {selected_year}",
                "print_date": get_bangkok_now().strftime('%d/%m/%Y %H:%M น.'),
                "total_qty": f"{total_qty_pieces:,}",
                "total_hours": f"{total_running_hrs:,.1f}",
                "total_value": f"{total_output_val:,.2f}",
                "on_time": f"{on_time_rate:.1f}" if pd.notna(on_time_rate) else "ไม่มีข้อมูล",
                "data_complete": f"{data_complete_rate:.0f}",
                "rows_m": rows_m_html,
                "rows_mat": rows_mat_html,
                "rows_job": rows_job_html
            }
            json_report_payload = json.dumps(report_data_dict, ensure_ascii=False).replace("<", "\\u003c")

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
                                    @page {{ size: A4 landscape; margin: 8mm 10mm; }}
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
                                    <div class="kpi-item"><div class="kpi-item-title">ต้นทุนเวลาเครื่องจักรจริง</div><div class="kpi-item-val">${{reportData.total_value}} ฿</div></div>
                                    <div class="kpi-item"><div class="kpi-item-title">จบไม่เกินเวลาตามแผน</div><div class="kpi-item-val">${{reportData.on_time}}${{reportData.on_time === 'ไม่มีข้อมูล' ? '' : ' %'}}</div><div style="font-size:8px;">ข้อมูลเวลาครบ ${{reportData.data_complete}}%</div></div>
                                </div>

                                <h3>1. กราฟวิเคราะห์ประสิทธิภาพและมูลค่าผลผลิต</h3>
                                <div class="chart-grid">
                                    <div>${{chart1Html}}</div>
                                    <div>${{chart2Html}}</div>
                                </div>

                                <h3>2. สรุปเวลาและต้นทุนเครื่องจักรแยกตามเครื่องจักร / แผนก</h3>
                                <table>
                                    <thead><tr><th>เครื่องจักร / แผนก</th><th>คิว</th><th>ชิ้นงาน</th><th>แผน (ชม.)</th><th>จริง (ชม.)</th><th>ผลต่าง</th><th>ต้นทุนเวลาเครื่อง (฿)</th><th>สัดส่วน (%)</th></tr></thead>
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
                        "เวลาจริง (ชม.)", "ผลต่าง (ชม.)", "แหล่งเวลา", "ผลตามกำหนด",
                        "เรตราคา (บาท/ชม.)", "มูลค่ารวม (บาท)"
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
                st.markdown("#### 🏭 สรุปประสิทธิภาพและสัดส่วนต้นทุนเวลาแยกตามเครื่องจักร")
                st.dataframe(
                    df_m_sum,
                    column_config={
                        "เครื่องจักร / แผนก": st.column_config.TextColumn("เครื่องจักร", width=150),
                        "จำนวนคิวงาน": st.column_config.NumberColumn("คิว", width=70, format="%d"),
                        "ชิ้นงานรวม (ชิ้น)": st.column_config.NumberColumn("ชิ้นงาน", width=85, format="%d"),
                        "เวลาแผน (ชม.)": st.column_config.NumberColumn("แผน (ชม.)", width=85, format="%.2f"),
                        "เวลาจริง (ชม.)": st.column_config.NumberColumn("จริง (ชม.)", width=85, format="%.2f"),
                        "ผลต่าง": st.column_config.TextColumn("ผลต่างเวลา", width=125),
                        "มูลค่าผลผลิต (บาท)": st.column_config.NumberColumn("ต้นทุนเวลาเครื่อง (บาท)", width=130, format="%.2f ฿"),
                        "สัดส่วนมูลค่า (%)": st.column_config.ProgressColumn("สัดส่วน", width=110, min_value=0, max_value=100, format="%d%%")
                    },
                    hide_index=True,
                    width=900
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
                        "มูลค่าผลผลิต (บาท)": st.column_config.NumberColumn("ต้นทุนเวลาเครื่อง (บาท)", width=120, format="%.2f ฿"),
                        "สัดส่วน (%)": st.column_config.ProgressColumn("สัดส่วน", width=95, min_value=0, max_value=100, format="%d%%")
                    },
                    hide_index=True,
                    width=610
                )

            st.divider()

            st.markdown("#### 📈 กราฟวิเคราะห์ต้นทุนเวลาและชั่วโมงการผลิตแยกตามเครื่องจักร")
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
                    width=960
                )
            else:
                st.success("🎉 ไม่มีงานใดที่ผลิตช้ากว่าเวลาแผนที่ตั้งไว้ในเดือนนี้")

            st.divider()

            st.markdown(f"#### 📋 รายละเอียดชิ้นงานทั้งหมดที่เสร็จสิ้นในเดือน {month_names[selected_month_idx-1]} {selected_year}")
            monthly_detail_df = monthly_jobs.copy()
            detail_filter = st.session_state.get("monthly_detail_quick_filter", "ALL")
            monthly_ontime_count = int((monthly_detail_df["ผลตามกำหนด"] == "🟢 จบไม่เกินแผน").sum())
            monthly_late_count = int((monthly_detail_df["ผลตามกำหนด"] == "🔴 จบเกินแผน").sum())
            monthly_missing_count = int((monthly_detail_df["แหล่งเวลา"] == "⚠️ เวลาไม่ครบ").sum())
            monthly_paused_count = int((pd.to_numeric(monthly_detail_df["เวลาพักสะสม (วินาที)"], errors="coerce").fillna(0) > 0).sum())

            st.markdown("**🔎 ค้นหาด่วนด้วยปุ่ม:**")
            monthly_quick_buttons = [
                ("ALL", f"🌐 ทั้งหมด ({len(monthly_detail_df)})"),
                ("ONTIME", f"🟢 ตามแผน ({monthly_ontime_count})"),
                ("LATE", f"🔴 เกินแผน ({monthly_late_count})"),
                ("PAUSED", f"⏸️ มีเวลาพัก ({monthly_paused_count})"),
                ("MISSING", f"⚠️ เวลาไม่ครบ ({monthly_missing_count})"),
            ]
            for detail_col, (detail_key, detail_label) in zip(st.columns(5), monthly_quick_buttons):
                with detail_col:
                    if st.button(
                        detail_label,
                        key=f"btn_monthly_detail_{detail_key}",
                        type="primary" if detail_filter == detail_key else "secondary",
                        use_container_width=True
                    ):
                        st.session_state.monthly_detail_quick_filter = detail_key
                        detail_filter = detail_key

            detail_machine_options = ["🌐 ทุกเครื่อง"] + sorted(monthly_detail_df["เลือกเครื่องจักร"].dropna().astype(str).unique().tolist())
            detail_plan_options = ["🌐 ทุกแผนงาน"] + sorted(monthly_detail_df["แผนงาน"].dropna().astype(str).unique().tolist())
            detail_material_options = ["🌐 ทุกวัสดุ"] + sorted(monthly_detail_df["วัสดุ"].dropna().astype(str).unique().tolist())
            md_c1, md_c2, md_c3, md_c4 = st.columns([1.2, 1, 1, 1.8])
            with md_c1:
                detail_machine = st.selectbox("🏭 เครื่องจักร:", detail_machine_options, key="monthly_detail_machine")
            with md_c2:
                detail_plan = st.selectbox("📌 แผนงาน:", detail_plan_options, key="monthly_detail_plan")
            with md_c3:
                detail_material = st.selectbox("🔩 วัสดุ:", detail_material_options, key="monthly_detail_material")
            with md_c4:
                detail_search = st.text_input(
                    "🔍 ค้นหา Drawing / Step / เครื่องจักร:",
                    placeholder="พิมพ์ Drawing, ขั้นตอน หรือชื่อเครื่อง...",
                    key="monthly_detail_search"
                )

            if detail_filter == "ONTIME":
                monthly_detail_df = monthly_detail_df[monthly_detail_df["ผลตามกำหนด"] == "🟢 จบไม่เกินแผน"]
            elif detail_filter == "LATE":
                monthly_detail_df = monthly_detail_df[monthly_detail_df["ผลตามกำหนด"] == "🔴 จบเกินแผน"]
            elif detail_filter == "PAUSED":
                monthly_detail_df = monthly_detail_df[
                    pd.to_numeric(monthly_detail_df["เวลาพักสะสม (วินาที)"], errors="coerce").fillna(0) > 0
                ]
            elif detail_filter == "MISSING":
                monthly_detail_df = monthly_detail_df[monthly_detail_df["แหล่งเวลา"] == "⚠️ เวลาไม่ครบ"]

            if normalize_filter_key(detail_machine) != normalize_filter_key("🌐 ทุกเครื่อง"):
                monthly_detail_df = monthly_detail_df[
                    monthly_detail_df["เลือกเครื่องจักร"].map(normalize_filter_key) == normalize_filter_key(detail_machine)
                ]
            if normalize_filter_key(detail_plan) != normalize_filter_key("🌐 ทุกแผนงาน"):
                monthly_detail_df = monthly_detail_df[
                    monthly_detail_df["แผนงาน"].map(normalize_filter_key) == normalize_filter_key(detail_plan)
                ]
            if normalize_filter_key(detail_material) != normalize_filter_key("🌐 ทุกวัสดุ"):
                monthly_detail_df = monthly_detail_df[
                    monthly_detail_df["วัสดุ"].map(normalize_filter_key) == normalize_filter_key(detail_material)
                ]
            if detail_search.strip():
                detail_q = detail_search.strip().casefold()
                search_mask = pd.Series(False, index=monthly_detail_df.index)
                for search_col in ["แผนงาน", "ชื่อ Drawing.", "ขั้นตอน (Step)", "เลือกเครื่องจักร", "วัสดุ"]:
                    search_mask |= monthly_detail_df[search_col].astype(str).str.casefold().str.contains(detail_q, regex=False, na=False)
                monthly_detail_df = monthly_detail_df[search_mask]

            st.caption(f"แสดงผล {len(monthly_detail_df):,} จากทั้งหมด {len(monthly_jobs):,} Step ในเดือนที่เลือก")
            st.dataframe(
                monthly_detail_df.sort_values(by="Target_Date", ascending=True)[[
                    "แผนงาน", "ชื่อ Drawing.", "จำนวน", "วัสดุ", "ขั้นตอน (Step)", 
                    "เลือกเครื่องจักร", "เริ่มจริง", "เสร็จจริง", "เวลาแผน (ชม.)", 
                    "เวลาจริง (ชม.)", "ผลต่าง (ชม.)", "แหล่งเวลา", "ผลตามกำหนด", "มูลค่ารวม (บาท)"
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
                    "แหล่งเวลา": st.column_config.TextColumn("คุณภาพเวลา", width=100),
                    "ผลตามกำหนด": st.column_config.TextColumn("จบตามกำหนด", width=125),
                    "มูลค่ารวม (บาท)": st.column_config.NumberColumn("มูลค่า (บาท)", width=120, format="%.2f ฿"),
                },
                hide_index=True,
                width=1620
            )

        else:
            st.info(f"ℹ️ ยังไม่มีประวัติงานที่ขึ้นสถานะ '✅ เสร็จสิ้นแล้ว' ในเดือน {month_names[selected_month_idx-1]} {selected_year}")

# ---------------------------------------------------------
# VIEW 5: จอทีวีกลางโรงงาน (Shop Floor TV Live Dashboard)
# ---------------------------------------------------------
elif st.session_state.current_view == "📺 จอทีวีกลางโรงงาน (TV Live)":
    st.cache_data.clear()
    df_live = fetch_jobs_from_supabase()

    now_bangkok = get_bangkok_now()
    cur_date_str = now_bangkok.strftime("%d/%m/%Y")

    machine_status_cards = []
    running_machines_count = 0
    hold_machines_count = 0
    idle_machines_count = 0
    overdue_machines_count = 0

    def get_tv_plan_window(job_row):
        """คืนเวลาเริ่ม/จบตามแผนของงานบนการ์ด และสถานะหลุดแผน"""
        plan_start = parse_flexible_datetime(job_row.get("วัน-เวลาขึ้นงาน"))
        if plan_start is None or pd.isna(plan_start):
            return None, None, "-", "-", False
        total_hours = (
            safe_float(job_row.get("Setup (น.)"), 10.0)
            + safe_float(job_row.get("Basic (น.)"), 0.0)
            + safe_float(job_row.get("โปรแกรม (น.)"), 120.0)
        ) / 60.0
        plan_start = get_next_valid_work_time(plan_start)
        _, plan_finish = add_work_time_with_shift(plan_start, total_hours)
        start_txt = plan_start.strftime("%d/%m/%Y %H:%M")
        finish_txt = plan_finish.strftime("%d/%m/%Y %H:%M")
        is_overdue = now_bangkok.replace(tzinfo=None) > plan_finish
        return plan_start, plan_finish, start_txt, finish_txt, is_overdue

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
            if h_dt_parsed is not None and pd.notna(h_dt_parsed):
                h_start_txt = f" [เริ่ม {h_dt_parsed.strftime('%H:%M น.')}]"
            hold_alert_html = f'<div style="margin-top:4px; padding:3px 6px; background:rgba(217, 119, 6, 0.35); border:1px dashed #FCD34D; border-radius:6px; font-size:10.5px; color:#FEF08A;">🛑 <b>พักงานรอ:</b> {h_first.get("แผนงาน", "-")} ({h_first.get("ชื่อ Drawing.", "-")}){h_start_txt}</div>'

        if not running_job.empty:
            running_machines_count += 1
            r_info = running_job.iloc[0]
            s_start = r_info.get("เริ่มจริง")
            r_paused_seconds = int(safe_float(r_info.get("เวลาพักสะสม (วินาที)"), 0.0))
            p_code = str(r_info.get("แผนงาน", "-"))
            d_code = str(r_info.get("ชื่อ Drawing.", "-"))
            step_name = str(r_info.get("ขั้นตอน (Step)", "-"))
            
            r_ready_dt, r_finish_dt, ready_display_txt, finish_display_txt, is_overdue = get_tv_plan_window(r_info)

            start_disp_txt = "-"
            start_epoch = to_bangkok_epoch_ms(s_start)
            r_start_parsed = parse_flexible_datetime(s_start)

            if r_start_parsed is None and r_ready_dt is not None and pd.notna(r_ready_dt):
                r_start_parsed = r_ready_dt
                start_epoch = to_bangkok_epoch_ms(r_ready_dt)

            if r_start_parsed is not None and pd.notna(r_start_parsed):
                start_disp_txt = r_start_parsed.strftime("%H:%M น.")
            
            tv_card_cls = "tv-card tv-card-running"
            badge_html = '<span class="tv-pulse-dot" style="margin-right:6px;"></span> <b style="color:#A7F3D0;">กำลังรันงาน</b>'
            if is_overdue:
                overdue_machines_count += 1
                tv_card_cls = "tv-card tv-card-overdue"
                badge_html = '<span class="tv-overdue-badge">🚨 หลุดแผน</span>'

            time_info_combined = f'''
            <div style="font-size:13px; font-weight:700; color:#FFFFFF; line-height:1.5;">
                <div style="display:flex; justify-content:space-between; align-items:center;">
                    <span>🚀 <b>เริ่ม:</b> <span style="color:#93C5FD;">{start_disp_txt}</span></span>
                    <span>⏱️ <span class="pes-live-timer" data-start-epoch="{start_epoch}" data-paused-seconds="{r_paused_seconds}" style="font-family:monospace; font-size:14.5px; font-weight:900; color:#FDE047;">00:00:00</span></span>
                </div>
                <div style="margin-top:4px; font-size:12.5px; opacity:0.98; background:rgba(0,0,0,0.25); padding:4px 8px; border-radius:6px; line-height:1.5;">
                    <div>📅 <b>เริ่มตามแผน:</b> {ready_display_txt}</div>
                    <div>🏁 <b>จบตามแผน:</b> {finish_display_txt}</div>
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
            h_start = h_info.get("เริ่มจริง")
            p_code = str(h_info.get("แผนงาน", "-"))
            d_code = str(h_info.get("ชื่อ Drawing.", "-"))
            step_name = str(h_info.get("ขั้นตอน (Step)", "-"))
            
            h_ready_dt, h_finish_dt, ready_display_txt, finish_display_txt, is_overdue = get_tv_plan_window(h_info)

            h_start_txt = ""
            h_st_parsed = parse_flexible_datetime(h_start)
            if h_st_parsed is not None and pd.notna(h_st_parsed):
                h_start_txt = f" (เริ่มไว้: {h_st_parsed.strftime('%H:%M น.')})"

            time_info_combined = f'''
            <div style="font-size:13px; font-weight:700; color:#FEF3C7; line-height:1.5;">
                <div>⚠️ <b>เครื่องหยุด:</b> รอเบิกวัสดุใหม่{h_start_txt}</div>
                <div style="margin-top:4px; font-size:12.5px; opacity:0.98; background:rgba(0,0,0,0.25); padding:4px 8px; border-radius:6px; line-height:1.5;">
                    <div>📅 <b>เริ่มตามแผน:</b> {ready_display_txt}</div>
                    <div>🏁 <b>จบตามแผน:</b> {finish_display_txt}</div>
                </div>
            </div>
            '''

            hold_card_cls = "tv-card tv-card-hold"
            hold_badge_html = '<b style="color:#FDE68A;">🛑 พักงาน (รอวัสดุ)</b>'
            if is_overdue:
                overdue_machines_count += 1
                hold_card_cls = "tv-card tv-card-overdue"
                hold_badge_html = '<span class="tv-overdue-badge">🚨 หลุดแผน</span>'

            machine_status_cards.append({
                "machine": m,
                "status": "HOLD",
                "card_class": hold_card_cls,
                "badge_html": hold_badge_html,
                "plan": p_code,
                "drawing": d_code,
                "step": step_name,
                "time_info": time_info_combined
            })
        else:
            idle_machines_count += 1
            next_txt = "ไม่มีคิวรอ"
            is_overdue = False
            next_dates_html = '''
            <div style="margin-top:4px; font-size:12.5px; color:#CBD5E1; background:rgba(0,0,0,0.25); padding:4px 8px; border-radius:6px; line-height:1.5;">
                <div>📅 <b>เริ่มตามแผน:</b> -</div>
                <div>🏁 <b>จบตามแผน:</b> -</div>
            </div>
            '''
            if not waiting_jobs.empty:
                w_first = waiting_jobs.iloc[0]
                p_code = str(w_first.get('แผนงาน', '-'))
                d_code = str(w_first.get('ชื่อ Drawing.', '-'))
                step_name = str(w_first.get('ขั้นตอน (Step)', '-'))
                next_txt = f"คิวถัดไป: {p_code} ({d_code})"
                
                w_ready_dt, w_finish_dt, ready_display_txt, finish_display_txt, is_overdue = get_tv_plan_window(w_first)
                
                next_dates_html = f'''
                <div style="margin-top:4px; font-size:12.5px; color:#FFFFFF; background:rgba(0,0,0,0.25); padding:4px 8px; border-radius:6px; line-height:1.5;">
                    <div>📅 <b>เริ่มตามแผน:</b> {ready_display_txt}</div>
                    <div>🏁 <b>จบตามแผน:</b> {finish_display_txt}</div>
                </div>
                '''

            idle_card_cls = "tv-card tv-card-idle"
            idle_badge_html = '<b style="color:#94A3B8;">⚪ เครื่องว่าง (IDLE)</b>'
            if not waiting_jobs.empty and is_overdue:
                overdue_machines_count += 1
                idle_card_cls = "tv-card tv-card-overdue"
                idle_badge_html = '<span class="tv-overdue-badge">🚨 หลุดแผน</span>'

            machine_status_cards.append({
                "machine": m,
                "status": "IDLE",
                "card_class": idle_card_cls,
                "badge_html": idle_badge_html,
                "plan": "พร้อมรับงาน",
                "drawing": next_txt,
                "step": "-",
                "time_info": f"<div style='font-size:13px; font-weight:600; color:#CBD5E1;'>📋 คิวรอ: {len(waiting_jobs)} งาน</div>{next_dates_html}"
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
                <span style="color:#94A3B8;">⚪ ว่าง {idle_machines_count}</span> |
                <span style="color:#FCA5A5;">🚨 หลุดแผน {overdue_machines_count} เครื่อง</span>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    card_items = []
    for c in machine_status_cards:
        card_item = (
            f'<div class="{c["card_class"]}">'
            f'<div style="display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:4px;">'
            f'<div style="font-size:17px; font-weight:800; letter-spacing:0.2px;">{c["machine"]}</div>'
            f'<div style="font-size:12px;">{c["badge_html"]}</div>'
            f'</div>'
            f'<div style="margin: 3px 0;">'
            f'<div style="font-size:15px; font-weight:700; color:#FFFFFF; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">📌 {c["plan"]}</div>'
            f'<div style="font-size:13.5px; color:rgba(255,255,255,0.9); white-space:nowrap; overflow:hidden; text-overflow:ellipsis; margin-top:2px;">📄 {c["drawing"]}</div>'
            f'<div style="font-size:12.5px; color:rgba(255,255,255,0.78); margin-top:2px;">⚙️ ขั้นตอน: {c["step"]}</div>'
            f'</div>'
            f'<div style="margin-top:8px; padding-top:6px; border-top:1px solid rgba(255,255,255,0.18);">'
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
                    const pausedSecs = parseFloat(el.getAttribute('data-paused-seconds') || '0') || 0;
                    const diffMs = Math.max(0, nowTs - startTs - (pausedSecs * 1000));
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
