import streamlit as st
import pandas as pd
from datetime import datetime, date, timedelta
from data_manager import DataManager
from point_system import PointSystem
from utils import format_date, calculate_days_remaining, get_status_color

# Initialize session state
if 'data_manager' not in st.session_state:
    st.session_state.data_manager = DataManager()
if 'point_system' not in st.session_state:
    st.session_state.point_system = PointSystem()

dm = st.session_state.data_manager
ps = st.session_state.point_system

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
    ["Dashboard", "Students", "Placements", "Daily Logs", "Point Events", "Assignments", "Notes"]
)

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
                    days_remaining = calculate_days_remaining(placement['startDate'], placement['daysAssigned'])
                    todays_points = dm.get_todays_points(placement['_id'])
                    cumulative_total = dm.get_cumulative_total(placement['_id'])
                    
                    # Student card
                    with st.container():
                        st.subheader(f"{student['firstName']} {student['lastName']}")
                        st.write(f"**Grade:** {student['grade']}")
                        st.write(f"**Homeroom Teacher:** {student['homeroomTeacher']}")
                        st.write(f"**Days Remaining:** {days_remaining}")
                        
                        # Points badge
                        if todays_points >= 0:
                            st.success(f"Today's Points: +{todays_points}")
                        else:
                            st.error(f"Today's Points: {todays_points}")
                        
                        st.info(f"Cumulative Total: {cumulative_total}")
                        
                        # Quick actions
                        if st.button(f"Add Points - {student['firstName']}", key=f"quick_points_{placement['_id']}"):
                            st.session_state.selected_placement_for_points = placement['_id']
                            st.session_state.selected_student_for_points = student['_id']
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
                        days_remaining = calculate_days_remaining(placement['startDate'], placement['daysAssigned'])
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
            
            with st.expander(f"{student['firstName']} {student['lastName']}", expanded=True):
                col1, col2, col3 = st.columns(3)
                
                with col1:
                    st.metric("Positive Points", daily_log['positiveTotal'])
                    st.metric("Negative Points", daily_log['negativeTotal'])
                
                with col2:
                    st.metric("Daily Total", daily_log['dailyTotal'])
                    readiness = daily_log.get('readiness', 'continue')
                    st.write(f"**Readiness:** {readiness}")
                
                with col3:
                    if not daily_log.get('finalizedBy'):
                        readiness_options = ["continue", "ready"]
                        new_readiness = st.selectbox(
                            "Set Readiness", 
                            readiness_options, 
                            index=readiness_options.index(readiness),
                            key=f"readiness_{daily_log['_id']}"
                        )
                        
                        if st.button(f"Finalize Log", key=f"finalize_{daily_log['_id']}"):
                            dm.finalize_daily_log(daily_log['_id'], new_readiness, "Staff")
                            st.success("Daily log finalized!")
                            st.rerun()
                    else:
                        st.success(f"Finalized by: {daily_log['finalizedBy']}")
                        st.write(f"At: {daily_log.get('finalizedAt', 'Unknown')}")

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
                    st.write(f"**Share with Parent:** {'Yes' if note.get('shareWithParent', False) else 'No'}")
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
                share_with_parent = st.checkbox("Share with Parent")
                
                if st.form_submit_button("Add Note"):
                    if selected_student and author_id and text:
                        student_data = next(s for s in students if f"{s['firstName']} {s['lastName']}" == selected_student)
                        
                        note_data = {
                            'studentId': student_data['_id'],
                            'authorId': author_id,
                            'text': text,
                            'shareWithParent': share_with_parent,
                            'createdAt': datetime.now().isoformat()
                        }
                        dm.add_note(note_data)
                        st.success("Note added successfully!")
                        st.rerun()
                    else:
                        st.error("Please fill in all required fields marked with *")

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
