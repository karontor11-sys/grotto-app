## Overview

The Grotto is a student placement and behavior tracking system for educational institutions. Its primary purpose is to manage student placements in alternative learning environments, track daily attendance and behavior using a point-based system, manage assignments, and maintain communication logs. The system aims to streamline administrative tasks, provide actionable insights into student well-being and academic performance, and assist educators in monitoring student progress and documenting interventions.

## User Preferences

Preferred communication style: Simple, everyday language.

## System Architecture

### Application Framework
The application is built with **Streamlit**, employing a multi-page architecture with robust session state management, optimized for data-rich dashboards.

### Data Layer
The system utilizes **SQLAlchemy ORM** with a relational database. Key design decisions include:
- **ORM Choice**: SQLAlchemy with declarative base for type safety and query abstraction.
- **Schema Enforcement**: Enum types for constrained fields (e.g., `StudentStatus`, `PlacementStatus`).
- **Soft Deletes**: Students are soft-deleted to preserve historical data.
- **JSON Storage**: Flexible storage for guardian contacts as JSON arrays.
- **Core Entities**: Students, Placements, Sessions (for partial-day tracking), DailyLogs, PointEvents, Assignments, and Notes.

### Business Logic Layer
A centralized **Point System Architecture** enforces business rules for behavioral tracking using configurable point categories with various constraint types. **Placement Duration Tracking** provides comprehensive duration information for all placement types, including total duration, current progress, days remaining, and active status, with integrated weekend logic.

### Utility Layer
A consistent date handling strategy uses ISO format for storage, date objects for calculations, and formatted strings for display. Utilities abstract presentation concerns and handle business logic like calculating remaining placement days and status-based UI theming.

### UI Components
The UI features the following navigation pages:
1. **Dashboard**: Main view with date selector, active placement cards, quick navigation buttons.
2. **Placements**: Create and manage placements with streamlined single-selector interface for three main placement types:
    - **In-School Suspension (ISS)**: Simplified placement with period-based tracking, two check-in options ("Full Day" and "Partial Day"). Supports editing existing ISS daily logs and recalculating totals.
    - **Lunch Detention**: Multi-day lunch detention placement.
    - **Class Period Referral**: Umbrella category with sub-types (Behavior, Cool-Down, Pre-Planned). Simplified creation forms and an "Add Periods" feature for same-day referrals.
3. **Completed Placements**: Archive of completed placements with school year hierarchy.
4. **Assignments**: Placeholder page for future development. Currently displays only header with no functionality.
5. **Notifications**: Provides real-time event alerts for placement events.

**Removed Pages** (Dec 2025): Notes, Reports & Analytics, and Import/Export pages were removed from navigation.

### System Design Choices
- **Simplified Single-Role System**: Only "Staff" role exists; Supervisor and Admin roles removed. No authentication required - app is open for viewing by all users.
- **Restricted Placement Creation**: Only four authorized staff members can create/edit placements: Aaron Toronto, Matthew Christie, Todd Foster, Chad Adamson. The "Add Staff" option appears in the dropdown as a non-functional placeholder for future expansion.
- **Staff List Constant**: `STAFF_OPTIONS` constant in app.py defines the authorized staff list plus placeholder.
- **Manual Student Entry**: Students are created manually during placement creation.
- **Weekend-Skipping Logic**: Weekends are automatically excluded from all duration calculations and displays for multi-day placements.
- **Partial-Day Session Tracking**: Tracks student activities during partial days and various session types, including session-scoped behavior tracking.
- **Session Attendance Tracking**: Real-time attendance management with Check-in, Check-out, and Mark No-show buttons.
- **Flexible Placement Completion Rules**: Configurable completion criteria with role-based "Complete Placement" button.
- **Conditional Form Fields**: Dynamic form fields based on placement type selection.
- **End-of-Day Processing**: Automated system processes pending dates, marking incomplete daily logs and handling 'no show'.
- **Retroactive Completion**: Staff can mark past incomplete records as complete.
- **Status Indicators**: Visual status badges using color coding for placement progress and lifecycle status.
- **ISS Period-Based Completion**: ISS placements track progress based on `iss_periods_served` out of `iss_total_required_periods`. Supports Day 1 partial auto-classification and future-dated ISS placements. `ISSSessionLog` model records session details.
- **Make-Up Session Support**: Allows for additional check-ins for students with remaining periods after scheduled ISS days.
- **ISS Make-Up Days Data Model**: Distinguishes between original scheduled ISS dates and make-up dates:
    - `original_day_count`: Immutable field storing the original "Day of Days" count (e.g., 3 for "3 days of ISS"). Never changes even when make-up days are added.
    - `is_makeup_session` (DailyLog): Boolean flag indicating if a day is a make-up session (`True`) or original session (`False`/`NULL`).
    - `makeup_days_used` (Placement): Count of completed make-up days (auto-calculated from make-up DailyLogs).
    - `makeup_periods_served` (Placement): Total periods served on make-up days (auto-calculated).
    - `makeup_note` (Placement): Completion note documenting make-up usage (e.g., "Make-up required: 2 additional days (15 periods) beyond original 3-day ISS assignment.").
    - `should_offer_makeup_days(placement)`: Helper function that returns `True` when all original dates are completed AND periods remaining > 0.
