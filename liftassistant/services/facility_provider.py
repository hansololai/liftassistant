"""Pluggable Facility & Live Schedule Provider (Decision 6 & Decision 14).
Queries live scheduling systems (GroupEx PRO API) for external facilities
such as the Rose E. Schneider Family YMCA pools and studios on-demand.
"""

from abc import ABC, abstractmethod
from datetime import date, datetime, time, timedelta
import json
import logging
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Tuple
import urllib.request

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class OccupiedWindow(BaseModel):
    """Represents a scheduled class or reservation occupying a facility studio."""
    start_time: datetime
    end_time: datetime
    facility_name: str
    studio: str
    activity_name: str
    instructor: Optional[str] = None
    category: Optional[str] = None
    signup_link: Optional[str] = None


class BaseFacilityProvider(ABC):
    """Abstract provider for querying external facility occupancy."""

    @abstractmethod
    def get_occupied_windows(
        self, target_date: date, studio_filter: Optional[str] = None
    ) -> List[OccupiedWindow]:
        """Return all occupied reservation blocks for a given date and optional studio."""
        pass


class YmcaScheduleProvider(BaseFacilityProvider):
    """Live schedule provider for YMCA facilities via GroupEx PRO API (Decision 6).
    Defaults to Rose E. Schneider Family YMCA (Account 793, Location 3827).
    """

    DEFAULT_ACCOUNT_ID = 793
    DEFAULT_LOCATION_ID = 3827
    API_URL_TEMPLATE = "https://groupexpro.com/schedule/embed/json.php?schedule&a={account_id}&location={location_id}"

    def __init__(
        self,
        account_id: int = DEFAULT_ACCOUNT_ID,
        location_id: int = DEFAULT_LOCATION_ID,
        cache_dir: Optional[Path] = None,
        cache_ttl_hours: int = 4,
    ):
        self.account_id = account_id
        self.location_id = location_id
        self.cache_dir = cache_dir or Path("data") / "cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_file = self.cache_dir / f"groupex_ymca_{location_id}.json"
        self.cache_ttl = timedelta(hours=cache_ttl_hours)
        self._memory_cache: Optional[Dict[str, Any]] = None
        self._memory_cache_time: Optional[datetime] = None

    def _parse_time_str(self, time_str: str) -> Tuple[int, int]:
        """Convert '8:00am' or '12:30pm' to (hour, minute) 24h format."""
        s = time_str.strip().lower()
        is_pm = "pm" in s
        is_am = "am" in s
        clean = s.replace("am", "").replace("pm", "").strip()
        if ":" in clean:
            parts = clean.split(":")
            h = int(parts[0])
            m = int(parts[1])
        else:
            h = int(clean)
            m = 0
        if is_pm and h < 12:
            h += 12
        elif is_am and h == 12:
            h = 0
        return h, m

    def _parse_time_range(self, time_range_str: str) -> Tuple[Tuple[int, int], Tuple[int, int]]:
        """Parse '8:00am-9:00am' into ((8, 0), (9, 0))."""
        parts = [p.strip() for p in time_range_str.split("-")]
        if len(parts) == 2:
            start_hm = self._parse_time_str(parts[0])
            end_hm = self._parse_time_str(parts[1])
            return start_hm, end_hm
        # Fallback 1 hour
        start_hm = self._parse_time_str(parts[0])
        return start_hm, ((start_hm[0] + 1) % 24, start_hm[1])

    def _parse_date(self, row: List[Any]) -> Optional[date]:
        """Extract date from row string or HTML link data-date attribute."""
        # 1. Try row[9] data-date="MM/DD/YYYY"
        if len(row) > 9 and row[9]:
            match = re.search(r'data-date="(\d{1,2})/(\d{1,2})/(\d{4})"', str(row[9]))
            if match:
                try:
                    m, d, y = int(match.group(1)), int(match.group(2)), int(match.group(3))
                    return date(y, m, d)
                except ValueError:
                    pass

        # 2. Try row[0] "Monday, November 9, 2026"
        if len(row) > 0 and row[0]:
            match = re.search(r"(\w+\s+\d{1,2},\s+\d{4})", str(row[0]))
            if match:
                try:
                    dt = datetime.strptime(match.group(1), "%B %d, %Y")
                    return dt.date()
                except ValueError:
                    pass
        return None

    def fetch_raw_schedule(self, force_refresh: bool = False) -> Dict[str, Any]:
        """Fetch raw JSON schedule from GroupEx PRO API with 4-hour disk/memory cache."""
        now = datetime.now()

        # Check memory cache
        if not force_refresh and self._memory_cache and self._memory_cache_time:
            if now - self._memory_cache_time < self.cache_ttl:
                return self._memory_cache

        # Check disk cache
        if not force_refresh and self.cache_file.exists():
            try:
                stat = self.cache_file.stat()
                mtime = datetime.fromtimestamp(stat.st_mtime)
                if now - mtime < self.cache_ttl:
                    data = json.loads(self.cache_file.read_text(encoding="utf-8"))
                    self._memory_cache = data
                    self._memory_cache_time = mtime
                    return data
            except Exception as e:
                logger.warning("Could not read GroupEx PRO cache file: %s", e)

        # Live network fetch
        url = self.API_URL_TEMPLATE.format(account_id=self.account_id, location_id=self.location_id)
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "LiftAssistant/3.0 (personal_life_os; +https://github.com/liftassistant)"},
            )
            with urllib.request.urlopen(req, timeout=6) as response:
                content = response.read().decode("utf-8")
                data = json.loads(content)
                self.cache_file.write_text(content, encoding="utf-8")
                self._memory_cache = data
                self._memory_cache_time = now
                logger.info("Successfully fetched and cached live GroupEx PRO YMCA schedule (%d classes)", data.get("iTotalRecords", 0))
                return data
        except Exception as e:
            logger.warning("GroupEx PRO live API query failed (%s); falling back to cached or seeded data", e)
            if self.cache_file.exists():
                try:
                    return json.loads(self.cache_file.read_text(encoding="utf-8"))
                except Exception:
                    pass
            return {"aaData": []}

    def get_all_occupied_windows(self, force_refresh: bool = False) -> List[OccupiedWindow]:
        """Parse all classes into domain OccupiedWindow models."""
        raw = self.fetch_raw_schedule(force_refresh=force_refresh)
        rows = raw.get("aaData", [])
        windows: List[OccupiedWindow] = []

        for row in rows:
            if not isinstance(row, list) or len(row) < 7:
                continue

            target_d = self._parse_date(row)
            if not target_d:
                continue

            time_range_str = str(row[1]) if len(row) > 1 else ""
            (s_h, s_m), (e_h, e_m) = self._parse_time_range(time_range_str)

            start_dt = datetime.combine(target_d, time(s_h, s_m))
            end_dt = datetime.combine(target_d, time(e_h, e_m))
            if end_dt <= start_dt:
                end_dt += timedelta(days=1)

            activity_name = str(row[2]).strip()
            studio = str(row[4]).replace("&nbsp;", "").strip()
            category = str(row[5]).strip() if len(row) > 5 else None
            instructor = str(row[6]).strip() if len(row) > 6 else None
            facility_name = str(row[8]).strip() if len(row) > 8 else "Rose E. Schneider Family YMCA"

            windows.append(
                OccupiedWindow(
                    start_time=start_dt,
                    end_time=end_dt,
                    facility_name=facility_name,
                    studio=studio,
                    activity_name=activity_name,
                    instructor=instructor,
                    category=category,
                )
            )

        return windows

    def get_occupied_windows(
        self, target_date: date, studio_filter: Optional[str] = None
    ) -> List[OccupiedWindow]:
        """Query occupied classes for a specific date and optional studio.
        If target_date is not in the fetched schedule week, projects recurring classes
        for the matching day of week.
        """
        all_windows = self.get_all_occupied_windows()
        
        # 1. Check if we have exact date matches
        exact_matches = [w for w in all_windows if w.start_time.date() == target_date]
        if exact_matches:
            candidates = exact_matches
        else:
            # 2. Project recurring weekly classes matching the target day of week
            candidates = []
            for w in all_windows:
                if w.start_time.weekday() == target_date.weekday():
                    s_time = w.start_time.time()
                    e_time = w.end_time.time()
                    proj_start = datetime.combine(target_date, s_time)
                    proj_end = datetime.combine(target_date, e_time)
                    if proj_end <= proj_start:
                        proj_end += timedelta(days=1)
                    projected = w.model_copy(update={"start_time": proj_start, "end_time": proj_end})
                    candidates.append(projected)

        result = []
        for w in candidates:
            if studio_filter:
                filter_lower = studio_filter.lower()
                studio_lower = w.studio.lower()
                if filter_lower not in studio_lower and studio_lower not in filter_lower:
                    continue
            result.append(w)

        return result
