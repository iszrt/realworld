# Optimization Integration Documentation

**Project:** CITC Department University Course Timetabling using ETFCSA-TSD
**Date:** March 2026
**Purpose:** Document how the ETFCSA-TSD optimizer (`app.py`) was updated to use the cleaned data, handle online classes, and enforce ITC 2019-style constraints.

---

## 1. Overview of Changes

The optimizer (`app.py`) was updated to:
1. Use the **cleaned input** (`Algorithm_Input_Cleaned.xlsx`) with all 755 class meetings preserved
2. Support **online class detection** via the `Mode` column
3. Use a **variable-length encoding** (online classes need fewer decision variables)
4. Enforce all **3 hard constraints** and **5 soft constraints** from the ITC 2019-inspired framework
5. Run **post-optimization validation** using `validate_schedule.py` for independent verification

---

## 2. Solution Encoding

### 2.1 Previous Encoding (Before Changes)

Every class received exactly 2 continuous variables:
- Variable 1: timeslot index (decoded from [0,1] to discrete timeslot)
- Variable 2: room index (decoded from [0,1] to discrete room)

**Problem:** Online classes (26% of meetings) don't need a room, but the old encoding still assigned them one, wasting search space and potentially creating false room conflicts.

### 2.2 New Mode-Aware Encoding

| Class Type | Variables | What They Encode |
|-----------|----------|-----------------|
| Face-to-face | 2 | timeslot index + room index |
| Online | 1 | timeslot index only |

**Dimensionality:**
```
dim = num_f2f * 2 + num_online * 1
    = 553 * 2 + 202 * 1
    = 1106 + 202
    = 1308 decision variables
```

Compare to the old encoding: `755 * 2 = 1510` variables. The new encoding reduces the search space by 202 dimensions.

### 2.3 Variable Mapping

Each class `i` has a `var_offsets[i] = (ts_offset, rm_offset_or_None)`:
- **Face-to-face:** `(idx, idx+1)` — two consecutive variables
- **Online:** `(idx, None)` — one variable, room is always `"ONLINE"`

The `decode_schedule()` function maps the continuous vector `x` to a concrete schedule:
```python
ts_idx = int(clip(x[ts_offset] * num_timeslots, 0, num_timeslots - 1))
if rm_offset is not None:
    rm_idx = int(clip(x[rm_offset] * num_rooms, 0, num_rooms - 1))
    room_name = rooms[rm_idx]
else:
    rm_idx = -1
    room_name = "ONLINE"
```

---

## 3. Timeslot Grid

The optimizer uses a fixed grid of 60 timeslots (6 days x 10 periods):

| Days | Monday through Saturday (6 days) |
|------|----------------------------------|
| Periods | 07:00-08:30, 08:30-10:00, 10:00-11:30, 11:30-01:00, 01:00-02:30, 02:30-04:00, 04:00-05:30, 05:30-07:00, 07:00-08:30, 08:30-10:00 |

Each period is 90 minutes. While the original CITC schedule has variable-length classes (60, 90, 120, 180 min), the optimizer assigns each meeting to a single 90-minute slot for tractability. The post-optimization validator uses the assigned time strings for overlap checking.

---

## 4. Objective Function

The objective function `calculate_conflicts(x)` returns a single scalar that the ETFCSA-TSD algorithm minimizes:

```
fitness = hard_penalty + soft_penalty
```

### 4.1 Hard Constraints (Integer Penalties)

Each hard violation adds exactly **1.0** to the fitness. These must reach zero for feasibility.

| ID | Constraint | Detection Method |
|----|-----------|-----------------|
| H1 | Room Conflict | Two face-to-face classes assigned to the same `(room, timeslot)` pair. Online classes are excluded. |
| H2 | Instructor Conflict | Two classes with the same instructor assigned to the same timeslot. Classes with missing/unknown instructors are excluded. |
| H3 | Section Conflict | Two classes in the same section assigned to the same timeslot. |

### 4.2 Soft Constraints (Weighted Penalties)

Each soft violation adds its **weight** to the fitness. Weights are configurable via the sidebar.

| ID | Constraint | Default Weight | Detection Method |
|----|-----------|---------------|-----------------|
| S1 | Room Type Mismatch | 0.5 | Lab subject assigned to a non-lab room (face-to-face only) |
| S2 | Section Daily Overload | 0.3 | Section has > 5 classes in one day; penalty = weight x (count - 5) |
| S3 | Instructor Daily Overload | 0.3 | Instructor teaches > 5 classes in one day; penalty = weight x (count - 5) |
| S4 | Schedule Gap | 0.2 | Gap > 2 hours between consecutive classes for a section on the same day |
| S5 | Late Class | 0.1 | Class starts at or after 6:00 PM (start_min >= 1080) |

### 4.3 Why Soft Weights Are Less Than 1.0

Hard constraints use a weight of 1.0. By keeping soft weights below 1.0, the optimizer **always prioritizes eliminating hard violations** over improving soft quality. This ensures the algorithm first achieves feasibility, then optimizes for quality — matching the ITC 2019 two-tier evaluation philosophy.

### 4.4 Online Class Handling in the Objective

| Constraint | Online Classes |
|-----------|---------------|
| H1: Room Conflict | **Excluded** (no room assigned) |
| H2: Instructor Conflict | **Included** (instructor still committed) |
| H3: Section Conflict | **Included** (students still attend) |
| S1: Room Type Mismatch | **Excluded** (no room to check) |
| S2-S5: All other soft | **Included** |

This matches the validation framework behavior documented in `validation_documentation.md`.

---

## 5. Post-Optimization Validation