- **ISS Status Field**: Derived status (`Not Started`, `In Progress`, `Completed`) for ISS placements based on periods served.
- **Placement Progress Status**: A persistent `progress_status` field (`NOT_STARTED`, `IN_PROGRESS`, `COMPLETED`) tracks completion progress for all placement types, separate from lifecycle status, with automatic transitions.
- **Unified Attendance UI**: Consistent Check In + Absent controls across all expanded placement cards, triggering `progress_status` updates and UI refreshes.
- **Absent Logic**: Marking a day as Absent uses `day_type='absent'` in DailyLog. Absent does NOT change `progress_status` - it simply records the absence without affecting completion progress.
- **Check In / Absent Mutual Exclusivity**: Check In and Absent controls are mutually exclusive - when Absent is checked, Check In is disabled; when already checked in, Absent is disabled.
- **Multiday Absent Handling**: For multiday placements (ISS, Lunch Detention), absent days are skipped in day/period counting. The served counter resumes from where it left off when the student checks in again.
- **Day X of Y Display Logic**: Uses completion-based counting (days actually served) rather than calendar-based counting. Helper functions (`get_iss_days_served_info`, `get_lunch_detention_days_served_info`, `get_preplanned_days_served_info`) count only days where the student was present (checked_in=True, day_type!='absent') AND the day was completed (daily_fulfillment='yes'). Absent days freeze the counter; Day X advances only when days are actually served. Future-dated completions are excluded from the count for earlier dates.
- **Completed Placements Archive**: Master archive of all completed placements with:
    - **School Year Hierarchy**: Organized by School Year (Aug 1 – Jul 31) → Month → Day, with current school year expanded by default.
    - **School Year Helper Functions**: `get_school_year_for_date()`, `get_current_school_year()`, `group_placements_by_school_year_month_day()` in utils.py.
    - **Search/Filter**: Filter placements by student name only (case-insensitive, whitespace-normalized).
    - **Reports & Export Section**: Collapsible expander with:
        - Report scope selector (Day/Month/Year) with date inputs.
        - Filtered table view showing Student, Placement type, Served time, Reason, Start/End dates, Staff, Placement ID.
        - Export buttons: Download CSV, Download XLSX, Download Print-Friendly HTML.
    - **Collapsed Cards**: Expandable read-only detail views for each completed placement with type-specific details (ISS periods/make-up info, Lunch Detention served dates, CPR session attendance).
    - **Restore Function**: Admin button to restore completed placements back to active status.
- **Dashboard Navigation Buttons**: Quick navigation buttons ("Create New Placement" and "Completed Placements") at the top of the Dashboard for easy access to placement management.
- **Session State-Based Tab Navigation**: Placements page uses session state-controlled conditional rendering (replacing `st.tabs()`) to enable programmatic tab selection and direct navigation to specific sections.
- **Programmatic Navigation Handling**: Navigation handlers sync widget states (`sidebar_page_widget`, `sidebar_page_selection`, `placements_tab_radio`) to prevent widget key conflicts during programmatic navigation.

### Notification System
The Notifications page provides dynamically-generated alerts for placement events. Notifications are computed on-demand from database queries, with dismissed notifications stored persistently.

**Notification Types** (8 total):
1. **New Placement**: When a new placement is created.
2. **Placement Completed**: When a placement is marked complete.
3. **Daily Log Finalized**: When a daily log is marked as complete.
4. **Daily Log Pending**: Outstanding daily logs needing attention.
5. **Assignment Overdue**: Assignments past their due date.
6. **Placement Ending Soon**: Placements ending within the next few days.
7. **End-of-Day Incomplete**: Past incomplete records from EOD processing.
8. **Placement No-Show**: Unified detection across ALL placement types.

**Unified Placement No-Show Notifications**:
- `get_placement_no_show_notifications()` method detects no-shows for ISS, Lunch Detention, and Class Period Referral (including Behavior, Cool-Down, Pre-Planned subtypes).
- Uses two detection methods:
  - DailyLog-based: Checks `no_show=True` or `day_type='absent'` flags.
  - PartialDaySession-based: Checks for sessions with `status=SessionStatus.no_show`.
- Deduplication ensures no duplicate notifications for the same placement/date combination.
- Displays type-specific labels (e.g., "ISS", "Lunch Detention", "Pre-Planned Referral").

**Dismiss Functionality** (Dec 2025):
- Each notification has a unique `notification_id` (format: `type:record_id:date`).
- "Dismiss" button on each active notification removes it from the active list.
- Dismissed notifications are stored in `dismissed_notifications` table with:
  - `notification_id`: Unique identifier for the notification.
  - `notification_type`, `notification_title`, `notification_message`, `notification_severity`: Original notification data for historical display.
  - `original_timestamp`: When the notification was originally generated.
  - `dismissed_at`: When the user dismissed it.
- **Dismissed Tab**: Shows all dismissed notifications with original info and dismissal date.
- **Restore Button**: Allows restoring dismissed notifications back to active state.
- Active tabs (All, Warnings, Info, Success) show only non-dismissed notifications.

**Implementation Details**:
- `notifications.py` contains `NotificationManager` class with all notification fetching methods.
- `_generate_notification_id()` creates unique, consistent IDs for each notification.
- `get_all_notifications()` aggregates notifications from all 8 sources, filtering out dismissed.
- `get_notifications_by_severity()` groups active notifications into 'warning', 'info', 'success' categories.
- `get_dismissed_notifications()` retrieves dismissed notifications for the Dismissed tab.
- `dismiss_notification()` and `restore_notification()` manage dismissal state.
- `DismissedNotification` model in db_manager.py persists dismissed state.
- Sidebar badge shows warning count calculated from active (non-dismissed) notifications.

## External Dependencies

### Core Framework
- **Streamlit**: Primary web application framework.

### Data Persistence
- **SQLAlchemy**: ORM for database interaction.

### Data Processing
- **Pandas**: Utilized for data manipulation and tabular display.

### Python Standard Library
- **uuid**: For generating unique identifiers.
- **datetime**: For handling temporal data.
- **typing**: For type hinting.
- **enum**: For defining constrained value sets.