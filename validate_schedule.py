"""
validate_schedule.py - ITC 2019-Style Schedule Validator for CITC Timetabling

Validates a schedule (initial or optimized) against hard and soft constraints
using methodology inspired by the International Timetabling Competition 2019.

Since the CITC data is not an official ITC instance, we define constraints
applicable to the university's real-world scheduling needs.

Usage:
  python validate_schedule.py                          # validate cleaned CITC schedule
  python validate_schedule.py path/to/schedule.xlsx    # validate a specific schedule

Output:
  - Console report with constraint-by-constraint breakdown
  - validation_report.txt saved alongside the input file
"""

import os
import sys
import re
import pandas as pd
from collections import defaultdict
from dataclasses import dataclass, field


# ─────────────────────────────────────────────────────────────
# TIME PARSING UTILITIES
# ─────────────────────────────────────────────────────────────

def parse_time_to_minutes(time_str: str) -> int | None:
    """Convert '07:00 AM' or '07:00 PM' to minutes since midnight."""
    if pd.isna(time_str):
        return None
    m = re.match(r"(\d{1,2}):(\d{2})\s*([AP]M)", str(time_str).strip(), re.IGNORECASE)
    if not m:
        return None
    h, mi, period = int(m.group(1)), int(m.group(2)), m.group(3).upper()
    if period == "PM" and h != 12:
        h += 12
    if period == "AM" and h == 12:
        h = 0
    return h * 60 + mi


def parse_time_range(time_str: str) -> tuple[int, int] | None:
    """
    Parse a time string into (start_minutes, end_minutes).
    Handles:
      - '07:00 AM - 08:30 AM' -> (420, 510)
      - '07:00 AM' (bare, no end) -> (420, 480)  # assume 1 hour
    Returns None if unparseable.
    """
    if pd.isna(time_str):
        return None

    s = str(time_str).strip()

    # Range format: 'HH:MM AM - HH:MM PM'
    m = re.match(
        r"(\d{1,2}:\d{2}\s*[AP]M)\s*-\s*(\d{1,2}:\d{2}\s*[AP]M)",
        s, re.IGNORECASE,
    )
    if m:
        start = parse_time_to_minutes(m.group(1))
        end = parse_time_to_minutes(m.group(2))
        if start is not None and end is not None:
            # Fix likely AM/PM error (e.g., '12:00 AM - 03:30 PM' = 930 min)
            if end - start > 300:  # > 5 hours is suspicious
                # Likely '12:00 AM' should be '12:00 PM'
                if start < 360:  # before 6 AM
                    start += 720  # flip AM->PM
            return (start, end)

    # Bare time: 'HH:MM AM' — assume 1-hour duration
    bare = parse_time_to_minutes(s)
    if bare is not None:
        return (bare, bare + 60)

    return None


def times_overlap(range1: tuple[int, int], range2: tuple[int, int]) -> bool:
    """Check if two (start, end) minute ranges overlap."""
    return range1[0] < range2[1] and range2[0] < range1[1]


def minutes_to_timestr(mins: int) -> str:
    """Convert minutes since midnight to 'HH:MM AM/PM'."""
    h = mins // 60
    m = mins % 60
    period = "AM" if h < 12 else "PM"
    h12 = h if 1 <= h <= 12 else (h - 12 if h > 12 else 12)
    return f"{h12:02d}:{m:02d} {period}"


# ─────────────────────────────────────────────────────────────
# ROOM TYPE CLASSIFICATION
# ─────────────────────────────────────────────────────────────

def is_online(row) -> bool:
    """
    Determine if a class meeting is online (no physical room needed).
    A meeting is online if its Room field is NaN/empty.
    Online meetings still participate in instructor and section conflict
    checking but are excluded from room conflict and room type checks.
    """
    if isinstance(row, dict):
        room = row.get("Room")
    else:
        room = row.get("Room") if hasattr(row, "get") else None
    return pd.isna(room) or str(room).strip() == ""


def classify_room(room_name: str) -> str:
    """Classify a room as 'lab', 'lecture', or 'other' based on its name."""
    if pd.isna(room_name):
        return "unknown"
    r = str(room_name).lower()
    if "lab" in r or "cadd" in r or "cisco" in r:
        return "lab"
    if "lec" in r or "classroom" in r:
        return "lecture"
    if "gym" in r:
        return "gym"
    return "other"


