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
A centralized **Point System Architecture** enforces business rules for behavioral tracking using configurable point categories with various constraint types. Point definitions are isolated in a `PointSystem` class. **Placement Duration Tracking** provides comprehensive duration information for all placement types, including total duration, current progress, days remaining, and active status, with integrated weekend logic.

### Utility Layer
A consistent date handling strategy uses ISO format for storage, date objects for calculations, and formatted strings for display. Utilities abstract presentation concerns and handle business logic like calculating remaining placement days and status-based UI theming.

### UI Components
The UI features a **Dashboard** with:
- **Date Selector**: Allows viewing placements for any date (past, present, or future). Defaults to today. Past dates show historical activity including completed placements; future dates show scheduled placements.
- **Today's Sessions**: Horizontal chip strip.
- **Active Placements**: Card-based student overviews for active placements, sorted by a 5-level hierarchy. Cards display placement type, progress indicator, student details, today's points, and quick action buttons. The "Class Period Referral" section unifies all referral subtypes under one display.
- **Placement Manager**: Manages placement lifecycles via "Create Placement" and "Completed Placements" tabs, allowing manual student entry and featuring a streamlined single-selector interface for three main placement types:
    - **In-School Suspension (ISS)**: Simplified placement with period-based tracking, displaying progress and two check-in options ("Full Day" and "Partial Day").
    - **Lunch Detention**: Multi-day lunch detention placement.
    - **Class Period Referral**: Umbrella category with sub-types (Behavior, Cool-Down, Pre-Planned) selected via dropdown. **Simplified Creation Forms**: Behavior and Cool-Down referrals use a streamlined 2-field scheduling interface (Date + single Period), while Pre-Planned retains its full multi-day/multi-period schedule builder. **Add Periods Feature**: Behavior and Cool-Down referral cards on the Dashboard include an "Add Periods" control allowing staff to add additional periods to same-day referrals via a form-based multiselect showing only available (unassigned) periods.
- **Daily Logs**: Interface for point tracking with "Session-Scoped View" and "Placement-Wide View".
- **Assignments**: Manages academic tasks.
- **Notes**: For general documentation.
- **Notifications**: Provides real-time event alerts.
- **Reports & Analytics**: Dashboards for placement statistics and behavior patterns.
- **Import/Export**: Facilitates bulk data operations via CSV.

### Key Features
- **Manual Student Entry**: Students are created manually during placement creation.
- **Weekend-Skipping Logic**: Weekends are automatically excluded from all duration calculations and displays for multi-day placements.
- **Date Range Validation**: Enforces `end_date >= start_date` for multi-day placements.
- **Partial-Day Session Tracking**: Tracks student activities during partial days and various session types.
- **Session-Scoped Behavior Tracking**: Point events can be associated with specific sessions.
- **Session Attendance Tracking**: Real-time attendance management with Check-in, Check-out, and Mark No-show buttons.
- **Flexible Placement Completion Rules**: Configurable completion criteria for different placement types with role-based "Complete Placement" button.
- **Conditional Form Fields**: Dynamic form fields appear based on placement type selection.
- **End-of-Day Processing**: Automated system processes pending dates, marking incomplete daily logs and handling 'no show' for pre-planned referrals.
- **Retroactive Completion**: Staff can mark past incomplete records as complete, preserving `alert_flag` for audit.
- **Status Indicators**: Visual status badges using color coding.
- **ISS Periods-Based Completion Logic**: ISS placements now use `iss_periods_served` out of `iss_total_required_periods` for progress tracking.
- **Partial-Day Period Selection**: For ISS partial days, users can select start and end periods, with required points automatically calculated.
- **Day 1 Partial Auto-Classification**: Multi-day ISS sessions starting with a partial day check-in on Day 1 are automatically classified as "flexible session mode."
- **ISS Start Date Logic & Terminology**: Future-dated ISS placements are shown as locked cards with a "First Check-In Date," automatically transitioning to active on the start date.
- **ISS Session Log Storage & History View**: A new `ISSSessionLog` model records details for each completed session within an ISS placement, providing a historical view.
- **Make-Up Session Support**: When students complete their scheduled ISS days but still have periods remaining (`needs_makeup` status), staff can perform additional check-ins via "Make-Up – Full Day" or "Make-Up – Partial Day" buttons. Make-up sessions are tracked with `is_makeup_session` and `periods_added` fields in daily logs, and recorded in ISSSessionLogs with session types like "Make-Up Full Day" or "Make-Up Partial Day". Placements auto-complete when total periods served meets or exceeds the required periods.

