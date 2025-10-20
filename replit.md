# Grotto Dashboard - Student Placement Management System

## Overview

The Grotto Dashboard is a student placement and behavior tracking system designed for educational institutions. It manages student placements in "The Grotto" (likely an alternative learning environment or intervention space), tracks daily attendance and behavior through a point-based system, manages assignments, and maintains communication logs. The system provides educators with tools to monitor student progress, document interventions, and track behavioral patterns during placement periods.

## User Preferences

Preferred communication style: Simple, everyday language.

## System Architecture

### Application Framework
**Technology**: Streamlit  
**Rationale**: Streamlit provides rapid development of data-centric web applications with minimal frontend code. It's ideal for internal educational tools where the focus is on functionality over complex UI interactions.

**Architecture Pattern**: Multi-page application with session state management
- Main navigation through sidebar with 7 core sections: Dashboard, Students, Placements, Daily Logs, Point Events, Assignments, and Notes
- Session state maintains persistent instances of DatabaseManager and PointSystem throughout user interactions
- Wide layout configuration optimized for data-rich dashboards

### Data Layer Migration
**Current State**: Dual implementation showing migration in progress
- Legacy: In-memory dictionary-based storage (`DataManager` class)
- Target: SQLAlchemy ORM with relational database (`DatabaseManager` class)

**Database Design Decisions**:
1. **ORM Choice**: SQLAlchemy with declarative base for type safety and query abstraction
2. **Schema Enforcement**: Enum types for constrained fields (StudentStatus, PlacementStatus, etc.) to prevent invalid states
3. **Soft Deletes**: Students use status='deleted' rather than hard deletion to preserve historical data
4. **JSON Storage**: Guardian contacts stored as JSON arrays for flexible contact information without separate tables

**Core Entities**:
- **Students**: Primary entity with soft-delete support, grade and homeroom tracking
- **Placements**: Time-bound assignments (1-15 days) linking students to intervention periods
- **DailyLogs**: Date-stamped records per placement for attendance/status tracking
- **PointEvents**: Behavioral tracking with positive/negative categorization
- **Assignments**: Task management with status workflow (assigned → in_progress → completed)
- **Notes**: Free-form documentation system

### Business Logic Layer

**Point System Architecture**:
- **Design Pattern**: Centralized configuration with business rules enforcement
- **Point Categories**: Dual menus for positive reinforcement and negative consequences
- **Constraint Types**:
  - `once_per_placement`: Limits like "Repair the harm" can only be earned once per placement period
  - `dailyCap`: Activities like "Read a chapter" capped at specific daily limits
  - Custom validation logic for complex business rules

**Point Item Structure**:
```python
{
  "label": "Human-readable description",
  "code": "UNIQUE_IDENTIFIER", 
  "value": integer_point_value,
  "limit": "constraint_type",  # optional
  "dailyCap": integer_max_per_day  # optional
}
```

**Separation of Concerns**:
- Point definitions isolated in `PointSystem` class
- Validation logic separated from UI layer
- Code-based lookups enable referential integrity

### Utility Layer

**Date Handling Strategy**:
- ISO format strings for storage/transport
- Date objects for calculations
- Formatted strings for display
- Defensive parsing with fallbacks for malformed data

**Key Utilities**:
- `calculate_days_remaining()`: Business logic for placement duration tracking
- `get_status_color()`: UI theming based on entity states
- Format helpers abstract presentation concerns from business logic

### UI Components

**Dashboard Pattern**: Card-based student overview
- Configurable columns (3 per row default)
- Active placements with student metadata
- Responsive grid layout through Streamlit columns

**Information Architecture**:
1. **Dashboard**: At-a-glance student status and active placements
2. **Students**: CRUD operations for student records
3. **Placements**: Intervention period management
4. **Daily Logs**: Attendance and daily status tracking
5. **Point Events**: Behavioral event recording
6. **Assignments**: Academic task management
7. **Notes**: General documentation and observations

## External Dependencies

### Core Framework
- **Streamlit**: Web application framework for data applications
  - Version not pinned in visible files
  - Handles routing, state management, and UI rendering

### Data Persistence
- **SQLAlchemy**: ORM and database toolkit
  - Declarative base for model definitions
  - Session management for transactions
  - Engine configuration suggests SQLite or PostgreSQL target
  - Note: Specific database driver not visible in provided files

### Data Processing
- **Pandas**: Data manipulation and analysis
  - Used for tabular data display
  - DataFrame integration with Streamlit components

### Python Standard Library
- **uuid**: Unique identifier generation for entities
- **datetime**: Temporal data handling (date, datetime, timedelta)
- **typing**: Type hints for code clarity and IDE support
- **enum**: Enumeration support for constrained value sets

### Database Schema Specifications
External schema definition file suggests possible integration with:
- Schema validation system (JSON Schema format)
- Index optimization for query performance on: homeroomTeacher, grade, studentId, status, startDate, placementId, date
- Email format validation for guardian contacts

**Integration Points**:
- Guardian email communications (format validation present, integration not implemented)
- Potential export/reporting systems (Pandas DataFrame support)
- Multi-user system (createdBy fields suggest user tracking)