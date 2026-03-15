"""
preprocess.py — Data Quality Preprocessing for CITC Schedule Optimization

Reads the original data files (without modifying them), applies normalization
mappings for instructors, subjects, and rooms, then outputs cleaned copies.

Outputs:
  - cleaned/CITC_SCHEDULING_CLEANED.xlsx   (cleaned initial schedule)
  - cleaned/Algorithm_Input_Cleaned.xlsx    (cleaned optimizer input, derived from CITC SCHED)

Usage:
  python preprocess.py
"""

import os
import pandas as pd
import re

# ─────────────────────────────────────────────────────────────
# PATHS
# ─────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CITC_SCHED_PATH = os.path.join(BASE_DIR, "CITC SCHED", "CITC SCHEDULING.xlsx")
OUTPUT_DIR = os.path.join(BASE_DIR, "cleaned")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# ─────────────────────────────────────────────────────────────
# 1. INSTRUCTOR NORMALIZATION MAP
#
# Built by inspecting the CITC SCHEDULING.xlsx data.
# Each key is a variant spelling; the value is the canonical form.
# Only entries where the same real person appears under multiple
# spellings are included.  Groups confirmed to be DIFFERENT people
# (e.g., Gamayon Candice May ≠ Gamayon Godfrey) are left untouched.
# ─────────────────────────────────────────────────────────────
INSTRUCTOR_MAP: dict[str, str] = {
    # --- Trailing-space / punctuation variants ---
    "Dagaraga, Laurence Murse B. ":  "Dagaraga, Laurence Murse B.",
    "Inte, Geldolin ":               "Inte, Geldolin",
    "Siwagan, Ma. Cynthia Fe V. ":   "Siwagan, Ma. Cynthia Fe V.",

    # --- Typos in first name ---
    "AMPOLITOD, KENJNETH":           "AMPOLITOD, KENNETH",
    "Lumagod, Botham De":            "Lumagod, Jotham De C",
    "Dial, Potal May M.":            "Dial, Petal May M.",
    "Manlanat, Jan Cendred":         "Manlanat, Ian Cendred",
    "Tanog, Meruylyn L.":            "Tanog, Mercylyn L.",
    "Lendio, Kezeia Mae R.":         "Lendio, Kezzia Mae R.",

    # --- Missing / extra middle initial or period ---
    "ALFECHE, MARIFE":               "ALFECHE, MARIFE M",
    "Bagares, May Golda H":          "Bagares, May Golda H.",
    "Cadelina, Wenico G. Jr":        "Cadelina, Wenico G. Jr.",
    "Cantular, Mary Faith B":        "Cantular, Mary Faith B.",
    "Crisologo, Emeline S":          "Crisologo, Emeline S.",
    "Llumuljo, Regh":                "Llumuljo, Regh P.",
    "Llumuljo, Regh P":              "Llumuljo, Regh P.",
    "Luczon, Rhyndi N":              "Luczon, Rhyndi N.",
    "Lumagod, Jotham De":            "Lumagod, Jotham De C",
    "Remotigue, Cristina T":         "Remotigue, Cristina T.",
    "Salva, Kara Frances F":         "Salva, Kara Frances F.",
    "Siwagan, Ma. Cynthia Fe V":     "Siwagan, Ma. Cynthia Fe V.",
    "Sumanpan, Bon Vincent Wilbur O": "Sumanpan, Bon Vincent Wilbur O.",
    "Tan, Quinto, Jr. A Jr":         "Tan, Quinto, Jr. A Jr.",
    "EBALLE, REYNACARMEL A":         "EBALLE, REYNACARMELA",
    "EBALLE, REYNACARMEL A.":        "EBALLE, REYNACARMELA",

    # --- Abbreviation / encoding differences ---
    "DACOSTA, STEPHANIE JEANS":      "DACOSTA, STEPHANIE JEAN S",
    "Montes, Marie Therese":         "Montes, Ma. Jeane Therese",
    "QUINITO, FLORETO TRE":          "QUINITO, FLORETO JR.",
    "TAURAc, RANIAH":                "TAURAC, RANIAH",
}