## Recent Changes (December 2025)

### ISS Dashboard Controls (Full Day vs Partial Day UI)
- Added ISS session summary display: `ISS: Required X periods | Served Y | Remaining Z`
- Added Day Type selector with "Full Day" and "Partial Day" options for active ISS placements
- **Full Day UI**: Hides period controls, shows points field with 10-point requirement
- **Partial Day UI**: Shows Start/End Period dropdowns (1-10) with validation
  - Error if End Period < Start Period
  - Points requirement adjusts based on periods selected (1 point per period)
- Updated "Complete" button to "Complete Day" with day type settings stored in session state
- Complete Day button respects period validation and disables if errors present

### ISS Period Tracking & Auto-Complete (December 2025)
- Added `complete_iss_day` method in DatabaseManager as the main entry point for "Complete Day"
- Method computes `servedPeriodsForThisDay` based on day type:
  - Full Day = 10 periods
  - Partial Day = endPeriod - startPeriod + 1
- Updates placement's `iss_periods_served` field with cumulative total
- Calculates `periodsRemaining = max(requiredTotalPeriods - servedPeriodsTotal, 0)`
- Auto-completes ISS placement when `servedPeriodsTotal >= requiredTotalPeriods`
- Dashboard refreshes with updated totals after completion
- Override button also uses `complete_iss_day` with `is_override=True`
- Retroactive completion buttons (for no-show sessions) also integrated

### ISS Period-Based Model Enhancement
- Added `PERIODS_PER_FULL_DAY = 10` constant for ISS period calculations
- Enhanced placement dictionary output with computed fields:
  - `periodsPerFullDay`: Constant value (10)
  - `numDays`: Alias for days assigned
  - `requiredTotalPeriods`: Total periods required (days × 10)
  - `servedPeriodsTotal`: Total periods served
  - `periodsRemaining`: Dynamically computed (required - served)
- Added debug logging for ISS model verification (temporary)
- Backward compatibility migration populates new fields for older placements

### Navigation System Fix
- Fixed Streamlit sidebar navigation synchronization issue
- Navigation now uses `navigate_to_dashboard` session state flag that's processed before sidebar widget renders
- All placement creation handlers (ISS, Lunch Detention, Behavior Referral, Cool-Down Referral, Pre-Planned Referral) redirect to Dashboard with success message after creation

### ISS Day Editing Support (December 2025)
- **Preload Existing Values**: When rendering an ISS card for a date with an existing entry, the Day Type radio and Start/End Period dropdowns are preloaded with stored values from the daily log
- **Edit Handling**: Clicking "Complete Day" on an existing entry updates (overwrites) the daily log with new values instead of creating a duplicate
- **Recalculate Totals on Edit**: After any edit, `iss_periods_served` is recalculated by summing `periods_added` from ALL daily logs for the placement, preventing double-counting
- **Completed Placement Guardrails**: Placements with status "completed" are rendered as read-only with a clear "ISS Session Complete" message, preventing further edits
- **Full ↔ Partial Conversions**: Supports changing a day from Full Day to Partial Day (or vice versa) with automatic period recalculation

### ISS Status Field (December 2025)
- **Derived Status**: Added `issStatus` computed field to ISS placements based on periods served:
  - **Not Started**: `iss_periods_served == 0`
  - **In Progress**: `iss_periods_served > 0` AND `iss_periods_served < requiredTotalPeriods`
  - **Completed**: `iss_periods_served >= requiredTotalPeriods` OR placement status is completed
- Field is available in placement dictionary as `issStatus` for UI display

### ISS Status Badge on Dashboard (December 2025)
- **Calendar-Based View**: ISS placements now show on all dates within their scheduled date range, including completed placements
- **Status Badge**: Each ISS card expander shows a color-coded status badge:
  - ⚪ Not Started (gray) - No periods served yet
  - 🔵 In Progress (blue) - Some periods served, not complete
  - ✅ Completed (green) - All required periods served
- **Scheduled Placements**: Future placements show with 🔒 lock icon and ⚪ Not Started badge

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