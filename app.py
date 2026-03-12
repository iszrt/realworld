import streamlit as st
import pandas as pd
import numpy as np
import io
import time
import requests
import xml.etree.ElementTree as ET
from xml.dom import minidom
from tsd import ETFCSA_TSD

# --- PAGE CONFIGURATION ---
st.set_page_config(page_title="ETFCSA-TSD ITC Scheduler", layout="wide")

st.title("🎓 University Class Scheduler (ITC 2019 Standard)")
st.markdown("**Powered by Event-Triggered FCSA with Temporal Substrate Drift (Thesis Algorithm)**")

# --- SIDEBAR: PARAMETERS ---
st.sidebar.header("Algorithm Parameters")
st.sidebar.markdown("Adjust hyperparameters for your thesis algorithm.")

N = st.sidebar.slider("Population Size (N)", min_value=10, max_value=300, value=200, step=10)
max_evals = st.sidebar.number_input("Max Evaluations", min_value=1000, max_value=500000, value=150000, step=10000)
n_clones = st.sidebar.slider("Clone Rate (n_clones)", min_value=1, max_value=20, value=10)
rho = st.sidebar.slider("Substrate Decay (rho)", min_value=0.5, max_value=0.99, value=0.98, step=0.01)

# Meta info for ITC XML Header
st.sidebar.header("ITC 2019 Metadata")
author_name = st.sidebar.text_input("Author Name", value="I. Zarate, et al.")
institution = st.sidebar.text_input("Institution", value="USTP")
instance_name = st.sidebar.text_input("Instance Name", value="bet-sum18")

# ITC API Credentials
st.sidebar.header("ITC 2019 API Validation")
st.sidebar.markdown("Enter credentials to automatically validate the schedule after optimization.")
itc_email = st.sidebar.text_input("ITC Email")
itc_password = st.sidebar.text_input("ITC Password", type="password")

