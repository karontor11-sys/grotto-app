import streamlit as st
import pandas as pd
from datetime import datetime, date, timedelta
from db_manager import DatabaseManager
from point_system import PointSystem
from analytics import AnalyticsEngine
from import_export import ImportExportManager
from notifications import NotificationManager
from utils import format_date, calculate_days_remaining, get_status_color

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
    
    # Create New Placement button
    if st.button("Create New Placement", type="primary"):
        st.session_state.navigate_to_create_placement = True
        st.rerun()
    
    # Today's Sessions strip
    st.markdown("### Today's Sessions")
    todays_sessions = dm.get_todays_sessions()
    
    if not todays_sessions:
        st.info("No sessions today.")
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
    st.markdown("### Active Placements")
    
    # Get all active placements with student info
    active_placements = dm.get_active_placements_with_students()
    
    if not active_placements:
        st.info("No active placements found.")
    else:
        # Display student cards in columns
        cols_per_row = 3
        for i in range(0, len(active_placements), cols_per_row):
            cols = st.columns(cols_per_row)
            for j, placement in enumerate(active_placements[i:i+cols_per_row]):
                with cols[j]:
                    student = placement['student']
                    
                    # Calculate metrics
                    days_completed = placement.get('daysCompleted', 0)
                    days_remaining = calculate_days_remaining(placement['startDate'], placement['daysAssigned'], days_completed)
                    todays_points = dm.get_todays_points(placement['_id'])
                    
                    # Student card
                    with st.container():
                        st.subheader(f"{student['firstName']} {student['lastName']}")
                        st.write(f"**Grade:** {student['grade']}")
                        st.write(f"**Homeroom Teacher:** {student['homeroomTeacher']}")
                        st.write(f"**Start Date:** {format_date(placement['startDate'])}")
                        st.write(f"**Days Remaining:** {days_remaining}")
                        
                        # Points badge
                        if todays_points >= 0:
                            st.success(f"Today's Points: +{todays_points}")
                        else:
                            st.error(f"Today's Points: {todays_points}")
                        
                        # Quick actions
                        col_btn1, col_btn2 = st.columns(2)
                        with col_btn1:
                            if st.button("Daily Logs", key=f"daily_logs_{placement['_id']}", use_container_width=True):
                                st.session_state.selected_placement_for_daily_logs = placement['_id']
                                st.session_state.navigate_to_daily_logs = True
                                st.rerun()
                        
                        # Complete Placement button (Supervisor/Admin only)
                        with col_btn2:
                            if user_role in ["Supervisor", "Admin"]:
                                # Check completion criteria
                                completion_check = dm.check_placement_completion_criteria(placement['_id'])
                                can_complete = completion_check.get('can_complete', False)
                                
                                if st.button(
                                    "Complete",
                                    key=f"complete_{placement['_id']}",
                                    disabled=not can_complete,
                                    use_container_width=True,
                                    type="primary" if can_complete else "secondary"
                                ):
                                    if dm.complete_placement(placement['_id']):
                                        st.success(f"Placement completed for {student['firstName']} {student['lastName']}")
                                        st.rerun()
                                    else:
                                        st.error("Failed to complete placement")
                                
                                # Show completion status as help text
                                if not can_complete:
                                    st.caption(f"⏳ {completion_check.get('reason', 'Not ready')}")

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
        
        # Placement Type toggle (outside form so it updates dynamically)
        placement_type = st.radio(
            "Placement Type",
            options=["ISS Days", "Partial Day"],
            horizontal=True,
            help="Choose ISS Days for full-day placements or Partial Day for period-specific sessions"
        )
        
        st.divider()
        
        if placement_type == "ISS Days":
            # ISS Days - show full form
            with st.form("create_placement_form"):
                # Student information section
                st.markdown("### Student Information")
                col1, col2 = st.columns(2)
                
                with col1:
                    first_name = st.text_input("First Name*")
                    grade = st.selectbox("Grade*", ["K", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12"])
                with col2:
                    last_name = st.text_input("Last Name*")
                    homeroom_teacher = st.text_input("Homeroom Teacher*")
                
                # Placement information section
                st.markdown("### Placement Details")
                
                # Placement Type selector
                placement_category = st.radio(
                    "Placement Type*",
                    options=["In-School Suspension (ISS)", "Lunch Detention", "Class Period Referral", "Cool-Down Referral"],
                    horizontal=True,
                    help="Select the type of placement"
                )
                
                # Map display names to internal values
                placement_type_map = {
                    "In-School Suspension (ISS)": "ISS",
                    "Lunch Detention": "LUNCH_DETENTION",
                    "Class Period Referral": "CLASS_REFERRAL",
                    "Cool-Down Referral": "COOL_DOWN"
                }
                placement_type_value = placement_type_map[placement_category]
                
                reason = st.text_area("Reason for Placement*")
                
                col3, col4 = st.columns(2)
                with col3:
                    start_date = st.date_input("Start Date*", value=date.today())
                with col4:
                    days_assigned = st.slider("Number of Days*", min_value=1, max_value=15, value=5)
                
                created_by = st.text_input("Created By*", value="Staff")
                
                # Submit button
                if st.form_submit_button("Create Placement"):
                    # Validate fields
                    if not first_name or not last_name or not homeroom_teacher or not reason or not created_by:
                        st.error("Please fill in all required fields marked with *")
                    else:
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
                        
                        # Create placement with new student
                        placement_data = {
                            "studentId": student_id,
                            "homeroomTeacherId": homeroom_teacher,
                            "reason": reason,
                            "type": "iss_full_day",
                            "placementType": placement_type_value,
                            "completionRule": "iss_days",
                            "minSessionsRequired": None,
                            "daysAssigned": days_assigned,
                            "startDate": start_date.isoformat(),
                            "status": "active",
                            "createdBy": created_by,
                            "createdAt": datetime.now().isoformat()
                        }
                        placement_id = dm.add_placement(placement_data)
                        
                        # Generate ISS full-day sessions (weekends automatically skipped)
                        dm.generate_iss_full_day_sessions(placement_id, start_date, days_assigned)
                        
                        st.session_state.placement_created = True
                        st.session_state.navigate_to_dashboard = True
                        st.rerun()
        
        else:
            # Partial Day - show placement fields and subtype selection
            st.markdown("### Partial Day Placement")
            
            # Student Information
            st.markdown("#### Student Information")
            col1, col2 = st.columns(2)
            
            with col1:
                partial_first_name = st.text_input("First Name*", key="partial_fname")
                partial_grade = st.selectbox("Grade*", ["K", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12"], key="partial_grade")
            with col2:
                partial_last_name = st.text_input("Last Name*", key="partial_lname")
                partial_homeroom_teacher = st.text_input("Homeroom Teacher*", key="partial_homeroom")
            
            # Placement Information
            st.markdown("#### Placement Information")
            
            # Placement Type selector
            partial_placement_category = st.radio(
                "Placement Type*",
                options=["In-School Suspension (ISS)", "Lunch Detention", "Class Period Referral", "Cool-Down Referral"],
                horizontal=True,
                help="Select the type of placement",
                key="partial_placement_type"
            )
            
            # Map display names to internal values
            partial_placement_type_map = {
                "In-School Suspension (ISS)": "ISS",
                "Lunch Detention": "LUNCH_DETENTION",
                "Class Period Referral": "CLASS_REFERRAL",
                "Cool-Down Referral": "COOL_DOWN"
            }
            partial_placement_type_value = partial_placement_type_map[partial_placement_category]
            
            col1, col2 = st.columns(2)
            with col1:
                partial_reason = st.text_area("Reason for Placement*", key="partial_reason")
                partial_start_date = st.date_input("Start Date*", value=date.today(), key="partial_start_date")
            with col2:
                partial_created_by = st.text_input("Created By (Your Name)*", key="partial_created_by")
                # Days assigned set to 1 for partial day placements (can be extended later)
                st.info("Partial day placements: Sessions are created individually")
            
            st.divider()
            
            # Subtype selection using pills (radio buttons)
            subtype = st.radio(
                "Select Session Subtype",
                options=["Periods", "Lunch Detention", "Cool-down", "Single-period Referral"],
                horizontal=True,
                help="Choose the type of partial-day session to create"
            )
            
            st.divider()
            
            # Show inputs based on selected subtype
            if subtype == "Periods":
                st.subheader("📚 Period-based Sessions")
                
                col1, col2 = st.columns(2)
                with col1:
                    session_date = st.date_input("Session Date*", value=date.today())
                    periods = st.multiselect(
                        "Select Periods*",
                        options=[1, 2, 3, 4, 5, 6, 7, 8],
                        help="Select one or more periods for this session"
                    )
                with col2:
                    repeat_days = st.number_input(
                        "Repeat for N Days (optional)",
                        min_value=0,
                        max_value=10,
                        value=0,
                        help="Leave at 0 for single day, or enter number of days to repeat"
                    )
                    location = st.text_input("Location", value="ISS Room")
                
                # Validation
                if periods:
                    st.info(f"✓ Selected {len(periods)} period(s): {', '.join([f'Period {p}' for p in periods])}")
                else:
                    st.warning("Please select at least one period")
            
            elif subtype == "Lunch Detention":
                st.subheader("🍽️ Lunch Detention Sessions")
                
                col1, col2 = st.columns(2)
                with col1:
                    start_date_lunch = st.date_input("Start Date*", value=date.today())
                    end_date_lunch = st.date_input("End Date*", value=date.today())
                with col2:
                    lunch_block = st.selectbox("Lunch Block*", options=["A Lunch", "B Lunch", "C Lunch"])
                    location_lunch = st.text_input("Location*", value="Cafeteria/Detention")
                
                # Validate date range
                #  st.caption(f"Debug: Start={start_date_lunch}, End={end_date_lunch}")  # Debug line
                if end_date_lunch < start_date_lunch:
                    st.error(f"❌ End date ({end_date_lunch}) must be on or after start date ({start_date_lunch})")
                else:
                    days_in_range = (end_date_lunch - start_date_lunch).days + 1
                    st.info(f"✓ Date range: {start_date_lunch} to {end_date_lunch} spans {days_in_range} day(s)")
                
                st.markdown("**Weekdays to Include:**")
                weekday_cols = st.columns(5)
                weekdays_selected = []
                with weekday_cols[0]:
                    mon_checked = st.checkbox("Monday", value=True, key="lunch_mon")
                    if mon_checked:
                        weekdays_selected.append("Mon")
                with weekday_cols[1]:
                    tue_checked = st.checkbox("Tuesday", value=True, key="lunch_tue")
                    if tue_checked:
                        weekdays_selected.append("Tue")
                with weekday_cols[2]:
                    wed_checked = st.checkbox("Wednesday", value=True, key="lunch_wed")
                    if wed_checked:
                        weekdays_selected.append("Wed")
                with weekday_cols[3]:
                    thu_checked = st.checkbox("Thursday", value=True, key="lunch_thu")
                    if thu_checked:
                        weekdays_selected.append("Thu")
                with weekday_cols[4]:
                    fri_checked = st.checkbox("Friday", value=True, key="lunch_fri")
                    if fri_checked:
                        weekdays_selected.append("Fri")
                
                if weekdays_selected:
                    st.info(f"✓ Sessions will occur on: {', '.join(weekdays_selected)}")
                else:
                    st.warning("⚠️ Please select at least one weekday")
            
            elif subtype == "Cool-down":
                st.subheader("🧘 Cool-down Session")
                
                st.info("Cool-down sessions are for today only")
                
                col1, col2 = st.columns(2)
                with col1:
                    time_start = st.time_input("Start Time*", value=datetime.now().time())
                    quick_reason = st.text_area("Quick Reason*", placeholder="Brief description of what happened...")
                with col2:
                    # Default end time is 1 hour after current time
                    default_end = (datetime.now() + timedelta(hours=1)).time()
                    time_end = st.time_input("End Time*", value=default_end)
                    location_cooldown = st.selectbox("Location*", options=["ISS Room", "Counselor Office", "Main Office"])
                
                # Show duration if both times selected
                if time_start and time_end:
                    duration_minutes = (datetime.combine(date.today(), time_end) - datetime.combine(date.today(), time_start)).total_seconds() / 60
                    if duration_minutes > 0:
                        st.info(f"✓ Duration: {int(duration_minutes)} minutes")
                    else:
                        st.error("❌ End time must be after start time")
            
            elif subtype == "Single-period Referral":
                st.subheader("📝 Single-period Referral")
                
                col1, col2 = st.columns(2)
                with col1:
                    referral_date = st.date_input("Date*", value=date.today(), key="ref_date")
                    single_period = st.selectbox("Period*", options=[1, 2, 3, 4, 5, 6, 7, 8], key="ref_period")
                    referring_teacher = st.text_input("Referring Teacher*", key="ref_teacher")
                with col2:
                    referral_reason = st.selectbox(
                        "Referral Reason*",
                        options=["Behavioral Issue", "Sub Coverage", "Administrative", "Other"],
                        key="ref_reason"
                    )
                    location_referral = st.text_input("Location*", value="ISS Room", key="ref_location")
                
                # Conditional field - shown only for "Other" reason
                # Note: Field will always appear but validation enforced during session creation
                if referral_reason == "Other":
                    st.caption("↳ Please provide additional details:")
                    other_reason = st.text_input("Specify Other Reason*", key="ref_other_specify", label_visibility="collapsed")
                
                # Note: Full field validation will occur when Preview Sessions is enabled
            
            st.divider()
            
            # Preview Sessions button and logic
            if 'preview_mode' not in st.session_state:
                st.session_state.preview_mode = False
            
            if not st.session_state.preview_mode:
                # Show Preview button
                if st.button("Preview Sessions", type="primary"):
                    # Validation before preview
                    errors = []
                    generated_sessions = []
                    
                    if subtype == "Periods":
                        if not periods:
                            errors.append("Please select at least one period")
                        else:
                            generated_sessions = generate_periods_sessions(
                                session_date, periods, repeat_days, location or "ISS Room"
                            )
                    
                    elif subtype == "Lunch Detention":
                        if end_date_lunch < start_date_lunch:
                            errors.append("End date must be on or after start date")
                        
                        # Get weekday values from session state
                        weekdays_map = {
                            "mon": st.session_state.get("lunch_mon", False),
                            "tue": st.session_state.get("lunch_tue", False),
                            "wed": st.session_state.get("lunch_wed", False),
                            "thu": st.session_state.get("lunch_thu", False),
                            "fri": st.session_state.get("lunch_fri", False)
                        }
                        
                        if not any(weekdays_map.values()):
                            errors.append("Please select at least one weekday")
                        
                        if not errors:
                            generated_sessions = generate_lunch_sessions(
                                start_date_lunch, end_date_lunch, weekdays_map,
                                lunch_block, location_lunch or "Cafeteria/Detention"
                            )
                    
                    elif subtype == "Cool-down":
                        if not quick_reason or not quick_reason.strip():
                            errors.append("Please provide a quick reason")
                        
                        duration_minutes = (datetime.combine(date.today(), time_end) - 
                                          datetime.combine(date.today(), time_start)).total_seconds() / 60
                        if duration_minutes <= 0:
                            errors.append("End time must be after start time")
                        
                        if not errors:
                            generated_sessions = generate_cooldown_session(
                                time_start, time_end, location_cooldown, quick_reason
                            )
                    
                    elif subtype == "Single-period Referral":
                        if not referring_teacher or not referring_teacher.strip():
                            errors.append("Please provide a referring teacher")
                        if not location_referral or not location_referral.strip():
                            errors.append("Please provide a location")
                        if referral_reason == "Other" and (not st.session_state.get("ref_other_specify") or 
                                                          not st.session_state["ref_other_specify"].strip()):
                            errors.append("Please specify the other reason")
                        
                        if not errors:
                            other_reason_text = st.session_state.get("ref_other_specify", "") if referral_reason == "Other" else None
                            generated_sessions = generate_referral_session(
                                referral_date, single_period, location_referral,
                                referring_teacher, referral_reason, other_reason_text
                            )
                    
                    # Show errors or proceed to preview
                    if errors:
                        for error in errors:
                            st.error(f"❌ {error}")
                    else:
                        st.session_state.preview_sessions = generated_sessions
                        st.session_state.preview_mode = True
                        st.rerun()
            
            else:
                # Show preview table
                st.success("✅ Session Preview Generated")
                st.markdown("### Sessions to be Created")
                st.caption("Review the sessions below before creating them")
                
                sessions = st.session_state.preview_sessions
                
                # Detect conflicts
                conflicts = detect_session_conflicts(sessions)
                
                # Show conflict warnings
                if conflicts:
                    st.warning(f"⚠️ {len(conflicts)} potential conflict(s) detected:")
                    for conflict in conflicts:
                        st.caption(f"  • {conflict['message']}")
                
                # Create DataFrame for display
                df_data = []
                for i, session in enumerate(sessions):
                    df_data.append({
                        "Date": session["date"].strftime("%m/%d/%Y"),
                        "Type": session["type"].replace("_", " ").title(),
                        "Scope": session["scope"],
                        "Location": session["location"]
                    })
                
                df = pd.DataFrame(df_data)
                st.dataframe(df, use_container_width=True, hide_index=True)
                
                st.info(f"📊 Total sessions to create: {len(sessions)}")
                
                # Back and Create buttons
                st.divider()
                col1, col2 = st.columns([1, 1])
                with col1:
                    if st.button("← Back to Edit", use_container_width=True):
                        st.session_state.preview_mode = False
                        if 'preview_sessions' in st.session_state:
                            del st.session_state.preview_sessions
                        st.rerun()
                with col2:
                    if st.button("Create Placement & Sessions", type="primary", use_container_width=True):
                        # Validate placement fields
                        creation_errors = []
                        
                        if not all([partial_first_name, partial_last_name, partial_grade, partial_homeroom_teacher]):
                            creation_errors.append("Please fill in all student information fields")
                        
                        if not partial_reason or not partial_reason.strip():
                            creation_errors.append("Please provide a reason for placement")
                        if not partial_created_by or not partial_created_by.strip():
                            creation_errors.append("Please provide your name in Created By field")
                        
                        if creation_errors:
                            for error in creation_errors:
                                st.error(f"❌ {error}")
                        else:
                            try:
                                # Create new student
                                new_student_data = {
                                    "firstName": partial_first_name,
                                    "lastName": partial_last_name,
                                    "grade": partial_grade,
                                    "homeroomTeacher": partial_homeroom_teacher,
                                    "guardianContacts": []
                                }
                                final_student_id = dm.add_student(new_student_data)
                                final_homeroom_teacher = partial_homeroom_teacher
                                
                                # Create placement with type="partial"
                                # For partial day, days_assigned is calculated from number of sessions
                                # Default to all_sessions_fulfilled for partial placements
                                placement_data = {
                                    "studentId": final_student_id,
                                    "homeroomTeacherId": final_homeroom_teacher,
                                    "reason": partial_reason,
                                    "type": "partial",
                                    "placementType": partial_placement_type_value,
                                    "completionRule": "all_sessions_fulfilled",
                                    "minSessionsRequired": None,
                                    "daysAssigned": len(sessions),  # Number of sessions
                                    "startDate": partial_start_date.isoformat(),
                                    "status": "active",
                                    "createdBy": partial_created_by,
                                    "createdAt": datetime.now().isoformat()
                                }
                                placement_id = dm.add_placement(placement_data)
                                
                                # Create sessions from preview data
                                sessions_to_create = []
                                for session in sessions:
                                    session_data = {
                                        "placement_id": placement_id,
                                        "date": session["date"],
                                        "type": session["type"],
                                        "location": session["location"],
                                        "periods": session["metadata"].get("periods", []) if "metadata" in session and session["metadata"].get("period") else [],
                                        "time_start": session["metadata"].get("start_time") if "metadata" in session else None,
                                        "time_end": session["metadata"].get("end_time") if "metadata" in session else None,
                                        "notes": session["metadata"].get("reason", "") if "metadata" in session else ""
                                    }
                                    # Add period to periods list if it exists
                                    if "metadata" in session and "period" in session["metadata"]:
                                        session_data["periods"] = [session["metadata"]["period"]]
                                    
                                    sessions_to_create.append(session_data)
                                
                                dm.add_sessions_bulk(sessions_to_create)
                                
                                # Clear preview state and navigate to Dashboard
                                st.session_state.preview_mode = False
                                if 'preview_sessions' in st.session_state:
                                    del st.session_state.preview_sessions
                                st.session_state.placement_created = True
                                st.session_state.navigate_to_dashboard = True
                                st.rerun()
                            except Exception as e:
                                st.error(f"❌ Error creating placement: {str(e)}")
                                import traceback
                                st.error(traceback.format_exc())
    
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
            st.markdown("---")
            
            # Display completed placements
            for placement in filtered_placements:
                student = placement['student']
                with st.expander(f"{student['firstName']} {student['lastName']} - {placement['reason']}"):
                    col1, col2 = st.columns(2)
                    with col1:
                        st.write(f"**Name:** {student['firstName']} {student['lastName']}")
                        st.write(f"**Start Date:** {format_date(placement['startDate'])}")
                        st.write(f"**Reason:** {placement['reason']}")
                    with col2:
                        st.write(f"**Number of Days:** {placement['daysAssigned']}")
                        st.write(f"**End Date:** {format_date(placement.get('endDate', 'N/A'))}")
                        st.write(f"**Total Points Earned:** {placement.get('totalPoints', 0)}")
                    
                    # Restore button
                    if st.button(f"Restore to Active", key=f"restore_{placement['_id']}"):
                        dm.restore_placement_to_active(placement['_id'])
                        st.success("Placement restored to active!")
                        st.rerun()
        else:
            st.info("No completed placements found.")

# Daily Logs Page
elif page == "Daily Logs":
    st.header("Daily Log Manager")
    
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
                st.markdown(f"### {session_context['student_name']} · {session_context['type_label']}")
            with header_col2:
                if st.button("← Back", key="exit_session_view"):
                    # Clear the session view state
                    if 'current_session_view_id' in st.session_state:
                        del st.session_state.current_session_view_id
                    st.rerun()
            
            # Show alert if no-show
            if session_context.get('alert_flag'):
                st.error("⚠️ SUPERVISOR ALERT: Student marked as no-show")
            
            # Display session details in a nice badge format
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
            
            # Attendance tracking buttons
            st.markdown("**Attendance:**")
            btn_col1, btn_col2, btn_col3 = st.columns(3)
            
            current_status = session_context['status']
            
            with btn_col1:
                # Check-in button (scheduled → in_progress)
                if current_status == 'scheduled':
                    if st.button("✓ Check-in", key=f"checkin_{current_session_id}", use_container_width=True):
                        if dm.update_session_status(current_session_id, 'in_progress'):
                            st.success("Student checked in!")
                            st.rerun()
                        else:
                            st.error("Failed to check in")
                else:
                    st.button("✓ Check-in", disabled=True, use_container_width=True)
            
            with btn_col2:
                # Check-out button (in_progress → fulfilled)
                if current_status == 'in_progress':
                    if st.button("✓ Check-out", key=f"checkout_{current_session_id}", use_container_width=True):
                        if dm.update_session_status(current_session_id, 'fulfilled'):
                            st.success("Student checked out!")
                            st.rerun()
                        else:
                            st.error("Failed to check out")
                else:
                    st.button("✓ Check-out", disabled=True, use_container_width=True)
            
            with btn_col3:
                # Mark No-show button (scheduled → no_show)
                if current_status == 'scheduled':
                    if st.button("⚠ Mark No-show", key=f"noshow_{current_session_id}", use_container_width=True):
                        if dm.update_session_status(current_session_id, 'no_show', set_alert=True):
                            st.warning("Marked as no-show. Supervisor alert created.")
                            st.rerun()
                        else:
                            st.error("Failed to mark no-show")
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
                    
                    st.markdown("---")
                    
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
                    
                    st.markdown("---")
                else:
                    # Show finalized metrics
                    st.metric("Positive Points", daily_log['positiveTotal'])
                    st.metric("Negative Points", daily_log['negativeTotal'])
                    
                    st.markdown("---")
                
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
                        
                        st.markdown("---")
                        
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
                        
                        st.markdown("---")
                    else:
                        # Show finalized metrics
                        st.metric("Positive Points", daily_log['positiveTotal'])
                        st.metric("Negative Points", daily_log['negativeTotal'])
                        
                        st.markdown("---")
                    
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
