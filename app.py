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

# Page configuration
st.set_page_config(
    page_title="Grotto Dashboard",
    page_icon="🏫",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Main title
st.title("🏫 Grotto Dashboard")

# Sidebar navigation
st.sidebar.title("Navigation")
page = st.sidebar.selectbox(
    "Select a page:",
    ["Dashboard", "Students", "Placements", "Daily Logs", "Point Events", "Assignments", "Notes", "Notifications", "Reports & Analytics", "Import/Export"]
)

# Show notification badge in sidebar
all_notifs = notifications.get_all_notifications()
warning_count = len([n for n in all_notifs if n.get('severity') == 'warning'])
if warning_count > 0:
    st.sidebar.warning(f"⚠️ {warning_count} notifications require attention")

# Dashboard Page
if page == "Dashboard":
    st.header("Student Overview")
    
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
                    cumulative_total = dm.get_cumulative_total(placement['_id'])
                    
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
                        
                        st.info(f"Cumulative Total: {cumulative_total}")
                        
                        # Quick actions
                        if st.button("Daily Logs", key=f"daily_logs_{placement['_id']}"):
                            st.session_state.selected_placement_for_daily_logs = placement['_id']
                            st.session_state.navigate_to_daily_logs = True
                            st.rerun()

# Students Page
elif page == "Students":
    st.header("Student Management")
    
    tab1, tab2 = st.tabs(["View Students", "Add Student"])
    
    with tab1:
        students = dm.get_all_students()
        if students:
            df = pd.DataFrame(students)
            df = df[['firstName', 'lastName', 'grade', 'homeroomTeacher', 'status']]
            st.dataframe(df, use_container_width=True)
            
            # Edit/Delete options
            selected_student = st.selectbox("Select student to edit/delete:", 
                                          [f"{s['firstName']} {s['lastName']}" for s in students])
            if selected_student:
                student_data = next(s for s in students if f"{s['firstName']} {s['lastName']}" == selected_student)
                
                col1, col2 = st.columns(2)
                with col1:
                    if st.button("Edit Student"):
                        st.session_state.editing_student = student_data
                        st.rerun()
                
                with col2:
                    if st.button("Delete Student", type="secondary"):
                        dm.delete_student(student_data['_id'])
                        st.success("Student deleted successfully!")
                        st.rerun()
        else:
            st.info("No students found.")
    
    with tab2:
        with st.form("add_student_form"):
            st.subheader("Add New Student")
            first_name = st.text_input("First Name*")
            last_name = st.text_input("Last Name*")
            grade = st.selectbox("Grade*", ["K", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12"])
            homeroom_teacher = st.text_input("Homeroom Teacher*")
            
            st.subheader("Guardian Contacts")
            num_guardians = st.number_input("Number of guardians", min_value=0, max_value=5, value=1)
            
            guardians = []
            for i in range(num_guardians):
                st.write(f"Guardian {i+1}:")
                name = st.text_input(f"Name", key=f"guardian_name_{i}")
                email = st.text_input(f"Email", key=f"guardian_email_{i}")
                phone = st.text_input(f"Phone", key=f"guardian_phone_{i}")
                if name:
                    guardians.append({"name": name, "email": email, "phone": phone})
            
            if st.form_submit_button("Add Student"):
                if first_name and last_name and grade and homeroom_teacher:
                    student_data = {
                        "firstName": first_name,
                        "lastName": last_name,
                        "grade": grade,
                        "homeroomTeacher": homeroom_teacher,
                        "guardianContacts": guardians,
                        "status": "active"
                    }
                    dm.add_student(student_data)
                    st.success("Student added successfully!")
                    st.rerun()
                else:
                    st.error("Please fill in all required fields marked with *")

# Placements Page
elif page == "Placements":
    st.header("Placement Management")
    
    tab1, tab2 = st.tabs(["Active Placements", "Create Placement"])
    
    with tab1:
        placements = dm.get_active_placements_with_students()
        if placements:
            for placement in placements:
                student = placement['student']
                with st.expander(f"{student['firstName']} {student['lastName']} - {placement['reason']}"):
                    col1, col2 = st.columns(2)
                    with col1:
                        st.write(f"**Start Date:** {placement['startDate']}")
                        st.write(f"**Days Assigned:** {placement['daysAssigned']}")
                        st.write(f"**Created By:** {placement.get('createdBy', 'Unknown')}")
                    with col2:
                        days_completed = placement.get('daysCompleted', 0)
                        days_remaining = calculate_days_remaining(placement['startDate'], placement['daysAssigned'], days_completed)
                        st.write(f"**Days Remaining:** {days_remaining}")
                        st.write(f"**Status:** {placement['status']}")
                        
                        if days_remaining <= 0 and placement['status'] == 'active':
                            if st.button(f"Complete Placement", key=f"complete_{placement['_id']}"):
                                dm.complete_placement(placement['_id'])
                                st.success("Placement completed!")
                                st.rerun()
        else:
            st.info("No active placements found.")
    
    with tab2:
        students = dm.get_all_students()
        if not students:
            st.warning("No students available. Please add students first.")
        else:
            with st.form("create_placement_form"):
                st.subheader("Create New Placement")
                student_options = [f"{s['firstName']} {s['lastName']}" for s in students]
                selected_student = st.selectbox("Select Student*", student_options)
                
                reason = st.text_area("Reason for Placement*")
                days_assigned = st.slider("Days Assigned*", min_value=1, max_value=15, value=5)
                start_date = st.date_input("Start Date*", value=date.today())
                created_by = st.text_input("Created By*", value="Staff")
                
                if st.form_submit_button("Create Placement"):
                    if selected_student and reason and created_by:
                        student_data = next(s for s in students if f"{s['firstName']} {s['lastName']}" == selected_student)
                        
                        placement_data = {
                            "studentId": student_data['_id'],
                            "homeroomTeacherId": student_data['homeroomTeacher'],
                            "reason": reason,
                            "daysAssigned": days_assigned,
                            "startDate": start_date.isoformat(),
                            "status": "active",
                            "createdBy": created_by,
                            "createdAt": datetime.now().isoformat()
                        }
                        dm.add_placement(placement_data)
                        st.success("Placement created successfully!")
                        st.rerun()
                    else:
                        st.error("Please fill in all required fields marked with *")

# Daily Logs Page
elif page == "Daily Logs":
    st.header("Daily Log Management")
    
    # Check if we navigated from Dashboard
    selected_placement_id = None
    if st.session_state.get('navigate_to_daily_logs'):
        selected_placement_id = st.session_state.get('selected_placement_for_daily_logs')
        # Clear the flags
        del st.session_state.navigate_to_daily_logs
        if 'selected_placement_for_daily_logs' in st.session_state:
            del st.session_state.selected_placement_for_daily_logs
        st.info("📋 Showing daily log for selected student")
    
    # Date selector
    selected_date = st.date_input("Select Date", value=date.today())
    
    # Get active placements for the selected date
    active_placements = dm.get_active_placements_for_date(selected_date)
    
    if not active_placements:
        st.info("No active placements for selected date.")
    else:
        st.subheader(f"Daily Logs for {format_date(selected_date)}")
        
        for placement in active_placements:
            student = placement['student']
            daily_log = dm.get_or_create_daily_log(placement['_id'], selected_date.isoformat())
            
            # Expand only the selected student's log, or all by default
            is_expanded = True if selected_placement_id is None else (placement['_id'] == selected_placement_id)
            
            with st.expander(f"{student['firstName']} {student['lastName']}", expanded=is_expanded):
                # Check if log is finalized
                is_finalized = daily_log.get('finalizedBy') is not None
                
                # Display alert indicator if present
                if daily_log.get('alertFlag'):
                    st.error("⚠️ ALERT: Daily Fulfillment marked as NO - Requires supervisor review")
                
                col1, col2, col3 = st.columns(3)
                
                with col1:
                    st.subheader("Points Control")
                    
                    # Positive Points
                    if not is_finalized:
                        positive_points = st.number_input(
                            "Positive Points", 
                            min_value=0,
                            value=daily_log['positiveTotal'],
                            step=1,
                            key=f"pos_{daily_log['_id']}"
                        )
                    else:
                        st.metric("Positive Points", daily_log['positiveTotal'])
                        positive_points = daily_log['positiveTotal']
                    
                    # Negative Points
                    if not is_finalized:
                        negative_points = st.number_input(
                            "Negative Points", 
                            value=daily_log['negativeTotal'],
                            step=1,
                            key=f"neg_{daily_log['_id']}"
                        )
                    else:
                        st.metric("Negative Points", daily_log['negativeTotal'])
                        negative_points = daily_log['negativeTotal']
                    
                    # Update points button (only if not finalized)
                    if not is_finalized:
                        if st.button("Update Points", key=f"update_pts_{daily_log['_id']}"):
                            dm.update_daily_log_points(daily_log['_id'], positive_points, negative_points)
                            st.success("Points updated!")
                            st.rerun()
                
                with col2:
                    st.subheader("Daily Summary")
                    # Compute daily total
                    computed_total = positive_points + negative_points
                    st.metric("Daily Total", computed_total)
                    
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
                
                with col3:
                    st.subheader("Daily Fulfillment")
                    
                    # Daily Fulfillment dropdown (only enabled after finalization)
                    current_fulfillment = daily_log.get('dailyFulfillment')
                    
                    if is_finalized:
                        fulfillment_options = ["-- Select --", "Yes", "No"]
                        if current_fulfillment == 'yes':
                            default_index = 1
                        elif current_fulfillment == 'no':
                            default_index = 2
                        else:
                            default_index = 0
                        
                        new_fulfillment = st.selectbox(
                            "Daily Fulfillment",
                            fulfillment_options,
                            index=default_index,
                            disabled=False,
                            key=f"fulfill_{daily_log['_id']}",
                            help="Yes = reduces remaining days by 1, No = flags for review"
                        )
                        
                        # Button to save fulfillment choice
                        if new_fulfillment != "-- Select --":
                            # Only enable button if value is different from current
                            is_changed = current_fulfillment != new_fulfillment.lower()
                            
                            if st.button("Save Fulfillment", key=f"save_fulfill_{daily_log['_id']}", disabled=not is_changed):
                                dm.set_daily_fulfillment(daily_log['_id'], new_fulfillment)
                                if new_fulfillment.lower() == 'yes':
                                    st.success("Fulfillment set to YES - Days reduced by 1")
                                else:
                                    st.warning("Fulfillment set to NO - Alert flagged for review")
                                st.rerun()
                            
                            if not is_changed and current_fulfillment:
                                st.info(f"Current: {current_fulfillment.upper()}")
                    else:
                        st.info("Finalize the log first to set Daily Fulfillment")

# Point Events Page
elif page == "Point Events":
    st.header("Point Event Tracking")
    
    # Check if we have a selected placement from quick actions
    if 'selected_placement_for_points' in st.session_state:
        placement_id = st.session_state.selected_placement_for_points
        student_id = st.session_state.selected_student_for_points
        
        # Clear the selection
        del st.session_state.selected_placement_for_points
        del st.session_state.selected_student_for_points
        
        st.info("Adding points for selected student...")
    else:
        # Regular placement selection
        active_placements = dm.get_active_placements_with_students()
        if not active_placements:
            st.warning("No active placements found.")
            placement_id = None
            student_id = None
        else:
            student_options = [f"{p['student']['firstName']} {p['student']['lastName']}" for p in active_placements]
            selected_student = st.selectbox("Select Student", student_options)
            
            if selected_student:
                placement = next(p for p in active_placements if f"{p['student']['firstName']} {p['student']['lastName']}" == selected_student)
                placement_id = placement['_id']
                student_id = placement['student']['_id']
            else:
                placement_id = None
                student_id = None
    
    if placement_id and student_id:
        tab1, tab2, tab3 = st.tabs(["Add Points", "Today's Events", "Point History"])
        
        with tab1:
            col1, col2 = st.columns(2)
            
            with col1:
                st.subheader("Positive Points")
                positive_menu = ps.get_positive_point_menu()
                
                for item in positive_menu:
                    # Check if this action can be performed
                    can_add, reason = ps.can_add_point_event(
                        placement_id, student_id, item['code'], date.today().isoformat()
                    )
                    
                    button_disabled = not can_add
                    help_text = reason if not can_add else None
                    
                    if st.button(
                        f"{item['label']} (+{item['value']})", 
                        key=f"pos_{item['code']}",
                        disabled=button_disabled,
                        help=help_text
                    ):
                        notes = st.text_input(f"Notes for {item['label']}", key=f"notes_pos_{item['code']}")
                        dm.add_point_event({
                            'studentId': student_id,
                            'placementId': placement_id,
                            'date': date.today().isoformat(),
                            'type': 'positive',
                            'code': item['code'],
                            'value': item['value'],
                            'notes': notes,
                            'createdBy': 'Staff',
                            'createdAt': datetime.now().isoformat()
                        })
                        st.success(f"Added {item['label']} (+{item['value']} points)")
                        st.rerun()
            
            with col2:
                st.subheader("Negative Points")
                negative_menu = ps.get_negative_point_menu()
                
                for item in negative_menu:
                    if st.button(f"{item['label']} ({item['value']})", key=f"neg_{item['code']}"):
                        notes = st.text_input(f"Notes for {item['label']}", key=f"notes_neg_{item['code']}")
                        dm.add_point_event({
                            'studentId': student_id,
                            'placementId': placement_id,
                            'date': date.today().isoformat(),
                            'type': 'negative',
                            'code': item['code'],
                            'value': item['value'],
                            'notes': notes,
                            'createdBy': 'Staff',
                            'createdAt': datetime.now().isoformat()
                        })
                        st.success(f"Added {item['label']} ({item['value']} points)")
                        st.rerun()
        
        with tab2:
            st.subheader("Today's Point Events")
            todays_events = dm.get_point_events_for_date(placement_id, date.today().isoformat())
            
            if todays_events:
                for event in todays_events:
                    point_item = ps.get_point_item_by_code(event['code'])
                    color = "green" if event['type'] == 'positive' else "red"
                    
                    with st.container():
                        st.markdown(f"**{point_item['label']}** - {event['value']} points")
                        if event.get('notes'):
                            st.write(f"Notes: {event['notes']}")
                        st.write(f"Added by: {event.get('createdBy', 'Unknown')} at {event.get('createdAt', 'Unknown')}")
                        st.divider()
            else:
                st.info("No point events recorded for today.")
        
        with tab3:
            st.subheader("Point Event History")
            all_events = dm.get_all_point_events_for_placement(placement_id)
            
            if all_events:
                df = pd.DataFrame(all_events)
                df['label'] = df['code'].apply(lambda x: ps.get_point_item_by_code(x)['label'])
                df_display = df[['date', 'type', 'label', 'value', 'notes', 'createdBy']].copy()
                df_display.columns = ['Date', 'Type', 'Action', 'Points', 'Notes', 'Created By']
                st.dataframe(df_display, use_container_width=True)
            else:
                st.info("No point events found for this placement.")

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
