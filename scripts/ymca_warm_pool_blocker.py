import sys
import json
import re
from datetime import datetime
import urllib.request

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

class YmcaPoolScheduleManager:
    """
    Manages schedule parsing and calendar blocking for the Rose E. Schneider Family YMCA pools.
    """
    API_URL = "https://groupexpro.com/schedule/embed/json_schedule.php?schedule&instructor_id=true&format=json&a=793&location=3827"
    
    def __init__(self, target_studio="Warm Water Pool"):
        self.target_studio = target_studio.lower()
        self.classes = []

    def fetch_schedule(self):
        headers = {
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://bcfymca.org/schedules-guides-rose-e-schneider-family-ymca"
        }
        req = urllib.request.Request(self.API_URL, headers=headers)
        raw = urllib.request.urlopen(req).read().decode("utf-8", errors="ignore")
        
        # Clean JSONP wrapper if present
        clean = re.sub(r'^[a-zA-Z0-9_]+\s*\(\s*', '', raw.strip())
        clean = re.sub(r'\s*\)\s*;?$', '', clean)
        data = json.loads(clean)
        
        aaData = data.get("aaData", [])
        self.classes = []

        for row in aaData:
            # Columns: [0: Date, 1: Time, 2: Name, 3: Desc, 4: Studio, 5: Category, 6: Instructor, 7: Duration, ...]
            studio = row[4] if len(row) > 4 else ""
            if self.target_studio in studio.lower():
                date_str = row[0].strip()           # e.g. "Monday, November 2, 2026"
                time_range = row[1].strip()         # e.g. "9:00am-10:00am"
                class_name = row[2].strip()
                # Clean html tags from instructor
                instructor_raw = row[6] if len(row) > 6 else ""
                instructor = re.sub(r'<[^>]+>', ' ', instructor_raw).strip()
                duration = row[7] if len(row) > 7 else ""

                # Parse start & end datetimes
                # time_range like "8:00am-9:00am" or "11:15am-12:15pm"
                times = time_range.split("-")
                start_dt, end_dt = None, None
                if len(times) == 2:
                    try:
                        # Full date string parse
                        s_str = f"{date_str} {times[0].strip().upper()}"
                        e_str = f"{date_str} {times[1].strip().upper()}"
                        start_dt = datetime.strptime(s_str, "%A, %B %d, %Y %I:%M%p")
                        end_dt = datetime.strptime(e_str, "%A, %B %d, %Y %I:%M%p")
                    except Exception:
                        pass

                self.classes.append({
                    "date": date_str,
                    "time": time_range,
                    "name": class_name,
                    "instructor": instructor,
                    "duration_mins": duration,
                    "studio": studio.replace("&nbsp;", "").strip(),
                    "start_dt": start_dt,
                    "end_dt": end_dt
                })
        return self.classes

    def get_calendar_blocks(self):
        """
        Converts occupied pool time slots into calendar busy block objects.
        """
        blocks = []
        for c in self.classes:
            blocks.append({
                "summary": f"Busy: Warm Pool Occupied ({c['name']})",
                "description": f"Class: {c['name']}\nStudio: {c['studio']}\nInstructor: {c['instructor']}",
                "start": c["start_dt"].isoformat() if c["start_dt"] else c["time"],
                "end": c["end_dt"].isoformat() if c["end_dt"] else c["time"],
                "location": "Rose E. Schneider Family YMCA - Warm Water Pool",
                "busy": True
            })
        return blocks

    def check_conflict(self, proposed_start: datetime, proposed_end: datetime):
        """
        Checks if a proposed swimming lesson conflicts with any warm pool class.
        """
        conflicts = []
        for c in self.classes:
            if c["start_dt"] and c["end_dt"]:
                # Conflict condition: max(start1, start2) < min(end1, end2)
                if max(proposed_start, c["start_dt"]) < min(proposed_end, c["end_dt"]):
                    conflicts.append(c)
        return conflicts

if __name__ == "__main__":
    mgr = YmcaPoolScheduleManager(target_studio="Warm Water Pool")
    classes = mgr.fetch_schedule()
    print(f"Retrieved {len(classes)} classes for Warm Water Pool.\n")

    # Group by Day for clean summary
    by_day = {}
    for c in classes:
        by_day.setdefault(c["date"], []).append(c)

    for day, items in sorted(by_day.items(), key=lambda x: x[1][0]["start_dt"] if x[1][0]["start_dt"] else datetime.min):
        print(f"📅 {day}:")
        for it in items:
            print(f"   🚫 {it['time']:<17} | {it['name']:<28} | Inst: {it['instructor']}")
        print()

    # Demonstration of conflict check
    print("=" * 60)
    print("VERIFYING LESSON CONFLICTS EXAMPLE:")
    test_start = datetime(2026, 11, 2, 9, 30)  # Monday 9:30 AM
    test_end = datetime(2026, 11, 2, 10, 15)    # Monday 10:15 AM
    print(f"Checking slot: {test_start.strftime('%A, %b %d %I:%M%p')} - {test_end.strftime('%I:%M%p')}")
    conflicts = mgr.check_conflict(test_start, test_end)
    if conflicts:
        print("❌ Cannot sign up! Conflict detected:")
        for cf in conflicts:
            print(f"   -> Occupied by '{cf['name']}' ({cf['time']})")
    else:
        print("✅ Warm Pool is free at this time!")

    test_start2 = datetime(2026, 11, 2, 13, 0) # Monday 1:00 PM
    test_end2 = datetime(2026, 11, 2, 14, 0)   # Monday 2:00 PM
    print(f"\nChecking slot: {test_start2.strftime('%A, %b %d %I:%M%p')} - {test_end2.strftime('%I:%M%p')}")
    conflicts2 = mgr.check_conflict(test_start2, test_end2)
    if conflicts2:
        print("❌ Cannot sign up! Conflict detected:")
    else:
        print("✅ Warm Pool is free at this time! Available for swimming lesson signup.")
