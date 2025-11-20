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

dm = st.session_state.data_manager
ps = st.session_state.point_system
analytics = st.session_state.analytics_engine
import_export = st.session_state.import_export_manager
notifications = st.session_state.notification_manager

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
    st.caption("George S. Mickelson Middle School - Brookings, South Dakota - In-School Suspension Placement Manager")

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
elif st.session_state.get('navigate_to_daily_logs'):
    st.session_state.current_page = "Daily Logs"
    st.session_state.page_selector = "Daily Logs"  # Sync selectbox state
    del st.session_state.navigate_to_daily_logs
elif 'current_page' not in st.session_state:
    st.session_state.current_page = "Dashboard"

# Use current_page as the source of truth for the page selector
page = st.session_state.current_page

# Sidebar page selector (synchronized with current_page)
sidebar_page = st.sidebar.selectbox(
    "Select a page:",
    ["Dashboard", "Placements", "Daily Logs", "Assignments", "Notes", "Notifications", "Reports & Analytics", "Import/Export"],
    index=["Dashboard", "Placements", "Daily Logs", "Assignments", "Notes", "Notifications", "Reports & Analytics", "Import/Export"].index(st.session_state.current_page),
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
    
    # Summary Bar - Placement counts for selected date
    st.markdown("### At-a-Glance Summary")
    
    # Get all active placements for selected date
    placements_for_date = dm.get_active_placements_for_date(selected_date)
    
    # Count placements by category
    iss_full_count = 0
    iss_partial_count = 0
    lunch_detention_count = 0
    class_referral_count = 0
    cooldown_count = 0
    preplanned_count = 0
    
    for placement in placements_for_date:
        placement_type = placement.get('placementType', '').upper()
        internal_type = placement.get('type', '')
        
        if placement_type == 'ISS':
            if internal_type == 'iss_full_day':
                iss_full_count += 1
            elif internal_type == 'partial':
                iss_partial_count += 1
        elif placement_type == 'LUNCH_DETENTION':
            lunch_detention_count += 1
        elif placement_type == 'CLASS_REFERRAL':
            class_referral_count += 1
        elif placement_type == 'COOL_DOWN':
            cooldown_count += 1
        elif placement_type == 'PRE_PLANNED_REFERRAL':
            preplanned_count += 1
    
    # Display summary in columns
    col1, col2, col3, col4, col5, col6 = st.columns(6)
    with col1:
        st.metric("ISS Full Day", iss_full_count)
    with col2:
        st.metric("ISS Partial Day", iss_partial_count)
    with col3:
        st.metric("Lunch Detention", lunch_detention_count)
    with col4:
        st.metric("Class Period Referral", class_referral_count)
    with col5:
        st.metric("Cool-Down Referral", cooldown_count)
    with col6:
        st.metric("Pre-Planned Referral", preplanned_count)
    
    st.divider()
    
    # Create New Placement button
    if st.button("Create New Placement", type="primary"):
        st.session_state.navigate_to_create_placement = True
        st.rerun()
    
    # Today's Sessions strip (using selected date)
    st.subheader(f"Sessions for {selected_date.strftime('%B %d, %Y')}")
    
    # Get sessions for selected date (need to query database)
    from db_manager import PartialDaySession, SessionStatus
    db_session = dm.get_session()
    try:
        sessions_query = db_session.query(PartialDaySession).filter(
            PartialDaySession.date == selected_date,
            PartialDaySession.status.in_([SessionStatus.scheduled, SessionStatus.in_progress])
        ).all()
        
        todays_sessions = []
        for sess in sessions_query:
            from db_manager import Placement, Student
            placement = db_session.query(Placement).filter(Placement.id == sess.placement_id).first()
            if placement:
                student = db_session.query(Student).filter(Student.id == placement.student_id).first()
                if student:
                    from db_manager import SessionType
                    # Format scope based on session type
                    scope = ""
                    if sess.type == SessionType.periods:
                        if sess.periods:
                            period_list = ", ".join([f"P{p}" for p in sess.periods])
                            scope = period_list
                    elif sess.type == SessionType.lunch:
                        scope = "Lunch"
                    elif sess.type == SessionType.cool_down:
                        if sess.time_start and sess.time_end:
                            scope = f"{sess.time_start}–{sess.time_end}"
                        else:
                            scope = "Cool-down"
                    elif sess.type == SessionType.referral:
                        if sess.periods and len(sess.periods) > 0:
                            scope = f"P{sess.periods[0]}"
                        else:
                            scope = "Referral"
                    elif sess.type == SessionType.iss_full_day:
                        scope = "Full Day"
                    
                    todays_sessions.append({
                        'session_id': sess.id,
                        'placement_id': sess.placement_id,
                        'student_name': f"{student.first_name} {student.last_name[0]}",
                        'student_full_name': f"{student.first_name} {student.last_name}",
                        'scope': scope,
                        'type': sess.type.value,
                        'location': sess.location or ''
                    })
    finally:
        db_session.close()
    
    if not todays_sessions:
        st.info(f"No sessions scheduled for {selected_date.strftime('%B %d, %Y')}.")
    else:
        # Display sessions as horizontal chips
        cols = st.columns(min(len(todays_sessions), 4))
        for idx, session in enumerate(todays_sessions):
            col_idx = idx % 4
            with cols[col_idx]:
                chip_label = f"{session['student_name']} · {session['scope']}"
                if st.button(chip_label, key=f"session_chip_{session['session_id']}", use_container_width=True):
                    # Navigate to Daily Logs for this specific session
                    st.session_state.selected_session_id = session['session_id']
                    st.session_state.navigate_to_daily_logs = True
                    st.rerun()
    
    st.divider()
    
    # Group placements by type
    iss_full_placements = []
    iss_partial_placements = []
    lunch_detention_placements = []
    class_referral_placements = []
    cooldown_placements = []
    preplanned_placements = []
    
    for placement in placements_for_date:
        placement_type = placement.get('placementType', '').upper()
        internal_type = placement.get('type', '')
        
        if placement_type == 'ISS':
            if internal_type == 'iss_full_day':
                iss_full_placements.append(placement)
            elif internal_type == 'partial':
                iss_partial_placements.append(placement)
        elif placement_type == 'LUNCH_DETENTION':
            lunch_detention_placements.append(placement)
        elif placement_type == 'CLASS_REFERRAL':
            class_referral_placements.append(placement)
        elif placement_type == 'COOL_DOWN':
            cooldown_placements.append(placement)
        elif placement_type == 'PRE_PLANNED_REFERRAL':
            preplanned_placements.append(placement)
    
    # Helper function to render universal student card
    def render_student_card(placement: dict, target_date: date):
        """Render a universal student card with status, notes, and completion button."""
        student = placement['student']
        placement_id = placement['_id']
        student_name = f"{student['firstName']} {student['lastName']}"
        date_str = target_date.isoformat()
        
        # Get or create daily log for this placement and date
        daily_log = dm.get_or_create_daily_log(placement_id, date_str)
        
        # Determine status color
        from utils import get_daily_status_color
        fulfillment = daily_log.get('dailyFulfillment') or ''
        status_color = get_daily_status_color(fulfillment, date_str)
        
        # Map colors to emojis
        status_icons = {
            'green': '🟢',
            'yellow': '🟡',
            'red': '🔴'
        }
        status_icon = status_icons.get(status_color, '⚪')
        
        with st.container():
            # Student name (clickable) with status indicator
            col1, col2, col3 = st.columns([3, 1, 1])
            
            with col1:
                # Clickable student name that navigates to Daily Logs
                if st.button(f"{status_icon} {student_name}", key=f"name_{placement_id}_{date_str}", use_container_width=True):
                    st.session_state.navigate_to_daily_logs = True
                    st.session_state.selected_log_date = target_date
                    st.rerun()
            
            with col2:
                st.caption(f"Grade {student.get('grade', 'N/A')}")
            
            with col3:
                # Complete button
                if daily_log.get('dailyFulfillment') != 'yes':
                    if st.button("✓ Complete", key=f"complete_{placement_id}_{date_str}", type="primary"):
                        dm.complete_placement_day(placement_id, date_str, "Admin")
                        st.rerun()
                else:
                    st.success("Completed")
            
            # Notes field (collapsed by default)
            notes_key = f"notes_{placement_id}_{date_str}"
            show_notes_key = f"show_notes_{placement_id}_{date_str}"
            
            if show_notes_key not in st.session_state:
                st.session_state[show_notes_key] = False
            
            if st.button("📝 Notes", key=f"toggle_notes_{placement_id}_{date_str}"):
                st.session_state[show_notes_key] = not st.session_state[show_notes_key]
                st.rerun()
            
            if st.session_state[show_notes_key]:
                current_notes = daily_log.get('notes', '')
                new_notes = st.text_area(
                    "Notes for this student on this date:",
                    value=current_notes or '',
                    key=notes_key,
                    height=100
                )
                
                if st.button("💾 Save Notes", key=f"save_notes_{placement_id}_{date_str}"):
                    dm.update_daily_log_notes(placement_id, date_str, new_notes)
                    st.success("Notes saved!")
                    st.rerun()
            
            st.divider()
    
    # Six Collapsible Sections
    # 1. ISS - Full Day
    with st.expander(f"ISS – Full Day ({len(iss_full_placements)})", expanded=len(iss_full_placements) > 0):
        if len(iss_full_placements) == 0:
            st.info("No students in ISS Full Day for this date.")
        else:
            for placement in iss_full_placements:
                render_student_card(placement, selected_date)
    
    # 2. ISS - Partial Day
    with st.expander(f"ISS – Partial Day ({len(iss_partial_placements)})", expanded=len(iss_partial_placements) > 0):
        if len(iss_partial_placements) == 0:
            st.info("No students in ISS Partial Day for this date.")
        else:
            for placement in iss_partial_placements:
                render_student_card(placement, selected_date)
    
    # 3. Lunch Detention
    with st.expander(f"Lunch Detention ({len(lunch_detention_placements)})", expanded=len(lunch_detention_placements) > 0):
        if len(lunch_detention_placements) == 0:
            st.info("No students in Lunch Detention for this date.")
        else:
            for placement in lunch_detention_placements:
                render_student_card(placement, selected_date)
    
    # 4. Class Period Referral
    with st.expander(f"Class Period Referral ({len(class_referral_placements)})", expanded=len(class_referral_placements) > 0):
        if len(class_referral_placements) == 0:
            st.info("No students in Class Period Referral for this date.")
        else:
            for placement in class_referral_placements:
                render_student_card(placement, selected_date)
    
    # 5. Cool-Down Referral
    with st.expander(f"Cool-Down Referral ({len(cooldown_placements)})", expanded=len(cooldown_placements) > 0):
        if len(cooldown_placements) == 0:
            st.info("No students in Cool-Down Referral for this date.")
        else:
            for placement in cooldown_placements:
                render_student_card(placement, selected_date)
    
    # 6. Pre-Planned Referral
    with st.expander(f"Pre-Planned Referral ({len(preplanned_placements)})", expanded=len(preplanned_placements) > 0):
        if len(preplanned_placements) == 0:
            st.info("No students in Pre-Planned Referral for this date.")
        else:
            for placement in preplanned_placements:
                render_student_card(placement, selected_date)

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
        
        # Single Placement Type selector (outside form for dynamic updates)
        # Initialize session state if not set
        if 'placement_category' not in st.session_state:
            st.session_state.placement_category = "In-School Suspension (Full)"
        
        placement_category = st.radio(
            "Placement Type*",
            options=[
                "In-School Suspension (Full)", 
                "In-School Suspension (Partial)", 
                "Lunch Detention", 
                "Class Period Referral", 
                "Cool-Down Referral",
                "Pre-Planned Referral"
            ],
            horizontal=False,
            help="Select the type of placement",
            key="placement_category"
        )
        
        # Map display names to internal values
        placement_type_map = {
            "In-School Suspension (Full)": "ISS",
            "In-School Suspension (Partial)": "ISS",
            "Lunch Detention": "LUNCH_DETENTION",
            "Class Period Referral": "CLASS_REFERRAL",
            "Cool-Down Referral": "COOL_DOWN",
            "Pre-Planned Referral": "PRE_PLANNED_REFERRAL"
        }
        placement_type_value = placement_type_map[placement_category]
        
        st.divider()
        
        # Create SEPARATE forms for each placement type
        # ISS (Full) - Multi-day ISS with ISS Days field
        if placement_category == "In-School Suspension (Full)":
            with st.form("iss_full_form"):
                st.markdown("## In-School – Full Days")
                st.markdown("### Student Information")
                col1, col2 = st.columns(2)
                with col1:
                    first_name = st.text_input("First Name*")
                    grade = st.selectbox("Grade*", ["6", "7", "8"])
                with col2:
                    last_name = st.text_input("Last Name*")
                    homeroom_teacher = st.text_input("Homeroom Teacher*")
                
                st.markdown("### Placement Details")
                reason = st.text_area("Reason*")
                
                st.markdown("### Scheduling")
                iss_days = st.number_input("ISS Days*", min_value=1, value=1, step=1, help="Number of full ISS days")
                start_date = st.date_input("Start Date*", value=date.today())
                
                created_by = st.selectbox("Created By*", ["Matthew Christie", "Aaron Toronto", "Todd Foster", "Chad Adamson"])
                
                if st.form_submit_button("Create ISS Full-Day Placement", type="primary", use_container_width=True):
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
                            
                            placement_data = {
                                "studentId": student_id,
                                "homeroomTeacherId": homeroom_teacher,
                                "reason": reason,
                                "type": "iss_full_day",
                                "placementType": "ISS",
                                "completionRule": "iss_days",
                                "minSessionsRequired": None,
                                "daysAssigned": iss_days,
                                "startDate": start_date.isoformat(),
                                "endDate": start_date.isoformat(),
                                "status": "active",
                                "createdBy": created_by,
                                "createdAt": datetime.now().isoformat()
                            }
                            
                            placement_id = dm.add_placement(placement_data)
                            dm.generate_iss_full_day_sessions(placement_id, start_date, iss_days)
                            
                            st.success(f"✅ ISS Full-Day placement created for {first_name} {last_name}")
                            st.rerun()
                        except Exception as e:
                            st.error(f"❌ Error: {str(e)}")
                            import traceback
                            st.error(traceback.format_exc())
        
        # ISS (Partial) - Single-day partial ISS with period selection
        elif placement_category == "In-School Suspension (Partial)":
            with st.form("iss_partial_form"):
                st.markdown("## In-School – Partial Day")
                st.markdown("### Student Information")
                col1, col2 = st.columns(2)
                with col1:
                    first_name = st.text_input("First Name*")
                    grade = st.selectbox("Grade*", ["6", "7", "8"])
                with col2:
                    last_name = st.text_input("Last Name*")
                    homeroom_teacher = st.text_input("Homeroom Teacher*")
                
                st.markdown("### Placement Details")
                reason = st.text_area("Reason*")
                
                st.markdown("### Scheduling")
                col1, col2 = st.columns(2)
                with col1:
                    selected_start_period = st.selectbox("Start Period*", options=[1, 2, 3, 4, 5, 6, 7, 8, 9, 10], format_func=lambda x: f"Period {x}")
                with col2:
                    selected_end_period = st.selectbox("End Period*", options=[1, 2, 3, 4, 5, 6, 7, 8, 9, 10], format_func=lambda x: f"Period {x}")
                st.info("For a single period, select the same period for both Start and End.")
                start_date = st.date_input("Date*", value=date.today())
                
                created_by = st.selectbox("Created By*", ["Matthew Christie", "Aaron Toronto", "Todd Foster", "Chad Adamson"])
                
                if st.form_submit_button("Create ISS Partial Placement", type="primary", use_container_width=True):
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
                                "placementType": "ISS",
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
                            dm.generate_partial_iss_session(placement_id, start_date, selected_start_period, selected_end_period)
                            
                            st.success(f"✅ ISS Partial placement created for {first_name} {last_name}")
                            st.rerun()
                        except Exception as e:
                            st.error(f"❌ Error: {str(e)}")
                            import traceback
                            st.error(traceback.format_exc())
        
        # Lunch Detention - Multi-day placement with automatic scheduling
        elif placement_category == "Lunch Detention":
            with st.form("lunch_detention_form"):
                st.markdown("## Lunch Detention")
                st.markdown("### Student Information")
                col1, col2 = st.columns(2)
                with col1:
                    first_name = st.text_input("First Name*")
                    grade = st.selectbox("Grade*", ["6", "7", "8"])
                with col2:
                    last_name = st.text_input("Last Name*")
                    homeroom_teacher = st.text_input("Homeroom Teacher*")
                
                st.markdown("### Placement Details")
                reason = st.text_area("Reason*")
                
                st.markdown("### Scheduling")
                lunch_days = st.number_input("Number of Lunch Detention Days*", min_value=1, value=1, step=1, help="Number of lunch detention days")
                start_date = st.date_input("Start Date*", value=date.today())
                
                created_by = st.selectbox("Created By*", ["Matthew Christie", "Aaron Toronto", "Todd Foster", "Chad Adamson"])
                
                if st.form_submit_button("Create Lunch Detention", type="primary", use_container_width=True):
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
                            
                            # Generate scheduled lunch dates (skip weekends, skip no-lunch days)
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
                st.markdown("## Class Period Referral")
                st.markdown("### Student Information")
                col1, col2 = st.columns(2)
                with col1:
                    first_name = st.text_input("First Name*")
                    grade = st.selectbox("Grade*", ["6", "7", "8"])
                with col2:
                    last_name = st.text_input("Last Name*")
                    homeroom_teacher = st.text_input("Homeroom Teacher*")
                
                st.markdown("### Placement Details")
                reason = st.text_area("Reason*")
                
                st.markdown("### Scheduling")
                col1, col2 = st.columns(2)
                with col1:
                    selected_start_period = st.selectbox("Start Period*", options=[1, 2, 3, 4, 5, 6, 7, 8, 9, 10], format_func=lambda x: f"Period {x}")
                with col2:
                    selected_end_period = st.selectbox("End Period*", options=[1, 2, 3, 4, 5, 6, 7, 8, 9, 10], format_func=lambda x: f"Period {x}")
                st.info("For a single period, select the same period for both Start and End.")
                start_date = st.date_input("Date*", value=date.today())
                
                created_by = st.selectbox("Created By*", ["Matthew Christie", "Aaron Toronto", "Todd Foster", "Chad Adamson"])
                
                if st.form_submit_button("Create Class Period Referral", type="primary", use_container_width=True):
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
                st.markdown("## Cool-Down Referral")
                st.markdown("### Student Information")
                col1, col2 = st.columns(2)
                with col1:
                    first_name = st.text_input("First Name*", key="cd_first_name")
                    grade = st.selectbox("Grade*", ["6", "7", "8"], key="cd_grade")
                with col2:
                    last_name = st.text_input("Last Name*", key="cd_last_name")
                    homeroom_teacher = st.text_input("Homeroom Teacher*", key="cd_homeroom")
                
                st.markdown("### Placement Details")
                reason = st.text_area("Reason*", key="cd_reason")
                
                st.markdown("### Scheduling")
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
                    # Validation
                    validation_error = False
                    
                    # Validate period range
                    if end_period < start_period:
                        st.error("❌ End period must be equal to or after start period")
                        validation_error = True
                    
                    # Validate required fields
                    if not first_name or not last_name or not homeroom_teacher or not reason or not created_by:
                        st.error("❌ Please fill in all required fields marked with *")
                        validation_error = True
                    
                    if not validation_error:
                        try:
                            # Create new student
                            new_student_data = {
                                "firstName": first_name,
                                "lastName": last_name,
                                "grade": grade,
                                "homeroomTeacher": homeroom_teacher,
                                "guardianContacts": [],
                                "status": "active"
                            }
                            student_id = dm.add_student(new_student_data)
                            
                            # Calculate days_assigned (always 1 for single-day cool-down)
                            days_assigned = 1
                            
                            # Create placement with new student
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
                            
                            # Generate cool-down session
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
            st.markdown("## Pre-Planned Referral")
            st.info("📅 This placement type allows you to schedule a student for specific periods on specific dates (e.g., when they will have a substitute teacher)")
            
            # Initialize session state for schedule rows
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
                
                st.markdown("### Placement Details")
                reason = st.text_area("Reason*", key="pp_reason")
                
                st.markdown("### Scheduling")
                st.caption("Add one or more date+period combinations for this referral")
                
                # Display schedule rows
                schedule_data = []
                
                # Display Day 1
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
                
                # Add Day button immediately after Day 1
                add_row_button = st.form_submit_button("+ Add Day", use_container_width=False)
                st.divider()
                
                # Display remaining schedule rows (Day 2, Day 3, etc.)
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
                
                # Form submit button
                submit_button = st.form_submit_button("Create Pre-Planned Referral", type="primary", use_container_width=True)
                
                if add_row_button:
                    # Add a new schedule row
                    st.session_state.preplanned_schedule.append({"date": date.today(), "periods": [1]})
                    st.rerun()
                
                if submit_button:
                    # Validation
                    validation_error = False
                    
                    if not first_name or not last_name or not homeroom_teacher or not reason or not created_by:
                        st.error("❌ Please fill in all required fields marked with *")
                        validation_error = True
                    
                    # Validate that at least one schedule entry exists with periods
                    valid_schedule = [s for s in schedule_data if s.get("periods")]
                    if not valid_schedule:
                        st.error("❌ Please add at least one day with selected periods")
                        validation_error = True
                    
                    if not validation_error:
                        try:
                            # Create new student
                            new_student_data = {
                                "firstName": first_name,
                                "lastName": last_name,
                                "grade": grade,
                                "homeroomTeacher": homeroom_teacher,
                                "guardianContacts": [],
                                "status": "active"
                            }
                            student_id = dm.add_student(new_student_data)
                            
                            # Process schedule data into scheduled_slots
                            scheduled_slots = []
                            for slot in valid_schedule:
                                for period in slot["periods"]:
                                    scheduled_slots.append({
                                        "date": slot["date"].isoformat(),
                                        "period": period
                                    })
                            
                            # Determine start and end dates from schedule
                            all_dates = [slot["date"] for slot in valid_schedule]
                            start_date = min(all_dates)
                            end_date = max(all_dates)
                            
                            # Create placement
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
                            
                            # Clear the schedule state for next use
                            st.session_state.preplanned_schedule = [{"date": date.today(), "periods": [1]}]
                            
                            st.success(f"✅ Pre-Planned Referral created for {first_name} {last_name} - {len(scheduled_slots)} session(s) scheduled")
                            st.rerun()
                        except Exception as e:
                            st.error(f"❌ Error creating pre-planned referral: {str(e)}")
                            import traceback
                            st.error(traceback.format_exc())
            
            # Remove row button (outside form)
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

# Daily Logs Page
elif page == "Daily Logs":
    st.header("Daily Log Manager")
    
    # ISS Attendance Section - Show for today's full-day ISS placements
    today = date.today()
    today_str = today.isoformat()
    
    # Get all active ISS full-day placements scheduled for today
    active_placements = dm.get_active_placements_with_students()
    todays_iss_placements = []
    
    for placement in active_placements:
        if placement.get('placementType') == 'ISS' and placement.get('type') == 'iss_full_day':
            scheduled_dates = placement.get('scheduledIssDates', [])
            served_dates = placement.get('servedDates', [])
            total_required = placement.get('daysAssigned', 0)
            
            # Check if today is in scheduled dates and placement not yet completed
            if today_str in scheduled_dates and len(served_dates) < total_required:
                todays_iss_placements.append(placement)
    
    if todays_iss_placements:
        st.subheader("📋 Today's ISS Attendance")
        st.info(f"**{format_date(today_str)}** - Mark attendance for students in full-day ISS")
        
        # Initialize attendance state if not exists
        if 'iss_attendance' not in st.session_state:
            st.session_state.iss_attendance = {}
        
        # Display each ISS placement with attendance controls
        for placement in todays_iss_placements:
            student = placement.get('student', {})
            student_name = f"{student.get('firstName', '')} {student.get('lastName', '')}"
            placement_id = placement.get('_id')
            
            # Calculate progress
            served_count = len(placement.get('servedDates', []))
            total_days = placement.get('daysAssigned', 0)
            
            with st.container():
                col1, col2, col3 = st.columns([3, 2, 2])
                
                with col1:
                    st.write(f"**{student_name}**")
                    st.caption(f"Grade {student.get('grade', 'N/A')} · {student.get('homeroomTeacher', 'N/A')}")
                
                with col2:
                    st.write(f"ISS – Full Day")
                    st.caption(f"Day {served_count + 1} of {total_days}")
                
                with col3:
                    # Default to Present
                    default_value = st.session_state.iss_attendance.get(placement_id, "Present")
                    attendance_status = st.radio(
                        "Attendance",
                        options=["Present", "Absent"],
                        index=0 if default_value == "Present" else 1,
                        key=f"attendance_{placement_id}",
                        horizontal=True
                    )
                    st.session_state.iss_attendance[placement_id] = attendance_status
                
                st.divider()
        
        # Save button for all attendance
        if st.button("💾 Save Today's ISS Attendance", type="primary", use_container_width=True):
            saved_count = 0
            for placement in todays_iss_placements:
                placement_id = placement.get('_id')
                attendance_status = st.session_state.iss_attendance.get(placement_id, "Present")
                is_present = attendance_status == "Present"
                
                if dm.update_iss_attendance(placement_id, today_str, is_present):
                    saved_count += 1
            
            if saved_count > 0:
                st.success(f"✅ Saved attendance for {saved_count} student(s)!")
                # Clear attendance state after saving
                st.session_state.iss_attendance = {}
                st.rerun()
            else:
                st.error("❌ Failed to save attendance")
        
        st.divider()
    
    # Lunch Detention Attendance Section - Show for today's lunch detention placements
    todays_lunch_placements = []
    
    for placement in active_placements:
        if placement.get('placementType') == 'LUNCH_DETENTION' and placement.get('type') == 'iss_full_day':
            scheduled_lunch_dates = placement.get('scheduledLunchDates', [])
            served_dates = placement.get('servedDates', [])
            total_required = placement.get('daysAssigned', 0)
            
            # Check if today is in scheduled lunch dates and placement not yet completed
            if today_str in scheduled_lunch_dates and len(served_dates) < total_required:
                todays_lunch_placements.append(placement)
    
    if todays_lunch_placements:
        st.subheader("🍽️ Today's Lunch Detention Attendance")
        st.info(f"**{format_date(today_str)}** - Mark attendance for students in lunch detention")
        
        # Initialize lunch attendance state if not exists
        if 'lunch_attendance' not in st.session_state:
            st.session_state.lunch_attendance = {}
        
        # Display each Lunch Detention placement with attendance controls
        for placement in todays_lunch_placements:
            student = placement.get('student', {})
            student_name = f"{student.get('firstName', '')} {student.get('lastName', '')}"
            placement_id = placement.get('_id')
            
            # Calculate progress
            served_count = len(placement.get('servedDates', []))
            total_days = placement.get('daysAssigned', 0)
            
            with st.container():
                col1, col2, col3 = st.columns([3, 2, 2])
                
                with col1:
                    st.write(f"**{student_name}**")
                    st.caption(f"Grade {student.get('grade', 'N/A')} · {student.get('homeroomTeacher', 'N/A')}")
                
                with col2:
                    st.write(f"Lunch Detention")
                    st.caption(f"Day {served_count + 1} of {total_days}")
                
                with col3:
                    # Default to Present
                    default_value = st.session_state.lunch_attendance.get(placement_id, "Present")
                    attendance_status = st.radio(
                        "Attendance",
                        options=["Present", "Absent"],
                        index=0 if default_value == "Present" else 1,
                        key=f"lunch_attendance_{placement_id}",
                        horizontal=True
                    )
                    st.session_state.lunch_attendance[placement_id] = attendance_status
                
                st.divider()
        
        # Save button for all lunch detention attendance
        if st.button("💾 Save Today's Lunch Detention Attendance", type="primary", use_container_width=True):
            saved_count = 0
            for placement in todays_lunch_placements:
                placement_id = placement.get('_id')
                attendance_status = st.session_state.lunch_attendance.get(placement_id, "Present")
                is_present = attendance_status == "Present"
                
                if dm.update_lunch_detention_attendance(placement_id, today_str, is_present):
                    saved_count += 1
            
            if saved_count > 0:
                st.success(f"✅ Saved lunch detention attendance for {saved_count} student(s)!")
                # Clear attendance state after saving
                st.session_state.lunch_attendance = {}
                st.rerun()
            else:
                st.error("❌ Failed to save lunch detention attendance")
        
        st.divider()
    
    # Check if we navigated from a session chip (session-scoped view)
    # Use persistent session ID that survives reruns
    if 'selected_session_id' in st.session_state:
        # Transfer to persistent key
        st.session_state.current_session_view_id = st.session_state.selected_session_id
        del st.session_state.selected_session_id
    
    current_session_id = st.session_state.get('current_session_view_id')
    session_context = None
    
    if current_session_id:
        # Load session details for session-scoped view
        session_context = dm.get_session_details(current_session_id)
        if session_context:
            # Session-scoped header with back button
            header_col1, header_col2 = st.columns([5, 1])
            with header_col1:
                st.subheader(f"{session_context['student_name']} · {session_context['type_label']}")
            with header_col2:
                if st.button("← Back", key="exit_session_view"):
                    # Clear the session view state
                    if 'current_session_view_id' in st.session_state:
                        del st.session_state.current_session_view_id
                    st.rerun()
            
            # Show alert if no-show
            if session_context.get('alert_flag'):
                st.error("⚠️ SUPERVISOR ALERT: Student marked as no-show")
            
            # Get placement details for "Day X of Y" calculation
            placement_details = dm.get_placement(session_context['placement_id'])
            show_day_number = False
            day_number = 0
            total_days = 0
            
            if placement_details:
                placement_type = placement_details.get('placementType', '')
                # Show "Day X of Y" for ISS and Lunch Detention (multi-day placements)
                if placement_type in ['ISS', 'LUNCH_DETENTION']:
                    day_number = calculate_school_day_number(
                        placement_details['startDate'], 
                        session_context['date']
                    )
                    total_days = placement_details.get('daysAssigned', 0)
                    # Only show if we got a valid day number (weekday within placement)
                    if day_number > 0:
                        show_day_number = True
            
            # Display session details in a nice badge format
            # Use 5 columns if showing day number, otherwise 4
            if show_day_number:
                col1, col2, col3, col4, col5 = st.columns(5)
            else:
                col1, col2, col3, col4 = st.columns(4)
            
            with col1:
                st.metric("Type", session_context['type_label'])
            with col2:
                st.metric("Scope", session_context['scope'])
            with col3:
                st.metric("Date", format_date(session_context['date']))
            with col4:
                # Status with color coding
                status = session_context['status']
                status_display = status.replace('_', ' ').title()
                status_color = {
                    'scheduled': '🔵',
                    'in_progress': '🟢',
                    'fulfilled': '✅',
                    'no_show': '🔴'
                }.get(status, '⚪')
                st.metric("Status", f"{status_color} {status_display}")
            
            if show_day_number:
                with col5:
                    st.metric("Progress", f"Day {day_number} of {total_days}")
            
            # Attendance tracking buttons
            st.markdown("**Attendance:**")
            btn_col1, btn_col2, btn_col3 = st.columns(3)
            
            current_status = session_context['status']
            
            with btn_col1:
                # Check-in button (scheduled → in_progress)
                if current_status == 'scheduled':
                    if st.button("✓ Check-in", key=f"checkin_{current_session_id}", use_container_width=True):
                        if dm.update_session_status(current_session_id, 'in_progress'):
                            st.success("✅ Student checked in!")
                            st.rerun()
                        else:
                            st.error("❌ Failed to check in")
                else:
                    st.button("✓ Check-in", disabled=True, use_container_width=True)
            
            with btn_col2:
                # Check-out button (in_progress → fulfilled)
                if current_status == 'in_progress':
                    if st.button("✓ Check-out", key=f"checkout_{current_session_id}", use_container_width=True):
                        if dm.update_session_status(current_session_id, 'fulfilled'):
                            st.success("✅ Student checked out!")
                            st.rerun()
                        else:
                            st.error("❌ Failed to check out")
                else:
                    st.button("✓ Check-out", disabled=True, use_container_width=True)
            
            with btn_col3:
                # Mark No-show button (scheduled → no_show)
                if current_status == 'scheduled':
                    if st.button("⚠ Mark No-show", key=f"noshow_{current_session_id}", use_container_width=True):
                        if dm.update_session_status(current_session_id, 'no_show', set_alert=True):
                            st.warning("⚠️ Marked as no-show. Supervisor alert created.")
                            st.rerun()
                        else:
                            st.error("❌ Failed to mark no-show")
                else:
                    st.button("⚠ Mark No-show", disabled=True, use_container_width=True)
            
            st.divider()
        else:
            st.error("Session not found")
            current_session_id = None
    
    # If not in session context, show placement-wide view
    if not session_context:
        # Date selector
        selected_date = st.date_input("Select Date", value=date.today())
        
        # Get active placements for the selected date
        active_placements = dm.get_active_placements_for_date(selected_date)
        
        if not active_placements:
            st.info("No active placements for selected date.")
        else:
            st.subheader(f"Daily Logs for {format_date(selected_date)}")
    
    # Process either session-scoped or placement-wide view
    if session_context:
        # Session-scoped view - single student/session
        placements_to_display = [{'_id': session_context['placement_id'], 
                                   'student': {'_id': session_context['student_id'],
                                              'firstName': session_context['student_first_name'],
                                              'lastName': session_context['student_last_name']}}]
        selected_date = datetime.fromisoformat(session_context['date']).date()
        is_session_scoped = True
    elif not session_context and active_placements:
        # Placement-wide view - all placements
        placements_to_display = active_placements
        is_session_scoped = False
    else:
        placements_to_display = []
        is_session_scoped = False
    
    # Extract session type for behavior filtering (if in session-scoped view)
    session_type_filter = None
    if is_session_scoped and session_context:
        session_type_filter = session_context.get('type')  # e.g., 'iss_full_day', 'periods', 'lunch', 'cool_down'
    
    # Display daily logs
    for placement in placements_to_display:
        student = placement['student']
        daily_log = dm.get_or_create_daily_log(placement['_id'], selected_date.isoformat())
        
        # In session-scoped view, don't use expander (already have header)
        # In placement-wide view, use expander
        if is_session_scoped:
            # Session-scoped view - no expander needed
            # Check if log is finalized
            is_finalized = daily_log.get('finalizedBy') is not None
            
            # Display alert indicator if present
            if daily_log.get('alertFlag'):
                st.error("⚠️ ALERT: Daily Fulfillment marked as NO - Requires supervisor review")
            
            # Get session-scoped point events
            todays_events = dm.get_point_events_for_session(current_session_id, selected_date.isoformat())
            positive_points = sum([e['value'] for e in todays_events if e['type'] == 'positive'])
            negative_points = sum([e['value'] for e in todays_events if e['type'] == 'negative'])
            
            col1, col2 = st.columns(2)
            
            with col1:
                st.subheader("Points")
                
                if not is_finalized:
                    # Positive Behaviors - Dropdown to add
                    st.markdown("**Add Positive Behavior**")
                    positive_menu = ps.get_positive_point_menu(session_type_filter)
                    
                    # Build options with availability status
                    positive_options = ["-- Select Behavior --"]
                    available_map = {}  # Maps display label to (item, can_add)
                    
                    for item in positive_menu:
                        can_add, reason = ps.can_add_point_event(
                            placement['_id'], 
                            student['_id'], 
                            item['code'], 
                            selected_date.isoformat()
                        )
                        
                        if can_add:
                            display_label = item['label']
                            available_map[display_label] = (item, True)
                        else:
                            display_label = f"🔒 {item['label']}"
                            available_map[display_label] = (item, False)
                        
                        positive_options.append(display_label)
                    
                    selected_positive_behavior = st.selectbox(
                        "Choose positive behavior to add:",
                        positive_options,
                        key=f"pos_select_{daily_log['_id']}_session",
                        label_visibility="collapsed"
                    )
                    
                    if selected_positive_behavior != "-- Select Behavior --":
                        item, can_add = available_map[selected_positive_behavior]
                        
                        if can_add:
                            # Add point event with session_id
                            dm.add_point_event({
                                'placementId': placement['_id'],
                                'studentId': student['_id'],
                                'sessionId': current_session_id,  # Include session_id
                                'code': item['code'],
                                'type': 'positive',
                                'value': item['value'],
                                'date': selected_date.isoformat(),
                                'notes': f"{item['label']}"
                            })
                            st.rerun()
                        else:
                            st.error("This behavior is not available")
                    
                    st.divider()
                    
                    # Negative Behaviors - Dropdown to add
                    st.markdown("**Add Negative Behavior**")
                    negative_menu = ps.get_negative_point_menu(session_type_filter)
                    
                    negative_options = ["-- Select Behavior --"] + [item['label'] for item in negative_menu]
                    selected_negative_behavior = st.selectbox(
                        "Choose negative behavior to add:",
                        negative_options,
                        key=f"neg_select_{daily_log['_id']}_session",
                        label_visibility="collapsed"
                    )
                    
                    if selected_negative_behavior != "-- Select Behavior --":
                        # Find the selected item
                        selected_item = next(item for item in negative_menu if item['label'] == selected_negative_behavior)
                        
                        # Add point event with session_id
                        dm.add_point_event({
                            'placementId': placement['_id'],
                            'studentId': student['_id'],
                            'sessionId': current_session_id,  # Include session_id
                            'code': selected_item['code'],
                            'type': 'negative',
                            'value': selected_item['value'],
                            'date': selected_date.isoformat(),
                            'notes': f"{selected_item['label']}"
                        })
                        st.rerun()
                    
                    st.divider()
                else:
                    # Show finalized metrics
                    st.metric("Positive Points", daily_log['positiveTotal'])
                    st.metric("Negative Points", daily_log['negativeTotal'])
                    
                    st.divider()
                
                # Daily Total section
                st.subheader("Daily Total")
                # Compute daily total
                computed_total = positive_points + negative_points
                st.markdown(f"<h1 style='text-align: left; margin: 0;'>{computed_total}</h1>", unsafe_allow_html=True)
                
                # Finalize button (disabled if both points are 0 or null)
                if not is_finalized:
                    can_finalize = (positive_points != 0 or negative_points != 0)
                    if st.button(
                        "Finalize Log", 
                        key=f"finalize_{daily_log['_id']}",
                        disabled=not can_finalize,
                        help="Points must be set (not both zero) to finalize"
                    ):
                        dm.finalize_daily_log(daily_log['_id'], "Staff")
                        st.success("✅ Daily log finalized!")
                        st.rerun()
                else:
                    st.success(f"✅ Finalized by: {daily_log['finalizedBy']}")
                    st.caption(f"At: {daily_log.get('finalizedAt', 'Unknown')}")
            
            with col2:
                st.subheader("Today's Behaviors")
                
                if todays_events:
                    for idx, event in enumerate(todays_events):
                        item = ps.get_point_item_by_code(event['code'])
                        icon = "✅" if event['type'] == 'positive' else "❌"
                        col_behavior, col_remove = st.columns([4, 1])
                        with col_behavior:
                            st.caption(f"{icon} {item['label']}")
                        with col_remove:
                            if not is_finalized:
                                if st.button("✕", key=f"remove_{event['_id']}", help="Remove this behavior"):
                                    dm.delete_point_event(event['_id'])
                                    st.rerun()
                else:
                    st.info("No behaviors added yet")
        
        else:
            # Placement-wide view - use expander
            is_expanded = True
            
            with st.expander(f"{student['firstName']} {student['lastName']}", expanded=is_expanded):
                # Check if log is finalized
                is_finalized = daily_log.get('finalizedBy') is not None
                
                # Display alert indicator if present
                if daily_log.get('alertFlag'):
                    st.error("⚠️ ALERT: Daily Fulfillment marked as NO - Requires supervisor review")
                
                # Get placement-wide point events (no session filter)
                todays_events = dm.get_point_events_for_date(placement['_id'], selected_date.isoformat())
                positive_points = sum([e['value'] for e in todays_events if e['type'] == 'positive'])
                negative_points = sum([e['value'] for e in todays_events if e['type'] == 'negative'])
                
                col1, col2 = st.columns(2)
                
                with col1:
                    st.subheader("Points")
                    
                    if not is_finalized:
                        # Positive Behaviors - Dropdown to add
                        st.markdown("**Add Positive Behavior**")
                        positive_menu = ps.get_positive_point_menu()
                        
                        # Build options with availability status
                        positive_options = ["-- Select Behavior --"]
                        available_map = {}  # Maps display label to (item, can_add)
                        
                        for item in positive_menu:
                            can_add, reason = ps.can_add_point_event(
                                placement['_id'], 
                                student['_id'], 
                                item['code'], 
                                selected_date.isoformat()
                            )
                            
                            if can_add:
                                display_label = item['label']
                                available_map[display_label] = (item, True)
                            else:
                                display_label = f"🔒 {item['label']}"
                                available_map[display_label] = (item, False)
                            
                            positive_options.append(display_label)
                        
                        selected_positive_behavior = st.selectbox(
                            "Choose positive behavior to add:",
                            positive_options,
                            key=f"pos_select_{daily_log['_id']}",
                            label_visibility="collapsed"
                        )
                        
                        if selected_positive_behavior != "-- Select Behavior --":
                            item, can_add = available_map[selected_positive_behavior]
                            
                            if can_add:
                                # Add point event (no session_id for placement-wide view)
                                dm.add_point_event({
                                    'placementId': placement['_id'],
                                    'studentId': student['_id'],
                                    'code': item['code'],
                                    'type': 'positive',
                                    'value': item['value'],
                                    'date': selected_date.isoformat(),
                                    'notes': f"{item['label']}"
                                })
                                st.rerun()
                            else:
                                st.error("This behavior is not available")
                        
                        st.divider()
                        
                        # Negative Behaviors - Dropdown to add
                        st.markdown("**Add Negative Behavior**")
                        negative_menu = ps.get_negative_point_menu()
                        
                        negative_options = ["-- Select Behavior --"] + [item['label'] for item in negative_menu]
                        selected_negative_behavior = st.selectbox(
                            "Choose negative behavior to add:",
                            negative_options,
                            key=f"neg_select_{daily_log['_id']}",
                            label_visibility="collapsed"
                        )
                        
                        if selected_negative_behavior != "-- Select Behavior --":
                            # Find the selected item
                            selected_item = next(item for item in negative_menu if item['label'] == selected_negative_behavior)
                            
                            # Add point event (no session_id for placement-wide view)
                            dm.add_point_event({
                                'placementId': placement['_id'],
                                'studentId': student['_id'],
                                'code': selected_item['code'],
                                'type': 'negative',
                                'value': selected_item['value'],
                                'date': selected_date.isoformat(),
                                'notes': f"{selected_item['label']}"
                            })
                            st.rerun()
                        
                        st.divider()
                    else:
                        # Show finalized metrics
                        st.metric("Positive Points", daily_log['positiveTotal'])
                        st.metric("Negative Points", daily_log['negativeTotal'])
                        
                        st.divider()
                    
                    # Daily Total section
                    st.subheader("Daily Total")
                    # Compute daily total
                    computed_total = positive_points + negative_points
                    st.markdown(f"<h1 style='text-align: left; margin: 0;'>{computed_total}</h1>", unsafe_allow_html=True)
                    
                    # Finalize button (disabled if both points are 0 or null)
                    if not is_finalized:
                        can_finalize = (positive_points != 0 or negative_points != 0)
                        if st.button(
                            "Finalize Log", 
                            key=f"finalize_{daily_log['_id']}",
                            disabled=not can_finalize,
                            help="Points must be set (not both zero) to finalize"
                        ):
                            dm.finalize_daily_log(daily_log['_id'], "Staff")
                            st.success("Daily log finalized!")
                            st.rerun()
                    else:
                        st.success(f"✓ Finalized by: {daily_log['finalizedBy']}")
                        st.caption(f"At: {daily_log.get('finalizedAt', 'Unknown')}")
                
                with col2:
                    st.subheader("Today's Behaviors")
                    
                    if todays_events:
                        for idx, event in enumerate(todays_events):
                            item = ps.get_point_item_by_code(event['code'])
                            icon = "✅" if event['type'] == 'positive' else "❌"
                            col_behavior, col_remove = st.columns([4, 1])
                            with col_behavior:
                                st.caption(f"{icon} {item['label']}")
                            with col_remove:
                                if not is_finalized:
                                    if st.button("✕", key=f"remove_{event['_id']}", help="Remove this behavior"):
                                        dm.delete_point_event(event['_id'])
                                        st.rerun()
                    else:
                        st.info("No behaviors added yet")

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
