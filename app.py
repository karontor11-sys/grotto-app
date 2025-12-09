import streamlit as st
import pandas as pd
import time
from datetime import datetime, date, timedelta
from db_manager import DatabaseManager
from point_system import PointSystem
from analytics import AnalyticsEngine
from import_export import ImportExportManager
from notifications import NotificationManager
from utils import format_date, calculate_days_remaining, get_status_color, calculate_school_day_number, get_placement_type_label, get_placement_duration_info, is_placement_active_today, get_placement_type_display_name, add_business_days

# Initialize session state
if 'data_manager' not in st.session_state:
    st.session_state.data_manager = DatabaseManager()
if 'point_system' not in st.session_state:
    st.session_state.point_system = PointSystem()
if 'analytics_engine' not in st.session_state:
    st.session_state.analytics_engine = AnalyticsEngine(st.session_state.data_manager)
if 'import_export_manager' not in st.session_state:
    st.session_state.import_export_manager = ImportExportManager(st.session_state.data_manager)
if 'notification_manager' not in st.session_state:
    st.session_state.notification_manager = NotificationManager(st.session_state.data_manager)

# Initialize end-of-day processing flag (runs once per session)
if 'eod_processing_checked' not in st.session_state:
    st.session_state.eod_processing_checked = False

dm = st.session_state.data_manager
ps = st.session_state.point_system
analytics = st.session_state.analytics_engine
import_export = st.session_state.import_export_manager
notifications = st.session_state.notification_manager

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

# Check and process end-of-day for pending dates (runs once per session)
if not st.session_state.eod_processing_checked:
    processing_results = dm.check_and_process_pending_dates()
    st.session_state.eod_processing_checked = True
    
    # Store results for potential display
    if processing_results:
        st.session_state.eod_processing_results = processing_results

# Auto-activate scheduled placements whose start date has arrived (runs once per session)
if 'scheduled_activation_checked' not in st.session_state:
    activated_count = dm.activate_scheduled_placements()
    st.session_state.scheduled_activation_checked = True
    if activated_count > 0:
        st.session_state.placements_activated = activated_count

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
        "date": date.today(),
        "type": "cool_down",
        "scope": f"{time_start.strftime('%I:%M %p')} - {time_end.strftime('%I:%M %p')}",
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

