import streamlit as st
import pandas as pd
import numpy as np
import io
import time
from tsd import ETFCSA_TSD

# --- PAGE CONFIGURATION ---
st.set_page_config(page_title="ETFCSA-TSD Internal Scheduler", layout="wide")

st.title("🎓 University Class Scheduler")
st.markdown("**Powered by Event-Triggered FCSA with Temporal Substrate Drift (ETFCSA-TSD)**")

# --- SIDEBAR: PARAMETERS ---
st.sidebar.header("Algorithm Parameters")
st.sidebar.markdown("Adjust hyperparameters for your thesis algorithm.")

N = st.sidebar.slider("Population Size (N)", min_value=10, max_value=300, value=200, step=10)
max_evals = st.sidebar.number_input("Max Evaluations", min_value=1000, max_value=500000, value=150000, step=10000)
n_clones = st.sidebar.slider("Clone Rate (n_clones)", min_value=1, max_value=20, value=10)
rho = st.sidebar.slider("Substrate Decay (rho)", min_value=0.5, max_value=0.99, value=0.98, step=0.01)

# Meta info for internal tracking
st.sidebar.header("Instance Metadata")
author_name = st.sidebar.text_input("Author Name", value="I. Zarate, et al.")
institution = st.sidebar.text_input("Institution", value="USTP")
instance_name = st.sidebar.text_input("Instance Name", value="USTP-Semester2")

# --- HELPER: CUSTOM VALIDATION METRICS ---
def evaluate_schedule_metrics(schedule):
    """
    Evaluates the decoded schedule to provide a detailed breakdown of conflicts
    mimicking standard timetabling competition metrics.
    """
    room_usage = set()
    instructor_usage = set()
    section_usage = set()
    
    room_penalty = 0
    time_penalty = 0  # Instructor overlaps
    student_conflicts = 0
    distribution_penalty = 0 # Late classes penalty
    
    for entry in schedule:
        ts = entry['Timeslot_Idx']
        rm = entry['Room_Idx']
        inst = entry['Instructor']
        sec = entry['Section']
        time_str = entry['Time']
        
        # 1. Room Overlaps
        if (rm, ts) in room_usage:
            room_penalty += 1
        else:
            room_usage.add((rm, ts))
            
        # 2. Instructor Overlaps (Time Penalty)
        if str(inst).upper() not in ['NAN', 'NONE', 'NO TEACHER', 'UNKNOWN', '']:
            if (inst, ts) in instructor_usage:
                time_penalty += 1
            else:
                instructor_usage.add((inst, ts))
                
        # 3. Section Overlaps (Student Conflicts)
        if (sec, ts) in section_usage:
            student_conflicts += 1
        else:
            section_usage.add((sec, ts))
            
        # 4. Distribution Penalty (e.g., classes scheduled 05:30 PM or later)
        if "05:30 PM" in time_str or "07:00 PM" in time_str or "08:30 PM" in time_str:
            distribution_penalty += 1
            
    total_cost = room_penalty + time_penalty + student_conflicts # Keeping distribution out of hard conflicts for now
    
    return {
        "room_penalty": room_penalty,
        "time_penalty": time_penalty,
        "student_conflicts": student_conflicts,
        "distribution_penalty": distribution_penalty,
        "total_cost": total_cost
    }


# --- MAIN UI ---
st.header("1. Upload Class Requirements Data")
uploaded_file = st.file_uploader("Upload 'Structured_Data_Algorithm_Input_Refined.xlsx'", type=["xlsx"])