# --- HELPER: ITC 2019 XML GENERATOR ---
def generate_itc2019_xml(schedule_data, runtime, fitness):
    """
    Translates the generated Pandas schedule into the ITC 2019 XML format.
    """
    root = ET.Element("solution", {
        "name": instance_name,
        "runtime": f"{runtime:.2f}",
        "cores": "1",
        "technique": f"ETFCSA_TSD (Conflicts: {fitness})",
        "author": author_name,
        "institution": institution,
        "country": "Philippines"
    })
    
    # ITC Maps Days to a 7-bit string (Mon, Tue, Wed, Thu, Fri, Sat, Sun)
    day_map = {
        'Monday': '1000000', 'Tuesday': '0100000', 'Wednesday': '0010000',
        'Thursday': '0001000', 'Friday': '0000100', 'Saturday': '0000010'
    }
    
    def parse_time_to_itc_start(time_str):
        try:
            start_str = time_str.split(" - ")[0]
            t = pd.to_datetime(start_str, format="%I:%M %p")
            return str((t.hour * 60 + t.minute) // 5)
        except:
            return "0"

    weeks_str = "11111111111111"

    room_to_id = {r: str(i+1) for i, r in enumerate(pd.DataFrame(schedule_data)['Room'].unique())}
    section_to_id = {s: str(i+1) for i, s in enumerate(pd.DataFrame(schedule_data)['Section'].unique())}

    for i, row in enumerate(schedule_data):
        class_node = ET.SubElement(root, "class", {
            "id": str(i + 1),
            "days": day_map.get(row['Day'], '0000000'),
            "start": parse_time_to_itc_start(row['Time']),
            "weeks": weeks_str,
            "room": room_to_id.get(row['Room'], "")
        })
        ET.SubElement(class_node, "student", {
            "id": section_to_id.get(row['Section'], "")
        })

    # Prettify the XML output
    xml_str = ET.tostring(root, 'utf-8')
    parsed = minidom.parseString(xml_str)
    pretty_xml = parsed.toprettyxml(indent="  ")
    
    # Split the auto-generated XML declaration from the rest of the body
    if pretty_xml.startswith('<?xml'):
        pretty_xml = pretty_xml.split('\n', 1)[1]
        
    # Rebuild the header in the strict order required by the validator
    header = '<?xml version="1.0" encoding="UTF-8"?>\n'
    doctype = '<!DOCTYPE solution PUBLIC "-//ITC 2019//DTD Problem Format/EN" "http://www.itc2019.org/competition-format.dtd">\n'
    
    return header + doctype + pretty_xml

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

        def calculate_conflicts(x: np.ndarray) -> float:
            schedule = decode_schedule(x)
            penalty = 0
            room_usage = set()
            instructor_usage = set()
            section_usage = set()
            
            for entry in schedule:
                ts, rm, inst, sec = entry['Timeslot_Idx'], entry['Room_Idx'], entry['Instructor'], entry['Section']
                
                if (rm, ts) in room_usage: penalty += 1
                else: room_usage.add((rm, ts))
                
                if str(inst).upper() not in ['NAN', 'NONE', 'NO TEACHER', 'UNKNOWN']:
                    if (inst, ts) in instructor_usage: penalty += 1
                    else: instructor_usage.add((inst, ts))
                    
                if (sec, ts) in section_usage: penalty += 1
                else: section_usage.add((sec, ts))
                    
            return float(penalty)
        
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
        
        # --- EXPORT OPTIONS ---
        st.header("3. Download Output")
        
        col1, col2 = st.columns(2)
        
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
        
        with col1:
            st.download_button(
                label="📊 Download Excel Format",
                data=output.getvalue(),
                file_name="Optimized_Schedule.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )

        xml_data = generate_itc2019_xml(best_schedule, runtime, int(best_f))
        
        with col2:
            st.download_button(
                label="📝 Download ITC 2019 XML Format",
                data=xml_data,
                file_name=f"{instance_name}_solution.xml",
                mime="application/xml"
            )
            
        with st.expander("👀 View ITC 2019 XML Output Code"):
            st.code(xml_data, language="xml")

        # --- ITC 2019 API VALIDATION ---
        st.header("4. ITC 2019 API Validation")
        
        if not itc_email or not itc_password:
            st.info("⚠️ Enter your ITC email and password in the sidebar to view official validation metrics here.")
        else:
            with st.spinner("Connecting to ITC 2019 servers for validation..."):
                url = "https://www.itc2019.org/itc2019-validator"
                credentials = (itc_email, itc_password)
                headers = {"Content-Type": "text/xml;charset=UTF-8"}
                
                try:
                    # Send the XML directly as a utf-8 encoded string
                    response = requests.post(url, auth=credentials, headers=headers, data=xml_data.encode('utf-8'))
                    
                    if response.status_code == 200:
                        response_data = response.json()
                        st.success("Validation Successful!")
                        
                        st.subheader(f"Optimization Results: {response_data.get('instance', 'Unknown Instance')}")

                        # Top level metrics 
                        m_col1, m_col2, m_col3 = st.columns(3)
                        with m_col1:
                            valid_status = response_data.get("result", "UNKNOWN")
                            st.metric(label="Validation Status", value=valid_status)
                        with m_col2:
                            total_cost = response_data.get("totalCost", {}).get("value", 0)
                            st.metric(label="Total Penalty (Cost)", value=total_cost)
                        with m_col3:
                            assigned = response_data.get("assignedVariables", {})
                            assigned_str = f"{assigned.get('value', 0)} / {assigned.get('total', 0)}"
                            st.metric(label="Variables Assigned", value=assigned_str)

                        st.divider()

                        # Detailed Penalty Metrics
                        st.markdown("**Penalty Breakdown**")
                        p_col1, p_col2, p_col3, p_col4 = st.columns(4)
                        with p_col1:
                            time_pen = response_data.get("timePenalty", {}).get("value", 0)
                            st.metric(label="Time Penalty", value=time_pen)
                        with p_col2:
                            room_pen = response_data.get("roomPenalty", {}).get("value", 0)
                            st.metric(label="Room Penalty", value=room_pen)
                        with p_col3:
                            dist_pen = response_data.get("distributionPenalty", {}).get("value", 0)
                            st.metric(label="Distribution Penalty", value=dist_pen)
                        with p_col4:
                            student_conf = response_data.get("studentConflicts", {}).get("value", 0)
                            st.metric(label="Student Conflicts", value=student_conf)

                        st.divider()

                        # Performance Metrics
                        st.markdown("**Performance**")
                        perf_col1, perf_col2 = st.columns(2)
                        with perf_col1:
                            st.metric(label="Runtime (s)", value=response_data.get("runtime", "N/A"))
                        with perf_col2:
                            st.metric(label="Technique", value=response_data.get("technique", "N/A"))
                            
                        # Show the raw validation error log
                        with st.expander("View Full ITC Validation Error Log"):
                            st.write(response_data.get("log", ["No log available."]))
                            
                    else:
                        st.error(f"API Error: Received status code {response.status_code}")
                        st.write(response.text)
                except Exception as e:
                    st.error(f"Failed to connect to the ITC Validator: {e}")