# Lab subjects identified from CITC SCHED room assignment patterns.
# These subjects were consistently placed in lab rooms in the original schedule.
LAB_SUBJECTS = {
    "CS122", "CS222", "CS321", "CS323", "CS325", "CS326", "CS422", "CS423",
    "DS121", "DS123", "DS221", "DS222", "DS223", "DS224", "DS322",
    "IT121", "IT122", "IT222", "IT223", "IT224", "IT322", "IT323", "IT324",
    "IT325", "IT421", "IT413a",
}


# ─────────────────────────────────────────────────────────────
# VIOLATION DATA STRUCTURES
# ─────────────────────────────────────────────────────────────

@dataclass
class Violation:
    constraint: str     # constraint name
    severity: str       # 'hard' or 'soft'
    description: str    # human-readable description
    entries: list = field(default_factory=list)  # involved rows


@dataclass
class ValidationReport:
    schedule_name: str
    total_meetings: int
    hard_violations: list = field(default_factory=list)
    soft_violations: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    stats: dict = field(default_factory=dict)

    @property
    def hard_count(self) -> int:
        return len(self.hard_violations)

    @property
    def soft_penalty(self) -> int:
        return len(self.soft_violations)

    @property
    def is_feasible(self) -> bool:
        return self.hard_count == 0


# ─────────────────────────────────────────────────────────────
# CONSTRAINT CHECKS
# ─────────────────────────────────────────────────────────────

def load_schedule(path: str) -> pd.DataFrame:
    """Load a schedule Excel file (multi-sheet, one per section) into one DataFrame."""
    xls = pd.ExcelFile(path)
    frames = []
    for sheet in xls.sheet_names:
        df = pd.read_excel(xls, sheet_name=sheet)
        keep = [c for c in df.columns if not c.startswith("Unnamed")]
        df = df[keep].copy()
        if "Section" not in df.columns:
            df["Section"] = sheet
        frames.append(df)
    combined = pd.concat(frames, ignore_index=True)
    return combined


def check_room_conflicts(df: pd.DataFrame) -> list[Violation]:
    """H1: No two classes in the same room at overlapping times on the same day."""
    violations = []
    # Group by (Room, Day)
    valid = df.dropna(subset=["Room", "Day", "Time"]).copy()
    valid["_time_range"] = valid["Time"].apply(parse_time_range)
    valid = valid[valid["_time_range"].notna()]

    for (room, day), group in valid.groupby(["Room", "Day"]):
        entries = group.to_dict("records")
        for i in range(len(entries)):
            for j in range(i + 1, len(entries)):
                r1 = entries[i]["_time_range"]
                r2 = entries[j]["_time_range"]
                if times_overlap(r1, r2):
                    violations.append(Violation(
                        constraint="H1: Room Conflict",
                        severity="hard",
                        description=(
                            f"Room '{room}' on {day}: "
                            f"'{entries[i].get('Subject','')}' ({entries[i].get('Section','')}) [{entries[i]['Time']}] "
                            f"overlaps with "
                            f"'{entries[j].get('Subject','')}' ({entries[j].get('Section','')}) [{entries[j]['Time']}]"
                        ),
                        entries=[entries[i], entries[j]],
                    ))
    return violations


def check_instructor_conflicts(df: pd.DataFrame) -> list[Violation]:
    """H2: No instructor can teach two classes at overlapping times on the same day."""
    violations = []
    valid = df.dropna(subset=["Instructor", "Day", "Time"]).copy()
    # Skip unknown instructors
    valid = valid[~valid["Instructor"].str.upper().isin(["NAN", "NONE", "NO TEACHER", "UNKNOWN"])]
    valid["_time_range"] = valid["Time"].apply(parse_time_range)
    valid = valid[valid["_time_range"].notna()]

    for (inst, day), group in valid.groupby(["Instructor", "Day"]):
        entries = group.to_dict("records")
        for i in range(len(entries)):
            for j in range(i + 1, len(entries)):
                r1 = entries[i]["_time_range"]
                r2 = entries[j]["_time_range"]
                if times_overlap(r1, r2):
                    violations.append(Violation(
                        constraint="H2: Instructor Conflict",
                        severity="hard",
                        description=(
                            f"Instructor '{inst}' on {day}: "
                            f"'{entries[i].get('Subject','')}' ({entries[i].get('Section','')}) [{entries[i]['Time']}] "
                            f"overlaps with "
                            f"'{entries[j].get('Subject','')}' ({entries[j].get('Section','')}) [{entries[j]['Time']}]"
                        ),
                        entries=[entries[i], entries[j]],
                    ))
    return violations


