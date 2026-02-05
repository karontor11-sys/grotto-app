import os
import uuid
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional, Any
from sqlalchemy import create_engine, Column, String, Integer, Boolean, DateTime, Date, JSON, Text, Enum as SQLEnum, UniqueConstraint, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
import enum
from utils import add_business_days, get_school_days, get_school_year_for_date, central_today, central_now_naive, central_now

Base = declarative_base()

# ISS Period-based tracking constant
PERIODS_PER_FULL_DAY = 10  # Standard 10-period school day for ISS calculations

# Define enums
class StudentStatus(enum.Enum):
    active = "active"
    deleted = "deleted"

class PlacementStatus(enum.Enum):
    active = "active"
    scheduled = "scheduled"
    completed = "completed"
    needs_makeup = "needs_makeup"  # Session complete but periods short, awaiting make-up

class PlacementProgressStatus(enum.Enum):
    """Progress status for all placement types - tracks overall completion progress"""
    NOT_STARTED = "NOT_STARTED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"

class PlacementType(enum.Enum):
    iss_full_day = "iss_full_day"
    partial = "partial"

class PlacementCategory(enum.Enum):
    ISS = "ISS"
    LUNCH_DETENTION = "LUNCH_DETENTION"
    CLASS_REFERRAL = "CLASS_REFERRAL"
    COOL_DOWN = "COOL_DOWN"
    PRE_PLANNED_REFERRAL = "PRE_PLANNED_REFERRAL"

class AssignmentStatus(enum.Enum):
    assigned = "assigned"
    in_progress = "in_progress"
    completed = "completed"

class PointEventType(enum.Enum):
    positive = "positive"
    negative = "negative"

class Readiness(enum.Enum):
    ready = "ready"
    continue_status = "continue"

class SessionType(enum.Enum):
    iss_full_day = "iss_full_day"
    periods = "periods"
    lunch = "lunch"
    cool_down = "cool_down"
    referral = "referral"

class SessionStatus(enum.Enum):
    scheduled = "scheduled"
    in_progress = "in_progress"
    fulfilled = "fulfilled"
    no_show = "no_show"
    canceled = "canceled"

class CompletionRule(enum.Enum):
    iss_days = "iss_days"  # Traditional ISS: completes when days_remaining = 0
    all_sessions_fulfilled = "all_sessions_fulfilled"  # All sessions must be fulfilled
    min_sessions_n = "min_sessions_n"  # Minimum number of sessions fulfilled
    date_range_end = "date_range_end"  # Auto-complete when end date passes

# Define models
class Student(Base):
    __tablename__ = 'students'
    
    id = Column(String, primary_key=True)
    first_name = Column(String, nullable=False)
    last_name = Column(String, nullable=False)
    grade = Column(String, nullable=False)
    homeroom_teacher = Column(String, nullable=False)
    guardian_contacts = Column(JSON, default=list)
    status = Column(SQLEnum(StudentStatus), default=StudentStatus.active)

class Placement(Base):
    __tablename__ = 'placements'
    
    id = Column(String, primary_key=True)
    student_id = Column(String, nullable=False)
    homeroom_teacher_id = Column(String)
    reason = Column(Text, nullable=False)
    type = Column(SQLEnum(PlacementType), default=PlacementType.iss_full_day)  # iss_full_day or partial
    placement_type = Column(SQLEnum(PlacementCategory), default=PlacementCategory.ISS)  # ISS, LUNCH_DETENTION, CLASS_REFERRAL, COOL_DOWN
    completion_rule = Column(SQLEnum(CompletionRule), default=CompletionRule.iss_days)  # How placement completes
    min_sessions_required = Column(Integer, nullable=True)  # For min_sessions_n rule
    days_assigned = Column(Integer, nullable=False)
    days_completed = Column(Integer, default=0)  # Days earned through Daily Fulfillment = Yes
    total_iss_periods = Column(Integer, nullable=True)  # DEPRECATED: For ISS: Total periods assigned (days_assigned × 10)
    iss_start_date = Column(Date, nullable=True)  # For ISS: Start date of ISS placement
    iss_total_days = Column(Integer, nullable=True)  # For ISS: Total ISS days assigned
    iss_remaining_days = Column(Integer, nullable=True)  # For ISS: Remaining ISS days (updated by Dashboard)
    # Period-based ISS tracking fields
    iss_days_assigned = Column(Integer, nullable=True)  # For ISS: Number of ISS days entered on form
    iss_total_required_periods = Column(Integer, nullable=True)  # For ISS: Calculated as iss_days_assigned * 10
    iss_periods_served = Column(Integer, default=0)  # For ISS: Running counter of periods served
    original_day_count = Column(Integer, nullable=True)  # For ISS: Original "Day of Days" count - NEVER changes, even when make-up days are added
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=True)  # Set when placement is completed
    start_period = Column(Integer, nullable=True)  # For CLASS_REFERRAL: starting period (e.g., 1 for P1)
    end_period = Column(Integer, nullable=True)  # For CLASS_REFERRAL: ending period (e.g., 3 for P3)
    scheduled_iss_dates = Column(JSON, default=list)  # Array of scheduled ISS dates (ISO format strings) for full-day ISS
    scheduled_iss_sessions = Column(JSON, default=list)  # Array of scheduled ISS sessions with date, periods, and session type
    served_dates = Column(JSON, default=list)  # Array of dates when student was present (ISO format strings)
    scheduled_lunch_dates = Column(JSON, default=list)  # Array of scheduled Lunch Detention dates (ISO format strings)
    referral_subtype = Column(String, nullable=True)  # For CLASS_REFERRAL: 'behavior', 'cool_down', or 'pre_planned'
    status = Column(SQLEnum(PlacementStatus), default=PlacementStatus.active)
    progress_status = Column(SQLEnum(PlacementProgressStatus), default=PlacementProgressStatus.NOT_STARTED)  # Progress tracking for all placement types
    created_by = Column(String)
    created_at = Column(DateTime, default=datetime.now)
    iss_label = Column(String, nullable=True)  # Official label: "{issDaysAssigned}-day ISS Session for {Student Name}"
    is_flexible_session_mode = Column(Boolean, default=False)  # True when multi-day ISS Session started with partial day on Day 1
    # Early closure tracking
    closed_early = Column(Boolean, default=False)  # True if Session was closed early with periods remaining
    early_closure_note = Column(Text, nullable=True)  # Required note when closing early
    periods_waived = Column(Integer, default=0)  # Number of periods waived when closing early
    # Make-up tracking fields
    makeup_days_used = Column(Integer, default=0)  # Number of make-up days completed
    makeup_periods_served = Column(Integer, default=0)  # Total periods served on make-up days
    makeup_note = Column(Text, nullable=True)  # Note about make-up days used (e.g., "Make-up required: 1 additional day (4 periods)")

class DailyLog(Base):
    __tablename__ = 'daily_logs'
    
    id = Column(String, primary_key=True)
    placement_id = Column(String, nullable=False)
    session_id = Column(String, nullable=True)  # NULL for traditional ISS day logs
    date = Column(Date, nullable=False)
    positive_total = Column(Integer, default=0)
    negative_total = Column(Integer, default=0)
    daily_total = Column(Integer, default=0)
    readiness = Column(String, default='continue')
    daily_fulfillment = Column(String)  # 'yes' or 'no', null until set
    alert_flag = Column(Boolean, default=False)
    finalized_by = Column(String)
    finalized_at = Column(DateTime)
    notes = Column(Text)
    # New fields for simplified ISS model
    day_type = Column(String, nullable=True)  # 'full', 'partial', or 'absent'
    periods_covered = Column(JSON, default=list)  # Array of period numbers covered for partial days
    override_used = Column(Boolean, default=False)  # True if "Call It Good" override was used
    override_comment = Column(Text, nullable=True)  # Required comment when override is used
    # Period-based fields for partial day ISS
    start_period = Column(Integer, nullable=True)  # For partial day: starting period (1-10)
    end_period = Column(Integer, nullable=True)  # For partial day: ending period (1-10)
    required_points = Column(Integer, nullable=True)  # Points required for this session (= periods covered)
    # Check-in workflow fields
    checked_in = Column(Boolean, default=False)  # True when student is checked in for the day
    checked_in_at = Column(DateTime, nullable=True)  # Timestamp when check-in occurred
    # No Show fields (for Pre-Planned Referral)
    no_show = Column(Boolean, default=False)  # True if student was marked as No Show
    no_show_note = Column(Text, nullable=True)  # Brief note explaining the No Show (e.g., "Sick today")
    # Make-up session fields
    is_makeup_session = Column(Boolean, default=False)  # True if this is a make-up session
    periods_added = Column(Integer, nullable=True)  # Number of periods added when session is completed
    
    __table_args__ = (UniqueConstraint('placement_id', 'date', name='uix_placement_date'),)

class PointEvent(Base):
    __tablename__ = 'point_events'
    
    id = Column(String, primary_key=True)
    student_id = Column(String, nullable=False)
    placement_id = Column(String, nullable=False)
    session_id = Column(String, nullable=True)  # NULL for traditional ISS behavior events
    date = Column(Date, nullable=False)
    type = Column(SQLEnum(PointEventType), nullable=False)
    code = Column(String, nullable=False)
    value = Column(Integer, nullable=False)
    notes = Column(Text)
    created_by = Column(String)
    created_at = Column(DateTime, default=datetime.now)

class Assignment(Base):
    __tablename__ = 'assignments'
    
    id = Column(String, primary_key=True)
    student_id = Column(String, nullable=False)
    teacher_id = Column(String)
    placement_id = Column(String)
    title = Column(String, nullable=False)
    link_or_file_ref = Column(String)
    due_date = Column(Date)
    status = Column(SQLEnum(AssignmentStatus), default=AssignmentStatus.assigned)
    notes = Column(Text)

class Note(Base):
    __tablename__ = 'notes'
    
    id = Column(String, primary_key=True)
    student_id = Column(String, nullable=False)
    author_id = Column(String, nullable=False)
    text = Column(Text, nullable=False)
    share_with_parent = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.now)

class PartialDaySession(Base):
    __tablename__ = 'sessions'
    
    id = Column(String, primary_key=True)
    placement_id = Column(String, nullable=False)
    date = Column(Date, nullable=False)
    type = Column(SQLEnum(SessionType), nullable=False)
    periods = Column(JSON, default=list)  # List of period numbers, e.g. [1, 2, 3]
    time_start = Column(String)  # HH:MM format
    time_end = Column(String)  # HH:MM format
    location = Column(String)
    status = Column(SQLEnum(SessionStatus), default=SessionStatus.scheduled)
    alert_flag = Column(Boolean, default=False)  # Supervisor alert for no-show
    alert_sent = Column(Boolean, default=False)  # Whether midnight alert notification was sent
    alert_timestamp = Column(DateTime, nullable=True)  # When midnight alert was triggered
    notes = Column(Text)

class EndOfDayProcessing(Base):
    __tablename__ = 'end_of_day_processing'
    
    id = Column(String, primary_key=True)
    processing_date = Column(Date, nullable=False, unique=True)  # The date that was processed
    processed_at = Column(DateTime, default=datetime.now)  # When the processing occurred
    incomplete_count = Column(Integer, default=0)  # Number of incomplete records found
    notification_sent = Column(Boolean, default=False)  # Whether notifications were sent

class ISSSessionLog(Base):
    """Log of each completed ISS session within a placement."""
    __tablename__ = 'iss_session_logs'
    
    id = Column(String, primary_key=True)
    placement_id = Column(String, nullable=False)  # Reference to the ISS placement
    session_date = Column(Date, nullable=False)  # Date of the session
    session_type = Column(String, nullable=False)  # 'Full Day' or 'Partial Day'
    start_period = Column(Integer, nullable=True)  # For partial days: starting period (1-10)
    end_period = Column(Integer, nullable=True)  # For partial days: ending period (1-10)
    periods_covered = Column(JSON, nullable=True)  # Array of period numbers attended (for non-contiguous selections)
    periods_credited = Column(Integer, nullable=False)  # Number of periods credited (10 for full, calculated for partial)
    points_target = Column(Integer, nullable=True)  # Points required for this session
    points_earned = Column(Integer, nullable=True)  # Actual points earned
    completion_method = Column(String, nullable=False)  # 'Complete' or 'Override'
    notes = Column(Text, nullable=True)  # General notes
    override_reason = Column(Text, nullable=True)  # Required when completion_method is 'Override'
    completed_by = Column(String, nullable=True)  # Who completed the session
    created_at = Column(DateTime, default=datetime.now)

class DismissedNotification(Base):
    """Track dismissed notifications to filter them from the active list."""
    __tablename__ = 'dismissed_notifications'
    
    id = Column(String, primary_key=True)  # UUID
    notification_id = Column(String, nullable=False, unique=True, index=True)  # Unique notification identifier (type:record_id:date)
    notification_type = Column(String, nullable=False)  # e.g., 'placement_created', 'placement_no_show'
    notification_title = Column(String, nullable=True)  # Original title for display in dismissed list
    notification_message = Column(Text, nullable=True)  # Original message for display
    notification_severity = Column(String, nullable=True)  # warning, info, success
    original_timestamp = Column(DateTime, nullable=True)  # When the original notification was generated
    dismissed_at = Column(DateTime, default=datetime.now, nullable=False)  # When user dismissed it
    dismissed_by = Column(String, nullable=True)  # Who dismissed (optional for future use)


class SchoolYearConfig(Base):
    """Per-school-year configuration flags (e.g., calendar finalized)."""
    __tablename__ = 'school_year_config'

    id = Column(String, primary_key=True)
    start_year = Column(Integer, nullable=False)
    end_year = Column(Integer, nullable=False)
    calendar_finalized = Column(Boolean, default=False)
    finalized_at = Column(DateTime, nullable=True)

    __table_args__ = (UniqueConstraint('start_year', 'end_year', name='uix_school_year_config'),)


class SchoolClosure(Base):
    """No-school day blocks (single day or ranges) that should be skipped like weekends."""
    __tablename__ = 'school_closures'

    id = Column(String, primary_key=True)
    start_year = Column(Integer, nullable=False)
    end_year = Column(Integer, nullable=False)

    title = Column(String, nullable=False)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)

    created_at = Column(DateTime, default=datetime.now)

    __table_args__ = (UniqueConstraint('start_year', 'end_year', 'title', 'start_date', 'end_date', name='uix_school_closure'),)


