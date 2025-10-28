# The Grotto - Student Placement Manager System

## Overview

The Grotto is a student placement and behavior tracking system designed for educational institutions. It manages student placements in "The Grotto" (an alternative learning environment or intervention space), tracks daily attendance and behavior through a point-based system, manages assignments, and maintains communication logs. The system provides educators with tools to monitor student progress, document interventions, and track behavioral patterns during placement periods.

## User Preferences

Preferred communication style: Simple, everyday language.

## System Architecture

### Application Framework
**Technology**: Streamlit  
**Rationale**: Streamlit provides rapid development of data-centric web applications with minimal frontend code. It's ideal for internal educational tools where the focus is on functionality over complex UI interactions.

**Architecture Pattern**: Multi-page application with session state management
- Main navigation through sidebar with 9 core sections: Dashboard, Placements, Daily Logs, Assignments, Notes, Notifications, Reports & Analytics, and Import/Export
- Session state maintains persistent instances of DatabaseManager, PointSystem, AnalyticsEngine, ImportExportManager, and NotificationManager throughout user interactions
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
- **Students**: Primary entity with soft-delete support, grade and homeroom tracking, guardian contacts
- **Placements**: Time-bound assignments (1-15 days) linking students to intervention periods
- **DailyLogs**: Date-stamped records per placement for attendance/status tracking, with readiness levels
- **PointEvents**: Behavioral tracking with positive/negative categorization
- **Assignments**: Task management with status workflow (assigned → in_progress → completed)
- **Notes**: Free-form documentation system (share_with_parent field exists but UI removed)

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
- `calculate_days_remaining()`: Business logic for placement duration tracking (now accounts for days_completed from daily fulfillment)
- `get_status_color()`: UI theming based on entity states
- Format helpers abstract presentation concerns from business logic

### UI Components

**Dashboard Pattern**: Card-based student overview
- Configurable columns (3 per row default)
- Active placements with student metadata
- Responsive grid layout through Streamlit columns

**Information Architecture**:
1. **Dashboard**: At-a-glance student status and active placements with point totals and accurate days remaining (accounting for daily fulfillment). Includes "Create New Placement" button for quick access to placement creation form
2. **Placement Manager**: Two-tab system for placement lifecycle management
   - **Create Placement**: Combined student and placement creation form with dropdown to select existing student or add new student inline
   - **Completed Placements**: Historical archive with search by Name/Reason, displays total points earned, allows restoration to active
3. **Daily Logs**: Comprehensive point tracking interface with dropdown-based behavior selection, two-column layout showing Points controls and Today's Behaviors list, finalize workflow
4. **Assignments**: Academic task management with due dates and status
5. **Notes**: General documentation and observations
6. **Notifications**: Real-time event notifications for placements, daily logs, assignments (with graceful error handling for database connection issues)
7. **Reports & Analytics**: Comprehensive analytics dashboard with placement statistics, behavior patterns, and student performance metrics
8. **Import/Export**: Bulk data import/export functionality for students and system data via CSV

### Recent Changes (October 2025)

**Daily Logs Redesign (October 26-28, 2025)**:
- Complete rebuild of Daily Logs page with dropdown-based behavior selection system
- Replaced number inputs with dropdown menus listing specific positive and negative behaviors
- **Positive Behaviors**: Repair the harm (written/verbal), Complete an assignment, Read a chapter, Meet with counselor, Restorative discussion, Helpful task, Grotto clean & damage free, Other
- **Negative Behaviors**: Behavior redirection, Unauthorized computer use, Refusing to do classwork, Sleeping/head on desk, Leaving without permission, Disrespectful behavior/language, Disruptive/loud behavior, Other
- **Behavior Limiting System**:
  - "Repair the harm" options: Once per placement, mutually exclusive (using one blocks the other)
  - "Read a chapter": Maximum 4 times total per placement
  - Unavailable behaviors shown with 🔒 icon directly in dropdown (no separate explanatory text)
- **Two-Column Layout**:
  - **Left Column (Points)**: Add Positive Behavior dropdown, Add Negative Behavior dropdown, Daily Total section with point value and Finalize Log button
  - **Right Column (Today's Behaviors)**: List of all behaviors added for the day with ✕ remove buttons
- **Interface**: Select behavior from dropdown → Click "➕ Add Positive/Negative" → Behavior appears in "Today's Behaviors" list on right
- Can add same behavior multiple times (e.g., "Read a chapter" 4 times on same day)
- Daily Total auto-calculates from all behaviors in today's list
- Daily Fulfillment feature temporarily removed from Daily Logs (location to be determined later)
- Database schema changes:
  - Added `days_completed` INTEGER column to placements table (tracks fulfilled days)
  - Added `daily_fulfillment` VARCHAR column to daily_logs table (stores 'yes' or 'no')
  - Added `alert_flag` BOOLEAN column to daily_logs table (flags logs requiring review)
- Updated `calculate_days_remaining()` utility to subtract days_completed from days_assigned
- Dashboard and Placements pages display accurate days remaining based on daily fulfillment

**Completed Placements Feature (October 27, 2025)**:
- Added Completed Placements tab to Placement Manager showing archived ISS sentences
- Tab structure: Create Placement → Completed Placements (Active Placements tab removed)
- Tab badges display counts (e.g., "Completed Placements (9)")
- Completed Placements displays: Name, Start Date, Reason, Number of Days, End Date, Total Points Earned
- Search functionality by student Name and placement Reason
- Restore to Active feature allows supervisors to reactivate mistakenly completed placements
- Database schema changes:
  - Added `end_date` DATE column to placements table (set when status changes to completed)
  - Updated Placement ORM model to include end_date attribute
- New methods: `get_completed_placements_with_students()`, `restore_placement_to_active()`
- Complete Placement button location to be determined (temporarily removed from UI)

**Combined Placement and Student Creation (October 27, 2025)**:
- Merged Student Management functionality into Placement Manager
- Create Placement form now includes student selection dropdown with "Add New Student" option
- When adding new student: First Name, Last Name, Grade, Homeroom Teacher fields are editable
- When selecting existing student: Student information auto-fills as disabled fields
- Single form captures both student and placement details: Name, Grade, Homeroom Teacher, Reason, Start Date, Number of Days, Created By
- After successful placement creation, user is automatically redirected to Dashboard
- Success message appears on Dashboard confirming placement creation
- New placement immediately visible in Active Placements section
- Eliminates need for separate Student Management page
- Database schema and student-related methods in DatabaseManager remain intact

**Guardian Contacts Removal (October 26, 2025)**:
- Removed Guardian contacts fields from Student Management Add Student form (page now removed entirely)
- Database field `guardian_contacts` retained for schema compatibility but set to empty array for new students

**Point Events Page Removal (October 28, 2025)**:
- Removed Point Events page entirely from navigation and application
- All point tracking functionality consolidated into Daily Logs page with dropdown-based behavior selection
- PointEvents database table and backend methods retained for data integrity
- Daily Logs now serves as the single interface for all behavioral tracking

**Parent Portal Removal**:
- Removed Parent Portal page from navigation and application
- Removed "Share with Parent" checkbox from Notes interface
- Database field `share_with_parent` retained for schema compatibility but forced to false on new notes
- Legacy notes with share_with_parent=true remain in database but have no UI exposure

**Database Error Handling**:
- Added comprehensive error handling to NotificationManager to prevent SSL connection errors from crashing the application
- All notification query methods now catch exceptions and return empty lists gracefully
- Error logging added via print statements for debugging (future enhancement: structured logging)

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