def check_section_conflicts(df: pd.DataFrame) -> list[Violation]:
    """H3: No section can have two classes at overlapping times on the same day."""
    violations = []
    valid = df.dropna(subset=["Section", "Day", "Time"]).copy()
    valid["_time_range"] = valid["Time"].apply(parse_time_range)
    valid = valid[valid["_time_range"].notna()]

    for (sec, day), group in valid.groupby(["Section", "Day"]):
        entries = group.to_dict("records")
        for i in range(len(entries)):
            for j in range(i + 1, len(entries)):
                r1 = entries[i]["_time_range"]
                r2 = entries[j]["_time_range"]
                if times_overlap(r1, r2):
                    violations.append(Violation(
                        constraint="H3: Section Conflict",
                        severity="hard",
                        description=(
                            f"Section '{sec}' on {day}: "
                            f"'{entries[i].get('Subject','')}' [{entries[i]['Time']}] "
                            f"overlaps with "
                            f"'{entries[j].get('Subject','')}' [{entries[j]['Time']}]"
                        ),
                        entries=[entries[i], entries[j]],
                    ))
    return violations


def check_room_type_mismatch(df: pd.DataFrame) -> list[Violation]:
    """S1: Lab subjects should be assigned to lab rooms.
    Online meetings are excluded — they have no room to check."""
    violations = []
    # Only check face-to-face meetings (those with a room assigned)
    valid = df.dropna(subset=["Room", "Subject"]).copy()

    for _, row in valid.iterrows():
        subj = str(row["Subject"]).strip()
        room = str(row["Room"]).strip()
        room_type = classify_room(room)

        if subj in LAB_SUBJECTS and room_type not in ("lab", "unknown"):
            violations.append(Violation(
                constraint="S1: Room Type Mismatch",
                severity="soft",
                description=(
                    f"Lab subject '{subj}' ({row.get('Section','')}) assigned to "
                    f"non-lab room '{room}' (type: {room_type})"
                ),
                entries=[row.to_dict()],
            ))
    return violations


def check_daily_load(df: pd.DataFrame, max_per_section: int = 5) -> list[Violation]:
    """S2: Sections should not have more than max_per_section classes per day."""
    violations = []
    valid = df.dropna(subset=["Section", "Day"]).copy()

    for (sec, day), group in valid.groupby(["Section", "Day"]):
        if len(group) > max_per_section:
            violations.append(Violation(
                constraint="S2: Section Daily Overload",
                severity="soft",
                description=(
                    f"Section '{sec}' has {len(group)} classes on {day} "
                    f"(max recommended: {max_per_section})"
                ),
            ))
    return violations


def check_instructor_daily_load(df: pd.DataFrame, max_per_instructor: int = 5) -> list[Violation]:
    """S3: Instructors should not teach more than max_per_instructor classes per day."""
    violations = []
    valid = df.dropna(subset=["Instructor", "Day"]).copy()
    valid = valid[~valid["Instructor"].str.upper().isin(["NAN", "NONE", "NO TEACHER", "UNKNOWN"])]

    for (inst, day), group in valid.groupby(["Instructor", "Day"]):
        if len(group) > max_per_instructor:
            violations.append(Violation(
                constraint="S3: Instructor Daily Overload",
                severity="soft",
                description=(
                    f"Instructor '{inst}' has {len(group)} classes on {day} "
                    f"(max recommended: {max_per_instructor})"
                ),
            ))
    return violations


