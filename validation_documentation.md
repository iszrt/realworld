# Schedule Validation Documentation

**Project:** CITC Department University Course Timetabling using ETFCSA-TSD
**Date:** March 2026
**Purpose:** Document the ITC 2019-inspired validation methodology, the constraints applied, and the validation results for the initial (department-provided) schedule.

---

## 1. Validation Methodology

### 1.1 Why ITC 2019?

The International Timetabling Competition 2019 (ITC 2019) defines a well-established framework for evaluating university course timetables. It categorizes constraints into:

- **Hard constraints** -- must be satisfied for a schedule to be considered *feasible*
- **Soft constraints** -- should be minimized to improve schedule *quality*

Since our CITC schedule is not an official ITC instance (it lacks some data fields like room capacities and student enrollments), we cannot use the official ITC 2019 validator. Instead, we implement an **ITC-inspired validation framework** that applies the same methodology to the constraints we can evaluate with the available data.

### 1.2 Approach

The validator (`validate_schedule.py`) operates on schedule files where each section has a sheet with columns: Day, Time, Subject, Room, Instructor.

For each constraint, the validator:
1. Checks every relevant pair/group of class meetings
2. Uses **actual time overlap detection** (not just timeslot equality) to handle variable-length classes (1h, 2h, 3h)
3. Reports each violation with full context (who, what, when, where)
4. Classifies violations as hard (feasibility) or soft (quality)

---

## 2. Constraints Defined

### 2.1 Hard Constraints (Feasibility)

A schedule is **feasible** if and only if it has zero hard constraint violations.

| ID | Constraint | Definition | ITC 2019 Equivalent |
|----|-----------|-----------|---------------------|
| H1 | **Room Conflict** | No two classes can occupy the same room at overlapping times on the same day | Time & Room Assignment |
| H2 | **Instructor Conflict** | No instructor can be assigned to two classes at overlapping times on the same day | Class Clashes (instructor) |
| H3 | **Section Conflict** | No student section can have two classes at overlapping times on the same day | Class Clashes (students) |

**Note on overlap detection:** Unlike simple timeslot-equality checks, our validator parses actual start and end times and checks for temporal overlap. This is necessary because the CITC schedule has variable class durations (60, 90, 120, 180 minutes), so two classes in different "timeslots" can still overlap.

### 2.2 Soft Constraints (Quality)

Each soft constraint violation adds 1 to the penalty score. Lower is better.

| ID | Constraint | Definition | ITC 2019 Equivalent |
|----|-----------|-----------|---------------------|
| S1 | **Room Type Mismatch** | Lab subjects (identified from historical room assignment patterns) should be assigned to lab-type rooms | Room Preferences |
| S2 | **Section Daily Overload** | A section should not have more than 5 classes in a single day | MaxDayLoad |
| S3 | **Instructor Daily Overload** | An instructor should not teach more than 5 classes in a single day | MaxDayLoad |
| S4 | **Schedule Gap** | Gaps exceeding 2 hours between consecutive classes for a section on the same day | Compactness / MinGap |
| S5 | **Late Class** | Classes starting at or after 6:00 PM | Time Preferences |

### 2.3 Online Class Handling

Class meetings with no room assigned in the original schedule are classified as **online meetings**. These represent virtual classes or PE classes held at outdoor/gym facilities without a formal room code.

**Constraint behavior for online meetings:**

| Constraint | Online Meetings |
|-----------|----------------|
| H1: Room Conflict | **Excluded** (no room to conflict) |
| H2: Instructor Conflict | **Included** (instructor still has a time commitment) |
| H3: Section Conflict | **Included** (students still attend at that time) |
| S1: Room Type Mismatch | **Excluded** (no room to check) |
| S2-S5: All other soft | **Included** |

### 2.4 Data Warnings

These are not constraint violations but flag data quality issues:

| ID | Warning | Meaning |
|----|---------|---------|
| W1 | Missing Room | Class meetings with no room assigned (classified as online) |
| W2 | Missing Instructor | Class meetings with no instructor |
| W3-W6 | Missing Subject/Time/Day, Unparseable Times | Other data gaps |

### 2.4 Constraints NOT Implemented (Insufficient Data)

| Constraint | Reason Not Implemented | Data Needed |
|-----------|----------------------|-------------|
| Room Capacity | No capacity data for rooms | Room capacity column |
| Room Features/Equipment | No feature data | Room features column |
| Instructor Time Preferences | No preference data | Availability matrix |
| Room Unavailability | No unavailability data | Room availability matrix |
| Student-level Conflicts | No individual student enrollment data | Student-course enrollment |
| Travel Time | No building distance data | Campus distance matrix |

---

## 3. Lab Subject Identification

Since the input data does not include a "subject type" flag, we inferred which subjects require lab rooms from the historical assignment patterns in the original CITC schedule:

