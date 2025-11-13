# The Grotto - Student Placement Manager System

## Overview

The Grotto is a student placement and behavior tracking system for educational institutions, managing student placements in alternative learning environments, tracking daily attendance and behavior via a point-based system, managing assignments, and maintaining communication logs. It helps educators monitor student progress, document interventions, and analyze behavioral patterns during placement periods. The system aims to streamline administrative tasks and provide actionable insights into student well-being and academic performance.

## User Preferences

Preferred communication style: Simple, everyday language.

## System Architecture

### Application Framework
The application is built with **Streamlit**, leveraging its rapid development capabilities for data-centric web applications. It uses a multi-page architecture with robust session state management to maintain persistent data and application states across user interactions. The layout is optimized for data-rich dashboards.

### Data Layer
The system is migrating from an in-memory dictionary-based storage to a **SQLAlchemy ORM** with a relational database. Key design decisions include:
- **ORM Choice**: SQLAlchemy with declarative base for type safety and query abstraction.
- **Schema Enforcement**: Enum types for constrained fields (e.g., `StudentStatus`, `PlacementStatus`).
- **Soft Deletes**: Students are soft-deleted to preserve historical data.
- **JSON Storage**: Flexible storage for guardian contacts as JSON arrays.

**Core Entities**: Students, Placements, Sessions (for partial-day tracking), DailyLogs, PointEvents, Assignments, and Notes.

### Business Logic Layer
A centralized **Point System Architecture** enforces business rules for behavioral tracking. It uses configurable point categories for positive and negative behaviors with various constraint types (e.g., `once_per_placement`, `dailyCap`). Point definitions are isolated in a `PointSystem` class for clear separation of concerns.

### Utility Layer
A consistent date handling strategy uses ISO format for storage, date objects for calculations, and formatted strings for display. Utilities abstract presentation concerns and handle business logic like calculating remaining placement days and status-based UI theming.

### UI Components
The UI features a **Dashboard** with:
- **Today's Sessions**: Horizontal chip strip showing all sessions scheduled for today with format "Student Name · Scope" (e.g., "Isaac T · P2", "Jesse M · Lunch"). Clicking a chip navigates to Daily Logs for that placement. Shows "No sessions today" when empty.
- **Active Placements**: Card-based student overviews with configurable columns and quick access to placement creation.
- **Placement Manager**: Manages placement lifecycles through two tabs: "Create Placement" (manual student entry only - students are created during placement creation) and "Completed Placements" (for historical archives and restoration).
- **Daily Logs**: A comprehensive interface for point tracking with two viewing modes:
  - **Session-Scoped View**: When navigating from a Today's Sessions chip, displays a focused view for that specific session with header showing student name, type badge, and scope. All behavior events are tagged with session_id and filtered to show only events for that session.
  - **Placement-Wide View**: Default view showing all placements for a selected date with behavior events not tied to specific sessions (session_id is NULL).
- **Assignments**: Manages academic tasks.
- **Notes**: For general documentation.
- **Notifications**: Provides real-time event alerts with robust error handling.
- **Reports & Analytics**: Offers comprehensive dashboards for placement statistics and behavior patterns.
- **Import/Export**: Facilitates bulk data operations via CSV.

