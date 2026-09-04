# =====================================================
            # 2. ใบจ่ายคิวงานหน้าเครื่อง (Work Order Sheet) - ฉบับเต็มสมบูรณ์
            # =====================================================
            st.subheader("📋 ใบจ่ายคิวงานหน้าเครื่อง (Work Order Sheet)")

            df_wo_direct = active_jobs_editor_df.copy()
            df_wo_direct["_dt_start"] = df_wo_direct["วัน-เวลาขึ้นงาน"].apply(parse_flexible_datetime)
            df_wo_direct["_dt_finish"] = df_wo_direct["วัน-เวลาจบงาน"].apply(parse_flexible_datetime)

            # จัดลำดับคิวหน้าเครื่องอย่างแม่นยำ: กำลังผลิต (0) -> พักงาน (1) -> รอคิวตามเวลา (2)
            def get_wo_queue_order(r):
                st_val = str(r.get("สถานะงาน", r.get("สถานะ", "")))
                if "กำลังผลิต" in st_val:
                    prio = 0
                elif "พักงาน" in st_val:
                    prio = 1
                else:
                    prio = 2
                dt_p = parse_flexible_datetime(r.get("วัน-เวลาขึ้นงาน"))
                return (prio, dt_p if dt_p is not None else pd.Timestamp.max, safe_int(r.get("ID")))

            df_wo_direct["_wo_order"] = df_wo_direct.apply(get_wo_queue_order, axis=1)
            df_wo_direct = df_wo_direct.sort_values(by=["เลือกเครื่องจักร", "_wo_order"]).drop(columns=["_wo_order"]).reset_index(drop=True)

            # กำหนดลำดับคิว: เริ่มจาก คิวที่ 1 สำหรับงานที่กำลังรันอยู่เสมอ
            df_wo_direct["ลำดับคิว"] = df_wo_direct.groupby("เลือกเครื่องจักร").cumcount() + 1
            df_wo_direct["ลำดับคิว"] = df_wo_direct["ลำดับคิว"].apply(lambda q: f"คิวที่ {q}")

            df_wo_direct["เครื่องจักร / แผนก"] = df_wo_direct["เลือกเครื่องจักร"]
            df_wo_direct["สถานะ"] = df_wo_direct["สถานะงาน"]
            df_wo_direct["เริ่มขึ้นงานตามแผน"] = df_wo_direct["วัน-เวลาขึ้นงาน"]
            df_wo_direct["จบงานตามแผน"] = df_wo_direct["วัน-เวลาจบงาน"]
            df_wo_direct["กำหนดพร้อมขึ้นงาน"] = df_wo_direct["วัน-เวลาขึ้นงาน"]

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
                    if st.button("🌐 ทั้งหมด", type=btn_all_type, use_container_width=True):
                        st.session_state.wo_color_filter = "ALL"
                        st.rerun()
                with f_b2:
                    btn_warn_type = "primary" if cur_wo_filter == "WARN" else "secondary"
                    if st.button(f"🟡 ใกล้เสร็จ ({warn_count})", type=btn_warn_type, use_container_width=True, help="เหลือน้อยกว่า 1 ชม."):
                        st.session_state.wo_color_filter = "WARN"
                        st.rerun()
                with f_b3:
                    btn_late_type = "primary" if cur_wo_filter == "LATE" else "secondary"
                    if st.button(f"🔴 เกินแผน ({late_count})", type=btn_late_type, use_container_width=True, help="เลยกำหนดเวลาแผน"):
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

            display_cols = [c for c in df_display.columns if c not in ["_dt_start", "_dt_finish"]]

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
