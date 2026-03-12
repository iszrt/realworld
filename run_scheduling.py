import pandas as pd
import numpy as np
from tsd import ETFCSA_TSD 

# 1. LOAD THE REFINED DATA
print("Loading data...")
file_name = 'Structured_Data_Algorithm_Input_Refined.xlsx'
df_classes = pd.read_excel(file_name, sheet_name='Class_Requirements')
df_rooms = pd.read_excel(file_name, sheet_name='Room_List')

classes = df_classes.to_dict('records')
rooms = df_rooms['Room'].tolist()
num_classes = len(classes)
num_rooms = len(rooms)

# 2. DEFINE TIME SLOTS (Separated Day and Time)
days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']
times = [
    "07:00 AM - 08:30 AM",
    "08:30 AM - 10:00 AM",
    "10:00 AM - 11:30 AM",
    "11:30 AM - 01:00 PM",
    "01:00 PM - 02:30 PM",
    "02:30 PM - 04:00 PM",
    "04:00 PM - 05:30 PM",
    "05:30 PM - 07:00 PM",
    "07:00 PM - 08:30 PM",
    "08:30 PM - 10:00 PM"
]

# Create a list of dictionaries holding both Day and Time separately
timeslots = [{'Day': d, 'Time': t} for d in days for t in times]
num_timeslots = len(timeslots)

print(f"Total Classes to Schedule: {num_classes}")
print(f"Available Rooms: {num_rooms}")
print(f"Available Timeslot Combinations: {num_timeslots}")

# 3. ENCODING AND FITNESS FUNCTION
dim = num_classes * 2

def decode_schedule(x: np.ndarray):
    schedule = []
    for i in range(num_classes):
        ts_val = x[2*i] * num_timeslots
        ts_idx = int(np.clip(ts_val, 0, num_timeslots - 1))
        
        rm_val = x[2*i + 1] * num_rooms
        rm_idx = int(np.clip(rm_val, 0, num_rooms - 1))
        
        schedule.append({
            'Class_Index': i,
            'Instructor': classes[i]['Instructor'],
            'Section': classes[i]['Section'],
            'Subject': classes[i]['Subject'],
            'Department': classes[i]['Department'],
            'Timeslot_Idx': ts_idx,
            'Day': timeslots[ts_idx]['Day'],        # Extracted Day
            'Time': timeslots[ts_idx]['Time'],      # Extracted Time
            'Room_Idx': rm_idx,
            'Room': rooms[rm_idx]
        })
    return schedule

def calculate_conflicts(x: np.ndarray) -> float:
    schedule = decode_schedule(x)
    penalty = 0
    
    room_usage = set()
    instructor_usage = set()
    section_usage = set()
    
    for entry in schedule:
        ts = entry['Timeslot_Idx']
        rm = entry['Room_Idx']
        inst = entry['Instructor']
        sec = entry['Section']
        
        if (rm, ts) in room_usage:
            penalty += 1
        else:
            room_usage.add((rm, ts))
            
        if (inst, ts) in instructor_usage:
            penalty += 1
        else:
            instructor_usage.add((inst, ts))
            
        if (sec, ts) in section_usage:
            penalty += 1
        else:
            section_usage.add((sec, ts))
            
    return float(penalty)

# 4. RUNNING YOUR ETFCSA_TSD ALGORITHM
if __name__ == "__main__":
    bounds = [(0.0, 1.0) for _ in range(dim)]
    
    print("\nInitializing ETFCSA with Temporal Substrate Drift...")
    
    optimizer = ETFCSA_TSD(
        func=calculate_conflicts,
        bounds=bounds,
        N=500,                 # Increase population size (Antibodies)
        max_evals=1000000,      # Give it much more time to search
        n_clones=10,           # More clones per generation
        rho=0.95,             
        c_threshold=3.0,
        eta=0.25
    )
    
    print("Optimizing Schedule (this may take a moment depending on max_evals)...")
    best_x, best_f, info = optimizer.optimize()
    
    print("\nOptimization Complete!")
    print(f"Total Conflicts (Fitness) in Best Schedule: {best_f}")
    
    # 5. EXPORT THE FINAL SCHEDULE SEPARATED BY SECTION
    best_schedule = decode_schedule(best_x)
    df_best = pd.DataFrame(best_schedule)
    
    # Map days to numbers so they sort chronologically (Monday->Saturday) instead of alphabetically
    day_map = {'Monday': 1, 'Tuesday': 2, 'Wednesday': 3, 'Thursday': 4, 'Friday': 5, 'Saturday': 6}
    df_best['Day_Num'] = df_best['Day'].map(day_map)
    
    # Sort the dataframe logically
    df_sorted = df_best.sort_values(by=['Department', 'Section', 'Day_Num', 'Time'])
    
    # Select final columns to display
    df_final = df_sorted[['Department', 'Section', 'Subject', 'Instructor', 'Day', 'Time', 'Room']]
    
    output_file = 'Optimized_Final_Schedule_By_Section.xlsx'
    print(f"\nExporting separated schedules to {output_file}...")
    
    with pd.ExcelWriter(output_file, engine='xlsxwriter') as writer:
        # Master sheet
        df_final.to_excel(writer, sheet_name='ALL_CLASSES', index=False)
        
        # Individual Section sheets
        unique_sections = sorted(df_final['Section'].unique())
        for sec in unique_sections:
            df_sec = df_final[df_final['Section'] == sec]
            safe_sheet_name = str(sec)[:31]
            df_sec.to_excel(writer, sheet_name=safe_sheet_name, index=False)
            
            # Auto-adjust column widths
            worksheet = writer.sheets[safe_sheet_name]
            for i, col in enumerate(df_sec.columns):
                max_len = max(df_sec[col].astype(str).map(len).max(), len(col)) + 2
                worksheet.set_column(i, i, max_len)

    print("Export complete! Check the Excel file tabs for individual sections.")