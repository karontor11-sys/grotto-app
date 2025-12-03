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
- **Today's Sessions**: Horizontal chip strip.
- **Active Placements**: Card-based student overviews for active placements, sorted by a 5-level hierarchy. Cards display placement type, progress indicator, student details, today's points, and quick action buttons. The "Class Period Referral" section unifies all referral subtypes under one display.
- **Placement Manager**: Manages placement lifecycles via "Create Placement" and "Completed Placements" tabs, allowing manual student entry and featuring a streamlined single-selector interface for three main placement types:
    - **In-School Suspension (ISS)**: Simplified placement with period-based tracking, displaying progress and two check-in options ("Full Day" and "Partial Day").
    - **Lunch Detention**: Multi-day lunch detention placement.
    - **Class Period Referral**: Umbrella category with sub-types (Behavior, Cool-Down, Pre-Planned) selected via dropdown.
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