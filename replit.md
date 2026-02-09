## Overview

The Grotto is a student placement and behavior tracking system for educational institutions. Its primary purpose is to manage student placements in alternative learning environments, track daily attendance and behavior using a point-based system, manage assignments, and maintain communication logs. The system aims to streamline administrative tasks, provide actionable insights into student well-being and academic performance, and assist educators in monitoring student progress and documenting interventions.

## User Preferences

Preferred communication style: Simple, everyday language.

## System Architecture

### Application Framework
The application is built with **Streamlit**, employing a multi-page architecture with robust session state management, optimized for data-rich dashboards.

### Data Layer
The system utilizes **SQLAlchemy ORM** with a relational database. Key design decisions include: ORM Choice, Schema Enforcement, Soft Deletes, JSON Storage, and Core Entities (Students, Placements, Sessions, DailyLogs, PointEvents, Assignments, Notes).

### Business Logic Layer
A centralized **Point System Architecture** enforces business rules for behavioral tracking using configurable point categories. **Placement Duration Tracking** provides comprehensive duration information for all placement types, including total duration, current progress, days remaining, and active status, with integrated weekend logic.

### Utility Layer
A consistent date handling strategy uses ISO format for storage, date objects for calculations, and formatted strings for display. Utilities abstract presentation concerns and handle business logic like calculating remaining placement days and status-based UI theming.

### UI Components
The UI features the following navigation pages:
1. **Dashboard**: Main view with date selector, active placement cards, quick navigation buttons.
2. **Placements**: Create and manage three main placement types: In-School Suspension (ISS), Lunch Detention, and Class Period Referral (Behavior, Cool-Down, Pre-Planned).
3. **Completed Placements**: Archive of completed placements with school year hierarchy, search/filter, and export functionality.
4. **Assignments**: Placeholder page.
5. **Notifications**: Provides real-time event alerts for placement events with dismissal and restoration capabilities.

### System Design Choices
- **Simplified Single-Role System**: Only "Staff" role exists; no authentication required.
- **Restricted Placement Creation**: Only four authorized staff members can create/edit placements.
- **Manual Student Entry**: Students are created manually during placement creation.
- **Weekend-Skipping Logic**: Weekends are automatically excluded from duration calculations for multi-day placements.
- **Partial-Day Session Tracking**: Tracks student activities during partial days and various session types, including session-scoped behavior tracking.
- **Session Attendance Tracking**: Real-time attendance management with Check-in, Check-out, and Mark No-show buttons.
- **Flexible Placement Completion Rules**: Configurable completion criteria.
- **Conditional Form Fields**: Dynamic form fields based on placement type selection.
- **End-of-Day Processing**: Automated system processes pending dates, marking incomplete daily logs and handling 'no show'.
- **Retroactive Completion**: Staff can mark past incomplete records as complete.
- **Status Indicators**: Visual status badges using color coding for placement progress and lifecycle status, with "Red overrides Yellow at the day level" logic for day-level status.
- **ISS Period-Based Completion**: ISS placements track progress based on periods served. Supports Day 1 partial auto-classification and future-dated ISS placements.
- **Make-Up Session Support**: Allows for additional check-ins for students with remaining periods after scheduled ISS days, tracked via `is_makeup_session` and `makeup_days_used`.
- **ISS Status Field**: Derived status (`Not Started`, `In Progress`, `Completed`) for ISS placements.
- **Placement Progress Status**: A persistent `progress_status` field tracks completion progress for all placement types.
- **Unified Attendance UI**: Consistent Check In + Absent controls across all expanded placement cards.
- **ISS Workflow Order**: ISS cards prioritize Absent checkbox and Check In button, with Day Type selector appearing after check-in.
- **Absent Logic**: Marking a day as Absent records `day_type='absent'` without changing `progress_status`.
- **Check In / Absent Mutual Exclusivity**: Controls are mutually exclusive.
- **Notes Auto-Save**: All notes fields auto-save to the database.
- **Multiday Absent Handling**: Absent days are skipped in day/period counting for multiday placements; the counter resumes from where it left off.
- **Day X of Y Display Logic**: Uses completion-based counting (days actually served) rather than calendar-based counting.
- **Completed Placements Archive**: Master archive with school year hierarchy, search/filter by student name, and export options (CSV, XLSX, HTML). Allows restoring completed placements.
- **Dashboard Navigation Buttons**: Quick navigation buttons ("Create New Placement" and "Completed Placements") for easy access.
- **Session State-Based Tab Navigation**: Placements page uses session state for programmatic tab selection.
- **Programmatic Navigation Handling**: Navigation handlers sync widget states to prevent conflicts.
- **School Year Filtering**: Placements have a `school_year_start` column (Integer, indexed). Dashboard queries filter by operating school year so only current-year placements appear. Auto-set on placement creation from start_date via `get_school_year_for_date`.

### Notification System
The Notifications page provides dynamically-generated alerts for placement events. Notifications are computed on-demand, with dismissed notifications stored persistently. There are 8 types of notifications, including a unified "Placement No-Show" detection across all placement types. Dismissal functionality allows users to remove notifications from the active list, which are then viewable in a "Dismissed" tab with restoration capability.

## External Dependencies

### Core Framework
- **Streamlit**: Primary web application framework.

### Data Persistence
- **SQLAlchemy**: ORM for database interaction.

### Data Processing
- **Pandas**: Utilized for data manipulation and tabular display.