**Method:** For each subject, we checked which rooms it was assigned to across all sections. Subjects that were *consistently* placed in rooms with "Lab", "CADD", or "Cisco" in their names were classified as lab subjects.

**Lab subjects identified (25):**
CS122, CS222, CS321, CS323, CS325, CS326, CS422, CS423, DS121, DS123, DS221, DS222, DS223, DS224, DS322, IT121, IT122, IT222, IT223, IT224, IT322, IT323, IT324, IT325, IT421, IT413a

**Mixed subjects (appear in both lab and non-lab rooms):** CS121, CS221, CS224, CS225, CS324 -- these are NOT included in the lab requirement to avoid false positives.

---

## 4. Initial Schedule Validation Results

The following results are from validating the **cleaned CITC department schedule** (the original schedule provided by the department, after name normalization).

### 4.1 Summary

| Metric | Value |
|--------|-------|
| Total class meetings | 750 (after removing empty rows) |
| Face-to-face meetings | 553 (checked for room conflicts) |
| Online meetings | 197 (excluded from room checks) |
| Sections | 100 |
| Instructors | 170 |
| Rooms used | 69 |
| **Hard constraint violations** | **380** |
| **Soft constraint violations** | **245** |
| **Feasibility** | **INFEASIBLE** |

### 4.2 Hard Constraint Breakdown

| Constraint | Violations | Analysis |
|-----------|------------|----------|
| H1: Room Conflict | **223** | Extensive room double-booking, especially in popular rooms like '09-201 (CITC Multimedia)' and the CITC Lab rooms. Many TCM and IT sections share rooms at overlapping times. |
| H2: Instructor Conflict | **144** | Many instructors assigned to teach two sections simultaneously. Worst offenders teach NSTP102b and IT-series subjects across multiple sections at the same time. |
| H3: Section Conflict | **13** | Some sections have two classes overlapping (e.g., CS2B has CS223 and CS224 overlapping on Tuesday). |

### 4.3 Soft Constraint Breakdown

| Constraint | Violations | Analysis |
|-----------|------------|----------|
| S1: Room Type Mismatch | 108 | Many lab subjects assigned to regular classrooms or numbered rooms (e.g., 51-xxx rooms). This may reflect real room shortages. |
| S2: Section Daily Overload | 0 | No section exceeds 5 classes per day. |
| S3: Instructor Daily Overload | 5 | 5 instructors teach 6-9 classes in a single day (e.g., DE VILLA, HARRY has 9 classes on Friday). |
| S4: Schedule Gap | 94 | Many sections have 3-5 hour gaps between classes (e.g., CS1A has a 5-hour gap on Friday). |
| S5: Late Class | 38 | 38 class meetings start at 6 PM or later. |

### 4.4 Data Warnings

| Warning | Count |
|---------|-------|
| Missing Room | 197 (26% of meetings) |
| Missing Instructor | 5 |

### 4.5 Key Findings

1. **The original department schedule is infeasible.** It has 380 hard constraint violations, meaning it cannot be executed as-is without conflicts. This establishes a clear motivation for the optimization approach.

2. **Room conflicts dominate (223 of 380 hard violations).** The CITC department has more scheduled class meetings than available room-time slots, leading to extensive double-booking.

3. **Instructor conflicts are severe (144 violations).** This may indicate that some instructors handle multiple sections and the schedule was assembled by separate coordinators without cross-checking.

4. **197 meetings (26%) have no room assigned.** These unassigned rooms contribute to the scheduling difficulty and represent classes that need room allocation.

5. **The schedule has room for significant quality improvement.** 94 compactness violations and 38 late-class penalties indicate poor schedule ergonomics for students and instructors.

---

## 5. Implications for Optimization

These validation results establish:

1. **Baseline metrics** -- the optimizer's output should reduce the 380 hard violations to 0 (feasibility) and minimize the 245 soft violations.

2. **Problem difficulty** -- with 755 meetings, 69 rooms, 170 instructors, and 100 sections across 6 days with variable-length classes, this is a non-trivial combinatorial optimization problem.

3. **The need for the ETFCSA-TSD approach** -- manual scheduling (as demonstrated by the department's current schedule) produces an infeasible result. An automated optimization approach is justified.

---

## 6. How to Use the Validator

### Validate the initial schedule:
```bash
python validate_schedule.py
```
(Defaults to `cleaned/CITC_SCHEDULING_CLEANED.xlsx`)

### Validate any schedule:
```bash
python validate_schedule.py path/to/schedule.xlsx
```

### Output:
- Console printout with full constraint breakdown
- `*_validation_report.txt` saved alongside the input file

### For programmatic use:
```python
from validate_schedule import load_schedule, validate, format_report

df = load_schedule("path/to/schedule.xlsx")
report = validate(df, schedule_name="My Schedule")
print(format_report(report))

# Access individual metrics
print(report.hard_count)    # number of hard violations
print(report.soft_penalty)  # number of soft violations
print(report.is_feasible)   # True/False
```
