import streamlit as st
import pandas as pd
import time
import html
from datetime import datetime, date, timedelta
from db_manager import DatabaseManager
from point_system import PointSystem
from analytics import AnalyticsEngine
from import_export import ImportExportManager
from utils import format_date, calculate_days_remaining, get_status_color, calculate_school_day_number, get_placement_type_label, get_placement_duration_info, is_placement_active_today, get_placement_type_display_name, add_business_days, central_now, central_today, get_school_year_for_date

# Initialize session state
if 'data_manager' not in st.session_state:
    st.session_state.data_manager = DatabaseManager()
if 'point_system' not in st.session_state:
    st.session_state.point_system = PointSystem()
if 'analytics_engine' not in st.session_state:
    st.session_state.analytics_engine = AnalyticsEngine(st.session_state.data_manager)
if 'import_export_manager' not in st.session_state:
    st.session_state.import_export_manager = ImportExportManager(st.session_state.data_manager)

# Initialize end-of-day processing flag (runs once per session)
if 'eod_processing_checked' not in st.session_state:
    st.session_state.eod_processing_checked = False

dm = st.session_state.data_manager
ps = st.session_state.point_system
analytics = st.session_state.analytics_engine
import_export = st.session_state.import_export_manager

# Authorized staff list for placement creation/editing
AUTHORIZED_STAFF = ["Aaron Toronto", "Matthew Christie", "Todd Foster", "Chad Adamson"]

# =========== DEBUG FLAG (remove after investigation) ===========
DEBUG_PREPLANNED_DIAG = True
STAFF_OPTIONS = AUTHORIZED_STAFF + ["Add Staff"]  # "Add Staff" is a non-functional placeholder

def build_points_hover_tooltip_html(total_points, required_points, point_events, positive_menu):
    """
    Builds the hover tooltip HTML for the big Points Total (e.g., 8 / 10).

    Tooltip shows ALL categories (including zeros) and displays POINT TOTALS per category,
    not event counts. Negative points are grouped into one final line and shown as an
    absolute total. Adds a final line: "Total Points — X".
    """
    def _clean_label(lbl: str) -> str:
        if not lbl:
            return ""
        return lbl.split(" (")[0].strip()

    ordered = []
    for item in (positive_menu or []):
        code = item.get("code")
        if code:
            ordered.append((code, _clean_label(item.get("label", ""))))

    # Sum POINTS per category (not counts)
    pos_points = {code: 0 for code, _ in ordered}
    neg_abs_points = 0

    for e in (point_events or []):
        e_type = e.get("type")
        val = int(e.get("value", 0) or 0)
        if e_type == "negative":
            neg_abs_points += abs(val)
        else:
            code = e.get("code")
            if code in pos_points:
                pos_points[code] += val

    # Build tooltip lines (categories only)
    lines = [f"{label} — {pos_points.get(code, 0)}" for code, label in ordered]

    # Negative Points line at the bottom (before total)
    lines.append(f"Negative Points — {neg_abs_points}")

    # Final total line (matches the big number shown on the card)
    lines.append(f"Total Points — {int(total_points)}")

    tooltip_text = "\n".join(lines)
    tooltip_attr = html.escape(tooltip_text).replace("\n", "&#10;")

    meets_target = total_points >= required_points
    h2_style = "margin: 0;" + (" color: green;" if meets_target else "")

    return f"""
    <div title="{tooltip_attr}" style="display:inline-flex; align-items:center; gap:6px; cursor: help;">
        <h2 style="{h2_style}">{int(total_points)} / {int(required_points)}</h2>
        <span style="font-size: 14px; opacity: 0.6;">ⓘ</span>
    </div>
    """

def build_completion_label_with_tooltip(label: str, tooltip: str) -> str:
    """
    Builds an HTML label with a hover tooltip for completed records.
    Used for RED-circle completed records on past dates to show completion flag info.
    """
    tooltip_escaped = html.escape(tooltip or "").replace("\n", "&#10;")
    return f'<span title="{tooltip_escaped}" style="cursor: help; text-decoration: underline dotted; text-underline-offset: 3px;">{label}</span>'

def build_iss_points_breakdown_tooltip(point_events, positive_menu) -> str:
    """
    Build a tooltip string that shows POINT TOTALS per category (not counts),
    always including zeros, plus Negative Points (absolute) and Total Points (net).
    
    Includes internal consistency validation:
    - total_net_points is derived directly from sum of all event values (source of truth)
    - sum_pos is the sum of all category point totals
    - Validates: total_net_points == sum_pos - neg_abs_points
    - If mismatch, uses total_net_points as the authoritative value
    """
    def _clean_label(lbl: str) -> str:
        if not lbl:
            return ""
        return lbl.split(" (")[0].strip()

    ordered = []
    for item in (positive_menu or []):
        code = item.get("code")
        if code:
            ordered.append((code, _clean_label(item.get("label", ""))))

    pos_points = {code: 0 for code, _ in ordered}
    neg_abs_points = 0
    total_net_points = 0

    for e in (point_events or []):
        val = int(e.get("value", 0) or 0)
        total_net_points += val

        if e.get("type") == "negative":
            neg_abs_points += abs(val)
        else:
            code = e.get("code")
            if code in pos_points:
                pos_points[code] += val

    sum_pos = sum(pos_points.values())
    expected_total = sum_pos - neg_abs_points
    
    if total_net_points != expected_total:
        pass

    lines = [f"{label} — {pos_points.get(code, 0)}" for code, label in ordered]
    lines.append(f"Negative Points — {neg_abs_points}")
    lines.append(f"Total Points — {total_net_points}")

    return "\n".join(lines)

def build_iss_session_points_summary(point_events, positive_menu):
    """
    Builds a SESSION-LEVEL ISS points summary across all days in the placement.
    Returns a list of display lines with POINT TOTALS per category and Total Points.
    """
    def _clean_label(lbl: str) -> str:
        if not lbl:
            return ""
        return lbl.split(" (")[0].strip()

    ordered = []
    for item in (positive_menu or []):
        code = item.get("code")
        if code:
            ordered.append((code, _clean_label(item.get("label", ""))))

    pos_points = {code: 0 for code, _ in ordered}
    neg_abs_points = 0
    total_net_points = 0

    for e in (point_events or []):
        val = int(e.get("value", 0) or 0)
        total_net_points += val

        if e.get("type") == "negative":
            neg_abs_points += abs(val)
        else:
            code = e.get("code")
            if code in pos_points:
                pos_points[code] += val

    lines = [f"{label} — {pos_points.get(code, 0)}" for code, label in ordered]
    lines.append(f"Negative Points — {neg_abs_points}")
    lines.append(f"Total Points — {total_net_points}")

    return lines

# ===== CACHING LAYER =====
# Cached wrappers for expensive read-only operations to improve Dashboard performance.
# TTL of 60 seconds balances responsiveness with data freshness.
# Uses closure pattern to access 'dm' without including it in cache key.

@st.cache_data(ttl=60, show_spinner=False)
def get_active_placements_for_date_cached(selected_date_str: str):
    """Cached wrapper for get_active_placements_for_date.
    
    Caches results keyed by selected_date string for 60 seconds.
    Uses closure to access dm instance without including in cache key.
    """
    selected_date = date.fromisoformat(selected_date_str)
    return dm.get_active_placements_for_date(selected_date)

@st.cache_data(ttl=60, show_spinner=False)
def get_students_by_ids_cached(student_ids: tuple):
    """Cached wrapper for batch student lookup.
    
    Note: student_ids must be a tuple (hashable) for caching.
    """
    return dm.get_students_by_ids(list(student_ids))

@st.cache_data(ttl=60, show_spinner=False)
def get_iss_sessions_for_date_cached(target_date_str: str):
    """Cached wrapper for ISS sessions lookup."""
    target_date = date.fromisoformat(target_date_str)
    return dm.get_iss_sessions_for_date(target_date)

@st.cache_data(ttl=60, show_spinner=False)
def get_scheduled_iss_placements_cached():
    """Cached wrapper for scheduled ISS placements lookup."""
    return dm.get_scheduled_iss_placements()

def clear_dashboard_caches():
    """Clear all Dashboard-related caches after data mutations.
    
    Call this after creating, updating, or completing placements
    to ensure fresh data is shown on the Dashboard.
    """
    get_active_placements_for_date_cached.clear()
    get_iss_sessions_for_date_cached.clear()
    get_scheduled_iss_placements_cached.clear()

# ===== END CACHING LAYER =====

# ---------- Dashboard Completed-Session Title Helpers ----------

def _parse_iso_date_safe(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s).date()
    except Exception:
        return None

def _completed_suffix_for_day(*, placement_type_label: str, total_days: int, target_date: date,
                             end_date: date, is_absent: bool, day_number: int | None,
                             is_same_day_cpr: bool = False):
    """
    Returns the suffix portion after 'Placement Type · ...' based on rules:
    - Absent day: 'Absent'
    - Same-day CPR (Behavior/Cool-Down): 'Session Completed' (no day count)
    - Final day: 'X-Day Session Completed'
    - Prior served day: 'Day Y of X Completed'
    - Single day: '1-Day Session Completed'
    """
    if is_absent:
        return "Absent"

    total_days = total_days or 1

    # Behavior and Cool-Down CPRs are always same-day; no day count needed
    if is_same_day_cpr:
        return "Session Completed"

    if total_days == 1:
        return "1-Day Session Completed"

    if end_date and target_date == end_date:
        return f"{total_days}-Day Session Completed"

    # Prior served day (multi-day, not final day)
    # Per UI standard: show a simple "Day Completed" instead of day numbering.
    if day_number and day_number > 0:
        return "Day Completed"

    # Fallback (should rarely happen)
    return f"{total_days}-Day Session Completed"

# =========================================================
# Circle Color Logic — Day-level overrides placement-level
# =========================================================

def _is_absent_for_date(dm, placement_id: str, date_str: str, *, daily_log: dict = None) -> bool:
    """
    Returns True if the given placement/day is marked absent or no-show.
    Uses DailyLog.dayType when available.
    
    Args:
        dm: DatabaseManager instance
        placement_id: Placement ID
        date_str: ISO format date string
        daily_log: Optional pre-fetched daily log to avoid duplicate fetch
    """
    if daily_log is None:
        try:
            daily_log = dm.get_daily_log(placement_id, date_str)
        except Exception:
            daily_log = None

    day_type = daily_log.get("dayType") if daily_log else None
    return day_type == "absent" or day_type == "no_show"


def _is_day_completed_for_date(
    daily_log: dict = None,
    *,
    session_status: str = None,
    is_absent_day: bool = False
) -> bool:
    """
    Returns True if the given day is completed.

    IMPORTANT FIX:
      - For ISS, session_status == 'fulfilled' previously forced completion.
      - For 1-day ISS Absent days, we must NOT treat 'fulfilled' as completion,
        because Absent never serves/completes the placement.

    Args:
        daily_log: Daily log dictionary (may be None)
        session_status: Optional session status for ISS ('fulfilled' means completed in general)
        is_absent_day: If True, DO NOT treat fulfilled as completed
    """
    # Only treat ISS "fulfilled" as completed when the day is NOT absent
    if session_status == 'fulfilled' and not is_absent_day:
        return True

    if daily_log is None:
        return False

    fulfillment = daily_log.get('dailyFulfillment')
    override_used = daily_log.get('overrideUsed', False)
    return fulfillment == 'yes' or override_used


def _circle_for_day(
    progress_status: str,
    *,
    is_absent_day: bool = False,
    is_day_completed: bool = False
) -> str:
    """
    Final circle rules (single source of truth):

    1) COMPLETED placement OR fulfilled day → 🔴
    2) IN_PROGRESS:
        - Absent day → 🔴
        - Otherwise → 🟡
    3) NOT_STARTED → 🟢 (even if absent marked)
    """
    if progress_status == "COMPLETED" or is_day_completed:
        return "🔴"

    if progress_status == "IN_PROGRESS":
        return "🔴" if is_absent_day else "🟡"

    return "🟢"


def _dashboard_request_keep_open(card_uid: str, ttl: int = 2) -> None:
    """
    Request that the Dashboard expander for `card_uid` remain open across reruns.
    TTL counts full Dashboard renders. ttl=2 survives a common 2-rerun cycle.
    """
    if not card_uid:
        return
    st.session_state["_dash_keep_open_uid"] = str(card_uid)
    st.session_state["_dash_keep_open_ttl"] = int(ttl)

def _dashboard_should_expand(card_uid: str) -> bool:
    uid = st.session_state.get("_dash_keep_open_uid")
    ttl = int(st.session_state.get("_dash_keep_open_ttl") or 0)
    return bool(uid) and (uid == str(card_uid)) and ttl > 0

def _dashboard_keep_open_tick() -> None:
    """
    Decrement TTL once per completed Dashboard render.
    When TTL hits 0, clear the keep-open request.
    """
    ttl = int(st.session_state.get("_dash_keep_open_ttl") or 0)
    if ttl <= 0:
        st.session_state.pop("_dash_keep_open_uid", None)
        st.session_state.pop("_dash_keep_open_ttl", None)
        return
    ttl -= 1
    if ttl <= 0:
        st.session_state.pop("_dash_keep_open_uid", None)
        st.session_state.pop("_dash_keep_open_ttl", None)
    else:
        st.session_state["_dash_keep_open_ttl"] = ttl


def _status_text_for_day(
    progress_status: str,
    *,
    is_absent_day: bool = False,
    is_day_completed: bool = False
) -> str:
    """
    Text that accompanies the status circle.
    """
    if progress_status == "COMPLETED" or is_day_completed:
        return "Completed"

    if progress_status == "IN_PROGRESS":
        return "Absent" if is_absent_day else "In Progress"

    return "Not Started"

# Check and process end-of-day for pending dates (runs once per session)
if not st.session_state.eod_processing_checked:
    processing_results = dm.check_and_process_pending_dates()
    st.session_state.eod_processing_checked = True
    
    # Store results for potential display
    if processing_results:
        st.session_state.eod_processing_results = processing_results

# Auto-activate scheduled placements whose start date has arrived
# IMPORTANT: run once per Central-time DAY (not once per Streamlit session),
# otherwise tabs left open overnight will never activate placements on the new day.
today_str = central_today().isoformat()
last_activation_day = st.session_state.get('scheduled_activation_last_date')

if last_activation_day != today_str:
    activated_count = dm.activate_scheduled_placements()
    st.session_state.scheduled_activation_last_date = today_str

    if activated_count > 0:
        st.session_state.placements_activated = activated_count

# Backward compatibility: remove old one-time flag if it exists
if 'scheduled_activation_checked' in st.session_state:
    del st.session_state['scheduled_activation_checked']

# Helper functions for session generation
def generate_periods_sessions(session_date, periods, repeat_days, location):
    """Generate sessions for period-based placements"""
    sessions = []
    for day_offset in range(repeat_days + 1):
        current_date = session_date + timedelta(days=day_offset)
        for period in periods:
            sessions.append({
                "date": current_date,
                "type": "periods",
                "scope": f"Period {period}",
                "location": location,
                "metadata": {"period": period}
            })
    return sessions

def generate_lunch_sessions(start_date, end_date, weekdays_map, lunch_block, location):
    """Generate sessions for lunch detention across date range"""
    sessions = []
    current_date = start_date
    
    while current_date <= end_date:
        weekday_name = current_date.strftime("%A")
        # Map weekday name to our keys
        weekday_key = {
            "Monday": "mon", "Tuesday": "tue", "Wednesday": "wed",
            "Thursday": "thu", "Friday": "fri"
        }.get(weekday_name)
        
        # Only include if this weekday is selected
        if weekday_key and weekdays_map.get(weekday_key, False):
            sessions.append({
                "date": current_date,
                "type": "lunch",
                "scope": lunch_block,
                "location": location,
                "metadata": {"lunch_block": lunch_block}
            })
        
        current_date += timedelta(days=1)
    
    return sessions

def generate_cooldown_session(time_start, time_end, location, quick_reason):
    """Generate a single cool-down session for today"""
    return [{
        "date": central_today(),
        "type": "cool_down",
        "scope": "Scheduled Window",
        "location": location,
        "metadata": {
            "start_time": time_start.isoformat(),
            "end_time": time_end.isoformat(),
            "reason": quick_reason
        }
    }]

def generate_referral_session(referral_date, period, location, teacher, reason, other_reason=None):
    """Generate a single-period referral session"""
    return [{
        "date": referral_date,
        "type": "referral",
        "scope": f"Period {period}",
        "location": location,
        "metadata": {
            "period": period,
            "teacher": teacher,
            "reason": other_reason if reason == "Other" else reason
        }
    }]

def detect_session_conflicts(sessions):
    """Detect time conflicts in sessions (same date, overlapping times)"""
    conflicts = []
    
    # Group sessions by date
    by_date = {}
    for i, session in enumerate(sessions):
        date_key = session["date"].isoformat()
        if date_key not in by_date:
            by_date[date_key] = []
        by_date[date_key].append((i, session))
    
    # Check for conflicts within each date
    for date_key, day_sessions in by_date.items():
        # For period-based sessions, check if same period appears multiple times
        period_sessions = [(i, s) for i, s in day_sessions if s["type"] in ["periods", "referral"]]
        if len(period_sessions) > 1:
            periods_used = {}
            for i, session in period_sessions:
                period = session["metadata"].get("period")
                if period:
                    if period in periods_used:
                        conflicts.append({
                            "indices": [periods_used[period], i],
                            "message": f"Period {period} conflict on {session['date'].strftime('%m/%d/%Y')}"
                        })
                    else:
                        periods_used[period] = i
        
        # For lunch sessions, check if multiple lunch blocks on same day
        lunch_sessions = [(i, s) for i, s in day_sessions if s["type"] == "lunch"]
        if len(lunch_sessions) > 1:
            conflicts.append({
                "indices": [i for i, _ in lunch_sessions],
                "message": f"Multiple lunch sessions on {lunch_sessions[0][1]['date'].strftime('%m/%d/%Y')}"
            })
    
    return conflicts

def render_auto_save_notes(unique_key: str, current_notes: str, save_callback, disabled: bool = False, help_text: str = None):
    """
    Render an always-visible Notes text area with auto-save functionality.
    
    Args:
        unique_key: Unique identifier for session state keys (e.g., placement_id + date)
        current_notes: Current notes value from database
        save_callback: Function to call to save notes, takes (notes_text) as argument
        disabled: Whether the text area should be disabled
        help_text: Optional help tooltip when disabled
    """
    notes_key = f"notes_{unique_key}"
    prev_notes_key = f"prev_notes_{unique_key}"
    saved_time_key = f"notes_saved_time_{unique_key}"
    
    if prev_notes_key not in st.session_state:
        st.session_state[prev_notes_key] = current_notes or ''
    
    def on_notes_change():
        new_notes = st.session_state.get(notes_key, '')
        prev_notes = st.session_state.get(prev_notes_key, '')
        if new_notes != prev_notes:
            save_callback(new_notes)
            st.session_state[prev_notes_key] = new_notes
            st.session_state[saved_time_key] = time.time()
    
    notes_col, saved_col = st.columns([4, 1])
    
    with notes_col:
        st.text_area(
            "Notes",
            value=st.session_state.get(prev_notes_key, current_notes or ''),
            key=notes_key,
            height=60,
            placeholder="Add notes here...",
            on_change=on_notes_change if not disabled else None,
            label_visibility="collapsed",
            disabled=disabled,
            help=help_text
        )
    
    with saved_col:
        saved_time = st.session_state.get(saved_time_key, 0)
        if saved_time > 0 and (time.time() - saved_time) < 2:
            st.markdown("<span style='color: #28a745; font-size: 0.85em;'>✓ Saved</span>", unsafe_allow_html=True)

# Page configuration
st.set_page_config(
    page_title="The Grotto",
    page_icon="🏫",
    layout="wide",
    initial_sidebar_state="expanded"
)

# =========================
# WEBSITE-STYLE TOP NAV (GLOBAL) — IN-APP (NO <a href>)
# =========================

PAGE_OPTIONS = [
    "Dashboard",
    "Placements",
    "Completed Placements",
    "Assignments",
]

# Initialize nav state
if "current_page" not in st.session_state:
    st.session_state.current_page = "Dashboard"

def _set_page(page_name: str, *, do_rerun: bool = True):
    """Set current page for in-app navigation (no URL navigation)."""
    st.session_state.current_page = page_name
    if do_rerun:
        st.rerun()

# --- Programmatic navigation flags (preserve existing behavior) ---
if st.session_state.get("navigate_to_dashboard"):
    del st.session_state.navigate_to_dashboard
    _set_page("Dashboard")
elif st.session_state.get("navigate_to_create_placement"):
    del st.session_state.navigate_to_create_placement
    _set_page("Placements")
elif st.session_state.get("navigate_to_completed_placements"):
    del st.session_state.navigate_to_completed_placements
    _set_page("Completed Placements")
elif st.session_state.get("navigate_to_assignments"):
    del st.session_state.navigate_to_assignments
    _set_page("Assignments")
elif st.session_state.get("navigate_to_iss_detail"):
    # Hidden/detail page: do not show as a nav item; keep nav highlight sane.
    del st.session_state.navigate_to_iss_detail
    st.session_state.current_page = "ISS Detail"

# For hidden pages, keep display/highlight on Dashboard
active_for_nav = (
    st.session_state.current_page
    if st.session_state.current_page in PAGE_OPTIONS
    else "Dashboard"
)

# --- Nav row (buttons styled by type; active page uses primary) ---
nav_cols = st.columns([1, 1, 1.5, 1], vertical_alignment="center")

labels = ["Dashboard", "Placements", "Completed Placements", "Assignments"]
targets = ["Dashboard", "Placements", "Completed Placements", "Assignments"]

for col, label, target in zip(nav_cols, labels, targets):
    with col:
        is_active = (target == active_for_nav)
        if st.button(
            label,
            key=f"nav_btn_{target.replace(' ', '_').lower()}",
            type="primary" if is_active else "secondary",
            use_container_width=True,
        ):
            _set_page(target)

# Source of truth for routing
page = st.session_state.current_page

# Main title with logo
col_logo, col_title = st.columns([1, 4])
with col_logo:
    st.image("attached_assets/Bobcats_1761658497832.png", width=150)
with col_title:
    st.title("The Grotto")
    st.caption("Student Support Placement Platform")