class DatabaseManager:
    def __init__(self):
        """Initialize the database manager."""
        database_url = os.environ.get('DATABASE_URL')
        if not database_url:
            # Fallback for environments where DATABASE_URL might not be set
            import streamlit as st
            st.error("⚠️ DATABASE_URL environment variable is not set. Please configure the database.")
            st.stop()
        
        try:
            # Configure connection pooling with SSL timeout handling
            self.engine = create_engine(
                database_url,
                pool_pre_ping=True,  # Verify connections before using them
                pool_recycle=3600,   # Recycle connections after 1 hour
                pool_size=5,          # Connection pool size
                max_overflow=10,      # Max overflow connections
                connect_args={
                    "connect_timeout": 10,
                    "keepalives": 1,
                    "keepalives_idle": 30,
                    "keepalives_interval": 10,
                    "keepalives_count": 5
                }
            )
            Base.metadata.create_all(self.engine)
            self.SessionLocal = sessionmaker(bind=self.engine)
            
            # Run migrations to add any missing columns
            self._run_migrations()
        except Exception as e:
            import streamlit as st
            st.error(f"❌ Database connection failed: {str(e)}")
            st.info("Please ensure DATABASE_URL is properly configured and the database is accessible.")
            st.stop()
    
    def _run_migrations(self):
        """Run database migrations to add missing columns."""
        session = self.get_session()
        try:
            # Check which columns exist in placements table
            result = session.execute("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name = 'placements' 
                AND column_name IN ('start_period', 'end_period', 'scheduled_iss_dates', 'scheduled_iss_sessions', 'served_dates', 'scheduled_lunch_dates', 'total_iss_periods', 'iss_start_date', 'iss_total_days', 'iss_remaining_days', 'iss_days_assigned', 'iss_total_required_periods', 'iss_periods_served', 'iss_label', 'is_flexible_session_mode', 'closed_early', 'early_closure_note', 'periods_waived', 'original_day_count', 'makeup_days_used', 'makeup_periods_served', 'makeup_note')
            """)
            existing_columns = {row[0] for row in result}
            
            # Check which columns exist in daily_logs table
            result = session.execute("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name = 'daily_logs' 
                AND column_name IN ('day_type', 'periods_covered', 'override_used', 'override_comment', 'start_period', 'end_period', 'required_points')
            """)
            existing_daily_log_columns = {row[0] for row in result}
            
            # Add start_period column if it doesn't exist
            if 'start_period' not in existing_columns:
                session.execute("ALTER TABLE placements ADD COLUMN start_period INTEGER")
                session.commit()
            
            # Add end_period column if it doesn't exist
            if 'end_period' not in existing_columns:
                session.execute("ALTER TABLE placements ADD COLUMN end_period INTEGER")
                session.commit()
            
            # Add scheduled_iss_dates column if it doesn't exist
            if 'scheduled_iss_dates' not in existing_columns:
                session.execute("ALTER TABLE placements ADD COLUMN scheduled_iss_dates JSON DEFAULT '[]'::json")
                session.commit()
            
            # Add served_dates column if it doesn't exist
            if 'served_dates' not in existing_columns:
                session.execute("ALTER TABLE placements ADD COLUMN served_dates JSON DEFAULT '[]'::json")
                session.commit()
            
            # Add scheduled_lunch_dates column for Lunch Detention
            if 'scheduled_lunch_dates' not in existing_columns:
                session.execute("ALTER TABLE placements ADD COLUMN scheduled_lunch_dates JSON DEFAULT '[]'::json")
                session.commit()
            
            # Add total_iss_periods column if it doesn't exist
            if 'total_iss_periods' not in existing_columns:
                session.execute("ALTER TABLE placements ADD COLUMN total_iss_periods INTEGER")
                session.commit()
            
            # Add scheduled_iss_sessions column if it doesn't exist
            if 'scheduled_iss_sessions' not in existing_columns:
                session.execute("ALTER TABLE placements ADD COLUMN scheduled_iss_sessions JSON DEFAULT '[]'::json")
                session.commit()
            
            # Add new ISS columns
            if 'iss_start_date' not in existing_columns:
                session.execute("ALTER TABLE placements ADD COLUMN iss_start_date DATE")
                session.commit()
            
            if 'iss_total_days' not in existing_columns:
                session.execute("ALTER TABLE placements ADD COLUMN iss_total_days INTEGER")
                session.commit()
            
            if 'iss_remaining_days' not in existing_columns:
                session.execute("ALTER TABLE placements ADD COLUMN iss_remaining_days INTEGER")
                session.commit()
            
            # Add new period-based ISS tracking columns
            if 'iss_days_assigned' not in existing_columns:
                session.execute("ALTER TABLE placements ADD COLUMN iss_days_assigned INTEGER")
                session.commit()
            
            if 'iss_total_required_periods' not in existing_columns:
                session.execute("ALTER TABLE placements ADD COLUMN iss_total_required_periods INTEGER")
                session.commit()
            
            if 'iss_periods_served' not in existing_columns:
                session.execute("ALTER TABLE placements ADD COLUMN iss_periods_served INTEGER DEFAULT 0")
                session.commit()
            
            if 'iss_label' not in existing_columns:
                session.execute("ALTER TABLE placements ADD COLUMN iss_label VARCHAR")
                session.commit()
            
            # Add is_flexible_session_mode column for Day 1 partial auto-classification
            if 'is_flexible_session_mode' not in existing_columns:
                session.execute("ALTER TABLE placements ADD COLUMN is_flexible_session_mode BOOLEAN DEFAULT FALSE")
                session.commit()
            
            # Add early closure tracking columns
            if 'closed_early' not in existing_columns:
                session.execute("ALTER TABLE placements ADD COLUMN closed_early BOOLEAN DEFAULT FALSE")
                session.commit()
            
            if 'early_closure_note' not in existing_columns:
                session.execute("ALTER TABLE placements ADD COLUMN early_closure_note TEXT")
                session.commit()
            
            if 'periods_waived' not in existing_columns:
                session.execute("ALTER TABLE placements ADD COLUMN periods_waived INTEGER DEFAULT 0")
                session.commit()
            
            # Add original_day_count column for ISS Make-Up Days tracking
            if 'original_day_count' not in existing_columns:
                session.execute("ALTER TABLE placements ADD COLUMN original_day_count INTEGER")
                session.commit()
                # Backfill from iss_days_assigned for existing placements
                session.execute("""
                    UPDATE placements 
                    SET original_day_count = iss_days_assigned 
                    WHERE original_day_count IS NULL AND iss_days_assigned IS NOT NULL
                """)
                session.commit()
            
            # Add make-up tracking columns
            if 'makeup_days_used' not in existing_columns:
                session.execute("ALTER TABLE placements ADD COLUMN makeup_days_used INTEGER DEFAULT 0")
                session.commit()
            
            if 'makeup_periods_served' not in existing_columns:
                session.execute("ALTER TABLE placements ADD COLUMN makeup_periods_served INTEGER DEFAULT 0")
                session.commit()
            
            if 'makeup_note' not in existing_columns:
                session.execute("ALTER TABLE placements ADD COLUMN makeup_note TEXT")
                session.commit()
            
            # Migrate existing ISS placements to populate new period-based fields
            session.execute("""
                UPDATE placements 
                SET iss_days_assigned = COALESCE(iss_total_days, days_assigned),
                    iss_total_required_periods = COALESCE(iss_total_days, days_assigned) * 10,
                    iss_periods_served = COALESCE(iss_periods_served, 0)
                WHERE placement_type = 'ISS' 
                AND iss_days_assigned IS NULL
            """)
            session.commit()
            
            # Add new daily_logs columns for simplified ISS model
            if 'day_type' not in existing_daily_log_columns:
                session.execute("ALTER TABLE daily_logs ADD COLUMN day_type VARCHAR")
                session.commit()
            
            if 'periods_covered' not in existing_daily_log_columns:
                session.execute("ALTER TABLE daily_logs ADD COLUMN periods_covered JSON DEFAULT '[]'::json")
                session.commit()
            
            if 'override_used' not in existing_daily_log_columns:
                session.execute("ALTER TABLE daily_logs ADD COLUMN override_used BOOLEAN DEFAULT FALSE")
                session.commit()
            
            if 'override_comment' not in existing_daily_log_columns:
                session.execute("ALTER TABLE daily_logs ADD COLUMN override_comment TEXT")
                session.commit()
            
            # Add period-based fields for partial day ISS
            if 'start_period' not in existing_daily_log_columns:
                session.execute("ALTER TABLE daily_logs ADD COLUMN start_period INTEGER")
                session.commit()
            
            if 'end_period' not in existing_daily_log_columns:
                session.execute("ALTER TABLE daily_logs ADD COLUMN end_period INTEGER")
                session.commit()
            
            if 'required_points' not in existing_daily_log_columns:
                session.execute("ALTER TABLE daily_logs ADD COLUMN required_points INTEGER")
                session.commit()
            
            # Check which columns exist in iss_session_logs table
            result = session.execute("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name = 'iss_session_logs' 
                AND column_name = 'periods_covered'
            """)
            existing_session_log_columns = {row[0] for row in result}
            
            # Add periods_covered column to iss_session_logs if it doesn't exist
            if 'periods_covered' not in existing_session_log_columns:
                session.execute("ALTER TABLE iss_session_logs ADD COLUMN periods_covered JSON DEFAULT '[]'::json")
                session.commit()
            
            # Add 'needs_makeup' to PlacementStatus enum if not already present
            try:
                result = session.execute("""
                    SELECT enumlabel 
                    FROM pg_enum 
                    WHERE enumtypid = (SELECT oid FROM pg_type WHERE typname = 'placementstatus')
                    AND enumlabel = 'needs_makeup'
                """)
                if not result.fetchone():
                    session.execute("ALTER TYPE placementstatus ADD VALUE IF NOT EXISTS 'needs_makeup'")
                    session.commit()
            except Exception:
                session.rollback()
                
        except Exception as e:
            # Silently ignore migration errors on first run
            session.rollback()
        finally:
            session.close()
    
    def get_session(self) -> Session:
        """Get a new database session."""
        return self.SessionLocal()
    
    def generate_id(self) -> str:
        """Generate a unique identifier."""
        return str(uuid.uuid4())

    # =========================
    # SCHOOL CALENDAR (NO-SCHOOL DAYS) — Aug→Jul school year
    # =========================

    def _ensure_school_year_config(self, school_year: tuple) -> SchoolYearConfig:
        """Create config row if missing; return the row."""
        session = self.get_session()
        try:
            sy_start, sy_end = int(school_year[0]), int(school_year[1])
            cfg = session.query(SchoolYearConfig).filter(
                SchoolYearConfig.start_year == sy_start,
                SchoolYearConfig.end_year == sy_end
            ).first()
            if not cfg:
                cfg = SchoolYearConfig(
                    id=self.generate_id(),
                    start_year=sy_start,
                    end_year=sy_end,
                    calendar_finalized=False,
                    finalized_at=None
                )
                session.add(cfg)
                session.commit()
            return cfg
        finally:
            session.close()

    def is_school_calendar_finalized(self, school_year: tuple) -> bool:
        session = self.get_session()
        try:
            sy_start, sy_end = int(school_year[0]), int(school_year[1])
            cfg = session.query(SchoolYearConfig).filter(
                SchoolYearConfig.start_year == sy_start,
                SchoolYearConfig.end_year == sy_end
            ).first()
            return bool(cfg and cfg.calendar_finalized)
        finally:
            session.close()

    def finalize_school_calendar(self, school_year: tuple) -> bool:
        session = self.get_session()
        try:
            sy_start, sy_end = int(school_year[0]), int(school_year[1])
            cfg = session.query(SchoolYearConfig).filter(
                SchoolYearConfig.start_year == sy_start,
                SchoolYearConfig.end_year == sy_end
            ).first()
            if not cfg:
                cfg = SchoolYearConfig(
                    id=self.generate_id(),
                    start_year=sy_start,
                    end_year=sy_end,
                    calendar_finalized=True,
                    finalized_at=datetime.now()
                )
                session.add(cfg)
            else:
                cfg.calendar_finalized = True
                cfg.finalized_at = datetime.now()
            session.commit()
            return True
        finally:
            session.close()

    def list_school_closures(self, school_year: tuple) -> List[Dict[str, Any]]:
        session = self.get_session()
        try:
            sy_start, sy_end = int(school_year[0]), int(school_year[1])
            rows = session.query(SchoolClosure).filter(
                SchoolClosure.start_year == sy_start,
                SchoolClosure.end_year == sy_end
            ).order_by(SchoolClosure.start_date.asc()).all()

            out = []
            for r in rows:
                out.append({
                    "id": r.id,
                    "title": r.title,
                    "start_date": r.start_date.isoformat(),
                    "end_date": r.end_date.isoformat(),
                })
            return out
        finally:
            session.close()

    def add_school_closure(self, school_year: tuple, title: str, start_date: date, end_date: date) -> Optional[str]:
        """Add a single-day or range closure. Returns id or None."""
        if not title:
            return None

        # Normalize
        if isinstance(start_date, str):
            start_date = datetime.fromisoformat(start_date).date()
        if isinstance(end_date, str):
            end_date = datetime.fromisoformat(end_date).date()
        if end_date < start_date:
            start_date, end_date = end_date, start_date

        session = self.get_session()
        try:
            sy_start, sy_end = int(school_year[0]), int(school_year[1])
            # ensure config exists so August prompt can be satisfied later
            self._ensure_school_year_config((sy_start, sy_end))

            new_id = self.generate_id()
            row = SchoolClosure(
                id=new_id,
                start_year=sy_start,
                end_year=sy_end,
                title=title.strip(),
                start_date=start_date,
                end_date=end_date
            )
            session.add(row)
            session.commit()
            return new_id
        except IntegrityError:
            session.rollback()
            return None
        finally:
            session.close()

    def delete_school_closure(self, closure_id: str) -> bool:
        session = self.get_session()
        try:
            row = session.query(SchoolClosure).filter(SchoolClosure.id == closure_id).first()
            if not row:
                return False
            session.delete(row)
            session.commit()
            return True
        finally:
            session.close()

    def _closure_date_set_for_year(self, school_year: tuple) -> set:
        """Expand closure ranges into a set of dates for quick membership checks."""
        session = self.get_session()
        try:
            sy_start, sy_end = int(school_year[0]), int(school_year[1])
            rows = session.query(SchoolClosure).filter(
                SchoolClosure.start_year == sy_start,
                SchoolClosure.end_year == sy_end
            ).all()

            dates = set()
            for r in rows:
                d = r.start_date
                while d <= r.end_date:
                    dates.add(d)
                    d += timedelta(days=1)
            return dates
        finally:
            session.close()

    def is_non_school_day(self, d: date) -> bool:
        """True if weekend OR a saved no-school day for that date's school year."""
        if isinstance(d, str):
            try:
                d = datetime.fromisoformat(d).date()
            except Exception:
                return True

        # weekend
        if d.weekday() >= 5:
            return True

        sy = get_school_year_for_date(d)
        closure_set = self._closure_date_set_for_year(sy)
        return d in closure_set

    def next_school_day(self, d: date) -> date:
        """Advance to the next valid school day (skips weekends + closures)."""
        if isinstance(d, str):
            d = datetime.fromisoformat(d).date()

        nd = d + timedelta(days=1)
        while self.is_non_school_day(nd):
            nd += timedelta(days=1)
        return nd

    def get_school_days_with_closures(self, start_date: date, days_needed: int) -> List[str]:
        """Generate weekday school days skipping weekends + configured closures."""
        if isinstance(start_date, str):
            start_date = datetime.fromisoformat(start_date).date()

        out = []
        cur = start_date
        while len(out) < int(days_needed):
            if not self.is_non_school_day(cur):
                out.append(cur.isoformat())
            cur += timedelta(days=1)
        return out

    # Student operations
    def add_student(self, student_data: Dict[str, Any]) -> str:
        """Add a new student."""
        session = self.get_session()
        try:
            student_id = self.generate_id()
            student = Student(
                id=student_id,
                first_name=student_data['firstName'],
                last_name=student_data['lastName'],
                grade=student_data['grade'],
                homeroom_teacher=student_data['homeroomTeacher'],
                guardian_contacts=student_data.get('guardianContacts', []),
                status=StudentStatus.active
            )
            session.add(student)
            session.commit()
            return student_id
        finally:
            session.close()
    
    def get_all_students(self) -> List[Dict[str, Any]]:
        """Get all active students."""
        session = self.get_session()
        try:
            students = session.query(Student).filter(Student.status == StudentStatus.active).all()
            return [self._student_to_dict(s) for s in students]
        finally:
            session.close()
    
    def get_student(self, student_id: str) -> Optional[Dict[str, Any]]:
        """Get a specific student by ID."""
        session = self.get_session()
        try:
            student = session.query(Student).filter(Student.id == student_id).first()
            return self._student_to_dict(student) if student else None
        finally:
            session.close()
    
    def get_students_by_ids(self, student_ids: List[str]) -> Dict[str, Dict[str, Any]]:
        """Batch lookup: Get multiple students by their IDs in a single query.
        
        Returns a dictionary mapping student_id -> student_dict for fast lookups.
        """
        if not student_ids:
            return {}
        
        session = self.get_session()
        try:
            students = session.query(Student).filter(Student.id.in_(student_ids)).all()
            return {s.id: self._student_to_dict(s) for s in students}
        finally:
            session.close()
    
    def delete_student(self, student_id: str) -> bool:
        """Soft delete a student."""
        session = self.get_session()
        try:
            student = session.query(Student).filter(Student.id == student_id).first()
            if student:
                student.status = StudentStatus.deleted
                session.commit()
                return True
            return False
        finally:
            session.close()
    
    # Placement operations
    def add_placement(self, placement_data: Dict[str, Any]) -> str:
        """Add a new placement."""
        session = self.get_session()
        try:
            placement_id = self.generate_id()
            
            # Determine placement type
            placement_type = PlacementType.iss_full_day
            if 'type' in placement_data:
                if placement_data['type'] == 'partial':
                    placement_type = PlacementType.partial
            
            # Determine placement category (ISS, LUNCH_DETENTION, CLASS_REFERRAL, COOL_DOWN)
            placement_category = PlacementCategory.ISS
            if 'placementType' in placement_data:
                placement_category = PlacementCategory[placement_data['placementType']]
            
            # Determine completion rule
            completion_rule = CompletionRule.iss_days
            if 'completionRule' in placement_data:
                completion_rule = CompletionRule[placement_data['completionRule']]
            
            # Parse end_date if provided
            end_date = None
            if 'endDate' in placement_data and placement_data['endDate']:
                end_date = datetime.fromisoformat(placement_data['endDate']).date()
            
            # Generate scheduled ISS dates for full-day ISS placements
            scheduled_iss_dates = []
            served_dates = []
            
            if placement_category == PlacementCategory.ISS and placement_type == PlacementType.iss_full_day:
                start_date_obj = datetime.fromisoformat(placement_data['startDate']).date()
                days_assigned = placement_data['daysAssigned']
                scheduled_iss_dates = self.get_school_days_with_closures(start_date_obj, days_assigned)
                # For ISS (Full), auto-calculate end_date from scheduled dates
                if scheduled_iss_dates:
                    end_date = datetime.fromisoformat(scheduled_iss_dates[-1]).date()
            
            # Parse new ISS fields if provided
            iss_start_date = None
            if 'issStartDate' in placement_data and placement_data['issStartDate']:
                iss_start_date = datetime.fromisoformat(placement_data['issStartDate']).date()
            
            # Calculate period-based ISS tracking fields
            iss_days_assigned = placement_data.get('issTotalDays') or placement_data.get('daysAssigned', 1)
            iss_total_required_periods = iss_days_assigned * PERIODS_PER_FULL_DAY if placement_category == PlacementCategory.ISS else None
            iss_periods_served = 0
            
            # Debug output for ISS period-based model verification
            if placement_category == PlacementCategory.ISS:
                print(f"[DEBUG ISS MODEL] Creating ISS placement:")
                print(f"  - num_days (iss_days_assigned): {iss_days_assigned}")
                print(f"  - periods_per_full_day: {PERIODS_PER_FULL_DAY}")
                print(f"  - required_total_periods: {iss_total_required_periods}")
                print(f"  - served_periods_total: {iss_periods_served}")
                print(f"  - periods_remaining: {iss_total_required_periods - iss_periods_served}")
            
            # Determine placement status based on start date
            # If start date is in the future, set status to 'scheduled'
            # If start date is today or in the past, set status to 'active'
            start_date_obj = datetime.fromisoformat(placement_data['startDate']).date()
            today = central_today()
            if start_date_obj > today:
                initial_status = PlacementStatus.scheduled
            else:
                initial_status = PlacementStatus.active
            
            placement = Placement(
                id=placement_id,
                student_id=placement_data['studentId'],
                homeroom_teacher_id=placement_data.get('homeroomTeacherId'),
                reason=placement_data['reason'],
                type=placement_type,
                placement_type=placement_category,
                completion_rule=completion_rule,
                min_sessions_required=placement_data.get('minSessionsRequired'),
                days_assigned=placement_data['daysAssigned'],
                total_iss_periods=placement_data.get('totalIssPeriods'),
                iss_start_date=iss_start_date,
                iss_total_days=placement_data.get('issTotalDays'),
                iss_remaining_days=placement_data.get('issRemainingDays'),
                iss_days_assigned=iss_days_assigned if placement_category == PlacementCategory.ISS else None,
                iss_total_required_periods=iss_total_required_periods,
                iss_periods_served=iss_periods_served if placement_category == PlacementCategory.ISS else None,
                original_day_count=iss_days_assigned if placement_category == PlacementCategory.ISS else None,
                start_date=start_date_obj,
                end_date=end_date,
                start_period=placement_data.get('startPeriod'),
                end_period=placement_data.get('endPeriod'),
                scheduled_iss_dates=scheduled_iss_dates,
                scheduled_iss_sessions=placement_data.get('scheduledIssSessions', []),
                served_dates=served_dates,
                scheduled_lunch_dates=placement_data.get('scheduledLunchDates', []),
                referral_subtype=placement_data.get('referralSubtype'),
                status=initial_status,
                created_by=placement_data.get('createdBy'),
                created_at=datetime.fromisoformat(placement_data.get('createdAt', central_now_naive().isoformat()))
            )
            session.add(placement)
            session.commit()
            return placement_id
        finally:
            session.close()
    
    def get_placement(self, placement_id: str) -> Optional[Dict[str, Any]]:
        """Get a single placement by ID."""
        session = self.get_session()
        try:
            placement = session.query(Placement).filter(Placement.id == placement_id).first()
            if placement:
                return self._placement_to_dict(placement)
            return None
        finally:
            session.close()
    
    def get_active_placements(self) -> List[Dict[str, Any]]:
        """Get all active placements (including those needing make-up periods)."""
        session = self.get_session()
        try:
            placements = session.query(Placement).filter(
                Placement.status.in_([PlacementStatus.active, PlacementStatus.needs_makeup])
            ).all()
            return [self._placement_to_dict(p) for p in placements]
        finally:
            session.close()
    
    def get_active_placements_with_students(self) -> List[Dict[str, Any]]:
        """Get active placements with student information, sorted by placement type.
        
        Uses batch student lookup to minimize database calls.
        """
        active_placements = self.get_active_placements()
        result = []
        today = central_today()
        
        # BATCH OPTIMIZATION: Collect all student IDs and fetch in one query
        student_ids = list({p['studentId'] for p in active_placements if p.get('studentId')})
        students_by_id = self.get_students_by_ids(student_ids)
        
        for placement in active_placements:
            student = students_by_id.get(placement['studentId'])
            if student:
                placement_with_student = placement.copy()
                placement_with_student['student'] = student
                result.append(placement_with_student)
        
        # Helper: Get placement type priority
        def get_placement_type_priority(placement):
            placement_type = placement.get('placementType', '').upper()
            type_order = {
                'ISS': 1,
                'LUNCH_DETENTION': 2,
                'CLASS_REFERRAL': 3,
                'COOL_DOWN': 4
            }
            return type_order.get(placement_type, 999)  # Unknown types go last
        
        # Helper: Check if ISS placement is multi-day
        def is_multi_day_iss(placement):
            placement_type = placement.get('placementType', '').upper()
            if placement_type != 'ISS':
                return False
            
            # Multi-day ISS has days_assigned > 1
            days_assigned = placement.get('daysAssigned', 0)
            return days_assigned > 1
        
        # Helper: Check if placement is active today
        def is_active_today(placement):
            placement_type = placement.get('placementType', '').upper()
            start_date_str = placement.get('startDate')
            
            if not start_date_str:
                return False
            
            try:
                start_date = datetime.fromisoformat(start_date_str).date()
            except (ValueError, AttributeError):
                return False
            
            # For period-based placements (Class Referral, Cool-Down), 
            # check if start_date == today
            if placement_type in ['CLASS_REFERRAL', 'COOL_DOWN']:
                return start_date == today
            
            # For multi-day placements (ISS, Lunch Detention), calculate effective end date
            # Active placements have end_date = NULL, so we calculate from days_assigned
            days_assigned = placement.get('daysAssigned', 0)
            
            if days_assigned == 0:
                return False
            
            # Calculate the effective end date using business days
            effective_end_date = add_business_days(start_date, days_assigned)
            
            # Check if today falls within the placement range (inclusive)
            return start_date <= today <= effective_end_date
        
        # Helper: Get student name for sorting
        def get_student_name(placement):
            student = placement.get('student', {})
            last_name = student.get('lastName', '')
            first_name = student.get('firstName', '')
            return f"{last_name}, {first_name}".lower()
        
        # Helper: Get start date for sorting
        def get_start_date(placement):
            # All placement types use 'startDate' field
            return placement.get('startDate', '')
        
        # Sort with complex key:
        # 1. Placement type priority (ISS, Lunch, Class, Cool-Down)
        # 2. For ISS only: multi-day before single-day (0=multi, 1=single)
        # 3. Active today before not active (0=active, 1=not active)
        # 4. Earliest start date
        # 5. Alphabetical by student name
        result.sort(key=lambda p: (
            get_placement_type_priority(p),
            0 if is_multi_day_iss(p) else 1,  # Multi-day ISS first
            0 if is_active_today(p) else 1,    # Active today first
            get_start_date(p),
            get_student_name(p)
        ))
        
        return result
    
    def get_active_placements_for_date(self, target_date: date) -> List[Dict[str, Any]]:
        """Get placements that are/were/will be active on a specific date.
        
        Supports viewing past, present, and future dates:
        - Past dates: Show placements that were active on that day (including now-completed)
        - Today: Show currently active placements
        - Future dates: Show placements scheduled for that date
        
        For ISS placements:
        - Check if target_date falls within the placement's active period
        
        For Lunch Detention:
        - Check if target_date is a scheduled lunch detention date
        
        For Class Period Referrals:
        - Behavior/Cool-Down: Single-day, show on start_date
        - Pre-Planned: Check for sessions scheduled on target_date
        """
        session = self.get_session()
        try:
            from sqlalchemy import or_, and_, func
            
            today = central_today()
            is_past = target_date < today
            is_future = target_date > today
            
            if is_future:
                base_query = session.query(Placement).filter(
                    Placement.status.in_([PlacementStatus.active, PlacementStatus.needs_makeup, PlacementStatus.scheduled]),
                    Placement.start_date <= target_date
                )
            elif is_past:
                base_query = session.query(Placement).filter(
                    Placement.start_date <= target_date
                )
            else:
                # TODAY: include completed placements too, so they can remain visible on the calendar day they occurred.
                base_query = session.query(Placement).filter(
                    Placement.status.in_([PlacementStatus.active, PlacementStatus.needs_makeup, PlacementStatus.scheduled, PlacementStatus.completed]),
                    Placement.start_date <= target_date
                )
            
            placements = base_query.all()
            
            # BATCH OPTIMIZATION: Collect all student IDs and fetch in one query
            student_ids = list({p.student_id for p in placements if p.student_id})
            students_by_id = self.get_students_by_ids(student_ids)
            
            result = []
            
            for placement in placements:
                placement_dict = self._placement_to_dict(placement)
                student = students_by_id.get(placement.student_id)
                if not student:
                    continue
                    
                placement_dict['student'] = student
                placement_type = placement.placement_type.value.upper() if placement.placement_type else ''
                
                # ISS-specific filtering
                if placement_type == 'ISS':
                    iss_start_date = placement.iss_start_date or placement.start_date
                    
                    # Skip if target_date is before ISS start
                    if target_date < iss_start_date:
                        continue
                    
                    # Check if placement had ended by target_date (using authoritative end_date)
                    end_date = placement.end_date
                    if end_date and target_date > end_date:
                        continue
                    
                    # For past dates: Use authoritative completion signals
                    if is_past:
                        # Check served_dates first - most authoritative for actual activity
                        served_dates = placement.served_dates or []
                        served_date_objs = set()
                        for sd in served_dates:
                            try:
                                if isinstance(sd, str):
                                    served_date_objs.add(datetime.fromisoformat(sd).date())
                                else:
                                    served_date_objs.add(sd)
                            except:
                                pass
                        
                        # If target_date is in served_dates, definitely include it
                        if target_date in served_date_objs:
                            result.append(placement_dict)
                            continue
                        
                        # If placement is completed, check if target_date was during active period
                        if placement.status == PlacementStatus.completed:
                            if end_date:
                                # Use authoritative end_date
                                if iss_start_date <= target_date <= end_date:
                                    result.append(placement_dict)
                            else:
                                # Fallback for completed placements without end_date:
                                # Estimate using days_completed or days_assigned
                                days_completed = placement.days_completed or placement.iss_days_assigned or 1
                                estimated_end = iss_start_date + timedelta(days=days_completed + 2)  # Small buffer for weekends
                                if iss_start_date <= target_date <= estimated_end:
                                    result.append(placement_dict)
                        else:
                            # Still active or needs_makeup - was definitely active on past date within range
                            result.append(placement_dict)
                        continue
                    
                    # For today/future: Current active logic
                    iss_periods_served = placement.iss_periods_served or 0
                    iss_total_required = placement.iss_total_required_periods or 0
                    
                    # Calculate remaining days
                    iss_remaining_days = placement.iss_remaining_days or 0
                    if iss_remaining_days == 0 and placement.iss_days_assigned:
                        days_completed = placement.days_completed or 0
                        iss_remaining_days = (placement.iss_days_assigned or 0) - days_completed
                    
                    # Check if needs make-up
                    needs_makeup = (iss_remaining_days <= 0 and iss_periods_served < iss_total_required)
                    is_needs_makeup_status = placement.status == PlacementStatus.needs_makeup
                    
                    # Skip completed ISS (all periods served, no remaining days, not needs_makeup)
                    if iss_periods_served >= iss_total_required and iss_remaining_days <= 0 and not is_needs_makeup_status:
                        continue
                    
                    # Include if has remaining days, needs makeup, or has needs_makeup status
                    if iss_remaining_days > 0 or needs_makeup or is_needs_makeup_status:
                        result.append(placement_dict)
                
                # Lunch Detention filtering
                elif placement_type == 'LUNCH_DETENTION':
                    scheduled_dates = placement.scheduled_lunch_dates or []
                    served_dates = placement.served_dates or []
                    
                    # Convert scheduled dates to date objects for comparison
                    scheduled_date_objs = set()
                    for sd in scheduled_dates:
                        try:
                            if isinstance(sd, str):
                                scheduled_date_objs.add(datetime.fromisoformat(sd).date())
                            elif hasattr(sd, 'date'):
                                scheduled_date_objs.add(sd.date() if callable(getattr(sd, 'date')) else sd)
                            else:
                                scheduled_date_objs.add(sd)
                        except:
                            pass
                    
                    # Convert served dates to date objects for comparison
                    served_date_objs = set()
                    for sd in served_dates:
                        try:
                            if isinstance(sd, str):
                                served_date_objs.add(datetime.fromisoformat(sd).date())
                            elif hasattr(sd, 'date'):
                                served_date_objs.add(sd.date() if callable(getattr(sd, 'date')) else sd)
                            else:
                                served_date_objs.add(sd)
                        except:
                            pass
                    
                    # For past dates: Show if target_date was scheduled or served
                    if is_past:
                        if target_date in scheduled_date_objs or target_date in served_date_objs:
                            result.append(placement_dict)
                        continue
                    
                    # For today/future: Current active logic
                    days_served = len(served_dates)
                    days_assigned = placement.days_assigned or 0
                    
                    # Skip if all lunch detention days are served,
                    # BUT keep it visible on the specific calendar day(s) it was served.
                    if days_served >= days_assigned:
                        if target_date in served_date_objs:
                            result.append(placement_dict)
                        continue
                    
                    # Check if target_date is a scheduled date (not yet served)
                    if target_date in scheduled_date_objs:
                        result.append(placement_dict)
                
                # Class Period Referral filtering
                elif placement_type == 'CLASS_REFERRAL':
                    referral_subtype = placement.referral_subtype or ''
                    
                    if referral_subtype == 'pre_planned':
                        # Pre-Planned: Check for session on this date
                        if is_past:
                            # For past dates, include all sessions for that date (even fulfilled)
                            sessions_for_date = session.query(PartialDaySession).filter(
                                PartialDaySession.placement_id == placement.id,
                                PartialDaySession.date == target_date
                            ).all()
                            if sessions_for_date:
                                all_periods = []
                                for s in sessions_for_date:
                                    all_periods.extend(s.periods or [])
                                placement_dict['scheduledSlots'] = [
                                    {'date': target_date.isoformat(), 'period': p} 
                                    for p in all_periods
                                ]
                                result.append(placement_dict)
                        else:
                            # For today/future: include ALL sessions for this date (fulfilled or not)
                            # This allows completed Pre-Planned referrals to persist on the Dashboard calendar day
                            # as a collapsed/inactive record, while still showing active ones normally.
                            sessions_for_date = session.query(PartialDaySession).filter(
                                PartialDaySession.placement_id == placement.id,
                                PartialDaySession.date == target_date
                            ).all()

                            if sessions_for_date:
                                all_periods = []
                                for s in sessions_for_date:
                                    all_periods.extend(s.periods or [])

                                placement_dict['scheduledSlots'] = [
                                    {'date': target_date.isoformat(), 'period': p}
                                    for p in all_periods
                                ]
                                result.append(placement_dict)
                    else:
                        # Behavior/Cool-Down: Single-day, show on start_date
                        if placement.start_date == target_date:
                            result.append(placement_dict)
                
                # Cool-Down filtering (same-day only, like referrals)
                elif placement_type == 'COOL_DOWN':
                    if placement.start_date == target_date:
                        result.append(placement_dict)
                
                # Legacy/other placement types - use date range logic
                else:
                    end_date = placement.start_date + timedelta(days=placement.days_assigned or 1)
                    if placement.start_date <= target_date <= end_date:
                        result.append(placement_dict)
            
            return result
        finally:
            session.close()
    
    def complete_placement(self, placement_id: str) -> bool:
        """Complete a placement."""
        session = self.get_session()
        try:
            placement = session.query(Placement).filter(Placement.id == placement_id).first()
            if placement:
                placement.status = PlacementStatus.completed
                placement.progress_status = PlacementProgressStatus.COMPLETED
                placement.end_date = central_today()
                session.commit()
                return True
            return False
        finally:
            session.close()
    
    def restore_placement_to_active(self, placement_id: str) -> bool:
        """Restore a completed placement back to active status."""
        session = self.get_session()
        try:
            placement = session.query(Placement).filter(Placement.id == placement_id).first()
            if placement and placement.status == PlacementStatus.completed:
                placement.status = PlacementStatus.active
                placement.end_date = None
                session.commit()
                return True
            return False
        finally:
            session.close()
    
    def auto_complete_preplanned_multi_day_after_last_date(self) -> int:
        """
        If the last scheduled date for a Pre-Planned multi-day placement
        has passed, mark the placement completed regardless of
        absent vs attended mix.
        """
        from sqlalchemy import func
        session = self.get_session()
        try:
            today = central_today()
            completed_count = 0

            placements = session.query(Placement).filter(
                Placement.status != PlacementStatus.completed,
                Placement.days_assigned.isnot(None),
                Placement.days_assigned > 1,
                (
                    (Placement.placement_type == PlacementCategory.PRE_PLANNED_REFERRAL) |
                    (
                        (Placement.placement_type == PlacementCategory.CLASS_REFERRAL) &
                        (Placement.referral_subtype == "pre_planned")
                    )
                )
            ).all()

            for placement in placements:
                # Authoritative schedule source: PartialDaySession dates
                last_scheduled_date = session.query(
                    func.max(PartialDaySession.date)
                ).filter(
                    PartialDaySession.placement_id == placement.id
                ).scalar()

                # Fallback: placement.end_date
                if not last_scheduled_date:
                    last_scheduled_date = placement.end_date

                if not last_scheduled_date:
                    continue

                if last_scheduled_date < today:
                    placement.status = PlacementStatus.completed
                    placement.progress_status = PlacementProgressStatus.COMPLETED
                    placement.end_date = last_scheduled_date

                    if placement.days_assigned:
                        placement.days_completed = max(
                            int(placement.days_completed or 0),
                            int(placement.days_assigned)
                        )

                    completed_count += 1

            if completed_count:
                session.commit()

            return completed_count

        except Exception as e:
            session.rollback()
            print(f"[auto_complete_preplanned_multi_day_after_last_date] error: {e}")
            return 0
        finally:
            session.close()

    def activate_scheduled_placements(self) -> int:
        """Auto-transition scheduled placements to active when their start date has arrived.
        
        This should be called on app startup to ensure placements are activated
        on their start date.
        
        Returns:
            Number of placements that were activated.
        """
        session = self.get_session()
        try:
            today = central_today()
            # Find all scheduled placements whose start_date is today or in the past
            scheduled_placements = session.query(Placement).filter(
                Placement.status == PlacementStatus.scheduled,
                Placement.start_date <= today
            ).all()
            
            activated_count = 0
            for placement in scheduled_placements:
                placement.status = PlacementStatus.active

                # IMPORTANT: Do NOT auto-set placements to IN_PROGRESS just because the date arrived.
                # Green/NOT_STARTED must remain until a user explicitly checks in / starts the session.
                placement.progress_status = PlacementProgressStatus.NOT_STARTED

                activated_count += 1
            
            if activated_count > 0:
                session.commit()
            
            # Auto-complete Pre-Planned multi-day placements whose last date has passed
            try:
                self.auto_complete_preplanned_multi_day_after_last_date()
            except Exception as e:
                print(f"Pre-Planned auto-complete sweep failed: {e}")

            return activated_count
        finally:
            session.close()
    
    def update_iss_attendance(self, placement_id: str, attendance_date: str, is_present: bool) -> bool:
        """Update ISS attendance for a specific date.
        
        Args:
            placement_id: ID of the placement
            attendance_date: ISO format date string
            is_present: True if student was present, False if absent
            
        Returns:
            True if successful, False otherwise
        """
        session = self.get_session()
        try:
            placement = session.query(Placement).filter(Placement.id == placement_id).first()
            if not placement:
                return False
            
            # Only apply to ISS full-day placements
            if placement.placement_type != PlacementCategory.ISS or placement.type != PlacementType.iss_full_day:
                return False
            
            date_obj = datetime.fromisoformat(attendance_date).date()
            date_str = date_obj.isoformat()
            
            # Get current arrays (handle None)
            served_dates = placement.served_dates if placement.served_dates else []
            scheduled_dates = placement.scheduled_iss_dates if placement.scheduled_iss_dates else []
            
            if is_present:
                # Add date to served_dates if not already there
                if date_str not in served_dates:
                    served_dates.append(date_str)
                    placement.served_dates = served_dates
                
                # Check if placement should be completed
                total_required = placement.days_assigned
                if len(served_dates) >= total_required:
                    placement.status = PlacementStatus.completed
                    placement.progress_status = PlacementProgressStatus.COMPLETED
                    placement.end_date = date_obj
            else:
                # Student was absent - extend schedule by one school day
                if not scheduled_dates:
                    return False
                
                last_date_str = scheduled_dates[-1]
                last_date = datetime.fromisoformat(last_date_str).date()
                
                # Find next school day
                next_date = last_date
                next_date = self.next_school_day(next_date)
                
                # Append to scheduled dates and update end date
                scheduled_dates.append(next_date.isoformat())
                placement.scheduled_iss_dates = scheduled_dates
                placement.end_date = next_date
            
            session.commit()
            return True
        finally:
            session.close()
    
    def check_in_student(self, placement_id: str, check_in_date: str, day_type: str = None,
                         start_period: int = None, end_period: int = None, is_makeup: bool = False) -> bool:
        """Check in a student for an ISS day.
        
        Args:
            placement_id: ID of the placement
            check_in_date: ISO format date string
            day_type: 'full' for full day (10 periods) or 'partial' for partial day
            start_period: For partial day, the starting period (1-10)
            end_period: For partial day, the ending period (1-10)
            is_makeup: True if this is a make-up session (for needs_makeup placements)
            
        Returns:
            True if successful, False otherwise
            
        Period-Based Point Target:
            For partial days: required_points = end_period - start_period + 1 (periods_covered)
            For full days: required_points = 10
            
        Auto-Classification for Day 1 Partial (Multi-day ISS Session):
            When ALL conditions are met:
            - placement_type is ISS
            - iss_days_assigned > 1 (multi-day Session)
            - start_date = today (check_in_date)
            - iss_periods_served = 0 (no periods served yet)
            - day_type = 'partial'
            
            Then automatically:
            - Treat as Day 1 of the multi-day ISS Session
            - Set is_flexible_session_mode = True for period-based completion tracking
        """
        session = self.get_session()
        try:
            placement = session.query(Placement).filter(Placement.id == placement_id).first()
            if not placement:
                return False
            
            date_obj = datetime.fromisoformat(check_in_date).date()
            date_str = date_obj.isoformat()
            
            # Auto-classification for Day 1 Partial of multi-day ISS Session
            # When: ISS, multi-day (>1), start_date = today, no periods served yet, partial day
            is_iss = placement.placement_type == PlacementCategory.ISS
            iss_days = placement.iss_days_assigned or placement.iss_total_days or 1
            is_multi_day = iss_days > 1
            is_start_date = placement.start_date == date_obj
            no_periods_served = (placement.iss_periods_served or 0) == 0
            is_partial = day_type == 'partial'
            
            if is_iss and is_multi_day and is_start_date and no_periods_served and is_partial:
                # Auto-classify as Day 1 of multi-day ISS Session
                # Flag placement for flexible session mode (period-based completion)
                placement.is_flexible_session_mode = True
            
            # Calculate periods_covered and required_points based on day_type
            # Only set day config if explicitly provided (day_type is not None)
            calc_start_period = None
            calc_end_period = None
            periods_covered = []
            required_points = None
            
            if day_type == 'full':
                # Full day: all 10 periods, 10 required points
                calc_start_period = 1
                calc_end_period = 10
                periods_covered = list(range(1, 11))
                required_points = 10
            elif day_type == 'partial':
                # Partial day: use provided periods or defaults
                calc_start_period = start_period if start_period else 1
                calc_end_period = end_period if end_period else 10
                # Validate: end_period >= start_period
                if calc_end_period < calc_start_period:
                    calc_end_period = calc_start_period
                periods_covered = list(range(calc_start_period, calc_end_period + 1))
                # Required points = periods covered (1 point per period)
                required_points = calc_end_period - calc_start_period + 1
            # If day_type is None, we leave the calc values as None/empty (attendance-only check-in)
            
            # Get or create daily log
            log = session.query(DailyLog).filter(
                DailyLog.placement_id == placement_id,
                DailyLog.date == date_obj
            ).first()
            
            if not log:
                # Create new log - only set day config if day_type provided
                log = DailyLog(
                    id=str(uuid.uuid4()),
                    placement_id=placement_id,
                    date=date_obj,
                    checked_in=True,
                    checked_in_at=central_now_naive(),
                    is_makeup_session=is_makeup
                )
                # Only set day config if day_type is explicitly provided
                if day_type is not None:
                    log.day_type = day_type
                    log.start_period = calc_start_period
                    log.end_period = calc_end_period
                    log.periods_covered = periods_covered
                    log.required_points = required_points
                session.add(log)
            else:
                log.checked_in = True
                log.checked_in_at = central_now_naive()
                log.is_makeup_session = is_makeup
                # Only set day config if day_type is explicitly provided
                if day_type is not None:
                    log.day_type = day_type
                    log.start_period = calc_start_period
                    log.end_period = calc_end_period
                    log.periods_covered = periods_covered
                    log.required_points = required_points
            
            # Also add to served_dates for ISS placements
            if placement.placement_type == PlacementCategory.ISS:
                served_dates = placement.served_dates if placement.served_dates else []
                if date_str not in served_dates:
                    served_dates.append(date_str)
                    placement.served_dates = served_dates
            
            # Update progress_status to IN_PROGRESS on check-in
            if placement.progress_status != PlacementProgressStatus.COMPLETED:
                placement.progress_status = PlacementProgressStatus.IN_PROGRESS
            
            session.commit()
            return True
        finally:
            session.close()
    
    def is_student_checked_in(self, placement_id: str, check_date: str) -> bool:
        """Check if a student is checked in for a specific date.
        
        Args:
            placement_id: ID of the placement
            check_date: ISO format date string
            
        Returns:
            True if checked in, False otherwise
        """
        session = self.get_session()
        try:
            date_obj = datetime.fromisoformat(check_date).date()
            log = session.query(DailyLog).filter(
                DailyLog.placement_id == placement_id,
                DailyLog.date == date_obj
            ).first()
            
            return log.checked_in if log else False
        finally:
            session.close()
    
    def update_lunch_detention_attendance(self, placement_id: str, attendance_date: str, is_present: bool) -> bool:
        """Update Lunch Detention attendance for a specific date.
        
        Args:
            placement_id: ID of the placement
            attendance_date: ISO format date string
            is_present: True if student was present, False if absent
            
        Returns:
            True if successful, False otherwise
        """
        session = self.get_session()
        try:
            placement = session.query(Placement).filter(Placement.id == placement_id).first()
            if not placement or placement.placement_type != PlacementCategory.LUNCH_DETENTION:
                return False

            date_obj = datetime.fromisoformat(attendance_date).date()
            date_str = date_obj.isoformat()

            served_dates = list(placement.served_dates) if placement.served_dates else []

            log = session.query(DailyLog).filter(
                DailyLog.placement_id == placement_id,
                DailyLog.date == date_obj
            ).first()

            if is_present:
                if not log:
                    log = DailyLog(
                        id=str(uuid.uuid4()),
                        placement_id=placement_id,
                        date=date_obj,
                        checked_in=True,
                        checked_in_at=central_now_naive(),
                        day_type=None,
                        daily_fulfillment='no',
                        positive_total=0,
                        negative_total=0,
                        daily_total=0
                    )
                    session.add(log)
                else:
                    log.checked_in = True
                    log.checked_in_at = central_now_naive()
                    log.day_type = None
                    log.daily_fulfillment = log.daily_fulfillment or 'no'

                if date_str not in served_dates:
                    served_dates.append(date_str)
                    placement.served_dates = served_dates

                if placement.status == PlacementStatus.scheduled:
                    placement.status = PlacementStatus.active

                placement.progress_status = PlacementProgressStatus.IN_PROGRESS

                self._sync_lunch_detention_schedule_for_absences(
                    session, placement, trim_extras=True
                )

            else:
                self.mark_absent(placement_id, attendance_date)
                self._sync_lunch_detention_schedule_for_absences(
                    session, placement, trim_extras=False
                )

            session.commit()
            return True
        finally:
            session.close()
    
    def mark_absent(self, placement_id: str, absent_date: str) -> bool:
        """Mark a student as absent for a specific date.
        
        This does NOT update progress_status - it simply records the absence.
        Absent days are skipped in day/period counting.
        
        Args:
            placement_id: ID of the placement
            absent_date: ISO format date string
            
        Returns:
            True if successful, False otherwise
        """
        session = self.get_session()
        try:
            placement = session.query(Placement).filter(Placement.id == placement_id).first()
            if not placement:
                return False
            
            date_obj = datetime.fromisoformat(absent_date).date()
            
            # Get or create daily log
            log = session.query(DailyLog).filter(
                DailyLog.placement_id == placement_id,
                DailyLog.date == date_obj
            ).first()
            
            if not log:
                log_id = self.generate_id()
                log = DailyLog(
                    id=log_id,
                    placement_id=placement_id,
                    date=date_obj,
                    day_type='absent',
                    checked_in=False,
                    start_period=None,
                    end_period=None,
                    periods_covered=[],
                    daily_fulfillment=None,
                    positive_total=0,
                    negative_total=0,
                    daily_total=0
                )
                session.add(log)
            else:
                # Mark absent and clear any "present day" artifacts
                log.day_type = 'absent'
                log.checked_in = False
                log.checked_in_at = None

                # Clear day config (prevents stale partial/full settings)
                log.start_period = None
                log.end_period = None
                log.periods_covered = []

                # Clear fulfillment + points for that day (absent days should not carry scoring)
                log.daily_fulfillment = None
                log.positive_total = 0
                log.negative_total = 0
                log.daily_total = 0
            
            # Do NOT update progress_status - absent days don't affect status

            if placement.placement_type == PlacementCategory.LUNCH_DETENTION:
                self._sync_lunch_detention_schedule_for_absences(
                    session, placement, trim_extras=False
                )
            
            session.commit()
            return True
        finally:
            session.close()

    def complete_and_clone_lunch_detention_absent(self, placement_id: str, absent_date: str, actor: str = "Admin") -> Optional[str]:
        """For 1-day Lunch Detention only:
        - ensure the day is marked absent
        - atomically (transactional) close original as COMPLETED
        - clone a new 1-day Lunch Detention on the next school day

        Option A UI intent preserved: red circle + 'Absent' subtitle on the original.
        """
        session = self.get_session()
        try:
            placement = session.query(Placement).filter(Placement.id == placement_id).first()
            if not placement:
                return None

            # Guardrails
            if placement.placement_type != PlacementCategory.LUNCH_DETENTION:
                return None
            if (placement.days_assigned or 1) != 1:
                return None

            date_obj = datetime.fromisoformat(absent_date).date()

            # Ensure DailyLog exists and is absent
            log = session.query(DailyLog).filter(
                DailyLog.placement_id == placement_id,
                DailyLog.date == date_obj
            ).first()

            if not log:
                log = DailyLog(
                    id=self.generate_id(),
                    placement_id=placement_id,
                    date=date_obj,
                    day_type='absent',
                    checked_in=False,
                    start_period=None,
                    end_period=None,
                    periods_covered=[],
                    daily_fulfillment=None,
                    positive_total=0,
                    negative_total=0,
                    daily_total=0,
                    readiness='continue'
                )
                session.add(log)
            else:
                log.day_type = 'absent'
                log.checked_in = False
                log.checked_in_at = None
                log.start_period = None
                log.end_period = None
                log.periods_covered = []
                log.daily_fulfillment = None
                log.positive_total = 0
                log.negative_total = 0
                log.daily_total = 0

            # --- Compute next school day BEFORE closing original (transaction safety) ---
            next_start = date_obj + timedelta(days=1)
            next_dates = self.calculate_scheduled_lunch_dates(next_start, 1)
            if not next_dates:
                raise RuntimeError("No next school day available for Lunch Detention reschedule.")
            next_day = next_dates[0]

            # Read original placement data once
            original = self.get_placement(placement_id)
            if not original:
                raise RuntimeError("Original placement not found during clone.")

            # Prepare clone payload
            placement_data = {
                "studentId": original.get('studentId'),
                "homeroomTeacherId": original.get('homeroomTeacherId'),
                "reason": original.get('reason', ''),
                "type": "iss_full_day",
                "placementType": "LUNCH_DETENTION",
                "completionRule": "all_sessions_fulfilled",
                "minSessionsRequired": None,
                "daysAssigned": 1,
                "startDate": next_day.isoformat(),
                "endDate": next_day.isoformat(),
                "scheduledLunchDates": [next_day.isoformat()],
                "servedDates": [],
                "status": "active",
                "createdBy": original.get('createdBy') or actor,
                "createdAt": central_now().isoformat()
            }

            # Create clone first
            new_placement_id = self.add_placement(placement_data)
            self.generate_lunch_detention_sessions_from_scheduled(new_placement_id, [next_day])

            # Now safely close original
            placement.status = PlacementStatus.completed
            placement.progress_status = PlacementProgressStatus.COMPLETED
            placement.end_date = date_obj

            # Store marker for UI subtitle
            existing = placement.makeup_note or ""
            marker = "ABSENT_RESCHEDULED"
            placement.makeup_note = f"{existing} | {marker}".strip(" |") if existing else marker

            session.commit()
            return new_placement_id

        except Exception:
            session.rollback()
            # Re-raise so UI can surface the error if needed
            raise
        finally:
            session.close()

    def mark_lunch_detention_absent_closed(self, placement_id: str):
        """Mark a 1-day Lunch Detention as absent + closed (no reschedule).
        
        Sets the placement to COMPLETED and appends ABSENT_CLOSED marker for UI subtitle.
        """
        self.close_lunch_detention_absent_no_clone(placement_id)

    def close_lunch_detention_absent_no_clone(self, placement_id: str, absent_date: str = None):
        """
        1-day Lunch Detention only:
          - mark day absent (if absent_date provided)
          - close original placement as COMPLETED
          - store marker: makeup_note contains 'ABSENT_CLOSED'
        """
        session = self.get_session()
        try:
            placement = session.query(Placement).filter(Placement.id == placement_id).first()
            if not placement:
                return

            # Guardrails
            if placement.placement_type != PlacementCategory.LUNCH_DETENTION:
                return
            if (placement.days_assigned or 1) != 1:
                return

            # Mark absent if date provided
            if absent_date:
                date_obj = datetime.fromisoformat(absent_date).date()

                # Ensure DailyLog absent
                log = session.query(DailyLog).filter(
                    DailyLog.placement_id == placement_id,
                    DailyLog.date == date_obj
                ).first()

                if not log:
                    log = DailyLog(
                        id=self.generate_id(),
                        placement_id=placement_id,
                        date=date_obj,
                        day_type='absent',
                        checked_in=False,
                        start_period=None,
                        end_period=None,
                        periods_covered=[],
                        daily_fulfillment=None,
                        positive_total=0,
                        negative_total=0,
                        daily_total=0
                    )
                    session.add(log)
                else:
                    log.day_type = 'absent'
                    log.checked_in = False
                    log.checked_in_at = None
                    log.start_period = None
                    log.end_period = None
                    log.periods_covered = []
                    log.daily_fulfillment = None
                    log.positive_total = 0
                    log.negative_total = 0
                    log.daily_total = 0

                placement.end_date = date_obj

            # Close original
            placement.status = PlacementStatus.completed
            placement.progress_status = PlacementProgressStatus.COMPLETED

            # Store marker for UI subtitle
            existing = placement.makeup_note or ""
            marker = "ABSENT_CLOSED"
            placement.makeup_note = f"{existing} | {marker}".strip(" |") if existing else marker

            session.commit()
        finally:
            session.close()
    
    def unmark_absent(self, placement_id: str, date_str: str) -> bool:
        """Remove the absent marking for a specific date.
        
        Args:
            placement_id: ID of the placement
            date_str: ISO format date string
            
        Returns:
            True if successful, False otherwise
        """
        session = self.get_session()
        try:
            date_obj = datetime.fromisoformat(date_str).date()
            
            log = session.query(DailyLog).filter(
                DailyLog.placement_id == placement_id,
                DailyLog.date == date_obj
            ).first()
            
            if log and log.day_type == 'absent':
                log.day_type = None
                
                placement = session.query(Placement).filter(Placement.id == placement_id).first()
                if placement and placement.placement_type == PlacementCategory.LUNCH_DETENTION:
                    self._sync_lunch_detention_schedule_for_absences(
                        session, placement, trim_extras=True
                    )
                
                session.commit()
            
            return True
        finally:
            session.close()
    
    def is_marked_absent(self, placement_id: str, date_str: str) -> bool:
        """Check if a specific date is marked as absent.
        
        Args:
            placement_id: ID of the placement
            date_str: ISO format date string
            
        Returns:
            True if marked absent, False otherwise
        """
        session = self.get_session()
        try:
            date_obj = datetime.fromisoformat(date_str).date()
            
            log = session.query(DailyLog).filter(
                DailyLog.placement_id == placement_id,
                DailyLog.date == date_obj
            ).first()
            
            return log.day_type == 'absent' if log else False
        finally:
            session.close()
    
    def complete_placement_as_absent(self, placement_id: str, absent_date: str) -> bool:
        """
        Marks a placement as completed due to absence (used for single-day CPR).
        """
        session = self.get_session()
        try:
            placement = session.query(Placement).filter(Placement.id == placement_id).first()
            if not placement:
                return False

            date_obj = datetime.fromisoformat(absent_date).date()

            # Ensure DailyLog exists and is marked absent
            log = session.query(DailyLog).filter(
                DailyLog.placement_id == placement_id,
                DailyLog.date == date_obj
            ).first()

            if not log:
                log = DailyLog(
                    id=self.generate_id(),
                    placement_id=placement_id,
                    date=date_obj,
                    day_type='absent',
                    checked_in=False,
                    daily_fulfillment='yes',
                    positive_total=0,
                    negative_total=0,
                    daily_total=0
                )
                session.add(log)
            else:
                log.day_type = 'absent'
                log.checked_in = False
                log.checked_in_at = None
                log.daily_fulfillment = 'yes'
                log.positive_total = 0
                log.negative_total = 0
                log.daily_total = 0

            # FIXED ENUM VALUE: use lowercase 'completed'
            placement.status = PlacementStatus.completed
            placement.progress_status = PlacementProgressStatus.COMPLETED
            placement.end_date = date_obj
            placement.days_completed = max(
                int(placement.days_completed or 0),
                int(placement.days_assigned or 1)
            )

            session.commit()
            return True

        except Exception as e:
            session.rollback()
            print(f"[complete_placement_as_absent] error: {e}")
            return False
        finally:
            session.close()
    
    def checkin_referral(self, placement_id: str, checkin_date: str) -> bool:
        """Check in a student for a Behavior or Cool-Down referral.
        
        This is a simplified check-in that:
        - Sets checked_in = True in the daily log
        - Updates progress_status to IN_PROGRESS
        
        Args:
            placement_id: ID of the placement
            checkin_date: ISO format date string
            
        Returns:
            True if successful, False otherwise
        """
        session = self.get_session()
        try:
            placement = session.query(Placement).filter(Placement.id == placement_id).first()
            if not placement:
                return False
            
            date_obj = datetime.fromisoformat(checkin_date).date()
            
            # Get or create daily log
            log = session.query(DailyLog).filter(
                DailyLog.placement_id == placement_id,
                DailyLog.date == date_obj
            ).first()
            
            if not log:
                log_id = self.generate_id()
                log = DailyLog(
                    id=log_id,
                    placement_id=placement_id,
                    date=date_obj,
                    checked_in=True,
                    checked_in_at=central_now_naive()
                )
                session.add(log)
            else:
                log.checked_in = True
                log.checked_in_at = central_now_naive()
            
            # Update progress_status to IN_PROGRESS on check-in
            if placement.progress_status != PlacementProgressStatus.COMPLETED:
                placement.progress_status = PlacementProgressStatus.IN_PROGRESS
            
            session.commit()
            return True
        finally:
            session.close()
    
    def get_completed_placements_with_students(self) -> List[Dict[str, Any]]:
        """Get all completed placements with student info.
        
        Uses batch student lookup to minimize database calls.
        """
        session = self.get_session()
        try:
            placements = session.query(Placement).filter(
                Placement.status == PlacementStatus.completed
            ).order_by(Placement.end_date.desc()).all()
            
            # BATCH OPTIMIZATION: Collect all student IDs and fetch in one query
            student_ids = list({p.student_id for p in placements if p.student_id})
            students_by_id = self.get_students_by_ids(student_ids)
            
            result = []
            for placement in placements:
                placement_dict = self._placement_to_dict(placement)

                # NEW: For ISS placements, compute an "archiveDate" = earliest DailyLog date
                # so Completed Placements can group by first check-in day (not completion day).
                if placement.placement_type == PlacementCategory.ISS:
                    from sqlalchemy import func
                    first_log_date = session.query(func.min(DailyLog.date)).filter(
                        DailyLog.placement_id == placement.id
                    ).scalar()
                    if first_log_date:
                        placement_dict['archiveDate'] = first_log_date.isoformat()

                student = students_by_id.get(placement.student_id)
                if student:
                    placement_dict['student'] = student
                    placement_dict['totalPoints'] = self.get_cumulative_total(placement.id)
                    result.append(placement_dict)
            
            return result
        finally:
            session.close()
    
    def get_session_fulfillment_stats(self, placement_id: str) -> Dict[str, int]:
        """Get session fulfillment statistics for a placement."""
        session = self.get_session()
        try:
            all_sessions = session.query(PartialDaySession).filter(
                PartialDaySession.placement_id == placement_id
            ).all()
            
            total_sessions = len(all_sessions)
            fulfilled_sessions = len([s for s in all_sessions if s.status == SessionStatus.fulfilled])
            
            return {
                'total_sessions': total_sessions,
                'fulfilled_sessions': fulfilled_sessions,
                'remaining_sessions': total_sessions - fulfilled_sessions
            }
        finally:
            session.close()
    
    def check_placement_completion_criteria(self, placement_id: str) -> Dict[str, Any]:
        """Check if placement meets its completion criteria."""
        session = self.get_session()
        try:
            placement = session.query(Placement).filter(Placement.id == placement_id).first()
            if not placement:
                return {'can_complete': False, 'reason': 'Placement not found'}
            
            # Already completed
            if placement.status == PlacementStatus.completed:
                return {'can_complete': False, 'reason': 'Already completed'}
            
            completion_rule = placement.completion_rule.value
            
            # ISS Days rule (traditional)
            if completion_rule == 'iss_days':
                days_remaining = placement.days_assigned - placement.days_completed
                can_complete = days_remaining <= 0
                return {
                    'can_complete': can_complete,
                    'reason': f'Days remaining: {days_remaining}' if not can_complete else 'All days completed',
                    'rule': 'iss_days',
                    'days_remaining': days_remaining
                }
            
            # Get session stats for partial placement rules
            stats = self.get_session_fulfillment_stats(placement_id)
            
            # All Sessions Fulfilled rule
            if completion_rule == 'all_sessions_fulfilled':
                can_complete = stats['total_sessions'] > 0 and stats['remaining_sessions'] == 0
                return {
                    'can_complete': can_complete,
                    'reason': f"{stats['fulfilled_sessions']}/{stats['total_sessions']} sessions fulfilled",
                    'rule': 'all_sessions_fulfilled',
                    'stats': stats
                }
            
            # Minimum Sessions rule
            if completion_rule == 'min_sessions_n':
                min_required = placement.min_sessions_required or 0
                can_complete = stats['fulfilled_sessions'] >= min_required
                return {
                    'can_complete': can_complete,
                    'reason': f"{stats['fulfilled_sessions']}/{min_required} minimum sessions fulfilled",
                    'rule': 'min_sessions_n',
                    'stats': stats,
                    'min_required': min_required
                }
            
            # Date Range End rule
            if completion_rule == 'date_range_end':
                # Auto-complete when end date has passed
                if placement.end_date:
                    can_complete = central_today() > placement.end_date
                    return {
                        'can_complete': can_complete,
                        'reason': f"End date: {placement.end_date.isoformat()}",
                        'rule': 'date_range_end',
                        'end_date': placement.end_date.isoformat()
                    }
                else:
                    return {
                        'can_complete': False,
                        'reason': 'No end date set',
                        'rule': 'date_range_end'
                    }
            
            return {'can_complete': False, 'reason': 'Unknown completion rule'}
        finally:
            session.close()
    
    # Session operations
    def add_session(self, session_data: Dict[str, Any]) -> str:
        """Add a new partial day session."""
        db_session = self.get_session()
        try:
            session_id = self.generate_id()
            
            # Parse session type
            session_type = SessionType[session_data['type']]
            
            new_session = PartialDaySession(
                id=session_id,
                placement_id=session_data['placement_id'],
                date=session_data['date'] if isinstance(session_data['date'], date) else datetime.fromisoformat(session_data['date']).date(),
                type=session_type,
                periods=session_data.get('periods', []),
                time_start=session_data.get('time_start'),
                time_end=session_data.get('time_end'),
                location=session_data.get('location', ''),
                status=SessionStatus.scheduled,
                notes=session_data.get('notes', '')
            )
            db_session.add(new_session)
            db_session.commit()
            return session_id
        finally:
            db_session.close()
    
    def add_sessions_bulk(self, sessions_data: List[Dict[str, Any]]) -> List[str]:
        """Add multiple sessions at once."""
        db_session = self.get_session()
        try:
            session_ids = []
            for sess_data in sessions_data:
                session_id = self.generate_id()
                session_ids.append(session_id)
                
                # Parse session type
                session_type = SessionType[sess_data['type']]
                
                new_session = PartialDaySession(
                    id=session_id,
                    placement_id=sess_data['placement_id'],
                    date=sess_data['date'] if isinstance(sess_data['date'], date) else datetime.fromisoformat(sess_data['date']).date(),
                    type=session_type,
                    periods=sess_data.get('periods', []),
                    time_start=sess_data.get('time_start'),
                    time_end=sess_data.get('time_end'),
                    location=sess_data.get('location', ''),
                    status=SessionStatus.scheduled,
                    notes=sess_data.get('notes', '')
                )
                db_session.add(new_session)
            
            db_session.commit()
            return session_ids
        finally:
            db_session.close()
    
    def generate_iss_full_day_sessions(self, placement_id: str, start_date: date, days_assigned: int, skip_weekends: bool = True) -> List[str]:
        """Generate ISS full-day sessions for traditional placements."""
        db_session = self.get_session()
        try:
            session_ids = []
            current_date = start_date
            days_created = 0
            
            while days_created < days_assigned:
                # Skip weekends if requested
                if skip_weekends and self.is_non_school_day(current_date):
                    current_date += timedelta(days=1)
                    continue
                
                session_id = self.generate_id()
                session_ids.append(session_id)
                
                new_session = PartialDaySession(
                    id=session_id,
                    placement_id=placement_id,
                    date=current_date,
                    type=SessionType.iss_full_day,
                    location='ISS Room',
                    status=SessionStatus.scheduled
                )
                db_session.add(new_session)
                
                days_created += 1
                current_date += timedelta(days=1)
            
            db_session.commit()
            return session_ids
        finally:
            db_session.close()
    
    def generate_lunch_detention_sessions(self, placement_id: str, start_date: date, end_date: date, skip_weekends: bool = True) -> List[str]:
        """Generate lunch detention sessions for lunch detention placements within a date range."""
        db_session = self.get_session()
        try:
            session_ids = []
            current_date = start_date
            
            # Iterate through the entire date range
            while current_date <= end_date:
                # Skip weekends if requested
                if skip_weekends and self.is_non_school_day(current_date):
                    current_date += timedelta(days=1)
                    continue
                
                session_id = self.generate_id()
                session_ids.append(session_id)
                
                new_session = PartialDaySession(
                    id=session_id,
                    placement_id=placement_id,
                    date=current_date,
                    type=SessionType.lunch,
                    location='Cafeteria',
                    status=SessionStatus.scheduled
                )
                db_session.add(new_session)
                
                current_date += timedelta(days=1)
            
            db_session.commit()
            return session_ids
        finally:
            db_session.close()
    
    def calculate_scheduled_lunch_dates(self, start_date: date, num_days: int) -> List[date]:
        """Calculate scheduled lunch dates, skipping weekends and no-lunch days.
        
        Args:
            start_date: The first date to start scheduling from
            num_days: Number of lunch detention days needed
            
        Returns:
            List of scheduled lunch dates (weekdays only)
        """
        scheduled_dates = []
        current_date = start_date
        
        while len(scheduled_dates) < num_days:
            # Skip weekends
            if not self.is_non_school_day(current_date):
                # TODO: Add logic to skip specific no-lunch days (early dismissal, etc.)
                # For now, just add all weekdays with lunch
                scheduled_dates.append(current_date)
            
            current_date += timedelta(days=1)
        
        return scheduled_dates

    def _sync_lunch_detention_schedule_for_absences(self, session, placement, *, trim_extras: bool) -> None:
        """
        Ensure multi-day Lunch Detention has enough scheduled dates to still deliver
        `days_assigned` SERVED days when absences occur (ISS-style).
        """
        try:
            if placement.placement_type != PlacementCategory.LUNCH_DETENTION:
                return

            days_assigned = int(placement.days_assigned or 1)
            if days_assigned <= 1:
                return

            scheduled = list(placement.scheduled_lunch_dates) if placement.scheduled_lunch_dates else []
            served = set(list(placement.served_dates) if placement.served_dates else [])

            absent_count = session.query(DailyLog).filter(
                DailyLog.placement_id == placement.id,
                DailyLog.day_type == 'absent'
            ).count()

            required_slots = days_assigned + absent_count

            if not scheduled:
                start = placement.start_date
                if not start:
                    return
                scheduled = [
                    d.isoformat()
                    for d in self.calculate_scheduled_lunch_dates(start, required_slots)
                ]
                placement.scheduled_lunch_dates = scheduled
                placement.end_date = datetime.fromisoformat(scheduled[-1]).date()
                return

            if len(scheduled) < required_slots:
                last_date = datetime.fromisoformat(scheduled[-1]).date()
                need = required_slots - len(scheduled)
                extra = self.calculate_scheduled_lunch_dates(last_date + timedelta(days=1), need)
                scheduled.extend([d.isoformat() for d in extra])
                placement.scheduled_lunch_dates = scheduled
                placement.end_date = datetime.fromisoformat(scheduled[-1]).date()

            if trim_extras and len(scheduled) > required_slots:
                while len(scheduled) > required_slots:
                    last_str = scheduled[-1]
                    last_date = datetime.fromisoformat(last_str).date()

                    if last_str in served:
                        break

                    log_exists = session.query(DailyLog).filter(
                        DailyLog.placement_id == placement.id,
                        DailyLog.date == last_date
                    ).first()
                    if log_exists:
                        break

                    scheduled.pop()

                placement.scheduled_lunch_dates = scheduled
                placement.end_date = datetime.fromisoformat(scheduled[-1]).date()

        except Exception:
            return
    
    def generate_lunch_detention_sessions_from_scheduled(self, placement_id: str, scheduled_dates: List[date]) -> List[str]:
        """Generate lunch detention sessions from a pre-calculated list of scheduled dates.
        
        Args:
            placement_id: The placement ID
            scheduled_dates: List of dates on which lunch detention is scheduled
            
        Returns:
            List of created session IDs
        """
        db_session = self.get_session()
        try:
            session_ids = []
            
            for lunch_date in scheduled_dates:
                session_id = self.generate_id()
                session_ids.append(session_id)
                
                new_session = PartialDaySession(
                    id=session_id,
                    placement_id=placement_id,
                    date=lunch_date,
                    type=SessionType.lunch,
                    location='Cafeteria',
                    status=SessionStatus.scheduled
                )
                db_session.add(new_session)
            
            db_session.commit()
            return session_ids
        finally:
            db_session.close()
    
    def generate_partial_iss_session(self, placement_id: str, iss_date: date, start_period: int, end_period: int) -> str:
        """Generate a single partial-day ISS session for a specific date and period range."""
        db_session = self.get_session()
        try:
            session_id = self.generate_id()
            
            # Create list of periods (e.g., start=2, end=4 -> [2, 3, 4])
            periods = list(range(start_period, end_period + 1))
            
            new_session = PartialDaySession(
                id=session_id,
                placement_id=placement_id,
                date=iss_date,
                type=SessionType.periods,
                periods=periods,
                location='ISS Room',
                status=SessionStatus.scheduled
            )
            db_session.add(new_session)
            
            db_session.commit()
            return session_id
        finally:
            db_session.close()
    
    def generate_class_referral_session(self, placement_id: str, referral_date: date, start_period: int, end_period: int) -> str:
        """Generate a single class period referral session for a specific date and period range."""
        db_session = self.get_session()
        try:
            session_id = self.generate_id()
            
            # Create list of periods (e.g., start=2, end=4 -> [2, 3, 4])
            periods = list(range(start_period, end_period + 1))
            
            new_session = PartialDaySession(
                id=session_id,
                placement_id=placement_id,
                date=referral_date,
                type=SessionType.referral,
                periods=periods,
                location='Classroom',
                status=SessionStatus.scheduled
            )
            db_session.add(new_session)
            
            db_session.commit()
            return session_id
        finally:
            db_session.close()
    
    def generate_cooldown_session(self, placement_id: str, cooldown_date: date, start_period: int, end_period: int) -> str:
        """Generate a single cool-down session for a specific date and period range."""
        db_session = self.get_session()
        try:
            session_id = self.generate_id()
            
            # Create list of periods (e.g., start=2, end=4 -> [2, 3, 4])
            periods = list(range(start_period, end_period + 1))
            
            new_session = PartialDaySession(
                id=session_id,
                placement_id=placement_id,
                date=cooldown_date,
                type=SessionType.cool_down,
                periods=periods,
                location='Cool-Down Room',
                status=SessionStatus.scheduled
            )
            db_session.add(new_session)
            
            db_session.commit()
            return session_id
        finally:
            db_session.close()
    
    def generate_preplanned_sessions(self, placement_id: str, scheduled_slots: List[Dict[str, Any]]) -> List[str]:
        """Generate multiple sessions from a list of scheduled date+period combinations.
        
        Args:
            placement_id: The placement ID
            scheduled_slots: List of dicts with 'date' (ISO string) and 'period' (int)
            
        Returns:
            List of created session IDs
        """
        db_session = self.get_session()
        try:
            session_ids = []
            
            for slot in scheduled_slots:
                session_id = self.generate_id()
                session_ids.append(session_id)
                
                # Convert date string to date object
                slot_date = datetime.fromisoformat(slot['date']).date()
                period = slot['period']
                
                new_session = PartialDaySession(
                    id=session_id,
                    placement_id=placement_id,
                    date=slot_date,
                    type=SessionType.periods,
                    periods=[period],
                    location='Office/Grotto',
                    status=SessionStatus.scheduled
                )
                db_session.add(new_session)
            
            db_session.commit()
            return session_ids
        finally:
            db_session.close()
    
    def get_referral_periods_for_date(self, placement_id: str, target_date: date) -> List[int]:
        """Get all scheduled periods for a Behavior/Cool-Down referral on a specific date.
        
        Args:
            placement_id: The placement ID
            target_date: The date to check
            
        Returns:
            Sorted list of period numbers scheduled for that date
        """
        db_session = self.get_session()
        try:
            # Query all sessions for this placement on the target date
            sessions = db_session.query(PartialDaySession).filter(
                PartialDaySession.placement_id == placement_id,
                PartialDaySession.date == target_date
            ).all()
            
            # Collect all periods from all sessions
            all_periods = set()
            for sess in sessions:
                if sess.periods:
                    all_periods.update(sess.periods)
            
            return sorted(list(all_periods))
        finally:
            db_session.close()
    
    def get_partial_day_sessions_for_placement(self, placement_id: str) -> list:
        """Return all PartialDaySession rows for a placement as dicts.

        Used by Completed Placements archive to reconstruct schedules for Pre-Planned referrals.
        """
        db_session = self.get_session()
        try:
            sessions = db_session.query(PartialDaySession).filter(
                PartialDaySession.placement_id == placement_id
            ).order_by(PartialDaySession.date.asc()).all()

            results = []
            for s in sessions:
                results.append({
                    "date": s.date.isoformat() if s.date else None,
                    "type": s.type.value if getattr(s, "type", None) else None,
                    "periods": s.periods or []
                })
            return results
        finally:
            db_session.close()

    def get_partial_day_sessions(self, placement_id: str) -> list:
        """
        Backward-compatible alias.

        Some dashboard/debug code calls `get_partial_day_sessions(...)`.
        The canonical method is `get_partial_day_sessions_for_placement(...)`.

        This alias prevents AttributeError without changing any behavior.
        """
        return self.get_partial_day_sessions_for_placement(placement_id)
    
    def add_periods_to_referral(self, placement_id: str, target_date: date, new_periods: List[int]) -> bool:
        """Add additional periods to a Behavior/Cool-Down referral for a specific date.
        
        Args:
            placement_id: The placement ID
            target_date: The date to add periods to (must match placement start_date)
            new_periods: List of new period numbers to add
            
        Returns:
            True if periods were added successfully
        """
        db_session = self.get_session()
        try:
            # Get the placement to verify type and get current periods
            placement = db_session.query(Placement).filter(Placement.id == placement_id).first()
            if not placement:
                return False
            
            # Only allow for Behavior and Cool-Down referrals
            referral_subtype = placement.referral_subtype or ''
            if referral_subtype not in ['behavior', 'cool_down']:
                return False
            
            # Get existing session for this date
            existing_session = db_session.query(PartialDaySession).filter(
                PartialDaySession.placement_id == placement_id,
                PartialDaySession.date == target_date
            ).first()
            
            if existing_session:
                # Update existing session by adding new periods
                current_periods = set(existing_session.periods or [])
                updated_periods = sorted(list(current_periods.union(set(new_periods))))
                existing_session.periods = updated_periods
                
                # Update placement start_period and end_period to reflect the full range
                placement.start_period = min(updated_periods)
                placement.end_period = max(updated_periods)
            else:
                # Create a new session with the new periods (shouldn't happen for same-day referrals, but handle it)
                session_type = SessionType.referral if referral_subtype == 'behavior' else SessionType.cool_down
                location = 'Classroom' if referral_subtype == 'behavior' else 'Cool-Down Room'
                
                new_session = PartialDaySession(
                    id=self.generate_id(),
                    placement_id=placement_id,
                    date=target_date,
                    type=session_type,
                    periods=sorted(new_periods),
                    location=location,
                    status=SessionStatus.scheduled
                )
                db_session.add(new_session)
                
                # Update placement start_period and end_period
                all_periods = sorted(new_periods)
                placement.start_period = min(all_periods)
                placement.end_period = max(all_periods)
            
            db_session.commit()
            return True
        except Exception as e:
            db_session.rollback()
            print(f"[ERROR] Failed to add periods to referral: {str(e)}")
            return False
        finally:
            db_session.close()
    
    def get_todays_sessions(self) -> List[Dict[str, Any]]:
        """Get all sessions scheduled for today with student and placement info."""
        db_session = self.get_session()
        try:
            today = central_today()
            sessions = db_session.query(PartialDaySession).filter(
                PartialDaySession.date == today,
                PartialDaySession.status.in_([SessionStatus.scheduled, SessionStatus.in_progress])
            ).all()
            
            result = []
            for sess in sessions:
                # Get placement and student info
                placement = db_session.query(Placement).filter(Placement.id == sess.placement_id).first()
                if placement:
                    student = db_session.query(Student).filter(Student.id == placement.student_id).first()
                    if student:
                        # Format scope based on session type
                        scope = ""
                        if sess.type == SessionType.periods:
                            if sess.periods:
                                period_list = ", ".join([f"P{p}" for p in sess.periods])
                                scope = period_list
                        elif sess.type == SessionType.lunch:
                            scope = "Lunch"
                        elif sess.type == SessionType.cool_down:
                            if sess.time_start and sess.time_end:
                                scope = f"{sess.time_start}–{sess.time_end}"
                            else:
                                scope = "Cool-down"
                        elif sess.type == SessionType.referral:
                            if sess.periods and len(sess.periods) > 0:
                                scope = f"P{sess.periods[0]}"
                            else:
                                scope = "Referral"
                        elif sess.type == SessionType.iss_full_day:
                            scope = "Full Day"
                        
                        result.append({
                            'session_id': sess.id,
                            'placement_id': sess.placement_id,
                            'student_name': f"{student.first_name} {student.last_name[0]}",
                            'student_full_name': f"{student.first_name} {student.last_name}",
                            'scope': scope,
                            'type': sess.type.value,
                            'location': sess.location or ''
                        })
            
            return result
        finally:
            db_session.close()
    
    def get_iss_sessions_for_date(self, target_date: date) -> List[Dict[str, Any]]:
        """Get all ISS sessions scheduled for a specific date with student and placement info.
        
        Includes both active and scheduled placements so Dashboard can show:
        - Active placements: fully interactive cards
        - Scheduled (future) placements: locked cards with 'First Check-In Date' label
        """
        db_session = self.get_session()
        try:
            sessions = db_session.query(PartialDaySession).filter(
                PartialDaySession.date == target_date,
                PartialDaySession.type == SessionType.iss_full_day
            ).all()
            
            result = []
            for sess in sessions:
                placement = db_session.query(Placement).filter(Placement.id == sess.placement_id).first()
                # Include active, scheduled, needs_makeup, AND completed placements
                # Completed placements should still show on dates within their scheduled range
                if placement and placement.status in [PlacementStatus.active, PlacementStatus.scheduled, PlacementStatus.needs_makeup, PlacementStatus.completed]:
                    student = db_session.query(Student).filter(Student.id == placement.student_id).first()
                    if student:
                        periods = sess.periods if sess.periods else list(range(1, 11))
                        if len(periods) == 10 and periods == list(range(1, 11)):
                            period_display = "Full Day (Periods 1–10)"
                        elif len(periods) == 1:
                            period_display = f"Period {periods[0]}"
                        else:
                            period_display = f"Periods {min(periods)}–{max(periods)}"
                        
                        # Derive ISS status based on periods served
                        iss_total_required = placement.iss_total_required_periods or 0
                        iss_periods_served = placement.iss_periods_served or 0
                        is_placement_completed = placement.status == PlacementStatus.completed
                        if is_placement_completed or (iss_total_required > 0 and iss_periods_served >= iss_total_required):
                            iss_status = "Completed"
                        elif iss_periods_served > 0:
                            iss_status = "In Progress"
                        else:
                            iss_status = "Not Started"
                        
                        result.append({
                            'session_id': sess.id,
                            'placement_id': sess.placement_id,
                            'student_id': student.id,
                            'student_name': f"{student.first_name} {student.last_name}",
                            'student_first_name': student.first_name,
                            'student_last_name': student.last_name,
                            'grade': student.grade,
                            'homeroom_teacher': student.homeroom_teacher,
                            'period_display': period_display,
                            'periods': periods,
                            'date': sess.date.isoformat(),
                            'status': sess.status.value,
                            'iss_total_days': placement.iss_total_days,
                            'iss_remaining_days': placement.iss_remaining_days,
                            'reason': placement.reason,
                            'placement_status': placement.status.value,
                            'start_date': placement.start_date.isoformat() if placement.start_date else None,
                            'iss_days_assigned': placement.iss_days_assigned,
                            'iss_total_required_periods': placement.iss_total_required_periods,
                            'iss_periods_served': placement.iss_periods_served or 0,
                            'days_completed': placement.days_completed or 0,
                            'issStatus': iss_status,  # Derived status field
                            'progressStatus': placement.progress_status.value if placement.progress_status else PlacementProgressStatus.NOT_STARTED.value
                        })
            
            return result
        finally:
            db_session.close()
    
    def get_scheduled_iss_placements(self) -> List[Dict[str, Any]]:
        """Get all scheduled ISS placements that haven't started yet.
        
        These are placements with status='scheduled' and start_date in the future.
        Used to display locked cards on the Dashboard before the start date.
        """
        db_session = self.get_session()
        try:
            today = central_today()
            placements = db_session.query(Placement).filter(
                Placement.status == PlacementStatus.scheduled,
                Placement.placement_type == PlacementCategory.ISS,
                Placement.start_date > today
            ).all()
            
            result = []
            for placement in placements:
                student = db_session.query(Student).filter(Student.id == placement.student_id).first()
                if student:
                    result.append({
                        'placement_id': placement.id,
                        'student_id': student.id,
                        'student_name': f"{student.first_name} {student.last_name}",
                        'student_first_name': student.first_name,
                        'student_last_name': student.last_name,
                        'grade': student.grade,
                        'homeroom_teacher': student.homeroom_teacher,
                        'iss_total_days': placement.iss_total_days,
                        'iss_days_assigned': placement.iss_days_assigned,
                        'reason': placement.reason,
                        'placement_status': 'scheduled',
                        'start_date': placement.start_date.isoformat() if placement.start_date else None
                    })
            
            return result
        finally:
            db_session.close()
    
    def get_session_details(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get detailed information about a specific session."""
        db_session = self.get_session()
        try:
            sess = db_session.query(PartialDaySession).filter(PartialDaySession.id == session_id).first()
            if not sess:
                return None
            
            # Get placement and student info
            placement = db_session.query(Placement).filter(Placement.id == sess.placement_id).first()
            if not placement:
                return None
            
            student = db_session.query(Student).filter(Student.id == placement.student_id).first()
            if not student:
                return None
            
            # Format scope based on session type
            scope = ""
            if sess.type == SessionType.periods:
                if sess.periods:
                    period_list = ", ".join([f"P{p}" for p in sess.periods])
                    scope = period_list
            elif sess.type == SessionType.lunch:
                scope = "Lunch"
            elif sess.type == SessionType.cool_down:
                if sess.time_start and sess.time_end:
                    scope = f"{sess.time_start}–{sess.time_end}"
                else:
                    scope = "Cool-down"
            elif sess.type == SessionType.referral:
                if sess.periods and len(sess.periods) > 0:
                    scope = f"P{sess.periods[0]}"
                else:
                    scope = "Referral"
            elif sess.type == SessionType.iss_full_day:
                scope = "Full Day"
            
            return {
                'session_id': sess.id,
                'placement_id': sess.placement_id,
                'student_id': student.id,
                'student_name': f"{student.first_name} {student.last_name}",
                'student_first_name': student.first_name,
                'student_last_name': student.last_name,
                'scope': scope,
                'type': sess.type.value,
                'type_label': sess.type.value.replace('_', ' ').title(),
                'date': sess.date.isoformat(),
                'location': sess.location or '',
                'status': sess.status.value,
                'alert_flag': sess.alert_flag
            }
        finally:
            db_session.close()
    
    def update_session_status(self, session_id: str, new_status: str, set_alert: bool = False) -> bool:
        """Update session status with validation."""
        db_session = self.get_session()
        try:
            sess = db_session.query(PartialDaySession).filter(PartialDaySession.id == session_id).first()
            if not sess:
                return False
            
            # Validate status transition
            valid_transitions = {
                'scheduled': ['in_progress', 'no_show'],
                'in_progress': ['fulfilled'],
                'fulfilled': [],
                'no_show': []
            }
            
            current_status = sess.status.value
            if new_status not in valid_transitions.get(current_status, []):
                return False
            
            # Update status
            sess.status = SessionStatus[new_status]
            
            # Set alert flag for no-show
            if set_alert:
                sess.alert_flag = True
            
            db_session.commit()
            return True
        except Exception as e:
            db_session.rollback()
            return False
        finally:
            db_session.close()
    
    def mark_session_completed(self, session_id: str, completed_by: str, is_override: bool = False, override_comment: str = None) -> bool:
        """Mark a session as completed (fulfilled) and update daily log."""
        db_session = self.get_session()
        try:
            sess = db_session.query(PartialDaySession).filter(PartialDaySession.id == session_id).first()
            if not sess:
                return False
            
            sess.status = SessionStatus.fulfilled
            
            date_obj = sess.date
            placement_id = sess.placement_id
            
            log = db_session.query(DailyLog).filter(
                DailyLog.placement_id == placement_id,
                DailyLog.date == date_obj
            ).first()
            
            if not log:
                log_id = self.generate_id()
                log = DailyLog(
                    id=log_id,
                    placement_id=placement_id,
                    date=date_obj,
                    positive_total=0,
                    negative_total=0,
                    daily_total=0,
                    readiness='continue'
                )
                db_session.add(log)
            
            log.daily_fulfillment = 'yes'
            log.finalized_by = completed_by
            log.finalized_at = central_now_naive()
            
            if is_override:
                log.override_used = True
                if override_comment:
                    log.override_comment = override_comment
                    existing_notes = log.notes or ''
                    if existing_notes:
                        log.notes = f"{existing_notes}\n\n{override_comment}"
                    else:
                        log.notes = override_comment
            
            db_session.commit()
            return True
        except Exception as e:
            db_session.rollback()
            return False
        finally:
            db_session.close()
    
    def mark_session_no_show(self, session_id: str) -> bool:
        """Mark a session as no_show (not completed by end of day) and update daily log."""
        db_session = self.get_session()
        try:
            sess = db_session.query(PartialDaySession).filter(PartialDaySession.id == session_id).first()
            if not sess:
                return False
            
            sess.status = SessionStatus.no_show
            sess.alert_flag = True
            sess.alert_sent = True
            sess.alert_timestamp = central_now_naive()
            
            date_obj = sess.date
            placement_id = sess.placement_id
            
            log = db_session.query(DailyLog).filter(
                DailyLog.placement_id == placement_id,
                DailyLog.date == date_obj
            ).first()
            
            if not log:
                log_id = self.generate_id()
                log = DailyLog(
                    id=log_id,
                    placement_id=placement_id,
                    date=date_obj,
                    positive_total=0,
                    negative_total=0,
                    daily_total=0,
                    readiness='continue'
                )
                db_session.add(log)
            
            log.daily_fulfillment = 'no'
            log.alert_flag = True
            
            db_session.commit()
            return True
        except Exception as e:
            db_session.rollback()
            return False
        finally:
            db_session.close()
    
    def calculate_iss_days_progress(self, placement_id: str, up_to_date: date = None) -> Dict[str, Any]:
        """Calculate ISS days progress for a placement up to a given date.
        
        Returns dict with:
        - total_days: Total ISS days assigned (Y)
        - completed_days: Sum of completed days (X) - full days = 1.0, partial = periods/10
        - remaining_days: total_days - completed_days
        - sessions_completed: Number of sessions completed
        - sessions_overridden: Number of sessions with override
        """
        db_session = self.get_session()
        try:
            placement = db_session.query(Placement).filter(Placement.id == placement_id).first()
            if not placement:
                return {'total_days': 0, 'completed_days': 0, 'remaining_days': 0, 'sessions_completed': 0, 'sessions_overridden': 0}
            
            total_days = placement.iss_total_days or 0
            
            if up_to_date is None:
                up_to_date = central_now_naive().date()
            
            sessions = db_session.query(PartialDaySession).filter(
                PartialDaySession.placement_id == placement_id,
                PartialDaySession.type == SessionType.iss_full_day,
                PartialDaySession.date <= up_to_date,
                PartialDaySession.status == SessionStatus.fulfilled
            ).all()
            
            completed_days = 0.0
            sessions_completed = 0
            sessions_overridden = 0
            
            for sess in sessions:
                periods = sess.periods if sess.periods else list(range(1, 11))
                num_periods = len(periods)
                
                if num_periods == 10 and periods == list(range(1, 11)):
                    day_value = 1.0
                else:
                    day_value = num_periods / 10.0
                
                completed_days += day_value
                sessions_completed += 1
                
                log = db_session.query(DailyLog).filter(
                    DailyLog.placement_id == placement_id,
                    DailyLog.date == sess.date
                ).first()
                if log and log.override_used:
                    sessions_overridden += 1
            
            remaining_days = max(0, total_days - completed_days)
            
            return {
                'total_days': total_days,
                'completed_days': round(completed_days, 1),
                'remaining_days': round(remaining_days, 1),
                'sessions_completed': sessions_completed,
                'sessions_overridden': sessions_overridden
            }
        finally:
            db_session.close()
    
    def calculate_iss_checkin_progress(self, placement_id: str, up_to_date: date = None) -> Dict[str, Any]:
        """Calculate ISS days progress based on check-ins for a placement.
        
        The 'Day X of Y Days' counter advances when Check In is pressed,
        not when the day is completed.
        
        Returns dict with:
        - total_days: Total ISS days assigned (Y)
        - checked_in_days: Number of days where student was checked in (X)
        - remaining_days: total_days - checked_in_days
        """
        db_session = self.get_session()
        try:
            placement = db_session.query(Placement).filter(Placement.id == placement_id).first()
            if not placement:
                return {'total_days': 0, 'checked_in_days': 0, 'remaining_days': 0}
            
            # Use iss_days_assigned as primary source, fallback to iss_total_days
            total_days = placement.iss_days_assigned or placement.iss_total_days or 0
            
            if up_to_date is None:
                up_to_date = central_now_naive().date()
            
            checked_in_count = db_session.query(DailyLog).filter(
                DailyLog.placement_id == placement_id,
                DailyLog.date <= up_to_date,
                DailyLog.checked_in == True
            ).count()
            
            remaining_days = max(0, total_days - checked_in_count)
            
            return {
                'total_days': total_days,
                'checked_in_days': checked_in_count,
                'remaining_days': remaining_days
            }
        finally:
            db_session.close()
    
    # ==========================================
    # DAYS SERVED HELPER FUNCTIONS
    # ==========================================
    # These helpers count days actually served (present + completed),
    # NOT calendar days. Used for "Day X of Y" display.
    
    def get_iss_days_served_info(self, placement_id: str, target_date: str = None) -> Dict[str, Any]:
        """Get ISS days served information for Day X of Y display.
        
        A day is counted as "served" when:
        - Student was present (checked_in=True AND day_type != 'absent')
        - The day was completed (daily_fulfillment='yes')
        
        Args:
            placement_id: ID of the placement
            target_date: ISO format date string for the current/target date (optional)
            
        Returns:
            Dict with:
            - days_served_completed: Count of previous days that are present + completed
            - total_days: Total required ISS days
            - is_today_in_progress: True if target_date is checked in but not completed
            - is_today_absent: True if target_date is marked absent
            - is_today_completed: True if target_date is completed
            - current_day_number: The X in "Day X of Y" to display
        """
        db_session = self.get_session()
        try:
            placement = db_session.query(Placement).filter(Placement.id == placement_id).first()
            if not placement:
                return {'days_served_completed': 0, 'total_days': 0, 'is_today_in_progress': False, 
                        'is_today_absent': False, 'is_today_completed': False, 'current_day_number': 1}
            
            total_days = placement.iss_days_assigned or placement.iss_total_days or placement.days_assigned or 1
            
            target_date_obj = None
            if target_date:
                target_date_obj = datetime.fromisoformat(target_date).date() if isinstance(target_date, str) else target_date
            
            days_served_before_today = 0
            is_today_in_progress = False
            is_today_absent = False
            is_today_completed = False
            
            if target_date_obj:
                prior_completed_logs = db_session.query(DailyLog).filter(
                    DailyLog.placement_id == placement_id,
                    DailyLog.date < target_date_obj,
                    DailyLog.checked_in == True,
                    DailyLog.daily_fulfillment == 'yes',
                    or_(DailyLog.day_type != 'absent', DailyLog.day_type.is_(None))
                ).all()
                
                days_served_before_today = len(prior_completed_logs)
                
                today_log = db_session.query(DailyLog).filter(
                    DailyLog.placement_id == placement_id,
                    DailyLog.date == target_date_obj
                ).first()
                
                if today_log:
                    is_today_absent = today_log.day_type == 'absent'
                    is_today_completed = (today_log.checked_in == True and 
                                         today_log.daily_fulfillment == 'yes' and 
                                         today_log.day_type != 'absent')
                    is_today_in_progress = (today_log.checked_in == True and 
                                           today_log.daily_fulfillment != 'yes' and 
                                           today_log.day_type != 'absent')
            
            if is_today_completed:
                current_day_number = days_served_before_today + 1
            elif is_today_in_progress:
                current_day_number = days_served_before_today + 1
            elif is_today_absent:
                current_day_number = days_served_before_today + 1
            else:
                current_day_number = min(days_served_before_today + 1, total_days)
            
            return {
                'days_served_completed': days_served_before_today,
                'total_days': total_days,
                'is_today_in_progress': is_today_in_progress,
                'is_today_absent': is_today_absent,
                'is_today_completed': is_today_completed,
                'current_day_number': current_day_number
            }
        finally:
            db_session.close()
    
    def get_lunch_detention_days_served_info(self, placement_id: str, target_date: str = None) -> Dict[str, Any]:
        """Get Lunch Detention days served information for Day X of Y display.
        
        A day is counted as "served" when:
        - The date is in served_dates (student was present)
        - The day was completed (daily_fulfillment='yes')
        
        Args:
            placement_id: ID of the placement
            target_date: ISO format date string for the current/target date (optional)
            
        Returns:
            Dict with:
            - days_served_completed: Count of previous days that are present + completed
            - total_days: Total required Lunch Detention days
            - is_today_in_progress: True if target_date is checked in but not completed
            - is_today_absent: True if target_date is marked absent
            - is_today_completed: True if target_date is completed
            - current_day_number: The X in "Day X of Y" to display
        """
        db_session = self.get_session()
        try:
            placement = db_session.query(Placement).filter(Placement.id == placement_id).first()
            if not placement:
                return {'days_served_completed': 0, 'total_days': 0, 'is_today_in_progress': False,
                        'is_today_absent': False, 'is_today_completed': False, 'current_day_number': 1}
            
            total_days = placement.days_assigned or 1
            served_dates = list(placement.served_dates) if placement.served_dates else []
            
            target_date_obj = None
            target_date_str = None
            if target_date:
                target_date_obj = datetime.fromisoformat(target_date).date() if isinstance(target_date, str) else target_date
                target_date_str = target_date_obj.isoformat() if hasattr(target_date_obj, 'isoformat') else str(target_date_obj)
            
            days_served_before_today = 0
            is_today_in_progress = False
            is_today_absent = False
            is_today_completed = False
            
            if target_date_obj:
                for served_date_str in served_dates:
                    served_date_obj = datetime.fromisoformat(served_date_str).date()
                    if served_date_obj < target_date_obj:
                        log = db_session.query(DailyLog).filter(
                            DailyLog.placement_id == placement_id,
                            DailyLog.date == served_date_obj
                        ).first()
                        
                        if log and log.daily_fulfillment == 'yes' and log.day_type != 'absent':
                            days_served_before_today += 1
                
                today_log = db_session.query(DailyLog).filter(
                    DailyLog.placement_id == placement_id,
                    DailyLog.date == target_date_obj
                ).first()
                
                if today_log:
                    is_today_absent = today_log.day_type == 'absent'
                    is_today_completed = today_log.daily_fulfillment == 'yes' and today_log.day_type != 'absent'
                
                is_today_present = target_date_str in served_dates if target_date_str else False
                
                if is_today_present and not is_today_completed and not is_today_absent:
                    is_today_in_progress = True
            
            if is_today_completed:
                current_day_number = days_served_before_today + 1
            elif is_today_in_progress:
                current_day_number = days_served_before_today + 1
            elif is_today_absent:
                current_day_number = days_served_before_today + 1
            else:
                current_day_number = min(days_served_before_today + 1, total_days)
            
            return {
                'days_served_completed': days_served_before_today,
                'total_days': total_days,
                'is_today_in_progress': is_today_in_progress,
                'is_today_absent': is_today_absent,
                'is_today_completed': is_today_completed,
                'current_day_number': current_day_number
            }
        finally:
            db_session.close()
    
    def get_preplanned_days_served_info(self, placement_id: str, target_date: str = None) -> Dict[str, Any]:
        """Get Pre-Planned referral days served information for Day X of Y display.
        
        A day/slot is counted as "served" when:
        - Student was present (checked_in=True AND day_type != 'absent')
        - The day was completed (daily_fulfillment='yes')
        
        Args:
            placement_id: ID of the placement
            target_date: ISO format date string for the current/target date (optional)
            
        Returns:
            Dict with:
            - days_served_completed: Count of previous days that are present + completed
            - total_days: Total required Pre-Planned days
            - is_today_in_progress: True if target_date is checked in but not completed
            - is_today_absent: True if target_date is marked absent
            - is_today_completed: True if target_date is completed
            - current_day_number: The X in "Day X of Y" to display
        """
        db_session = self.get_session()
        try:
            placement = db_session.query(Placement).filter(Placement.id == placement_id).first()
            if not placement:
                return {'days_served_completed': 0, 'total_days': 0, 'is_today_in_progress': False,
                        'is_today_absent': False, 'is_today_completed': False, 'current_day_number': 1}
            
            total_days = placement.days_assigned or 1
            
            target_date_obj = None
            if target_date:
                target_date_obj = datetime.fromisoformat(target_date).date() if isinstance(target_date, str) else target_date
            
            days_served_before_today = 0
            is_today_in_progress = False
            is_today_absent = False
            is_today_completed = False
            
            if target_date_obj:
                prior_completed_logs = db_session.query(DailyLog).filter(
                    DailyLog.placement_id == placement_id,
                    DailyLog.date < target_date_obj,
                    DailyLog.checked_in == True,
                    DailyLog.daily_fulfillment == 'yes',
                    or_(DailyLog.day_type != 'absent', DailyLog.day_type.is_(None))
                ).all()
                
                days_served_before_today = len(prior_completed_logs)
                
                today_log = db_session.query(DailyLog).filter(
                    DailyLog.placement_id == placement_id,
                    DailyLog.date == target_date_obj
                ).first()
                
                if today_log:
                    is_today_absent = today_log.day_type == 'absent'
                    is_today_completed = (today_log.checked_in == True and 
                                         today_log.daily_fulfillment == 'yes' and 
                                         today_log.day_type != 'absent')
                    is_today_in_progress = (today_log.checked_in == True and 
                                           today_log.daily_fulfillment != 'yes' and 
                                           today_log.day_type != 'absent')
            
            if is_today_completed:
                current_day_number = days_served_before_today + 1
            elif is_today_in_progress:
                current_day_number = days_served_before_today + 1
            elif is_today_absent:
                current_day_number = days_served_before_today + 1
            else:
                current_day_number = min(days_served_before_today + 1, total_days)
            
            return {
                'days_served_completed': days_served_before_today,
                'total_days': total_days,
                'is_today_in_progress': is_today_in_progress,
                'is_today_absent': is_today_absent,
                'is_today_completed': is_today_completed,
                'current_day_number': current_day_number
            }
        finally:
            db_session.close()
    
    # ==========================================
    # ISS PERIOD HELPER FUNCTIONS (Normalized)
    # ==========================================
    # These helpers provide a single, consistent logic path for ISS period tracking.
    # Use these throughout the application instead of direct field access.
    
    def get_iss_total_periods_required(self, placement: dict) -> int:
        """Get total periods required for an ISS placement.
        
        Args:
            placement: Placement dict (from _placement_to_dict or similar)
            
        Returns:
            Total periods required for this ISS session.
            - Full-day ISS: 10 periods per scheduled day
            - Partial-day ISS: Sum of scheduled periods across all days
            - Multiday ISS: Sum of all scheduled periods
            
        Priority order:
        1. issTotalRequiredPeriods (authoritative stored value)
        2. Sum of scheduledIssSessions periods (for partial-day/multiday)
        3. days * 10 (fallback for legacy data)
        """
        if not placement:
            return 0
        
        # Priority 1: issTotalRequiredPeriods field (authoritative)
        total_required = placement.get('issTotalRequiredPeriods') or 0
        if total_required > 0:
            return total_required
        
        # Priority 2: Sum scheduled sessions (handles partial-day and multiday correctly)
        scheduled_sessions = placement.get('scheduledIssSessions') or []
        if scheduled_sessions:
            total_from_schedule = 0
            for session in scheduled_sessions:
                # Check for explicit periods array first (legacy format)
                periods_array = session.get('periods') or session.get('periodsCovered')
                if periods_array and isinstance(periods_array, list) and len(periods_array) > 0:
                    total_from_schedule += len(periods_array)
                    continue
                
                # Check for periodCount (legacy key)
                period_count = session.get('periodCount') or session.get('periodsCount')
                if period_count and isinstance(period_count, int) and period_count > 0:
                    total_from_schedule += period_count
                    continue
                
                # Check session type
                session_type = session.get('type', '')
                if session_type == 'full_day':
                    total_from_schedule += PERIODS_PER_FULL_DAY
                elif session_type in ('partial_day', 'partial'):
                    start_period = session.get('startPeriod', 1)
                    end_period = session.get('endPeriod', 10)
                    total_from_schedule += max(1, end_period - start_period + 1)
                elif not session_type:
                    # No type specified - infer from start/end or default to full day
                    start_period = session.get('startPeriod')
                    end_period = session.get('endPeriod')
                    if start_period is not None and end_period is not None:
                        total_from_schedule += max(1, end_period - start_period + 1)
                    else:
                        # Default to full day when no metadata
                        total_from_schedule += PERIODS_PER_FULL_DAY
                else:
                    # Unknown type, assume full day
                    total_from_schedule += PERIODS_PER_FULL_DAY
            if total_from_schedule > 0:
                return total_from_schedule
        
        # Priority 3: Fallback - Calculate from days assigned * 10
        days = placement.get('issDaysAssigned') or placement.get('issTotalDays') or placement.get('daysAssigned') or 0
        return days * PERIODS_PER_FULL_DAY
    
    def get_iss_periods_served(self, placement: dict) -> int:
        """Get cumulative periods served for an ISS placement.
        
        Args:
            placement: Placement dict (from _placement_to_dict or similar)
            
        Returns:
            Total periods served across all completed days.
            Initialized at 0 when placement is created.
            Incremented when a day is completed.
        """
        if not placement:
            return 0
        
        return placement.get('issPeriodsServed') or 0

    def get_iss_periods_served_through_date(self, placement_id: str, through_date: str) -> int:
        """Get periods served for an ISS placement through (and including) a given date.

        Used to make the Dashboard period summary *date-aware* when browsing past/future dates.

        Args:
            placement_id: Placement ID
            through_date: ISO date string (YYYY-MM-DD)

        Returns:
            Sum of periods_added for all completed DailyLog rows with date <= through_date.
            Includes make-up sessions (they also contribute periods_added when completed).
        """
        if not placement_id or not through_date:
            return 0

        try:
            cutoff_date = date.fromisoformat(str(through_date)[:10])
        except Exception:
            return 0

        with self.get_db_session() as session:
            from sqlalchemy import func
            total = session.query(func.coalesce(func.sum(DailyLog.periods_added), 0)).filter(
                DailyLog.placement_id == placement_id,
                DailyLog.daily_fulfillment == 'yes',
                DailyLog.periods_added.isnot(None),
                DailyLog.date <= cutoff_date
            ).scalar()
            return int(total or 0)

    def get_iss_period_math_for_date(self, placement: dict, placement_id: str, date_str: str) -> dict:
        """Return consistent ISS period math for a given dashboard date.

        Returns required/served/remaining (remaining accounts for periodsWaived).
        """
        total_required = self.get_iss_total_periods_required(placement)
        served = self.get_iss_periods_served_through_date(placement_id, date_str)
        waived = placement.get('periodsWaived') or 0
        remaining = max(0, total_required - served - waived)
        return {
            "required": int(total_required or 0),
            "served": int(served or 0),
            "remaining": int(remaining or 0),
            "waived": int(waived or 0),
        }
    
    def get_iss_periods_remaining(self, placement: dict) -> int:
        """Get periods remaining for an ISS placement.
        
        Args:
            placement: Placement dict (from _placement_to_dict or similar)
            
        Returns:
            Periods remaining = total_required - periods_served - periods_waived
            Never returns negative (guards against < 0).
            
        Accounts for early closure where periods may be waived.
        """
        total_required = self.get_iss_total_periods_required(placement)
        periods_served = self.get_iss_periods_served(placement)
        periods_waived = placement.get('periodsWaived') or 0
        
        return max(0, total_required - periods_served - periods_waived)
    
    def should_offer_makeup_days(self, placement: dict) -> bool:
        """Determine if make-up days should be offered for an ISS placement.
        
        This helper implements the trigger condition for prompting the user
        to add make-up days when a student hasn't completed all required periods
        after finishing all original scheduled dates.
        
        Args:
            placement: Placement dict (from _placement_to_dict or similar)
            
        Returns:
            True if all of the following conditions are met:
            1. The placement is ISS (multiday with original_day_count >= 1)
            2. Placement is NOT already in make-up mode (status != 'needs_makeup')
            3. All original scheduled dates are marked as completed
            4. session_periods_served < session_total_periods_required
            
            Otherwise returns False.
        """
        if not placement:
            return False
        
        # Check 1: Must be ISS placement
        placement_type = placement.get('placementType', '')
        if placement_type != 'ISS':
            return False
        
        # Check 2: If already in make-up mode (has scheduled make-up days), don't prompt again
        status = placement.get('status', '')
        if status == 'needs_makeup':
            return False
        
        # Check 3: Must be multiday ISS (original_day_count >= 1)
        original_day_count = placement.get('originalDayCount') or placement.get('issDaysAssigned') or 0
        if original_day_count < 1:
            return False
        
        # Check 4: Get periods served and required
        periods_served = self.get_iss_periods_served(placement)
        periods_required = self.get_iss_total_periods_required(placement)
        
        # If periods_served >= periods_required, no make-up needed
        if periods_served >= periods_required:
            return False
        
        # Check 4: All original scheduled dates must be completed
        # Get original scheduled dates (not make-up dates)
        scheduled_iss_dates = placement.get('scheduledIssDates') or []
        scheduled_sessions = placement.get('scheduledIssSessions') or []
        
        # Collect all original dates (non-make-up)
        original_dates = set()
        
        # From scheduled_iss_dates (simple date list)
        for date_str in scheduled_iss_dates:
            original_dates.add(date_str)
        
        # From scheduled_iss_sessions (detailed session list)
        for session in scheduled_sessions:
            is_makeup = session.get('isMakeup', False) or session.get('is_makeup', False)
            if not is_makeup:
                session_date = session.get('date', '')
                if session_date:
                    original_dates.add(session_date)
        
        # If no original dates found, can't determine - return False
        if not original_dates:
            return False
        
        # Query daily logs to check if all original dates are completed
        placement_id = placement.get('_id')
        if not placement_id:
            return False
        
        session = self.get_session()
        try:
            from sqlalchemy import and_
            
            # Get all daily logs for this placement
            logs = session.query(DailyLog).filter(
                DailyLog.placement_id == placement_id
            ).all()
            
            # Build a set of completed dates (daily_fulfillment = 'yes' and not absent)
            completed_dates = set()
            for log in logs:
                if log.daily_fulfillment == 'yes' and log.day_type != 'absent':
                    # Original sessions have is_makeup_session = False or NULL (legacy data)
                    # Only make-up sessions have is_makeup_session = True
                    is_makeup = log.is_makeup_session is True  # Explicitly True means make-up
                    if not is_makeup:  # Original session (False or NULL)
                        completed_dates.add(log.date.isoformat())
            
            # Check if all original dates are completed
            all_original_completed = original_dates.issubset(completed_dates)
            
            # Return True only if all original dates completed AND periods still remaining
            return all_original_completed
            
        finally:
            session.close()

    # =========================
    # STRICT MAKE-UP TRUTH (ISS ONLY)
    # =========================

    def get_iss_total_periods_required_strict(self, placement: dict) -> int:
        """
        Strict required periods = original day count * 10 (full-day expectation).
        This intentionally ignores partial-day schedules and overrides.
        """
        if not placement:
            return 0

        original_day_count = placement.get('originalDayCount') or placement.get('issDaysAssigned') or 0
        try:
            original_day_count = int(original_day_count)
        except Exception:
            original_day_count = 0

        return max(0, original_day_count * 10)

    def should_offer_makeup_days_strict(self, placement: dict) -> bool:
        """
        Strict trigger for offering make-up days (ISS only).

        Same intent as should_offer_makeup_days(), except the required total is computed
        as (original_day_count * 10) regardless of partial schedules/overrides.
        """
        if not placement:
            return False

        # Must be ISS placement
        if placement.get('placementType', '') != 'ISS':
            return False

        # If already in make-up mode, don't prompt again
        if placement.get('status', '') == 'needs_makeup':
            return False

        # Must have at least 1 assigned day
        original_day_count = placement.get('originalDayCount') or placement.get('issDaysAssigned') or 0
        if original_day_count < 1:
            return False

        # Strict served vs required
        periods_served = self.get_iss_periods_served(placement)
        periods_required_strict = self.get_iss_total_periods_required_strict(placement)

        if periods_served >= periods_required_strict:
            return False

        # Must have original scheduled dates (non-make-up)
        scheduled_iss_dates = placement.get('scheduledIssDates') or []
        scheduled_sessions = placement.get('scheduledIssSessions') or []

        original_dates = set()

        for date_str in scheduled_iss_dates:
            original_dates.add(date_str)

        for sess in scheduled_sessions:
            is_makeup = sess.get('isMakeup', False) or sess.get('is_makeup', False)
            if not is_makeup:
                d = sess.get('date', '')
                if d:
                    original_dates.add(d)

        if not original_dates:
            return False

        placement_id = placement.get('_id')
        if not placement_id:
            return False

        session = self.get_session()
        try:
            logs = session.query(DailyLog).filter(DailyLog.placement_id == placement_id).all()

            completed_dates = set()
            for log in logs:
                # Completed + present
                if log.daily_fulfillment == 'yes' and log.day_type != 'absent':
                    # Only explicit True means make-up; False/NULL = original day (legacy-safe)
                    is_makeup = (log.is_makeup_session is True)
                    if not is_makeup:
                        # DailyLog uses "date" (Date), while scheduled dates are stored as "YYYY-MM-DD" strings.
                        # Convert to ISO string so comparisons are consistent.
                        if log.date:
                            completed_dates.add(log.date.isoformat())

            # All original scheduled dates must be completed
            for d in original_dates:
                if d not in completed_dates:
                    return False

            return True
        finally:
            session.close()

    def check_iss_session_needs_makeup_strict(self, placement_id: str) -> Dict[str, Any]:
        """
        Strict version of check_iss_session_needs_makeup().

        Uses full-day expectation (originalDayCount * 10) to detect a shortfall
        even when partial-day schedules/overrides reduce the schedule-based required total.
        """
        session = self.get_session()
        try:
            placement = session.query(Placement).filter(Placement.id == placement_id).first()
            if not placement:
                return {'needsMakeup': False, 'isFinalDay': False}

            placement_dict = self._placement_to_dict(placement)

            needs_makeup = self.should_offer_makeup_days_strict(placement_dict)

            iss_days_assigned = placement_dict.get('originalDayCount') or placement_dict.get('issDaysAssigned') or 0
            periods_served = self.get_iss_periods_served(placement_dict)

            periods_required_strict = self.get_iss_total_periods_required_strict(placement_dict)
            periods_remaining_strict = max(0, periods_required_strict - periods_served)

            days_completed = placement_dict.get('daysCompleted') or 0
            is_final_day = days_completed >= iss_days_assigned

            return {
                'needsMakeup': needs_makeup,
                'isFinalDay': is_final_day,
                'periodsServed': periods_served,
                'periodsRequired': periods_required_strict,
                'periodsRemaining': periods_remaining_strict,
                'daysCompleted': days_completed,
                'daysAssigned': iss_days_assigned,
                'strictTruth': True
            }
        finally:
            session.close()

    def get_iss_scheduled_periods_for_date(self, placement: dict, target_date) -> int:
        """Get scheduled periods for a specific ISS date.
        
        Args:
            placement: Placement dict (from _placement_to_dict or similar)
            target_date: The date to check (date object or ISO string)
            
        Returns:
            Number of periods scheduled for this date:
            - Full-day: Returns 10 (PERIODS_PER_FULL_DAY)
            - Partial-day: Returns exact number from schedule builder
            - Legacy fallback: Returns 10 if date is in scheduled_iss_dates or date range
            
        This value is used to update periods_served when that date is completed.
        """
        if not placement:
            return 0
        
        # Convert target_date to string for comparison
        if hasattr(target_date, 'isoformat'):
            date_str = target_date.isoformat()
        else:
            date_str = str(target_date)
        
        # Check scheduled ISS sessions for this date
        scheduled_sessions = placement.get('scheduledIssSessions') or []
        
        for session in scheduled_sessions:
            session_date = session.get('date', '')
            
            # Match the date
            if session_date == date_str:
                # Check for explicit periods array first (legacy format)
                periods_array = session.get('periods') or session.get('periodsCovered')
                if periods_array and isinstance(periods_array, list) and len(periods_array) > 0:
                    return len(periods_array)
                
                # Check for periodCount (legacy key)
                period_count = session.get('periodCount') or session.get('periodsCount')
                if period_count and isinstance(period_count, int) and period_count > 0:
                    return period_count
                
                session_type = session.get('type', '')
                
                if session_type == 'full_day':
                    return PERIODS_PER_FULL_DAY
                elif session_type in ('partial_day', 'partial'):
                    # Calculate periods from start/end
                    start_period = session.get('startPeriod', 1)
                    end_period = session.get('endPeriod', 10)
                    return max(1, end_period - start_period + 1)
                elif not session_type:
                    # No type - infer from start/end or default to full day
                    start_period = session.get('startPeriod')
                    end_period = session.get('endPeriod')
                    if start_period is not None and end_period is not None:
                        return max(1, end_period - start_period + 1)
                    else:
                        return PERIODS_PER_FULL_DAY
                else:
                    # Unknown session type, assume full day
                    return PERIODS_PER_FULL_DAY
        
        # Legacy fallback: Check if date is in scheduled_iss_dates (older format)
        scheduled_dates = placement.get('scheduledIssDates') or []
        if date_str in scheduled_dates:
            return PERIODS_PER_FULL_DAY
        
        # Check if date falls within placement date range (implicit scheduling)
        start_date = placement.get('startDate') or placement.get('issStartDate')
        end_date = placement.get('endDate')
        if start_date and end_date:
            if start_date <= date_str <= end_date:
                # Date is in range, default to full day for legacy placements
                return PERIODS_PER_FULL_DAY
        
        # No scheduled session found for this date
        return 0
    
    def get_iss_status(self, placement: dict) -> str:
        """Get ISS status based on periods served and placement flags.
        
        Args:
            placement: Placement dict
            
        Returns:
            - 'Not Started': periods_served == 0 and not checked in
            - 'In Progress': periods_served > 0 AND remaining > 0
            - 'Needs Makeup': needs_makeup flag is set (authoritative, until cleared)
            - 'Completed': placement status is completed OR closed_early with waiver
        
        Respects placement progress_status, needs_makeup, and closed_early flags.
        needs_makeup is authoritative - stays until explicitly cleared.
        """
        if not placement:
            return 'Not Started'
        
        # Check explicit flags
        placement_status = placement.get('status', '')
        progress_status = placement.get('progressStatus', '')
        is_closed_early = placement.get('closedEarly', False)
        
        # needs_makeup is authoritative - stays until explicitly cleared
        # This takes priority over period calculations
        if placement_status == 'needs_makeup':
            return 'Needs Makeup'
        
        # Explicit completed status
        if placement_status == 'completed' or progress_status == 'COMPLETED':
            return 'Completed'
        
        # Closed early = Completed (periods were waived)
        if is_closed_early:
            return 'Completed'
        
        # Get period calculations for remaining cases
        periods_remaining = self.get_iss_periods_remaining(placement)
        periods_served = self.get_iss_periods_served(placement)
        
        # Calculate based on periods
        if periods_remaining == 0 and periods_served > 0:
            return 'Completed'
        elif periods_served > 0 or progress_status == 'IN_PROGRESS':
            return 'In Progress'
        else:
            return 'Not Started'
    
    # Daily Log operations
    def get_daily_log(self, placement_id: str, log_date: str) -> Optional[Dict[str, Any]]:
        """Get a daily log for a placement on a specific date (read-only, no create).
        
        Returns None if no log exists for this date.
        Use this for checking if a student is checked in without creating logs.
        """
        session = self.get_session()
        try:
            date_obj = datetime.fromisoformat(log_date).date() if isinstance(log_date, str) else log_date
            
            log = session.query(DailyLog).filter(
                DailyLog.placement_id == placement_id,
                DailyLog.date == date_obj
            ).first()
            
            if log:
                return self._daily_log_to_dict(log)
            return None
        finally:
            session.close()
    
    def get_or_create_daily_log(self, placement_id: str, log_date: str) -> Dict[str, Any]:
        """Get or create a daily log for a placement on a specific date."""
        session = self.get_session()
        try:
            date_obj = datetime.fromisoformat(log_date).date() if isinstance(log_date, str) else log_date
            
            log = session.query(DailyLog).filter(
                DailyLog.placement_id == placement_id,
                DailyLog.date == date_obj
            ).first()
            
            if log:
                return self._daily_log_to_dict(log)
            
            # Create new daily log
            log_id = self.generate_id()
            daily_log = DailyLog(
                id=log_id,
                placement_id=placement_id,
                date=date_obj,
                positive_total=0,
                negative_total=0,
                daily_total=0,
                readiness='continue'
            )
            session.add(daily_log)
            session.commit()
            return self._daily_log_to_dict(daily_log)
        finally:
            session.close()
    
    def update_daily_log_points(self, log_id: str, positive_points: int, negative_points: int) -> bool:
        """Update positive and negative points for a daily log."""
        session = self.get_session()
        try:
            log = session.query(DailyLog).filter(DailyLog.id == log_id).first()
            if log:
                log.positive_total = positive_points
                log.negative_total = negative_points
                log.daily_total = positive_points + negative_points
                session.commit()
                return True
            return False
        finally:
            session.close()
    
    def finalize_daily_log(self, log_id: str, finalized_by: str) -> bool:
        """Finalize a daily log."""
        session = self.get_session()
        try:
            log = session.query(DailyLog).filter(DailyLog.id == log_id).first()
            if log:
                log.finalized_by = finalized_by
                log.finalized_at = central_now_naive()
                session.commit()
                return True
            return False
        finally:
            session.close()
    
    def set_daily_fulfillment(self, log_id: str, fulfillment: str) -> bool:
        """Set daily fulfillment (yes/no) and handle days reduction or alert."""
        session = self.get_session()
        try:
            log = session.query(DailyLog).filter(DailyLog.id == log_id).first()
            if not log or not log.finalized_by:
                return False  # Can only set fulfillment after finalization
            
            # Check if we're changing the fulfillment value
            old_fulfillment = log.daily_fulfillment
            log.daily_fulfillment = fulfillment.lower()
            
            # Get the placement to update days_completed
            placement = session.query(Placement).filter(Placement.id == log.placement_id).first()
            if not placement:
                return False
            
            if fulfillment.lower() == 'yes':
                log.alert_flag = False
                # Increment days_completed if this is a new 'yes' or changed from 'no'
                if old_fulfillment != 'yes':
                    placement.days_completed = (placement.days_completed or 0) + 1
            else:  # 'no'
                log.alert_flag = True
                # Decrement days_completed if we're changing from 'yes' to 'no'
                if old_fulfillment == 'yes':
                    placement.days_completed = max(0, (placement.days_completed or 0) - 1)
            
            session.commit()
            return True
        finally:
            session.close()
    
    def update_daily_log_notes(self, placement_id: str, log_date: str, notes: str) -> bool:
        """Update notes for a daily log."""
        session = self.get_session()
        try:
            date_obj = datetime.fromisoformat(log_date).date() if isinstance(log_date, str) else log_date
            
            log = session.query(DailyLog).filter(
                DailyLog.placement_id == placement_id,
                DailyLog.date == date_obj
            ).first()
            
            if not log:
                log_id = self.generate_id()
                log = DailyLog(
                    id=log_id,
                    placement_id=placement_id,
                    date=date_obj,
                    positive_total=0,
                    negative_total=0,
                    daily_total=0,
                    readiness='continue',
                    notes=notes
                )
                session.add(log)
            else:
                log.notes = notes
            
            session.commit()
            return True
        finally:
            session.close()
    
    def update_daily_log_no_show(self, placement_id: str, log_date: str, no_show: bool) -> bool:
        """Update no_show flag for a daily log (for Pre-Planned Referral)."""
        session = self.get_session()
        try:
            date_obj = datetime.fromisoformat(log_date).date() if isinstance(log_date, str) else log_date
            
            log = session.query(DailyLog).filter(
                DailyLog.placement_id == placement_id,
                DailyLog.date == date_obj
            ).first()
            
            if not log:
                log_id = self.generate_id()
                log = DailyLog(
                    id=log_id,
                    placement_id=placement_id,
                    date=date_obj,
                    positive_total=0,
                    negative_total=0,
                    daily_total=0,
                    readiness='continue',
                    no_show=no_show
                )
                session.add(log)
            else:
                log.no_show = no_show
            
            session.commit()
            return True
        finally:
            session.close()
    
    def update_daily_log_no_show_note(self, placement_id: str, log_date: str, note: str) -> bool:
        """Update no_show_note for a daily log (for Pre-Planned Referral)."""
        session = self.get_session()
        try:
            date_obj = datetime.fromisoformat(log_date).date() if isinstance(log_date, str) else log_date
            
            log = session.query(DailyLog).filter(
                DailyLog.placement_id == placement_id,
                DailyLog.date == date_obj
            ).first()
            
            if not log:
                log_id = self.generate_id()
                log = DailyLog(
                    id=log_id,
                    placement_id=placement_id,
                    date=date_obj,
                    positive_total=0,
                    negative_total=0,
                    daily_total=0,
                    readiness='continue',
                    no_show=True,
                    no_show_note=note
                )
                session.add(log)
            else:
                log.no_show_note = note
            
            session.commit()
            return True
        finally:
            session.close()
    
    def complete_placement_day_no_show(self, placement_id: str, log_date: str, completed_by: str) -> bool:
        """Mark a placement day as complete with No Show status.
        
        Args:
            placement_id: ID of the placement
            log_date: ISO format date string
            completed_by: Name/ID of person completing
        """
        session = self.get_session()
        try:
            date_obj = datetime.fromisoformat(log_date).date() if isinstance(log_date, str) else log_date
            
            log = session.query(DailyLog).filter(
                DailyLog.placement_id == placement_id,
                DailyLog.date == date_obj
            ).first()
            
            if not log:
                log_id = self.generate_id()
                log = DailyLog(
                    id=log_id,
                    placement_id=placement_id,
                    date=date_obj,
                    positive_total=0,
                    negative_total=0,
                    daily_total=0,
                    readiness='continue',
                    daily_fulfillment='yes',
                    no_show=True,
                    finalized_by=completed_by,
                    finalized_at=central_now_naive()
                )
                session.add(log)
            else:
                old_fulfillment = log.daily_fulfillment
                log.daily_fulfillment = 'yes'
                log.no_show = True
                log.finalized_by = completed_by
                log.finalized_at = central_now_naive()
                
                placement = session.query(Placement).filter(Placement.id == placement_id).first()
                if placement and old_fulfillment != 'yes':
                    placement.days_completed = (placement.days_completed or 0) + 1
            
            session.commit()
            return True
        finally:
            session.close()
    
    def complete_placement_day(self, placement_id: str, log_date: str, completed_by: str, is_override: bool = False) -> bool:
        """Mark a placement day as complete by setting daily_fulfillment to 'yes'.
        
        This method supports retroactive completion - staff can mark incomplete
        records from past dates as complete while preserving alert history.
        
        Args:
            placement_id: ID of the placement
            log_date: ISO format date string
            completed_by: Name/ID of person completing
            is_override: True if using Override & Count Full (early release with full credit)
        """
        session = self.get_session()
        try:
            date_obj = datetime.fromisoformat(log_date).date() if isinstance(log_date, str) else log_date
            
            log = session.query(DailyLog).filter(
                DailyLog.placement_id == placement_id,
                DailyLog.date == date_obj
            ).first()
            
            if not log:
                log_id = self.generate_id()
                log = DailyLog(
                    id=log_id,
                    placement_id=placement_id,
                    date=date_obj,
                    positive_total=0,
                    negative_total=0,
                    daily_total=0,
                    readiness='continue',
                    daily_fulfillment='yes',
                    finalized_by=completed_by,
                    finalized_at=central_now_naive(),
                    override_used=is_override
                )
                session.add(log)
                
                # Increment days_completed when creating new completed log
                placement = session.query(Placement).filter(Placement.id == placement_id).first()
                if placement:
                    placement.days_completed = (placement.days_completed or 0) + 1
                    
                    # Auto-complete Lunch Detention when all days are completed
                    if placement.placement_type == PlacementCategory.LUNCH_DETENTION:
                        days_assigned = placement.days_assigned or 1
                        if placement.days_completed >= days_assigned:
                            placement.status = PlacementStatus.completed
                            placement.progress_status = PlacementProgressStatus.COMPLETED
                            placement.end_date = date_obj
                        else:
                            # Set to IN_PROGRESS when completing a day but not yet finished
                            if placement.progress_status != PlacementProgressStatus.COMPLETED:
                                placement.progress_status = PlacementProgressStatus.IN_PROGRESS
                    
                    # Auto-complete Class Period Referral (Behavior, Cool-Down, Pre-Planned single day)
                    elif placement.placement_type == PlacementCategory.CLASS_REFERRAL:
                        days_assigned = placement.days_assigned or 1
                        if placement.days_completed >= days_assigned:
                            placement.status = PlacementStatus.completed
                            placement.progress_status = PlacementProgressStatus.COMPLETED
                            placement.end_date = date_obj
                        else:
                            # Set to IN_PROGRESS when completing a day but not yet finished
                            if placement.progress_status != PlacementProgressStatus.COMPLETED:
                                placement.progress_status = PlacementProgressStatus.IN_PROGRESS
                    else:
                        # For other placement types, set to IN_PROGRESS if not already completed
                        if placement.progress_status != PlacementProgressStatus.COMPLETED:
                            placement.progress_status = PlacementProgressStatus.IN_PROGRESS
            else:
                old_fulfillment = log.daily_fulfillment
                log.daily_fulfillment = 'yes'
                log.finalized_by = completed_by
                log.finalized_at = central_now_naive()
                if is_override:
                    log.override_used = True
                
                placement = session.query(Placement).filter(Placement.id == placement_id).first()
                if placement and old_fulfillment != 'yes':
                    placement.days_completed = (placement.days_completed or 0) + 1
                    
                    # Auto-complete Lunch Detention when all days are completed
                    if placement.placement_type == PlacementCategory.LUNCH_DETENTION:
                        # OPTION B: Only count a Lunch Detention day as "served" when it is completed.
                        served_dates = list(placement.served_dates) if placement.served_dates else []
                        ds = date_obj.isoformat()
                        if ds not in served_dates:
                            served_dates.append(ds)
                            placement.served_dates = served_dates

                        days_assigned = placement.days_assigned or 1
                        if placement.days_completed >= days_assigned:
                            placement.status = PlacementStatus.completed
                            placement.progress_status = PlacementProgressStatus.COMPLETED
                            placement.end_date = date_obj
                        else:
                            # Set to IN_PROGRESS when completing a day but not yet finished
                            if placement.progress_status != PlacementProgressStatus.COMPLETED:
                                placement.progress_status = PlacementProgressStatus.IN_PROGRESS
                    
                    # Auto-complete Class Period Referral (Behavior, Cool-Down, Pre-Planned single day)
                    elif placement.placement_type == PlacementCategory.CLASS_REFERRAL:
                        days_assigned = placement.days_assigned or 1
                        if placement.days_completed >= days_assigned:
                            placement.status = PlacementStatus.completed
                            placement.progress_status = PlacementProgressStatus.COMPLETED
                            placement.end_date = date_obj
                        else:
                            # Set to IN_PROGRESS when completing a day but not yet finished
                            if placement.progress_status != PlacementProgressStatus.COMPLETED:
                                placement.progress_status = PlacementProgressStatus.IN_PROGRESS
                    else:
                        # For other placement types, set to IN_PROGRESS if not already completed
                        if placement.progress_status != PlacementProgressStatus.COMPLETED:
                            placement.progress_status = PlacementProgressStatus.IN_PROGRESS
            
            session.commit()
            return True
        finally:
            session.close()
    
    def checkin_preplanned_session(self, placement_id: str, log_date: str) -> bool:
        """Check in a student for a Pre-Planned referral day.
        
        Sets checked_in = True and checked_in_at to current timestamp.
        Also updates the session status to in_progress.
        
        Args:
            placement_id: ID of the placement
            log_date: ISO format date string
            
        Returns:
            True if successful, False otherwise
        """
        db_session = self.get_session()
        try:
            date_obj = datetime.fromisoformat(log_date).date() if isinstance(log_date, str) else log_date
            
            log = db_session.query(DailyLog).filter(
                DailyLog.placement_id == placement_id,
                DailyLog.date == date_obj
            ).first()
            
            if not log:
                log_id = self.generate_id()
                log = DailyLog(
                    id=log_id,
                    placement_id=placement_id,
                    date=date_obj,
                    positive_total=0,
                    negative_total=0,
                    daily_total=0,
                    readiness='continue',
                    checked_in=True,
                    checked_in_at=central_now_naive()
                )
                db_session.add(log)
            else:
                log.checked_in = True
                log.checked_in_at = central_now_naive()
            
            session_record = db_session.query(PartialDaySession).filter(
                PartialDaySession.placement_id == placement_id,
                PartialDaySession.date == date_obj
            ).first()
            
            if session_record:
                session_record.status = SessionStatus.in_progress
            
            # Update progress_status to IN_PROGRESS on check-in
            placement = db_session.query(Placement).filter(Placement.id == placement_id).first()
            if placement and placement.progress_status != PlacementProgressStatus.COMPLETED:
                placement.progress_status = PlacementProgressStatus.IN_PROGRESS
            
            db_session.commit()
            return True
        except Exception as e:
            db_session.rollback()
            print(f"[ERROR] Failed to check in Pre-Planned session: {str(e)}")
            return False
        finally:
            db_session.close()
    
    def complete_preplanned_session(self, placement_id: str, log_date: str, completed_by: str) -> bool:
        """Complete a Pre-Planned referral day with attendance based on check-in status.
        
        Sets:
        - daily_fulfillment = 'yes'
        - Session status = 'fulfilled' if checked_in, 'no_show' if not
        - Updates placement.days_completed and auto-completes if all days done
        
        Args:
            placement_id: ID of the placement
            log_date: ISO format date string
            completed_by: Name/ID of person completing
            
        Returns:
            True if successful, False otherwise
        """
        db_session = self.get_session()
        try:
            date_obj = datetime.fromisoformat(log_date).date() if isinstance(log_date, str) else log_date
            
            log = db_session.query(DailyLog).filter(
                DailyLog.placement_id == placement_id,
                DailyLog.date == date_obj
            ).first()
            
            was_checked_in = log.checked_in if log else False
            
            if not log:
                log_id = self.generate_id()
                log = DailyLog(
                    id=log_id,
                    placement_id=placement_id,
                    date=date_obj,
                    positive_total=0,
                    negative_total=0,
                    daily_total=0,
                    readiness='continue',
                    daily_fulfillment='yes',
                    no_show=not was_checked_in,
                    finalized_by=completed_by,
                    finalized_at=central_now_naive()
                )
                db_session.add(log)
            else:
                log.daily_fulfillment = 'yes'
                log.no_show = not was_checked_in
                log.finalized_by = completed_by
                log.finalized_at = central_now_naive()
            
            session_records = db_session.query(PartialDaySession).filter(
                PartialDaySession.placement_id == placement_id,
                PartialDaySession.date == date_obj
            ).all()
            
            for session_record in session_records:
                if was_checked_in:
                    session_record.status = SessionStatus.fulfilled
                else:
                    session_record.status = SessionStatus.no_show
            
            placement = db_session.query(Placement).filter(Placement.id == placement_id).first()
            if placement:
                placement.days_completed = (placement.days_completed or 0) + 1
                days_assigned = placement.days_assigned or 1
                if placement.days_completed >= days_assigned:
                    placement.status = PlacementStatus.completed
                    placement.progress_status = PlacementProgressStatus.COMPLETED
                    placement.end_date = date_obj
            
            db_session.commit()
            return True
        except Exception as e:
            db_session.rollback()
            print(f"[ERROR] Failed to complete Pre-Planned session: {str(e)}")
            return False
        finally:
            db_session.close()
    
    def get_preplanned_checkin_status(self, placement_id: str, log_date: str) -> dict:
        """Get the check-in status for a Pre-Planned referral day.
        
        Args:
            placement_id: ID of the placement
            log_date: ISO format date string
            
        Returns:
            Dict with keys: checked_in (bool), checked_in_at (datetime or None)
        """
        db_session = self.get_session()
        try:
            date_obj = datetime.fromisoformat(log_date).date() if isinstance(log_date, str) else log_date
            
            log = db_session.query(DailyLog).filter(
                DailyLog.placement_id == placement_id,
                DailyLog.date == date_obj
            ).first()
            
            if log:
                return {
                    'checked_in': log.checked_in or False,
                    'checked_in_at': log.checked_in_at
                }
            return {'checked_in': False, 'checked_in_at': None}
        finally:
            db_session.close()
    
    def complete_iss_full_day_session(self, placement_id: str, log_date: str, completed_by: str, 
                                       is_override: bool = False, override_note: str = None,
                                       points_earned: int = None) -> bool:
        """Complete a Full Day ISS session, adding scheduled periods to issPeriodsServed.
        
        Args:
            placement_id: ID of the placement
            log_date: ISO format date string
            completed_by: Name/ID of person completing
            is_override: True if using Override (early release with full credit)
            override_note: Required note when using override
            points_earned: Points earned for this session
            
        Returns:
            True if successful, False otherwise
            
        Note:
            Uses the normalized get_iss_scheduled_periods_for_date helper to determine
            how many periods to credit. For full days this is 10 (PERIODS_PER_FULL_DAY).
            Idempotent: Multiple clicks on same day do not double-count periods.
        """
        session = self.get_session()
        try:
            date_obj = datetime.fromisoformat(log_date).date() if isinstance(log_date, str) else log_date
            
            # Get placement to update issPeriodsServed
            placement = session.query(Placement).filter(Placement.id == placement_id).first()
            if not placement:
                return False
            
            # Convert placement to dict for helper functions
            placement_dict = self._placement_to_dict(placement)
            
            # Use normalized helper to get scheduled periods for this date
            periods_to_credit = self.get_iss_scheduled_periods_for_date(placement_dict, date_obj)
            if periods_to_credit == 0:
                # Fallback to full day default (10) if no schedule found
                periods_to_credit = PERIODS_PER_FULL_DAY
            
            # Get student for the label
            student = session.query(Student).filter(Student.id == placement.student_id).first()
            student_name = f"{student.first_name} {student.last_name}" if student else "Unknown"
            
            # Get or create daily log
            log = session.query(DailyLog).filter(
                DailyLog.placement_id == placement_id,
                DailyLog.date == date_obj
            ).first()
            
            should_add_periods = False
            
            # Read periods_covered from the daily log (set during check-in)
            # Priority: daily log coverage > scheduled periods > default 10
            if log and log.periods_covered and len(log.periods_covered) > 0:
                periods_covered = log.periods_covered
                periods_to_credit = len(periods_covered)  # Use actual coverage, not scheduled
                start_period = min(periods_covered)
                end_period = max(periods_covered)
            elif periods_to_credit > 0:
                # Use scheduled periods from helper as fallback
                periods_covered = list(range(1, periods_to_credit + 1))
                start_period = 1
                end_period = periods_to_credit
            else:
                # Final fallback to full day defaults
                periods_to_credit = PERIODS_PER_FULL_DAY
                periods_covered = list(range(1, 11))
                start_period = 1
                end_period = 10
            
            # Read required_points from daily log (for points_target in session log)
            required_points = log.required_points if log and log.required_points else periods_to_credit
            
            if not log:
                log_id = self.generate_id()
                log = DailyLog(
                    id=log_id,
                    placement_id=placement_id,
                    date=date_obj,
                    positive_total=0,
                    negative_total=0,
                    daily_total=0,
                    readiness='continue',
                    daily_fulfillment='yes',
                    day_type='full',
                    start_period=start_period,
                    end_period=end_period,
                    periods_covered=periods_covered,
                    required_points=required_points,
                    finalized_by=completed_by,
                    finalized_at=central_now_naive(),
                    override_used=is_override,
                    override_comment=override_note if is_override else None
                )
                session.add(log)
                should_add_periods = True
            else:
                old_fulfillment = log.daily_fulfillment
                log.daily_fulfillment = 'yes'
                log.day_type = 'full'
                log.finalized_by = completed_by
                log.finalized_at = central_now_naive()
                if is_override:
                    log.override_used = True
                    log.override_comment = override_note
                
                # Ensure period values are persisted in the log for consistency
                # These values come from check-in time, but ensure they're set
                if not log.start_period:
                    log.start_period = start_period
                if not log.end_period:
                    log.end_period = end_period
                if not log.periods_covered:
                    log.periods_covered = periods_covered
                if not log.required_points:
                    log.required_points = required_points
                
                # Only add periods if not already completed
                if old_fulfillment != 'yes':
                    should_add_periods = True
            
            # Store periods_added in the daily log
            log.periods_added = periods_to_credit
            
            if should_add_periods:
                # Add periods_covered (not hard-coded 10) for completion
                placement.iss_periods_served = (placement.iss_periods_served or 0) + periods_to_credit
                placement.days_completed = (placement.days_completed or 0) + 1
                
                # Create ISS Session Log entry
                session_log = ISSSessionLog(
                    id=self.generate_id(),
                    placement_id=placement_id,
                    session_date=date_obj,
                    session_type='Make-Up Full Day' if log.is_makeup_session else 'Full Day',
                    start_period=start_period,
                    end_period=end_period,
                    periods_covered=periods_covered,
                    periods_credited=periods_to_credit,
                    points_target=required_points,
                    points_earned=points_earned,
                    completion_method='Override' if is_override else 'Complete',
                    notes=log.notes if log else None,
                    override_reason=override_note if is_override else None,
                    completed_by=completed_by
                )
                session.add(session_log)
            
            # Check if ISS Session is now complete
            iss_total_required = placement.iss_total_required_periods or (placement.iss_days_assigned or 0) * 10
            if placement.iss_periods_served >= iss_total_required:
                placement.status = PlacementStatus.completed
                placement.progress_status = PlacementProgressStatus.COMPLETED
                placement.end_date = date_obj
                # Set the official label
                iss_days = placement.iss_days_assigned or 0
                placement.iss_label = f"{iss_days}-day ISS Session for {student_name}"
            
            session.commit()
            return True
        finally:
            session.close()
    
    def convert_full_day_to_partial(self, placement_id: str, log_date: str, 
                                     start_period: int, end_period: int) -> bool:
        """Convert an active Full Day ISS session to a Partial Day (for early departures).
        
        This converts the day type from 'full' to 'partial' and updates the period info.
        Does NOT update iss_periods_served - that happens when the session is completed.
        
        Args:
            placement_id: ID of the placement
            log_date: ISO format date string
            start_period: Starting period (1-10)
            end_period: Ending period (1-10)
            
        Returns:
            True if successful, False otherwise
        """
        session = self.get_session()
        try:
            date_obj = datetime.fromisoformat(log_date).date() if isinstance(log_date, str) else log_date
            
            # Validate period range
            if end_period < start_period:
                return False
            
            # Get the daily log
            log = session.query(DailyLog).filter(
                DailyLog.placement_id == placement_id,
                DailyLog.date == date_obj
            ).first()
            
            if not log:
                return False
            
            # Only convert if not already completed
            if log.daily_fulfillment == 'yes':
                return False
            
            # Only convert if currently a full day
            if log.day_type != 'full':
                return False
            
            # Calculate new periods
            periods_count = end_period - start_period + 1
            periods_covered = list(range(start_period, end_period + 1))
            required_points = periods_count
            
            # Update the daily log
            log.day_type = 'partial'
            log.start_period = start_period
            log.end_period = end_period
            log.periods_covered = periods_covered
            log.required_points = required_points
            
            session.commit()
            return True
        finally:
            session.close()
    
    def complete_iss_partial_day_session(self, placement_id: str, log_date: str, completed_by: str,
                                          start_period: int = None, end_period: int = None, 
                                          periods_covered_list: list = None,
                                          required_points: int = None,
                                          is_override: bool = False, override_note: str = None,
                                          points_earned: int = None) -> bool:
        """Complete a Partial Day ISS session, adding scheduled periods to issPeriodsServed.
        
        Args:
            placement_id: ID of the placement
            log_date: ISO format date string
            completed_by: Name/ID of person completing
            start_period: Starting period (1-10) - used if periods_covered_list not provided
            end_period: Ending period (1-10) - used if periods_covered_list not provided
            periods_covered_list: Explicit list of period numbers attended (for non-contiguous selections)
            required_points: Points required for this partial day (optional)
            is_override: True if using Override
            override_note: Required note when using override
            points_earned: Points earned for this session
            
        Returns:
            True if successful, False otherwise
            
        Note:
            Uses the normalized get_iss_scheduled_periods_for_date helper to determine
            how many periods to credit. Falls back to passed-in parameters if helper returns 0.
            Idempotent: Multiple clicks on same day do not double-count periods.
        """
        session = self.get_session()
        try:
            date_obj = datetime.fromisoformat(log_date).date() if isinstance(log_date, str) else log_date
            
            # Get placement to update issPeriodsServed
            placement = session.query(Placement).filter(Placement.id == placement_id).first()
            if not placement:
                return False
            
            # Convert placement to dict for helper functions
            placement_dict = self._placement_to_dict(placement)
            
            # Use normalized helper to get scheduled periods for this date
            scheduled_periods = self.get_iss_scheduled_periods_for_date(placement_dict, date_obj)
            
            # Calculate planned periods - priority: explicit list > passed params > scheduled > default
            if periods_covered_list and len(periods_covered_list) > 0:
                # Explicit list takes highest priority (actual coverage)
                planned_periods = len(periods_covered_list)
                start_period = min(periods_covered_list)
                end_period = max(periods_covered_list)
            elif start_period is not None and end_period is not None:
                # Use passed-in period range (from UI)
                if end_period < start_period:
                    end_period = start_period
                planned_periods = end_period - start_period + 1
            elif scheduled_periods > 0:
                # Use scheduled periods from helper as fallback
                planned_periods = scheduled_periods
                start_period = 1
                end_period = planned_periods
            else:
                # Final fallback
                start_period = 1
                end_period = 1
                planned_periods = 1
            
            # Get student for the label
            student = session.query(Student).filter(Student.id == placement.student_id).first()
            student_name = f"{student.first_name} {student.last_name}" if student else "Unknown"
            
            # Get or create daily log
            log = session.query(DailyLog).filter(
                DailyLog.placement_id == placement_id,
                DailyLog.date == date_obj
            ).first()
            
            # Build periods_covered array - use explicit list if provided, else generate from range
            if periods_covered_list:
                periods_covered = sorted(periods_covered_list)
            else:
                periods_covered = list(range(start_period, end_period + 1))
            
            should_add_periods = False
            
            if not log:
                log_id = self.generate_id()
                log = DailyLog(
                    id=log_id,
                    placement_id=placement_id,
                    date=date_obj,
                    positive_total=0,
                    negative_total=0,
                    daily_total=0,
                    readiness='continue',
                    daily_fulfillment='yes',
                    day_type='partial',
                    periods_covered=periods_covered,
                    finalized_by=completed_by,
                    finalized_at=central_now_naive(),
                    override_used=is_override,
                    override_comment=override_note if is_override else None
                )
                session.add(log)
                should_add_periods = True
            else:
                old_fulfillment = log.daily_fulfillment
                log.daily_fulfillment = 'yes'
                log.day_type = 'partial'
                log.periods_covered = periods_covered
                log.finalized_by = completed_by
                log.finalized_at = central_now_naive()
                log.override_used = is_override
                log.override_comment = override_note if is_override else None
                
                # Only add periods if not already completed
                if old_fulfillment != 'yes':
                    should_add_periods = True
            
            # Store periods_added in the daily log
            log.periods_added = planned_periods
            
            if should_add_periods:
                # Add planned periods for partial day completion
                placement.iss_periods_served = (placement.iss_periods_served or 0) + planned_periods
                placement.days_completed = (placement.days_completed or 0) + 1
                
                # Create ISS Session Log entry
                session_log = ISSSessionLog(
                    id=self.generate_id(),
                    placement_id=placement_id,
                    session_date=date_obj,
                    session_type='Make-Up Partial Day' if log.is_makeup_session else 'Partial Day',
                    start_period=start_period,
                    end_period=end_period,
                    periods_covered=periods_covered,  # Array of period numbers attended
                    periods_credited=planned_periods,
                    points_target=required_points,
                    points_earned=points_earned,
                    completion_method='Override' if is_override else 'Complete',
                    notes=log.notes if log else None,
                    override_reason=override_note if is_override else None,
                    completed_by=completed_by
                )
                session.add(session_log)
            
            # Check if ISS Session is now complete
            iss_total_required = placement.iss_total_required_periods or (placement.iss_days_assigned or 0) * 10
            if placement.iss_periods_served >= iss_total_required:
                placement.status = PlacementStatus.completed
                placement.progress_status = PlacementProgressStatus.COMPLETED
                placement.end_date = date_obj
                # Set the official label
                iss_days = placement.iss_days_assigned or 0
                placement.iss_label = f"{iss_days}-day ISS Session for {student_name}"
            
            session.commit()
            return True
        finally:
            session.close()
    
    def check_iss_session_needs_makeup(self, placement_id: str) -> Dict[str, Any]:
        """Check if an ISS session needs make-up periods after final scheduled day.
        
        Delegates entirely to should_offer_makeup_days() helper for trigger logic.
        
        Args:
            placement_id: ID of the placement
            
        Returns:
            Dictionary with:
            - needsMakeup: True if should_offer_makeup_days() returns True
            - isFinalDay: True if all original scheduled days are completed
            - periodsServed: Current periods served
            - periodsRequired: Total required periods
            - periodsRemaining: Periods still needed (0 if complete)
            - daysCompleted: Number of days completed
            - daysAssigned: Original day count (immutable)
        """
        session = self.get_session()
        try:
            placement = session.query(Placement).filter(Placement.id == placement_id).first()
            if not placement:
                return {'needsMakeup': False, 'isFinalDay': False}
            
            # Get placement dict and use shared helper for trigger logic
            placement_dict = self._placement_to_dict(placement)
            
            # Delegate entirely to should_offer_makeup_days() for the trigger decision
            needs_makeup = self.should_offer_makeup_days(placement_dict)
            
            # Extract metadata from placement_dict (consistent with helper's view)
            iss_days_assigned = placement_dict.get('originalDayCount') or placement_dict.get('issDaysAssigned') or 0
            periods_served = self.get_iss_periods_served(placement_dict)
            periods_required = self.get_iss_total_periods_required(placement_dict)
            periods_remaining = self.get_iss_periods_remaining(placement_dict)
            days_completed = placement_dict.get('daysCompleted') or 0
            
            # Final day = all original scheduled days completed
            is_final_day = days_completed >= iss_days_assigned
            
            return {
                'needsMakeup': needs_makeup,
                'isFinalDay': is_final_day,
                'periodsServed': periods_served,
                'periodsRequired': periods_required,
                'periodsRemaining': periods_remaining,
                'daysCompleted': days_completed,
                'daysAssigned': iss_days_assigned
            }
        finally:
            session.close()
    
    def complete_iss_day(self, placement_id: str, log_date: str, completed_by: str,
                         day_type: str = "Full Day", start_period: int = 1, end_period: int = 10,
                         points_earned: int = None, is_override: bool = False, 
                         override_note: str = None) -> Dict[str, Any]:
        """Complete or edit an ISS day with period tracking and auto-complete logic.
        
        This is the main entry point for the "Complete Day" button on the Dashboard.
        Supports both new completions and edits to existing entries.
        
        For edits: Updates the daily log with new values and recalculates placement
        totals by summing all daily logs (prevents double-counting).
        
        Args:
            placement_id: ID of the placement
            log_date: ISO format date string
            completed_by: Name/ID of person completing
            day_type: "Full Day" or "Partial Day"
            start_period: Starting period (1-10) for Partial Day
            end_period: Ending period (1-10) for Partial Day
            points_earned: Points earned for this session
            is_override: True if using Override
            override_note: Required note when using override
            
        Returns:
            Dictionary with:
            - success: True if successful
            - servedPeriodsForThisDay: Periods credited for this day
            - servedPeriodsTotal: Updated total periods served
            - periodsRemaining: Remaining periods needed
            - isCompleted: True if placement is now complete
            - message: Success/error message
        """
        session = self.get_session()
        try:
            date_obj = datetime.fromisoformat(log_date).date() if isinstance(log_date, str) else log_date
            
            # Get placement
            placement = session.query(Placement).filter(Placement.id == placement_id).first()
            if not placement:
                return {'success': False, 'message': 'Placement not found'}
            
            # Get student for logging
            student = session.query(Student).filter(Student.id == placement.student_id).first()
            student_name = f"{student.first_name} {student.last_name}" if student else "Unknown"
            
            # Calculate periods for this day
            if day_type == "Full Day":
                served_periods_for_day = 10
                db_day_type = 'full'
                actual_start = 1
                actual_end = 10
                periods_covered = list(range(1, 11))
            else:
                served_periods_for_day = end_period - start_period + 1
                db_day_type = 'partial'
                actual_start = start_period
                actual_end = end_period
                periods_covered = list(range(start_period, end_period + 1))
            
            # Get or create daily log
            log = session.query(DailyLog).filter(
                DailyLog.placement_id == placement_id,
                DailyLog.date == date_obj
            ).first()
            
            is_edit = log is not None and log.daily_fulfillment == 'yes'
            was_first_completion = log is None or log.daily_fulfillment != 'yes'
            
            if not log:
                log_id = self.generate_id()
                log = DailyLog(
                    id=log_id,
                    placement_id=placement_id,
                    date=date_obj,
                    positive_total=0,
                    negative_total=0,
                    daily_total=0,
                    readiness='continue'
                )
                session.add(log)
            
            # Update daily log with new values
            log.day_type = db_day_type
            log.start_period = actual_start
            log.end_period = actual_end
            log.periods_covered = periods_covered
            log.periods_added = served_periods_for_day
            log.required_points = served_periods_for_day
            log.daily_fulfillment = 'yes'
            log.finalized_by = completed_by
            log.finalized_at = central_now_naive()
            
            if is_override:
                log.override_used = True
                log.override_comment = override_note
            
            # Flush to ensure this log is included in the sum query
            session.flush()
            
            # Recalculate total periods served by summing ALL daily logs for this placement
            # This ensures edits don't double-count and totals are always accurate
            from sqlalchemy import func
            total_periods = session.query(func.coalesce(func.sum(DailyLog.periods_added), 0)).filter(
                DailyLog.placement_id == placement_id,
                DailyLog.daily_fulfillment == 'yes',
                DailyLog.periods_added.isnot(None)
            ).scalar()
            
            # Update placement totals
            placement.iss_periods_served = total_periods
            
            # Count completed days
            days_completed = session.query(DailyLog).filter(
                DailyLog.placement_id == placement_id,
                DailyLog.daily_fulfillment == 'yes'
            ).count()
            placement.days_completed = days_completed
            
            # Track make-up periods: count completed make-up sessions
            makeup_logs = session.query(DailyLog).filter(
                DailyLog.placement_id == placement_id,
                DailyLog.daily_fulfillment == 'yes',
                DailyLog.is_makeup_session == True
            ).all()
            
            makeup_days_count = len(makeup_logs)
            makeup_periods_total = sum(ml.periods_added or 0 for ml in makeup_logs)
            
            # Update placement make-up tracking fields
            placement.makeup_days_used = makeup_days_count
            placement.makeup_periods_served = makeup_periods_total
            
            # Calculate required and remaining
            required_total = placement.iss_total_required_periods or (placement.iss_days_assigned or 0) * 10
            # FIX: For 1-day ISS placements completed as Partial Day, the session should require
            # only the scheduled/credited partial-day periods (not a default 10-period full day).
            # This allows the Placement to reach "completed" and be archived to Completed Placements.
            if (placement.iss_days_assigned == 1) and (db_day_type == 'partial'):
                required_total = served_periods_for_day
                placement.iss_total_required_periods = served_periods_for_day
            remaining = max(0, required_total - total_periods)
            
            # Check for auto-complete
            was_completed = placement.status == PlacementStatus.completed
            if total_periods >= required_total and not was_completed:
                placement.status = PlacementStatus.completed
                placement.progress_status = PlacementProgressStatus.COMPLETED
                placement.end_date = date_obj
                # Use original_day_count for the label (preserves "X days of ISS")
                original_days = placement.original_day_count or placement.iss_days_assigned or 0
                placement.iss_label = f"{original_days}-day ISS Session for {student_name}"
                
                # Generate make-up note if make-up days were used
                if makeup_days_count > 0:
                    day_word = "day" if makeup_days_count == 1 else "days"
                    placement.makeup_note = f"Make-up required: {makeup_days_count} additional {day_word} ({makeup_periods_total} periods) beyond original {original_days}-day ISS assignment."
            
            # Create ISS Session Log entry (only for new completions, not edits)
            if was_first_completion:
                session_type = 'Full Day' if day_type == "Full Day" else 'Partial Day'
                if is_override:
                    session_type = f"{session_type} (Override)"
                
                session_log = ISSSessionLog(
                    id=self.generate_id(),
                    placement_id=placement_id,
                    session_date=date_obj,
                    session_type=session_type,
                    start_period=actual_start,
                    end_period=actual_end,
                    periods_covered=periods_covered,
                    periods_credited=served_periods_for_day,
                    points_target=served_periods_for_day,
                    points_earned=points_earned,
                    completion_method='Override' if is_override else 'Complete',
                    notes=log.notes if log else None,
                    override_reason=override_note if is_override else None,
                    completed_by=completed_by
                )
                session.add(session_log)
            
            session.commit()
            
            is_now_completed = placement.status == PlacementStatus.completed
            
            return {
                'success': True,
                'servedPeriodsForThisDay': served_periods_for_day,
                'servedPeriodsTotal': total_periods,
                'periodsRemaining': remaining,
                'requiredTotalPeriods': required_total,
                'isCompleted': is_now_completed,
                'isEdit': is_edit,
                'message': 'ISS day updated successfully!' if is_edit else 'ISS day completed successfully!'
            }
                
        except Exception as e:
            session.rollback()
            return {
                'success': False,
                'message': f'Error completing ISS day: {str(e)}'
            }
        finally:
            session.close()
    
    def keep_iss_session_open_for_makeup(self, placement_id: str) -> bool:
        """Keep the ISS session open for make-up periods.
        
        Args:
            placement_id: ID of the placement
            
        Returns:
            True if successful, False otherwise
        """
        session = self.get_session()
        try:
            placement = session.query(Placement).filter(Placement.id == placement_id).first()
            if not placement:
                return False
            
            # Set status to needs_makeup
            placement.status = PlacementStatus.needs_makeup
            
            session.commit()
            return True
        finally:
            session.close()
    
    def close_iss_session_early(self, placement_id: str, note: str) -> bool:
        """Close an ISS session early, waiving remaining periods.
        
        Args:
            placement_id: ID of the placement
            note: Required note explaining the early closure
            
        Returns:
            True if successful, False otherwise
        """
        session = self.get_session()
        try:
            placement = session.query(Placement).filter(Placement.id == placement_id).first()
            if not placement:
                return False
            
            # Get student for the label
            student = session.query(Student).filter(Student.id == placement.student_id).first()
            student_name = f"{student.first_name} {student.last_name}" if student else "Unknown"
            
            # Calculate periods waived
            iss_total_required = placement.iss_total_required_periods or 0
            iss_periods_served = placement.iss_periods_served or 0
            periods_waived = max(0, iss_total_required - iss_periods_served)
            
            # Update placement
            placement.status = PlacementStatus.completed
            placement.progress_status = PlacementProgressStatus.COMPLETED
            placement.end_date = central_today()
            placement.closed_early = True
            placement.early_closure_note = note or "Session closed early — remaining periods waived by staff judgment."
            placement.periods_waived = periods_waived
            
            # Set the official label
            iss_days = placement.iss_days_assigned or 0
            placement.iss_label = f"{iss_days}-day ISS Session for {student_name}"
            
            session.commit()
            return True
        finally:
            session.close()
    
    def add_iss_makeup_dates(self, placement_id: str, makeup_dates: list) -> Dict[str, Any]:
        """Add make-up dates to an ISS placement.
        
        Creates DailyLog and ISSSession entries for each make-up date,
        and updates placement's scheduled_iss_sessions with make-up entries.
        Does NOT modify original_day_count.
        
        Args:
            placement_id: ID of the placement
            makeup_dates: List of dicts with:
                - date: ISO date string
                - day_type: 'full' or 'partial'
                - start_period: int (for partial)
                - end_period: int (for partial)
        
        Returns:
            Dictionary with success status and added dates
        """
        session = self.get_session()
        try:
            placement = session.query(Placement).filter(Placement.id == placement_id).first()
            if not placement:
                return {'success': False, 'message': 'Placement not found'}
            
            # Get student for labeling
            student = session.query(Student).filter(Student.id == placement.student_id).first()
            student_name = f"{student.first_name} {student.last_name}" if student else "Unknown"
            
            # Get existing scheduled sessions (preserve original ones)
            existing_sessions = placement.scheduled_iss_sessions or []
            new_sessions = list(existing_sessions)  # Copy to avoid mutation issues
            
            added_dates = []
            for makeup_entry in makeup_dates:
                date_str = makeup_entry.get('date')
                day_type = makeup_entry.get('day_type', 'full')
                start_period = makeup_entry.get('start_period', 1)
                end_period = makeup_entry.get('end_period', 10)
                
                date_obj = datetime.fromisoformat(date_str).date() if isinstance(date_str, str) else date_str
                date_iso = date_obj.isoformat()
                
                # Check if daily log already exists for this date
                existing_log = session.query(DailyLog).filter(
                    DailyLog.placement_id == placement_id,
                    DailyLog.date == date_obj
                ).first()
                
                if existing_log:
                    continue  # Skip if already exists
                
                # Check if date already in scheduled sessions
                date_already_scheduled = any(
                    s.get('date') == date_iso for s in new_sessions
                )
                if date_already_scheduled:
                    continue
                
                # Calculate periods for this make-up day
                if day_type == 'full':
                    periods = 10
                    periods_list = list(range(1, 11))
                else:
                    periods = end_period - start_period + 1
                    periods_list = list(range(start_period, end_period + 1))
                
                # Create daily log with is_makeup_session = True
                log_id = self.generate_id()
                daily_log = DailyLog(
                    id=log_id,
                    placement_id=placement_id,
                    date=date_obj,
                    day_type=day_type,
                    start_period=start_period,
                    end_period=end_period,
                    required_points=periods,
                    positive_total=0,
                    negative_total=0,
                    daily_total=0,
                    daily_fulfillment='pending',
                    is_makeup_session=True,
                    readiness='continue'
                )
                session.add(daily_log)
                
                # Create ISS session for this make-up date
                session_id = self.generate_id()
                iss_session = ISSSession(
                    id=session_id,
                    placement_id=placement_id,
                    student_id=placement.student_id,
                    date=date_obj,
                    day_type=day_type,
                    status='pending',
                    periods=periods_list,
                    is_makeup=True
                )
                session.add(iss_session)
                
                # Add to scheduled_iss_sessions with is_makeup flag
                new_sessions.append({
                    'date': date_iso,
                    'dayType': day_type,
                    'periods': periods_list,
                    'startPeriod': start_period,
                    'endPeriod': end_period,
                    'isMakeup': True
                })
                
                added_dates.append({
                    'date': date_iso,
                    'day_type': day_type,
                    'periods': periods
                })
            
            if not added_dates:
                return {
                    'success': False,
                    'message': 'No new dates were added (all dates may already exist)'
                }
            
            # Update placement's scheduled_iss_sessions
            placement.scheduled_iss_sessions = new_sessions
            
            # Update placement status to needs_makeup (keeping it open)
            placement.status = PlacementStatus.needs_makeup
            
            # Keep progress_status as IN_PROGRESS since make-up days are pending
            placement.progress_status = PlacementProgressStatus.IN_PROGRESS
            
            session.commit()
            
            return {
                'success': True,
                'added_dates': added_dates,
                'count': len(added_dates),
                'message': f'Added {len(added_dates)} make-up date(s) for {student_name}'
            }
                
        except Exception as e:
            session.rollback()
            return {
                'success': False,
                'message': f'Error adding make-up dates: {str(e)}'
            }
        finally:
            session.close()
    
    def update_daily_log_totals(self, placement_id: str, log_date: str):
        """Update daily log totals based on point events."""
        session = self.get_session()
        try:
            date_obj = datetime.fromisoformat(log_date).date() if isinstance(log_date, str) else log_date
            
            # Get or create daily log
            log = session.query(DailyLog).filter(
                DailyLog.placement_id == placement_id,
                DailyLog.date == date_obj
            ).first()
            
            if not log:
                log_id = self.generate_id()
                log = DailyLog(
                    id=log_id,
                    placement_id=placement_id,
                    date=date_obj,
                    positive_total=0,
                    negative_total=0,
                    daily_total=0,
                    readiness='continue'
                )
                session.add(log)
            
            # Calculate totals from point events
            events = session.query(PointEvent).filter(
                PointEvent.placement_id == placement_id,
                PointEvent.date == date_obj
            ).all()
            
            positive_total = sum(e.value for e in events if e.type == PointEventType.positive)
            negative_total = sum(e.value for e in events if e.type == PointEventType.negative)
            
            log.positive_total = positive_total
            log.negative_total = negative_total
            log.daily_total = positive_total + negative_total
            
            session.commit()
        finally:
            session.close()
    
    def get_iss_session_logs(self, placement_id: str) -> List[Dict]:
        """Get all ISS session logs for a placement, ordered by date.
        
        Args:
            placement_id: ID of the placement
            
        Returns:
            List of session log dictionaries
        """
        session = self.get_session()
        try:
            logs = session.query(ISSSessionLog).filter(
                ISSSessionLog.placement_id == placement_id
            ).order_by(ISSSessionLog.session_date.asc()).all()
            
            return [{
                'id': log.id,
                'placementId': log.placement_id,
                'sessionDate': log.session_date.isoformat() if log.session_date else None,
                'sessionType': log.session_type,
                'startPeriod': log.start_period,
                'endPeriod': log.end_period,
                'periodsCovered': log.periods_covered or [],
                'periodsCredited': log.periods_credited,
                'pointsTarget': log.points_target,
                'pointsEarned': log.points_earned,
                'completionMethod': log.completion_method,
                'notes': log.notes,
                'overrideReason': log.override_reason,
                'completedBy': log.completed_by,
                'createdAt': log.created_at.isoformat() if log.created_at else None
            } for log in logs]
        finally:
            session.close()
    
    def update_iss_day_type(self, placement_id: str, log_date: str, day_type: str,
                           start_period: int = 1, end_period: int = 10) -> bool:
        """Set ISS day type configuration without marking the day as complete.
        
        Used when user selects Full Day or Partial Day to lock in their choice.
        Does NOT mark the day as fulfilled - that happens separately on completion.
        
        Args:
            placement_id: ID of the ISS placement
            log_date: Date of the log (ISO format)
            day_type: 'full' or 'partial'
            start_period: Start period (1-10), default 1
            end_period: End period (1-10), default 10
            
        Returns:
            True if successful, False otherwise
        """
        session = self.get_session()
        try:
            date_obj = datetime.fromisoformat(log_date).date() if isinstance(log_date, str) else log_date
            
            # Get or create daily log
            log = session.query(DailyLog).filter(
                DailyLog.placement_id == placement_id,
                DailyLog.date == date_obj
            ).first()
            
            if not log:
                log_id = self.generate_id()
                log = DailyLog(
                    id=log_id,
                    placement_id=placement_id,
                    date=date_obj,
                    positive_total=0,
                    negative_total=0,
                    daily_total=0,
                    readiness='continue'
                )
                session.add(log)
            
            # Set day type configuration (without marking as fulfilled)
            log.day_type = day_type
            log.start_period = start_period
            log.end_period = end_period
            
            # Calculate periods covered and required points
            if day_type == 'full':
                log.periods_covered = list(range(1, 11))  # Periods 1-10
                log.required_points = 10
            else:
                log.periods_covered = list(range(start_period, end_period + 1))
                log.required_points = end_period - start_period + 1
            
            session.commit()
            return True
        except Exception as e:
            session.rollback()
            print(f"Error updating ISS day type: {e}")
            return False
        finally:
            session.close()
    
    def update_iss_daily_log(self, placement_id: str, log_date: str, day_type: str, 
                            periods_covered: list = None, completed_by: str = "Admin") -> bool:
        """Update ISS daily log with day type and periods, and decrement iss_remaining_days if appropriate.
        
        This function is idempotent - it only adjusts iss_remaining_days when transitioning
        from an unfulfilled state to a fulfilled state, preventing double-counting.
        
        Validation:
        - Partial days must have at least one period
        - Day type must be 'full', 'partial', or 'absent'
        - Placement must exist and be active or completed
        
        Args:
            placement_id: ID of the ISS placement
            log_date: Date of the log (ISO format or date object)
            day_type: 'full', 'partial', or 'absent'
            periods_covered: List of period numbers (e.g., [1,2,5]) for partial days
            completed_by: User completing the day
            
        Returns:
            True if successful, False otherwise
        """
        session = self.get_session()
        try:
            # Validate day_type
            if day_type not in ['full', 'partial', 'absent']:
                return False
            
            # Validate partial day has periods
            if day_type == 'partial' and (not periods_covered or len(periods_covered) == 0):
                return False
            
            date_obj = datetime.fromisoformat(log_date).date() if isinstance(log_date, str) else log_date
            
            # Get or create daily log
            log = session.query(DailyLog).filter(
                DailyLog.placement_id == placement_id,
                DailyLog.date == date_obj
            ).first()
            
            if not log:
                log_id = self.generate_id()
                log = DailyLog(
                    id=log_id,
                    placement_id=placement_id,
                    date=date_obj,
                    positive_total=0,
                    negative_total=0,
                    daily_total=0,
                    readiness='continue'
                )
                session.add(log)
            
            # Capture previous state BEFORE any changes for idempotency check
            old_day_type = log.day_type
            old_fulfillment = log.daily_fulfillment
            
            # EARLY EXIT: If already fulfilled with same day type, this is a duplicate submission
            # Return success without modifying iss_remaining_days to prevent double-counting
            if old_fulfillment == 'yes' and old_day_type == day_type:
                # Already completed with same type - no changes needed (idempotent)
                return True
            
            # Update log fields - only mark as fulfilled for full/partial days
            # Absent days are marked fulfilled but tracked separately
            log.day_type = day_type
            log.periods_covered = periods_covered or []
            log.daily_fulfillment = 'yes'
            log.finalized_by = completed_by
            log.finalized_at = central_now_naive()
            
            # Get placement to update iss_remaining_days
            placement = session.query(Placement).filter(Placement.id == placement_id).first()
            if not placement:
                return False
            
            # Initialize iss_remaining_days if None
            if placement.iss_remaining_days is None:
                placement.iss_remaining_days = placement.iss_total_days or 0
            
            # Get student for the label
            student = session.query(Student).filter(Student.id == placement.student_id).first()
            student_name = f"{student.first_name} {student.last_name}" if student else "Unknown"
            
            # IDEMPOTENCY CHECK: Only adjust iss_remaining_days when transitioning states
            # This prevents double-counting on reruns or edits
            
            # Case 1: First-time completion (was not fulfilled before)
            if old_fulfillment != 'yes':
                # Full Day or Partial Day: Decrement remaining days
                if day_type in ['full', 'partial'] and placement.iss_remaining_days > 0:
                    placement.iss_remaining_days -= 1
                    
                    # Use normalized helper to get scheduled periods for this date (as fallback)
                    placement_dict = self._placement_to_dict(placement)
                    scheduled_periods = self.get_iss_scheduled_periods_for_date(placement_dict, date_obj)
                    
                    # Also update period-based tracking
                    # Priority: actual periods_covered > scheduled > default
                    if day_type == 'full':
                        # Full day: Use periods_covered if exists, else scheduled, else default 10
                        if periods_covered and len(periods_covered) > 0:
                            periods_credited = len(periods_covered)
                            actual_periods = sorted(periods_covered)
                        elif scheduled_periods > 0:
                            periods_credited = scheduled_periods
                            actual_periods = list(range(1, periods_credited + 1))
                        else:
                            periods_credited = PERIODS_PER_FULL_DAY
                            actual_periods = list(range(1, 11))
                    else:
                        # Partial day: Use periods_covered if exists, else scheduled
                        if periods_covered and len(periods_covered) > 0:
                            periods_credited = len(periods_covered)
                            actual_periods = sorted(periods_covered)
                        elif scheduled_periods > 0:
                            periods_credited = scheduled_periods
                            actual_periods = list(range(1, periods_credited + 1))
                        else:
                            periods_credited = 0
                            actual_periods = []
                    
                    placement.iss_periods_served = (placement.iss_periods_served or 0) + periods_credited
                    placement.days_completed = (placement.days_completed or 0) + 1
                    
                    # Create ISS Session Log entry
                    session_log = ISSSessionLog(
                        id=self.generate_id(),
                        placement_id=placement_id,
                        session_date=date_obj,
                        session_type='Full Day' if day_type == 'full' else 'Partial Day',
                        start_period=min(actual_periods) if actual_periods else 1,
                        end_period=max(actual_periods) if actual_periods else periods_credited,
                        periods_covered=actual_periods,
                        periods_credited=periods_credited,
                        points_target=periods_credited,
                        points_earned=log.daily_total,
                        completion_method='Complete',
                        notes=log.notes,
                        completed_by=completed_by
                    )
                    session.add(session_log)
                    
                    # Check if ISS Session is now complete
                    iss_total_required = placement.iss_total_required_periods or (placement.iss_days_assigned or 0) * 10
                    if placement.iss_periods_served >= iss_total_required:
                        placement.status = PlacementStatus.completed
                        placement.progress_status = PlacementProgressStatus.COMPLETED
                        placement.end_date = date_obj
                        iss_days = placement.iss_days_assigned or 0
                        placement.iss_label = f"{iss_days}-day ISS Session for {student_name}"
                
                # Absent Day: Do NOT decrement (student didn't serve time)
            
            # Case 2: Editing an already-fulfilled day (changing day type)
            elif old_fulfillment == 'yes' and old_day_type != day_type:
                # BUSINESS RULE: Full and Partial days count EQUALLY toward ISS completion
                # Only transitions involving Absent days change iss_remaining_days
                
                # Changing FROM full/partial TO absent: Refund the day (student didn't serve)
                if old_day_type in ['full', 'partial'] and day_type == 'absent':
                    placement.iss_remaining_days += 1
                
                # Changing FROM absent TO full/partial: Charge the day (student now served)
                elif old_day_type == 'absent' and day_type in ['full', 'partial']:
                    if placement.iss_remaining_days > 0:
                        placement.iss_remaining_days -= 1
                
                # Changing between Full and Partial: NO CHANGE (both count as served days)
                # This is intentional - correcting periods doesn't affect days served
            
            # Safeguard: Prevent negative values
            if placement.iss_remaining_days < 0:
                placement.iss_remaining_days = 0
            
            # Auto-complete placement if no days remaining
            if placement.iss_remaining_days == 0 and placement.status == PlacementStatus.active:
                placement.status = PlacementStatus.completed
                placement.progress_status = PlacementProgressStatus.COMPLETED
            
            session.commit()
            return True
        finally:
            session.close()
    
    def apply_iss_override(self, placement_id: str, override_comment: str, completed_by: str = "Admin") -> bool:
        """Apply 'Call It Good' override to close ISS placement immediately.
        
        Args:
            placement_id: ID of the ISS placement
            override_comment: Required comment explaining the override
            completed_by: User applying the override
            
        Returns:
            True if successful, False otherwise
        """
        session = self.get_session()
        try:
            # Get placement
            placement = session.query(Placement).filter(Placement.id == placement_id).first()
            if not placement:
                return False
            
            # Set iss_remaining_days to 0
            placement.iss_remaining_days = 0
            placement.status = PlacementStatus.completed
            placement.progress_status = PlacementProgressStatus.COMPLETED
            
            # Create or update today's daily log with override flag
            today = central_today()
            log = session.query(DailyLog).filter(
                DailyLog.placement_id == placement_id,
                DailyLog.date == today
            ).first()
            
            if not log:
                log_id = self.generate_id()
                log = DailyLog(
                    id=log_id,
                    placement_id=placement_id,
                    date=today,
                    positive_total=0,
                    negative_total=0,
                    daily_total=0,
                    readiness='continue'
                )
                session.add(log)
            
            log.override_used = True
            log.override_comment = override_comment
            log.daily_fulfillment = 'yes'
            log.finalized_by = completed_by
            log.finalized_at = central_now_naive()
            
            session.commit()
            return True
        finally:
            session.close()
    
    # Point Event operations
    def add_point_event(self, event_data: Dict[str, Any]) -> str:
        """Add a point event.

        Guardrail: For ISS placements, points may only be added after the day's ISS configuration
        is locked (day_type set to 'full' or 'partial' in the DailyLog for that date).
        """
        session = self.get_session()
        try:
            placement_id = event_data['placementId']
            event_date = datetime.fromisoformat(event_data['date']).date()

            # --- ISS guardrail: require confirmed day_type before allowing points ---
            placement = session.query(Placement).filter(Placement.id == placement_id).first()
            if placement and placement.placement_type == PlacementCategory.ISS:
                log = session.query(DailyLog).filter(
                    DailyLog.placement_id == placement_id,
                    DailyLog.date == event_date
                ).first()

                # Block if the log doesn't exist yet or day_type hasn't been confirmed
                if not log or not getattr(log, "day_type", None):
                    return ""

                # Block absent days (future-proofing; your schema/comment allows 'absent')
                if str(log.day_type).lower() == "absent":
                    return ""

            # ---------------------------------------------------------------

            event_id = self.generate_id()
            event = PointEvent(
                id=event_id,
                student_id=event_data['studentId'],
                placement_id=placement_id,
                session_id=event_data.get('sessionId'),  # Optional session_id for partial-day sessions
                date=event_date,
                type=PointEventType[event_data['type']],
                code=event_data['code'],
                value=event_data['value'],
                notes=event_data.get('notes'),
                created_by=event_data.get('createdBy'),
                created_at=datetime.fromisoformat(event_data.get('createdAt', central_now_naive().isoformat()))
            )
            session.add(event)
            session.commit()
            
            # Update daily log totals
            self.update_daily_log_totals(event_data['placementId'], event_data['date'])
            
            return event_id
        finally:
            session.close()
    
    def get_point_events_for_date(self, placement_id: str, event_date: str) -> List[Dict[str, Any]]:
        """Get all point events for a placement on a specific date."""
        session = self.get_session()
        try:
            date_obj = datetime.fromisoformat(event_date).date() if isinstance(event_date, str) else event_date
            events = session.query(PointEvent).filter(
                PointEvent.placement_id == placement_id,
                PointEvent.date == date_obj
            ).all()
            return [self._point_event_to_dict(e) for e in events]
        finally:
            session.close()
    
    def get_point_events_for_session(self, session_id: str, event_date: str) -> List[Dict[str, Any]]:
        """Get all point events for a specific session on a specific date."""
        db_session = self.get_session()
        try:
            date_obj = datetime.fromisoformat(event_date).date() if isinstance(event_date, str) else event_date
            events = db_session.query(PointEvent).filter(
                PointEvent.session_id == session_id,
                PointEvent.date == date_obj
            ).all()
            return [self._point_event_to_dict(e) for e in events]
        finally:
            db_session.close()
    
    def get_all_point_events_for_placement(self, placement_id: str) -> List[Dict[str, Any]]:
        """Get all point events for a placement."""
        session = self.get_session()
        try:
            events = session.query(PointEvent).filter(
                PointEvent.placement_id == placement_id
            ).order_by(PointEvent.date.desc(), PointEvent.created_at.desc()).all()
            return [self._point_event_to_dict(e) for e in events]
        finally:
            session.close()
    
    def delete_point_event(self, event_id: str) -> bool:
        """Delete a point event by ID."""
        session = self.get_session()
        try:
            event = session.query(PointEvent).filter(PointEvent.id == event_id).first()
            if event:
                placement_id = event.placement_id
                event_date = event.date.isoformat()
                session.delete(event)
                session.commit()
                
                # Update daily log totals after deletion
                self.update_daily_log_totals(placement_id, event_date)
                
                return True
            return False
        finally:
            session.close()
    
    def get_todays_points(self, placement_id: str) -> int:
        """Get today's total points for a placement."""
        today = central_today().isoformat()
        events = self.get_point_events_for_date(placement_id, today)
        return sum(event['value'] for event in events)
    
    def get_cumulative_total(self, placement_id: str) -> int:
        """Get cumulative total points for a placement."""
        all_events = self.get_all_point_events_for_placement(placement_id)
        return sum(event['value'] for event in all_events)
    
    # Assignment operations
    def add_assignment(self, assignment_data: Dict[str, Any]) -> str:
        """Add a new assignment."""
        session = self.get_session()
        try:
            assignment_id = self.generate_id()
            assignment = Assignment(
                id=assignment_id,
                student_id=assignment_data['studentId'],
                teacher_id=assignment_data.get('teacherId'),
                placement_id=assignment_data.get('placementId'),
                title=assignment_data['title'],
                link_or_file_ref=assignment_data.get('linkOrFileRef'),
                due_date=datetime.fromisoformat(assignment_data['dueDate']).date() if assignment_data.get('dueDate') else None,
                status=AssignmentStatus.assigned,
                notes=assignment_data.get('notes')
            )
            session.add(assignment)
            session.commit()
            return assignment_id
        finally:
            session.close()
    
    def get_all_assignments_with_students(self) -> List[Dict[str, Any]]:
        """Get all assignments with student information.
        
        Uses batch student lookup to minimize database calls.
        """
        session = self.get_session()
        try:
            assignments = session.query(Assignment).all()
            
            # BATCH OPTIMIZATION: Collect all student IDs and fetch in one query
            student_ids = list({a.student_id for a in assignments if a.student_id})
            students_by_id = self.get_students_by_ids(student_ids)
            
            result = []
            for assignment in assignments:
                student = students_by_id.get(assignment.student_id)
                if student:
                    assignment_dict = self._assignment_to_dict(assignment)
                    assignment_dict['student'] = student
                    result.append(assignment_dict)
            return result
        finally:
            session.close()
    
    def update_assignment_status(self, assignment_id: str, new_status: str) -> bool:
        """Update an assignment's status."""
        session = self.get_session()
        try:
            assignment = session.query(Assignment).filter(Assignment.id == assignment_id).first()
            if assignment:
                assignment.status = AssignmentStatus[new_status]
                session.commit()
                return True
            return False
        finally:
            session.close()
    
    # Notes operations
    def add_note(self, note_data: Dict[str, Any]) -> str:
        """Add a new note."""
        session = self.get_session()
        try:
            note_id = self.generate_id()
            note = Note(
                id=note_id,
                student_id=note_data['studentId'],
                author_id=note_data['authorId'],
                text=note_data['text'],
                share_with_parent=note_data.get('shareWithParent', False),
                created_at=datetime.fromisoformat(note_data.get('createdAt', central_now_naive().isoformat()))
            )
            session.add(note)
            session.commit()
            return note_id
        finally:
            session.close()
    
    def get_all_notes_with_students(self) -> List[Dict[str, Any]]:
        """Get all notes with student information.
        
        Uses batch student lookup to minimize database calls.
        """
        session = self.get_session()
        try:
            notes = session.query(Note).order_by(Note.created_at.desc()).all()
            
            # BATCH OPTIMIZATION: Collect all student IDs and fetch in one query
            student_ids = list({n.student_id for n in notes if n.student_id})
            students_by_id = self.get_students_by_ids(student_ids)
            
            result = []
            for note in notes:
                student = students_by_id.get(note.student_id)
                if student:
                    note_dict = self._note_to_dict(note)
                    note_dict['student'] = student
                    result.append(note_dict)
            return result
        finally:
            session.close()
    
    # Helper methods to convert ORM objects to dictionaries
    def _student_to_dict(self, student: Student) -> Dict[str, Any]:
        """Convert Student ORM object to dictionary."""
        return {
            '_id': student.id,
            'firstName': student.first_name,
            'lastName': student.last_name,
            'grade': student.grade,
            'homeroomTeacher': student.homeroom_teacher,
            'guardianContacts': student.guardian_contacts,
            'status': student.status.value if student.status else 'active'  # Default to 'active' if status is None
        }
    
    def _placement_to_dict(self, placement: Placement) -> Dict[str, Any]:
        """Convert Placement ORM object to dictionary."""
        # Calculate periods remaining dynamically for ISS placements
        iss_total_required = placement.iss_total_required_periods or 0
        iss_periods_served = placement.iss_periods_served or 0
        periods_remaining = max(0, iss_total_required - iss_periods_served)
        num_days = placement.iss_days_assigned or placement.iss_total_days or placement.days_assigned
        
        # Derive ISS status based on periods served
        # - Not Started: periods served == 0
        # - In Progress: periods served > 0 AND periods served < required
        # - Completed: periods served >= required OR placement status is completed
        is_placement_completed = placement.status == PlacementStatus.completed
        if is_placement_completed or (iss_total_required > 0 and iss_periods_served >= iss_total_required):
            iss_status = "Completed"
        elif iss_periods_served > 0:
            iss_status = "In Progress"
        else:
            iss_status = "Not Started"
        
        # Debug output for ISS period-based model verification (temporary)
        if placement.placement_type == PlacementCategory.ISS:
            print(f"[DEBUG ISS MODEL] Loading ISS placement {placement.id[:8]}...:")
            print(f"  - num_days: {num_days}")
            print(f"  - periods_per_full_day: {PERIODS_PER_FULL_DAY}")
            print(f"  - required_total_periods: {iss_total_required}")
            print(f"  - served_periods_total: {iss_periods_served}")
            print(f"  - periods_remaining: {periods_remaining}")
            print(f"  - iss_status: {iss_status}")
        
        return {
            '_id': placement.id,
            'studentId': placement.student_id,
            'homeroomTeacherId': placement.homeroom_teacher_id,
            'reason': placement.reason,
            'type': placement.type.value,
            'placementType': placement.placement_type.value,
            'completionRule': placement.completion_rule.value,
            'minSessionsRequired': placement.min_sessions_required,
            'daysAssigned': placement.days_assigned,
            'daysCompleted': placement.days_completed or 0,
            'totalIssPeriods': placement.total_iss_periods,  # DEPRECATED but kept for backward compatibility
            'issStartDate': placement.iss_start_date.isoformat() if placement.iss_start_date else None,
            'issTotalDays': placement.iss_total_days,
            'issRemainingDays': placement.iss_remaining_days,
            # Period-based ISS tracking (new standard fields)
            'periodsPerFullDay': PERIODS_PER_FULL_DAY,  # Constant: 10 periods per school day
            'numDays': num_days,  # Alias for clarity
            'issDaysAssigned': placement.iss_days_assigned,
            'issTotalRequiredPeriods': placement.iss_total_required_periods,
            'requiredTotalPeriods': iss_total_required,  # Alias for clarity
            'issPeriodsServed': iss_periods_served,
            'servedPeriodsTotal': iss_periods_served,  # Alias for clarity
            'periodsRemaining': periods_remaining,  # Dynamically computed
            'issStatus': iss_status,  # Derived: "Not Started" / "In Progress" / "Completed"
            'startDate': placement.start_date.isoformat(),
            'endDate': placement.end_date.isoformat() if placement.end_date else None,
            'startPeriod': placement.start_period,
            'endPeriod': placement.end_period,
            'scheduledIssDates': placement.scheduled_iss_dates or [],
            'scheduledIssSessions': placement.scheduled_iss_sessions or [],
            'servedDates': placement.served_dates or [],
            'scheduledLunchDates': placement.scheduled_lunch_dates or [],
            'referralSubtype': placement.referral_subtype,
            'status': placement.status.value,
            'progressStatus': placement.progress_status.value if placement.progress_status else PlacementProgressStatus.NOT_STARTED.value,
            'createdBy': placement.created_by,
            'createdAt': placement.created_at.isoformat() if placement.created_at else None,
            'issLabel': placement.iss_label,
            'isFlexibleSessionMode': placement.is_flexible_session_mode or False,
            # Early closure tracking
            'closedEarly': placement.closed_early or False,
            'earlyClosureNote': placement.early_closure_note,
            'periodsWaived': placement.periods_waived or 0,
            # Make-up day tracking
            'originalDayCount': placement.original_day_count,  # Original "Day of Days" count - NEVER changes
            # Make-up / misc note (useful for non-ISS metadata too)
            'makeupDaysUsed': placement.makeup_days_used or 0,
            'makeupPeriodsServed': placement.makeup_periods_served or 0,
            'makeupNote': placement.makeup_note
        }
    
    def _daily_log_to_dict(self, log: DailyLog) -> Dict[str, Any]:
        """Convert DailyLog ORM object to dictionary."""
        return {
            '_id': log.id,
            'placementId': log.placement_id,
            'date': log.date.isoformat(),
            'positiveTotal': log.positive_total,
            'negativeTotal': log.negative_total,
            'dailyTotal': log.daily_total,
            'readiness': log.readiness,
            'dailyFulfillment': log.daily_fulfillment,
            'alertFlag': log.alert_flag,
            'finalizedBy': log.finalized_by,
            'finalizedAt': log.finalized_at.isoformat() if log.finalized_at else None,
            'notes': log.notes,
            # New fields for simplified ISS model
            'dayType': log.day_type,
            'periodsCovered': log.periods_covered or [],
            'overrideUsed': log.override_used or False,
            'overrideComment': log.override_comment,
            # Period-based fields for partial day ISS
            'startPeriod': log.start_period,
            'endPeriod': log.end_period,
            'requiredPoints': log.required_points,
            # Check-in workflow fields
            'checkedIn': log.checked_in or False,
            'checkedInAt': log.checked_in_at.isoformat() if log.checked_in_at else None,
            # No Show fields
            'noShow': log.no_show or False,
            'noShowNote': log.no_show_note,
            # Make-up session fields
            'isMakeupSession': log.is_makeup_session or False,
            'periodsAdded': log.periods_added
        }
    
    def _point_event_to_dict(self, event: PointEvent) -> Dict[str, Any]:
        """Convert PointEvent ORM object to dictionary."""
        return {
            '_id': event.id,
            'studentId': event.student_id,
            'placementId': event.placement_id,
            'date': event.date.isoformat(),
            'type': event.type.value,
            'code': event.code,
            'value': event.value,
            'notes': event.notes,
            'createdBy': event.created_by,
            'createdAt': event.created_at.isoformat() if event.created_at else None
        }
    
    def _assignment_to_dict(self, assignment: Assignment) -> Dict[str, Any]:
        """Convert Assignment ORM object to dictionary."""
        return {
            '_id': assignment.id,
            'studentId': assignment.student_id,
            'teacherId': assignment.teacher_id,
            'placementId': assignment.placement_id,
            'title': assignment.title,
            'linkOrFileRef': assignment.link_or_file_ref,
            'dueDate': assignment.due_date.isoformat() if assignment.due_date else None,
            'status': assignment.status.value,
            'notes': assignment.notes
        }
    
    def _note_to_dict(self, note: Note) -> Dict[str, Any]:
        """Convert Note ORM object to dictionary."""
        return {
            '_id': note.id,
            'studentId': note.student_id,
            'authorId': note.author_id,
            'text': note.text,
            'shareWithParent': note.share_with_parent,
            'createdAt': note.created_at.isoformat() if note.created_at else None
        }
    
    def process_end_of_day(self, target_date: date) -> Dict[str, int]:
        """Process end-of-day for a specific date.
        
        Finds all DailyLog records and ISS sessions for the date where not completed,
        marks them as incomplete/no_show, sets alert_flag to True, and records the processing.
        
        Special handling for Class Period Referrals (all subtypes):
        - Auto-complete at midnight (mark as 'yes') instead of marking incomplete
        - If No Show was selected for Pre-Planned, keep as Completed (No Show)
        
        Args:
            target_date: The date to process (typically yesterday)
            
        Returns:
            Dict with incomplete_logs and incomplete_sessions counts
        """
        session = self.get_session()
        try:
            existing = session.query(EndOfDayProcessing).filter(
                EndOfDayProcessing.processing_date == target_date
            ).first()
            
            if existing:
                return {'incomplete_logs': 0, 'incomplete_sessions': 0}
            
            incomplete_logs = session.query(DailyLog).filter(
                DailyLog.date == target_date,
                or_(DailyLog.daily_fulfillment != 'yes', DailyLog.daily_fulfillment.is_(None))
            ).all()
            
            class_referral_auto_completed = 0
            for log in incomplete_logs:
                # Get the placement to check if it's a Class Period Referral
                placement = session.query(Placement).filter(
                    Placement.id == log.placement_id
                ).first()
                
                if placement and placement.placement_type.value in ['CLASS_REFERRAL', 'COOL_DOWN', 'PRE_PLANNED_REFERRAL']:
                    # Auto-complete Class Period Referrals at midnight
                    log.daily_fulfillment = 'yes'
                    log.finalized_by = 'System (End of Day)'
                    log.finalized_at = central_now_naive()
                    class_referral_auto_completed += 1
                    
                    # For Pre-Planned referrals, set attendance based on check-in status
                    if placement.referral_subtype == 'pre_planned':
                        # If not checked in, mark as no_show (Absent)
                        if not log.checked_in:
                            log.no_show = True
                        # Update session status based on check-in
                        sess = session.query(PartialDaySession).filter(
                            PartialDaySession.placement_id == log.placement_id,
                            PartialDaySession.date == log.date
                        ).first()
                        if sess and sess.status in [SessionStatus.scheduled, SessionStatus.in_progress]:
                            if log.checked_in:
                                sess.status = SessionStatus.fulfilled
                            else:
                                sess.status = SessionStatus.no_show
                    
                    # Update placement days_completed for auto-completed referrals
                    if placement:
                        placement.days_completed = (placement.days_completed or 0) + 1
                        days_assigned = placement.days_assigned or 1
                        if placement.days_completed >= days_assigned:
                            placement.status = PlacementStatus.completed
                            placement.progress_status = PlacementProgressStatus.COMPLETED
                            placement.end_date = target_date
                else:
                    # For ISS and other types, mark as incomplete
                    log.daily_fulfillment = 'no'
                    log.alert_flag = True
            
            incomplete_sessions = session.query(PartialDaySession).filter(
                PartialDaySession.date == target_date,
                PartialDaySession.type == SessionType.iss_full_day,
                PartialDaySession.status.in_([SessionStatus.scheduled, SessionStatus.in_progress])
            ).all()
            
            iss_session_ids = []
            for sess in incomplete_sessions:
                sess.status = SessionStatus.no_show
                sess.alert_flag = True
                sess.alert_sent = True
                sess.alert_timestamp = central_now_naive()
                iss_session_ids.append(sess.id)
                
                log = session.query(DailyLog).filter(
                    DailyLog.placement_id == sess.placement_id,
                    DailyLog.date == sess.date
                ).first()
                
                if not log:
                    log_id = self.generate_id()
                    log = DailyLog(
                        id=log_id,
                        placement_id=sess.placement_id,
                        date=sess.date,
                        positive_total=0,
                        negative_total=0,
                        daily_total=0,
                        readiness='continue',
                        daily_fulfillment='no',
                        alert_flag=True
                    )
                    session.add(log)
                else:
                    if log.daily_fulfillment != 'yes':
                        log.daily_fulfillment = 'no'
                        log.alert_flag = True
            
            processing_id = self.generate_id()
            processed_at = central_now_naive()
            processing_record = EndOfDayProcessing(
                id=processing_id,
                processing_date=target_date,
                processed_at=processed_at,
                incomplete_count=len(incomplete_logs) + len(incomplete_sessions),
                notification_sent=True
            )
            session.add(processing_record)
            
            try:
                session.commit()
            except IntegrityError:
                # Another session processed the same date first (unique constraint hit).
                # Treat as already processed and safely no-op.
                session.rollback()
                return {
                    'incomplete_logs': 0,
                    'incomplete_sessions': 0,
                    'iss_session_ids': [],
                    'class_referral_auto_completed': 0
                }
            
            return {
                'incomplete_logs': len(incomplete_logs) - class_referral_auto_completed,  # Only count non-auto-completed
                'incomplete_sessions': len(incomplete_sessions),
                'iss_session_ids': iss_session_ids,
                'class_referral_auto_completed': class_referral_auto_completed
            }
        except Exception as e:
            session.rollback()
            print(f"Error processing end-of-day for {target_date}: {e}")
            return {'incomplete_logs': 0, 'incomplete_sessions': 0, 'iss_session_ids': [], 'class_referral_auto_completed': 0}
        finally:
            session.close()
    
    def check_and_process_pending_dates(self) -> List[Dict[str, Any]]:
        """Check for dates that need end-of-day processing and process them.
        
        Returns list of processing results with date and incomplete counts.
        """
        session = self.get_session()
        results = []
        
        try:
            latest_processing = session.query(EndOfDayProcessing).order_by(
                EndOfDayProcessing.processing_date.desc()
            ).first()
            
            today = central_today()
            yesterday = today - timedelta(days=1)
            
            if latest_processing:
                last_processed_date = latest_processing.processing_date
                check_date = last_processed_date + timedelta(days=1)
            else:
                check_date = yesterday - timedelta(days=6)
            
            current_date = check_date
            while current_date < today:
                if not self.is_non_school_day(current_date):
                    result = self.process_end_of_day(current_date)
                    total_incomplete = result.get('incomplete_logs', 0) + result.get('incomplete_sessions', 0)
                    if total_incomplete > 0:
                        results.append({
                            'date': current_date.isoformat(),
                            'incomplete_logs': result.get('incomplete_logs', 0),
                            'incomplete_sessions': result.get('incomplete_sessions', 0),
                            'iss_session_ids': result.get('iss_session_ids', [])
                        })
                current_date += timedelta(days=1)
            
            return results
        finally:
            session.close()
    
    def get_eod_incomplete_records(self, target_date: date) -> List[Dict[str, Any]]:
        """Get incomplete records that were marked during end-of-day processing.
        
        Args:
            target_date: The date to get incomplete records for
            
        Returns:
            List of incomplete record details with student and placement info
        """
        session = self.get_session()
        try:
            # Get all daily logs marked as incomplete (daily_fulfillment='no' and alert_flag=True)
            incomplete_logs = session.query(DailyLog).filter(
                DailyLog.date == target_date,
                DailyLog.daily_fulfillment == 'no',
                DailyLog.alert_flag == True
            ).all()
            
            results = []
            for log in incomplete_logs:
                placement = session.query(Placement).filter(Placement.id == log.placement_id).first()
                if placement:
                    student = session.query(Student).filter(Student.id == placement.student_id).first()
                    if student:
                        results.append({
                            'student_name': f"{student.first_name} {student.last_name}",
                            'student_id': student.id,
                            'placement_type': placement.placement_type.value,
                            'date': target_date.isoformat(),
                            'homeroom_teacher': placement.homeroom_teacher_id or student.homeroom_teacher
                        })
            
            return results
        finally:
            session.close()
    
    def dismiss_notification(self, notification_id: str, notification_data: Dict[str, Any], dismissed_by: str = None) -> bool:
        """Dismiss a notification by storing its dismissed state.
        
        Args:
            notification_id: Unique identifier for the notification (type:record_id:date format)
            notification_data: Dictionary containing notification details for historical display
            dismissed_by: Optional - who dismissed the notification
            
        Returns:
            True if successfully dismissed, False otherwise
        """
        session = self.get_session()
        try:
            # Check if already dismissed
            existing = session.query(DismissedNotification).filter(
                DismissedNotification.notification_id == notification_id
            ).first()
            
            if existing:
                return True  # Already dismissed
            
            dismissed = DismissedNotification(
                id=str(uuid.uuid4()),
                notification_id=notification_id,
                notification_type=notification_data.get('type', ''),
                notification_title=notification_data.get('title', ''),
                notification_message=notification_data.get('message', ''),
                notification_severity=notification_data.get('severity', 'info'),
                original_timestamp=notification_data.get('timestamp'),
                dismissed_at=central_now_naive(),
                dismissed_by=dismissed_by
            )
            
            session.add(dismissed)
            session.commit()
            return True
        except Exception as e:
            session.rollback()
            print(f"Error dismissing notification: {e}")
            return False
        finally:
            session.close()
    
    def is_notification_dismissed(self, notification_id: str) -> bool:
        """Check if a notification has been dismissed.
        
        Args:
            notification_id: Unique identifier for the notification
            
        Returns:
            True if dismissed, False otherwise
        """
        session = self.get_session()
        try:
            exists = session.query(DismissedNotification).filter(
                DismissedNotification.notification_id == notification_id
            ).first() is not None
            return exists
        finally:
            session.close()
    
    def get_dismissed_notification_ids(self) -> set:
        """Get all dismissed notification IDs as a set for efficient lookup.
        
        Returns:
            Set of dismissed notification IDs
        """
        session = self.get_session()
        try:
            dismissed = session.query(DismissedNotification.notification_id).all()
            return {d[0] for d in dismissed}
        finally:
            session.close()
    
    def get_dismissed_notifications(self) -> List[Dict[str, Any]]:
        """Get all dismissed notifications for display in the Dismissed tab.
        
        Returns:
            List of dismissed notification dictionaries sorted by dismissed_at (most recent first)
        """
        session = self.get_session()
        try:
            dismissed_list = session.query(DismissedNotification).order_by(
                DismissedNotification.dismissed_at.desc()
            ).all()
            
            return [{
                'notification_id': d.notification_id,
                'type': d.notification_type,
                'title': d.notification_title,
                'message': d.notification_message,
                'severity': d.notification_severity,
                'timestamp': d.original_timestamp,
                'dismissed_at': d.dismissed_at,
                'dismissed_by': d.dismissed_by
            } for d in dismissed_list]
        finally:
            session.close()
    
    def restore_notification(self, notification_id: str) -> bool:
        """Restore a dismissed notification back to active state.
        
        Args:
            notification_id: Unique identifier for the notification
            
        Returns:
            True if successfully restored, False otherwise
        """
        session = self.get_session()
        try:
            deleted = session.query(DismissedNotification).filter(
                DismissedNotification.notification_id == notification_id
            ).delete()
            session.commit()
            return deleted > 0
        except Exception as e:
            session.rollback()
            print(f"Error restoring notification: {e}")
            return False
        finally:
            session.close()