# ─────────────────────────────────────────────────────────────
# 2. SUBJECT CODE NORMALIZATION MAP
#
# Fixes case inconsistencies and confirmed typos.
# ─────────────────────────────────────────────────────────────
SUBJECT_MAP: dict[str, str] = {
    "NSTP102B":   "NSTP102b",       # case inconsistency
    "TCM326A":    "TCM326a",        # case inconsistency
    "CSI22":      "CS122",          # typo (same instructor Gamayon, same section CS1A)
    "Ethc":       "Ethics",         # abbreviation inconsistency
    "RPH/Rizal":  "RPH",            # merged label → use canonical code
}

# ─────────────────────────────────────────────────────────────
# 3. ROOM NAME NORMALIZATION MAP
#
# Rooms sharing the same physical room number but entered with
# different labels are merged to a single canonical name.
# ─────────────────────────────────────────────────────────────
ROOM_MAP: dict[str, str] = {
    # Same physical room, abbreviated differently
    "09-301 (CADD Lab)":                      "09-301 (CADD Lab 1)",
    "09-303 (ICT Lab3 451)":                  "09-303 (ICT Lab 3)",
    "09-304 (CITC Lab)":                      "09-304 (CITC Lab 4)",
    "09-306 (CITC Lab 6) / 09-404 (ICT AVR2)": "09-306 (CITC Lab 6)",

    # Truncated names
    "19-101 SCIENCE CENTR":                   "19-101 SCIENCE CENTER",
    "19-102 SCIENCE CENTR":                   "19-102 SCIENCE CENTER",
    "23-104 (CITC 21st Center)":              "23-104 (CITC 21st Cen)",
    "23-105 LRC BLDG":                        "23-105 LRC BLDG(LEC)",

    # Missing building label
    "28-104":                                 "28-104 SCIENCE BLDG",
}

# ─────────────────────────────────────────────────────────────
# 4. DEPARTMENT NORMALIZATION (derived from Section_List)
# ─────────────────────────────────────────────────────────────
SECTION_DEPARTMENT: dict[str, str] = {}  # populated at runtime from Section_List


def normalize_str(value, mapping: dict[str, str]) -> str:
    """Apply strip + mapping lookup."""
    if pd.isna(value):
        return value
    v = str(value).strip()
    return mapping.get(v, v)


def load_citc_schedule(path: str) -> pd.DataFrame:
    """Load all section sheets from CITC SCHEDULING.xlsx into one DataFrame."""
    xls = pd.ExcelFile(path)
    frames = []
    for sheet in xls.sheet_names:
        df = pd.read_excel(xls, sheet_name=sheet)
        # Keep only the expected columns (some sheets have extra unnamed cols)
        keep = [c for c in df.columns if not c.startswith("Unnamed")]
        df = df[keep].copy()
        df["Section"] = sheet
        frames.append(df)
    return pd.concat(frames, ignore_index=True)


def normalize_time(time_val) -> str | None:
    """
    Normalize time values to consistent 'HH:MM AM/PM - HH:MM AM/PM' format.
    Handles:
      - Already formatted strings like '07:00 AM - 08:00 AM'
      - Bare time objects/strings like '07:30:00', '17:30:00'
    """
    if pd.isna(time_val):
        return None

    s = str(time_val).strip()

    # Already in 'HH:MM AM/PM - HH:MM AM/PM' format
    if re.match(r"\d{1,2}:\d{2}\s*[AP]M\s*-\s*\d{1,2}:\d{2}\s*[AP]M", s, re.IGNORECASE):
        return s

    # Bare time like '07:30:00' or '17:30:00' (no end time available)
    m = re.match(r"(\d{1,2}):(\d{2})(?::(\d{2}))?$", s)
    if m:
        h, mi = int(m.group(1)), int(m.group(2))
        period = "AM" if h < 12 else "PM"
        h12 = h if 1 <= h <= 12 else (h - 12 if h > 12 else 12)
        return f"{h12:02d}:{mi:02d} {period}"

    # Edge cases like '12:00:00 AM - 3:30 PM' or '11:00:00 AM - 12:30 PM'
    m2 = re.match(
        r"(\d{1,2}:\d{2}(?::\d{2})?)\s*([AP]M)\s*-\s*(\d{1,2}:\d{2}(?::\d{2})?)\s*([AP]M)",
        s, re.IGNORECASE,
    )
    if m2:
        def _fmt(t_str, ampm):
            parts = t_str.split(":")
            h, mi = int(parts[0]), int(parts[1])
            return f"{h:02d}:{mi:02d} {ampm.upper()}"
        return f"{_fmt(m2.group(1), m2.group(2))} - {_fmt(m2.group(3), m2.group(4))}"

    return s  # return as-is if unrecognized


