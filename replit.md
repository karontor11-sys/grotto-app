## Overview

The Grotto is a student placement and behavior tracking system for educational institutions. It manages student placements in alternative learning environments, tracks daily attendance and behavior via a point-based system, manages assignments, and maintains communication logs. The system aims to streamline administrative tasks, provide actionable insights into student well-being and academic performance, and help educators monitor student progress and document interventions.

## User Preferences

Preferred communication style: Simple, everyday language.

## System Architecture

### Application Framework
The application is built with **Streamlit**, utilizing a multi-page architecture with robust session state management. The layout is optimized for data-rich dashboards.

### Data Layer
The system uses **SQLAlchemy ORM** with a relational database. Key design decisions include:
- **ORM Choice**: SQLAlchemy with declarative base for type safety and query abstraction.
- **Schema Enforcement**: Enum types for constrained fields (e.g., `StudentStatus`, `PlacementStatus`).
- **Soft Deletes**: Students are soft-deleted to preserve historical data.
- **JSON Storage**: Flexible storage for guardian contacts as JSON arrays.
- **Core Entities**: Students, Placements, Sessions (for partial-day tracking), DailyLogs, PointEvents, Assignments, and Notes.

### Business Logic Layer
A centralized **Point System Architecture** enforces business rules for behavioral tracking using configurable point categories with various constraint types (e.g., `once_per_placement`, `dailyCap`). Point definitions are isolated in a `PointSystem` class.
**Placement Duration Tracking**: A unified interface provides comprehensive duration information for all placement types (ISS, Lunch Detention, Class Referral, Cool-Down) including total duration, current progress ("Day X of Y"), days remaining, and active status, normalizing field names and handling weekend logic.

### Utility Layer
A consistent date handling strategy uses ISO format for storage, date objects for calculations, and formatted strings for display. Utilities abstract presentation concerns and handle business logic like calculating remaining placement days and status-based UI theming.

### UI Components
The UI features a **Dashboard** with:
- **Today's Sessions**: Horizontal chip strip for daily sessions.
- **Active Placements**: Card-based student overviews displaying only active placements, sorted by a 5-level hierarchy (placement type, multi-day vs. single-day, active today, start date, student name). Cards show placement type, progress indicator (for multi-day), student details, today's points, and quick action buttons. The "Class Period Referral" section unifies all referral subtypes (Behavior, Cool-Down, Pre-Planned) under one display, using a single rendering function and subtype-specific completion buttons and "No Show" functionality for Pre-Planned referrals.
- **Placement Manager**: Manages placement lifecycles via "Create Placement" and "Completed Placements" tabs, allowing manual student entry. Features a streamlined single-selector interface with three main placement types:
    - **In-School Suspension (ISS)**: Simplified placement using start date + number of days model, including period-based tracking with `iss_days_assigned`, `iss_total_required_periods`, and `iss_periods_served`. ISS cards display period-based progress and two check-in options ("Full Day" and "Partial Day").
    - **Lunch Detention**: Multi-day lunch detention placement.
    - **Class Period Referral**: Umbrella category with three sub-types selected via dropdown: Behavior Referral (single-day), Cool-Down Referral (short-term), and Pre-Planned Referral (schedule-based). Referral sub-types are tracked via a `referral_subtype` field.
- **Daily Logs**: Interface for point tracking with "Session-Scoped View" and "Placement-Wide View".
- **Assignments**: Manages academic tasks.
- **Notes**: For general documentation.
- **Notifications**: Provides real-time event alerts.
- **Reports & Analytics**: Dashboards for placement statistics and behavior patterns.
- **Import/Export**: Facilitates bulk data operations via CSV.

### Key Features
- **Manual Student Entry**: Students are created manually during placement creation.
- **Weekend-Skipping Logic**: Weekends are automatically excluded from all duration calculations, session generation, and "Days Remaining" displays for multi-day placements.
- **Date Range Validation**: Enforces `end_date >= start_date` for multi-day placements.
- **Partial-Day Session Tracking**: Tracks student activities during partial days and various session types.
- **Session-Scoped Behavior Tracking**: Point events can be associated with specific sessions.
- **Session Attendance Tracking**: Real-time attendance management with Check-in, Check-out, and Mark No-show buttons.
- **Flexible Placement Completion Rules**: Configurable completion criteria for different placement types with role-based "Complete Placement" button.
- **Conditional Form Fields**: Dynamic form fields appear based on placement type selection (e.g., period selection for Class Referral, multi-date schedule builder for Pre-Planned Referral).
- **End-of-Day Processing**: Automated system processes pending dates, marking incomplete daily logs and handling 'no show' for pre-planned referrals.
- **Retroactive Completion**: Staff can mark past incomplete records as complete, preserving `alert_flag` for audit.
- **Status Indicators**: Visual status badges using color coding (Green for completed, Yellow for in progress, Red for not completed/past date).

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

## Recent Changes

### ISS Start Date Logic & Terminology Update (Dec 03, 2025)

**Terminology Change:**
- All references to "sentence" now use "Session" (e.g., "4-day ISS Session")

**Start Date Logic for ISS Placements:**
- Future-dated ISS placements show as locked cards on the Dashboard with "First Check-In Date" labels
- Three placement states: active (start date is today/past), scheduled (start date is future), completed
- PlacementStatus enum updated to include 'scheduled' value
- Automatic transition: scheduled → active when start date arrives

**Database Changes:**
- Added 'scheduled' to PlacementStatus enum via PostgreSQL ALTER TYPE
- Placement creation logic: status = 'active' if start_date <= today, else 'scheduled'

**New/Updated Methods:**
- `get_scheduled_iss_placements()`: Returns all scheduled ISS placements with future start dates
- `activate_scheduled_placements()`: Runs on app startup, transitions scheduled → active when start date arrives
- `add_placement()`: Sets initial status based on start date comparison with today

**Dashboard Changes:**
- ISS section now displays both active sessions and scheduled (locked) placements
- Locked cards show: 🔒 icon, "(Scheduled)" label, grayed appearance, disabled Check In button
- Info box displays: "📅 First Check-In Date: {formatted_date}"
- Caption: "This ISS Session has not started yet. Check-in will be available on the start date."

### ISS Session Log Storage & History View (Dec 02, 2025)

**New Database Model - ISSSessionLog:**
- Records each completed session within an ISS placement
- Fields: session_date, session_type (Full Day/Partial Day), start_period, end_period, periods_credited
- Points tracking: points_target, points_earned
- Completion tracking: completion_method (Complete/Override), override_reason, completed_by

**Placement Enhancement:**
- Added `iss_label` field to Placement model
- Stores official label "{issDaysAssigned}-day ISS Session for {Student Name}" when Session completes

**Complete Methods Updated:**
- `complete_iss_full_day_session()`: Creates ISSSessionLog entry, sets iss_label on completion
- `complete_iss_partial_day_session()`: Creates ISSSessionLog entry, sets iss_label on completion

**New Retrieval Methods:**
- `get_iss_session_logs(placement_id)`: Returns all session logs for a placement
- `get_completed_iss_placements(student_id)`: Returns completed ISS placements with session logs

**ISS History View (Placements > ISS History tab):**
- Shows all completed ISS sentences with expandable details
- Header: "{X}-day ISS for Student Name (Completed)"
- Session list: Date, Full/Partial Day, periods credited, Complete vs Override, points, notes
- Search by student name
- Override reasons and notes displayed for each session