def check_compactness(df: pd.DataFrame, max_gap_minutes: int = 120) -> list[Violation]:
    """S4: Minimize idle gaps in a section's daily schedule.
    Flags gaps larger than max_gap_minutes between consecutive classes."""
    violations = []
    valid = df.dropna(subset=["Section", "Day", "Time"]).copy()
    valid["_time_range"] = valid["Time"].apply(parse_time_range)
    valid = valid[valid["_time_range"].notna()]

    for (sec, day), group in valid.groupby(["Section", "Day"]):
        if len(group) < 2:
            continue
        ranges = sorted(group["_time_range"].tolist(), key=lambda x: x[0])
        for i in range(len(ranges) - 1):
            gap = ranges[i + 1][0] - ranges[i][1]
            if gap > max_gap_minutes:
                violations.append(Violation(
                    constraint="S4: Schedule Gap",
                    severity="soft",
                    description=(
                        f"Section '{sec}' on {day}: {gap} min gap between "
                        f"class ending at {minutes_to_timestr(ranges[i][1])} and "
                        f"class starting at {minutes_to_timestr(ranges[i+1][0])}"
                    ),
                ))
    return violations


def check_late_classes(df: pd.DataFrame, late_threshold: int = 1080) -> list[Violation]:
    """S5: Penalize classes scheduled after the threshold (default 6:00 PM = 1080 min)."""
    violations = []
    valid = df.dropna(subset=["Time"]).copy()
    valid["_time_range"] = valid["Time"].apply(parse_time_range)
    valid = valid[valid["_time_range"].notna()]

    for _, row in valid.iterrows():
        start = row["_time_range"][0]
        if start >= late_threshold:
            violations.append(Violation(
                constraint="S5: Late Class",
                severity="soft",
                description=(
                    f"'{row.get('Subject','')}' ({row.get('Section','')}) on {row.get('Day','')} "
                    f"starts at {minutes_to_timestr(start)} (after 06:00 PM)"
                ),
            ))
    return violations


def check_missing_data(df: pd.DataFrame) -> list[str]:
    """Report missing data as warnings."""
    warnings = []
    nan_rooms = df["Room"].isna().sum() if "Room" in df.columns else 0
    nan_inst = df["Instructor"].isna().sum() if "Instructor" in df.columns else 0
    nan_subj = df["Subject"].isna().sum() if "Subject" in df.columns else 0
    nan_time = df["Time"].isna().sum() if "Time" in df.columns else 0
    nan_day = df["Day"].isna().sum() if "Day" in df.columns else 0

    if nan_rooms:
        warnings.append(f"W1: {nan_rooms} class meetings have no room assigned (classified as online)")
    if nan_inst:
        warnings.append(f"W2: {nan_inst} class meetings have no instructor assigned")
    if nan_subj:
        warnings.append(f"W3: {nan_subj} class meetings have no subject assigned")
    if nan_time:
        warnings.append(f"W4: {nan_time} class meetings have no time assigned")
    if nan_day:
        warnings.append(f"W5: {nan_day} class meetings have no day assigned")

    # Check unparseable times
    if "Time" in df.columns:
        unparseable = 0
        for t in df["Time"].dropna():
            if parse_time_range(str(t)) is None:
                unparseable += 1
        if unparseable:
            warnings.append(f"W6: {unparseable} time values could not be parsed")

    return warnings


def compute_stats(df: pd.DataFrame) -> dict:
    """Compute summary statistics."""
    online_count = df["Room"].isna().sum() if "Room" in df.columns else 0
    f2f_count = len(df) - online_count
    stats = {
        "total_meetings": len(df),
        "face-to-face_meetings": f2f_count,
        "online_meetings": online_count,
        "sections": df["Section"].nunique() if "Section" in df.columns else 0,
        "subjects": df["Subject"].dropna().nunique() if "Subject" in df.columns else 0,
        "instructors": df["Instructor"].dropna().nunique() if "Instructor" in df.columns else 0,
        "rooms_used": df["Room"].dropna().nunique() if "Room" in df.columns else 0,
        "days_used": df["Day"].dropna().nunique() if "Day" in df.columns else 0,
    }
    return stats


# ─────────────────────────────────────────────────────────────
# MAIN VALIDATION
# ─────────────────────────────────────────────────────────────

