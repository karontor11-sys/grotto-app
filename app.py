import streamlit as st
import pandas as pd
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

# Check and process end-of-day for pending dates (runs once per session)
if not st.session_state.eod_processing_checked:
    processing_results = dm.check_and_process_pending_dates()
    st.session_state.eod_processing_checked = True
    
    # Store results for potential display
    if processing_results:
        st.session_state.eod_processing_results = processing_results

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

# Check if we need to navigate to a specific page
if st.session_state.get('navigate_to_create_placement'):
    st.session_state.current_page = "Placements"
    st.session_state.page_selector = "Placements"  # Sync selectbox state
    del st.session_state.navigate_to_create_placement
elif st.session_state.get('navigate_to_dashboard'):
    st.session_state.current_page = "Dashboard"
    st.session_state.page_selector = "Dashboard"  # Sync selectbox state
    del st.session_state.navigate_to_dashboard
elif st.session_state.get('navigate_to_iss_detail'):
    st.session_state.current_page = "ISS Detail"
    # Don't sync page_selector - this is a hidden page
    del st.session_state.navigate_to_iss_detail
elif 'current_page' not in st.session_state:
    st.session_state.current_page = "Dashboard"

# Use current_page as the source of truth for the page selector
page = st.session_state.current_page

# Sidebar page selector (synchronized with current_page)
sidebar_page = st.sidebar.selectbox(
    "Select a page:",
    ["Dashboard", "Placements", "Assignments", "Notes", "Notifications", "Reports & Analytics", "Import/Export"],
    index=["Dashboard", "Placements", "Assignments", "Notes", "Notifications", "Reports & Analytics", "Import/Export"].index(st.session_state.current_page),
    key="page_selector"
)

# Update current_page when user manually selects a page from sidebar
if sidebar_page != st.session_state.current_page:
    st.session_state.current_page = sidebar_page
    page = sidebar_page

# Show notification badge in sidebar
all_notifs = notifications.get_all_notifications()
warning_count = len([n for n in all_notifs if n.get('severity') == 'warning'])
if warning_count > 0:
    st.sidebar.warning(f"⚠️ {warning_count} notifications require attention")

