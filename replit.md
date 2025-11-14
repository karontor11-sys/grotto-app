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
- **Active Placements**: Card-based student overviews.
- **Placement Manager**: Manages placement lifecycles via "Create Placement" and "Completed Placements" tabs, allowing manual student entry during placement creation.
- **Daily Logs**: Interface for point tracking with "Session-Scoped View" (for specific sessions) and "Placement-Wide View" (default, for all placements).
- **Assignments**: Manages academic tasks.
- **Notes**: For general documentation.
- **Notifications**: Provides real-time event alerts.
- **Reports & Analytics**: Dashboards for placement statistics and behavior patterns.
- **Import/Export**: Facilitates bulk data operations via CSV.

### Key Features
- **Manual Student Entry**: Students are created manually during placement creation.
- **Weekend-Skipping Logic**: Weekends are automatically excluded from all duration calculations, session generation, and "Days Remaining" displays for multi-day placements.
- **Partial-Day Session Tracking**: Tracks student activities during partial days, including various session types (periods, lunch, cool-down, referral).
- **Session-Scoped Behavior Tracking**: Point events can be associated with specific sessions for granular tracking, with behavior menus filtered by session type.
- **Session Attendance Tracking**: Real-time attendance management with Check-in, Check-out, and Mark No-show buttons, following a validated state machine.
- **Flexible Placement Completion Rules**: Configurable completion criteria for different placement types with role-based "Complete Placement" button.
- **Placement Type Toggle**: Allows selection between "ISS Days" and "Partial Day" placements, with dynamic UI adjustments.
- **Partial Day Subtypes**: Four session type collection interfaces: Periods, Lunch Detention, Cool-down, and Single-period Referral.

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