### Key Features
- **Manual Student Entry**: All students are created manually during placement creation. No connection to school enrollment systems - each placement creates a new student record with basic information (name, grade, homeroom teacher).
- **Partial-Day Session Tracking**: Infrastructure for tracking student activities during partial days, including various session types (periods, lunch, cool-down, referral) and statuses.
- **Session-Scoped Behavior Tracking**: Point events can be associated with specific sessions via session_id, enabling granular tracking of student behavior during individual periods, lunch, cool-down, or referral sessions. The Daily Logs interface automatically switches to session-scoped mode when navigating from Today's Sessions chips.
- **Behavior Masking by Session Type**: Behavior menus are filtered based on session type to keep options relevant. ISS Full Day shows all behaviors, Periods/Referral hide optional items like "Read a chapter", Lunch shows simplified menus (3 positives, 4 negatives), and Cool-down shows minimal options (1 positive, 0 negatives). Mutual exclusion rules and caps still enforce across all sessions of the same placement.
- **Session Attendance Tracking**: Real-time attendance management with Check-in, Check-out, and Mark No-show buttons in the session-scoped Daily Log view. Status transitions follow a validated state machine (scheduled → in_progress → fulfilled, or scheduled → no_show). No-show actions create supervisor alerts with a visible alert banner and set an alert flag on the session record. Session state persists across page reruns for seamless attendance workflows.
- **Flexible Placement Completion Rules**: Configurable completion criteria for different placement types with role-based Complete Placement button:
  - **ISS Days** (default for ISS placements): Completes when days_completed >= days_assigned (days_remaining = 0)
  - **All Sessions Fulfilled** (default for partial placements): Requires all sessions to have status = fulfilled
  - **Minimum Sessions**: Completes when fulfilled_sessions >= min_sessions_required
  - **Date Range End**: Auto-completes when current date exceeds placement end_date
  - Complete button only visible to Supervisor/Admin roles, enabled when criteria met, shows helpful status captions
- **Placement Type Toggle**: Allows selection between "ISS Days" and "Partial Day" placements, with dynamic UI adjustments.
- **Partial Day Subtypes**: Four session type collection interfaces:
  - **Periods**: Multi-period sessions with optional repeat capability, validates at least one period selected
  - **Lunch Detention**: True date range (start/end dates) with weekday selection and lunch block assignment, validates end >= start
  - **Cool-down**: Same-day time-bounded sessions with time range and duration calculation, validates end > start
  - **Single-period Referral**: Individual period referrals with teacher and reason tracking (Note: conditional "specify" field for "Other" reason has known Streamlit rendering limitation - field persists when switching reasons; will be addressed in session creation phase)

## Recent Changes (November 13, 2025)
- **Placement Type Field**: Added placement_type field to capture the category of each placement (ISS, LUNCH_DETENTION, CLASS_REFERRAL, COOL_DOWN). This field appears as a radio button selector on both ISS Days and Partial Day placement creation forms with options: "In-School Suspension (ISS)", "Lunch Detention", "Class Period Referral", and "Cool-Down Referral". The value is stored with every placement record for archival purposes.
- **Lunch Detention Support**: Modified ISS Days form to support both ISS and Lunch Detention placement types with Start/End date fields. Lunch detention sessions are generated using `generate_lunch_detention_sessions` method, which creates SessionType.lunch sessions in Cafeteria location. Date-range-based session generation ensures sessions align with user-selected dates. Weekday-aware calculation counts only Monday-Friday for days_assigned.
- **Class Period Referral Support**: Implemented full Class Period Referral workflow in ISS Days tab. When selected, displays dedicated form with Date, Start Period (P1-P8), and End Period (P1-P8) fields. Supports both single-period (start=end) and multi-period (end>start) referrals. Added start_period and end_period fields to Placement schema for archival. Creates single PartialDaySession with type=SessionType.referral containing periods array. Session generator `generate_class_referral_session` creates period list from start to end (e.g., P2-P5 creates [2,3,4,5]). Validation ensures end_period >= start_period. Database migration support added via `_run_migrations()` method.
- **Cool-Down Referral Support**: Implemented full Cool-Down Referral workflow in ISS Days tab. When selected, displays dedicated form with Date, Start Period (P1-P8), and End Period (P1-P8) fields. Supports both short cool-downs (start=end, single period) and longer cool-downs (end>start, multi-period). Uses same start_period and end_period database fields as Class Referrals. Creates single PartialDaySession with type=SessionType.cool_down containing periods array. Session generator `generate_cooldown_session` creates period list from start to end with location "Cool-Down Room". Form widgets use unique "cd_" prefixed keys to prevent conflicts. Added comprehensive error handling with try-except blocks that display detailed error messages and stack traces. Success message "✓ Cool-Down created for {student name}" confirms successful creation. Validation ensures end_period >= start_period.

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