# Dashboard Page
if page == "Dashboard":
    # Create New Placement button at the very top
    if st.button("Create New Placement", type="primary"):
        st.session_state.navigate_to_create_placement = True
        st.rerun()
    
    st.header("Dashboard")
    
    # Show success message if placement was just created
    if st.session_state.get('placement_created'):
        st.success("✅ Placement created successfully! The new placement appears below.")
        del st.session_state.placement_created
    
    # Date Selector
    if 'dashboard_selected_date' not in st.session_state:
        st.session_state.dashboard_selected_date = date.today()
    
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
    placements_for_date = dm.get_active_placements_for_date(selected_date)
    
    # Date display
    st.subheader(f"{selected_date.strftime('%B %d, %Y')}")
    
    st.divider()
    
    # Group placements by type
    iss_placements = []
    lunch_detention_placements = []
    class_referral_placements = []
    cooldown_placements = []
    preplanned_placements = []
    
    for placement in placements_for_date:
        placement_type = placement.get('placementType', '').upper()
        
        if placement_type == 'ISS':
            iss_placements.append(placement)
        elif placement_type == 'LUNCH_DETENTION':
            lunch_detention_placements.append(placement)
        elif placement_type == 'CLASS_REFERRAL':
            class_referral_placements.append(placement)
        elif placement_type == 'COOL_DOWN':
            cooldown_placements.append(placement)
        elif placement_type == 'PRE_PLANNED_REFERRAL':
            preplanned_placements.append(placement)
    
    # Helper function to render ISS Full Day student card
    def render_iss_full_card(placement: dict, target_date: date):
        """Render ISS Full Day card with attendance, Day X of Y, points, and behaviors."""
        student = placement['student']
        placement_id = placement['_id']
        student_name = f"{student['firstName']} {student['lastName']}"
        date_str = target_date.isoformat()
        
        # Get or create daily log
        daily_log = dm.get_or_create_daily_log(placement_id, date_str)
        
        # Determine status color
        from utils import get_daily_status_color, calculate_school_day_number
        fulfillment = daily_log.get('dailyFulfillment') or ''
        status_color = get_daily_status_color(fulfillment, date_str)
        status_icon = {'green': '🟢', 'yellow': '🟡', 'red': '🔴'}.get(status_color, '⚪')
        
        # Calculate Day X of Y
        served_dates = placement.get('servedDates', [])
        total_days = placement.get('daysAssigned', 0)
        day_number = calculate_school_day_number(placement['startDate'], date_str)
        
        # Get point events
        point_events = dm.get_point_events_for_date(placement_id, date_str)
        positive_points = sum([e['value'] for e in point_events if e['type'] == 'positive'])
        negative_points = sum([e['value'] for e in point_events if e['type'] == 'negative'])
        total_points = positive_points + negative_points
        
        # Check if student is marked present for this date
        is_present = date_str in served_dates
        
        with st.container():
            # Header row: Name, Grade, Attendance
            col1, col2, col3 = st.columns([3, 1, 2])
            
            with col1:
                if st.button(f"{status_icon} {student_name}", key=f"name_{placement_id}_{date_str}", use_container_width=True):
                    # Navigate to ISS Detail page
                    st.session_state.navigate_to_iss_detail = True
                    st.session_state.iss_detail_placement_id = placement_id
                    st.session_state.iss_detail_date = target_date
                    st.rerun()
            
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
                    dm.update_iss_attendance(placement_id, date_str, attendance == "Present")
                    st.rerun()
            
            # Day X of Y
            if day_number > 0 and day_number <= total_days:
                st.caption(f"📅 Day {day_number} of {total_days}")
            
            # Points section with behaviors
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
                    st.caption("✓ Eligible for completion")
                else:
                    st.markdown(f"<h2>{total_points}</h2>", unsafe_allow_html=True)
                    st.caption(f"Need {10 - total_points} more points")
                
                # Complete button
                if daily_log.get('dailyFulfillment') != 'yes':
                    if st.button("✓ Complete", key=f"complete_{placement_id}_{date_str}", type="primary"):
                        dm.complete_placement_day(placement_id, date_str, "Admin")
                        st.rerun()
                else:
                    st.success("Completed")
            
            # Notes (collapsed)
            show_notes_key = f"show_notes_{placement_id}_{date_str}"
            if show_notes_key not in st.session_state:
                st.session_state[show_notes_key] = False
            
            if st.button("📝 Notes", key=f"toggle_notes_{placement_id}_{date_str}"):
                st.session_state[show_notes_key] = not st.session_state[show_notes_key]
                st.rerun()
            
            if st.session_state[show_notes_key]:
                new_notes = st.text_area(
                    "Notes:",
                    value=daily_log.get('notes', '') or '',
                    key=f"notes_{placement_id}_{date_str}",
                    height=100
                )
                if st.button("💾 Save Notes", key=f"save_notes_{placement_id}_{date_str}"):
                    dm.update_daily_log_notes(placement_id, date_str, new_notes)
                    st.success("Notes saved!")
                    st.rerun()
            
            st.divider()
    
    # Helper function to render ISS Partial Day student card
    def render_iss_partial_card(placement: dict, target_date: date):
        """Render ISS Partial Day card with periods, points, and behaviors."""
        student = placement['student']
        placement_id = placement['_id']
        student_name = f"{student['firstName']} {student['lastName']}"
        date_str = target_date.isoformat()
        
        daily_log = dm.get_or_create_daily_log(placement_id, date_str)
        from utils import get_daily_status_color
        fulfillment = daily_log.get('dailyFulfillment') or ''
        status_color = get_daily_status_color(fulfillment, date_str)
        status_icon = {'green': '🟢', 'yellow': '🟡', 'red': '🔴'}.get(status_color, '⚪')
        
        # Get periods
        start_period = placement.get('startPeriod', 'N/A')
        end_period = placement.get('endPeriod', 'N/A')
        if start_period == end_period:
            period_label = f"Period {start_period}"
        else:
            period_label = f"Periods {start_period}–{end_period}"
        
        # Get points
        point_events = dm.get_point_events_for_date(placement_id, date_str)
        total_points = sum([e['value'] for e in point_events])
        
        with st.container():
            col1, col2, col3 = st.columns([3, 1, 1])
            
            with col1:
                st.markdown(f"**{status_icon} {student_name}**")
            
            with col2:
                st.caption(f"Grade {student.get('grade', 'N/A')}")
            
            with col3:
                if daily_log.get('dailyFulfillment') != 'yes':
                    if st.button("✓ Complete", key=f"complete_{placement_id}_{date_str}", type="primary"):
                        dm.complete_placement_day(placement_id, date_str, "Admin")
                        st.rerun()
                else:
                    st.success("Completed")
            
            st.caption(f"📚 {period_label}")
            st.caption(f"Points: {total_points}")
            
            # Notes
            show_notes_key = f"show_notes_{placement_id}_{date_str}"
            if show_notes_key not in st.session_state:
                st.session_state[show_notes_key] = False
            
            if st.button("📝 Notes", key=f"toggle_notes_{placement_id}_{date_str}"):
                st.session_state[show_notes_key] = not st.session_state[show_notes_key]
                st.rerun()
            
            if st.session_state[show_notes_key]:
                new_notes = st.text_area(
                    "Notes:",
                    value=daily_log.get('notes', '') or '',
                    key=f"notes_{placement_id}_{date_str}",
                    height=100
                )
                if st.button("💾 Save Notes", key=f"save_notes_{placement_id}_{date_str}"):
                    dm.update_daily_log_notes(placement_id, date_str, new_notes)
                    st.success("Notes saved!")
                    st.rerun()
            
            st.divider()
    
    # Helper function to render Lunch Detention student card
    def render_lunch_detention_card(placement: dict, target_date: date):
        """Render Lunch Detention card with attendance and Day X of Y."""
        student = placement['student']
        placement_id = placement['_id']
        student_name = f"{student['firstName']} {student['lastName']}"
        date_str = target_date.isoformat()
        
        daily_log = dm.get_or_create_daily_log(placement_id, date_str)
        from utils import get_daily_status_color, calculate_school_day_number
        fulfillment = daily_log.get('dailyFulfillment') or ''
        status_color = get_daily_status_color(fulfillment, date_str)
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
            
            # Complete button
            if daily_log.get('dailyFulfillment') != 'yes':
                if st.button("✓ Complete", key=f"complete_{placement_id}_{date_str}", type="primary"):
                    dm.complete_placement_day(placement_id, date_str, "Admin")
                    st.rerun()
            else:
                st.success("Completed")
            
            # Notes
            show_notes_key = f"show_notes_{placement_id}_{date_str}"
            if show_notes_key not in st.session_state:
                st.session_state[show_notes_key] = False
            
            if st.button("📝 Notes", key=f"toggle_notes_{placement_id}_{date_str}"):
                st.session_state[show_notes_key] = not st.session_state[show_notes_key]
                st.rerun()
            
            if st.session_state[show_notes_key]:
                new_notes = st.text_area(
                    "Notes:",
                    value=daily_log.get('notes', '') or '',
                    key=f"notes_{placement_id}_{date_str}",
                    height=100
                )
                if st.button("💾 Save Notes", key=f"save_notes_{placement_id}_{date_str}"):
                    dm.update_daily_log_notes(placement_id, date_str, new_notes)
                    st.success("Notes saved!")
                    st.rerun()
            
            st.divider()
    
    # Helper function to render Class Period Referral student card
    def render_class_referral_card(placement: dict, target_date: date):
        """Render Class Period Referral card with periods only."""
        student = placement['student']
        placement_id = placement['_id']
        student_name = f"{student['firstName']} {student['lastName']}"
        date_str = target_date.isoformat()
        
        daily_log = dm.get_or_create_daily_log(placement_id, date_str)
        from utils import get_daily_status_color
        fulfillment = daily_log.get('dailyFulfillment') or ''
        status_color = get_daily_status_color(fulfillment, date_str)
        status_icon = {'green': '🟢', 'yellow': '🟡', 'red': '🔴'}.get(status_color, '⚪')
        
        # Get periods
        start_period = placement.get('startPeriod', 'N/A')
        end_period = placement.get('endPeriod', 'N/A')
        if start_period == end_period:
            period_label = f"Period {start_period}"
        else:
            period_label = f"Periods {start_period}–{end_period}"
        
        with st.container():
            col1, col2, col3 = st.columns([3, 1, 1])
            
            with col1:
                st.markdown(f"**{status_icon} {student_name}**")
            
            with col2:
                st.caption(f"Grade {student.get('grade', 'N/A')}")
            
            with col3:
                if daily_log.get('dailyFulfillment') != 'yes':
                    if st.button("✓ Complete", key=f"complete_{placement_id}_{date_str}", type="primary"):
                        dm.complete_placement_day(placement_id, date_str, "Admin")
                        st.rerun()
                else:
                    st.success("Completed")
            
            st.caption(f"📚 {period_label}")
            
            # Notes
            show_notes_key = f"show_notes_{placement_id}_{date_str}"
            if show_notes_key not in st.session_state:
                st.session_state[show_notes_key] = False
            
            if st.button("📝 Notes", key=f"toggle_notes_{placement_id}_{date_str}"):
                st.session_state[show_notes_key] = not st.session_state[show_notes_key]
                st.rerun()
            
            if st.session_state[show_notes_key]:
                new_notes = st.text_area(
                    "Notes:",
                    value=daily_log.get('notes', '') or '',
                    key=f"notes_{placement_id}_{date_str}",
                    height=100
                )
                if st.button("💾 Save Notes", key=f"save_notes_{placement_id}_{date_str}"):
                    dm.update_daily_log_notes(placement_id, date_str, new_notes)
                    st.success("Notes saved!")
                    st.rerun()
            
            st.divider()
    
    # Helper function to render Cool-Down Referral student card
    def render_cooldown_card(placement: dict, target_date: date):
        """Render Cool-Down Referral card with periods only."""
        student = placement['student']
        placement_id = placement['_id']
        student_name = f"{student['firstName']} {student['lastName']}"
        date_str = target_date.isoformat()
        
        daily_log = dm.get_or_create_daily_log(placement_id, date_str)
        from utils import get_daily_status_color
        fulfillment = daily_log.get('dailyFulfillment') or ''
        status_color = get_daily_status_color(fulfillment, date_str)
        status_icon = {'green': '🟢', 'yellow': '🟡', 'red': '🔴'}.get(status_color, '⚪')
        
        # Get periods
        start_period = placement.get('startPeriod', 'N/A')
        end_period = placement.get('endPeriod', 'N/A')
        if start_period == end_period:
            period_label = f"Period {start_period}"
        else:
            period_label = f"Periods {start_period}–{end_period}"
        
        with st.container():
            col1, col2, col3 = st.columns([3, 1, 1])
            
            with col1:
                st.markdown(f"**{status_icon} {student_name}**")
            
            with col2:
                st.caption(f"Grade {student.get('grade', 'N/A')}")
            
            with col3:
                if daily_log.get('dailyFulfillment') != 'yes':
                    if st.button("✓ Complete", key=f"complete_{placement_id}_{date_str}", type="primary"):
                        dm.complete_placement_day(placement_id, date_str, "Admin")
                        st.rerun()
                else:
                    st.success("Completed")
            
            st.caption(f"🧘 {period_label}")
            
            # Notes
            show_notes_key = f"show_notes_{placement_id}_{date_str}"
            if show_notes_key not in st.session_state:
                st.session_state[show_notes_key] = False
            
            if st.button("📝 Notes", key=f"toggle_notes_{placement_id}_{date_str}"):
                st.session_state[show_notes_key] = not st.session_state[show_notes_key]
                st.rerun()
            
            if st.session_state[show_notes_key]:
                new_notes = st.text_area(
                    "Notes:",
                    value=daily_log.get('notes', '') or '',
                    key=f"notes_{placement_id}_{date_str}",
                    height=100
                )
                if st.button("💾 Save Notes", key=f"save_notes_{placement_id}_{date_str}"):
                    dm.update_daily_log_notes(placement_id, date_str, new_notes)
                    st.success("Notes saved!")
                    st.rerun()
            
            st.divider()
    
    # Helper function to render Pre-Planned Referral student card
    def render_preplanned_card(placement: dict, target_date: date):
        """Render Pre-Planned Referral card (simplified for now)."""
        student = placement['student']
        placement_id = placement['_id']
        student_name = f"{student['firstName']} {student['lastName']}"
        date_str = target_date.isoformat()
        
        daily_log = dm.get_or_create_daily_log(placement_id, date_str)
        from utils import get_daily_status_color
        fulfillment = daily_log.get('dailyFulfillment') or ''
        status_color = get_daily_status_color(fulfillment, date_str)
        status_icon = {'green': '🟢', 'yellow': '🟡', 'red': '🔴'}.get(status_color, '⚪')
        
        with st.container():
            col1, col2, col3 = st.columns([3, 1, 1])
            
            with col1:
                st.markdown(f"**{status_icon} {student_name}**")
            
            with col2:
                st.caption(f"Grade {student.get('grade', 'N/A')}")
            
            with col3:
                if daily_log.get('dailyFulfillment') != 'yes':
                    if st.button("✓ Complete", key=f"complete_{placement_id}_{date_str}", type="primary"):
                        dm.complete_placement_day(placement_id, date_str, "Admin")
                        st.rerun()
                else:
                    st.success("Completed")
            
            # Notes
            show_notes_key = f"show_notes_{placement_id}_{date_str}"
            if show_notes_key not in st.session_state:
                st.session_state[show_notes_key] = False
            
            if st.button("📝 Notes", key=f"toggle_notes_{placement_id}_{date_str}"):
                st.session_state[show_notes_key] = not st.session_state[show_notes_key]
                st.rerun()
            
            if st.session_state[show_notes_key]:
                new_notes = st.text_area(
                    "Notes:",
                    value=daily_log.get('notes', '') or '',
                    key=f"notes_{placement_id}_{date_str}",
                    height=100
                )
                if st.button("💾 Save Notes", key=f"save_notes_{placement_id}_{date_str}"):
                    dm.update_daily_log_notes(placement_id, date_str, new_notes)
                    st.success("Notes saved!")
                    st.rerun()
            
            st.divider()
    
    # Helper function to render enhanced ISS session card
    def render_iss_session_card(iss_session: dict, target_date: date):
        """Render enhanced ISS session card with full functionality."""
        session_id = iss_session['session_id']
        placement_id = iss_session['placement_id']
        student_id = iss_session['student_id']
        student_name = iss_session['student_name']
        date_str = iss_session['date']
        periods = iss_session.get('periods', list(range(1, 11)))
        is_full_day = len(periods) == 10 and periods == list(range(1, 11))
        is_past_session = target_date < date.today()
        
        daily_log = dm.get_or_create_daily_log(placement_id, date_str)
        point_events = dm.get_point_events_for_date(placement_id, date_str)
        positive_points = sum([e['value'] for e in point_events if e['type'] == 'positive'])
        negative_points = sum([e['value'] for e in point_events if e['type'] == 'negative'])
        total_points = positive_points + negative_points
        
        session_status = iss_session.get('status', 'scheduled')
        fulfillment = daily_log.get('dailyFulfillment') or ''
        override_used = daily_log.get('overrideUsed', False)
        is_completed = session_status == 'fulfilled' or fulfillment == 'yes' or override_used
        is_no_show = session_status == 'no_show'
        
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
        iss_total_days = placement_data.get('issTotalDays', 1) if placement_data else 1
        is_multi_day_iss = iss_total_days > 1
        
        progress = dm.calculate_iss_days_progress(placement_id, target_date)
        completed_days = progress['completed_days']
        total_days = progress['total_days']
        
        # Build the "Day X of Y Days" progress label
        completed_int = int(completed_days) if completed_days == int(completed_days) else int(completed_days)
        day_word = "Day" if total_days == 1 else "Days"
        day_progress_label = f"Day {completed_int} of {total_days} {day_word}"
        
        with st.container():
            header_col1, header_col2, header_col3 = st.columns([3, 2, 1])
            
            with header_col1:
                # Day progress label and student info
                st.markdown(f"**{day_progress_label}**")
                st.caption(f"Grade {iss_session.get('grade', 'N/A')} · {iss_session.get('homeroom_teacher', 'N/A')}")
            
            with header_col2:
                pass
            
            with header_col3:
                attendance_key = f"iss_attendance_{session_id}"
                current_attendance = "Present" if is_present else "Absent"
                new_attendance = st.radio(
                    "Attendance",
                    ["Present", "Absent"],
                    index=0 if current_attendance == "Present" else 1,
                    horizontal=True,
                    key=attendance_key,
                    label_visibility="collapsed",
                    disabled=is_completed
                )
                if new_attendance != current_attendance and not is_completed:
                    dm.update_iss_attendance(placement_id, date_str, new_attendance == "Present")
                    st.rerun()
            
            if not is_completed:
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
                    if is_full_day:
                        if total_points >= 10:
                            st.markdown(f"<h2 style='color: green; margin: 0;'>{total_points}</h2>", unsafe_allow_html=True)
                            st.caption("✓ Eligible for completion")
                        else:
                            st.markdown(f"<h2 style='margin: 0;'>{total_points}</h2>", unsafe_allow_html=True)
                            st.caption(f"Need {10 - total_points} more points")
                    else:
                        st.markdown(f"<h2 style='margin: 0;'>{total_points}</h2>", unsafe_allow_html=True)
                        st.caption("Custom session")
                
                action_col1, action_col2 = st.columns(2)
                
                with action_col1:
                    can_complete = (not is_full_day) or (is_full_day and total_points >= 10)
                    complete_help = "" if can_complete else "Full day requires 10+ points"
                    complete_label = "✓ Complete (Retroactive)" if is_past_session else "✓ Complete"
                    if st.button(complete_label, key=f"iss_complete_{session_id}", type="primary", 
                                 use_container_width=True, disabled=not can_complete, help=complete_help):
                        dm.mark_session_completed(session_id, "Admin")
                        if not is_present:
                            dm.update_iss_attendance(placement_id, date_str, True)
                        success_msg = "Session completed retroactively!" if is_past_session else "Session completed!"
                        st.success(success_msg)
                        st.rerun()
                
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
                        dm.mark_session_completed(session_id, "Admin", is_override=True, override_comment=override_note)
                        if not is_present:
                            dm.update_iss_attendance(placement_id, date_str, True)
                        st.success("✅ Override applied retroactively!" if is_past_session else "✅ Override applied!")
                        st.session_state[f"iss_override_expand_{session_id}"] = False
                        st.rerun()
            elif is_no_show:
                st.error("⚠️ Not Completed")
                st.markdown(f"**Points Total: {total_points}**")
                st.caption("Session was not completed by end of day")
                
                retro_col1, retro_col2 = st.columns(2)
                with retro_col1:
                    if st.button("✓ Mark Complete (Retroactive)", key=f"iss_retro_complete_{session_id}"):
                        dm.mark_session_completed(session_id, "Admin")
                        st.success("Session marked complete!")
                        st.rerun()
                with retro_col2:
                    if st.button("🔓 Apply Override", key=f"iss_retro_override_{session_id}"):
                        override_note = "Retroactive override: session marked complete after end-of-day processing."
                        dm.mark_session_completed(session_id, "Admin", is_override=True, override_comment=override_note)
                        st.success("Override applied!")
                        st.rerun()
            else:
                st.success("✓ Session Completed" + (" (Override)" if override_used else ""))
                st.markdown(f"**Points Total: {total_points}**")
            
            notes_key = f"iss_notes_expand_{session_id}"
            if notes_key not in st.session_state:
                st.session_state[notes_key] = False
            
            if st.button("📝 Notes", key=f"iss_notes_btn_{session_id}"):
                st.session_state[notes_key] = not st.session_state[notes_key]
                st.rerun()
            
            if st.session_state.get(notes_key, False):
                current_notes = daily_log.get('notes', '') or ''
                new_notes = st.text_area(
                    "Session Notes:",
                    value=current_notes,
                    key=f"iss_notes_text_{session_id}",
                    height=100
                )
                if st.button("💾 Save Notes", key=f"iss_notes_save_{session_id}"):
                    dm.update_daily_log_notes(placement_id, date_str, new_notes)
                    st.success("Notes saved!")
                    st.rerun()
            
            st.divider()
    
    # Five Placement Type Sections with Clickable Student Names
    # 1. In-School Suspension (ISS) - Session-based
    iss_sessions = dm.get_iss_sessions_for_date(selected_date)
    st.markdown("#### In-School Suspension (ISS)")
    if len(iss_sessions) == 0:
        st.caption("No students")
    else:
        for iss_session in iss_sessions:
            session_id = iss_session['session_id']
            student_name = iss_session['student_name']
            expand_key = f"expand_iss_{session_id}"
            if expand_key not in st.session_state:
                st.session_state[expand_key] = False
            
            if st.button(f"{'▼' if st.session_state[expand_key] else '▶'} {student_name}", key=f"toggle_iss_{session_id}", use_container_width=True):
                st.session_state[expand_key] = not st.session_state[expand_key]
                st.rerun()
            
            if st.session_state[expand_key]:
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
            expand_key = f"expand_lunch_{placement_id}"
            if expand_key not in st.session_state:
                st.session_state[expand_key] = False
            
            if st.button(f"{'▼' if st.session_state[expand_key] else '▶'} {student_name}", key=f"toggle_lunch_{placement_id}", use_container_width=True):
                st.session_state[expand_key] = not st.session_state[expand_key]
                st.rerun()
            
            if st.session_state[expand_key]:
                render_lunch_detention_card(placement, selected_date)
    
    st.divider()
    
    # 3. Class Period Referral
    st.markdown("#### Class Period Referral")
    if len(class_referral_placements) == 0:
        st.caption("No students")
    else:
        for placement in class_referral_placements:
            placement_id = placement['_id']
            student = placement['student']
            student_name = f"{student['firstName']} {student['lastName']}"
            expand_key = f"expand_class_{placement_id}"
            if expand_key not in st.session_state:
                st.session_state[expand_key] = False
            
            if st.button(f"{'▼' if st.session_state[expand_key] else '▶'} {student_name}", key=f"toggle_class_{placement_id}", use_container_width=True):
                st.session_state[expand_key] = not st.session_state[expand_key]
                st.rerun()
            
            if st.session_state[expand_key]:
                render_class_referral_card(placement, selected_date)
    
    st.divider()
    
    # 4. Cool-Down Referral
    st.markdown("#### Cool-Down Referral")
    if len(cooldown_placements) == 0:
        st.caption("No students")
    else:
        for placement in cooldown_placements:
            placement_id = placement['_id']
            student = placement['student']
            student_name = f"{student['firstName']} {student['lastName']}"
            expand_key = f"expand_cooldown_{placement_id}"
            if expand_key not in st.session_state:
                st.session_state[expand_key] = False
            
            if st.button(f"{'▼' if st.session_state[expand_key] else '▶'} {student_name}", key=f"toggle_cooldown_{placement_id}", use_container_width=True):
                st.session_state[expand_key] = not st.session_state[expand_key]
                st.rerun()
            
            if st.session_state[expand_key]:
                render_cooldown_card(placement, selected_date)
    
    st.divider()
    
    # 5. Pre-Planned Referral
    st.markdown("#### Pre-Planned Referral")
    if len(preplanned_placements) == 0:
        st.caption("No students")
    else:
        for placement in preplanned_placements:
            placement_id = placement['_id']
            student = placement['student']
            student_name = f"{student['firstName']} {student['lastName']}"
            expand_key = f"expand_preplanned_{placement_id}"
            if expand_key not in st.session_state:
                st.session_state[expand_key] = False
            
            if st.button(f"{'▼' if st.session_state[expand_key] else '▶'} {student_name}", key=f"toggle_preplanned_{placement_id}", use_container_width=True):
                st.session_state[expand_key] = not st.session_state[expand_key]
                st.rerun()
            
            if st.session_state[expand_key]:
                render_preplanned_card(placement, selected_date)