def clean_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Apply all normalization mappings to a DataFrame."""
    df = df.copy()

    if "Instructor" in df.columns:
        df["Instructor"] = df["Instructor"].apply(lambda x: normalize_str(x, INSTRUCTOR_MAP))

    if "Subject" in df.columns:
        df["Subject"] = df["Subject"].apply(lambda x: normalize_str(x, SUBJECT_MAP))

    if "Room" in df.columns:
        df["Room"] = df["Room"].apply(lambda x: normalize_str(x, ROOM_MAP))

    if "Time" in df.columns:
        df["Time"] = df["Time"].apply(normalize_time)

    return df


def classify_meeting_mode(row: pd.Series) -> str:
    """
    Classify a class meeting as 'online' or 'face-to-face' based on room assignment.

    Logic:
      - If the Room field is NaN/empty, the meeting is 'online'.
        This is consistent with the CITC department practice where online classes
        and PE/gym classes (PATH FIT) have no room code in the schedule.
      - Otherwise, the meeting is 'face-to-face'.
    """
    if pd.isna(row.get("Room")) or str(row.get("Room", "")).strip() == "":
        return "online"
    return "face-to-face"


def derive_input_from_schedule(df_sched: pd.DataFrame) -> pd.DataFrame:
    """
    Derive the optimizer input from the cleaned CITC schedule.

    Each row in the CITC schedule is one class *meeting* (e.g., CS121 on Monday,
    CS121 on Friday = 2 rows).  The optimizer needs to schedule every meeting,
    so we preserve all rows — we just strip the Day/Time/Room assignments.

    We add:
      - 'Meeting_Index' column so multi-day classes are distinguishable.
      - 'Mode' column ('online' or 'face-to-face') based on room assignment.
        Online meetings skip room assignment in the optimizer but still
        participate in instructor and section conflict checking.
    """
    # Determine department from section name
    input_refined = os.path.join(BASE_DIR, "Structured_Data_Algorithm_Input_Refined.xlsx")
    if os.path.exists(input_refined):
        df_sec = pd.read_excel(input_refined, sheet_name="Section_List")
        for _, row in df_sec.iterrows():
            SECTION_DEPARTMENT[row["Section"]] = row["Department"]

    rows = []
    # Track meeting index per (Section, Subject, Instructor) group
    meeting_counter: dict[tuple, int] = {}

    for _, row in df_sched.iterrows():
        sec = row.get("Section", "")
        subj = row.get("Subject", "")
        inst = row.get("Instructor", "")
        mode = classify_meeting_mode(row)

        key = (sec, str(subj), str(inst))
        meeting_counter[key] = meeting_counter.get(key, 0) + 1

        dept = SECTION_DEPARTMENT.get(sec, "Unknown")

        rows.append({
            "Department": dept,
            "Section": sec,
            "Subject": subj,
            "Instructor": inst,
            "Meeting_Index": meeting_counter[key],
            "Mode": mode,
        })

    return pd.DataFrame(rows)


def build_room_list(df_sched: pd.DataFrame) -> pd.DataFrame:
    """Extract deduplicated room list from cleaned schedule."""
    rooms = df_sched["Room"].dropna().unique()
    return pd.DataFrame({"Room": sorted(rooms)})


def build_section_list(df_sched: pd.DataFrame) -> pd.DataFrame:
    """Extract section-department mapping."""
    input_refined = os.path.join(BASE_DIR, "Structured_Data_Algorithm_Input_Refined.xlsx")
    if os.path.exists(input_refined):
        return pd.read_excel(input_refined, sheet_name="Section_List")
    # Fallback: derive from schedule sections
    sections = sorted(df_sched["Section"].unique())
    return pd.DataFrame({"Section": sections, "Department": "Unknown"})


def build_instructor_list(df_input: pd.DataFrame) -> pd.DataFrame:
    """Build instructor sheet from cleaned input."""
    cols = ["Instructor", "Subject", "Section", "Department"]
    return df_input[cols].drop_duplicates().sort_values(cols).reset_index(drop=True)


def print_report(df_orig: pd.DataFrame, df_clean: pd.DataFrame):
    """Print a summary of what changed."""
    print("=" * 60)
    print("PREPROCESSING REPORT")
    print("=" * 60)

    # Instructor changes
    if "Instructor" in df_orig.columns:
        orig_inst = df_orig["Instructor"].dropna().nunique()
        clean_inst = df_clean["Instructor"].dropna().nunique()
        print(f"\nInstructors: {orig_inst} unique -> {clean_inst} unique (merged {orig_inst - clean_inst} duplicates)")

    # Subject changes
    if "Subject" in df_orig.columns:
        orig_subj = df_orig["Subject"].dropna().nunique()
        clean_subj = df_clean["Subject"].dropna().nunique()
        print(f"Subjects:    {orig_subj} unique -> {clean_subj} unique (merged {orig_subj - clean_subj} duplicates)")

    # Room changes
    if "Room" in df_orig.columns:
        orig_room = df_orig["Room"].dropna().nunique()
        clean_room = df_clean["Room"].dropna().nunique()
        print(f"Rooms:       {orig_room} unique -> {clean_room} unique (merged {orig_room - clean_room} duplicates)")

    print(f"\nTotal class meetings: {len(df_clean)}")
    print(f"Sections: {df_clean['Section'].nunique()}")
    print(f"NaN Instructors: {df_clean['Instructor'].isna().sum()}")
    print(f"NaN Rooms: {df_clean['Room'].isna().sum()} (online/unassigned)")
    print(f"NaN Subjects: {df_clean['Subject'].isna().sum()}")


def main():
    print("Loading CITC SCHEDULING.xlsx ...")
    df_citc_orig = load_citc_schedule(CITC_SCHED_PATH)

    print("Applying normalization mappings ...")
    df_citc_clean = clean_dataframe(df_citc_orig)

    print_report(df_citc_orig, df_citc_clean)

    # --- Output 1: Cleaned CITC Schedule ---
    out_sched = os.path.join(OUTPUT_DIR, "CITC_SCHEDULING_CLEANED.xlsx")
    with pd.ExcelWriter(out_sched, engine="openpyxl") as writer:
        # Write each section as its own sheet (same structure as original)
        for sec in sorted(df_citc_clean["Section"].unique()):
            df_sec = df_citc_clean[df_citc_clean["Section"] == sec].drop(columns=["Section"])
            safe_name = str(sec)[:31]
            df_sec.to_excel(writer, sheet_name=safe_name, index=False)
    print(f"\n[OK] Saved cleaned schedule -> {out_sched}")

    # --- Output 2: Cleaned Algorithm Input ---
    print("\nDeriving optimizer input from cleaned schedule ...")
    df_input = derive_input_from_schedule(df_citc_clean)
    df_rooms = build_room_list(df_citc_clean)
    df_sections = build_section_list(df_citc_clean)
    df_instructors = build_instructor_list(df_input)

    out_input = os.path.join(OUTPUT_DIR, "Algorithm_Input_Cleaned.xlsx")
    with pd.ExcelWriter(out_input, engine="openpyxl") as writer:
        df_input.to_excel(writer, sheet_name="Class_Requirements", index=False)
        df_rooms.to_excel(writer, sheet_name="Room_List", index=False)
        df_sections.to_excel(writer, sheet_name="Section_List", index=False)
        df_instructors.to_excel(writer, sheet_name="Instructors", index=False)
    print(f"[OK] Saved cleaned input   -> {out_input}")

    # Summary comparison
    f2f = len(df_input[df_input["Mode"] == "face-to-face"])
    online = len(df_input[df_input["Mode"] == "online"])
    print(f"\n{'-'*60}")
    print(f"Original input_refined had:  488 classes (collapsed, some meetings lost)")
    print(f"New cleaned input has:       {len(df_input)} class meetings (all meetings preserved)")
    print(f"  Face-to-face meetings:     {f2f} (need room assignment)")
    print(f"  Online meetings:           {online} (skip room assignment)")
    print(f"Difference:                  {len(df_input) - 488} meetings recovered")
    print(f"Deduplicated rooms:          {len(df_rooms)}")
    print(f"{'-'*60}")


if __name__ == "__main__":
    main()