After optimization, the app runs **independent validation** using `validate_schedule.py` — the same validator used on the initial CITC schedule. This provides:

1. **Independent verification** — the validation code is separate from the optimizer, preventing circular reasoning
2. **Detailed breakdown** — per-constraint violation counts and descriptions
3. **Downloadable report** — full validation report as a text file

The optimized schedule is converted to the same DataFrame format as the initial schedule (columns: Day, Time, Subject, Room, Instructor, Section), with `Room=None` for online classes. This ensures the validator applies the exact same rules to both initial and optimized schedules, making the comparison fair.

### 5.1 Expected Improvement

| Metric | Initial (Department) Schedule | Target (Optimized) |
|--------|------------------------------|---------------------|
| Hard violations | 380 | 0 (feasible) |
| Soft violations | 245 | Minimized |
| Feasibility | INFEASIBLE | FEASIBLE |

---

## 6. Algorithm Parameters

The ETFCSA-TSD algorithm (`tsd.py`) was **not modified**. It is a generic population-based metaheuristic that accepts any objective function. The scheduling-specific logic is entirely in `app.py`.

| Parameter | Default | Description |
|-----------|---------|-------------|
| Population Size (N) | 200 | Number of candidate solutions |
| Max Evaluations | 150,000 | Termination criterion |
| Clone Rate (n_clones) | 10 | Clones per selected antibody |
| Substrate Decay (rho) | 0.98 | TSD decay rate for temporal substrate |
| c_threshold | 3.0 | Concentration threshold for suppression |
| eta | 0.25 | Mutation scaling parameter |

---

## 7. Output Formats

The optimizer produces two output formats:

### 7.1 Excel Output
- `Optimized_Schedule.xlsx` with:
  - `ALL_CLASSES` sheet: all 755 meetings sorted by department, section, day, time
  - One sheet per section (100 sheets): that section's meetings only
  - Columns: Department, Section, Subject, Instructor, Day, Time, Room

### 7.2 ITC 2019 XML Output
- Follows the ITC 2019 solution format for reference
- Maps days to binary strings, times to 5-minute slot indices
- Online classes get `room="0"` in the XML

---

## 8. User Interface

The Streamlit app is organized into 5 sections:

### Section 1: Upload
- File uploader for `Algorithm_Input_Cleaned.xlsx`
- Displays class count breakdown (face-to-face vs online) and room count on load

### Section 2: Optimizing Schedule
- Shows problem size (classes, variables, rooms, timeslots)
- Live progress bar with evaluation count
- Completion banner with final fitness and runtime

### Section 3: Schedule Validation (ITC 2019-Style)
- **Feasibility banner** — green (FEASIBLE) or red (INFEASIBLE) status
- **Results overview** — fitness, hard violations, soft violations, runtime in a 4-column row
- **Before vs After** comparison — delta metrics against the initial CITC schedule baseline (380 hard, 245 soft, INFEASIBLE)
- **Hard constraint breakdown** — 3 columns (H1/H2/H3) with color-coded counts and expandable violation details
- **Soft constraint breakdown** — 5 columns (S1-S5) showing violation count or "DISABLED" if weight=0, with expandable details
- **Active weights** displayed above soft constraints so the user knows which were used
- **Algorithm Parameters Used** — collapsible section showing N, max_evals, clones, rho

### Section 4: Download Output
- **Excel download** (`Optimized_Schedule.xlsx`) — ALL_CLASSES sheet + one sheet per section
- **ITC 2019 XML download** — solution in ITC 2019 format
- **Validation report download** — full text report from `validate_schedule.py`
- Expandable XML viewer

### Section 5: ITC 2019 API Validation (Optional)
- Requires ITC credentials in sidebar
- Sends XML to official ITC 2019 validator and displays results

### Sidebar Controls
- **Algorithm Parameters:** Population (N), Max Evaluations, Clone Rate, Substrate Decay (rho)
- **Constraint Weights:** S1-S5 sliders (0.0 to 5.0, 0 = disabled)
- **ITC 2019 Metadata:** Author, Institution, Instance Name
- **ITC API Credentials:** Email and Password

---

## 9. Run Logging

After each optimization run, a log file is automatically saved to the `logs/` directory with the filename format `run_YYYYMMDD_HHMMSS.log`. Each log contains:

- **Timestamp and runtime**
- **Algorithm parameters** (N, max_evals, n_clones, rho, soft weights)
- **Problem size** (total classes, f2f/online split, variables, rooms, timeslots)
- **Validation results** (feasibility, hard violation breakdown by H1/H2/H3, soft violation breakdown by S1-S5)

This allows comparison across multiple runs with different parameter settings to identify the best configuration for the CITC timetabling problem.

**Example log output:**
```
=== ETFCSA-TSD Optimization Log ===
Timestamp   : 2026-03-15 14:30:00
Runtime     : 1313.20s
Final Fitness: 211.60

--- Parameters ---
Population  : 300
Max Evals   : 500000
...

--- Validation Results ---
Feasibility  : INFEASIBLE
Hard Violations: 72
  H1: Room Conflict: 30
  H2: Instructor Conflict: 35
  H3: Section Conflict: 7
Soft Violations: 139
  ...
```

---

## 10. How to Run

```bash
# Ensure cleaned data exists
python preprocess.py

# Run the optimizer
streamlit run app.py
```

Then:
1. Upload `cleaned/Algorithm_Input_Cleaned.xlsx`
2. Adjust algorithm parameters and soft constraint weights in sidebar
3. Click "Run Optimization"
4. Review validation results in Section 3 (before vs after comparison, hard/soft breakdown)
5. Download the optimized schedule in Section 4
6. Check `logs/` folder for the auto-saved run log
