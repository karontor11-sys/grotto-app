# The Grotto - Student Placement Manager System

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
**Core Entities**: Students, Placements, Sessions (for partial-day tracking), DailyLogs, PointEvents, Assignments, and Notes.

### Business Logic Layer
A centralized **Point System Architecture** enforces business rules for behavioral tracking using configurable point categories with various constraint types (e.g., `once_per_placement`, `dailyCap`). Point definitions are isolated in a `PointSystem` class.
**Placement Duration Tracking**: A unified interface provides comprehensive duration information for all placement types (ISS, Lunch Detention, Class Referral, Cool-Down) including total duration, current progress ("Day X of Y"), days remaining, and active status, normalizing field names and handling weekend logic.

### Utility Layer
A consistent date handling strategy uses ISO format for storage, date objects for calculations, and formatted strings for display. Utilities abstract presentation concerns and handle business logic like calculating remaining placement days and status-based UI theming.

### UI Components
The UI features a **Dashboard** with:
- **Today's Sessions**: Horizontal chip strip for daily sessions.
- **Active Placements**: Card-based student overviews displaying only placements with status="active", sorted with a 5-level hierarchy: (1) placement type (ISS → Lunch Detention → Class Referral → Cool-Down), (2) within ISS, multi-day placements before single-day, (3) placements active today appear first, (4) earliest start date, (5) alphabetical by student name. The "active today" check uses weekend-skipping logic for multi-day placements. Each card displays:
  - **Placement Type Label**: Clear, descriptive labels showing placement type and date/period information (e.g., "ISS – Multi-Day (Nov 14–Nov 18)", "Lunch Detention – Single Day (Nov 14)", "Class Period Referral – Periods 2–4 (Nov 14)")
  - **Progress Indicator**: For multi-day placements only, displays current progress (e.g., "📅 Day 2 of 5") using school-day calculations
  - Student details (grade, homeroom teacher)
  - Today's points (positive/negative)
  - Quick action buttons (Daily Logs, Complete Placement)
  
  Completed placements appear only in the "Completed Placements" tab.
- **Placement Manager**: Manages placement lifecycles via "Create Placement" and "Completed Placements" tabs, allowing manual student entry during placement creation. Features a streamlined single-selector interface with 5 placement type options:
  - **In-School Suspension (ISS)**: Simplified ISS placement using start date + number of days model. Stores `iss_start_date`, `iss_total_days`, and `iss_remaining_days` (initialized equal to total days). No period/day conversion at placement creation.
  - **Lunch Detention**: Multi-day lunch detention placement
  - **Class Period Referral**: Single-period or multi-period classroom referral with period selection
  - **Cool-Down Referral**: Short-term cool-down placement with date and period selection
  - **Pre-Planned Referral**: Schedule-based referral with multiple date+period combinations
- **Daily Logs**: Interface for point tracking with "Session-Scoped View" (for specific sessions) and "Placement-Wide View" (default, for all placements).
- **Assignments**: Manages academic tasks.
- **Notes**: For general documentation.
- **Notifications**: Provides real-time event alerts.
- **Reports & Analytics**: Dashboards for placement statistics and behavior patterns.
- **Import/Export**: Facilitates bulk data operations via CSV.

### Key Features
- **Manual Student Entry**: Students are created manually during placement creation.
- **Weekend-Skipping Logic**: Weekends are automatically excluded from all duration calculations, session generation, and "Days Remaining" displays for multi-day placements.
- **Date Range Validation**: Multi-day ISS and Lunch Detention placements enforce end_date >= start_date with clear, formatted error messages. Validation order prevents confusing double errors by checking date validity before calculating weekdays. Weekend dates in ranges are allowed - only weekdays count toward days_assigned.
- **Partial-Day Session Tracking**: Tracks student activities during partial days, including various session types (periods, lunch, cool-down, referral).
- **Session-Scoped Behavior Tracking**: Point events can be associated with specific sessions for granular tracking, with behavior menus filtered by session type.
- **Session Attendance Tracking**: Real-time attendance management with Check-in, Check-out, and Mark No-show buttons, following a validated state machine.
- **Flexible Placement Completion Rules**: Configurable completion criteria for different placement types with role-based "Complete Placement" button.
- **Five Placement Types**: Single radio selector for choosing between In-School Suspension (ISS), Lunch Detention, Class Period Referral, Cool-Down Referral, and Pre-Planned Referral with conditional fields based on selection.
- **Simplified ISS Form**: The ISS placement form collects:
  - Student Information (name, grade, homeroom teacher)
  - Placement Details (reason)
  - Scheduling (start date and number of ISS days)
  - Created By selector
  The system initializes `iss_remaining_days` equal to `iss_total_days` for Dashboard tracking. No period/day conversion occurs at placement creation.
- **Conditional Form Fields**: Dynamic form fields that appear based on placement type selection - period selection for Class Referral, date and period selection for Cool-Down, no additional fields for Lunch Detention, and multi-date schedule builder for Pre-Planned Referral.
- **End-of-Day Processing**: Automated system that runs on app startup to process any pending dates, marking incomplete daily logs (where daily_fulfillment is not 'yes') as 'no' with alert_flag=True. Processing is tracked via EndOfDayProcessing table to ensure each date is processed exactly once.
- **Retroactive Completion**: Staff can mark incomplete records from past dates as complete using the "✓ Complete" button. The alert_flag is preserved for audit accountability - if alerts were sent for an incomplete record, that history is maintained even after the record is marked complete.
- **Status Indicators**: Visual status badges using color coding - Green (completed/daily_fulfillment='yes'), Yellow (in progress/today), Red (not completed/past date). Past dates marked incomplete by end-of-day processing display red until manually completed.

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