def render_auto_save_notes(unique_key: str, current_notes: str, save_callback):
    """
    Render an always-visible Notes text area with auto-save functionality.
    
    Args:
        unique_key: Unique identifier for session state keys (e.g., placement_id + date)
        current_notes: Current notes value from database
        save_callback: Function to call to save notes, takes (notes_text) as argument
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
            on_change=on_notes_change,
            label_visibility="collapsed"
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

# Main title with logo
col_logo, col_title = st.columns([1, 4])
with col_logo:
    st.image("attached_assets/Bobcats_1761658497832.png", width=150)
with col_title:
    st.title("The Grotto")
    st.caption("Student Support Placement Platform")

# Sidebar navigation
st.sidebar.title("Navigation")

# Role selector
user_role = st.sidebar.selectbox(
    "User Role",
    ["Staff", "Supervisor", "Admin"],
    index=1  # Default to Supervisor
)

st.sidebar.divider()

# Page options for navigation
PAGE_OPTIONS = ["Dashboard", "Placements", "Assignments", "Notes", "Notifications", "Reports & Analytics", "Import/Export"]

# Initialize navigation state
if 'current_page' not in st.session_state:
    st.session_state.current_page = "Dashboard"

# Handle navigation requests BEFORE rendering sidebar
# These flags are set by various parts of the app to request page changes
if st.session_state.get('navigate_to_create_placement'):
    st.session_state.current_page = "Placements"
    del st.session_state.navigate_to_create_placement
elif st.session_state.get('navigate_to_dashboard'):
    st.session_state.current_page = "Dashboard"
    del st.session_state.navigate_to_dashboard
elif st.session_state.get('navigate_to_iss_detail'):
    st.session_state.current_page = "ISS Detail"
    del st.session_state.navigate_to_iss_detail

# Ensure current_page is in valid options for sidebar display (fallback to Dashboard for hidden pages)
display_page = st.session_state.current_page if st.session_state.current_page in PAGE_OPTIONS else "Dashboard"

# Get the index for the current page to control sidebar selection
current_page_index = PAGE_OPTIONS.index(display_page) if display_page in PAGE_OPTIONS else 0

# Sidebar page selector - uses index to control selection, no key to avoid widget state conflicts
sidebar_page = st.sidebar.selectbox(
    "Select a page:",
    PAGE_OPTIONS,
    index=current_page_index
)

# Update current_page when user manually selects a different page from sidebar
if sidebar_page != st.session_state.current_page and sidebar_page in PAGE_OPTIONS:
    st.session_state.current_page = sidebar_page
    st.rerun()

# Use current_page as the source of truth for rendering
page = st.session_state.current_page

# Show notification badge in sidebar
all_notifs = notifications.get_all_notifications()
warning_count = len([n for n in all_notifs if n.get('severity') == 'warning'])
if warning_count > 0:
    st.sidebar.warning(f"⚠️ {warning_count} notifications require attention")

# Dashboard Page
if page == "Dashboard":
    # Create New Placement button - left-aligned and prominent at the very top
    btn_col1, btn_col2 = st.columns([2, 2])
    with btn_col1:
        if st.button("Create New Placement", type="primary", use_container_width=True):
            st.session_state.navigate_to_create_placement = True
            st.rerun()
    
    st.header("Dashboard")
    
    # Show success message if placement was just created
    if st.session_state.get('placement_created'):
        st.success("Placement created successfully!")
        del st.session_state.placement_created
    
    # Date Selector (compact width)
    if 'dashboard_selected_date' not in st.session_state:
        st.session_state.dashboard_selected_date = date.today()
    
    date_col, _ = st.columns([1, 3])
    with date_col:
        selected_date = st.date_input(
            "Select Date",
            value=st.session_state.dashboard_selected_date,
            key="dashboard_date_selector"
        )
    st.session_state.dashboard_selected_date = selected_date
    
    # Show past date indicator
    is_past_date = selected_date < date.today()
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
        iss_total_required_periods = placement.get('issTotalRequiredPeriods') or (iss_days_assigned * 10)
        iss_periods_served = placement.get('issPeriodsServed', 0) or 0
        days_completed = placement.get('daysCompleted', 0) or 0
        
        # Calculate current day based on completed check-in days (not periods)
        # Current day = days_completed + 1 (if within scheduled days)
        # Make-up days do NOT increment the day counter
        current_day = min(days_completed + 1, iss_days_assigned)
        
        # Check if ISS Session is complete
        is_session_complete = iss_periods_served >= iss_total_required_periods
        
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
            st.info(f"📊 Periods served: **{iss_periods_served}** of **{iss_total_required_periods}**")
            
            # Calculate remaining periods needed
            remaining_periods = iss_total_required_periods - iss_periods_served
            
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
                    periods_remaining = iss_total_required_periods - iss_periods_served
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
                    if is_makeup_session or is_makeup_day:
                        st.markdown("### 📋 Make-Up Full Day Session (10 periods)")
                        st.info(f"**{iss_days_assigned}-day ISS Session for {student_name}** · Make-Up Session")
                    else:
                        st.markdown("### 📋 Full Day ISS Session (10 periods)")
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
                                st.rerun()
                    
                    with col_right:
                        st.markdown("**Points Total**")
                        if total_points >= 10:
                            st.markdown(f"<h2 style='color: green;'>{total_points}</h2>", unsafe_allow_html=True)
                            st.caption("Eligible for completion")
                        else:
                            st.markdown(f"<h2>{total_points}</h2>", unsafe_allow_html=True)
                            st.caption(f"Need {10 - total_points} more points")
                    
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
                        can_complete = total_points >= 10
                        if st.button("✅ Complete", key=f"complete_full_{placement_id}_{date_str}", type="primary", 
                                     use_container_width=True, disabled=not can_complete):
                            dm.complete_iss_full_day_session(placement_id, date_str, "Admin", 
                                                              points_earned=total_points)
                            # Check if make-up is needed after completing
                            makeup_check = dm.check_iss_session_needs_makeup(placement_id)
                            if makeup_check.get('needsMakeup', False):
                                st.session_state[f"show_makeup_prompt_{placement_id}"] = True
                                st.session_state[f"makeup_info_{placement_id}"] = makeup_check
                            st.rerun()
                        if not can_complete:
                            st.caption("Requires 10+ points")
                    
                    with col_override:
                        # Initialize session state for override modal
                        override_key = f"show_override_{placement_id}_{date_str}"
                        if override_key not in st.session_state:
                            st.session_state[override_key] = False
                        
                        if st.button("⚡ Override", key=f"override_btn_{placement_id}_{date_str}", use_container_width=True):
                            st.session_state[override_key] = True
                            st.rerun()
                    
                    # Override panel (shown when Override button is clicked)
                    if st.session_state.get(f"show_override_{placement_id}_{date_str}", False):
                        st.warning("**Override: Complete with full 10-period credit**")
                        override_note = st.text_area(
                            "Reason for Override (required)",
                            key=f"override_note_{placement_id}_{date_str}",
                            placeholder="Enter reason for early release with full credit...",
                            height=80
                        )
                        
                        col_confirm, col_cancel = st.columns(2)
                        with col_confirm:
                            if st.button("Confirm Override", key=f"confirm_override_{placement_id}_{date_str}", 
                                        type="primary", use_container_width=True, disabled=not override_note.strip()):
                                dm.complete_iss_full_day_session(placement_id, date_str, "Admin", 
                                                                  is_override=True, override_note=override_note.strip(),
                                                                  points_earned=total_points)
                                st.session_state[f"show_override_{placement_id}_{date_str}"] = False
                                # Check if make-up is needed after completing
                                makeup_check = dm.check_iss_session_needs_makeup(placement_id)
                                if makeup_check.get('needsMakeup', False):
                                    st.session_state[f"show_makeup_prompt_{placement_id}"] = True
                                    st.session_state[f"makeup_info_{placement_id}"] = makeup_check
                                st.rerun()
                        with col_cancel:
                            if st.button("Cancel", key=f"cancel_override_{placement_id}_{date_str}", use_container_width=True):
                                st.session_state[f"show_override_{placement_id}_{date_str}"] = False
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
                                st.rerun()
                    
                    with col_right:
                        st.markdown("**Points Total**")
                        if total_points >= required_points:
                            st.markdown(f"<h2 style='color: green;'>{total_points}</h2>", unsafe_allow_html=True)
                            st.caption(f"Meets target of {required_points} points")
                        else:
                            st.markdown(f"<h2>{total_points}</h2>", unsafe_allow_html=True)
                            st.caption(f"Target: {required_points} points ({required_points - total_points} more needed)")
                    
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
                            makeup_check = dm.check_iss_session_needs_makeup(placement_id)
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
                                makeup_check = dm.check_iss_session_needs_makeup(placement_id)
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
                
                st.warning(f"""
                **⚠️ ISS Session Needs Make-Up Periods**
                
                This student still needs **{periods_remaining}** more periods to complete this ISS Session.
                
                Would you like to keep the case open for a make-up Session?
                """)
                
                col_keep, col_close = st.columns(2)
                with col_keep:
                    if st.button("✅ YES, keep the case open", key=f"keep_open_main_{placement_id}", 
                                type="primary", use_container_width=True):
                        dm.keep_iss_session_open_for_makeup(placement_id)
                        st.session_state[f"show_makeup_prompt_{placement_id}"] = False
                        st.success("Case kept open for make-up periods.")
                        st.rerun()
                
                with col_close:
                    close_key = f"show_close_early_main_{placement_id}"
                    if close_key not in st.session_state:
                        st.session_state[close_key] = False
                    
                    if st.button("❌ NO, close the case anyway", key=f"close_early_main_btn_{placement_id}", 
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
                if not is_completed:
                    if st.button("✓ Complete", key=f"complete_{placement_id}_{date_str}", type="primary"):
                        dm.complete_placement_day(placement_id, date_str, "Admin")
                        st.rerun()
                else:
                    st.success("Completed")
            
            st.caption(f"📚 {period_label}")
            st.caption(f"Points: {total_points}")
            
            # Notes (always visible with auto-save, safe access - daily_log may be None)
            st.caption("Notes")
            render_auto_save_notes(
                f"partial_{placement_id}_{date_str}",
                (daily_log.get('notes', '') if daily_log else '') or '',
                lambda notes: dm.update_daily_log_notes(placement_id, date_str, notes)
            )
            
            st.divider()
    
    # Helper function to render Lunch Detention student card
    def render_lunch_detention_card(placement: dict, target_date: date):
        """Render Lunch Detention card with attendance and Day X of Y.
        
        Uses lazy loading for daily logs.
        """
        from utils import get_daily_status_color, calculate_school_day_number
        
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
            status_color = 'yellow'  # Default to yellow (pending)
        status_icon = {'green': '🟢', 'yellow': '🟡', 'red': '🔴'}.get(status_color, '⚪')
        
        # Day X of Y for multi-day lunch detention
        total_days = placement.get('daysAssigned', 0)
        day_number = calculate_school_day_number(placement['startDate'], date_str)
        
        # Check attendance
        served_dates = placement.get('servedDates', [])
        is_present = date_str in served_dates
        
        with st.container():
            col1, col2, col3 = st.columns([3, 1, 2])
            
            with col1:
                st.markdown(f"**{status_icon} {student_name}**")
            
            with col2:
                st.caption(f"Grade {student.get('grade', 'N/A')}")
            
            with col3:
                # Attendance toggle
                attendance_key = f"attendance_{placement_id}_{date_str}"
                if attendance_key not in st.session_state:
                    st.session_state[attendance_key] = "Present" if is_present else "Absent"
                
                attendance = st.radio(
                    "Attendance",
                    ["Present", "Absent"],
                    index=0 if st.session_state[attendance_key] == "Present" else 1,
                    horizontal=True,
                    key=f"radio_{attendance_key}",
                    label_visibility="collapsed"
                )
                
                if attendance != st.session_state[attendance_key]:
                    st.session_state[attendance_key] = attendance
                    dm.update_lunch_detention_attendance(placement_id, date_str, attendance == "Present")
                    st.rerun()
            
            # Day X of Y
            if total_days > 1 and day_number > 0:
                st.caption(f"📅 Day {day_number} of {total_days}")
            
            # Complete button (safe access - daily_log may be None)
            is_completed = daily_log.get('dailyFulfillment') == 'yes' if daily_log else False
            if not is_completed:
                if st.button("✓ Complete", key=f"complete_{placement_id}_{date_str}", type="primary"):
                    dm.complete_placement_day(placement_id, date_str, "Admin")
                    st.rerun()
            else:
                st.success("Completed")
            
            # Notes (always visible with auto-save, safe access - daily_log may be None)
            st.caption("Notes")
            render_auto_save_notes(
                f"lunch_{placement_id}_{date_str}",
                (daily_log.get('notes', '') if daily_log else '') or '',
                lambda notes: dm.update_daily_log_notes(placement_id, date_str, notes)
            )
            
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
        
        # LAZY LOADING: Only fetch daily log if it exists (read-only check)
        daily_log = dm.get_daily_log(placement_id, date_str)
        
        if daily_log:
            fulfillment = daily_log.get('dailyFulfillment') or ''
            status_color = get_daily_status_color(fulfillment, date_str)
        else:
            fulfillment = ''
            status_color = 'yellow'  # Default to yellow (pending)
        
        # Determine subtype from placement data
        placement_type = placement.get('placementType', '').upper()
        referral_subtype = placement.get('referralSubtype', '')
        
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
            # Header: Name, Grade, Status
            col1, col2 = st.columns([4, 1])
            
            with col1:
                st.markdown(f"**{status_icon} {student_name}**")
            
            with col2:
                st.caption(f"Grade {student.get('grade', 'N/A')}")
            
            # Subtype label
            if subtype_key == 'behavior':
                st.caption(f"📚 **{subtype_display}**")
            elif subtype_key == 'cool_down':
                st.caption(f"🧘 **{subtype_display}**")
            else:
                st.caption(f"📅 **{subtype_display}**")
            
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
                    # Behavior Referral: Simple "Complete Referral" button
                    if st.button("Complete Referral", key=f"complete_behavior_{placement_id}_{date_str}", type="primary"):
                        dm.complete_placement_day(placement_id, date_str, "Admin")
                        st.rerun()
                
                elif subtype_key == 'cool_down':
                    # Cool-Down Referral: "Complete Cool-Down" button
                    if st.button("Complete Cool-Down", key=f"complete_cooldown_{placement_id}_{date_str}", type="primary"):
                        dm.complete_placement_day(placement_id, date_str, "Admin")
                        st.rerun()
                
                elif subtype_key == 'pre_planned':
                    # Pre-Planned Referral: Check In + Complete workflow
                    checkin_status = dm.get_preplanned_checkin_status(placement_id, date_str)
                    is_checked_in = checkin_status.get('checked_in', False)
                    checked_in_at = checkin_status.get('checked_in_at')
                    
                    col_checkin, col_complete = st.columns([1, 1])
                    
                    with col_checkin:
                        if is_checked_in:
                            # Show check-in confirmation
                            checkin_time = checked_in_at.strftime('%I:%M %p') if checked_in_at else ''
                            st.success(f"✓ Checked In {checkin_time}")
                        else:
                            # Show Check In button
                            if st.button("Check In", key=f"checkin_preplanned_{placement_id}_{date_str}", type="secondary"):
                                dm.checkin_preplanned_session(placement_id, date_str)
                                st.rerun()
                    
                    with col_complete:
                        # Complete button - sets attendance based on check-in status
                        if st.button("Complete", key=f"complete_preplanned_{placement_id}_{date_str}", type="primary"):
                            dm.complete_preplanned_session(placement_id, date_str, "Admin")
                            st.rerun()
                    
                    # Show attendance preview
                    if not is_checked_in:
                        st.caption("⚠️ If completed now, attendance will be marked as **Absent**")
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
            
            # Notes (always visible with auto-save, safe access - daily_log may be None)
            st.caption("Notes")
            render_auto_save_notes(
                f"classref_{placement_id}_{date_str}",
                (daily_log.get('notes', '') if daily_log else '') or '',
                lambda notes: dm.update_daily_log_notes(placement_id, date_str, notes)
            )
            
            st.divider()
    
    # Helper function to render enhanced ISS session card
    def render_iss_session_card(iss_session: dict, target_date: date):
        """Render enhanced ISS session card with full functionality.
        
        Handles three states:
        - Future (scheduled): Locked card with 'First Check-In Date' label
        - Active: Fully interactive card
        - Completed: Shows completion status
        """
        session_id = iss_session['session_id']
        placement_id = iss_session['placement_id']
        student_id = iss_session['student_id']
        student_name = iss_session['student_name']
        date_str = iss_session['date']
        periods = iss_session.get('periods', list(range(1, 11)))
        is_full_day = len(periods) == 10 and periods == list(range(1, 11))
        is_past_session = target_date < date.today()
        
        # Check if this is a future-dated (scheduled) placement
        placement_status = iss_session.get('placement_status', 'active')
        start_date_str = iss_session.get('start_date')
        is_future_placement = False
        start_date_obj = None
        if start_date_str:
            start_date_obj = datetime.fromisoformat(start_date_str).date()
            is_future_placement = start_date_obj > date.today()
        
        # Also check placement_status for scheduled
        if placement_status == 'scheduled':
            is_future_placement = True
        
        # If this is a future-dated placement, show locked card
        if is_future_placement:
            # Get ISS days for the label
            placement_data = dm.get_placement(placement_id)
            iss_total_days = placement_data.get('issTotalDays', 1) if placement_data else 1
            if iss_total_days is None:
                iss_total_days = 1
            
            # Format start date for display
            formatted_start_date = start_date_obj.strftime('%B %d, %Y') if start_date_obj else 'Unknown'
            
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
                    st.button("Check In", key=f"iss_checkin_{session_id}", disabled=True)
                
                # "First Check-In Date" label - prominent display
                st.info(f"📅 **First Check-In Date:** {formatted_start_date}")
                st.caption("This ISS Session has not started yet. Check-in will be available on the start date.")
                
                st.markdown("</div>", unsafe_allow_html=True)
            
            return  # Exit early for future placements
        
        # LAZY LOADING: Only fetch daily log if it exists (read-only check)
        daily_log = dm.get_daily_log(placement_id, date_str)
        
        # Only fetch point events if student is checked in (lazy loading)
        is_checked_in = (daily_log.get('checkedIn', False) if daily_log else False)
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
        
        session_status = iss_session.get('status', 'scheduled')
        fulfillment = (daily_log.get('dailyFulfillment') or '') if daily_log else ''
        override_used = (daily_log.get('overrideUsed', False) if daily_log else False)
        is_day_completed = session_status == 'fulfilled' or fulfillment == 'yes' or override_used
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
            header_col1, header_col2, header_col3 = st.columns([3, 2, 1])
            
            with header_col1:
                st.markdown(f"**{day_progress_label}**")
                st.caption(f"Grade {iss_session.get('grade', 'N/A')} · {iss_session.get('homeroom_teacher', 'N/A')}")
            
            with header_col2:
                pass
            
            with header_col3:
                # Check In button (replaces Present/Absent)
                if is_completed:
                    st.success("Checked Out")
                elif is_checked_in:
                    st.button("Check In", key=f"iss_checkin_{session_id}", disabled=True)
                else:
                    if st.button("Check In", key=f"iss_checkin_{session_id}", type="primary"):
                        dm.check_in_student(placement_id, date_str)
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
            
            # Day Type selector and controls (only show when checked in and not completed)
            if is_checked_in and not is_completed:
                # Initialize session state for day type - preload from daily log if available
                day_type_key = f"iss_day_type_{session_id}"
                start_period_key = f"iss_start_period_{session_id}"
                end_period_key = f"iss_end_period_{session_id}"
                
                # Preload existing values from daily log if they exist
                stored_day_type = daily_log.get('dayType') if daily_log else None
                stored_start_period = daily_log.get('startPeriod') if daily_log else None
                stored_end_period = daily_log.get('endPeriod') if daily_log else None
                
                if day_type_key not in st.session_state:
                    # Use stored value if available, else default based on is_full_day
                    if stored_day_type == 'full':
                        st.session_state[day_type_key] = "Full Day"
                    elif stored_day_type == 'partial':
                        st.session_state[day_type_key] = "Partial Day"
                    else:
                        st.session_state[day_type_key] = "Full Day" if is_full_day else "Partial Day"
                
                # Preload start/end periods if stored
                if start_period_key not in st.session_state and stored_start_period:
                    st.session_state[start_period_key] = stored_start_period
                if end_period_key not in st.session_state and stored_end_period:
                    st.session_state[end_period_key] = stored_end_period
                
                # Day Type selector
                st.markdown("**Day Type**")
                day_type_col, periods_col = st.columns([1, 2])
                
                with day_type_col:
                    day_type = st.radio(
                        "Select Day Type",
                        options=["Full Day", "Partial Day"],
                        key=day_type_key,
                        horizontal=True,
                        label_visibility="collapsed"
                    )
                
                with periods_col:
                    period_validation_error = None
                    selected_start_period = None
                    selected_end_period = None
                    
                    if day_type == "Partial Day":
                        # Show Start and End Period dropdowns
                        period_options = list(range(1, 11))  # 1-10
                        
                        # Determine default index from stored values or defaults
                        default_start_idx = (stored_start_period - 1) if stored_start_period else 0
                        default_end_idx = (stored_end_period - 1) if stored_end_period else (len(period_options) - 1)
                        
                        period_col1, period_col2 = st.columns(2)
                        with period_col1:
                            selected_start_period = st.selectbox(
                                "Start Period*",
                                options=period_options,
                                key=start_period_key,
                                index=default_start_idx if start_period_key not in st.session_state else None
                            )
                        with period_col2:
                            selected_end_period = st.selectbox(
                                "End Period*",
                                options=period_options,
                                key=end_period_key,
                                index=default_end_idx if end_period_key not in st.session_state else None
                            )
                        
                        # Validate Start/End Period
                        if selected_start_period is None or selected_end_period is None:
                            period_validation_error = "Start Period and End Period are required for Partial Day."
                        elif selected_end_period < selected_start_period:
                            period_validation_error = "End Period must be greater than or equal to Start Period."
                        
                        if period_validation_error:
                            st.error(period_validation_error)
                    else:
                        # Full Day - periods are 1-10 (all periods)
                        st.caption("Full Day: Periods 1-10 (all periods)")
                
                st.divider()
            
            if is_checked_in and not is_completed:
                points_col, behaviors_col = st.columns([1, 1])
                
                with behaviors_col:
                    st.markdown("**Add Behaviors**")
                    pos_col, neg_col = st.columns(2)
                    
                    with pos_col:
                        positive_menu = ps.get_positive_point_menu()
                        positive_options = ["+ Positive"] + [item['label'] for item in positive_menu]
                        selected_positive = st.selectbox(
                            "Positive",
                            positive_options,
                            key=f"iss_pos_{session_id}",
                            label_visibility="collapsed"
                        )
                        if selected_positive != "+ Positive":
                            item = next((i for i in positive_menu if i['label'] == selected_positive), None)
                            if item:
                                dm.add_point_event({
                                    'placementId': placement_id,
                                    'studentId': student_id,
                                    'sessionId': session_id,
                                    'code': item['code'],
                                    'type': 'positive',
                                    'value': item['value'],
                                    'date': date_str
                                })
                                st.rerun()
                    
                    with neg_col:
                        negative_menu = ps.get_negative_point_menu()
                        negative_options = ["- Negative"] + [item['label'] for item in negative_menu]
                        selected_negative = st.selectbox(
                            "Negative",
                            negative_options,
                            key=f"iss_neg_{session_id}",
                            label_visibility="collapsed"
                        )
                        if selected_negative != "- Negative":
                            item = next((i for i in negative_menu if i['label'] == selected_negative), None)
                            if item:
                                dm.add_point_event({
                                    'placementId': placement_id,
                                    'studentId': student_id,
                                    'sessionId': session_id,
                                    'code': item['code'],
                                    'type': 'negative',
                                    'value': item['value'],
                                    'date': date_str
                                })
                                st.rerun()
                
                with points_col:
                    st.markdown("**Points Total**")
                    # Get selected day type from session state
                    current_day_type = st.session_state.get(f"iss_day_type_{session_id}", "Full Day")
                    is_full_day_selected = current_day_type == "Full Day"
                    
                    if is_full_day_selected:
                        if total_points >= 10:
                            st.markdown(f"<h2 style='color: green; margin: 0;'>{total_points}</h2>", unsafe_allow_html=True)
                            st.caption("✓ Eligible for completion")
                        else:
                            st.markdown(f"<h2 style='margin: 0;'>{total_points}</h2>", unsafe_allow_html=True)
                            st.caption(f"Need {10 - total_points} more points")
                    else:
                        # Partial day - points requirement varies by periods
                        current_start = st.session_state.get(f"iss_start_period_{session_id}", 1)
                        current_end = st.session_state.get(f"iss_end_period_{session_id}", 10)
                        periods_count = max(1, current_end - current_start + 1) if current_end >= current_start else 1
                        required_points = periods_count  # 1 point per period
                        if total_points >= required_points:
                            st.markdown(f"<h2 style='color: green; margin: 0;'>{total_points}</h2>", unsafe_allow_html=True)
                            st.caption(f"✓ {periods_count} periods = {required_points} points needed")
                        else:
                            st.markdown(f"<h2 style='margin: 0;'>{total_points}</h2>", unsafe_allow_html=True)
                            st.caption(f"{periods_count} periods = {required_points} points needed")
                
                action_col1, action_col2 = st.columns(2)
                
                with action_col1:
                    # Check period validation for Partial Day
                    current_day_type = st.session_state.get(f"iss_day_type_{session_id}", "Full Day")
                    has_period_error = False
                    if current_day_type == "Partial Day":
                        curr_start = st.session_state.get(f"iss_start_period_{session_id}", 1)
                        curr_end = st.session_state.get(f"iss_end_period_{session_id}", 10)
                        if curr_end < curr_start:
                            has_period_error = True
                    
                    can_complete = (not has_period_error) and ((current_day_type != "Full Day") or (current_day_type == "Full Day" and total_points >= 10))
                    complete_help = ""
                    if has_period_error:
                        complete_help = "Fix period validation errors first"
                    elif current_day_type == "Full Day" and total_points < 10:
                        complete_help = "Full day requires 10+ points"
                    
                    complete_label = "✓ Complete Day (Retroactive)" if is_past_session else "✓ Complete Day"
                    if st.button(complete_label, key=f"iss_complete_{session_id}", type="primary", 
                                 use_container_width=True, disabled=not can_complete, help=complete_help):
                        # Get day type and period settings from session state
                        selected_day_type = st.session_state.get(f"iss_day_type_{session_id}", "Full Day")
                        selected_start = st.session_state.get(f"iss_start_period_{session_id}", 1)
                        selected_end = st.session_state.get(f"iss_end_period_{session_id}", 10)
                        
                        # Call the complete_iss_day method which handles:
                        # - Computing servedPeriodsForThisDay (10 for Full, end-start+1 for Partial)
                        # - Updating iss_periods_served on the placement
                        # - Auto-completing when servedPeriodsTotal >= requiredTotalPeriods
                        result = dm.complete_iss_day(
                            placement_id=placement_id,
                            log_date=date_str,
                            completed_by="Admin",
                            day_type=selected_day_type,
                            start_period=selected_start,
                            end_period=selected_end,
                            points_earned=total_points
                        )
                        
                        if result.get('success'):
                            # Also mark the session as completed
                            dm.mark_session_completed(session_id, "Admin")
                            if not is_present:
                                dm.update_iss_attendance(placement_id, date_str, True)
                            
                            # Check if placement is now complete
                            if result.get('isCompleted'):
                                st.success("ISS Session complete! All required periods served.")
                            else:
                                # Check if make-up is needed
                                makeup_check = dm.check_iss_session_needs_makeup(placement_id)
                                if makeup_check.get('needsMakeup', False):
                                    st.session_state[f"show_makeup_prompt_{placement_id}"] = True
                                    st.session_state[f"makeup_info_{placement_id}"] = makeup_check
                                st.success("ISS day completed successfully!")
                            
                            # Clear dashboard caches to refresh data
                            if hasattr(st, 'cache_data'):
                                st.cache_data.clear()
                            st.rerun()
                        else:
                            st.error(result.get('message', 'Failed to complete ISS day'))
                
                with action_col2:
                    override_key = f"iss_override_expand_{session_id}"
                    if override_key not in st.session_state:
                        st.session_state[override_key] = False
                    
                    override_label = "🔓 Override (Retroactive)" if is_past_session else "🔓 Override & Count Full"
                    if st.button(override_label, key=f"iss_override_btn_{session_id}", 
                                 use_container_width=True):
                        st.session_state[override_key] = not st.session_state[override_key]
                        st.rerun()
                
                if st.session_state.get(f"iss_override_expand_{session_id}", False):
                    warning_msg = "⚠️ This will retroactively mark the session complete and credit all scheduled periods." if is_past_session else "⚠️ This will mark the session complete and credit all scheduled periods."
                    st.warning(warning_msg)
                    if st.button("Confirm Override", key=f"iss_override_confirm_{session_id}", type="primary"):
                        override_note = "Retroactive override: session marked complete after the fact." if is_past_session else "Supervisor override: student released early due to positive behavior; remaining periods waived."
                        
                        # Use complete_iss_day with override flag - always use Full Day for override
                        result = dm.complete_iss_day(
                            placement_id=placement_id,
                            log_date=date_str,
                            completed_by="Admin",
                            day_type="Full Day",  # Override always credits full day
                            start_period=1,
                            end_period=10,
                            points_earned=total_points,
                            is_override=True,
                            override_note=override_note
                        )
                        
                        if result.get('success'):
                            dm.mark_session_completed(session_id, "Admin", is_override=True, override_comment=override_note)
                            if not is_present:
                                dm.update_iss_attendance(placement_id, date_str, True)
                            
                            # Check if placement is now complete
                            if result.get('isCompleted'):
                                st.success("✅ Override applied! ISS Session complete.")
                            else:
                                # Check if make-up is needed after completing
                                makeup_check = dm.check_iss_session_needs_makeup(placement_id)
                                if makeup_check.get('needsMakeup', False):
                                    st.session_state[f"show_makeup_prompt_{placement_id}"] = True
                                    st.session_state[f"makeup_info_{placement_id}"] = makeup_check
                                st.success("✅ Override applied retroactively!" if is_past_session else "✅ Override applied!")
                            
                            st.session_state[f"iss_override_expand_{session_id}"] = False
                            if hasattr(st, 'cache_data'):
                                st.cache_data.clear()
                            st.rerun()
                        else:
                            st.error(result.get('message', 'Failed to apply override'))
            elif not is_checked_in and not is_completed and not is_no_show:
                st.caption("Check in student to add behaviors and track points")
            elif is_no_show:
                st.error("Not Completed")
                st.markdown(f"**Points Total: {total_points}**")
                st.caption("Session was not completed by end of day")
                
                retro_col1, retro_col2 = st.columns(2)
                with retro_col1:
                    if st.button("Mark Complete (Retroactive)", key=f"iss_retro_complete_{session_id}"):
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
                    if st.button("Apply Override", key=f"iss_retro_override_{session_id}"):
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
                
                st.warning(f"""
                **⚠️ ISS Session Needs Make-Up Periods**
                
                This student still needs **{periods_remaining}** more periods to complete this ISS Session.
                
                Would you like to keep the case open for a make-up Session?
                """)
                
                col_keep, col_close = st.columns(2)
                with col_keep:
                    if st.button("✅ YES, keep the case open", key=f"keep_open_final_{placement_id}", 
                                type="primary", use_container_width=True):
                        dm.keep_iss_session_open_for_makeup(placement_id)
                        st.session_state[f"show_makeup_prompt_{placement_id}"] = False
                        st.success("Case kept open for make-up periods.")
                        st.rerun()
                
                with col_close:
                    close_key = f"show_close_early_final_{placement_id}"
                    if close_key not in st.session_state:
                        st.session_state[close_key] = False
                    
                    if st.button("❌ NO, close the case anyway", key=f"close_early_final_btn_{placement_id}", 
                                use_container_width=True):
                        st.session_state[close_key] = True
                        st.rerun()
                
                if st.session_state.get(f"show_close_early_final_{placement_id}", False):
                    st.info("**Close Case Early**")
                    close_note = st.text_area(
                        "Reason for closing early (optional):",
                        key=f"close_early_final_note_{placement_id}",
                        placeholder="Session closed early — remaining periods waived by staff judgment.",
                        height=80
                    )
                    
                    col_confirm_close, col_cancel_close = st.columns(2)
                    with col_confirm_close:
                        if st.button("Confirm Close", key=f"confirm_close_final_{placement_id}", 
                                    type="primary", use_container_width=True):
                            note = close_note.strip() if close_note.strip() else "Session closed early — remaining periods waived by staff judgment."
                            dm.close_iss_session_early(placement_id, note)
                            st.session_state[f"show_makeup_prompt_{placement_id}"] = False
                            st.session_state[f"show_close_early_final_{placement_id}"] = False
                            st.success(f"Case closed. {periods_remaining} periods waived.")
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
    scheduled_iss_placements = get_scheduled_iss_placements_cached()
    
    st.markdown("#### In-School Suspension (ISS)")
    
    # First, show active sessions for the selected date
    has_active_sessions = len(iss_sessions) > 0
    has_scheduled_placements = len(scheduled_iss_placements) > 0
    
    if not has_active_sessions and not has_scheduled_placements:
        st.caption("No students")
    else:
        # Show active sessions first
        for iss_session in iss_sessions:
            session_id = iss_session['session_id']
            student_name = iss_session['student_name']
            progress_status = iss_session.get('progressStatus', 'NOT_STARTED')
            
            # Create colored circle based on progress_status
            if progress_status == "COMPLETED":
                status_circle = "🔴"  # Red circle for COMPLETED
            elif progress_status == "IN_PROGRESS":
                status_circle = "🟡"  # Yellow circle for IN_PROGRESS
            else:
                status_circle = "🟢"  # Green circle for NOT_STARTED
            
            with st.expander(f"{status_circle} {student_name}", expanded=False):
                render_iss_session_card(iss_session, selected_date)
        
        # Then show scheduled (future) placements as locked cards
        for scheduled_placement in scheduled_iss_placements:
            placement_id = scheduled_placement['placement_id']
            student_name = scheduled_placement['student_name']
            start_date_str = scheduled_placement.get('start_date')
            iss_days = scheduled_placement.get('iss_days_assigned') or scheduled_placement.get('iss_total_days', 1) or 1
            
            # Format the start date for display
            start_date_obj = datetime.fromisoformat(start_date_str).date() if start_date_str else None
            formatted_start_date = start_date_obj.strftime('%B %d, %Y') if start_date_obj else 'Unknown'
            
            # Scheduled placements are always "NOT_STARTED" - show green circle
            with st.expander(f"🟢 🔒 {student_name}", expanded=False):
                # Render locked card for scheduled placement
                with st.container():
                    st.markdown(f"<div style='opacity: 0.6;'>", unsafe_allow_html=True)
                    
                    header_col1, header_col2 = st.columns([3, 1])
                    
                    with header_col1:
                        days_label = "Day" if iss_days == 1 else "Days"
                        st.markdown(f"**{iss_days}-{days_label} ISS Session**")
                        st.caption(f"Grade {scheduled_placement.get('grade', 'N/A')} · {scheduled_placement.get('homeroom_teacher', 'N/A')}")
                    
                    with header_col2:
                        st.button("Check In", key=f"iss_scheduled_checkin_{placement_id}", disabled=True)
                    
                    st.info(f"📅 **First Check-In Date:** {formatted_start_date}")
                    st.caption("This ISS Session has not started yet. Check-in will be available on the start date.")
                    
                    st.markdown("</div>", unsafe_allow_html=True)
    
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
            
            # Create colored circle based on progress_status
            if progress_status == "COMPLETED":
                status_circle = "🔴"  # Red circle for COMPLETED
            elif progress_status == "IN_PROGRESS":
                status_circle = "🟡"  # Yellow circle for IN_PROGRESS
            else:
                status_circle = "🟢"  # Green circle for NOT_STARTED
            
            with st.expander(f"{status_circle} {student_name}", expanded=False):
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
            
            # Create colored circle based on progress_status
            if progress_status == "COMPLETED":
                status_circle = "🔴"  # Red circle for COMPLETED
            elif progress_status == "IN_PROGRESS":
                status_circle = "🟡"  # Yellow circle for IN_PROGRESS
            else:
                status_circle = "🟢"  # Green circle for NOT_STARTED
            
            with st.expander(f"{status_circle} {student_name}", expanded=False):
                render_unified_class_referral_card(placement, selected_date)

# Placements Page
elif page == "Placements":
    st.header("Placement Manager")
    
    # Get counts for badges
    completed_placements = dm.get_completed_placements_with_students()
    completed_count = len(completed_placements)
    
    # Get completed ISS placements for history tab
    completed_iss_placements = dm.get_completed_iss_placements()
    iss_history_count = len(completed_iss_placements)
    
    tab1, tab2, tab3 = st.tabs([
        "Create Placement", 
        f"Completed Placements ({completed_count})",
        f"ISS History ({iss_history_count})"
    ])
    
    # Tab 1: Create Placement
    with tab1:
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
                iss_start_date = st.date_input("Start Date*", value=date.today(), help="First day of ISS placement", key="iss_start_date")
            with sched_col2:
                iss_total_days = st.number_input("Number of ISS Days*", min_value=1, value=1, step=1, help="Total ISS days assigned", key="iss_total_days")
            
            created_by = st.selectbox("Created By*", ["Matthew Christie", "Aaron Toronto", "Todd Foster", "Chad Adamson"], key="iss_created_by")
            
            if st.button("Create ISS Placement", type="primary", use_container_width=True, key="iss_submit"):
                print(f"[DEBUG] ISS button clicked - First: '{first_name}', Last: '{last_name}', Homeroom: '{homeroom_teacher}', Reason: '{reason[:20] if reason else 'empty'}...'")
                if not first_name or not last_name or not homeroom_teacher or not reason or not created_by:
                    st.error("Please fill in all required fields marked with *")
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
                            "createdAt": datetime.now().isoformat()
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
                start_date = st.date_input("Start Date*", value=date.today(), key="ld_start_date")
            with sched_col2:
                lunch_days = st.number_input("Number of Lunch Detention Days*", min_value=1, value=1, step=1, help="Number of lunch detention days", key="ld_lunch_days")
            
            created_by = st.selectbox("Created By*", ["Matthew Christie", "Aaron Toronto", "Todd Foster", "Chad Adamson"], key="ld_created_by")
            
            if st.button("Create Lunch Detention", type="primary", use_container_width=True, key="ld_submit"):
                print(f"[DEBUG] Lunch Detention button clicked - First: '{first_name}', Last: '{last_name}', Homeroom: '{homeroom_teacher}', Reason: '{reason[:20] if reason else 'empty'}...'")
                if not first_name or not last_name or not homeroom_teacher or not reason or not created_by:
                    st.error("Please fill in all required fields marked with *")
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
                            "createdAt": datetime.now().isoformat()
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
                    start_date = st.date_input("Date*", value=date.today(), key="br_start_date")
                with sched_col2:
                    selected_period = st.selectbox("Period*", options=[1, 2, 3, 4, 5, 6, 7, 8, 9, 10], format_func=lambda x: f"P{x}", key="br_period")
                
                created_by = st.selectbox("Created By*", ["Matthew Christie", "Aaron Toronto", "Todd Foster", "Chad Adamson"], key="br_created_by")
                
                if st.button("Create Behavior Referral", type="primary", use_container_width=True, key="br_submit"):
                    print(f"[DEBUG] Behavior Referral button clicked - First: '{first_name}', Last: '{last_name}'")
                    if not first_name or not last_name or not homeroom_teacher or not reason or not created_by:
                        st.error("Please fill in all required fields marked with *")
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
                                "createdAt": datetime.now().isoformat()
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
                    cooldown_date = st.date_input("Date*", value=date.today(), key="cd_date")
                with sched_col2:
                    selected_period = st.selectbox("Period*", options=[1, 2, 3, 4, 5, 6, 7, 8, 9, 10], format_func=lambda x: f"P{x}", key="cd_period")
                
                created_by = st.selectbox("Created By*", ["Matthew Christie", "Aaron Toronto", "Todd Foster", "Chad Adamson"], key="cd_created_by")
                
                if st.button("Create Cool-Down Referral", type="primary", use_container_width=True, key="cd_submit"):
                    print(f"[DEBUG] Cool-Down Referral button clicked - First: '{first_name}', Last: '{last_name}'")
                    if not first_name or not last_name or not homeroom_teacher or not reason or not created_by:
                        st.error("Please fill in all required fields marked with *")
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
                                "createdAt": datetime.now().isoformat()
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
                    st.session_state.preplanned_schedule = [{"date": date.today(), "periods": [1]}]
                
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
                            value=row_data.get("date", date.today()),
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
                            row_date = st.date_input(
                                f"Date",
                                value=row_data.get("date", date.today()),
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
                    
                    created_by = st.selectbox("Created By*", ["Matthew Christie", "Aaron Toronto", "Todd Foster", "Chad Adamson"], key="pp_created_by")
                    
                    submit_button = st.form_submit_button("Create Pre-Planned Referral", type="primary", use_container_width=True)
                    
                    if add_row_button:
                        st.session_state.preplanned_schedule.append({"date": date.today(), "periods": [1]})
                        st.rerun()
                    
                    if submit_button:
                        print(f"[DEBUG] Pre-Planned Referral form submitted - First: '{first_name}', Last: '{last_name}'")
                        validation_error = False
                        
                        if not first_name or not last_name or not homeroom_teacher or not reason or not created_by:
                            st.error("Please fill in all required fields marked with *")
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
                                    "createdAt": datetime.now().isoformat()
                                }
                                
                                placement_id = dm.add_placement(placement_data)
                                dm.generate_preplanned_sessions(placement_id, scheduled_slots)
                                
                                st.session_state.preplanned_schedule = [{"date": date.today(), "periods": [1]}]
                                
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
            
    # Tab 2: Completed Placements
    with tab2:
        if completed_placements:
            # Search filters
            st.subheader("Search Completed Placements")
            col1, col2 = st.columns(2)
            with col1:
                search_name = st.text_input("Search by Name", "")
            with col2:
                search_reason = st.text_input("Search by Reason", "")
            
            # Filter placements
            filtered_placements = completed_placements
            if search_name:
                filtered_placements = [p for p in filtered_placements 
                                     if search_name.lower() in f"{p['student']['firstName']} {p['student']['lastName']}".lower()]
            if search_reason:
                filtered_placements = [p for p in filtered_placements 
                                     if search_reason.lower() in p['reason'].lower()]
            
            st.write(f"**Showing {len(filtered_placements)} of {completed_count} completed placements**")
            st.divider()
            
            # Display completed placements
            for placement in filtered_placements:
                student = placement['student']
                placement_type_display = get_placement_type_display_name(placement.get('placementType', ''))
                referral_subtype = placement.get('referralSubtype', '')
                
                with st.expander(f"{student['firstName']} {student['lastName']} - {placement['reason']}"):
                    col1, col2 = st.columns(2)
                    with col1:
                        st.write(f"**Name:** {student['firstName']} {student['lastName']}")
                        st.write(f"**Placement Type:** {placement_type_display}")
                        st.write(f"**Start Date:** {format_date(placement['startDate'])}")
                        st.write(f"**Reason:** {placement['reason']}")
                    with col2:
                        st.write(f"**Number of Days:** {placement['daysAssigned']}")
                        st.write(f"**End Date:** {format_date(placement.get('endDate', 'N/A'))}")
                        st.write(f"**Total Points Earned:** {placement.get('totalPoints', 0)}")
                    
                    # Pre-Planned specific: Show date, periods, and attendance for each day
                    if referral_subtype == 'pre_planned':
                        st.divider()
                        st.markdown("**Session Details:**")
                        scheduled_slots = placement.get('scheduledSlots', [])
                        
                        # Group slots by date
                        from collections import defaultdict
                        slots_by_date = defaultdict(list)
                        for slot in scheduled_slots:
                            slot_date = slot.get('date', '')
                            slot_period = slot.get('period', 0)
                            slots_by_date[slot_date].append(slot_period)
                        
                        # Get daily logs for attendance info
                        placement_id = placement.get('_id')
                        for slot_date in sorted(slots_by_date.keys()):
                            periods = sorted(slots_by_date[slot_date])
                            if len(periods) == 1:
                                period_label = f"Period {periods[0]}"
                            else:
                                period_label = f"Periods {', '.join(map(str, periods))}"
                            
                            # Get check-in status for this date
                            checkin_status = dm.get_preplanned_checkin_status(placement_id, slot_date)
                            was_checked_in = checkin_status.get('checked_in', False)
                            
                            # Display attendance
                            if was_checked_in:
                                attendance_badge = "✅ Attended"
                            else:
                                attendance_badge = "❌ Absent"
                            
                            st.caption(f"📅 {format_date(slot_date)} · {period_label} · {attendance_badge}")
                    
                    # Restore button
                    if st.button(f"Restore to Active", key=f"restore_{placement['_id']}"):
                        dm.restore_placement_to_active(placement['_id'])
                        st.success("✅ Placement restored to active!")
                        st.rerun()
        else:
            st.info("No completed placements found.")
    
    # Tab 3: ISS History
    with tab3:
        st.subheader("Completed ISS Sessions")
        st.caption("View detailed session logs for all completed ISS placements")
        
        if completed_iss_placements:
            # Search filter
            iss_search_name = st.text_input("Search by Student Name", "", key="iss_history_search")
            
            filtered_iss = completed_iss_placements
            if iss_search_name:
                filtered_iss = [p for p in filtered_iss 
                               if iss_search_name.lower() in p['studentName'].lower()]
            
            st.write(f"**Showing {len(filtered_iss)} of {iss_history_count} completed ISS placements**")
            st.divider()
            
            for iss_placement in filtered_iss:
                iss_label = iss_placement.get('issLabel', '')
                student_name = iss_placement.get('studentName', 'Unknown')
                
                with st.expander(f"✅ {iss_label} (Completed)", expanded=False):
                    # Header info
                    col1, col2 = st.columns(2)
                    with col1:
                        st.write(f"**Student:** {student_name}")
                        st.write(f"**Days Assigned:** {iss_placement.get('issDaysAssigned', 0)}")
                        st.write(f"**Reason:** {iss_placement.get('reason', 'N/A')}")
                    with col2:
                        st.write(f"**Start Date:** {format_date(iss_placement.get('startDate', 'N/A'))}")
                        st.write(f"**End Date:** {format_date(iss_placement.get('endDate', 'N/A'))}")
                        periods_served = iss_placement.get('issPeriodsServed', 0)
                        total_required = iss_placement.get('issTotalRequiredPeriods', 0)
                        st.write(f"**Periods Served:** {periods_served} of {total_required}")
                    
                    st.divider()
                    
                    # Session logs
                    session_logs = iss_placement.get('sessionLogs', [])
                    if session_logs:
                        st.markdown("**Session History:**")
                        for i, log in enumerate(session_logs, 1):
                            session_date = log.get('sessionDate', 'Unknown')
                            session_type = log.get('sessionType', 'Unknown')
                            periods_credited = log.get('periodsCredited', 0)
                            completion_method = log.get('completionMethod', 'Unknown')
                            points_earned = log.get('pointsEarned')
                            points_target = log.get('pointsTarget')
                            override_reason = log.get('overrideReason')
                            notes = log.get('notes')
                            
                            # Build session description using periods_covered
                            periods_covered = log.get('periodsCovered', [])
                            if session_type == 'Full Day':
                                period_desc = "Periods 1-10"
                            elif periods_covered:
                                # Display the actual periods attended
                                if len(periods_covered) == 1:
                                    period_desc = f"Period {periods_covered[0]}"
                                else:
                                    period_desc = f"Periods {', '.join(map(str, sorted(periods_covered)))}"
                            else:
                                # Fallback to start/end if no periods_covered
                                start_p = log.get('startPeriod', 1)
                                end_p = log.get('endPeriod', 10)
                                period_desc = f"Periods {start_p}-{end_p}"
                            
                            # Status indicator
                            status_icon = "⚡" if completion_method == "Override" else "✅"
                            
                            # Points display
                            points_display = ""
                            if points_earned is not None:
                                points_display = f" · {points_earned}"
                                if points_target:
                                    points_display += f"/{points_target} pts"
                                else:
                                    points_display += " pts"
                            
                            st.markdown(f"**{i}. {format_date(session_date)}** - {session_type} ({period_desc}) · {periods_credited} periods credited {status_icon}{points_display}")
                            
                            # Show override reason if applicable
                            if completion_method == "Override" and override_reason:
                                st.caption(f"   ⚡ Override: {override_reason}")
                            
                            # Show notes if present
                            if notes:
                                st.caption(f"   📝 Notes: {notes}")
                    else:
                        st.info("No session logs recorded for this placement.")
        else:
            st.info("No completed ISS placements found.")
            st.caption("Completed ISS Sessions will appear here with full session history.")

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
    
    # Calculate Day X of Y
    from utils import calculate_school_day_number
    iss_start_date = placement.get('issStartDate')
    iss_total_days = placement.get('issTotalDays', 0)
    iss_remaining_days = placement.get('issRemainingDays', 0)
    
    if iss_start_date:
        day_number = calculate_school_day_number(iss_start_date, date_str)
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
            st.metric("Total Points", total_points)
            if selected_day_type == "full":
                if total_points >= 10:
                    st.success("✓ Eligible for completion")
                else:
                    st.warning(f"Need {10 - total_points} more")
            else:
                st.caption("No minimum for partial days")
        
        st.divider()
    
    # Notes Section
    st.subheader("4. Notes (Optional)")
    existing_notes = daily_log.get('notes', '') or ''
    notes = st.text_area(
        "Add any notes about today's ISS session:",
        value=existing_notes,
        height=100,
        key="iss_notes",
        disabled=is_completed
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
        
        col_complete, col_override = st.columns(2)
        
        with col_complete:
            # Validation
            can_complete = True
            reasons = []
            
            if selected_day_type == "partial" and not periods_covered:
                can_complete = False
                reasons.append("Select at least one period")
            
            if selected_day_type == "full" and total_points < 10:
                can_complete = False
                reasons.append(f"Need {10 - total_points} more points")
            
            if st.button("✓ Complete Day", type="primary", disabled=not can_complete, use_container_width=True):
                # Save notes first if any
                if notes and notes != existing_notes:
                    dm.update_daily_log_notes(placement_id, date_str, notes)
                
                # Update ISS daily log
                if dm.update_iss_daily_log(placement_id, date_str, selected_day_type, periods_covered, "Admin"):
                    st.success(f"✅ Day completed as '{selected_day_type.title()}' day!")
                    if selected_day_type in ['full', 'partial']:
                        new_remaining = iss_remaining_days - 1
                        st.info(f"ISS remaining days updated: {iss_remaining_days} → {new_remaining}")
                    st.rerun()
                else:
                    st.error("Failed to complete day. Please try again.")
            
            if not can_complete:
                for reason in reasons:
                    st.caption(f"⚠️ {reason}")
        
        with col_override:
            with st.expander("🚨 Call It Good (Override)"):
                st.warning("This will close the ISS placement immediately, regardless of remaining days.")
                st.caption("Use this for early releases approved by administration.")
                
                override_comment = st.text_area(
                    "Required: Explain why this placement is being closed early",
                    key="override_comment",
                    height=80
                )
                
                if st.button("🚨 Close Placement Now", type="secondary", use_container_width=True):
                    if not override_comment or len(override_comment.strip()) < 10:
                        st.error("Please provide a detailed comment (at least 10 characters)")
                    else:
                        if dm.apply_iss_override(placement_id, override_comment, "Admin"):
                            st.success("✅ Placement closed with override!")
                            st.balloons()
                            st.rerun()
                        else:
                            st.error("Failed to apply override. Please try again.")

# Assignments Page
elif page == "Assignments":
    st.header("Assignment Management")
    
    tab1, tab2 = st.tabs(["View Assignments", "Create Assignment"])
    
    with tab1:
        assignments = dm.get_all_assignments_with_students()
        if assignments:
            # Filter options
            col1, col2 = st.columns(2)
            with col1:
                status_filter = st.selectbox("Filter by status", ["All", "assigned", "in_progress", "completed"])
            with col2:
                student_filter = st.selectbox("Filter by student", ["All"] + [f"{a['student']['firstName']} {a['student']['lastName']}" for a in assignments])
            
            # Apply filters
            filtered_assignments = assignments
            if status_filter != "All":
                filtered_assignments = [a for a in filtered_assignments if a['status'] == status_filter]
            if student_filter != "All":
                filtered_assignments = [a for a in filtered_assignments if f"{a['student']['firstName']} {a['student']['lastName']}" == student_filter]
            
            # Display assignments
            for assignment in filtered_assignments:
                student = assignment['student']
                with st.expander(f"{assignment['title']} - {student['firstName']} {student['lastName']}"):
                    col1, col2 = st.columns(2)
                    with col1:
                        st.write(f"**Student:** {student['firstName']} {student['lastName']}")
                        st.write(f"**Teacher:** {assignment.get('teacherId', 'Unknown')}")
                        st.write(f"**Due Date:** {assignment.get('dueDate', 'Not set')}")
                    with col2:
                        st.write(f"**Status:** {assignment['status']}")
                        if assignment.get('linkOrFileRef'):
                            st.write(f"**Link/File:** {assignment['linkOrFileRef']}")
                        if assignment.get('notes'):
                            st.write(f"**Notes:** {assignment['notes']}")
                    
                    # Status update
                    new_status = st.selectbox(
                        "Update Status", 
                        ["assigned", "in_progress", "completed"],
                        index=["assigned", "in_progress", "completed"].index(assignment['status']),
                        key=f"status_{assignment['_id']}"
                    )
                    
                    if st.button(f"Update Status", key=f"update_{assignment['_id']}"):
                        dm.update_assignment_status(assignment['_id'], new_status)
                        st.success("Status updated!")
                        st.rerun()
        else:
            st.info("No assignments found.")
    
    with tab2:
        students = dm.get_all_students()
        if not students:
            st.warning("No students available. Please add students first.")
        else:
            with st.form("create_assignment_form"):
                st.subheader("Create New Assignment")
                
                student_options = [f"{s['firstName']} {s['lastName']}" for s in students]
                selected_student = st.selectbox("Select Student*", student_options)
                
                title = st.text_input("Assignment Title*")
                teacher_id = st.text_input("Teacher ID")
                link_or_file = st.text_input("Link or File Reference")
                due_date = st.date_input("Due Date")
                notes = st.text_area("Notes")
                
                if st.form_submit_button("Create Assignment"):
                    if selected_student and title:
                        student_data = next(s for s in students if f"{s['firstName']} {s['lastName']}" == selected_student)
                        
                        assignment_data = {
                            'studentId': student_data['_id'],
                            'teacherId': teacher_id,
                            'title': title,
                            'linkOrFileRef': link_or_file,
                            'dueDate': due_date.isoformat() if due_date else None,
                            'status': 'assigned',
                            'notes': notes
                        }
                        dm.add_assignment(assignment_data)
                        st.success("Assignment created successfully!")
                        st.rerun()
                    else:
                        st.error("Please fill in all required fields marked with *")

# Notes Page
elif page == "Notes":
    st.header("Notes Management")
    
    tab1, tab2 = st.tabs(["View Notes", "Add Note"])
    
    with tab1:
        notes = dm.get_all_notes_with_students()
        if notes:
            for note in notes:
                student = note['student']
                with st.expander(f"Note for {student['firstName']} {student['lastName']} - {note.get('createdAt', 'Unknown date')}"):
                    st.write(f"**Author:** {note.get('authorId', 'Unknown')}")
                    st.write(f"**Note:**")
                    st.write(note['text'])
        else:
            st.info("No notes found.")
    
    with tab2:
        students = dm.get_all_students()
        if not students:
            st.warning("No students available. Please add students first.")
        else:
            with st.form("add_note_form"):
                st.subheader("Add New Note")
                
                student_options = [f"{s['firstName']} {s['lastName']}" for s in students]
                selected_student = st.selectbox("Select Student*", student_options)
                
                author_id = st.text_input("Author ID*", value="Staff")
                text = st.text_area("Note Text*")
                
                if st.form_submit_button("Add Note"):
                    if selected_student and author_id and text:
                        student_data = next(s for s in students if f"{s['firstName']} {s['lastName']}" == selected_student)
                        
                        note_data = {
                            'studentId': student_data['_id'],
                            'authorId': author_id,
                            'text': text,
                            'shareWithParent': False,
                            'createdAt': datetime.now().isoformat()
                        }
                        dm.add_note(note_data)
                        st.success("Note added successfully!")
                        st.rerun()
                    else:
                        st.error("Please fill in all required fields marked with *")

# Reports & Analytics Page
elif page == "Reports & Analytics":
    st.header("📊 Reports & Analytics")
    
    # Get all analytics data
    placement_stats = analytics.get_placement_statistics()
    student_stats = analytics.get_student_statistics()
    behavior_patterns = analytics.get_behavior_patterns()
    assignment_stats = analytics.get_assignment_statistics()
    daily_log_compliance = analytics.get_daily_log_compliance()
    
    # Overview metrics
    st.subheader("Overview Metrics")
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric("Total Students", student_stats['active_students'])
        st.metric("Total Placements", placement_stats['total_placements'])
    
    with col2:
        st.metric("Active Placements", placement_stats['active_placements'])
        st.metric("Completed Placements", placement_stats['completed_placements'])
    
    with col3:
        st.metric("Completion Rate", f"{placement_stats['completion_rate']}%")
        st.metric("Avg Days Assigned", placement_stats['average_days_assigned'])
    
    with col4:
        st.metric("Assignment Completion", f"{assignment_stats['completion_rate']}%")
        st.metric("Daily Log Compliance", f"{daily_log_compliance['compliance_rate']}%")
    
    st.divider()
    
    # Student Performance Summary
    st.subheader("Student Performance Summary")
    performance_data = analytics.get_student_performance_summary()
    
    if performance_data:
        df_performance = pd.DataFrame(performance_data)
        st.dataframe(
            df_performance[[
                'student_name', 'grade', 'homeroom_teacher', 
                'cumulative_points', 'avg_daily_points', 
                'positive_events', 'negative_events', 'total_events'
            ]],
            use_container_width=True
        )
    else:
        st.info("No active placements to display.")
    
    st.divider()
    
    # Behavior Patterns
    st.subheader("Behavior Pattern Analysis")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.write("**Top Positive Behaviors**")
        if behavior_patterns['top_positive_behaviors']:
            for code, count in behavior_patterns['top_positive_behaviors']:
                point_item = ps.get_point_item_by_code(code)
                st.write(f"• {point_item['label']}: {count} occurrences")
        else:
            st.info("No positive behaviors recorded yet.")
        
        st.metric("Total Positive Events", behavior_patterns['total_positive_events'])
    
    with col2:
        st.write("**Top Negative Behaviors**")
        if behavior_patterns['top_negative_behaviors']:
            for code, count in behavior_patterns['top_negative_behaviors']:
                point_item = ps.get_point_item_by_code(code)
                st.write(f"• {point_item['label']}: {count} occurrences")
        else:
            st.info("No negative behaviors recorded yet.")
        
        st.metric("Total Negative Events", behavior_patterns['total_negative_events'])
    
    st.divider()
    
    # Point Trends
    st.subheader("Point Trends (Last 30 Days)")
    point_trends = analytics.get_point_trends(days=30)
    
    if point_trends['daily_totals']:
        # Create DataFrame for visualization
        dates = sorted(point_trends['daily_totals'].keys())
        daily_data = {
            'Date': dates,
            'Total Points': [point_trends['daily_totals'][d] for d in dates],
            'Positive Points': [point_trends['positive_by_day'].get(d, 0) for d in dates],
            'Negative Points': [point_trends['negative_by_day'].get(d, 0) for d in dates]
        }
        df_trends = pd.DataFrame(daily_data)
        
        st.line_chart(df_trends.set_index('Date'))
        
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Total Point Events", point_trends['total_events'])
        with col2:
            total_positive = sum(point_trends['positive_by_day'].values())
            st.metric("Total Positive Points", total_positive)
        with col3:
            total_negative = sum(point_trends['negative_by_day'].values())
            st.metric("Total Negative Points", total_negative)
    else:
        st.info("No point event data available for the selected period.")
    
    st.divider()
    
    # Assignment Statistics
    st.subheader("Assignment Statistics")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.metric("Total Assignments", assignment_stats['total_assignments'])
        st.metric("Assigned", assignment_stats['assigned'])
    
    with col2:
        st.metric("In Progress", assignment_stats['in_progress'])
        st.metric("Completed", assignment_stats['completed'])
    
    with col3:
        st.metric("Completion Rate", f"{assignment_stats['completion_rate']}%")
        st.metric("Overdue", assignment_stats['overdue'], 
                 delta=f"-{assignment_stats['overdue']}" if assignment_stats['overdue'] > 0 else "0",
                 delta_color="inverse")
    
    st.divider()
    
    # Daily Log Compliance
    st.subheader("Daily Log Finalization")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.metric("Total Logs (30 days)", daily_log_compliance['total_logs'])
        st.metric("Finalized", daily_log_compliance['finalized'])
    
    with col2:
        st.metric("Pending", daily_log_compliance['pending'],
                 delta=f"-{daily_log_compliance['pending']}" if daily_log_compliance['pending'] > 0 else "0",
                 delta_color="inverse")
        st.metric("Compliance Rate", f"{daily_log_compliance['compliance_rate']}%")
    
    with col3:
        st.write("**Readiness Status**")
        readiness = daily_log_compliance['readiness_counts']
        st.write(f"• Ready: {readiness.get('ready', 0)}")
        st.write(f"• Continue: {readiness.get('continue', 0)}")
    
    st.divider()
    
    # Grade Distribution
    st.subheader("Student Grade Distribution")
    
    if student_stats['grade_distribution']:
        grade_df = pd.DataFrame([
            {'Grade': grade, 'Count': count} 
            for grade, count in sorted(student_stats['grade_distribution'].items())
        ])
        st.bar_chart(grade_df.set_index('Grade'))
    else:
        st.info("No student grade data available.")

# Import/Export Page
elif page == "Import/Export":
    st.header("📥📤 Import/Export Data")
    
    st.write("Bulk import and export data for students, placements, point events, assignments, notes, and daily logs.")
    
    tab1, tab2 = st.tabs(["Export Data", "Import Data"])
    
    with tab1:
        st.subheader("Export Data to CSV")
        st.write("Download your data in CSV format for backup or analysis.")
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.write("**Student Data**")
            if st.button("Export Students"):
                csv_data = import_export.export_students_csv()
                if csv_data:
                    st.download_button(
                        label="Download Students CSV",
                        data=csv_data,
                        file_name=f"students_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                        mime="text/csv"
                    )
                else:
                    st.info("No students to export.")
            
            st.write("**Placement Data**")
            if st.button("Export Placements"):
                csv_data = import_export.export_placements_csv()
                if csv_data:
                    st.download_button(
                        label="Download Placements CSV",
                        data=csv_data,
                        file_name=f"placements_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                        mime="text/csv"
                    )
                else:
                    st.info("No placements to export.")
            
            st.write("**Assignment Data**")
            if st.button("Export Assignments"):
                csv_data = import_export.export_assignments_csv()
                if csv_data:
                    st.download_button(
                        label="Download Assignments CSV",
                        data=csv_data,
                        file_name=f"assignments_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                        mime="text/csv"
                    )
                else:
                    st.info("No assignments to export.")
        
        with col2:
            st.write("**Point Event Data**")
            if st.button("Export Point Events"):
                csv_data = import_export.export_point_events_csv()
                if csv_data:
                    st.download_button(
                        label="Download Point Events CSV",
                        data=csv_data,
                        file_name=f"point_events_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                        mime="text/csv"
                    )
                else:
                    st.info("No point events to export.")
            
            st.write("**Notes Data**")
            if st.button("Export Notes"):
                csv_data = import_export.export_notes_csv()
                if csv_data:
                    st.download_button(
                        label="Download Notes CSV",
                        data=csv_data,
                        file_name=f"notes_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                        mime="text/csv"
                    )
                else:
                    st.info("No notes to export.")
            
            st.write("**Daily Log Data**")
            if st.button("Export Daily Logs"):
                csv_data = import_export.export_daily_logs_csv()
                if csv_data:
                    st.download_button(
                        label="Download Daily Logs CSV",
                        data=csv_data,
                        file_name=f"daily_logs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                        mime="text/csv"
                    )
                else:
                    st.info("No daily logs to export.")
    
    with tab2:
        st.subheader("Import Data from CSV")
        st.write("Upload CSV files to bulk import data.")
        
        # Student Import
        st.write("**Import Students**")
        st.write("Upload a CSV file with columns: firstName, lastName, grade, homeroomTeacher")
        
        # Download template
        template_csv = import_export.get_student_template_csv()
        st.download_button(
            label="Download Student Template CSV",
            data=template_csv,
            file_name="student_template.csv",
            mime="text/csv"
        )
        
        uploaded_file = st.file_uploader("Choose a CSV file to import students", type=['csv'], key='student_import')
        
        if uploaded_file is not None:
            try:
                csv_content = uploaded_file.getvalue().decode('utf-8')
                
                if st.button("Import Students from CSV"):
                    with st.spinner("Importing students..."):
                        results = import_export.import_students_csv(csv_content)
                    
                    if results['success_count'] > 0:
                        st.success(f"Successfully imported {results['success_count']} students!")
                    
                    if results['error_count'] > 0:
                        st.error(f"Failed to import {results['error_count']} students.")
                        with st.expander("View Errors"):
                            for error in results['errors']:
                                st.write(f"• {error}")
                    
                    if results['success_count'] > 0:
                        st.rerun()
            
            except Exception as e:
                st.error(f"Error reading file: {str(e)}")
        
        st.divider()
        
        st.info("""
        **Import Guidelines:**
        - Download the template CSV to see the required format
        - Ensure all required fields are filled
        - CSV files must be UTF-8 encoded
        - For best results, export existing data first to see the format
        """)

# Notifications Page
elif page == "Notifications":
    st.header("🔔 Notifications")
    
    st.write("Stay informed about placement events, daily summaries, and important updates.")
    
    # Get all notifications grouped by severity
    grouped_notifications = notifications.get_notifications_by_severity()
    
    # Summary metrics
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("⚠️ Warnings", len(grouped_notifications['warning']))
    with col2:
        st.metric("ℹ️ Info", len(grouped_notifications['info']))
    with col3:
        st.metric("✅ Success", len(grouped_notifications['success']))
    
    st.divider()
    
    # Display notifications by severity
    tab1, tab2, tab3, tab4 = st.tabs(["All", "Warnings", "Info", "Success"])
    
    with tab1:
        all_notifications = notifications.get_all_notifications()
        if all_notifications:
            for notif in all_notifications:
                severity_icon = {
                    'warning': '⚠️',
                    'info': 'ℹ️',
                    'success': '✅'
                }.get(notif['severity'], 'ℹ️')
                
                with st.container():
                    col_icon, col_content = st.columns([1, 11])
                    with col_icon:
                        st.write(severity_icon)
                    with col_content:
                        st.write(f"**{notif['title']}**")
                        st.write(notif['message'])
                        if notif.get('timestamp'):
                            st.caption(f"Time: {notif['timestamp'].strftime('%m/%d/%Y %I:%M %p')}")
                    st.divider()
        else:
            st.info("No notifications at this time.")
    
    with tab2:
        warning_notifs = grouped_notifications['warning']
        if warning_notifs:
            for notif in warning_notifs:
                with st.container():
                    st.warning(f"**{notif['title']}**\n\n{notif['message']}")
                    if notif.get('timestamp'):
                        st.caption(f"Time: {notif['timestamp'].strftime('%m/%d/%Y %I:%M %p')}")
                    st.divider()
        else:
            st.success("No warnings at this time.")
    
    with tab3:
        info_notifs = grouped_notifications['info']
        if info_notifs:
            for notif in info_notifs:
                with st.container():
                    st.info(f"**{notif['title']}**\n\n{notif['message']}")
                    if notif.get('timestamp'):
                        st.caption(f"Time: {notif['timestamp'].strftime('%m/%d/%Y %I:%M %p')}")
                    st.divider()
        else:
            st.info("No info notifications at this time.")
    
    with tab4:
        success_notifs = grouped_notifications['success']
        if success_notifs:
            for notif in success_notifs:
                with st.container():
                    st.success(f"**{notif['title']}**\n\n{notif['message']}")
                    if notif.get('timestamp'):
                        st.caption(f"Time: {notif['timestamp'].strftime('%m/%d/%Y %I:%M %p')}")
                    st.divider()
        else:
            st.info("No success notifications at this time.")


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