def validate(df: pd.DataFrame, schedule_name: str = "Schedule") -> ValidationReport:
    """Run all constraint checks and return a ValidationReport."""
    report = ValidationReport(
        schedule_name=schedule_name,
        total_meetings=len(df),
    )

    # Hard constraints
    report.hard_violations.extend(check_room_conflicts(df))
    report.hard_violations.extend(check_instructor_conflicts(df))
    report.hard_violations.extend(check_section_conflicts(df))

    # Soft constraints
    report.soft_violations.extend(check_room_type_mismatch(df))
    report.soft_violations.extend(check_daily_load(df))
    report.soft_violations.extend(check_instructor_daily_load(df))
    report.soft_violations.extend(check_compactness(df))
    report.soft_violations.extend(check_late_classes(df))

    # Warnings
    report.warnings = check_missing_data(df)

    # Stats
    report.stats = compute_stats(df)

    return report


def format_report(report: ValidationReport) -> str:
    """Format a ValidationReport as a readable string."""
    lines = []
    sep = "=" * 70
    lines.append(sep)
    lines.append(f"  VALIDATION REPORT: {report.schedule_name}")
    lines.append(sep)

    # Stats
    lines.append(f"\n  Schedule Statistics:")
    for k, v in report.stats.items():
        label = k.replace("_", " ").title()
        lines.append(f"    {label:30s}: {v}")

    lines.append(f"\n  Note: Online meetings (no room) are excluded from room conflict")
    lines.append(f"  and room type checks, but still checked for instructor/section conflicts.")

    # Feasibility
    lines.append(f"\n  {'='*50}")
    if report.is_feasible:
        lines.append(f"  FEASIBILITY: FEASIBLE (0 hard constraint violations)")
    else:
        lines.append(f"  FEASIBILITY: INFEASIBLE ({report.hard_count} hard constraint violations)")
    lines.append(f"  SOFT PENALTY: {report.soft_penalty} soft constraint violations")
    lines.append(f"  {'='*50}")

    # Hard constraint breakdown
    hard_groups = defaultdict(list)
    for v in report.hard_violations:
        hard_groups[v.constraint].append(v)

    lines.append(f"\n  --- HARD CONSTRAINTS ---")
    for cname in ["H1: Room Conflict", "H2: Instructor Conflict", "H3: Section Conflict"]:
        vlist = hard_groups.get(cname, [])
        status = "PASS" if len(vlist) == 0 else f"FAIL ({len(vlist)} violations)"
        lines.append(f"  {cname:35s} {status}")
        for v in vlist[:20]:  # show first 20
            lines.append(f"    - {v.description}")
        if len(vlist) > 20:
            lines.append(f"    ... and {len(vlist) - 20} more")

    # Soft constraint breakdown
    soft_groups = defaultdict(list)
    for v in report.soft_violations:
        soft_groups[v.constraint].append(v)

    lines.append(f"\n  --- SOFT CONSTRAINTS ---")
    for cname in [
        "S1: Room Type Mismatch",
        "S2: Section Daily Overload",
        "S3: Instructor Daily Overload",
        "S4: Schedule Gap",
        "S5: Late Class",
    ]:
        vlist = soft_groups.get(cname, [])
        count = len(vlist)
        lines.append(f"  {cname:35s} {count} violations")
        for v in vlist[:10]:  # show first 10
            lines.append(f"    - {v.description}")
        if len(vlist) > 10:
            lines.append(f"    ... and {len(vlist) - 10} more")

    # Warnings
    if report.warnings:
        lines.append(f"\n  --- WARNINGS ---")
        for w in report.warnings:
            lines.append(f"  {w}")

    lines.append(f"\n{sep}")
    return "\n".join(lines)


def main():
    # Determine input file
    if len(sys.argv) > 1:
        path = sys.argv[1]
    else:
        # Default: validate the cleaned CITC schedule
        base = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(base, "cleaned", "CITC_SCHEDULING_CLEANED.xlsx")

    if not os.path.exists(path):
        print(f"Error: File not found: {path}")
        sys.exit(1)

    name = os.path.basename(path).replace(".xlsx", "")
    print(f"Loading schedule: {path}")
    df = load_schedule(path)
    print(f"Loaded {len(df)} class meetings from {df['Section'].nunique()} sections.\n")

    report = validate(df, schedule_name=name)
    text = format_report(report)
    print(text)

    # Save report
    report_path = os.path.join(os.path.dirname(path), f"{name}_validation_report.txt")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"\nReport saved to: {report_path}")


if __name__ == "__main__":
    main()