# Dashboard Page
if page == "Dashboard":
    # =========================
    # AUGUST PROMPT: SCHOOL CALENDAR (NO-SCHOOL DAYS)
    # =========================
    today = central_today()
    current_sy = get_school_year_for_date(today)

    # School Calendar editor toggle (lets a user reopen the August-style workflow any time)
    if "school_calendar_edit_mode" not in st.session_state:
        st.session_state.school_calendar_edit_mode = False

    # Show the prompt until the calendar is finalized for this school year
    finalized_calendar = dm.is_school_calendar_finalized(current_sy)

    # Prompt persists year-round until calendar is finalized for this school year
    show_calendar_prompt = (not finalized_calendar)

    if show_calendar_prompt:
        st.warning("📅 School Calendar Setup: Please enter this school year's holidays / no-school days so schedules can skip them like weekends.")

    # Editor mode is allowed any time via the bottom summary card's Edit button
    edit_mode = st.session_state.get("school_calendar_edit_mode", False)

    # Only render the full editor UI when:
    # - It's August prompt time (not finalized), OR
    # - User explicitly clicked Edit from the bottom summary
    if show_calendar_prompt or (not finalized_calendar) or edit_mode:
        with st.expander(
            "📅 School Calendar Setup (No-School Days / Breaks)",
            expanded=(show_calendar_prompt or edit_mode)
        ):
            # Ensure config exists so finalize works cleanly
            dm._ensure_school_year_config(current_sy)

            st.caption(f"School Year: {int(current_sy[0])}-{str(int(current_sy[1]))[-2:]}  (Aug → Jul)")

            # Pull closures once so we can drive button flow + reuse for rendering
            closures = dm.list_school_closures(current_sy)
            has_closures = len(closures) > 0

            # --- School Calendar: Add Entry UI (Option A: radio outside form, inputs inside form) ---
            if "cal_form_nonce" not in st.session_state:
                st.session_state.cal_form_nonce = 0

            n = st.session_state.cal_form_nonce
            today_default = central_today()

            # Radio OUTSIDE the form so it triggers rerun and shows correct date inputs immediately
            mode = st.radio(
                "Add entry type",
                ["Single Day", "Date Range"],
                horizontal=True,
                index=0,  # default Single Day
                key=f"cal_mode_{n}",
            )

            # Inputs INSIDE the form for submit-only behavior + clear_on_submit
            with st.form(f"school_calendar_add_form_{n}", clear_on_submit=True):
                title = st.text_input(
                    "Title / label (e.g., Winter Break, MLK Day, Teacher Inservice)",
                    value="",
                    key=f"cal_title_{n}",
                ).strip()

                if mode == "Single Day":
                    one_day = st.date_input(
                        "Date",
                        value=today_default,
                        key=f"cal_single_date_{n}",
                    )
                    start_date = one_day
                    end_date = one_day
                else:
                    colA, colB = st.columns(2)
                    with colA:
                        start_date = st.date_input(
                            "Start date",
                            value=today_default,
                            key=f"cal_start_date_{n}",
                        )
                    with colB:
                        end_date = st.date_input(
                            "End date",
                            value=today_default,
                            key=f"cal_end_date_{n}",
                        )

                submitted = st.form_submit_button("➕ Save & Add No-School Day(s)", use_container_width=True)

            if submitted:
                new_id = dm.add_school_closure(current_sy, title, start_date, end_date)
                if new_id:
                    st.success("Saved.")
                    # Remount widgets to reset back to defaults (blank title, Single Day, today)
                    st.session_state.cal_form_nonce += 1
                    st.rerun()
                else:
                    st.warning("Not saved (missing title, duplicate, or invalid dates).")

            finalize_col = st.columns([1])[0]

            with finalize_col:
                # If already finalized and the user is editing, show a small status indicator.
                # (No side effects: editing is allowed; finalizing again is a deliberate action.)
                if finalized_calendar and edit_mode:
                    st.success("✅ Calendar finalized (Edit Mode)")
                elif finalized_calendar and not edit_mode:
                    st.success("✅ Calendar finalized")
                else:
                    # Before any entries exist: show Finalize Year here, but disabled
                    if not has_closures:
                        st.button(
                            "✅ Finalize Year",
                            use_container_width=True,
                            disabled=True,
                            help="Add at least one no-school day before finalizing the year."
                        )
                    # After entries exist: Finalize Year moves below the saved list (rendered later)

            st.divider()

            if not closures:
                st.info("No no-school days entered yet.")
            else:
                st.markdown("**Saved no-school days:**")
                for c in closures:
                    left, right = st.columns([6, 1])
                    label = c["title"]
                    if c["start_date"] == c["end_date"]:
                        date_label = c["start_date"]
                    else:
                        date_label = f'{c["start_date"]} → {c["end_date"]}'

                    with left:
                        st.write(f"• **{label}** — {date_label}")
                    with right:
                        if st.button("🗑️", key=f"del_closure_{c['id']}"):
                            dm.delete_school_closure(c["id"])
                            st.rerun()

                # After at least one saved entry exists: show Finalize Year underneath the list
                if not dm.is_school_calendar_finalized(current_sy):
                    if st.button("✅ Finalize Year", use_container_width=True):
                        dm.finalize_school_calendar(current_sy)

                        # Collapse + "move to bottom": exit edit mode and rerun
                        st.session_state.school_calendar_edit_mode = False

                        st.success("Calendar finalized. August prompt will stop for this school year.")
                        st.rerun()
                else:
                    # If the calendar is already finalized, allow exiting edit mode cleanly
                    if edit_mode:
                        if st.button("Done Editing", use_container_width=True, type="secondary"):
                            st.session_state.school_calendar_edit_mode = False
                            st.rerun()
    # Else: finalized + not editing -> editor UI is hidden here (it will appear as the bottom summary card)

    # ===== ISS PENDING ACTION DISPATCHER (best long-term fix) =====
    # Instead of scanning deferred_* keys (fragile), we process exactly ONE explicit action per rerun.
    ISS_PENDING_KEY = "ISS_PENDING_ACTION"

    pending = st.session_state.pop(ISS_PENDING_KEY, None)
    if pending:
        # Keep the originating ISS card expanded through this rerun cycle
        _dashboard_request_keep_open(pending.get("card_uid"), ttl=2)

        action = pending.get("action")  # "complete", "override", or "add_point"
        print(f"[ISS_DISPATCH] Processing action={action} payload={pending}")

        try:
            if action == "add_point":
                # Payload comes from the card dropdown, but execution happens here (single targeted action)
                payload = pending.get("payload")
                if not payload:
                    st.error("Missing payload for add_point")
                else:
                    # Enforce placement-level limits (e.g., Repair the harm single-use + mutex)
                    ps = st.session_state.point_system
                    placement_id_for_gate = payload.get("placementId")
                    student_id_for_gate = payload.get("studentId")
                    code_for_gate = payload.get("code")
                    date_for_gate = payload.get("date", "")

                    can_add, reason = ps.can_add_point_event(
                        placement_id_for_gate,
                        student_id_for_gate,
                        code_for_gate,
                        date_for_gate,
                    )

                    if not can_add:
                        st.warning(f"🔒 {reason}")
                    else:
                        event_id = dm.add_point_event(payload)
                        if not event_id:
                            st.warning("🔒 Points were not added. Confirm **Full Day** or confirm **Partial Day** periods for this date first.")

                # Reset dropdowns by setting defaults (not deleting keys) so the next selection triggers cleanly
                card_uid = pending.get("card_uid")
                if card_uid:
                    pos_k = f"iss_pos_{card_uid}"
                    neg_k = f"iss_neg_{card_uid}"

                    # Set back to the default option so the next selection always triggers cleanly
                    if pos_k in st.session_state:
                        st.session_state[pos_k] = "+ Positive"
                    if neg_k in st.session_state:
                        st.session_state[neg_k] = "- Negative"

            elif action == "override":
                # Execute override
                result = dm.complete_iss_day(
                    placement_id=pending["placement_id"],
                    log_date=pending["log_date"],
                    completed_by=pending.get("completed_by", "Admin"),
                    day_type="Full Day",
                    start_period=1,
                    end_period=10,
                    points_earned=pending["points_earned"],
                    is_override=True,
                    override_note=pending["override_note"],
                )

                if result.get("success"):
                    # Only mark session completed if session_id exists
                    if pending.get("session_id") is not None:
                        dm.mark_session_completed(
                            pending["session_id"],
                            "Admin",
                            is_override=True,
                            override_comment=pending["override_note"],
                        )
                    if not pending.get("is_present", False):
                        dm.update_iss_attendance(pending["placement_id"], pending["log_date"], True)


                    # STRICT make-up trigger (ISS only):
                    # Only prompts after the final ORIGINAL session day is completed
                    # and only when the student is still short under strict math (originalDayCount * 10).
                    strict_makeup_check = dm.check_iss_session_needs_makeup_strict(pending["placement_id"])
                    if strict_makeup_check.get("needsMakeup", False):
                        st.session_state[f"show_makeup_prompt_{pending['placement_id']}"] = True
                        st.session_state[f"makeup_info_{pending['placement_id']}"] = strict_makeup_check

                    st.success("Override applied! ISS Session complete." if result.get("isCompleted") else "Override applied!")
                else:
                    st.error(result.get("message", "Failed to apply override"))

            else:
                # Execute regular completion
                result = dm.complete_iss_day(
                    placement_id=pending["placement_id"],
                    log_date=pending["log_date"],
                    completed_by=pending.get("completed_by", "Admin"),
                    day_type=pending["day_type"],
                    start_period=pending["start_period"],
                    end_period=pending["end_period"],
                    points_earned=pending["points_earned"],
                )

                if result.get("success"):
                    # Only mark session completed if session_id exists
                    if pending.get("session_id") is not None:
                        dm.mark_session_completed(pending["session_id"], "Admin")

                    if not pending.get("is_present", False):
                        dm.update_iss_attendance(pending["placement_id"], pending["log_date"], True)

                    # STRICT make-up trigger (ISS only):
                    # Even if schedule-based math marks the session complete, enforce "full-day expectation"
                    # (originalDayCount * 10) and show the existing Make-Up Days decision prompt when short.
                    strict_makeup_check = dm.check_iss_session_needs_makeup_strict(pending["placement_id"])
                    if strict_makeup_check.get("needsMakeup", False):
                        st.session_state[f"show_makeup_prompt_{pending['placement_id']}"] = True
                        st.session_state[f"makeup_info_{pending['placement_id']}"] = strict_makeup_check

                    if result.get("isCompleted"):
                        st.success("ISS Session complete! All required periods served.")
                    else:
                        st.success("ISS day completed successfully!")
                else:
                    st.error(result.get("message", "Failed to complete ISS day"))

        finally:
            # Clear caches after processing
            if hasattr(st, "cache_data"):
                st.cache_data.clear()

        # Always rerun after dispatch so UI reflects updated DB state
        st.rerun()
    # ===== END ISS PENDING ACTION DISPATCHER =====
    
    # Navigation button - Create New Placement
    btn_col1, btn_col2, btn_col3 = st.columns([2, 2, 2])
    with btn_col1:
        if st.button("Create New Placement", type="primary", use_container_width=True, key="dash_create_placement_btn"):
            st.session_state.navigate_to_create_placement = True
            st.rerun()
    
    st.header("Dashboard")
    
    # Helper for debug logging (only logs when DEBUG_ISS_POINTS env var or session state is set)
    def iss_debug_log(msg: str):
        """Console log only when DEBUG_ISS_POINTS is enabled."""
        if st.session_state.get("DEBUG_ISS_POINTS"):
            print(msg)
    
    # Show success message if placement was just created
    if st.session_state.get('placement_created'):
        today = central_today()

        # Force both the internal Dashboard date state
        # AND the date_input widget value back to Today
        st.session_state.dashboard_selected_date = today
        st.session_state.dashboard_date_selector = today

        st.success("Placement created successfully!")
        del st.session_state.placement_created
    
    # Date Selector (compact width)
    # Use the widget key as the single source of truth to avoid Streamlit "default value + session_state" warnings.
    if 'dashboard_date_selector' not in st.session_state:
        st.session_state.dashboard_date_selector = central_today()

    date_col, _ = st.columns([1, 3])
    with date_col:
        selected_date = st.date_input(
            "Select Date",
            key="dashboard_date_selector"
        )

    # Keep internal state in sync (downstream code uses dashboard_selected_date)
    st.session_state.dashboard_selected_date = selected_date
    
    # Show past date indicator
    is_past_date = selected_date < central_today()
    if is_past_date:
        st.info(f"📅 Viewing historical data for {selected_date.strftime('%B %d, %Y')}. You can still complete sessions retroactively.")
    
    # Get all active placements for selected date (used by placement sections below)
    # CACHED: Results cached for 60 seconds to improve Dashboard responsiveness
    placements_for_date = get_active_placements_for_date_cached(selected_date.isoformat())
    
    # Date display
    st.subheader(f"{selected_date.strftime('%B %d, %Y')}")
    
    st.divider()
    
    # Group placements by type
    iss_placements = []
    lunch_detention_placements = []
    unified_class_referral_placements = []  # All three referral subtypes merged
    
    for placement in placements_for_date:
        placement_type = placement.get('placementType', '').upper()
        
        if placement_type == 'ISS':
            iss_placements.append(placement)
        elif placement_type == 'LUNCH_DETENTION':
            lunch_detention_placements.append(placement)
        elif placement_type in ['CLASS_REFERRAL', 'COOL_DOWN', 'PRE_PLANNED_REFERRAL']:
            # All referral types go into unified list
            unified_class_referral_placements.append(placement)
    
    # Helper function to render ISS Full Day student card with period-based tracking
    def render_iss_full_card(placement: dict, target_date: date):
        """Render ISS Full Day card with period-based tracking, Check In workflow, and behaviors.
        
        Uses lazy loading: only fetches daily log when student is checked in or has existing log.
        """
        import math
        from utils import get_daily_status_color
        
        student = placement['student']
        placement_id = placement['_id']
        student_name = f"{student['firstName']} {student['lastName']}"
        date_str = target_date.isoformat()
        
        # Get period-based ISS tracking fields
        iss_days_assigned = placement.get('issDaysAssigned') or placement.get('issTotalDays') or placement.get('daysAssigned', 1)

        # Date-aware ISS period math (snapshot as-of the Dashboard date)
        iss_total_required_periods = dm.get_iss_total_periods_required(placement)
        period_math_asof = dm.get_iss_period_math_for_date(placement, placement_id, date_str)
        iss_periods_served = period_math_asof['served']
        iss_periods_remaining = period_math_asof['remaining']

        # Current/overall served periods (used for completion/make-up logic)
        iss_periods_served_total = dm.get_iss_periods_served(placement)
        periods_waived = placement.get('periodsWaived') or 0
        iss_periods_remaining_total = max(0, iss_total_required_periods - iss_periods_served_total - periods_waived)

        days_completed = placement.get('daysCompleted', 0) or 0
        
        # Get days served info for Day X of Y display (completion-based, not calendar-based)
        days_served_info = dm.get_iss_days_served_info(placement_id, date_str)
        current_day = days_served_info.get('current_day_number', 1)
        is_today_absent = days_served_info.get('is_today_absent', False)
        
        # Check if ISS Session is complete (overall/current status)
        is_session_complete = (placement.get('status') == 'completed') or (iss_periods_served_total >= iss_total_required_periods)
        
        # LAZY LOADING: Only fetch daily log if it exists (read-only check)
        # This prevents creating logs on initial Dashboard load
        daily_log = dm.get_daily_log(placement_id, date_str)
        
        # Determine if student is checked in (from existing log, if any)
        is_checked_in = daily_log.get('checkedIn', False) if daily_log else False
        is_day_completed = daily_log.get('dailyFulfillment') == 'yes' if daily_log else False
        
        # Determine status: only fetch from log if it exists
        if daily_log:
            fulfillment = daily_log.get('dailyFulfillment') or ''
            status_color = get_daily_status_color(fulfillment, date_str)
        else:
            status_color = 'yellow'  # Default to yellow (pending) for no log
        status_icon = {'green': '🟢', 'yellow': '🟡', 'red': '🔴'}.get(status_color, '⚪')
        
        # Only fetch point events if student is checked in (lazy loading)
        if is_checked_in:
            point_events = dm.get_point_events_for_date(placement_id, date_str)
            positive_points = sum([e['value'] for e in point_events if e['type'] == 'positive'])
            negative_points = sum([e['value'] for e in point_events if e['type'] == 'negative'])
            total_points = positive_points + negative_points
        else:
            point_events = []
            positive_points = 0
            negative_points = 0
            total_points = 0
        
        with st.container():
            # Header row: Student name with status
            st.markdown(f"### {status_icon} {student_name}")
            st.caption(f"Grade {student.get('grade', 'N/A')} · {student.get('homeroomTeacher', 'N/A')}")
            
            # Summary line: "{issDaysAssigned}-day ISS Session for {Student Name}"
            st.markdown(f"**{iss_days_assigned}-day ISS Session for {student_name}**")
            
            # Progress line: "Periods served: X of Y"
            # Grey summary snapshot (date-aware)
            st.info(
                f"📊 **ISS:** Required **{iss_total_required_periods}** periods | "
                f"Served **{iss_periods_served}** | "
                f"Remaining **{iss_periods_remaining}**"
            )
            
            # Calculate remaining periods needed
            remaining_periods = iss_periods_remaining
            
            # Check if placement needs make-up
            placement_status = placement.get('status', 'active')
            needs_makeup = placement_status == 'needs_makeup'
            
            # Check if this is a make-up session (days_completed >= iss_days_assigned but still needs periods)
            is_makeup_day = days_completed >= iss_days_assigned and not is_session_complete
            
            # Day label or completion message
            if is_session_complete:
                st.success("✅ **ISS Session complete**")
            elif is_makeup_day or needs_makeup:
                # Make-up days do NOT show a day number
                st.warning(f"⚠️ **{iss_days_assigned}-Day ISS Session (Active – Needs Make-Up Periods)**")
                st.caption(f"🔢 **Remaining Periods Needed:** {remaining_periods}")
            else:
                st.markdown(f"📅 **Day {current_day} of {iss_days_assigned} ISS Session**")
                # Show remaining periods needed (for late arrivals and multi-day tracking)
                if remaining_periods > 0:
                    st.caption(f"🔢 **Remaining Periods Needed:** {remaining_periods}")
            
            # Check-in buttons (only for active ISS or needs_makeup, not completed Session)
            if not is_session_complete or needs_makeup:
                st.markdown("---")
                
                # Show appropriate session label
                if needs_makeup:
                    periods_remaining = iss_periods_remaining_total
                    st.markdown("**Make-Up Session**")
                    st.info(f"🔄 **Make-Up Session Needed:** {periods_remaining} periods remaining to complete ISS")
                else:
                    st.markdown("**Today's Session**")
                
                # Get day_type from daily log (safe access - daily_log may be None)
                day_type = daily_log.get('dayType', None) if daily_log else None
                is_makeup_session = daily_log.get('isMakeupSession', False) if daily_log else False
                
                if is_day_completed:
                    periods_added = daily_log.get('periodsAdded', 10)
                    if is_makeup_session:
                        st.success(f"✅ Make-up session completed (+{periods_added} periods)")
                    else:
                        st.success(f"✅ Today's session completed (+{periods_added} periods)")
                elif is_checked_in and day_type == 'full':
                    # Show Full Day ISS Session Panel
                    # Read required_points from daily_log (source of truth after Check In)
                    full_day_periods = daily_log.get('endPeriod', 10) - daily_log.get('startPeriod', 1) + 1 if daily_log else 10
                    full_day_required_points = daily_log.get('requiredPoints') or full_day_periods
                    
                    # card_uid for Full Day sessions (session_id is None for full-day)
                    card_uid = f"{placement_id}_full_{date_str}"
                    
                    if is_makeup_session or is_makeup_day:
                        st.markdown(f"### 📋 Make-Up Full Day Session ({full_day_periods} periods)")
                        st.info(f"**{iss_days_assigned}-day ISS Session for {student_name}** · Make-Up Session")
                    else:
                        st.markdown(f"### 📋 Full Day ISS Session ({full_day_periods} periods)")
                        st.info(f"**{iss_days_assigned}-day ISS Session for {student_name}** · Day {current_day} of {iss_days_assigned} ISS Session")
                    
                    # Behaviors section
                    col_left, col_right = st.columns([1, 1])
                    
                    with col_left:
                        st.markdown("**Behaviors**")
                        # Positive behaviors dropdown
                        positive_menu = ps.get_positive_point_menu()
                        positive_options = ["-- Add Positive --"] + [item['label'] for item in positive_menu]
                        selected_positive = st.selectbox(
                            "Positive",
                            positive_options,
                            key=f"pos_{placement_id}_{date_str}",
                            label_visibility="collapsed"
                        )
                        
                        if selected_positive != "-- Add Positive --":
                            item = next((i for i in positive_menu if i['label'] == selected_positive), None)
                            if item:
                                dm.add_point_event({
                                    'placementId': placement_id,
                                    'studentId': student['_id'],
                                    'code': item['code'],
                                    'type': 'positive',
                                    'value': item['value'],
                                    'date': date_str
                                })
                                # Reset dropdown to prevent ghost point on rerun
                                st.session_state[f"pos_{placement_id}_{date_str}"] = "-- Add Positive --"
                                st.rerun()
                        
                        # Negative behaviors dropdown
                        negative_menu = ps.get_negative_point_menu()
                        negative_options = ["-- Add Negative --"] + [item['label'] for item in negative_menu]
                        selected_negative = st.selectbox(
                            "Negative",
                            negative_options,
                            key=f"neg_{placement_id}_{date_str}",
                            label_visibility="collapsed"
                        )
                        
                        if selected_negative != "-- Add Negative --":
                            item = next((i for i in negative_menu if i['label'] == selected_negative), None)
                            if item:
                                dm.add_point_event({
                                    'placementId': placement_id,
                                    'studentId': student['_id'],
                                    'code': item['code'],
                                    'type': 'negative',
                                    'value': item['value'],
                                    'date': date_str
                                })
                                # Reset dropdown to prevent ghost point on rerun
                                st.session_state[f"neg_{placement_id}_{date_str}"] = "-- Add Negative --"
                                st.rerun()
                    
                    with col_right:
                        st.markdown("**Points Total**")
                        # Use stored required_points from daily_log (source of truth)
                        if total_points >= full_day_required_points:
                            st.markdown(f"<h2 style='color: green;'>{total_points} / {full_day_required_points}</h2>", unsafe_allow_html=True)
                            st.caption("Eligible for completion")
                        else:
                            st.markdown(f"<h2>{total_points} / {full_day_required_points}</h2>", unsafe_allow_html=True)
                            st.caption(f"Need {full_day_required_points - total_points} more points")
                    
                    # Notes for Full Day session
                    st.caption("Session Notes")
                    render_auto_save_notes(
                        f"fullday_session_{placement_id}_{date_str}",
                        daily_log.get('notes', '') or '',
                        lambda notes: dm.update_daily_log_notes(placement_id, date_str, notes)
                    )
                    
                    st.markdown("---")
                    
                    # Complete and Override buttons for Full Day session
                    col_complete, col_override = st.columns(2)
                    
                    with col_complete:
                        can_complete = total_points >= full_day_required_points
                        if st.button(
                            "✅ Complete",
                            key=f"complete_full_{card_uid}",
                            type="primary",
                            use_container_width=True,
                            disabled=not can_complete
                        ):
                            st.session_state["ISS_PENDING_ACTION"] = {
                                "action": "complete",
                                "card_uid": card_uid,
                                "placement_id": placement_id,
                                "session_id": None,
                                "log_date": date_str,
                                "completed_by": "Admin",
                                "day_type": "Full Day",
                                "start_period": 1,
                                "end_period": 10,
                                "points_earned": total_points,
                                "is_present": True,
                            }
                            st.rerun()
                        if not can_complete:
                            st.caption(f"Requires {full_day_required_points}+ points")
                    
                    with col_override:
                        # Initialize session state for override modal
                        override_key = f"show_override_{card_uid}"
                        if override_key not in st.session_state:
                            st.session_state[override_key] = False
                        
                        if st.button("⚡ Override", key=f"override_btn_{card_uid}", use_container_width=True):
                            st.session_state[override_key] = True
                            st.rerun()
                    
                    # Override panel (shown when Override button is clicked)
                    if st.session_state.get(override_key, False):
                        st.warning(f"**Override: Complete with full {full_day_periods}-period credit**")
                        override_note = st.text_area(
                            "Reason for Override (required)",
                            key=f"override_note_{card_uid}",
                            placeholder="Enter reason for early release with full credit...",
                            height=80
                        )
                        
                        col_confirm, col_cancel = st.columns(2)
                        with col_confirm:
                            if st.button("Confirm Override", key=f"confirm_override_{card_uid}", use_container_width=True):
                                if not override_note or not override_note.strip():
                                    st.error("Override reason is required.")
                                else:
                                    st.session_state["ISS_PENDING_ACTION"] = {
                                        "action": "override",
                                        "card_uid": card_uid,
                                        "placement_id": placement_id,
                                        "session_id": None,
                                        "log_date": date_str,
                                        "completed_by": "Admin",
                                        "points_earned": total_points,
                                        "override_note": override_note.strip(),
                                        "is_present": True,
                                    }
                                    st.session_state[override_key] = False
                                    st.rerun()
                        with col_cancel:
                            if st.button("Cancel", key=f"cancel_override_{card_uid}", use_container_width=True):
                                st.session_state[override_key] = False
                                st.rerun()
                    
                    # Convert to Partial Day section (for early departures)
                    st.markdown("---")
                    convert_key = f"show_convert_partial_{placement_id}_{date_str}"
                    if convert_key not in st.session_state:
                        st.session_state[convert_key] = False
                    
                    if not st.session_state.get(convert_key, False):
                        if st.button("🔄 Convert to Partial Day", key=f"convert_btn_{placement_id}_{date_str}", 
                                    use_container_width=True, help="Use if student leaves early"):
                            st.session_state[convert_key] = True
                            st.rerun()
                    else:
                        st.warning("**Convert to Partial Day**")
                        st.caption("Convert today's Full ISS Day into a Partial Day. Specify which periods the student actually served.")
                        
                        col_start, col_end = st.columns(2)
                        with col_start:
                            convert_start = st.selectbox(
                                "Start Period",
                                options=list(range(1, 11)),
                                index=0,
                                key=f"convert_start_{placement_id}_{date_str}"
                            )
                        with col_end:
                            convert_end = st.selectbox(
                                "End Period",
                                options=list(range(1, 11)),
                                index=min(convert_start - 1, 9) if convert_start else 0,
                                key=f"convert_end_{placement_id}_{date_str}"
                            )
                        
                        # Validate end >= start
                        valid_range = convert_end >= convert_start
                        if not valid_range:
                            st.error("End period must be >= start period")
                        
                        convert_periods = convert_end - convert_start + 1 if valid_range else 0
                        st.info(f"This will set the session to **{convert_periods} periods** (periods {convert_start}-{convert_end})")
                        st.caption(f"Points earned so far: {total_points} · New target: {convert_periods} points")
                        
                        col_confirm_conv, col_cancel_conv = st.columns(2)
                        with col_confirm_conv:
                            if st.button("Confirm Conversion", key=f"confirm_convert_{placement_id}_{date_str}",
                                        type="primary", use_container_width=True, disabled=not valid_range):
                                success = dm.convert_full_day_to_partial(
                                    placement_id, date_str, 
                                    start_period=convert_start, 
                                    end_period=convert_end
                                )
                                if success:
                                    st.session_state[convert_key] = False
                                    st.rerun()
                        with col_cancel_conv:
                            if st.button("Cancel", key=f"cancel_convert_{placement_id}_{date_str}", use_container_width=True):
                                st.session_state[convert_key] = False
                                st.rerun()
                
                elif is_checked_in and day_type == 'partial':
                    # Show Partial Day ISS Session Panel
                    is_makeup_session = daily_log.get('isMakeupSession', False)
                    
                    if is_makeup_session or is_makeup_day:
                        st.markdown("### 📋 Make-Up Partial Day Session")
                        st.info(f"**{iss_days_assigned}-day ISS Session for {student_name}** · Make-Up Session")
                    else:
                        st.markdown("### 📋 Partial Day ISS Session")
                        st.info(f"**{iss_days_assigned}-day ISS Session for {student_name}** · Day {current_day} of {iss_days_assigned} ISS Session")
                    
                    # Get stored period values from daily log (set during check-in)
                    start_period = daily_log.get('startPeriod') or 1
                    end_period = daily_log.get('endPeriod') or 10
                    required_points = daily_log.get('requiredPoints') or (end_period - start_period + 1)
                    
                    # Display period info (read-only since already checked in)
                    periods_count = end_period - start_period + 1
                    st.markdown(f"**Periods:** {start_period} to {end_period} ({periods_count} periods)")
                    
                    # Show remaining periods after this session
                    periods_after_this_session = remaining_periods - periods_count
                    if periods_after_this_session > 0:
                        st.warning(f"🔢 **After this session, {periods_after_this_session} periods will still be needed**")
                    
                    # Prominently display required points
                    st.success(f"**Required Points for this Session: {required_points}**")
                    
                    st.markdown("---")
                    
                    # Behaviors section
                    col_left, col_right = st.columns([1, 1])
                    
                    with col_left:
                        st.markdown("**Behaviors**")
                        # Positive behaviors dropdown
                        positive_menu = ps.get_positive_point_menu()
                        positive_options = ["-- Add Positive --"] + [item['label'] for item in positive_menu]
                        selected_positive = st.selectbox(
                            "Positive",
                            positive_options,
                            key=f"pos_partial_{placement_id}_{date_str}",
                            label_visibility="collapsed"
                        )
                        
                        if selected_positive != "-- Add Positive --":
                            item = next((i for i in positive_menu if i['label'] == selected_positive), None)
                            if item:
                                dm.add_point_event({
                                    'placementId': placement_id,
                                    'studentId': student['_id'],
                                    'code': item['code'],
                                    'type': 'positive',
                                    'value': item['value'],
                                    'date': date_str
                                })
                                # Reset dropdown to prevent ghost point on rerun
                                st.session_state[f"pos_partial_{placement_id}_{date_str}"] = "-- Add Positive --"
                                st.rerun()
                        
                        # Negative behaviors dropdown
                        negative_menu = ps.get_negative_point_menu()
                        negative_options = ["-- Add Negative --"] + [item['label'] for item in negative_menu]
                        selected_negative = st.selectbox(
                            "Negative",
                            negative_options,
                            key=f"neg_partial_{placement_id}_{date_str}",
                            label_visibility="collapsed"
                        )
                        
                        if selected_negative != "-- Add Negative --":
                            item = next((i for i in negative_menu if i['label'] == selected_negative), None)
                            if item:
                                dm.add_point_event({
                                    'placementId': placement_id,
                                    'studentId': student['_id'],
                                    'code': item['code'],
                                    'type': 'negative',
                                    'value': item['value'],
                                    'date': date_str
                                })
                                # Reset dropdown to prevent ghost point on rerun
                                st.session_state[f"neg_partial_{placement_id}_{date_str}"] = "-- Add Negative --"
                                st.rerun()
                    
                    with col_right:
                        st.markdown("**Points Total**")
                        if total_points >= required_points:
                            st.markdown(f"<h2 style='color: green;'>{total_points} / {required_points}</h2>", unsafe_allow_html=True)
                            st.caption(f"Meets target ({required_points} pts for {periods_count} periods)")
                        else:
                            st.markdown(f"<h2>{total_points} / {required_points}</h2>", unsafe_allow_html=True)
                            st.caption(f"Need {required_points - total_points} more ({required_points} pts for {periods_count} periods)")
                    
                    # Notes for Partial Day session
                    st.caption("Session Notes")
                    render_auto_save_notes(
                        f"partialday_session_{placement_id}_{date_str}",
                        daily_log.get('notes', '') or '',
                        lambda notes: dm.update_daily_log_notes(placement_id, date_str, notes)
                    )
                    
                    st.markdown("---")
                    
                    # Complete and Override buttons for Partial Day session
                    col_complete, col_override = st.columns(2)
                    
                    with col_complete:
                        can_complete = total_points >= required_points
                        if st.button("✅ Complete", key=f"complete_partial_{placement_id}_{date_str}", type="primary", 
                                     use_container_width=True, disabled=not can_complete):
                            dm.complete_iss_partial_day_session(
                                placement_id, date_str, "Admin",
                                start_period=start_period,
                                end_period=end_period,
                                required_points=required_points,
                                points_earned=total_points
                            )
                            # Check if make-up is needed after completing
                            makeup_check = dm.check_iss_session_needs_makeup_strict(placement_id)
                            if makeup_check.get('needsMakeup', False):
                                st.session_state[f"show_makeup_prompt_{placement_id}"] = True
                                st.session_state[f"makeup_info_{placement_id}"] = makeup_check
                            st.rerun()
                        if not can_complete:
                            st.caption(f"Requires {required_points}+ points")
                    
                    with col_override:
                        # Initialize session state for override modal
                        override_key = f"show_partial_override_{placement_id}_{date_str}"
                        if override_key not in st.session_state:
                            st.session_state[override_key] = False
                        
                        if st.button("⚡ Override", key=f"override_partial_btn_{placement_id}_{date_str}", use_container_width=True):
                            st.session_state[override_key] = True
                            st.rerun()
                    
                    # Override panel (shown when Override button is clicked)
                    if st.session_state.get(f"show_partial_override_{placement_id}_{date_str}", False):
                        st.warning(f"**Override: Complete with full {planned_periods}-period credit**")
                        override_note = st.text_area(
                            "Reason for Override (required)",
                            key=f"override_partial_note_{placement_id}_{date_str}",
                            placeholder="Enter reason for override...",
                            height=80
                        )
                        
                        col_confirm, col_cancel = st.columns(2)
                        with col_confirm:
                            if st.button("Confirm Override", key=f"confirm_partial_override_{placement_id}_{date_str}", 
                                        type="primary", use_container_width=True, disabled=not override_note.strip()):
                                dm.complete_iss_partial_day_session(
                                    placement_id, date_str, "Admin",
                                    start_period=start_period,
                                    end_period=end_period,
                                    required_points=required_points,
                                    is_override=True,
                                    override_note=override_note.strip(),
                                    points_earned=total_points
                                )
                                st.session_state[f"show_partial_override_{placement_id}_{date_str}"] = False
                                # Check if make-up is needed after completing
                                makeup_check = dm.check_iss_session_needs_makeup_strict(placement_id)
                                if makeup_check.get('needsMakeup', False):
                                    st.session_state[f"show_makeup_prompt_{placement_id}"] = True
                                    st.session_state[f"makeup_info_{placement_id}"] = makeup_check
                                st.rerun()
                        with col_cancel:
                            if st.button("Cancel", key=f"cancel_partial_override_{placement_id}_{date_str}", use_container_width=True):
                                st.session_state[f"show_partial_override_{placement_id}_{date_str}"] = False
                                st.rerun()
                
                elif is_checked_in:
                    # Student is checked in but without specific day type (legacy)
                    st.info("📍 Student checked in for today")
                else:
                    # Not checked in - show check-in buttons
                    # Check if partial day form should be shown
                    show_partial_form_key = f"show_partial_form_{placement_id}_{date_str}"
                    
                    if st.session_state.get(show_partial_form_key, False):
                        # Show Partial Day period selection form
                        st.markdown("#### Select Periods for Partial Day")
                        
                        col_start, col_end = st.columns(2)
                        with col_start:
                            partial_start = st.selectbox(
                                "Start Period",
                                options=list(range(1, 11)),
                                index=0,
                                key=f"partial_start_{placement_id}_{date_str}"
                            )
                        with col_end:
                            # End period must be >= start period
                            end_options = list(range(partial_start, 11))
                            partial_end = st.selectbox(
                                "End Period",
                                options=end_options,
                                index=len(end_options) - 1,
                                key=f"partial_end_{placement_id}_{date_str}"
                            )
                        
                        # Calculate and display periods covered and required points
                        periods_count = partial_end - partial_start + 1
                        st.info(f"**Periods Covered:** {periods_count} (Period {partial_start} to {partial_end})")
                        st.markdown(f"**Required Points for this Session:** {periods_count}")
                        
                        col_confirm, col_cancel = st.columns(2)
                        with col_confirm:
                            if st.button("Confirm Check-In", key=f"confirm_partial_{placement_id}_{date_str}", 
                                        type="primary", use_container_width=True):
                                dm.check_in_student(placement_id, date_str, day_type='partial',
                                                   start_period=partial_start, end_period=partial_end,
                                                   is_makeup=needs_makeup)
                                st.session_state[show_partial_form_key] = False
                                clear_dashboard_caches()  # Clear cache to show fresh partial day data
                                st.rerun()
                        with col_cancel:
                            if st.button("Cancel", key=f"cancel_partial_{placement_id}_{date_str}", 
                                        use_container_width=True):
                                st.session_state[show_partial_form_key] = False
                                st.rerun()
                    else:
                        # Show check-in buttons
                        col_checkin1, col_checkin2 = st.columns(2)
                        with col_checkin1:
                            # Adjust button label for make-up sessions
                            btn_label = "Make-Up – Full Day" if needs_makeup else "Check-In – Full Day"
                            if st.button(btn_label, key=f"checkin_full_{placement_id}_{date_str}", type="primary", use_container_width=True):
                                dm.check_in_student(placement_id, date_str, day_type='full', is_makeup=needs_makeup)
                                clear_dashboard_caches()  # Clear cache to show fresh check-in data
                                st.rerun()
                        with col_checkin2:
                            # Adjust button label for make-up sessions
                            btn_label = "Make-Up – Partial Day" if needs_makeup else "Check-In – Partial Day"
                            if st.button(btn_label, key=f"checkin_partial_{placement_id}_{date_str}", use_container_width=True):
                                # Show partial day form instead of immediately checking in
                                st.session_state[show_partial_form_key] = True
                                st.rerun()
            
            # Make-up prompt - OUTSIDE the if not is_session_complete block
            # Shows after final day completion when periods are short
            if st.session_state.get(f"show_makeup_prompt_{placement_id}", False):
                makeup_info = st.session_state.get(f"makeup_info_{placement_id}", {})
                periods_remaining = makeup_info.get('periodsRemaining', 0)
                periods_served = makeup_info.get('periodsServed', None)
                periods_required = makeup_info.get('periodsRequired', None)

                # Friendly display (avoid showing 'None' if the dict came from a non-strict source)
                periods_served_display = periods_served if periods_served is not None else "\u2014"
                periods_required_display = periods_required if periods_required is not None else "\u2014"

                # Initialize session state for schedule builder
                schedule_builder_key = f"show_makeup_builder_{placement_id}"
                if schedule_builder_key not in st.session_state:
                    st.session_state[schedule_builder_key] = False
                
                # Show schedule builder if "Yes" was clicked
                if st.session_state.get(schedule_builder_key, False):
                    st.info("**ISS Make-Up Days – Add additional dates and periods to complete remaining time.**")
                    st.caption(f"Periods remaining: **{periods_remaining}**")
                    
                    # Date picker for make-up dates
                    makeup_dates_key = f"makeup_dates_{placement_id}"
                    if makeup_dates_key not in st.session_state:
                        st.session_state[makeup_dates_key] = []
                    
                    # Add new make-up date form
                    st.markdown("**Add Make-Up Date:**")
                    col_date, col_type = st.columns(2)
                    with col_date:
                        min_date = central_today() + timedelta(days=1)
                        new_makeup_date = st.date_input(
                            "Select date",
                            min_value=min_date,
                            value=min_date,
                            key=f"new_makeup_date_{placement_id}"
                        )
                    with col_type:
                        makeup_day_type = st.selectbox(
                            "Day type",
                            ["Full Day (10 periods)", "Partial Day"],
                            key=f"makeup_day_type_{placement_id}"
                        )
                    
                    # Show period selectors for partial day
                    start_p, end_p = 1, 10
                    if makeup_day_type == "Partial Day":
                        col_start, col_end = st.columns(2)
                        with col_start:
                            start_p = st.number_input("Start period", min_value=1, max_value=10, value=1, 
                                                      key=f"makeup_start_{placement_id}")
                        with col_end:
                            end_p = st.number_input("End period", min_value=1, max_value=10, value=10,
                                                    key=f"makeup_end_{placement_id}")
                    
                    # Add date button
                    if st.button("➕ Add Date", key=f"add_makeup_date_{placement_id}"):
                        day_type_val = 'full' if makeup_day_type.startswith("Full") else 'partial'
                        new_entry = {
                            'date': new_makeup_date.isoformat(),
                            'day_type': day_type_val,
                            'start_period': start_p if day_type_val == 'partial' else 1,
                            'end_period': end_p if day_type_val == 'partial' else 10
                        }
                        if makeup_dates_key not in st.session_state:
                            st.session_state[makeup_dates_key] = []
                        st.session_state[makeup_dates_key].append(new_entry)
                        st.rerun()
                    
                    # Display added dates
                    if st.session_state.get(makeup_dates_key):
                        st.markdown("**Scheduled Make-Up Dates:**")
                        for i, entry in enumerate(st.session_state[makeup_dates_key]):
                            entry_date = datetime.fromisoformat(entry['date']).strftime('%B %d, %Y')
                            if entry['day_type'] == 'full':
                                period_info = "Full Day (10 periods)"
                            else:
                                period_info = f"Periods {entry['start_period']}–{entry['end_period']}"
                            col_info, col_remove = st.columns([4, 1])
                            with col_info:
                                st.caption(f"• {entry_date}: {period_info}")
                            with col_remove:
                                if st.button("🗑️", key=f"remove_makeup_{placement_id}_{i}"):
                                    st.session_state[makeup_dates_key].pop(i)
                                    st.rerun()
                    
                    # Save and Cancel buttons
                    col_save, col_cancel = st.columns(2)
                    with col_save:
                        save_disabled = not st.session_state.get(makeup_dates_key)
                        if st.button("💾 Save Make-Up Schedule", key=f"save_makeup_{placement_id}", 
                                    type="primary", use_container_width=True, disabled=save_disabled):
                            result = dm.add_iss_makeup_dates(placement_id, st.session_state[makeup_dates_key])
                            if result.get('success'):
                                st.session_state[f"show_makeup_prompt_{placement_id}"] = False
                                st.session_state[schedule_builder_key] = False
                                st.session_state[makeup_dates_key] = []
                                st.success(result.get('message', 'Make-up dates added!'))
                                if hasattr(st, 'cache_data'):
                                    st.cache_data.clear()
                                st.rerun()
                            else:
                                st.error(result.get('message', 'Failed to add make-up dates'))
                    with col_cancel:
                        if st.button("Cancel", key=f"cancel_makeup_builder_{placement_id}", use_container_width=True):
                            st.session_state[schedule_builder_key] = False
                            st.session_state[makeup_dates_key] = []
                            st.rerun()
                else:
                    # Show initial prompt
                    st.warning(f"""
                    **Make-up time needed**
                    
                    The original ISS session is complete, but the credited periods are short.
                    
                    - Expected: **{periods_required_display}** periods
                    - Credited: **{periods_served_display}** periods
                    - Short by: **{periods_remaining}** periods
                    """)
                    
                    col_yes, col_no, col_close = st.columns(3)
                    with col_yes:
                        if st.button("✅ Yes, add make-up days", key=f"yes_makeup_main_{placement_id}", 
                                    type="primary", use_container_width=True):
                            st.session_state[schedule_builder_key] = True
                            st.rerun()
                    
                    with col_no:
                        if st.button("⏸️ No, not now", key=f"no_makeup_main_{placement_id}", 
                                    use_container_width=True):
                            dm.keep_iss_session_open_for_makeup(placement_id)
                            st.session_state[f"show_makeup_prompt_{placement_id}"] = False
                            st.info("Case kept open. You can add make-up days later.")
                            st.rerun()
                    
                    with col_close:
                        close_key = f"show_close_early_main_{placement_id}"
                        if close_key not in st.session_state:
                            st.session_state[close_key] = False
                        
                        if st.button("❌ Close case anyway", key=f"close_early_main_btn_{placement_id}", 
                                    use_container_width=True):
                            st.session_state[close_key] = True
                            st.rerun()
                    
                    if st.session_state.get(f"show_close_early_main_{placement_id}", False):
                        st.info("**Close Case Early**")
                        close_note = st.text_area(
                            "Reason for closing early (optional):",
                            key=f"close_early_main_note_{placement_id}",
                            placeholder="Session closed early — remaining periods waived by staff judgment.",
                            height=80
                        )
                        
                        col_confirm_close, col_cancel_close = st.columns(2)
                        with col_confirm_close:
                            if st.button("Confirm Close", key=f"confirm_close_main_{placement_id}", 
                                        type="primary", use_container_width=True):
                                note = close_note.strip() if close_note.strip() else "Session closed early — remaining periods waived by staff judgment."
                                dm.close_iss_session_early(placement_id, note)
                                st.session_state[f"show_makeup_prompt_{placement_id}"] = False
                                st.session_state[f"show_close_early_main_{placement_id}"] = False
                                st.success(f"Case closed. {periods_remaining} periods waived.")
                                st.rerun()
                        with col_cancel_close:
                            if st.button("Cancel", key=f"cancel_close_main_{placement_id}", use_container_width=True):
                                st.session_state[f"show_close_early_main_{placement_id}"] = False
                                st.rerun()
            
            # Notes (always visible with auto-save, safe access - daily_log may be None)
            st.caption("Notes")
            render_auto_save_notes(
                f"fullday_{placement_id}_{date_str}",
                (daily_log.get('notes', '') if daily_log else '') or '',
                lambda notes: dm.update_daily_log_notes(placement_id, date_str, notes)
            )
            
            st.divider()
    
    # Helper function to render ISS Partial Day student card
    def render_iss_partial_card(placement: dict, target_date: date):
        """Render ISS Partial Day card with periods, points, and behaviors.
        
        Uses lazy loading for daily logs.
        """
        from utils import get_daily_status_color
        
        student = placement['student']
        placement_id = placement['_id']
        student_name = f"{student['firstName']} {student['lastName']}"
        date_str = target_date.isoformat()
        
        # LAZY LOADING: Only fetch daily log if it exists (read-only check)
        daily_log = dm.get_daily_log(placement_id, date_str)
        
        if daily_log:
            fulfillment = daily_log.get('dailyFulfillment') or ''
            status_color = get_daily_status_color(fulfillment, date_str)
        else:
            fulfillment = ''
            status_color = 'yellow'  # Default to yellow (pending)
        status_icon = {'green': '🟢', 'yellow': '🟡', 'red': '🔴'}.get(status_color, '⚪')
        
        # Get periods
        start_period = placement.get('startPeriod', 'N/A')
        end_period = placement.get('endPeriod', 'N/A')
        if start_period == end_period:
            period_label = f"Period {start_period}"
        else:
            period_label = f"Periods {start_period}–{end_period}"
        
        # Get points (lazy loading - only fetch if needed for display)
        point_events = dm.get_point_events_for_date(placement_id, date_str)
        total_points = sum([e['value'] for e in point_events])
        
        # Check completion status (safe access - daily_log may be None)
        is_completed = fulfillment == 'yes'
        
        with st.container():
            col1, col2, col3 = st.columns([3, 1, 1])
            
            with col1:
                st.markdown(f"**{status_icon} {student_name}**")
            
            with col2:
                st.caption(f"Grade {student.get('grade', 'N/A')}")
            
            with col3:
                # Disable Complete until checked in for the day
                is_checked_in = daily_log.get('checkedIn', False) if daily_log else False
                complete_disabled = not is_checked_in
                complete_help = "Check in required before completing" if complete_disabled else None

                if not is_completed:
                    if st.button(
                        "✓ Complete",
                        key=f"complete_{placement_id}_{date_str}",
                        type="primary",
                        disabled=complete_disabled,
                        help=complete_help
                    ):
                        dm.complete_placement_day(placement_id, date_str, "Admin")
                        st.rerun()
                else:
                    st.success("Completed")
            
            st.caption(f"📚 {period_label}")
            # Get required points from daily_log (authoritative) with fallback to calculated
            if daily_log and daily_log.get('requiredPoints'):
                required_points = daily_log.get('requiredPoints')
            elif start_period != 'N/A' and end_period != 'N/A':
                required_points = end_period - start_period + 1
            else:
                required_points = 1  # Default
            st.caption(f"Points: {total_points} / {required_points}")
            
            # Notes (always visible with auto-save, safe access - daily_log may be None)
            st.caption("Notes")
            render_auto_save_notes(
                f"partial_{placement_id}_{date_str}",
                (daily_log.get('notes', '') if daily_log else '') or '',
                lambda notes: dm.update_daily_log_notes(placement_id, date_str, notes)
            )
            
            st.divider()
    
    # ---------------------------------------------------------------------
    # Shared UI helpers — Standardized FUTURE-DATE expanded card content
    # (UI-only; does not change any underlying logic)
    # ---------------------------------------------------------------------
    def _ordinal_suffix_shared(day: int) -> str:
        if 11 <= day <= 13:
            return 'th'
        return {1: 'st', 2: 'nd', 3: 'rd'}.get(day % 10, 'th')

    def _format_date_with_ordinal_shared(d: date) -> str:
        day_num = d.day
        return f"{d.strftime('%b')}. {day_num}{_ordinal_suffix_shared(day_num)}, {d.year}"

    def _format_grade_homeroom_line(grade, homeroom) -> str:
        grade_str = str(grade) if grade is not None else "N/A"
        if homeroom:
            return f"Grade {grade_str} · {homeroom}"
        return f"Grade {grade_str}"

    def _render_standard_future_day_expanded_view(
        *,
        progress_status: str,
        title_line: str,
        grade,
        homeroom,
        lock_until_date: date
    ) -> None:
        """
        Standard future-day expanded view:
          Status line
          Title line (bold)
          Grade/Homeroom line
          Blue info bar lock message
        """
        # For future dates we intentionally do NOT infer day-level absent/completed.
        progress_circle = _circle_for_day(progress_status, is_absent_day=False, is_day_completed=False)
        progress_text = _status_text_for_day(progress_status, is_absent_day=False, is_day_completed=False)

        st.markdown(f"**Status:** {progress_circle} {progress_text}")
        st.markdown(f"**{title_line}**")
        st.caption(_format_grade_homeroom_line(grade, homeroom))

        formatted_lock_date = _format_date_with_ordinal_shared(lock_until_date)
        st.info(f"🔒 Locked until {formatted_lock_date}")

    # Helper function to render Lunch Detention student card
    def render_lunch_detention_card(placement: dict, target_date: date):
        """Render Lunch Detention card with attendance and Day X of Y.
        
        Uses lazy loading for daily logs.
        """
        from utils import get_daily_status_color
        
        student = placement['student']
        placement_id = placement['_id']
        student_name = f"{student['firstName']} {student['lastName']}"
        date_str = target_date.isoformat()

        # Card UID for keep-open pattern
        card_uid = f"ld_{placement_id}_{date_str}"
        
        # FUTURE PLACEMENT LOCK: disable Check In until the start date
        placement_status = placement.get('status', 'active')
        start_date_str = placement.get('startDate')
        is_future_placement = False
        start_date_obj = None
        if start_date_str:
            try:
                start_date_obj = datetime.fromisoformat(start_date_str).date()
                is_future_placement = start_date_obj > central_today()
            except Exception:
                is_future_placement = False

        if placement_status == 'scheduled' and start_date_obj and start_date_obj > central_today():
            is_future_placement = True

        # Format start date for display with ordinal suffix (e.g., "Jan. 13th")
        def ordinal_suffix(day):
            if 11 <= day <= 13:
                return 'th'
            return {1: 'st', 2: 'nd', 3: 'rd'}.get(day % 10, 'th')
        
        if is_future_placement and start_date_obj:
            day = start_date_obj.day
            formatted_start_date = f"{start_date_obj.strftime('%b')}. {day}{ordinal_suffix(day)}, {start_date_obj.year}"
            future_checkin_msg = f"This session has not started yet. Check-in will be available on the start date: {formatted_start_date}."
        else:
            future_checkin_msg = "This session has not started yet. Check-in will be available on the start date."
        
        # ---------- BEGIN: ISS-style future-day and future-placement locks ----------
        def _format_date_with_ordinal(d: date) -> str:
            def _ordinal_suffix(day: int) -> str:
                if 11 <= day <= 13:
                    return 'th'
                return {1: 'st', 2: 'nd', 3: 'rd'}.get(day % 10, 'th')
            day_num = d.day
            return f"{d.strftime('%b')}. {day_num}{_ordinal_suffix(day_num)}, {d.year}"

        today = central_today()

        # A) FUTURE PLACEMENT LOCK (start date is in the future relative to today)
        if is_future_placement and start_date_obj:
            formatted_start_date = _format_date_with_ordinal(start_date_obj)
            st.info(
                f"This session has not started yet. "
                f"Check-in will be available on the start date: {formatted_start_date}."
            )
            return

        # B) FUTURE-DAY VIEW LOCK (dashboard date is in the future) - standardized UI
        if target_date > today:
            total_days = placement.get('daysAssigned', 1)
            if not total_days or total_days < 1:
                total_days = 1

            days_label = "Day" if total_days == 1 else "Days"
            title_line = f"{total_days}-{days_label} Lunch Detention"

            grade = student.get('grade', 'N/A')
            homeroom = student.get('homeroomTeacher', '')
            progress_status = placement.get('progressStatus', 'NOT_STARTED')

            _render_standard_future_day_expanded_view(
                progress_status=progress_status,
                title_line=title_line,
                grade=grade,
                homeroom=homeroom,
                lock_until_date=target_date
            )
            return
        # ---------- END: ISS-style future-day and future-placement locks ----------
        
        # Get progress status
        progress_status = placement.get('progressStatus', 'NOT_STARTED')
        
        # LAZY LOADING: Only fetch daily log if it exists (read-only check)
        daily_log = dm.get_daily_log(placement_id, date_str)
        
        # Use centralized helpers for day-level absent and completion status (pass pre-fetched daily_log)
        is_absent_day = _is_absent_for_date(dm, placement_id, date_str, daily_log=daily_log)
        is_day_completed = _is_day_completed_for_date(daily_log)
        
        # Use centralized helpers for circle and text
        progress_circle = _circle_for_day(progress_status, is_absent_day=is_absent_day, is_day_completed=is_day_completed)
        progress_text = _status_text_for_day(progress_status, is_absent_day=is_absent_day, is_day_completed=is_day_completed)
        
        # Display status line at top of expanded card (no student name)
        st.markdown(f"**Status:** {progress_circle} {progress_text}")
        
        # Display Grade + Homeroom Teacher
        grade = student.get('grade', 'N/A')
        homeroom = student.get('homeroomTeacher', '')
        if homeroom:
            st.caption(f"Grade {grade} — {homeroom}")
        else:
            st.caption(f"Grade {grade}")
        
        # Day X of Y for multi-day lunch detention (completion-based, not calendar-based)
        total_days = placement.get('daysAssigned', 0)
        days_served_info = dm.get_lunch_detention_days_served_info(placement_id, date_str)
        day_number = days_served_info.get('current_day_number', 1)
        is_today_absent = days_served_info.get('is_today_absent', False)
        
        # Lunch Detention check-in must reflect the DailyLog's checkedIn flag,
        # not merely the existence of a DailyLog (Absent creates a log too).
        is_checked_in = bool(daily_log and daily_log.get("checkedIn"))
        is_present = is_checked_in and (not is_absent_day)
        
        with st.container():
            # Check In + Absent controls
            # is_checked_in already computed from DailyLog existence above
            is_completed_day = daily_log.get('dailyFulfillment') == 'yes' if daily_log else False
            
            # Absent checkbox key
            absent_key = f"ld_absent_{placement_id}_{date_str}"
            absent_resched_key = f"ld_absent_resched_{placement_id}_{date_str}"
            db_absent = dm.is_marked_absent(placement_id, date_str)
            
            # Initialize session state from DB if not set
            if absent_key not in st.session_state:
                st.session_state[absent_key] = db_absent

            # Track whether the 1-day reschedule confirmation is pending/answered for this day
            # Values: None (no prompt), 'pending', 'no'
            if absent_resched_key not in st.session_state:
                st.session_state[absent_resched_key] = None
            
            # Absent checkbox - render FIRST so state is processed
            def handle_absent_change(pid=placement_id, ds=date_str, key=absent_key):
                new_val = st.session_state.get(key, False)
                if new_val:
                    dm.mark_absent(pid, ds)
                    # For 1-day Lunch Detention, trigger a one-time reschedule confirmation UI
                    if int(total_days or 1) == 1:
                        st.session_state[absent_resched_key] = 'pending'
                else:
                    dm.unmark_absent(pid, ds)
                    # Reset reschedule prompt state if absence is cleared
                    st.session_state[absent_resched_key] = None
            
            # Day X of Y (show for all placements, including single-day)
            display_total = max(total_days, 1)
            display_day = max(day_number, 1)
            st.caption(f"📅 Day {display_day} of {display_total}")
            
            # Check In / Absent controls in columns
            ctrl_col1, ctrl_col2 = st.columns(2)
            with ctrl_col1:
                absent_checked = st.checkbox(
                    "Absent",
                    key=absent_key,
                    disabled=is_checked_in or is_completed_day or is_future_placement,
                    on_change=handle_absent_change
                )
            
            with ctrl_col2:
                # is_absent uses the checkbox return value (current state after widget processing)
                is_absent = absent_checked
                
                # Check In button - disabled if already checked in, completed, or marked absent
                checkin_disabled = is_completed_day or is_checked_in or is_absent or is_future_placement
                if st.button("Check In", key=f"ld_checkin_{placement_id}_{date_str}", 
                           type="primary" if not checkin_disabled else "secondary",
                           disabled=checkin_disabled):
                    dm.update_lunch_detention_attendance(placement_id, date_str, True)
                    # Unmark absent in DB if was marked (mutual exclusivity)
                    dm.unmark_absent(placement_id, date_str)
                    clear_dashboard_caches()
                    _dashboard_request_keep_open(card_uid, ttl=2)
                    st.rerun()
                
                # Show future placement message (generic)
                if is_future_placement:
                    st.caption(future_checkin_msg)

            # ------------------------------------------------------------
            # 1-Day Lunch Detention: Absent → confirm reschedule to next school day
            # Option A: Original record closes with red circle + "Absent" subtitle.
            # ------------------------------------------------------------
            if is_absent and int(total_days or 1) == 1 and st.session_state.get(absent_resched_key) == 'pending':
                st.warning("Student marked absent for this 1-day Lunch Detention. Create the same placement for the next school day?")
                yn_col1, yn_col2 = st.columns(2)
                with yn_col1:
                    if st.button("Yes", key=f"{absent_resched_key}_yes", type="primary"):
                        dm.complete_and_clone_lunch_detention_absent(placement_id, date_str, actor="Admin")
                        st.session_state[absent_resched_key] = None
                        clear_dashboard_caches()
                        _dashboard_request_keep_open(card_uid, ttl=2)
                        st.rerun()
                with yn_col2:
                    if st.button("No", key=f"{absent_resched_key}_no"):
                        dm.close_lunch_detention_absent_no_clone(placement_id, date_str)
                        st.session_state[absent_resched_key] = None
                        clear_dashboard_caches()
                        _dashboard_request_keep_open(card_uid, ttl=2)
                        st.rerun()
            
            # Notes (always available + auto-saving)
            st.caption("Notes")
            render_auto_save_notes(
                f"lunch_{placement_id}_{date_str}",
                (daily_log.get('notes', '') if daily_log else '') or '',
                lambda notes: dm.update_daily_log_notes(placement_id, date_str, notes),
                disabled=False,
                help_text=None
            )

            # Complete button (safe access - daily_log may be None)
            is_completed = daily_log.get('dailyFulfillment') == 'yes' if daily_log else False

            # If 1-day LD is absent AND we're awaiting Yes/No, do not allow completion
            decision_pending = (int(total_days or 1) == 1) and (is_absent) and (st.session_state.get(absent_resched_key) == "pending")

            if not is_completed:
                # Safety guard: Absent 1-day LD should not be completable (closed via Yes/No flow)
                absent_one_day_ld = (int(total_days or 1) == 1) and is_absent_day
                complete_disabled = (not is_checked_in) or decision_pending or absent_one_day_ld

                if decision_pending:
                    complete_help = "Choose Yes/No for Absent before completing"
                elif absent_one_day_ld:
                    complete_help = "This day is marked Absent. Use the Yes/No prompt to close it."
                else:
                    complete_help = "Check in required before completing" if (not is_checked_in) else None

                if not decision_pending:
                    if st.button(
                        "✓ Complete",
                        key=f"complete_{placement_id}_{date_str}",
                        type="primary",
                        disabled=complete_disabled,
                        help=complete_help
                    ):
                        dm.complete_placement_day(placement_id, date_str, "Admin")
                        clear_dashboard_caches()
                        _dashboard_request_keep_open(card_uid, ttl=2)
                        st.rerun()
                else:
                    st.info("Absent is marked for a 1-day Lunch Detention. Please choose Yes/No above to close this record.")
            else:
                st.success("Completed")
            
            st.divider()
    
    # Unified helper function to render Class Period Referral student card (all subtypes)
    def render_unified_class_referral_card(placement: dict, target_date: date):
        """Render unified Class Period Referral card for all subtypes (Behavior, Cool-Down, Pre-Planned).
        
        Uses lazy loading for daily logs.
        """
        from utils import get_daily_status_color
        
        student = placement['student']
        placement_id = placement['_id']
        student_name = f"{student['firstName']} {student['lastName']}"
        date_str = target_date.isoformat()

        # Card UID for keep-open pattern
        card_uid = f"cpr_{placement_id}_{date_str}"
        
        # ------------------------------------------------------------
        # UI STANDARDIZATION FIX: Pre-Planned + future dashboard date
        # Render ONLY the standardized future-day block and return early
        # (prevents duplicate Status/Grade lines from shared CPR header)
        # ------------------------------------------------------------
        placement_type_early = placement.get('placementType', '').upper()
        referral_subtype_early = placement.get('referralSubtype', '')

        is_preplanned_early = (
            placement_type_early == 'PRE_PLANNED_REFERRAL'
            or str(referral_subtype_early).strip().lower() in {'pre_planned', 'pre-planned', 'preplanned', 'pre planned'}
        )

        today_early = central_today()
        if is_preplanned_early and target_date > today_early:
            progress_status_early = placement.get('progressStatus', 'NOT_STARTED')

            days_assigned = placement.get('daysAssigned', 1)
            if not days_assigned or days_assigned < 1:
                days_assigned = 1
            day_label = "Day" if days_assigned == 1 else "Days"
            title_line = f"{days_assigned}-{day_label} Pre-Planned Referral"

            grade_early = student.get('grade', 'N/A')
            homeroom_early = student.get('homeroomTeacher', '')

            _render_standard_future_day_expanded_view(
                progress_status=progress_status_early,
                title_line=title_line,
                grade=grade_early,
                homeroom=homeroom_early,
                lock_until_date=target_date
            )
            return
        
        # FUTURE PLACEMENT LOCK: disable Check In until the start date
        placement_status = placement.get('status', 'active')
        start_date_str = placement.get('startDate')
        is_future_placement = False
        start_date_obj = None
        if start_date_str:
            try:
                start_date_obj = datetime.fromisoformat(start_date_str).date()
                is_future_placement = start_date_obj > central_today()
            except Exception:
                is_future_placement = False

        if placement_status == 'scheduled' and start_date_obj and start_date_obj > central_today():
            is_future_placement = True

        # Default future check-in message (for Behavior and Cool-Down)
        future_checkin_msg = "This session has not started yet. Check-in will be available on the start date."
        
        # Get progress status
        progress_status = placement.get('progressStatus', 'NOT_STARTED')
        
        # LAZY LOADING: Only fetch daily log if it exists (read-only check)
        daily_log = dm.get_daily_log(placement_id, date_str)
        
        # Ensure is_checked_in is always defined (prevents UnboundLocalError after Complete/rerun paths)
        is_checked_in = bool(daily_log and daily_log.get('checkedIn', False))
        
        # Use centralized helpers for day-level absent and completion status (pass pre-fetched daily_log)
        is_absent_day = _is_absent_for_date(dm, placement_id, date_str, daily_log=daily_log)
        is_day_completed = _is_day_completed_for_date(daily_log)
        
        # Use centralized helpers for circle and text
        progress_circle = _circle_for_day(progress_status, is_absent_day=is_absent_day, is_day_completed=is_day_completed)
        progress_text = _status_text_for_day(progress_status, is_absent_day=is_absent_day, is_day_completed=is_day_completed)
        
        # Display status line at top of expanded card (no student name)
        st.markdown(f"**Status:** {progress_circle} {progress_text}")
        
        # Display Grade + Homeroom Teacher
        grade = student.get('grade', 'N/A')
        homeroom = student.get('homeroomTeacher', '')
        if homeroom:
            st.caption(f"Grade {grade} — {homeroom}")
        else:
            st.caption(f"Grade {grade}")
        
        if daily_log:
            fulfillment = daily_log.get('dailyFulfillment') or ''
            status_color = get_daily_status_color(fulfillment, date_str)
        else:
            fulfillment = ''
            status_color = 'yellow'  # Default to yellow (pending)
        
        # Determine subtype from placement data
        placement_type = placement.get('placementType', '').upper()
        referral_subtype = placement.get('referralSubtype', '')
        
        # Pre-Planned specific: Update future_checkin_msg with formatted start date
        if (placement_type == 'PRE_PLANNED_REFERRAL' or referral_subtype == 'pre_planned') and is_future_placement and start_date_obj:
            def ordinal_suffix(day):
                if 11 <= day <= 13:
                    return 'th'
                return {1: 'st', 2: 'nd', 3: 'rd'}.get(day % 10, 'th')
            day = start_date_obj.day
            formatted_start_date = f"{start_date_obj.strftime('%b')}. {day}{ordinal_suffix(day)}, {start_date_obj.year}"
            future_checkin_msg = f"Check-in will be available on: {formatted_start_date}"
        
        # Map to display names and determine subtype
        if placement_type == 'COOL_DOWN':
            subtype_display = "Cool-Down Referral"
            subtype_key = "cool_down"
        elif placement_type == 'PRE_PLANNED_REFERRAL':
            subtype_display = "Pre-Planned Referral"
            subtype_key = "pre_planned"
        elif referral_subtype == 'cool_down':
            subtype_display = "Cool-Down Referral"
            subtype_key = "cool_down"
        elif referral_subtype == 'pre_planned':
            subtype_display = "Pre-Planned Referral"
            subtype_key = "pre_planned"
        else:
            subtype_display = "Behavior Referral"
            subtype_key = "behavior"
        
        # ---------- BEGIN: ISS-style locks for Pre-Planned only ----------
        if subtype_key == "pre_planned":
            def _format_date_with_ordinal(d: date) -> str:
                def _ordinal_suffix(day: int) -> str:
                    if 11 <= day <= 13:
                        return 'th'
                    return {1: 'st', 2: 'nd', 3: 'rd'}.get(day % 10, 'th')
                day_num = d.day
                return f"{d.strftime('%b')}. {day_num}{_ordinal_suffix(day_num)}, {d.year}"

            today = central_today()

            # A) FUTURE PLACEMENT LOCK (start date is in the future relative to today)
            if is_future_placement and start_date_obj:
                formatted_start_date = _format_date_with_ordinal(start_date_obj)
                st.info(
                    f"This session has not started yet. "
                    f"Check-in will be available on the start date: {formatted_start_date}."
                )
                return

            # B) FUTURE-DAY VIEW LOCK (dashboard date is in the future) - standardized UI
            if target_date > today:
                days_assigned = placement.get('daysAssigned', 1)
                if not days_assigned or days_assigned < 1:
                    days_assigned = 1

                days_label = "Day" if days_assigned == 1 else "Days"
                title_line = f"{days_assigned}-{days_label} Pre-Planned Referral"

                grade = student.get('grade', 'N/A')
                homeroom = student.get('homeroomTeacher', '')

                _render_standard_future_day_expanded_view(
                    progress_status=progress_status,
                    title_line=title_line,
                    grade=grade,
                    homeroom=homeroom,
                    lock_until_date=target_date
                )
                return
        # ---------- END: ISS-style locks for Pre-Planned only ----------
        
        # Check if no-show is set (for Pre-Planned only, safe access - daily_log may be None)
        is_no_show = daily_log.get('noShow', False) if daily_log else False
        is_completed = fulfillment == 'yes'
        
        # Determine status icon
        if is_completed and is_no_show:
            status_icon = '🔴'  # Completed as No-Show
        elif is_completed:
            status_icon = '🟢'  # Completed
        else:
            status_icon = '🟡'  # In Progress
        
        # Get periods (different logic for Pre-Planned vs Behavior/Cool-Down)
        if subtype_key == 'pre_planned':
            # For Pre-Planned, get periods from scheduled slots for this date
            scheduled_slots = placement.get('scheduledSlots', [])
            periods_today = [slot['period'] for slot in scheduled_slots 
                           if slot.get('date') == date_str]
            if periods_today:
                periods_today.sort()
                if len(periods_today) == 1:
                    period_label = f"Period {periods_today[0]}"
                else:
                    # Check if consecutive
                    if periods_today == list(range(periods_today[0], periods_today[-1] + 1)):
                        period_label = f"Periods {periods_today[0]}–{periods_today[-1]}"
                    else:
                        period_label = f"Periods {', '.join(map(str, periods_today))}"
            else:
                period_label = "No periods scheduled"
        else:
            # For Behavior and Cool-Down, get periods from sessions table
            periods_today = dm.get_referral_periods_for_date(placement_id, target_date)
            if periods_today:
                if len(periods_today) == 1:
                    period_label = f"Period {periods_today[0]}"
                else:
                    # Check if consecutive
                    if periods_today == list(range(periods_today[0], periods_today[-1] + 1)):
                        period_label = f"Periods {periods_today[0]}–{periods_today[-1]}"
                    else:
                        period_label = f"Periods {', '.join(map(str, periods_today))}"
            else:
                # Fallback to startPeriod/endPeriod for backward compatibility
                start_period = placement.get('startPeriod', 'N/A')
                end_period = placement.get('endPeriod', 'N/A')
                if start_period == end_period:
                    period_label = f"Period {start_period}"
                else:
                    period_label = f"Periods {start_period}–{end_period}"
                periods_today = list(range(start_period, end_period + 1)) if isinstance(start_period, int) else []
        
        # Get reason
        reason = placement.get('reason', 'No reason provided')
        
        with st.container():
            # Subtype label
            if subtype_key == 'behavior':
                st.caption(f"📚 **{subtype_display}**")
            elif subtype_key == 'cool_down':
                st.caption(f"🧘 **{subtype_display}**")
            else:
                st.caption(f"📅 **{subtype_display}**")
            
            # Day X of Y for Pre-Planned referrals (show for all placements, including single-day)
            if subtype_key == 'pre_planned':
                days_assigned = placement.get('daysAssigned', 1)
                preplanned_days_info = dm.get_preplanned_days_served_info(placement_id, date_str)
                preplanned_day_number = max(preplanned_days_info.get('current_day_number', 1), 1)
                preplanned_total_days = max(preplanned_days_info.get('total_days', days_assigned), 1)
                preplanned_is_absent = preplanned_days_info.get('is_today_absent', False)
                if preplanned_is_absent:
                    st.caption(f"📅 Day {preplanned_day_number} of {preplanned_total_days} (Absent)")
                else:
                    st.caption(f"📅 Day {preplanned_day_number} of {preplanned_total_days}")
            
            # Reason
            st.caption(f"**Reason:** {reason}")
            
            # Periods (show for all subtypes)
            st.caption(f"📚 {period_label}")
            
            # Add Periods control (only for Behavior and Cool-Down, not completed)
            if subtype_key in ['behavior', 'cool_down'] and not is_completed:
                # Calculate available periods (periods not already assigned)
                all_periods = list(range(1, 11))  # P1-P10
                assigned_periods = periods_today if periods_today else []
                available_periods = [p for p in all_periods if p not in assigned_periods]
                
                if available_periods:
                    with st.expander("➕ Add Periods", expanded=False):
                        with st.form(key=f"add_periods_form_{placement_id}_{date_str}"):
                            st.caption("Select additional periods to add to this referral:")
                            
                            # Multi-select for available periods
                            selected_new_periods = st.multiselect(
                                "Available Periods",
                                options=available_periods,
                                format_func=lambda x: f"Period {x}",
                                label_visibility="collapsed"
                            )
                            
                            # Submit button for the form
                            submitted = st.form_submit_button("Add Selected Periods", type="secondary")
                            
                            if submitted:
                                if selected_new_periods:
                                    success = dm.add_periods_to_referral(placement_id, target_date, selected_new_periods)
                                    if success:
                                        # Clear caches and refresh
                                        clear_dashboard_caches()
                                        st.success(f"Added {len(selected_new_periods)} period(s)")
                                        st.rerun()
                                    else:
                                        st.error("Failed to add periods")
                                else:
                                    st.warning("Please select at least one period to add")
            
            st.markdown("---")
            
            # Completion controls - different by subtype
            if not is_completed:
                if subtype_key == 'behavior':
                    # Behavior Referral: Check In + Complete Referral (NO Absent - same-day placement)
                    is_checked_in = daily_log.get('checkedIn', False) if daily_log else False
                    
                    # Check In button
                    if is_checked_in:
                        st.success("✓ Checked In")
                    else:
                        if st.button(
                            "Check In",
                            key=f"checkin_behavior_{placement_id}_{date_str}",
                            type="primary",
                            disabled=is_future_placement,
                            help=("Check-in will be available on the start date." if is_future_placement else None)
                        ):
                            dm.checkin_referral(placement_id, date_str)
                            clear_dashboard_caches()
                            st.rerun()
                        
                        if is_future_placement:
                            st.caption(future_checkin_msg)
                    
                    # Complete Referral button (disabled until checked in)
                    complete_disabled = not is_checked_in
                    complete_help = "Check in required before completing" if complete_disabled else None

                    if st.button(
                        "Complete Referral",
                        key=f"complete_behavior_{placement_id}_{date_str}",
                        type="primary",
                        disabled=complete_disabled,
                        help=complete_help
                    ):
                        dm.complete_placement_day(placement_id, date_str, "Admin")
                        clear_dashboard_caches()
                        _dashboard_request_keep_open(card_uid, ttl=2)
                        st.rerun()
                
                elif subtype_key == 'cool_down':
                    # Cool-Down Referral: Check In + Complete Cool-Down (NO Absent - same-day placement)
                    is_checked_in = daily_log.get('checkedIn', False) if daily_log else False
                    
                    # Check In button
                    if is_checked_in:
                        st.success("✓ Checked In")
                    else:
                        if st.button(
                            "Check In",
                            key=f"checkin_cooldown_{placement_id}_{date_str}",
                            type="primary",
                            disabled=is_future_placement,
                            help=("Check-in will be available on the start date." if is_future_placement else None)
                        ):
                            dm.checkin_referral(placement_id, date_str)
                            clear_dashboard_caches()
                            st.rerun()
                        
                        if is_future_placement:
                            st.caption(future_checkin_msg)
                    
                    # Complete Cool-Down button (disabled until checked in)
                    complete_disabled = not is_checked_in
                    complete_help = "Check in required before completing" if complete_disabled else None

                    if st.button(
                        "Complete Cool-Down",
                        key=f"complete_cooldown_{placement_id}_{date_str}",
                        type="primary",
                        disabled=complete_disabled,
                        help=complete_help
                    ):
                        dm.complete_placement_day(placement_id, date_str, "Admin")
                        clear_dashboard_caches()
                        _dashboard_request_keep_open(card_uid, ttl=2)
                        st.rerun()
                
                elif subtype_key == 'pre_planned':
                    # Pre-Planned Referral: Check In + Absent + Complete workflow
                    # Special logic for one-day vs multi-day Pre-Planned
                    days_assigned = placement.get('daysAssigned', 1)
                    is_one_day = days_assigned == 1
                    
                    checkin_status = dm.get_preplanned_checkin_status(placement_id, date_str)
                    is_checked_in = checkin_status.get('checked_in', False)
                    checked_in_at = checkin_status.get('checked_in_at')
                    
                    # Absent checkbox key
                    absent_key = f"absent_preplanned_{placement_id}_{date_str}"
                    db_absent = dm.is_marked_absent(placement_id, date_str)
                    
                    # Initialize session state from DB if not set
                    if absent_key not in st.session_state:
                        st.session_state[absent_key] = db_absent
                    
                    # Render Absent checkbox FIRST (in its own column) so state is processed
                    col_absent, col_checkin = st.columns([1, 1])
                    
                    with col_absent:
                        # Absent checkbox with on_change callback for database sync
                        def handle_preplanned_absent(pid=placement_id, ds=date_str, key=absent_key, one_day=is_one_day):
                            new_val = st.session_state.get(key, False)
                            if new_val:
                                dm.mark_absent(pid, ds)
                                # For one-day Pre-Planned: auto-complete
                                if one_day:
                                    dm.complete_placement_as_absent(pid, ds)
                            else:
                                dm.unmark_absent(pid, ds)
                        
                        absent_checked = st.checkbox(
                            "Absent",
                            key=absent_key,
                            disabled=is_checked_in or is_future_placement,
                            on_change=handle_preplanned_absent
                        )
                    
                    # is_absent uses the checkbox return value (current state after widget processing)
                    is_absent = absent_checked
                    
                    with col_checkin:
                        if is_checked_in:
                            # Show check-in confirmation (no timestamp for Pre-Planned)
                            st.success("✓ Checked In")
                        else:
                            # Show Check In button - disabled if absent or future placement
                            checkin_disabled = is_absent or is_future_placement
                            if st.button("Check In", key=f"checkin_preplanned_{placement_id}_{date_str}", 
                                       type="primary" if not checkin_disabled else "secondary",
                                       disabled=checkin_disabled):
                                dm.checkin_preplanned_session(placement_id, date_str)
                                clear_dashboard_caches()
                                st.rerun()
                            
                            if is_future_placement:
                                st.caption(future_checkin_msg)
                    
                    # For multi-day Pre-Planned when marked absent: show skip message
                    if is_absent and not is_one_day:
                        st.warning("⚠️ Student marked absent for this day. Day will be skipped and resumed on next scheduled date.")
                    
                    # Complete button - disabled until checked in
                    # Hide for one-day when absent (auto-completed above)
                    if not (is_one_day and is_absent):
                        complete_disabled = not is_checked_in
                        complete_help = "Check in required before completing" if complete_disabled else None

                        if st.button(
                            "Complete",
                            key=f"complete_preplanned_{placement_id}_{date_str}",
                            type="primary",
                            disabled=complete_disabled,
                            help=complete_help
                        ):
                            dm.complete_preplanned_session(placement_id, date_str, "Admin")
                            clear_dashboard_caches()
                            st.rerun()
            else:
                # Show completed status for all subtypes
                if subtype_key == 'pre_planned':
                    # For Pre-Planned, show Attended or Absent based on check-in
                    was_checked_in = daily_log.get('checkedIn', False) if daily_log else False
                    if is_no_show or not was_checked_in:
                        st.error("Completed — Absent")
                    else:
                        st.success("Completed — Attended")
                elif is_no_show:
                    st.success("Completed (No Show)")
                    no_show_note = daily_log.get('noShowNote', '')
                    if no_show_note:
                        st.caption(f"📝 {no_show_note}")
                else:
                    st.success("Completed")
            
            # Notes (always available + auto-saving)
            st.caption("Notes")
            render_auto_save_notes(
                f"classref_{placement_id}_{date_str}",
                (daily_log.get('notes', '') if daily_log else '') or '',
                lambda notes: dm.update_daily_log_notes(placement_id, date_str, notes),
                disabled=False,
                help_text=None
            )
            
            st.divider()
    
    # Helper function to render enhanced ISS session card
    def render_iss_session_card(iss_session: dict, target_date: date):
        """Render enhanced ISS session card with full functionality.
        
        Handles three states:
        - Future (scheduled): Locked card with disabled Check In
        - Active: Fully interactive card
        - Completed: Shows completion status
        """
        session_id = iss_session['session_id']
        placement_id = iss_session['placement_id']
        student_id = iss_session['student_id']
        student_name = iss_session['student_name']
        date_str = iss_session['date']
        
        # Unique per-card namespace (prevents key collisions for full-day ISS where session_id can be None)
        session_key = session_id if session_id is not None else "full"
        card_uid = f"{placement_id}_{session_key}_{date_str}"
        
        # Debug fingerprint for ISS points logging
        card_fp = f"student={student_name}|placement={placement_id}|session={session_id}|date={date_str}"
        
        periods = iss_session.get('periods', list(range(1, 11)))
        is_full_day = len(periods) == 10 and periods == list(range(1, 11))
        is_past_session = target_date < central_today()
        
        # Check if this is a future-dated (scheduled) placement
        placement_status = iss_session.get('placement_status', 'active')
        start_date_str = iss_session.get('start_date')
        is_future_placement = False
        start_date_obj = None
        if start_date_str:
            start_date_obj = datetime.fromisoformat(start_date_str).date()
            is_future_placement = start_date_obj > central_today()
        
        # Also check placement_status for scheduled (but only if start date is actually in the future)
        if placement_status == 'scheduled' and start_date_obj and start_date_obj > central_today():
            is_future_placement = True
        
        # If this is a future-dated placement, show locked card
        if is_future_placement:
            # Get ISS days for the label
            placement_data = dm.get_placement(placement_id)
            iss_total_days = placement_data.get('issTotalDays', 1) if placement_data else 1
            if iss_total_days is None:
                iss_total_days = 1
            
            # Format start date for display with ordinal suffix (e.g., "Jan. 13th, 2026")
            def ordinal_suffix(day):
                if 11 <= day <= 13:
                    return 'th'
                return {1: 'st', 2: 'nd', 3: 'rd'}.get(day % 10, 'th')
            
            if start_date_obj:
                day = start_date_obj.day
                formatted_start_date = f"{start_date_obj.strftime('%b')}. {day}{ordinal_suffix(day)}, {start_date_obj.year}"
            else:
                formatted_start_date = 'Unknown'
            
            with st.container():
                # Grayed-out header
                st.markdown(f"<div style='opacity: 0.6;'>", unsafe_allow_html=True)
                
                header_col1, header_col2 = st.columns([3, 1])
                
                with header_col1:
                    days_label = "Day" if iss_total_days == 1 else "Days"
                    st.markdown(f"**{iss_total_days}-{days_label} ISS Session**")
                    st.caption(f"Grade {iss_session.get('grade', 'N/A')} · {iss_session.get('homeroom_teacher', 'N/A')}")
                
                with header_col2:
                    # Disabled Check In button
                    st.button("Check In", key=f"iss_checkin_{card_uid}", disabled=True)
                
                st.caption(f"This session has not started yet. Check-in will be available on the start date: {formatted_start_date}.")
                
                st.markdown("</div>", unsafe_allow_html=True)
            
            return  # Exit early for future placements
        
        # Future-day locking: When viewing a future date (not the placement start date)
        # show collapsed-only card to prevent interaction with future days
        today = central_today()
        is_future_day_view = target_date > today
        
        if is_future_day_view:
            # Get ISS days for the title line
            placement_data = dm.get_placement(placement_id)
            iss_total_days = placement_data.get('issTotalDays', 1) if placement_data else 1
            if iss_total_days is None:
                iss_total_days = 1

            days_label = "Day" if iss_total_days == 1 else "Days"
            title_line = f"{iss_total_days}-{days_label} ISS Session"

            _render_standard_future_day_expanded_view(
                progress_status=iss_session.get('progressStatus', 'NOT_STARTED'),
                title_line=title_line,
                grade=iss_session.get('grade', 'N/A'),
                homeroom=iss_session.get('homeroom_teacher', ''),
                lock_until_date=target_date
            )
            return  # Exit early for future day views
        
        # LAZY LOADING: Only fetch daily log if it exists (read-only check)
        daily_log = dm.get_daily_log(placement_id, date_str)
        
        # Stabilize override flag across all Streamlit rerun states (daily_log can be None early in the flow)
        override_used = bool(daily_log and daily_log.get('overrideUsed', False))
        
        # Get progress status and use centralized helpers for day-level absent/completion (pass pre-fetched daily_log)
        progress_status = iss_session.get('progressStatus', 'NOT_STARTED')
        session_status = iss_session.get('status', 'scheduled')
        is_absent_day = _is_absent_for_date(dm, placement_id, date_str, daily_log=daily_log)
        is_day_completed = _is_day_completed_for_date(daily_log, session_status=session_status)
        
        # Use centralized helpers for circle and text
        progress_circle = _circle_for_day(progress_status, is_absent_day=is_absent_day, is_day_completed=is_day_completed)
        progress_text = _status_text_for_day(progress_status, is_absent_day=is_absent_day, is_day_completed=is_day_completed)
        
        # Display status at top of expanded card
        st.markdown(f"**Status:** {progress_circle} {progress_text}")
        
        # Only fetch point events if student is checked in (lazy loading)
        # (A) Explicit normalization for multi-day gating when daily_log is None
        has_daily_log = daily_log is not None
        is_checked_in = bool(daily_log and daily_log.get('checkedIn', False))
        if is_checked_in:
            point_events = dm.get_point_events_for_date(placement_id, date_str)
            positive_points = sum([e['value'] for e in point_events if e['type'] == 'positive'])
            negative_points = sum([e['value'] for e in point_events if e['type'] == 'negative'])
            total_points = positive_points + negative_points
        else:
            point_events = []
            positive_points = 0
            negative_points = 0
            total_points = 0
        
        is_no_show = session_status == 'no_show'
        
        # Check if placement itself is completed (prevents further edits)
        placement_status = iss_session.get('placement_status', 'active')
        is_placement_completed = placement_status == 'completed'
        
        # is_completed = True if either the day is completed OR the entire placement is completed
        is_completed = is_day_completed or is_placement_completed
        
        if is_completed:
            status_icon = '🟢'
            status_color = 'green'
        elif is_no_show:
            status_icon = '🔴'
            status_color = 'red'
        else:
            status_icon = '🟡'
            status_color = 'yellow'
        
        served_dates = []
        placement_data = dm.get_placement(placement_id)
        if placement_data:
            served_dates = placement_data.get('servedDates', [])
        is_present = date_str in served_dates
        
        # Get ISS total days from placement for partial day control
        iss_total_days = placement_data.get('issTotalDays') if placement_data else 1
        if iss_total_days is None:
            iss_total_days = 1
        is_multi_day_iss = iss_total_days > 1
        
        # Get period-based ISS tracking fields
        required_total_periods = placement_data.get('requiredTotalPeriods', 0) if placement_data else 0
        served_periods_total = placement_data.get('servedPeriodsTotal', 0) if placement_data else 0
        periods_remaining = placement_data.get('periodsRemaining', 0) if placement_data else 0
        periods_per_full_day = placement_data.get('periodsPerFullDay', 10) if placement_data else 10
        
        # Calculate check-in based progress (Day X advances when Check In is pressed)
        checkin_progress = dm.calculate_iss_checkin_progress(placement_id, target_date)
        checked_in_days = checkin_progress['checked_in_days']
        total_days = checkin_progress['total_days']
        
        # Build the "Day X of Y Days" progress label based on check-ins
        day_word = "Day" if total_days == 1 else "Days"
        day_progress_label = f"Day {checked_in_days} of {total_days} {day_word}"
        
        with st.container():
            # Initialize session state for day type - preload from daily log if available
            day_type_key = f"iss_day_type_{card_uid}"
            start_period_key = f"iss_start_period_{card_uid}"
            end_period_key = f"iss_end_period_{card_uid}"
            
            # Preload existing values from daily log if they exist
            stored_day_type = daily_log.get('dayType') if daily_log else None
            stored_start_period = daily_log.get('startPeriod') if daily_log else None
            stored_end_period = daily_log.get('endPeriod') if daily_log else None
            
            if day_type_key not in st.session_state:
                # Use stored value if available, else no default (user must choose)
                if stored_day_type == 'full':
                    st.session_state[day_type_key] = "Full Day"
                elif stored_day_type == 'partial':
                    st.session_state[day_type_key] = "Partial Day"
                # If no stored value, don't set any default - user must choose
            
            # Preload start/end periods if stored
            if start_period_key not in st.session_state and stored_start_period:
                st.session_state[start_period_key] = stored_start_period
            if end_period_key not in st.session_state and stored_end_period:
                st.session_state[end_period_key] = stored_end_period
            
            # Check if day type is already locked (stored in database)
            is_day_type_locked = stored_day_type is not None
            
            header_col1, header_col2, header_col3 = st.columns([3, 2, 1])
            
            with header_col1:
                st.markdown(f"**{day_progress_label}**")
                st.caption(f"Grade {iss_session.get('grade', 'N/A')} · {iss_session.get('homeroom_teacher', 'N/A')}")
            
            with header_col2:
                pass
            
            with header_col3:
                # --- Attendance-first controls ---
                absent_key = f"iss_absent_{card_uid}"

                # (B) Log-safe source of truth: default to False when no log exists
                # (this prevents cross-day inference from placement-level data)
                db_absent = bool(daily_log and daily_log.get("dayType") == "absent")

                # Init widget state on FIRST render only (not every rerun)
                if absent_key not in st.session_state:
                    st.session_state[absent_key] = bool(db_absent)

                # Disable absent toggle after check-in or completion to prevent contradictions
                absent_disabled = is_checked_in or is_completed

                def handle_absent_toggle(pid=placement_id, ds=date_str, key=absent_key):
                    if st.session_state.get(key):
                        dm.mark_absent(pid, ds)
                    else:
                        dm.unmark_absent(pid, ds)
                    clear_dashboard_caches()
                    st.rerun()

                # Render checkbox (unchecked by default unless DB says absent)
                is_absent = st.checkbox(
                    "Absent",
                    key=absent_key,
                    disabled=absent_disabled,
                    on_change=handle_absent_toggle
                )

                # Render Check In button (check-in implies present)
                if is_completed:
                    st.success("Checked Out")
                else:
                    checkin_disabled = is_checked_in or is_completed or is_absent
                    if st.button(
                        "Check In",
                        key=f"iss_checkin_{card_uid}",
                        type="primary" if not checkin_disabled else "secondary",
                        disabled=checkin_disabled
                    ):
                        # Ensure absent is cleared (check-in implies present)
                        dm.unmark_absent(placement_id, date_str)
                        # IMPORTANT: do not lock day type at check-in time
                        dm.check_in_student(placement_id, date_str, day_type=None)
                        clear_dashboard_caches()
                        st.rerun()
            
            # ISS Session Summary - Period tracking display
            st.markdown(f"""
            <div style='background-color: #f0f2f6; padding: 8px 12px; border-radius: 6px; margin: 8px 0;'>
                <strong>ISS:</strong> Required <strong>{required_total_periods}</strong> periods | 
                Served <strong>{served_periods_total}</strong> | 
                Remaining <strong>{periods_remaining}</strong>
            </div>
            """, unsafe_allow_html=True)
            
            # Show completion message for fully completed placements
            if is_placement_completed:
                st.success("ISS Session Complete - All required periods served. No further edits allowed.")
            
            # Day Type selector - only after check-in AND if not absent
            if (not is_completed) and is_checked_in and (not is_absent):
                # Day Type selector
                st.markdown("**Day Type**")
                day_type_col, periods_col = st.columns([1, 2])
                
                with day_type_col:
                    # Widget uses session state via key - no index parameter needed
                    # Session state was initialized earlier (lines 1790-1796)
                    day_type = st.radio(
                        "Select Day Type",
                        options=["Full Day", "Partial Day"],
                        key=day_type_key,
                        horizontal=True,
                        label_visibility="collapsed",
                        disabled=is_day_type_locked
                    )
                
                with periods_col:
                    period_validation_error = None
                    selected_start_period = None
                    selected_end_period = None
                    
                    if day_type == "Full Day" and not is_day_type_locked:
                        # Show Confirm button for Full Day (requires explicit user action)
                        st.caption("Full Day: Periods 1-10 (all periods)")
                        if st.button("Confirm Full Day", key=f"confirm_full_{card_uid}", type="primary"):
                            dm.update_iss_day_type(placement_id, date_str, 'full', 1, 10)
                            clear_dashboard_caches()
                            st.rerun()
                    elif day_type == "Full Day" and is_day_type_locked:
                        # Full Day already locked
                        st.caption("Full Day: Periods 1-10 (all periods)")
                    elif day_type == "Partial Day" and not is_day_type_locked:
                        # Show Start and End Period dropdowns (only if not locked)
                        period_options = list(range(1, 11))  # 1-10
                        
                        # Initialize session state for period selectboxes if not set
                        # This prevents conflicts between key= and index= parameters
                        if start_period_key not in st.session_state:
                            st.session_state[start_period_key] = stored_start_period if stored_start_period else 1
                        if end_period_key not in st.session_state:
                            st.session_state[end_period_key] = stored_end_period if stored_end_period else 10
                        
                        period_col1, period_col2, confirm_col = st.columns([1, 1, 1])
                        with period_col1:
                            selected_start_period = st.selectbox(
                                "Start Period*",
                                options=period_options,
                                key=start_period_key
                            )
                        with period_col2:
                            selected_end_period = st.selectbox(
                                "End Period*",
                                options=period_options,
                                key=end_period_key
                            )
                        
                        # Validate Start/End Period
                        if selected_start_period is None or selected_end_period is None:
                            period_validation_error = "Start Period and End Period are required for Partial Day."
                        elif selected_end_period < selected_start_period:
                            period_validation_error = "End Period must be greater than or equal to Start Period."
                        
                        if period_validation_error:
                            st.error(period_validation_error)
                        else:
                            # Show Confirm button to lock in the partial day selection
                            with confirm_col:
                                st.markdown("<div style='height: 28px'></div>", unsafe_allow_html=True)  # Align with selectboxes
                                if st.button("Confirm", key=f"confirm_partial_{card_uid}", type="primary"):
                                    dm.update_iss_day_type(placement_id, date_str, 'partial', 
                                                         selected_start_period, selected_end_period)
                                    clear_dashboard_caches()
                                    st.rerun()
                    elif day_type == "Partial Day" and is_day_type_locked:
                        # Show locked partial day info
                        st.caption(f"Partial Day: Periods {stored_start_period}-{stored_end_period}")
                
                # Show message only until the user chooses Partial Day (scheduler visible) OR the day type is locked.
                # This is a UI-only tweak; it does not affect save/lock/validation logic.
                if (not is_day_type_locked) and (day_type != "Partial Day"):
                    st.info("📋 Please select Full Day or Partial Day to continue.")
                
                st.divider()
            
            # NOTE: Two-phase completion is now handled by the GLOBAL handler at the top
            # of the Dashboard page. This ensures Phase 2 runs even when expanders are collapsed.
            
            # If checked in but not yet locked, explain why points are unavailable
            if is_checked_in and not is_completed and not is_day_type_locked:
                st.info("🔒 Points are locked until you confirm **Full Day** or confirm **Partial Day** periods for this date.")
            
            # Gate points behind day-type confirmation:
            # - Full Day requires "Confirm Full Day"
            # - Partial Day requires selecting start/end + "Confirm Partial Day"
            if is_checked_in and not is_completed and is_day_type_locked:
                points_col, behaviors_col = st.columns([1, 1])
                
                with behaviors_col:
                    st.markdown("**Add Behaviors**")
                    pos_col, neg_col = st.columns(2)
                    
                    with pos_col:
                        positive_menu = ps.get_positive_point_menu()

                        # If either repair option has been used anywhere in this placement,
                        # lock BOTH repair options for the remainder of the placement/session.
                        existing_events_for_lock = dm.get_all_point_events_for_placement(placement_id)
                        repair_locked = any(
                            (e.get("code") in ("REPAIR_WRITTEN", "REPAIR_VERBAL"))
                            for e in (existing_events_for_lock or [])
                        )

                        if repair_locked:
                            # Remove both repair options from the dropdown (acts like disabled/greyed out)
                            positive_menu_filtered = [
                                i for i in positive_menu
                                if i.get("code") not in ("REPAIR_WRITTEN", "REPAIR_VERBAL")
                            ]
                            st.markdown(
                                "<div style='color:#999;font-size:0.85em;'>Repair the harm (written/verbal) — used for this ISS session</div>",
                                unsafe_allow_html=True
                            )
                        else:
                            positive_menu_filtered = positive_menu

                        positive_options = ["+ Positive"] + [item['label'] for item in positive_menu_filtered]

                        # Unique per-card widget key
                        pos_key = f"iss_pos_{card_uid}"

                        def on_positive_change():
                            selected = st.session_state.get(pos_key, "+ Positive")
                            if selected == "+ Positive":
                                return

                            item = next((i for i in positive_menu_filtered if i["label"] == selected), None)
                            if not item:
                                return

                            payload = {
                                "placementId": placement_id,
                                "studentId": student_id,
                                "sessionId": session_id,
                                "code": item["code"],
                                "type": "positive",
                                "value": item["value"],
                                "date": date_str,
                            }

                            # Dispatch ONE targeted action; Dashboard processes it
                            st.session_state["ISS_PENDING_ACTION"] = {
                                "action": "add_point",
                                "card_uid": card_uid,
                                "payload": payload,
                            }
                            _dashboard_request_keep_open(card_uid, ttl=2)
                            st.rerun()

                        st.selectbox(
                            "Positive",
                            positive_options,
                            key=pos_key,
                            label_visibility="collapsed",
                            on_change=on_positive_change,
                        )
                    
                    with neg_col:
                        negative_menu = ps.get_negative_point_menu()
                        negative_options = ["- Negative"] + [item['label'] for item in negative_menu]

                        # Unique per-card widget key
                        neg_key = f"iss_neg_{card_uid}"

                        def on_negative_change():
                            selected = st.session_state.get(neg_key, "- Negative")
                            if selected == "- Negative":
                                return

                            item = next((i for i in negative_menu if i["label"] == selected), None)
                            if not item:
                                return

                            payload = {
                                "placementId": placement_id,
                                "studentId": student_id,
                                "sessionId": session_id,
                                "code": item["code"],
                                "type": "negative",
                                "value": item["value"],
                                "date": date_str,
                            }

                            # Dispatch ONE targeted action; Dashboard processes it
                            st.session_state["ISS_PENDING_ACTION"] = {
                                "action": "add_point",
                                "card_uid": card_uid,
                                "payload": payload,
                            }
                            st.rerun()

                        st.selectbox(
                            "Negative",
                            negative_options,
                            key=neg_key,
                            label_visibility="collapsed",
                            on_change=on_negative_change,
                        )
                
                with points_col:
                    st.markdown("**Points Total**")
                    # After Check In, use daily_log as source of truth for required_points
                    # This ensures consistency across all display sections
                    stored_day_type_display = daily_log.get('dayType') if daily_log else None
                    stored_required_points = daily_log.get('requiredPoints') if daily_log else None
                    stored_start = daily_log.get('startPeriod', 1) if daily_log else 1
                    stored_end = daily_log.get('endPeriod', 10) if daily_log else 10
                    
                    # Use stored values if checked in, otherwise fall back to session state
                    if is_checked_in and stored_required_points is not None:
                        # Use stored values from daily_log (source of truth after Check In)
                        display_required_points = stored_required_points
                        display_periods_count = stored_end - stored_start + 1
                        is_full_day_display = stored_day_type_display == 'full'
                    else:
                        # Fall back to session state for pre-check-in state
                        # Use card_uid-safe keys (matches widget definitions)
                        current_day_type = st.session_state.get(day_type_key, "Full Day")
                        is_full_day_display = current_day_type == "Full Day"
                        if is_full_day_display:
                            display_required_points = 10
                            display_periods_count = 10
                        else:
                            current_start = st.session_state.get(start_period_key, 1)
                            current_end = st.session_state.get(end_period_key, 10)
                            display_periods_count = max(1, current_end - current_start + 1) if current_end >= current_start else 1
                            display_required_points = display_periods_count
                    
                    # ---- Hover breakdown (POINT TOTALS per category, not counts) ----
                    positive_menu_for_tooltip = ps.get_positive_point_menu()
                    points_html = build_points_hover_tooltip_html(
                        total_points,
                        display_required_points,
                        point_events,
                        positive_menu_for_tooltip
                    )
                    st.markdown(points_html, unsafe_allow_html=True)

                    if total_points >= display_required_points:
                        st.caption(f"✓ Eligible for completion ({display_periods_count} periods)")
                    else:
                        st.caption(f"Need {display_required_points - total_points} more points ({display_periods_count} periods)")
                
                action_col1, action_col2 = st.columns(2)
                
                with action_col1:
                    # Use stored values from daily_log (source of truth after Check In)
                    # This ensures can_complete logic matches the displayed required_points
                    has_period_error = False
                    if not is_full_day_display and not is_checked_in:
                        # Only validate session state periods if not yet checked in
                        curr_start = st.session_state.get(start_period_key, 1)
                        curr_end = st.session_state.get(end_period_key, 10)
                        if curr_end < curr_start:
                            has_period_error = True
                    
                    # Use display_required_points (from daily_log if checked in) for completion check
                    # Both full and partial day require meeting the points threshold
                    can_complete = (not has_period_error) and (total_points >= display_required_points)
                    complete_help = ""
                    if has_period_error:
                        complete_help = "Fix period validation errors first"
                    elif total_points < display_required_points:
                        complete_help = f"Requires {display_required_points}+ points"
                    
                    complete_label = "✓ Complete Day (Retroactive)" if is_past_session else "✓ Complete Day"

                    def _defer_complete_day():
                        print(f"[DEBUG COMPLETE_DAY] Phase 1 (on_click): Deferring completion for card_uid={card_uid}")

                        # Use stored values from daily_log (source of truth after Check In)
                        if is_checked_in and stored_day_type_display is not None:
                            selected_day_type = "Full Day" if stored_day_type_display == 'full' else "Partial Day"
                            selected_start = stored_start
                            selected_end = stored_end
                        else:
                            selected_day_type = st.session_state.get(day_type_key, "Full Day")
                            selected_start = st.session_state.get(start_period_key, 1)
                            selected_end = st.session_state.get(end_period_key, 10)

                        # Store pending action data (single dispatcher pattern - replaces deferred_* keys)
                        st.session_state["ISS_PENDING_ACTION"] = {
                            "action": "complete",
                            "placement_id": placement_id,
                            "session_id": session_id,
                            "log_date": date_str,
                            "completed_by": "Admin",
                            "day_type": selected_day_type,
                            "start_period": selected_start,
                            "end_period": selected_end,
                            "points_earned": total_points,
                            "is_present": is_present,
                            "card_uid": card_uid,
                        }

                        # Clear any pending behavior or widget keys to prevent re-fire
                        # Use card_uid for unique keys (matches behavior dropdown keys)
                        for k in (
                            f"pending_pos_{card_uid}",
                            f"pending_neg_{card_uid}",
                            f"iss_pos_{card_uid}",
                            f"iss_neg_{card_uid}",
                        ):
                            if k in st.session_state:
                                del st.session_state[k]

                    st.button(
                        complete_label,
                        key=f"iss_complete_{card_uid}",
                        type="primary",
                        use_container_width=True,
                        disabled=not can_complete,
                        help=complete_help,
                        on_click=_defer_complete_day
                    )
                
                with action_col2:
                    override_label = "🔓 Override (Retroactive)" if is_past_session else "🔓 Override & Count Full"

                    def _defer_override_day():
                        print(f"[DEBUG OVERRIDE] Phase 1 (on_click): Deferring override for card_uid={card_uid}")

                        override_note = "Retroactive override: Student released early due to positive behavior; remaining periods waived."

                        # Store pending action data (single dispatcher pattern - replaces deferred_* keys)
                        st.session_state["ISS_PENDING_ACTION"] = {
                            "action": "override",
                            "placement_id": placement_id,
                            "session_id": session_id,
                            "log_date": date_str,
                            "completed_by": "Admin",
                            "points_earned": total_points,
                            "override_note": override_note,
                            "is_present": is_present,
                            "card_uid": card_uid,
                        }

                        # Clear any pending behavior or widget keys to prevent re-fire
                        # Use card_uid for unique keys (matches behavior dropdown keys)
                        for k in (
                            f"pending_pos_{card_uid}",
                            f"pending_neg_{card_uid}",
                            f"iss_pos_{card_uid}",
                            f"iss_neg_{card_uid}",
                        ):
                            if k in st.session_state:
                                del st.session_state[k]

                    st.button(
                        override_label,
                        key=f"iss_override_btn_{card_uid}",
                        use_container_width=True,
                        type="secondary",
                        on_click=_defer_override_day
                    )
            elif not is_checked_in and not is_completed and not is_no_show:
                st.caption("Check in student to add behaviors and track points")
            elif is_no_show:
                st.error("Not Completed")
                st.markdown(f"**Points Total: {total_points}**")
                st.caption("Session was not completed by end of day")
                
                retro_col1, retro_col2 = st.columns(2)
                with retro_col1:
                    if st.button("Mark Complete (Retroactive)", key=f"iss_retro_complete_{card_uid}"):
                        # Use complete_iss_day for retroactive completion
                        result = dm.complete_iss_day(
                            placement_id=placement_id,
                            log_date=date_str,
                            completed_by="Admin",
                            day_type="Full Day",
                            points_earned=total_points
                        )
                        if result.get('success'):
                            dm.mark_session_completed(session_id, "Admin")
                            if result.get('isCompleted'):
                                st.success("Session marked complete! ISS Session finished.")
                            else:
                                st.success("Session marked complete!")
                            if hasattr(st, 'cache_data'):
                                st.cache_data.clear()
                            st.rerun()
                        else:
                            st.error(result.get('message', 'Failed to complete session'))
                with retro_col2:
                    if st.button("Apply Override", key=f"iss_retro_override_{card_uid}"):
                        override_note = "Retroactive override: session marked complete after end-of-day processing."
                        result = dm.complete_iss_day(
                            placement_id=placement_id,
                            log_date=date_str,
                            completed_by="Admin",
                            day_type="Full Day",
                            points_earned=total_points,
                            is_override=True,
                            override_note=override_note
                        )
                        if result.get('success'):
                            dm.mark_session_completed(session_id, "Admin", is_override=True, override_comment=override_note)
                            if result.get('isCompleted'):
                                st.success("Override applied! ISS Session finished.")
                            else:
                                st.success("Override applied!")
                            if hasattr(st, 'cache_data'):
                                st.cache_data.clear()
                            st.rerun()
                        else:
                            st.error(result.get('message', 'Failed to apply override'))
            else:
                st.success("Session Completed" + (" (Override)" if override_used else ""))
                st.markdown(f"**Points Total: {total_points}**")
            
            # Check for and display make-up prompt (shown after completing final day when periods are short)
            # This needs to be outside the is_completed check so it shows after completion
            if st.session_state.get(f"show_makeup_prompt_{placement_id}", False):
                makeup_info = st.session_state.get(f"makeup_info_{placement_id}", {})
                periods_remaining = makeup_info.get('periodsRemaining', 0)
                
                # Initialize session state for schedule builder
                schedule_builder_key = f"show_makeup_builder_final_{placement_id}"
                if schedule_builder_key not in st.session_state:
                    st.session_state[schedule_builder_key] = False
                
                # Show schedule builder if "Yes" was clicked
                if st.session_state.get(schedule_builder_key, False):
                    st.info("**ISS Make-Up Days – Add additional dates and periods to complete remaining time.**")
                    st.caption(f"Periods remaining: **{periods_remaining}**")
                    
                    # Date picker for make-up dates
                    makeup_dates_key = f"makeup_dates_final_{placement_id}"
                    if makeup_dates_key not in st.session_state:
                        st.session_state[makeup_dates_key] = []
                    
                    # Add new make-up date form
                    st.markdown("**Add Make-Up Date:**")
                    col_date, col_type = st.columns(2)
                    with col_date:
                        min_date = central_today() + timedelta(days=1)
                        new_makeup_date = st.date_input(
                            "Select date",
                            min_value=min_date,
                            value=min_date,
                            key=f"new_makeup_date_final_{placement_id}"
                        )
                    with col_type:
                        makeup_day_type = st.selectbox(
                            "Day type",
                            ["Full Day (10 periods)", "Partial Day"],
                            key=f"makeup_day_type_final_{placement_id}"
                        )
                    
                    # Show period selectors for partial day
                    start_p, end_p = 1, 10
                    if makeup_day_type == "Partial Day":
                        col_start, col_end = st.columns(2)
                        with col_start:
                            start_p = st.number_input("Start period", min_value=1, max_value=10, value=1, 
                                                      key=f"makeup_start_final_{placement_id}")
                        with col_end:
                            end_p = st.number_input("End period", min_value=1, max_value=10, value=10,
                                                    key=f"makeup_end_final_{placement_id}")
                    
                    # Add date button
                    if st.button("➕ Add Date", key=f"add_makeup_date_final_{placement_id}"):
                        day_type_val = 'full' if makeup_day_type.startswith("Full") else 'partial'
                        new_entry = {
                            'date': new_makeup_date.isoformat(),
                            'day_type': day_type_val,
                            'start_period': start_p if day_type_val == 'partial' else 1,
                            'end_period': end_p if day_type_val == 'partial' else 10
                        }
                        if makeup_dates_key not in st.session_state:
                            st.session_state[makeup_dates_key] = []
                        st.session_state[makeup_dates_key].append(new_entry)
                        st.rerun()
                    
                    # Display added dates
                    if st.session_state.get(makeup_dates_key):
                        st.markdown("**Scheduled Make-Up Dates:**")
                        for i, entry in enumerate(st.session_state[makeup_dates_key]):
                            entry_date = datetime.fromisoformat(entry['date']).strftime('%B %d, %Y')
                            if entry['day_type'] == 'full':
                                period_info = "Full Day (10 periods)"
                            else:
                                period_info = f"Periods {entry['start_period']}–{entry['end_period']}"
                            col_info, col_remove = st.columns([4, 1])
                            with col_info:
                                st.caption(f"• {entry_date}: {period_info}")
                            with col_remove:
                                if st.button("🗑️", key=f"remove_makeup_final_{placement_id}_{i}"):
                                    st.session_state[makeup_dates_key].pop(i)
                                    st.rerun()
                    
                    # Save and Cancel buttons
                    col_save, col_cancel = st.columns(2)
                    with col_save:
                        save_disabled = not st.session_state.get(makeup_dates_key)
                        if st.button("💾 Save Make-Up Schedule", key=f"save_makeup_final_{placement_id}", 
                                    type="primary", use_container_width=True, disabled=save_disabled):
                            result = dm.add_iss_makeup_dates(placement_id, st.session_state[makeup_dates_key])
                            if result.get('success'):
                                st.session_state[f"show_makeup_prompt_{placement_id}"] = False
                                st.session_state[schedule_builder_key] = False
                                st.session_state[makeup_dates_key] = []
                                st.success(result.get('message', 'Make-up dates added!'))
                                if hasattr(st, 'cache_data'):
                                    st.cache_data.clear()
                                st.rerun()
                            else:
                                st.error(result.get('message', 'Failed to add make-up dates'))
                    with col_cancel:
                        if st.button("Cancel", key=f"cancel_makeup_builder_final_{placement_id}", use_container_width=True):
                            st.session_state[schedule_builder_key] = False
                            st.session_state[makeup_dates_key] = []
                            st.rerun()
                else:
                    # Show decision prompt with radio buttons
                    st.warning(f"**This student has {periods_remaining} periods remaining to complete the ISS session.**")
                    
                    # Radio button key for decision
                    decision_key = f"iss_end_decision_{placement_id}"
                    
                    # Radio buttons for decision
                    decision = st.radio(
                        "Select an option:",
                        options=["Add Make-Up Time", "Complete Session Now"],
                        key=decision_key,
                        index=None,  # No default selection
                        horizontal=True
                    )
                    
                    # Continue button - disabled until a choice is made
                    continue_disabled = decision is None
                    if st.button("Continue", key=f"continue_decision_{placement_id}", 
                                type="primary", use_container_width=True, disabled=continue_disabled):
                        if decision == "Add Make-Up Time":
                            # Show schedule builder
                            st.session_state[schedule_builder_key] = True
                            st.rerun()
                        elif decision == "Complete Session Now":
                            # Show close case confirmation
                            st.session_state[f"show_close_early_final_{placement_id}"] = True
                            st.rerun()
                    
                    # Show close case confirmation if that option was selected
                    if st.session_state.get(f"show_close_early_final_{placement_id}", False):
                        st.info("**Complete Session Now**")
                        st.caption(f"This will mark the ISS session as complete with **{periods_remaining} periods remaining unserved**.")
                        
                        additional_note = st.text_area(
                            "Additional notes (optional):",
                            key=f"close_early_final_note_{placement_id}",
                            placeholder="Enter any additional notes about this early completion...",
                            height=80
                        )
                        
                        col_confirm_close, col_cancel_close = st.columns(2)
                        with col_confirm_close:
                            if st.button("Complete Session", key=f"confirm_close_final_{placement_id}", 
                                        type="primary", use_container_width=True):
                                # Generate the standard note with periods remaining
                                base_note = f"ISS session marked complete by staff with {periods_remaining} periods remaining unserved."
                                if additional_note.strip():
                                    full_note = f"{base_note} Additional notes: {additional_note.strip()}"
                                else:
                                    full_note = base_note
                                dm.close_iss_session_early(placement_id, full_note)
                                st.session_state[f"show_makeup_prompt_{placement_id}"] = False
                                st.session_state[f"show_close_early_final_{placement_id}"] = False
                                # Clear decision radio state
                                if f"iss_end_decision_{placement_id}" in st.session_state:
                                    del st.session_state[f"iss_end_decision_{placement_id}"]
                                st.success(f"ISS session completed. {periods_remaining} periods waived.")
                                if hasattr(st, 'cache_data'):
                                    st.cache_data.clear()
                                st.rerun()
                        with col_cancel_close:
                            if st.button("Cancel", key=f"cancel_close_final_{placement_id}", use_container_width=True):
                                st.session_state[f"show_close_early_final_{placement_id}"] = False
                                st.rerun()
            
            # Notes (always visible with auto-save, safe access - daily_log may be None)
            st.caption("Notes")
            render_auto_save_notes(
                f"isssession_{session_id}_{date_str}",
                (daily_log.get('notes', '') if daily_log else '') or '',
                lambda notes: dm.update_daily_log_notes(placement_id, date_str, notes)
            )
            
            st.divider()
    
    # Five Placement Type Sections with Clickable Student Names
    # 1. In-School Suspension (ISS) - Session-based
    # CACHED: Results cached for 60 seconds to improve Dashboard responsiveness
    iss_sessions = get_iss_sessions_for_date_cached(selected_date.isoformat())
    
    st.markdown("#### In-School Suspension (ISS)")
    
    # First, show active sessions for the selected date
    has_active_sessions = len(iss_sessions) > 0
    
    if not has_active_sessions:
        st.caption("No students")
    else:
        # Show active sessions first
        for iss_session in iss_sessions:
            session_id = iss_session['session_id']
            student_name = iss_session['student_name']
            progress_status = iss_session.get('progressStatus', 'NOT_STARTED')

            # Placement_id/date for this row
            placement_id = iss_session.get('placement_id')
            date_str = selected_date.isoformat()

            # Determine total ISS days (used for the 1-day exception)
            iss_days_assigned = (
                iss_session.get('iss_days_assigned')
                or iss_session.get('iss_total_days')
                or iss_session.get('issDaysAssigned')
                or iss_session.get('iss_days')
                or 1
            )

            # Fetch daily log once for both absent and completion checks
            daily_log = dm.get_daily_log(placement_id, date_str)
            is_absent_day = _is_absent_for_date(dm, placement_id, date_str, daily_log=daily_log)

            # 1-day ISS exception: Absent should NEVER cause the row to be treated as Completed/fulfilled for UI collapse
            is_one_day_iss_absent = (int(iss_days_assigned or 1) == 1) and bool(is_absent_day)

            # If DB says COMPLETED but this is 1-day ISS Absent, DO NOT show the collapsed "truth card".
            # Keep it interactive so it can be served later.
            if progress_status == "COMPLETED" and not is_one_day_iss_absent:
                # Pull placement to get endDate reliably
                placement_obj = dm.get_placement(placement_id) or {}
                end_date = _parse_iso_date_safe(placement_obj.get('endDate'))

                day_info = dm.get_iss_days_served_info(placement_id, date_str)
                day_num = day_info.get('current_day_number', None)

                suffix = _completed_suffix_for_day(
                    placement_type_label="ISS",
                    total_days=int(iss_days_assigned or 1),
                    target_date=selected_date,
                    end_date=end_date,
                    is_absent=bool(is_absent_day),
                    day_number=day_num
                )

                # Add hover tooltip ONLY for whole-session completion labels
                suffix_html = suffix
                if (not bool(is_absent_day)) and ("Session Completed" in (suffix or "")):
                    final_date = end_date or selected_date
                    final_date_str = final_date.isoformat()

                    try:
                        positive_menu_for_breakdown = ps.get_positive_point_menu('iss_full_day')
                    except Exception:
                        positive_menu_for_breakdown = ps.get_positive_point_menu()

                    point_events_for_final_day = dm.get_point_events_for_date(placement_id, final_date_str)
                    breakdown = build_iss_points_breakdown_tooltip(point_events_for_final_day, positive_menu_for_breakdown)
                    tooltip_text = "Final Day Points\n" + (breakdown or "")
                    suffix_html = build_completion_label_with_tooltip(suffix, tooltip_text)

                # Standardize ISS completed subtitle to match LD/CPR:
                # - 1-Day Session Completed (single-day)
                # - X-Day · Day Completed (multi-day, non-final day)
                # - X-Day Session Completed (multi-day, final day)
                total_days_assigned = int(iss_days_assigned or 1)

                if (total_days_assigned > 1) and (suffix == "Day Completed"):
                    subtitle = f"ISS · {total_days_assigned}-Day · {suffix_html}"
                else:
                    subtitle = f"ISS · {suffix_html}"

                st.markdown(
                    f"""<div style="padding: 12px; border: 1px solid #e0e0e0; border-radius: 8px;
                    background-color: #fafafa; margin-bottom: 8px;">
                    <span style="font-size: 1.1em;">🔴 <strong>{student_name}</strong></span>
                    <span style="color: #666; margin-left: 12px;">{subtitle}</span>
                    </div>""",
                    unsafe_allow_html=True
                )
                continue

            # For normal (non-collapsed) handling, compute completion with the absent-aware helper
            session_status = iss_session.get('status', 'scheduled')
            is_day_completed = _is_day_completed_for_date(
                daily_log,
                session_status=session_status,
                is_absent_day=bool(is_absent_day)  # key fix: 1-day absent not treated as completed
            )

            # If this is 1-day ISS Absent, force the row to remain expandable (never collapse as completed)
            should_collapse = (progress_status == "COMPLETED" or is_day_completed) and (not is_one_day_iss_absent)

            # Use a display progress status so 1-day Absent doesn't look "finalized"
            display_progress_status = "IN_PROGRESS" if (progress_status == "COMPLETED" and is_one_day_iss_absent) else progress_status

            status_circle = _circle_for_day(
                display_progress_status,
                is_absent_day=bool(is_absent_day),
                is_day_completed=bool(is_day_completed) and (not is_one_day_iss_absent)
            )

            # COMPLETED placements or COMPLETED days: show non-interactive collapsed card
            if should_collapse:
                total_days_here = int(iss_days_assigned or 1)
                if progress_status == "COMPLETED":
                    completion_label = f"{total_days_here}-Day Session Completed"
                else:
                    completion_label = "Day Completed"

                # Hover tooltip for ISS points breakdown
                try:
                    positive_menu_for_breakdown = ps.get_positive_point_menu('iss_full_day')
                except Exception:
                    positive_menu_for_breakdown = ps.get_positive_point_menu()

                point_events_for_day = dm.get_point_events_for_date(placement_id, date_str)
                tooltip_text = build_iss_points_breakdown_tooltip(point_events_for_day, positive_menu_for_breakdown)
                completion_label_html = build_completion_label_with_tooltip(completion_label, tooltip_text)

                if progress_status == "COMPLETED":
                    subtitle = f"In-School Suspension (ISS) · {completion_label_html}"
                else:
                    subtitle = f"In-School Suspension (ISS) · {total_days_here}-Day · {completion_label_html}"

                st.markdown(
                    f"""<div style="padding: 12px; border: 1px solid #e0e0e0; border-radius: 8px;
                    background-color: #fafafa; margin-bottom: 8px;">
                    <span style="font-size: 1.1em;">{status_circle} <strong>{student_name}</strong></span>
                    <span style="color: #666; margin-left: 12px;">{subtitle}</span>
                    </div>""",
                    unsafe_allow_html=True
                )
                st.caption(f"Placement ID: {placement_id}")
            else:
                # Active/In Progress: expandable card with full functionality
                # Build a stable ISS card_uid that matches render_iss_session_card()
                session_key = session_id if session_id is not None else "full"
                iss_card_uid = f"{placement_id}_{session_key}_{date_str}"

                with st.expander(
                    f"{status_circle} {student_name}{' · In Progress' if status_circle == '🟡' else ''}",
                    expanded=_dashboard_should_expand(iss_card_uid)
                ):
                    render_iss_session_card(iss_session, selected_date)
    
    st.divider()
    
    # 2. Lunch Detention
    st.markdown("#### Lunch Detention")
    if len(lunch_detention_placements) == 0:
        st.caption("No students")
    else:
        for placement in lunch_detention_placements:
            placement_id = placement['_id']
            student = placement['student']
            student_name = f"{student['firstName']} {student['lastName']}"
            progress_status = placement.get('progressStatus', 'NOT_STARTED')
            days_assigned = placement.get('daysAssigned', 1)
            date_str = selected_date.isoformat()
            
            # Fetch daily log once for both absent and completion checks
            daily_log = dm.get_daily_log(placement_id, date_str)
            
            # Use centralized helpers for day-level absent and completion status (pass pre-fetched daily_log)
            is_absent_day = _is_absent_for_date(dm, placement_id, date_str, daily_log=daily_log)
            is_day_completed = _is_day_completed_for_date(daily_log)
            
            # Use centralized helper for colored circle
            status_circle = _circle_for_day(progress_status, is_absent_day=is_absent_day, is_day_completed=is_day_completed)
            
            # Collapse rules for Lunch Detention:
            # - If the overall placement is COMPLETED (final-day / whole-session complete), always collapse
            # - If this DATE is completed AND it's a multi-day Lunch Detention, collapse (middle-day "Day Completed")
            collapse_for_completed_day = bool(is_day_completed) and (days_assigned or 1) > 1
            collapse_for_completed_session = (progress_status == "COMPLETED")

            # Show as non-interactive collapsed card (no expander)
            if collapse_for_completed_session or collapse_for_completed_day:
                is_absent = is_absent_day
                
                end_date = _parse_iso_date_safe(placement.get('endDate'))
                day_info = dm.get_lunch_detention_days_served_info(placement_id, date_str)
                day_num = day_info.get('current_day_number', None)
                
                suffix = _completed_suffix_for_day(
                    placement_type_label="Lunch Detention",
                    total_days=days_assigned,
                    target_date=selected_date,
                    end_date=end_date,
                    is_absent=is_absent,
                    day_number=day_num
                )

                # 1-day Lunch Detention: absent outcome labels (stored in makeupNote marker)
                if (days_assigned or 1) == 1 and suffix == "Absent":
                    note = (placement.get("makeupNote") or "")
                    if "ABSENT_RESCHEDULED" in note:
                        suffix = "Absent · Rescheduled"
                    elif "ABSENT_CLOSED" in note:
                        suffix = "Absent · Closed Complete"
                
                # No hover flags for non-ISS placements (redundant)
                suffix_html = suffix
                
                # For multi-day "middle day" completion, include the 3-Day label:
                # Lunch Detention · 3-Day · Day Completed
                # For final-day completion, keep: Lunch Detention · 3-Day Session Completed
                if (days_assigned or 1) > 1 and suffix == "Day Completed":
                    subtitle = f"Lunch Detention · {days_assigned}-Day · {suffix_html}"
                else:
                    subtitle = f"Lunch Detention · {suffix_html}"
                
                st.markdown(
                    f"""<div style="padding: 12px; border: 1px solid #e0e0e0; border-radius: 8px; 
                    background-color: #fafafa; margin-bottom: 8px;">
                    <span style="font-size: 1.1em;">{status_circle} <strong>{student_name}</strong></span>
                    <span style="color: #666; margin-left: 12px;">{subtitle}</span>
                    </div>""",
                    unsafe_allow_html=True
                )
            else:
                # Active/In Progress: Use expandable card with full functionality
                ld_card_uid = f"ld_{placement_id}_{date_str}"

                with st.expander(
                    f"{status_circle} {student_name}{' · In Progress' if status_circle == '🟡' else ''}",
                    expanded=_dashboard_should_expand(ld_card_uid)
                ):
                    render_lunch_detention_card(placement, selected_date)
    
    st.divider()
    
    # 3. Class Period Referral (unified: includes Behavior, Cool-Down, and Pre-Planned)
    st.markdown("#### Class Period Referral")
    if len(unified_class_referral_placements) == 0:
        st.caption("No students")
    else:
        for placement in unified_class_referral_placements:
            placement_id = placement['_id']
            student = placement['student']
            student_name = f"{student['firstName']} {student['lastName']}"
            progress_status = placement.get('progressStatus', 'NOT_STARTED')
            referral_subtype = placement.get('referralSubtype', '')
            date_str = selected_date.isoformat()

            placement_type = (placement.get('placementType') or placement.get('type') or '').upper()
            referral_subtype_norm = (referral_subtype or '').strip().lower()

            # Robust "is pre-planned" detection (some records use placementType=PRE_PLANNED_REFERRAL instead of referralSubtype)
            is_preplanned = (
                placement_type == 'PRE_PLANNED_REFERRAL'
                or referral_subtype_norm in {'pre_planned', 'pre-planned', 'preplanned', 'pre planned'}
            )
            
            # Get subtype display name
            subtype_labels = {
                'behavior': 'Behavior',
                'cool_down': 'Cool-Down',
                'pre_planned': 'Pre-Planned'
            }
            subtype_display = subtype_labels.get(referral_subtype.lower() if referral_subtype else '', referral_subtype or 'Referral')
            
            # Fetch daily log once for both absent and completion checks
            daily_log = dm.get_daily_log(placement_id, date_str)
            
            # Use centralized helpers for day-level absent and completion status (pass pre-fetched daily_log)
            is_absent_day = _is_absent_for_date(dm, placement_id, date_str, daily_log=daily_log)
            is_day_completed = _is_day_completed_for_date(daily_log)

            # =========== DEBUG: Pre-Planned diagnostic (remove after investigation) ===========
            if DEBUG_PREPLANNED_DIAG and is_preplanned and False:
                with st.expander(f"🔍 DEBUG: Pre-Planned Diag for {student_name} (ID: {placement_id})", expanded=False):
                    st.markdown("**Placement Fields:**")
                    st.write({
                        "id": placement_id,
                        "placementType": placement.get('placementType'),
                        "type": placement.get('type'),
                        "referralSubtype": placement.get('referralSubtype'),
                        "status": placement.get('status'),
                        "progressStatus": progress_status,
                        "daysAssigned": placement.get('daysAssigned'),
                        "daysCompleted": placement.get('daysCompleted'),
                        "startDate": placement.get('startDate'),
                        "endDate": placement.get('endDate'),
                    })
                    st.markdown("**Derived Booleans (Dashboard Logic):**")
                    st.write({
                        "referral_subtype_norm": referral_subtype_norm,
                        "placement_type (upper)": placement_type,
                        "is_preplanned": is_preplanned,
                        "is_day_completed": is_day_completed,
                        "is_absent_day": is_absent_day,
                        "would_collapse": progress_status == "COMPLETED" or (is_preplanned and is_day_completed),
                    })
                    st.markdown(f"**DailyLog for {date_str}:**")
                    if daily_log:
                        st.write({
                            "date": daily_log.get('date'),
                            "day_type": daily_log.get('day_type'),
                            "daily_fulfillment": daily_log.get('daily_fulfillment'),
                            "periods_covered": daily_log.get('periods_covered'),
                            "periods_added": daily_log.get('periods_added'),
                        })
                    else:
                        st.write("No DailyLog found for this date")

                    # Multi-day: show all DailyLogs between startDate and endDate
                    start_d = _parse_iso_date_safe(placement.get('startDate'))
                    end_d = _parse_iso_date_safe(placement.get('endDate'))
                    if start_d and end_d and start_d != end_d:
                        st.markdown("**All DailyLogs (startDate → endDate):**")
                        cursor_d = start_d
                        all_logs = []
                        while cursor_d <= end_d:
                            log = dm.get_daily_log(placement_id, cursor_d.isoformat())
                            if log:
                                all_logs.append({
                                    "date": log.get('date'),
                                    "day_type": log.get('day_type'),
                                    "daily_fulfillment": log.get('daily_fulfillment'),
                                    "periods_covered": log.get('periods_covered'),
                                })
                            cursor_d += timedelta(days=1)
                        if all_logs:
                            st.write(all_logs)
                        else:
                            st.write("No DailyLogs found in date range")

                    # Show partial day sessions if any
                    st.markdown("**PartialDaySessions for this placement:**")
                    sessions = dm.get_partial_day_sessions(placement_id)
                    if sessions:
                        st.write([{
                            "date": s.get('date'),
                            "status": s.get('status'),
                            "session_type": s.get('session_type'),
                            "periods_assigned": s.get('periods_assigned'),
                            "periods_served": s.get('periods_served'),
                        } for s in sessions])
                    else:
                        st.write("No PartialDaySessions found")
            # =========== END DEBUG ===========
            
            # Use centralized helper for colored circle
            status_circle = _circle_for_day(progress_status, is_absent_day=is_absent_day, is_day_completed=is_day_completed)
            
            # COMPLETED placements OR (Pre-Planned day completed): Show as non-interactive collapsed card (no expander)
            if progress_status == "COMPLETED" or (is_preplanned and is_day_completed):
                is_absent = is_absent_day
                
                end_date = _parse_iso_date_safe(placement.get('endDate'))
                days_assigned = placement.get('daysAssigned', 1) or 1
                
                # Friendly placement type label for the collapsed record
                if is_preplanned:
                    placement_type_label = "Pre-Planned Referral"
                elif referral_subtype == 'cool_down':
                    placement_type_label = "Cool-Down Referral"
                else:
                    placement_type_label = "Behavior Referral"
                
                # Day numbering only matters for multi-day Pre-Planned
                day_num = None
                if is_preplanned and days_assigned > 1:
                    day_info = dm.get_preplanned_days_served_info(placement_id, date_str)
                    day_num = day_info.get('current_day_number', None)
                
                suffix = _completed_suffix_for_day(
                    placement_type_label=placement_type_label,
                    total_days=days_assigned,
                    target_date=selected_date,
                    end_date=end_date,
                    is_absent=bool(is_absent),
                    day_number=day_num,
                    is_same_day_cpr=not is_preplanned  # Behavior/Cool-Down are always same-day
                )
                
                # No hover flags for non-ISS placements (redundant)
                suffix_html = suffix
                
                # For multi-day Pre-Planned "middle day" completion, include the X-Day label:
                # Pre-Planned Referral · 3-Day · Day Completed
                # For final-day completion, keep: Pre-Planned Referral · 3-Day Session Completed
                # For single-day completion, keep: Pre-Planned Referral · 1-Day Session Completed
                if is_preplanned and (days_assigned or 1) > 1 and suffix == "Day Completed":
                    subtitle = f"{placement_type_label} · {days_assigned}-Day · {suffix_html}"
                else:
                    subtitle = f"{placement_type_label} · {suffix_html}"
                
                st.markdown(
                    f"""<div style="padding: 12px; border: 1px solid #e0e0e0; border-radius: 8px; 
                    background-color: #fafafa; margin-bottom: 8px;">
                    <span style="font-size: 1.1em;">{status_circle} <strong>{student_name}</strong></span>
                    <span style="color: #666; margin-left: 12px;">{subtitle}</span>
                    </div>""",
                    unsafe_allow_html=True
                )
            else:
                # Active/In Progress: Use expandable card with full functionality
                cpr_card_uid = f"cpr_{placement_id}_{date_str}"

                with st.expander(
                    f"{status_circle} {student_name}{' · In Progress' if status_circle == '🟡' else ''}",
                    expanded=_dashboard_should_expand(cpr_card_uid)
                ):
                    render_unified_class_referral_card(placement, selected_date)

    st.divider()

    # =========================
    # SCHOOL CALENDAR — FINALIZED SUMMARY (BOTTOM OF DASHBOARD)
    # =========================
    finalized_calendar = dm.is_school_calendar_finalized(current_sy)
    edit_mode = st.session_state.get("school_calendar_edit_mode", False)

    if finalized_calendar and (not edit_mode):
        # View-only summary card at the bottom (collapsed by default)
        with st.expander("📅 School Calendar (Finalized)", expanded=False):
            st.caption(f"School Year: {int(current_sy[0])}-{str(int(current_sy[1]))[-2:]}  (Aug → Jul)")

            closures = dm.list_school_closures(current_sy)

            if not closures:
                st.info("No no-school days are currently saved for this year.")
            else:
                st.markdown("**Saved no-school days:**")
                for c in closures:
                    label = c["title"]
                    if c["start_date"] == c["end_date"]:
                        date_label = c["start_date"]
                    else:
                        date_label = f'{c["start_date"]} → {c["end_date"]}'
                    st.write(f"• **{label}** — {date_label}")

            if st.button("✏️ Edit", use_container_width=True):
                st.session_state.school_calendar_edit_mode = True
                st.rerun()

    # Tick down the keep-open TTL once per Dashboard render
    _dashboard_keep_open_tick()

# Placements Page
elif page == "Placements":
    st.header("Placement Manager")
    
    # Navigation button to Completed Placements (right-justified)
    completed_count = len(dm.get_completed_placements_with_students())
    left_col, right_col = st.columns([5, 1])
    with right_col:
        if st.button(f"📋 Completed Placements ({completed_count})", key="placements_completed_btn", type="secondary"):
            st.session_state.navigate_to_completed_placements = True
            st.rerun()
    
    st.divider()
    
    # Create Placement content
    students = dm.get_all_students()
    
    st.subheader("Create New Placement")
    
    # Initialize session state for placement type selection
    if 'placement_category' not in st.session_state:
        st.session_state.placement_category = "In-School Suspension (ISS)"
    if 'referral_subtype' not in st.session_state:
        st.session_state.referral_subtype = "Behavior Referral"
    
    # Placement Type selector (outside forms so it can switch between forms)
    placement_category = st.radio(
        "Placement Type*",
        options=[
            "In-School Suspension (ISS)", 
            "Lunch Detention", 
            "Class Period Referral"
        ],
        horizontal=True,
        help="Select the type of placement",
        key="placement_category"
    )
    
    # Show sub-type dropdown only for Class Period Referral
    referral_subtype = None
    if placement_category == "Class Period Referral":
        referral_subtype = st.selectbox(
            "Referral Type*",
            options=["Behavior Referral", "Cool-Down Referral", "Pre-Planned Referral"],
            help="Select the specific type of class period referral",
            key="referral_subtype"
        )
    
    st.divider()
    
    # ===== ISS FORM - Using regular widgets with button callback =====
    if placement_category == "In-School Suspension (ISS)":
        st.markdown("### Student Information")
        col1, col2 = st.columns(2)
        with col1:
            first_name = st.text_input("First Name*", key="iss_first_name")
            grade = st.selectbox("Grade*", ["6", "7", "8"], key="iss_grade")
        with col2:
            last_name = st.text_input("Last Name*", key="iss_last_name")
            homeroom_teacher = st.text_input("Homeroom Teacher*", key="iss_homeroom")
        
        st.divider()
        st.markdown("### Placement Details")
        reason = st.text_area("Reason for Placement*", key="iss_reason")
        
        st.divider()
        st.markdown("### Scheduling")
        sched_col1, sched_col2 = st.columns(2)
        with sched_col1:
            iss_start_date = st.date_input("Start Date*", value=central_today(), help="First day of ISS placement", key="iss_start_date")
        with sched_col2:
            iss_total_days = st.number_input("Number of ISS Days*", min_value=1, value=1, step=1, help="Total ISS days assigned", key="iss_total_days")
        
        created_by = st.selectbox("Created By*", STAFF_OPTIONS, key="iss_created_by")
        
        # Show warning if "Add Staff" placeholder is selected
        if created_by == "Add Staff":
            st.warning("Note: 'Add Staff' is a placeholder for future use. Please select a valid staff member to create a placement.")
        
        iss_submit = st.button("Create ISS Placement", type="primary", use_container_width=True, key="iss_submit")
        
        if iss_submit:
            if not first_name or not last_name or not homeroom_teacher or not reason or not created_by:
                st.error("Please fill in all required fields marked with *")
            elif created_by == "Add Staff":
                st.error("Please select a valid staff member. 'Add Staff' is a placeholder for future use.")
            else:
                try:
                    new_student_data = {
                        "firstName": first_name,
                        "lastName": last_name,
                        "grade": grade,
                        "homeroomTeacher": homeroom_teacher,
                        "guardianContacts": [],
                        "status": "active"
                    }
                    student_id = dm.add_student(new_student_data)
                    
                    placement_data = {
                        "studentId": student_id,
                        "homeroomTeacherId": homeroom_teacher,
                        "reason": reason,
                        "type": "iss_full_day",
                        "placementType": "ISS",
                        "completionRule": "iss_days",
                        "minSessionsRequired": None,
                        "daysAssigned": iss_total_days,
                        "issStartDate": iss_start_date.isoformat(),
                        "issTotalDays": iss_total_days,
                        "issRemainingDays": iss_total_days,
                        "startDate": iss_start_date.isoformat(),
                        "status": "active",
                        "createdBy": created_by,
                        "createdAt": central_now().isoformat()
                    }
                    
                    placement_id = dm.add_placement(placement_data)
                    dm.generate_iss_full_day_sessions(placement_id, iss_start_date, iss_total_days)
                    
                    st.session_state.placement_created = True
                    st.session_state.navigate_to_dashboard = True
                    clear_dashboard_caches()
                    st.rerun()
                except Exception as e:
                    import traceback
                    st.error(f"Error creating placement: {str(e)}")
                    st.error(traceback.format_exc())
    
    # ===== LUNCH DETENTION - Using regular widgets with button =====
    elif placement_category == "Lunch Detention":
        print(f"[DEBUG] Rendering Lunch Detention section")
        st.markdown("### Student Information")
        col1, col2 = st.columns(2)
        with col1:
            first_name = st.text_input("First Name*", key="ld_first_name")
            grade = st.selectbox("Grade*", ["6", "7", "8"], key="ld_grade")
        with col2:
            last_name = st.text_input("Last Name*", key="ld_last_name")
            homeroom_teacher = st.text_input("Homeroom Teacher*", key="ld_homeroom")
        
        st.divider()
        st.markdown("### Placement Details")
        reason = st.text_area("Reason for Placement*", key="ld_reason")
        
        st.divider()
        st.markdown("### Scheduling")
        sched_col1, sched_col2 = st.columns(2)
        with sched_col1:
            start_date = st.date_input("Start Date*", value=central_today(), key="ld_start_date")
        with sched_col2:
            lunch_days = st.number_input("Number of Lunch Detention Days*", min_value=1, value=1, step=1, help="Number of lunch detention days", key="ld_lunch_days")
        
        created_by = st.selectbox("Created By*", STAFF_OPTIONS, key="ld_created_by")
        
        # Show warning if "Add Staff" placeholder is selected
        if created_by == "Add Staff":
            st.warning("Note: 'Add Staff' is a placeholder for future use. Please select a valid staff member to create a placement.")
        
        if st.button("Create Lunch Detention", type="primary", use_container_width=True, key="ld_submit"):
            if not first_name or not last_name or not homeroom_teacher or not reason or not created_by:
                st.error("Please fill in all required fields marked with *")
            elif created_by == "Add Staff":
                st.error("Please select a valid staff member. 'Add Staff' is a placeholder for future use.")
            else:
                try:
                    new_student_data = {
                        "firstName": first_name,
                        "lastName": last_name,
                        "grade": grade,
                        "homeroomTeacher": homeroom_teacher,
                        "guardianContacts": [],
                        "status": "active"
                    }
                    student_id = dm.add_student(new_student_data)
                    
                    scheduled_lunch_dates = dm.calculate_scheduled_lunch_dates(start_date, int(lunch_days))
                    end_date = scheduled_lunch_dates[-1] if scheduled_lunch_dates else start_date
                    
                    placement_data = {
                        "studentId": student_id,
                        "homeroomTeacherId": homeroom_teacher,
                        "reason": reason,
                        "type": "iss_full_day",
                        "placementType": "LUNCH_DETENTION",
                        "completionRule": "all_sessions_fulfilled",
                        "minSessionsRequired": None,
                        "daysAssigned": int(lunch_days),
                        "startDate": start_date.isoformat(),
                        "endDate": end_date.isoformat(),
                        "scheduledLunchDates": [d.isoformat() for d in scheduled_lunch_dates],
                        "servedDates": [],
                        "status": "active",
                        "createdBy": created_by,
                        "createdAt": central_now().isoformat()
                    }
                    
                    placement_id = dm.add_placement(placement_data)
                    dm.generate_lunch_detention_sessions_from_scheduled(placement_id, scheduled_lunch_dates)
                    
                    st.session_state.placement_created = True
                    st.session_state.navigate_to_dashboard = True
                    clear_dashboard_caches()
                    st.rerun()
                except Exception as e:
                    import traceback
                    st.error(f"Error: {str(e)}")
                    st.error(traceback.format_exc())
    
    # ===== CLASS PERIOD REFERRAL - Using regular widgets with buttons =====
    elif placement_category == "Class Period Referral":
        # Behavior Referral - Single-day with single period selection
        if referral_subtype == "Behavior Referral":
            st.markdown("### Student Information")
            col1, col2 = st.columns(2)
            with col1:
                first_name = st.text_input("First Name*", key="br_first_name")
                grade = st.selectbox("Grade*", ["6", "7", "8"], key="br_grade")
            with col2:
                last_name = st.text_input("Last Name*", key="br_last_name")
                homeroom_teacher = st.text_input("Homeroom Teacher*", key="br_homeroom")
            
            st.divider()
            st.markdown("### Placement Details")
            reason = st.text_area("Reason for Placement*", key="br_reason")
            
            st.divider()
            st.markdown("### Scheduling")
            sched_col1, sched_col2 = st.columns(2)
            with sched_col1:
                start_date = st.date_input("Date*", value=central_today(), key="br_start_date")
            with sched_col2:
                selected_period = st.selectbox("Period*", options=[1, 2, 3, 4, 5, 6, 7, 8, 9, 10], format_func=lambda x: f"P{x}", key="br_period")
            
            created_by = st.selectbox("Created By*", STAFF_OPTIONS, key="br_created_by")
            
            # Show warning if "Add Staff" placeholder is selected
            if created_by == "Add Staff":
                st.warning("Note: 'Add Staff' is a placeholder for future use. Please select a valid staff member to create a placement.")
            
            if st.button("Create Behavior Referral", type="primary", use_container_width=True, key="br_submit"):
                if not first_name or not last_name or not homeroom_teacher or not reason or not created_by:
                    st.error("Please fill in all required fields marked with *")
                elif created_by == "Add Staff":
                    st.error("Please select a valid staff member. 'Add Staff' is a placeholder for future use.")
                else:
                    try:
                        new_student_data = {
                            "firstName": first_name,
                            "lastName": last_name,
                            "grade": grade,
                            "homeroomTeacher": homeroom_teacher,
                            "guardianContacts": [],
                            "status": "active"
                        }
                        student_id = dm.add_student(new_student_data)
                        
                        placement_data = {
                            "studentId": student_id,
                            "homeroomTeacherId": homeroom_teacher,
                            "reason": reason,
                            "type": "partial",
                            "placementType": "CLASS_REFERRAL",
                            "referralSubtype": "behavior",
                            "completionRule": "all_sessions_fulfilled",
                            "minSessionsRequired": None,
                            "daysAssigned": 1,
                            "startDate": start_date.isoformat(),
                            "endDate": start_date.isoformat(),
                            "startPeriod": selected_period,
                            "endPeriod": selected_period,
                            "status": "active",
                            "createdBy": created_by,
                            "createdAt": central_now().isoformat()
                        }
                        
                        placement_id = dm.add_placement(placement_data)
                        dm.generate_class_referral_session(placement_id, start_date, selected_period, selected_period)
                        
                        st.session_state.placement_created = True
                        st.session_state.navigate_to_dashboard = True
                        clear_dashboard_caches()
                        st.rerun()
                    except Exception as e:
                        import traceback
                        st.error(f"Error: {str(e)}")
                        st.error(traceback.format_exc())
        
        # Cool-Down Referral - Single-day with single period selection
        elif referral_subtype == "Cool-Down Referral":
            st.markdown("### Student Information")
            col1, col2 = st.columns(2)
            with col1:
                first_name = st.text_input("First Name*", key="cd_first_name")
                grade = st.selectbox("Grade*", ["6", "7", "8"], key="cd_grade")
            with col2:
                last_name = st.text_input("Last Name*", key="cd_last_name")
                homeroom_teacher = st.text_input("Homeroom Teacher*", key="cd_homeroom")
            
            st.divider()
            st.markdown("### Placement Details")
            reason = st.text_area("Reason for Placement*", key="cd_reason")
            
            st.divider()
            st.markdown("### Scheduling")
            sched_col1, sched_col2 = st.columns(2)
            with sched_col1:
                cooldown_date = st.date_input("Date*", value=central_today(), key="cd_date")
            with sched_col2:
                selected_period = st.selectbox("Period*", options=[1, 2, 3, 4, 5, 6, 7, 8, 9, 10], format_func=lambda x: f"P{x}", key="cd_period")
            
            created_by = st.selectbox("Created By*", STAFF_OPTIONS, key="cd_created_by")
            
            # Show warning if "Add Staff" placeholder is selected
            if created_by == "Add Staff":
                st.warning("Note: 'Add Staff' is a placeholder for future use. Please select a valid staff member to create a placement.")
            
            if st.button("Create Cool-Down Referral", type="primary", use_container_width=True, key="cd_submit"):
                if not first_name or not last_name or not homeroom_teacher or not reason or not created_by:
                    st.error("Please fill in all required fields marked with *")
                elif created_by == "Add Staff":
                    st.error("Please select a valid staff member. 'Add Staff' is a placeholder for future use.")
                else:
                    try:
                        new_student_data = {
                            "firstName": first_name,
                            "lastName": last_name,
                            "grade": grade,
                            "homeroomTeacher": homeroom_teacher,
                            "guardianContacts": [],
                            "status": "active"
                        }
                        student_id = dm.add_student(new_student_data)
                        
                        placement_data = {
                            "studentId": student_id,
                            "homeroomTeacherId": homeroom_teacher,
                            "reason": reason,
                            "type": "partial",
                            "placementType": "CLASS_REFERRAL",
                            "referralSubtype": "cool_down",
                            "completionRule": "all_sessions_fulfilled",
                            "minSessionsRequired": None,
                            "daysAssigned": 1,
                            "startDate": cooldown_date.isoformat(),
                            "endDate": cooldown_date.isoformat(),
                            "startPeriod": selected_period,
                            "endPeriod": selected_period,
                            "status": "active",
                            "createdBy": created_by,
                            "createdAt": central_now().isoformat()
                        }
                        placement_id = dm.add_placement(placement_data)
                        dm.generate_cooldown_session(placement_id, cooldown_date, selected_period, selected_period)
                        
                        st.session_state.placement_created = True
                        st.session_state.navigate_to_dashboard = True
                        clear_dashboard_caches()
                        st.rerun()
                    except Exception as e:
                        import traceback
                        st.error(f"Error creating cool-down referral: {str(e)}")
                        st.error(traceback.format_exc())
        
        # Pre-Planned Referral - schedule-based referral with multiple date+period combinations
        elif referral_subtype == "Pre-Planned Referral":
            st.info("This placement type allows you to schedule a student for specific periods on specific dates (e.g., when they will have a substitute teacher)")
            
            if 'preplanned_schedule' not in st.session_state:
                st.session_state.preplanned_schedule = [{"date": central_today(), "periods": [1]}]

            # --- Pre-Planned CPR: forward-only date guardrail (prevents duplicates/overlaps) ---
            # Ensures each day is >= the prior day + 1, starting from today.
            min_allowed = central_today()
            for i, slot in enumerate(st.session_state.preplanned_schedule):
                slot_date = slot.get("date") or central_today()

                if slot_date < min_allowed:
                    # Correct the stored schedule date
                    st.session_state.preplanned_schedule[i]["date"] = min_allowed

                    # Also correct the widget state if it already exists (Streamlit keys override `value=` params)
                    widget_key = f"pp_date_{i}"
                    if widget_key in st.session_state:
                        st.session_state[widget_key] = min_allowed

                    slot_date = min_allowed

                min_allowed = slot_date + timedelta(days=1)
            
            with st.form("preplanned_referral_form"):
                st.markdown("### Student Information")
                col1, col2 = st.columns(2)
                with col1:
                    first_name = st.text_input("First Name*", key="pp_first_name")
                    grade = st.selectbox("Grade*", ["6", "7", "8"], key="pp_grade")
                with col2:
                    last_name = st.text_input("Last Name*", key="pp_last_name")
                    homeroom_teacher = st.text_input("Homeroom Teacher*", key="pp_homeroom")
                
                st.divider()
                st.markdown("### Placement Details")
                reason = st.text_area("Reason for Placement*", key="pp_reason")
                
                st.divider()
                st.markdown("### Scheduling")
                st.caption("Add one or more date+period combinations for this referral")
                
                schedule_data = []
                
                row_data = st.session_state.preplanned_schedule[0]
                st.markdown("**Day 1**")
                col_date, col_periods = st.columns([2, 3])
                
                with col_date:
                    row_date = st.date_input(
                        f"Date",
                        value=row_data.get("date", central_today()),
                        min_value=central_today(),
                        key=f"pp_date_0",
                        label_visibility="collapsed"
                    )
                
                with col_periods:
                    row_periods = st.multiselect(
                        f"Periods",
                        options=[1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
                        default=row_data.get("periods", [1]),
                        format_func=lambda x: f"Period {x}",
                        key=f"pp_periods_0",
                        label_visibility="collapsed"
                    )
                
                schedule_data.append({"date": row_date, "periods": row_periods})
                st.divider()
                
                for idx in range(1, len(st.session_state.preplanned_schedule)):
                    row_data = st.session_state.preplanned_schedule[idx]
                    
                    st.markdown(f"**Day {idx + 1}**")
                    col_date, col_periods = st.columns([2, 3])
                    
                    with col_date:
                        prev_date = st.session_state.preplanned_schedule[idx - 1].get("date") or central_today()
                        row_date = st.date_input(
                            f"Date",
                            value=row_data.get("date", prev_date + timedelta(days=1)),
                            min_value=prev_date + timedelta(days=1),
                            key=f"pp_date_{idx}",
                            label_visibility="collapsed"
                        )
                    
                    with col_periods:
                        row_periods = st.multiselect(
                            f"Periods",
                            options=[1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
                            default=row_data.get("periods", [1]),
                            format_func=lambda x: f"Period {x}",
                            key=f"pp_periods_{idx}",
                            label_visibility="collapsed"
                        )
                    
                    schedule_data.append({"date": row_date, "periods": row_periods})
                    st.divider()
                
                add_row_button = st.form_submit_button("+ Add Day", use_container_width=False)
                
                created_by = st.selectbox("Created By*", STAFF_OPTIONS, key="pp_created_by")
                
                # Note: Can't show dynamic st.warning inside st.form, but validation below handles it
                
                submit_button = st.form_submit_button("Create Pre-Planned Referral", type="primary", use_container_width=True)
                
                if add_row_button:
                    last_date = st.session_state.preplanned_schedule[-1].get("date") or central_today()
                    next_date = last_date + timedelta(days=1)
                    st.session_state.preplanned_schedule.append({"date": next_date, "periods": [1]})
                    st.rerun()
                
                if submit_button:
                    print(f"[DEBUG] Pre-Planned Referral form submitted - First: '{first_name}', Last: '{last_name}'")
                    validation_error = False
                    
                    if not first_name or not last_name or not homeroom_teacher or not reason or not created_by:
                        st.error("Please fill in all required fields marked with *")
                        validation_error = True
                    elif created_by == "Add Staff":
                        st.error("Please select a valid staff member. 'Add Staff' is a placeholder for future use.")
                        validation_error = True
                    
                    valid_schedule = [s for s in schedule_data if s.get("periods")]
                    if not valid_schedule:
                        st.error("Please add at least one day with selected periods")
                        validation_error = True
                    
                    if not validation_error:
                        try:
                            new_student_data = {
                                "firstName": first_name,
                                "lastName": last_name,
                                "grade": grade,
                                "homeroomTeacher": homeroom_teacher,
                                "guardianContacts": [],
                                "status": "active"
                            }
                            student_id = dm.add_student(new_student_data)
                            
                            scheduled_slots = []
                            for slot in valid_schedule:
                                for period in slot["periods"]:
                                    scheduled_slots.append({
                                        "date": slot["date"].isoformat(),
                                        "period": period
                                    })
                            
                            all_dates = [slot["date"] for slot in valid_schedule]
                            start_date = min(all_dates)
                            end_date = max(all_dates)
                            
                            placement_data = {
                                "studentId": student_id,
                                "homeroomTeacherId": homeroom_teacher,
                                "reason": reason,
                                "type": "partial",
                                "placementType": "CLASS_REFERRAL",
                                "referralSubtype": "pre_planned",
                                "completionRule": "all_sessions_fulfilled",
                                "minSessionsRequired": None,
                                "daysAssigned": len(valid_schedule),
                                "startDate": start_date.isoformat(),
                                "endDate": end_date.isoformat(),
                                "scheduledSlots": scheduled_slots,
                                "status": "active",
                                "createdBy": created_by,
                                "createdAt": central_now().isoformat()
                            }
                            
                            placement_id = dm.add_placement(placement_data)
                            dm.generate_preplanned_sessions(placement_id, scheduled_slots)
                            
                            st.session_state.preplanned_schedule = [{"date": central_today(), "periods": [1]}]
                            
                            st.session_state.placement_created = True
                            st.session_state.navigate_to_dashboard = True
                            clear_dashboard_caches()
                            st.rerun()
                        except Exception as e:
                            import traceback
                            st.error(f"Error creating pre-planned referral: {str(e)}")
                            st.error(traceback.format_exc())
            
            if len(st.session_state.preplanned_schedule) > 1:
                if st.button("Remove Last Day"):
                    st.session_state.preplanned_schedule.pop()
                    st.rerun()

# Completed Placements Page - Dedicated page for completed placements archive
elif page == "Completed Placements":
    print(f"[DEBUG] Entering Completed Placements page. page={page}, current_page={st.session_state.current_page}")
    from utils import (get_school_year_for_date, get_current_school_year, 
                      group_placements_by_school_year_month_day, get_placement_type_with_subtype,
                      format_ordinal_day)
    
    st.header("Completed Placements Archive")
    st.caption("Master archive of all completed placements organized by school year")

    left_col, right_col = st.columns([5, 1])
    with right_col:
        show_admin_tools = st.toggle("Show admin tools", value=False)

    # -------------------------------
    # ADMIN: Fix legacy 3-day ISS records
    # -------------------------------
    if show_admin_tools:
      with st.expander("Admin: Fix legacy 3-day ISS records", expanded=False):
        st.caption(
            "Find 3-day ISS placements where all original days were completed, "
            "but strict period reconciliation is short, and mark them completed."
        )
        st.info("Admin tool loaded.")

        st.divider()
        st.subheader("Manual Fix (by Placement ID)")
        st.caption("Paste one or more Placement IDs (comma or whitespace separated). Preview first, then mark completed.")

        default_note = "Legacy reconciliation \u2014 AP counted session served; waiving remaining periods."
        manual_note = st.text_input("Closure note (audit trail)", value=default_note, key="legacy_manual_note")

        raw_ids = st.text_area(
            "Placement ID(s)",
            placeholder="Example: 123e4567-e89b-12d3-a456-426614174000, 987e6543-e21b-45d6-b789-123456789abc",
            key="legacy_manual_ids",
            height=80,
        )

        def _parse_ids(raw: str) -> list[str]:
            if not raw:
                return []
            parts = [p.strip() for p in raw.replace("\n", " ").replace("\t", " ").split(" ")]
            ids = []
            for part in parts:
                if not part:
                    continue
                for sub in part.split(","):
                    sub = sub.strip()
                    if sub:
                        ids.append(sub)
            seen = set()
            out = []
            for pid in ids:
                if pid not in seen:
                    seen.add(pid)
                    out.append(pid)
            return out

        preview_key = "legacy_manual_preview"
        if preview_key not in st.session_state:
            st.session_state[preview_key] = {}

        colp1, colp2 = st.columns([1, 3])
        with colp1:
            do_preview = st.button("Preview", key="legacy_manual_preview_btn")
        with colp2:
            st.caption("Preview shows strict Expected/Credited/Short-by. Then you can mark each one completed.")

        if do_preview:
            st.session_state[preview_key] = {}
            ids = _parse_ids(raw_ids)
            if not ids:
                st.warning("Paste at least one Placement ID above.")
            else:
                for pid in ids:
                    try:
                        info = dm.check_iss_session_needs_makeup_strict(pid)
                        st.session_state[preview_key][pid] = info
                    except Exception as e:
                        st.session_state[preview_key][pid] = {"_error": str(e)}

        preview = st.session_state.get(preview_key, {})
        if preview:
            st.divider()
            for pid, info in preview.items():
                st.markdown(f"### Placement `{pid}`")
                if isinstance(info, dict) and info.get("_error"):
                    st.error(f"Preview failed: {info['_error']}")
                    continue

                expected_ = info.get("periodsRequired", "\u2014")
                credited_ = info.get("periodsServed", "\u2014")
                short_ = info.get("periodsRemaining", "\u2014")
                needs_ = info.get("needsMakeup", False)

                st.markdown(f"- **Expected:** **{expected_}** periods")
                st.markdown(f"- **Credited:** **{credited_}** periods")
                st.markdown(f"- **Short by:** **{short_}** periods")
                st.markdown(f"- **Strict needsMakeup:** `{needs_}`")

                btn_key = f"legacy_manual_close_{pid}"
                if st.button("Waive shortfall & Mark Completed", key=btn_key):
                    try:
                        ok = dm.close_iss_session_early(pid, note=manual_note)
                        if ok:
                            st.success("Marked completed. This record should now appear in Completed Placements.")
                            st.rerun()
                        else:
                            st.error("Could not mark completed (close_iss_session_early returned False).")
                    except Exception as e:
                        st.error(f"Failed to mark completed: {e}")

                st.divider()

    completed_placements = dm.get_completed_placements_with_students()
    
    if completed_placements:
        # Search control
        search_query = st.text_input("🔍 Search student name", "", key="archive_search").strip()
        
        # Filter placements based on search (student name only)
        filtered_placements = completed_placements
        if search_query:
            q = " ".join(search_query.lower().split())  # normalize whitespace + lowercase
            
            def _name_matches(p: dict) -> bool:
                # Prefer explicit student fields if present
                first = (p.get("student", {}).get("firstName") or "").strip()
                last = (p.get("student", {}).get("lastName") or "").strip()
                full = f"{first} {last}".strip()
                
                full_norm = " ".join(full.lower().split())
                return q in full_norm
            
            filtered_placements = [p for p in filtered_placements if _name_matches(p)]
        
        # Group by school year, month, day
        grouped = group_placements_by_school_year_month_day(filtered_placements)
        current_school_year = get_current_school_year()
        
        st.write(f"**{len(filtered_placements)} completed placements**")
        st.divider()
        
        # ---------------- Reports + Export Section ----------------
        import io
        
        def _iso_to_date_safe(s):
            if not s:
                return None
            try:
                return datetime.fromisoformat(s).date()
            except Exception:
                return None
        
        def _completion_date_for(p: dict, dm):
            """
            Returns the 'report date' for Day/Month/Year reports using tighter, type-aware logic.
            - ISS / Lunch Detention / Pre-Planned: use final completion day (completedDate/endDate), else derive.
            - Behavior / Cool-Down: use startDate (same-day).
            """
            from datetime import timedelta
            
            placement_type = (p.get("placementType") or p.get("type") or "").upper()
            subtype = (p.get("referralSubtype") or p.get("subtype") or "").lower()
            
            start = _iso_to_date_safe(p.get("startDate"))
            end = _iso_to_date_safe(p.get("endDate"))
            completed = _iso_to_date_safe(p.get("completedDate")) or _iso_to_date_safe(p.get("dateCompleted"))
            
            # Same-day referrals: always use start date (prevents updatedAt drift)
            if placement_type in ("CLASS_REFERRAL", "CPR", "CLASS_PERIOD_REFERRAL") and subtype in ("behavior", "cool_down"):
                return start or completed or end
            
            # Multi-day capable types: prefer true completion day
            if completed:
                return completed
            if end:
                return end
            
            # Pre-Planned: if endDate missing, derive from scheduled sessions (PartialDaySession)
            if placement_type in ("CLASS_REFERRAL", "CPR", "CLASS_PERIOD_REFERRAL") and subtype == "pre_planned":
                try:
                    placement_id = p.get("id") or p.get("placementId") or p.get("_id")
                    if placement_id:
                        sessions = dm.get_partial_day_sessions_for_placement(placement_id) or []
                        session_dates = [_iso_to_date_safe(s.get("date")) for s in sessions]
                        session_dates = [d for d in session_dates if d]
                        if session_dates:
                            return max(session_dates)
                except Exception:
                    pass
            
            # Generic fallback for multi-day placements if we have daysAssigned
            days_assigned = p.get("daysAssigned") or p.get("issDaysAssigned") or p.get("iss_days_assigned")
            try:
                days_assigned = int(days_assigned) if days_assigned is not None else None
            except Exception:
                days_assigned = None
            
            if start and days_assigned and days_assigned > 1:
                return start + timedelta(days=days_assigned - 1)
            
            # Final safe fallback
            return start or completed or end
        
        def _placement_type_label(p: dict) -> str:
            pt = (p.get("placementType") or p.get("type") or "").upper()
            if pt == "ISS":
                return "ISS"
            if pt in ("LUNCH_DETENTION", "LUNCH"):
                return "Lunch Detention"
            if pt in ("CLASS_REFERRAL", "CPR", "CLASS_PERIOD_REFERRAL"):
                sub = (p.get("referralSubtype") or p.get("subtype") or "").lower()
                if sub == "pre_planned":
                    return "Pre-Planned Referral"
                if sub == "cool_down":
                    return "Cool-Down Referral"
                if sub == "behavior":
                    return "Behavior Referral"
                return "Class Period Referral"
            return p.get("placementType") or p.get("type") or "Placement"
        
        def _served_time_label(p: dict) -> str:
            days = p.get("daysAssigned") or p.get("issDaysAssigned")
            sp = p.get("startPeriod")
            ep = p.get("endPeriod")
            
            if sp and ep:
                try:
                    sp_i, ep_i = int(sp), int(ep)
                    if ep_i >= sp_i:
                        n = ep_i - sp_i + 1
                        return f"Periods {sp_i}-{ep_i} ({n})"
                except Exception:
                    pass
            if sp:
                try:
                    return f"Period {int(sp)}"
                except Exception:
                    return "Period (unspecified)"
            
            if days:
                try:
                    return f"{int(days)} day(s)"
                except Exception:
                    return f"{days} day(s)"
            return ""
        
        # Reports & Export expander moved below the archive view (see below).
        
        # Normal hierarchical view - Render School Year → Month → Day hierarchy
        for school_year, year_data in grouped.items():
            is_current_year = (school_year == current_school_year)
            year_label = year_data['label']
            
            # Count total placements in this school year
            year_total = sum(
                len(day_placements) 
                for month_data in year_data['months'].values() 
                for day_placements in month_data['days'].values()
            )
            
            with st.expander(f"📅 {year_label} ({year_total})", expanded=is_current_year):
                for month_num, month_data in year_data['months'].items():
                    month_label = month_data['label']
                    
                    # Count placements in this month
                    month_total = sum(len(day_placements) for day_placements in month_data['days'].values())
                    
                    st.markdown(f"##### {month_label} ({month_total})")
                    
                    for day_num, day_placements in month_data['days'].items():
                        day_ordinal = format_ordinal_day(day_num)
                        
                        st.markdown(f"###### {day_ordinal}")
                        
                        for placement in day_placements:
                                student = placement['student']
                                student_name = f"{student['firstName']} {student['lastName']}"
                                type_display = get_placement_type_with_subtype(placement)
                                placement_id = placement.get('_id')
                                placement_type = (placement.get('placementType') or '').upper()
                                referral_subtype = placement.get('referralSubtype', '')
                                
                                # Collapsed card header
                                with st.expander(f"🔴 {student_name} – {type_display}", expanded=False):
                                    # Expanded read-only detail view
                                    col1, col2 = st.columns(2)
                                    with col1:
                                        st.write(f"**Student:** {student_name}")
                                        st.write(f"**Grade:** {student.get('grade', 'N/A')}")
                                        st.write(f"**Homeroom:** {student.get('homeroomTeacher', 'N/A')}")
                                        st.write(f"**Placement Type:** {type_display}")
                                    with col2:
                                        st.write(f"**Start Date:** {format_date(placement.get('startDate', 'N/A'))}")
                                        st.write(f"**End Date:** {format_date(placement.get('endDate', 'N/A'))}")
                                        
                                        # In archive view: Behavioral/Cool-Down are period-based (typically same-day), so show periods assigned
                                        if placement_type == 'CLASS_REFERRAL' and referral_subtype in ('behavior', 'cool_down'):
                                            start_date_str = placement.get('startDate')
                                            periods = []
                                            try:
                                                if start_date_str:
                                                    start_date_obj = datetime.fromisoformat(start_date_str).date()
                                                    periods = dm.get_referral_periods_for_date(placement_id, start_date_obj) or []
                                            except Exception:
                                                periods = []
                                            
                                            # Fallback to placement start/end period fields if session periods are missing
                                            if not periods:
                                                sp = placement.get('startPeriod')
                                                ep = placement.get('endPeriod')
                                                if sp and ep and ep >= sp:
                                                    periods = list(range(int(sp), int(ep) + 1))
                                                elif sp:
                                                    periods = [int(sp)]
                                            
                                            if periods:
                                                periods = sorted(set(periods))
                                                if len(periods) == 1:
                                                    period_label = f"Period {periods[0]}"
                                                else:
                                                    period_label = f"Periods {periods[0]}–{periods[-1]} ({len(periods)} periods)"
                                                st.write(f"**Period(s) Assigned:** {period_label}")
                                            else:
                                                st.write("**Period(s) Assigned:** N/A")
                                        else:
                                            st.write(f"**Days Assigned:** {placement.get('daysAssigned', 'N/A')}")
                                    
                                    st.divider()
                                    st.write(f"**Reason:** {placement.get('reason', 'N/A')}")
                                    
                                    # ISS-specific details
                                    if placement_type == 'ISS':
                                        st.divider()
                                        st.markdown("**ISS Details:**")
                                        iss_days = placement.get('issDaysAssigned') or placement.get('daysAssigned', 0)
                                        iss_periods_served = placement.get('issPeriodsServed', 0)
                                        iss_total_periods = placement.get('issTotalRequiredPeriods') or (iss_days * 10)
                                        total_points = placement.get('totalPoints', 0)
                                        
                                        col1, col2 = st.columns(2)
                                        with col1:
                                            st.write(f"**Days:** {iss_days}-Day ISS ({iss_total_periods} periods)")
                                            st.write(f"**Periods Served:** {iss_periods_served} of {iss_total_periods}")
                                        with col2:
                                            st.write(f"**Total Points Earned:** {total_points}")
                                            
                                            # Make-up info
                                            makeup_days = placement.get('makeupDaysUsed', 0)
                                            if makeup_days > 0:
                                                makeup_periods = placement.get('makeupPeriodsServed', 0)
                                                st.write(f"**Make-Up Days:** {makeup_days} ({makeup_periods} periods)")
                                        
                                        # Make-up note if exists
                                        makeup_note = placement.get('makeupNote')
                                        if makeup_note:
                                            st.caption(f"📋 {makeup_note}")
                                        
                                        # ISS SESSION-LEVEL POINT SUMMARY
                                        st.divider()
                                        try:
                                            positive_menu_for_summary = ps.get_positive_point_menu('iss_full_day')
                                        except Exception:
                                            positive_menu_for_summary = ps.get_positive_point_menu()
                                        
                                        session_point_events = dm.get_all_point_events_for_placement(placement_id)
                                        summary_lines = build_iss_session_points_summary(session_point_events, positive_menu_for_summary)
                                        
                                        st.markdown("**Points Summary**")
                                        for line in summary_lines:
                                            st.caption(line)
                                    
                                    # Lunch Detention specific details
                                    elif placement_type == 'LUNCH_DETENTION':
                                        st.divider()
                                        st.markdown("**Lunch Detention Details:**")
                                        served_dates = placement.get('servedDates', [])
                                        if served_dates:
                                            st.write(f"**Served Dates:** {', '.join([format_date(d) for d in served_dates[:5]])}" + 
                                                    (f" (+{len(served_dates)-5} more)" if len(served_dates) > 5 else ""))
                                    
                                    # Class Period Referral specific details
                                    elif placement_type == 'CLASS_REFERRAL':
                                        st.divider()
                                        st.markdown("**Referral Details:**")
                                        
                                        # Pre-Planned specific: Show scheduled sessions (stored as PartialDaySession rows)
                                        if referral_subtype == 'pre_planned':
                                            sessions = dm.get_partial_day_sessions_for_placement(placement_id) or []
                                            
                                            if sessions:
                                                st.markdown("**Sessions:**")
                                                from collections import defaultdict
                                                
                                                periods_by_date = defaultdict(set)
                                                for sess in sessions:
                                                    d = sess.get("date")
                                                    for p in (sess.get("periods") or []):
                                                        if p:
                                                            periods_by_date[d].add(int(p))
                                                
                                                for slot_date in sorted([d for d in periods_by_date.keys() if d]):
                                                    periods = sorted(periods_by_date[slot_date])
                                                    if len(periods) == 1:
                                                        period_label = f"Period {periods[0]}"
                                                    else:
                                                        period_label = f"Periods {periods[0]}–{periods[-1]} ({len(periods)} periods)"
                                                    
                                                    checkin_status = dm.get_preplanned_checkin_status(placement_id, slot_date)
                                                    badge = "✅ Attended" if checkin_status.get('checked_in') else "❌ Absent"
                                                    st.caption(f"📅 {format_date(slot_date)} · {period_label} · {badge}")
                                            else:
                                                st.caption("No scheduled sessions found for this Pre-Planned referral.")
                                    
                                    # Notes if available
                                    notes = placement.get('notes')
                                    if notes:
                                        st.divider()
                                        st.write(f"**Notes:** {notes}")
                                    
                        
                        st.markdown("---")

        # ---------------- Reports + Export Section (moved below archive view) ----------------
        with st.expander("Reports & Export", expanded=False):
            # Only Month + School Year
            report_scope = st.selectbox(
                "Report range",
                ["Month", "School Year"],
                index=0,
                key="cp_report_scope"
            )

            # Build School Year dropdown from what's actually in the archive grouping
            available_school_years = list(grouped.keys())  # keys are tuples like (2025, 2026)

            def _sy_short_label(sy: tuple) -> str:
                # e.g. (2025, 2026) -> "2025-26"
                try:
                    return f"{int(sy[0])}-{str(int(sy[1]))[-2:]}"
                except Exception:
                    return str(sy)

            sy_labels = [_sy_short_label(sy) for sy in available_school_years]

            # Default selection: current school year if present, else first available
            default_sy_index = 0
            try:
                if current_school_year in available_school_years:
                    default_sy_index = available_school_years.index(current_school_year)
            except Exception:
                default_sy_index = 0

            selected_sy = st.selectbox(
                "School Year",
                options=available_school_years,
                format_func=_sy_short_label,
                index=default_sy_index,
                key="cp_report_school_year"
            )

            today_central = central_today()

            if report_scope == "Month":
                # Month dropdown: Aug -> Jul (full school-year cycle, includes July)
                months_order = [8, 9, 10, 11, 12, 1, 2, 3, 4, 5, 6, 7]
                month_names = {
                    1: "January", 2: "February", 3: "March", 4: "April",
                    5: "May", 6: "June", 7: "July", 8: "August",
                    9: "September", 10: "October", 11: "November", 12: "December"
                }
                month_options = months_order
                month_default = today_central.month if today_central.month in month_options else 8
                month_index = month_options.index(month_default) if month_default in month_options else 0

                selected_month = st.selectbox(
                    "Month",
                    options=month_options,
                    format_func=lambda m: month_names.get(m, str(m)),
                    index=month_index,
                    key="cp_report_month_sy"
                )

                def _in_scope(p):
                    d = _completion_date_for(p, dm)
                    return bool(d) and get_school_year_for_date(d) == selected_sy and d.month == int(selected_month)

            else:  # School Year
                def _in_scope(p):
                    d = _completion_date_for(p, dm)
                    return bool(d) and get_school_year_for_date(d) == selected_sy

            report_rows = [p for p in filtered_placements if _in_scope(p)]

            table = []
            for p in report_rows:
                cd = _completion_date_for(p, dm)
                student = p.get("student", {})
                student_name = f"{student.get('firstName', '')} {student.get('lastName', '')}".strip()
                table.append({
                    "Student": student_name,
                    "Placement": _placement_type_label(p),
                    "Served time": _served_time_label(p),
                    "Reason": (p.get("reason") or "").strip(),
                    "Start date": p.get("startDate") or "",
                    "End/Completed date": cd.isoformat() if cd else "",
                    "Staff": (p.get("staffName") or p.get("createdBy") or "").strip(),
                    "Placement ID": p.get("id") or p.get("placementId") or p.get("_id") or "",
                })

            df = pd.DataFrame(table)

            st.caption(f"{len(df)} record(s) in report")

            if len(df) > 0:
                st.dataframe(df, use_container_width=True, hide_index=True)

                dl_col1, dl_col2, dl_col3 = st.columns(3)

                with dl_col1:
                    csv_bytes = df.to_csv(index=False).encode("utf-8")
                    st.download_button(
                        "Download CSV",
                        data=csv_bytes,
                        file_name="completed_placements_report.csv",
                        mime="text/csv",
                        use_container_width=True
                    )

                with dl_col2:
                    xlsx_buffer = io.BytesIO()
                    with pd.ExcelWriter(xlsx_buffer, engine="openpyxl") as writer:
                        df.to_excel(writer, index=False, sheet_name="Completed Placements")
                    st.download_button(
                        "Download Excel",
                        data=xlsx_buffer.getvalue(),
                        file_name="completed_placements_report.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        use_container_width=True
                    )

                with dl_col3:
                    html = df.to_html(index=False)
                    st.download_button(
                        "Download Print-Friendly HTML",
                        data=html.encode("utf-8"),
                        file_name="completed_placements_report.html",
                        mime="text/html",
                        use_container_width=True
                    )
            else:
                st.info("No completed placements found for the selected report range.")
        # -----------------------------------------------------------------------

    else:
        st.info("No completed placements found.")

# ISS Detail Page - Hidden page for ISS daily workflow
elif page == "ISS Detail":
    placement_id = st.session_state.get('iss_detail_placement_id')
    target_date = st.session_state.get('iss_detail_date')
    
    if not placement_id or not target_date:
        st.error("Missing placement or date information")
        st.button("← Back to Dashboard", on_click=lambda: setattr(st.session_state, 'navigate_to_dashboard', True))
        st.stop()
    
    # Get placement and student details
    placement = dm.get_placement(placement_id)
    if not placement:
        st.error("Placement not found")
        st.button("← Back to Dashboard", on_click=lambda: setattr(st.session_state, 'navigate_to_dashboard', True))
        st.stop()
    
    student = dm.get_student(placement['studentId'])
    if not student:
        st.error("Student not found")
        st.button("← Back to Dashboard", on_click=lambda: setattr(st.session_state, 'navigate_to_dashboard', True))
        st.stop()
    
    student_name = f"{student['firstName']} {student['lastName']}"
    date_str = target_date.isoformat()
    
    # Get or create daily log
    daily_log = dm.get_or_create_daily_log(placement_id, date_str)
    
    # Header with back button
    col_back, col_header = st.columns([1, 5])
    with col_back:
        if st.button("← Back", key="back_to_dashboard"):
            st.session_state.navigate_to_dashboard = True
            st.rerun()
    with col_header:
        st.header(f"ISS Daily Log - {student_name}")
        st.caption(f"{format_date(date_str)} · Grade {student.get('grade', 'N/A')} · {student.get('homeroomTeacher', 'N/A')}")
    
    # Calculate Day X of Y (completion-based, not calendar-based)
    iss_total_days = placement.get('issDaysAssigned') or placement.get('issTotalDays', 0)
    iss_remaining_days = placement.get('issRemainingDays', 0)
    
    if iss_total_days > 0:
        days_served_info = dm.get_iss_days_served_info(placement_id, date_str)
        day_number = days_served_info.get('current_day_number', 1)
        if day_number > 0:
            st.info(f"📅 Day {day_number} of {iss_total_days} · {iss_remaining_days} days remaining")
    
    st.divider()
    
    # Check if already completed
    is_completed = daily_log.get('dailyFulfillment') == 'yes'
    existing_day_type = daily_log.get('dayType')
    existing_periods = daily_log.get('periodsCovered', [])
    override_used = daily_log.get('overrideUsed', False)
    
    if override_used:
        st.success("✅ Placement closed using 'Call It Good' override")
        st.info(f"**Override Comment:** {daily_log.get('overrideComment', 'No comment provided')}")
        st.caption(f"Completed by: {daily_log.get('finalizedBy', 'Unknown')} at {daily_log.get('finalizedAt', 'Unknown')}")
        st.divider()
        if st.button("← Return to Dashboard", type="primary"):
            st.session_state.navigate_to_dashboard = True
            st.rerun()
        st.stop()
    
    # Day Type Selector
    st.subheader("1. Select Day Type")
    day_type_options = ["Full Day (All 10 Periods)", "Partial Day (Select Periods)", "Absent (Did Not Attend)"]
    day_type_map = {"Full Day (All 10 Periods)": "full", "Partial Day (Select Periods)": "partial", "Absent (Did Not Attend)": "absent"}
    
    # Determine default index based on existing data
    default_index = 0
    if existing_day_type:
        for i, option in enumerate(day_type_options):
            if day_type_map[option] == existing_day_type:
                default_index = i
                break
    
    selected_day_type_label = st.radio(
        "How did the student attend ISS today?",
        day_type_options,
        index=default_index,
        key="day_type_selector",
        disabled=is_completed
    )
    selected_day_type = day_type_map[selected_day_type_label]
    
    st.divider()
    
    # Periods Section (show for Full Day and Partial Day)
    periods_covered = []
    if selected_day_type == "full":
        st.subheader("2. Periods Covered")
        st.success("✓ All 10 periods automatically marked (Periods 1-10)")
        periods_covered = list(range(1, 11))
        
    elif selected_day_type == "partial":
        st.subheader("2. Select Periods Attended")
        st.info("Check the periods the student was present for ISS")
        
        # Create 2 rows of 5 checkboxes
        col1, col2, col3, col4, col5 = st.columns(5)
        cols_row1 = [col1, col2, col3, col4, col5]
        
        for i in range(5):
            period = i + 1
            with cols_row1[i]:
                checked = period in existing_periods if is_completed else False
                if st.checkbox(f"Period {period}", key=f"period_{period}", value=checked, disabled=is_completed):
                    periods_covered.append(period)
        
        col6, col7, col8, col9, col10 = st.columns(5)
        cols_row2 = [col6, col7, col8, col9, col10]
        
        for i in range(5):
            period = i + 6
            with cols_row2[i]:
                checked = period in existing_periods if is_completed else False
                if st.checkbox(f"Period {period}", key=f"period_{period}", value=checked, disabled=is_completed):
                    periods_covered.append(period)
        
        if not periods_covered and not is_completed:
            st.warning("⚠️ Please select at least one period for a partial day")
        
        st.divider()
    
    elif selected_day_type == "absent":
        st.subheader("2. Periods Covered")
        st.info("Student was absent - no periods to track")
        st.caption("Note: Absent days do NOT count toward ISS completion")
        st.divider()
    
    # Points Section (only for Full Day and Partial Day)
    if selected_day_type in ["full", "partial"]:
        st.subheader("3. Behavior & Points")
        
        # Get point events
        point_events = dm.get_point_events_for_date(placement_id, date_str)
        positive_points = sum([e['value'] for e in point_events if e['type'] == 'positive'])
        negative_points = sum([e['value'] for e in point_events if e['type'] == 'negative'])
        total_points = positive_points + negative_points
        
        col_behaviors, col_total = st.columns([2, 1])
        
        with col_behaviors:
            if not is_completed:
                # Positive behaviors dropdown
                positive_menu = ps.get_positive_point_menu()
                positive_options = ["-- Add Positive Behavior --"] + [item['label'] for item in positive_menu]
                selected_positive = st.selectbox(
                    "Add Positive Behavior",
                    positive_options,
                    key=f"add_positive_{placement_id}_{date_str}"
                )
                
                if selected_positive != "-- Add Positive Behavior --":
                    item = next((i for i in positive_menu if i['label'] == selected_positive), None)
                    if item:
                        dm.add_point_event({
                            'placementId': placement_id,
                            'studentId': student['_id'],
                            'code': item['code'],
                            'type': 'positive',
                            'value': item['value'],
                            'date': date_str
                        })
                        # Reset dropdown to prevent ghost point on rerun
                        st.session_state[f"add_positive_{placement_id}_{date_str}"] = "-- Add Positive Behavior --"
                        st.rerun()
                
                # Negative behaviors dropdown
                negative_menu = ps.get_negative_point_menu()
                negative_options = ["-- Add Negative Behavior --"] + [item['label'] for item in negative_menu]
                selected_negative = st.selectbox(
                    "Add Negative Behavior",
                    negative_options,
                    key=f"add_negative_{placement_id}_{date_str}"
                )
                
                if selected_negative != "-- Add Negative Behavior --":
                    item = next((i for i in negative_menu if i['label'] == selected_negative), None)
                    if item:
                        dm.add_point_event({
                            'placementId': placement_id,
                            'studentId': student['_id'],
                            'code': item['code'],
                            'type': 'negative',
                            'value': item['value'],
                            'date': date_str
                        })
                        # Reset dropdown to prevent ghost point on rerun
                        st.session_state[f"add_negative_{placement_id}_{date_str}"] = "-- Add Negative Behavior --"
                        st.rerun()
            
            # Display current behaviors
            if point_events:
                st.caption("**Today's Behaviors:**")
                for event in point_events:
                    item = ps.get_point_item_by_code(event['code'])
                    icon = "✅" if event['type'] == 'positive' else "❌"
                    col_label, col_remove = st.columns([4, 1])
                    with col_label:
                        st.caption(f"{icon} {item['label']} ({event['value']:+d} pts)")
                    with col_remove:
                        if not is_completed:
                            if st.button("✕", key=f"remove_{event['_id']}", help="Remove"):
                                dm.delete_point_event(event['_id'])
                                st.rerun()
            else:
                st.caption("No behaviors recorded yet")
        
        with col_total:
            full_day_points_required = 10  # Full Day ISS = 10 periods = 10 points
            st.metric("Total Points", f"{total_points} / {full_day_points_required}" if selected_day_type == "full" else total_points)
            if selected_day_type == "full":
                if total_points >= full_day_points_required:
                    st.success("✓ Eligible for completion")
                else:
                    st.warning(f"Need {full_day_points_required - total_points} more")
            else:
                st.caption("No minimum for partial days")
        
        st.divider()
    
    # Notes Section (auto-save)
    st.subheader("4. Notes (Optional)")
    render_auto_save_notes(
        f"issedit_{placement_id}_{iss_date}",
        daily_log.get('notes', '') or '',
        lambda notes: dm.update_daily_log_notes(placement_id, iss_date, notes),
        disabled=is_completed,
        help_text="Notes auto-save when you click/tap outside the box."
    )
    
    st.divider()
    
    # Action Buttons
    if is_completed:
        st.success(f"✅ Day Completed as '{existing_day_type.title()}' Day")
        st.caption(f"Completed by: {daily_log.get('finalizedBy', 'Unknown')} at {daily_log.get('finalizedAt', 'Unknown')}")
        if existing_day_type in ['full', 'partial']:
            st.caption(f"Periods covered: {', '.join([str(p) for p in existing_periods])}")
    else:
        st.subheader("5. Complete Day")
        st.info("To complete this ISS day, please use the **Dashboard**. Navigate to Dashboard and expand the student's card to access the Complete Day button.")
        st.caption("This ensures accurate point tracking during completion.")

# Assignments Page (Placeholder - to be built in the future)
elif page == "Assignments":
    st.header("Assignments")

# Handle editing student (if triggered from students page)
if hasattr(st.session_state, 'editing_student'):
    student = st.session_state.editing_student
    
    with st.form("edit_student_form"):
        st.subheader(f"Edit Student: {student['firstName']} {student['lastName']}")
        
        first_name = st.text_input("First Name*", value=student['firstName'])
        last_name = st.text_input("Last Name*", value=student['lastName'])
        grade = st.selectbox("Grade*", ["K", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12"], 
                           index=["K", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12"].index(student['grade']))
        homeroom_teacher = st.text_input("Homeroom Teacher*", value=student['homeroomTeacher'])
        
        if st.form_submit_button("Update Student"):
            updated_data = {
                "firstName": first_name,
                "lastName": last_name,
                "grade": grade,
                "homeroomTeacher": homeroom_teacher,
                "guardianContacts": student.get('guardianContacts', []),
                "status": student.get('status', 'active')
            }
            dm.update_student(student['_id'], updated_data)
            del st.session_state.editing_student
            st.success("Student updated successfully!")
            st.rerun()
        
        if st.form_submit_button("Cancel"):
            del st.session_state.editing_student
            st.rerun()

# Footer branding - displayed on every page (centered)
st.divider()
st.markdown("<p style='text-align: center; color: rgba(49, 51, 63, 0.6); font-size: 0.875rem;'>George S. Mickelson Middle School – Brookings, South Dakota</p>", unsafe_allow_html=True)