if uploaded_file is not None:
    df_classes = pd.read_excel(uploaded_file, sheet_name='Class_Requirements')
    df_rooms = pd.read_excel(uploaded_file, sheet_name='Room_List')
    st.success(f"Data loaded successfully! Found {len(df_classes)} classes and {len(df_rooms)} rooms.")
    
    if st.button("🚀 Run Optimization"):
        
        classes = df_classes.to_dict('records')
        rooms = df_rooms['Room'].tolist()
        num_classes = len(classes)
        num_rooms = len(rooms)
        
        days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']
        times = [
            "07:00 AM - 08:30 AM", "08:30 AM - 10:00 AM", "10:00 AM - 11:30 AM",
            "11:30 AM - 01:00 PM", "01:00 PM - 02:30 PM", "02:30 PM - 04:00 PM",
            "04:00 PM - 05:30 PM", "05:30 PM - 07:00 PM", "07:00 PM - 08:30 PM",
            "08:30 PM - 10:00 PM"
        ]
        timeslots = [{'Day': d, 'Time': t} for d in days for t in times]
        num_timeslots = len(timeslots)
        dim = num_classes * 2
        
        def decode_schedule(x: np.ndarray):
            schedule = []
            for i in range(num_classes):
                ts_idx = int(np.clip(x[2*i] * num_timeslots, 0, num_timeslots - 1))
                rm_idx = int(np.clip(x[2*i + 1] * num_rooms, 0, num_rooms - 1))
                schedule.append({
                    'Department': classes[i]['Department'],
                    'Section': classes[i]['Section'],
                    'Subject': classes[i]['Subject'],
                    'Instructor': classes[i]['Instructor'],
                    'Day': timeslots[ts_idx]['Day'],
                    'Time': timeslots[ts_idx]['Time'],
                    'Room': rooms[rm_idx],
                    'Timeslot_Idx': ts_idx,
                    'Room_Idx': rm_idx
                })
            return schedule

        # Link the objective function directly to our metrics logic
        def calculate_conflicts(x: np.ndarray) -> float:
            schedule = decode_schedule(x)
            metrics = evaluate_schedule_metrics(schedule)
            # The algorithm minimizes hard constraints (Room, Instructor, Student overlaps)
            return float(metrics["total_cost"])
        
        st.header("2. Optimizing Schedule")
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        def update_progress(**kwargs):
            current_evals = kwargs.get('evals', 0)
            progress = min(current_evals / max_evals, 1.0)
            progress_bar.progress(progress)
            status_text.markdown(f"**Evaluations:** {current_evals} / {max_evals}...")
            
        bounds = [(0.0, 1.0) for _ in range(dim)]
        optimizer = ETFCSA_TSD(
            func=calculate_conflicts,
            bounds=bounds,
            N=N,
            max_evals=max_evals,
            n_clones=n_clones,
            rho=rho,
            c_threshold=3.0,
            eta=0.25,
            progress=update_progress 
        )
        
        start_time = time.time()
        best_x, best_f, info = optimizer.optimize()
        runtime = time.time() - start_time
        
        progress_bar.progress(1.0)
        status_text.success(f"✅ Optimization Complete! Final Fitness (Conflicts): {int(best_f)} | Time: {runtime:.2f}s")
        
        best_schedule = decode_schedule(best_x)
        final_metrics = evaluate_schedule_metrics(best_schedule)
        
        # --- INTERNAL VALIDATION DASHBOARD ---
        st.header("3. ETFCSA-TSD Performance Dashboard")
        
        # Top level metrics 
        m_col1, m_col2, m_col3 = st.columns(3)
        with m_col1:
            valid_status = "VALID" if final_metrics["total_cost"] == 0 else "NEEDS REVISION"
            st.metric(label="Validation Status", value=valid_status)
        with m_col2:
            st.metric(label="Total Hard Penalty (Cost)", value=final_metrics["total_cost"])
        with m_col3:
            st.metric(label="Variables Assigned", value=f"{num_classes} / {num_classes}")

        st.divider()

        # Detailed Penalty Metrics
        st.markdown("**Penalty Breakdown**")
        p_col1, p_col2, p_col3, p_col4 = st.columns(4)
        with p_col1:
            st.metric(label="Instructor Overlaps (Time)", value=final_metrics["time_penalty"])
        with p_col2:
            st.metric(label="Room Double-Booking", value=final_metrics["room_penalty"])
        with p_col3:
            st.metric(label="Late Classes (Distribution)", value=final_metrics["distribution_penalty"], help="Classes scheduled 5:30 PM or later.")
        with p_col4:
            st.metric(label="Section Conflicts (Student)", value=final_metrics["student_conflicts"])

        st.divider()

        # Performance Metrics
        st.markdown("**Algorithm Performance**")
        perf_col1, perf_col2 = st.columns(2)
        with perf_col1:
            st.metric(label="Runtime (s)", value=f"{runtime:.2f}")
        with perf_col2:
            st.metric(label="Technique", value="ETFCSA_TSD")
            
        # --- EXPORT OPTIONS ---
        st.header("4. Download Output")
        
        df_best = pd.DataFrame(best_schedule)
        day_map_excel = {'Monday': 1, 'Tuesday': 2, 'Wednesday': 3, 'Thursday': 4, 'Friday': 5, 'Saturday': 6}
        df_best['Day_Num'] = df_best['Day'].map(day_map_excel)
        df_final = df_best.sort_values(by=['Department', 'Section', 'Day_Num', 'Time'])[['Department', 'Section', 'Subject', 'Instructor', 'Day', 'Time', 'Room']]
        
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df_final.to_excel(writer, sheet_name='ALL_CLASSES', index=False)
            for sec in sorted(df_final['Section'].unique()):
                df_sec = df_final[df_final['Section'] == sec]
                safe_name = str(sec)[:31]
                df_sec.to_excel(writer, sheet_name=safe_name, index=False)
        
        st.download_button(
            label="📊 Download Excel Format",
            data=output.getvalue(),
            file_name=f"{instance_name}_Optimized_Schedule.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )