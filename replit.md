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
The UI features a **Dashboard** with card-based student overviews, configurable columns, and quick access to placement creation.
- **Placement Manager**: Manages placement lifecycles through two tabs: "Create Placement" (combining student and placement creation) and "Completed Placements" (for historical archives and restoration).
- **Daily Logs**: A comprehensive interface for point tracking using dropdown-based behavior selection, displaying daily totals, and allowing log finalization.
- **Assignments**: Manages academic tasks.
- **Notes**: For general documentation.
- **Notifications**: Provides real-time event alerts with robust error handling.
- **Reports & Analytics**: Offers comprehensive dashboards for placement statistics and behavior patterns.
- **Import/Export**: Facilitates bulk data operations via CSV.

### Key Features
- **Combined Placement and Student Creation**: Streamlined form for creating new students and placements simultaneously.
- **Partial-Day Session Tracking**: Infrastructure for tracking student activities during partial days, including various session types (periods, lunch, cool-down, referral) and statuses.
- **Placement Type Toggle**: Allows selection between "ISS Days" and "Partial Day" placements, with dynamic UI adjustments.
- **Partial Day Subtypes**: Four session type collection interfaces:
  - **Periods**: Multi-period sessions with optional repeat capability, validates at least one period selected
  - **Lunch Detention**: True date range (start/end dates) with weekday selection and lunch block assignment, validates end >= start
  - **Cool-down**: Same-day time-bounded sessions with time range and duration calculation, validates end > start
  - **Single-period Referral**: Individual period referrals with teacher and reason tracking (Note: conditional "specify" field for "Other" reason has known Streamlit rendering limitation - field persists when switching reasons; will be addressed in session creation phase)

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