# Placements Page
elif page == "Placements":
    st.header("Placement Manager")
    
    # Get counts for badges
    completed_placements = dm.get_completed_placements_with_students()
    completed_count = len(completed_placements)
    
    tab1, tab2 = st.tabs([
        "Create Placement", 
        f"Completed Placements ({completed_count})"
    ])
    
    # Tab 1: Create Placement
    with tab1:
        students = dm.get_all_students()
        
        st.subheader("Create New Placement")
        
        # Initialize session state for student info persistence
        if 'placement_category' not in st.session_state:
            st.session_state.placement_category = "In-School Suspension (ISS)"
        
        # Map display names to internal values
        placement_type_map = {
            "In-School Suspension (ISS)": "ISS",
            "Lunch Detention": "LUNCH_DETENTION",
            "Class Period Referral": "CLASS_REFERRAL",
            "Cool-Down Referral": "COOL_DOWN",
            "Pre-Planned Referral": "PRE_PLANNED_REFERRAL"
        }
        
        # ===== CARD 1: STUDENT INFORMATION =====
        with st.container():
            st.markdown("### Student Information")
            col1, col2 = st.columns(2)
            with col1:
                student_first_name = st.text_input("First Name*", key="student_first_name")
                student_grade = st.selectbox("Grade*", ["6", "7", "8"], key="student_grade")
            with col2:
                student_last_name = st.text_input("Last Name*", key="student_last_name")
                student_homeroom = st.text_input("Homeroom Teacher*", key="student_homeroom")
        
        st.divider()
        
        # ===== CARD 2: PLACEMENT DETAILS =====
        with st.container():
            st.markdown("### Placement Details")
            
            # Placement Type radio at top of Placement Details card
            placement_category = st.radio(
                "Placement Type*",
                options=[
                    "In-School Suspension (ISS)", 
                    "Lunch Detention", 
                    "Class Period Referral", 
                    "Cool-Down Referral",
                    "Pre-Planned Referral"
                ],
                horizontal=False,
                help="Select the type of placement",
                key="placement_category"
            )
            placement_type_value = placement_type_map[placement_category]
            
            st.divider()
            
            # Reason field (common to all placement types)
            placement_reason = st.text_area("Reason*", key="placement_reason")
            
            st.divider()
            
            # ===== TYPE-SPECIFIC SCHEDULING FIELDS =====
            
            # ISS - Simplified start date + number of days model
            if placement_category == "In-School Suspension (ISS)":
                with st.form("iss_form"):
                    st.markdown("#### Scheduling")
                    col1, col2 = st.columns(2)
                    with col1:
                        iss_start_date = st.date_input("Start Date*", value=date.today(), help="First day of ISS placement")
                    with col2:
                        iss_total_days = st.number_input("Number of ISS Days*", min_value=1, value=1, step=1, help="Total ISS days assigned")
                    
                    created_by = st.selectbox("Created By*", ["Matthew Christie", "Aaron Toronto", "Todd Foster", "Chad Adamson"])
                    
                    submit_clicked = st.form_submit_button("Create ISS Placement", type="primary", use_container_width=True)
                    
                    if submit_clicked:
                        first_name = student_first_name
                        last_name = student_last_name
                        grade = student_grade
                        homeroom_teacher = student_homeroom
                        reason = placement_reason
                        
                        print(f"[DEBUG] ISS Form submitted - First Name: {first_name}, Last Name: {last_name}")
                        if not first_name or not last_name or not homeroom_teacher or not reason or not created_by:
                            print(f"[DEBUG] Validation failed - Missing fields")
                            st.error("❌ Please fill in all required fields marked with *")
                        else:
                            print(f"[DEBUG] Validation passed, creating placement...")
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
                                
                                print(f"[DEBUG] Student created with ID: {student_id}")
                                placement_id = dm.add_placement(placement_data)
                                print(f"[DEBUG] Placement created with ID: {placement_id}")
                                dm.generate_iss_full_day_sessions(placement_id, iss_start_date, iss_total_days)
                                print(f"[DEBUG] Sessions generated, setting navigation flags")
                                
                                st.session_state.placement_created = True
                                st.session_state.navigate_to_dashboard = True
                                st.success(f"✅ ISS placement created for {first_name} {last_name}")
                                print(f"[DEBUG] About to rerun...")
                                st.rerun()
                            except Exception as e:
                                print(f"[DEBUG] Exception occurred: {str(e)}")
                                import traceback
                                print(f"[DEBUG] Traceback: {traceback.format_exc()}")
                                st.error(f"❌ Error creating placement: {str(e)}")
                                st.error(traceback.format_exc())
            
            # Lunch Detention - Multi-day placement with automatic scheduling
            elif placement_category == "Lunch Detention":
                with st.form("lunch_detention_form"):
                    st.markdown("#### Scheduling")
                    col1, col2 = st.columns(2)
                    with col1:
                        start_date = st.date_input("Start Date*", value=date.today())
                    with col2:
                        lunch_days = st.number_input("Number of Lunch Detention Days*", min_value=1, value=1, step=1, help="Number of lunch detention days")
                    
                    created_by = st.selectbox("Created By*", ["Matthew Christie", "Aaron Toronto", "Todd Foster", "Chad Adamson"])
                    
                    if st.form_submit_button("Create Lunch Detention", type="primary", use_container_width=True):
                        first_name = student_first_name
                        last_name = student_last_name
                        grade = student_grade
                        homeroom_teacher = student_homeroom
                        reason = placement_reason
                        
                        if not first_name or not last_name or not homeroom_teacher or not reason or not created_by:
                            st.error("❌ Please fill in all required fields marked with *")
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
                                
                                st.success(f"✅ Lunch Detention created for {first_name} {last_name} - {lunch_days} day(s) scheduled through {end_date.strftime('%b %d, %Y')}")
                                st.rerun()
                            except Exception as e:
                                st.error(f"❌ Error: {str(e)}")
                                import traceback
                                st.error(traceback.format_exc())
            
            # Class Period Referral - Single-day with period selection
            elif placement_category == "Class Period Referral":
                with st.form("class_referral_form"):
                    st.markdown("#### Scheduling")
                    col1, col2, col3 = st.columns(3)
                    with col1:
                        start_date = st.date_input("Date*", value=date.today())
                    with col2:
                        selected_start_period = st.selectbox("Start Period*", options=[1, 2, 3, 4, 5, 6, 7, 8, 9, 10], format_func=lambda x: f"P{x}")
                    with col3:
                        selected_end_period = st.selectbox("End Period*", options=[1, 2, 3, 4, 5, 6, 7, 8, 9, 10], format_func=lambda x: f"P{x}")
                    st.info("For a single period, select the same period for both Start and End.")
                    
                    created_by = st.selectbox("Created By*", ["Matthew Christie", "Aaron Toronto", "Todd Foster", "Chad Adamson"])
                    
                    if st.form_submit_button("Create Class Period Referral", type="primary", use_container_width=True):
                        first_name = student_first_name
                        last_name = student_last_name
                        grade = student_grade
                        homeroom_teacher = student_homeroom
                        reason = placement_reason
                        
                        if not first_name or not last_name or not homeroom_teacher or not reason or not created_by:
                            st.error("❌ Please fill in all required fields marked with *")
                        elif selected_end_period < selected_start_period:
                            st.error("❌ End period must be equal to or after start period")
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
                                    "completionRule": "all_sessions_fulfilled",
                                    "minSessionsRequired": None,
                                    "daysAssigned": 1,
                                    "startDate": start_date.isoformat(),
                                    "endDate": start_date.isoformat(),
                                    "startPeriod": selected_start_period,
                                    "endPeriod": selected_end_period,
                                    "status": "active",
                                    "createdBy": created_by,
                                    "createdAt": datetime.now().isoformat()
                                }
                                
                                placement_id = dm.add_placement(placement_data)
                                dm.generate_class_referral_session(placement_id, start_date, selected_start_period, selected_end_period)
                                
                                st.success(f"✅ Class Period Referral created for {first_name} {last_name}")
                                st.rerun()
                            except Exception as e:
                                st.error(f"❌ Error: {str(e)}")
                                import traceback
                                st.error(traceback.format_exc())

            # Cool-Down Referral - show cool-down form with date and period fields
            elif placement_category == "Cool-Down Referral":
                with st.form("create_cooldown_form"):
                    st.markdown("#### Scheduling")
                    col3, col4, col5 = st.columns(3)
                    with col3:
                        cooldown_date = st.date_input("Date*", value=date.today(), key="cd_date")
                    with col4:
                        start_period = st.selectbox("Start Period*", options=[1, 2, 3, 4, 5, 6, 7, 8, 9, 10], format_func=lambda x: f"P{x}", key="cd_start_period")
                    with col5:
                        end_period = st.selectbox("End Period*", options=[1, 2, 3, 4, 5, 6, 7, 8, 9, 10], format_func=lambda x: f"P{x}", key="cd_end_period")
                    st.info("For a short cool-down, select the same period for both Start and End. For a longer cool-down, select a later period for End.")
                    
                    created_by = st.selectbox("Created By*", ["Matthew Christie", "Aaron Toronto", "Todd Foster", "Chad Adamson"], key="cd_created_by")
                    
                    if st.form_submit_button("Create Cool-Down", type="primary", use_container_width=True):
                        first_name = student_first_name
                        last_name = student_last_name
                        grade = student_grade
                        homeroom_teacher = student_homeroom
                        reason = placement_reason
                        
                        validation_error = False
                        
                        if end_period < start_period:
                            st.error("❌ End period must be equal to or after start period")
                            validation_error = True
                        
                        if not first_name or not last_name or not homeroom_teacher or not reason or not created_by:
                            st.error("❌ Please fill in all required fields marked with *")
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
                                
                                days_assigned = 1
                                
                                placement_data = {
                                    "studentId": student_id,
                                    "homeroomTeacherId": homeroom_teacher,
                                    "reason": reason,
                                    "type": "partial",
                                    "placementType": "COOL_DOWN",
                                    "completionRule": "all_sessions_fulfilled",
                                    "minSessionsRequired": None,
                                    "daysAssigned": days_assigned,
                                    "startDate": cooldown_date.isoformat(),
                                    "endDate": cooldown_date.isoformat(),
                                    "startPeriod": start_period,
                                    "endPeriod": end_period,
                                    "status": "active",
                                    "createdBy": created_by,
                                    "createdAt": datetime.now().isoformat()
                                }
                                placement_id = dm.add_placement(placement_data)
                                
                                dm.generate_cooldown_session(placement_id, cooldown_date, start_period, end_period)
                                
                                st.session_state.placement_created = True
                                st.session_state.navigate_to_dashboard = True
                                st.success(f"✅ Cool-Down created for {first_name} {last_name}")
                                st.rerun()
                            except Exception as e:
                                st.error(f"❌ Error creating cool-down: {str(e)}")
                                import traceback
                                st.error(traceback.format_exc())
            
            # Pre-Planned Referral - schedule-based referral with multiple date+period combinations
            elif placement_category == "Pre-Planned Referral":
                st.info("📅 This placement type allows you to schedule a student for specific periods on specific dates (e.g., when they will have a substitute teacher)")
                
                if 'preplanned_schedule' not in st.session_state:
                    st.session_state.preplanned_schedule = [{"date": date.today(), "periods": [1]}]
                
                with st.form("preplanned_referral_form"):
                    st.markdown("#### Scheduling")
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
                    
                    add_row_button = st.form_submit_button("+ Add Day", use_container_width=False)
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
                    
                    created_by = st.selectbox("Created By*", ["Matthew Christie", "Aaron Toronto", "Todd Foster", "Chad Adamson"], key="pp_created_by")
                    
                    submit_button = st.form_submit_button("Create Pre-Planned Referral", type="primary", use_container_width=True)
                    
                    if add_row_button:
                        st.session_state.preplanned_schedule.append({"date": date.today(), "periods": [1]})
                        st.rerun()
                    
                    if submit_button:
                        first_name = student_first_name
                        last_name = student_last_name
                        grade = student_grade
                        homeroom_teacher = student_homeroom
                        reason = placement_reason
                        
                        validation_error = False
                        
                        if not first_name or not last_name or not homeroom_teacher or not reason or not created_by:
                            st.error("❌ Please fill in all required fields marked with *")
                            validation_error = True
                        
                        valid_schedule = [s for s in schedule_data if s.get("periods")]
                        if not valid_schedule:
                            st.error("❌ Please add at least one day with selected periods")
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
                                    "placementType": "PRE_PLANNED_REFERRAL",
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
                                
                                st.success(f"✅ Pre-Planned Referral created for {first_name} {last_name} - {len(scheduled_slots)} session(s) scheduled")
                                st.rerun()
                            except Exception as e:
                                st.error(f"❌ Error creating pre-planned referral: {str(e)}")
                                import traceback
                                st.error(traceback.format_exc())
                
                if len(st.session_state.preplanned_schedule) > 1:
                    if st.button("🗑️ Remove Last Day"):
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
                    
                    # Restore button
                    if st.button(f"Restore to Active", key=f"restore_{placement['_id']}"):
                        dm.restore_placement_to_active(placement['_id'])
                        st.success("✅ Placement restored to active!")
                        st.rerun()
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

# Footer branding - displayed on every page
st.divider()
st.caption("George S. Mickelson Middle School – Brookings, South Dakota")
