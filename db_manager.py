import os
import uuid
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional, Any
from sqlalchemy import create_engine, Column, String, Integer, Boolean, DateTime, Date, JSON, Text, Enum as SQLEnum, UniqueConstraint, or_
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
import enum
from utils import add_business_days, get_school_days

Base = declarative_base()

# Define enums
class StudentStatus(enum.Enum):
    active = "active"
    deleted = "deleted"

class PlacementStatus(enum.Enum):
    active = "active"
    completed = "completed"

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
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=True)  # Set when placement is completed
    start_period = Column(Integer, nullable=True)  # For CLASS_REFERRAL: starting period (e.g., 1 for P1)
    end_period = Column(Integer, nullable=True)  # For CLASS_REFERRAL: ending period (e.g., 3 for P3)
    scheduled_iss_dates = Column(JSON, default=list)  # Array of scheduled ISS dates (ISO format strings) for full-day ISS
    served_dates = Column(JSON, default=list)  # Array of dates when student was present (ISO format strings)
    status = Column(SQLEnum(PlacementStatus), default=PlacementStatus.active)
    created_by = Column(String)
    created_at = Column(DateTime, default=datetime.now)

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
    notes = Column(Text)

class EndOfDayProcessing(Base):
    __tablename__ = 'end_of_day_processing'
    
    id = Column(String, primary_key=True)
    processing_date = Column(Date, nullable=False, unique=True)  # The date that was processed
    processed_at = Column(DateTime, default=datetime.now)  # When the processing occurred
    incomplete_count = Column(Integer, default=0)  # Number of incomplete records found
    notification_sent = Column(Boolean, default=False)  # Whether notifications were sent

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
                AND column_name IN ('start_period', 'end_period', 'scheduled_iss_dates', 'served_dates')
            """)
            existing_columns = {row[0] for row in result}
            
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
                scheduled_iss_dates = get_school_days(start_date_obj, days_assigned)
                # For ISS (Full), auto-calculate end_date from scheduled dates
                if scheduled_iss_dates:
                    end_date = datetime.fromisoformat(scheduled_iss_dates[-1]).date()
            
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
                start_date=datetime.fromisoformat(placement_data['startDate']).date(),
                end_date=end_date,
                start_period=placement_data.get('startPeriod'),
                end_period=placement_data.get('endPeriod'),
                scheduled_iss_dates=scheduled_iss_dates,
                served_dates=served_dates,
                status=PlacementStatus.active,
                created_by=placement_data.get('createdBy'),
                created_at=datetime.fromisoformat(placement_data.get('createdAt', datetime.now().isoformat()))
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
        """Get all active placements."""
        session = self.get_session()
        try:
            placements = session.query(Placement).filter(Placement.status == PlacementStatus.active).all()
            return [self._placement_to_dict(p) for p in placements]
        finally:
            session.close()
    
    def get_active_placements_with_students(self) -> List[Dict[str, Any]]:
        """Get active placements with student information, sorted by placement type."""
        active_placements = self.get_active_placements()
        result = []
        today = date.today()
        
        for placement in active_placements:
            student = self.get_student(placement['studentId'])
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
        """Get placements that are active on a specific date."""
        active_placements = self.get_active_placements_with_students()
        result = []
        
        for placement in active_placements:
            start_date = datetime.fromisoformat(placement['startDate']).date() if isinstance(placement['startDate'], str) else placement['startDate']
            end_date = start_date + timedelta(days=placement['daysAssigned'])
            
            if start_date <= target_date <= end_date:
                result.append(placement)
        
        return result
    
    def complete_placement(self, placement_id: str) -> bool:
        """Complete a placement."""
        session = self.get_session()
        try:
            placement = session.query(Placement).filter(Placement.id == placement_id).first()
            if placement:
                placement.status = PlacementStatus.completed
                placement.end_date = date.today()
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
                    placement.end_date = date_obj
            else:
                # Student was absent - extend schedule by one school day
                if not scheduled_dates:
                    return False
                
                last_date_str = scheduled_dates[-1]
                last_date = datetime.fromisoformat(last_date_str).date()
                
                # Find next school day
                next_date = last_date + timedelta(days=1)
                while next_date.weekday() >= 5:  # Skip weekends
                    next_date += timedelta(days=1)
                
                # Append to scheduled dates and update end date
                scheduled_dates.append(next_date.isoformat())
                placement.scheduled_iss_dates = scheduled_dates
                placement.end_date = next_date
            
            session.commit()
            return True
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
            if not placement:
                return False
            
            # Only apply to Lunch Detention placements
            if placement.placement_type != PlacementCategory.LUNCH_DETENTION or placement.type != PlacementType.iss_full_day:
                return False
            
            date_obj = datetime.fromisoformat(attendance_date).date()
            date_str = date_obj.isoformat()
            
            # Get current arrays (handle None)
            served_dates = placement.served_dates if placement.served_dates else []
            scheduled_lunch_dates = placement.scheduled_lunch_dates if placement.scheduled_lunch_dates else []
            
            if is_present:
                # Add date to served_dates if not already there
                if date_str not in served_dates:
                    served_dates.append(date_str)
                    placement.served_dates = served_dates
                
                # Check if placement should be completed
                total_required = placement.days_assigned
                if len(served_dates) >= total_required:
                    placement.status = PlacementStatus.completed
                    placement.end_date = date_obj
            else:
                # Student was absent - extend schedule by one school day with lunch
                if not scheduled_lunch_dates:
                    return False
                
                last_date_str = scheduled_lunch_dates[-1]
                last_date = datetime.fromisoformat(last_date_str).date()
                
                # Find next school day with lunch (skip weekends)
                next_date = last_date + timedelta(days=1)
                while next_date.weekday() >= 5:  # Skip weekends
                    next_date += timedelta(days=1)
                
                # Append to scheduled lunch dates and update end date
                scheduled_lunch_dates.append(next_date.isoformat())
                placement.scheduled_lunch_dates = scheduled_lunch_dates
                placement.end_date = next_date
            
            session.commit()
            return True
        finally:
            session.close()
    
    def get_completed_placements_with_students(self) -> List[Dict[str, Any]]:
        """Get all completed placements with student info."""
        session = self.get_session()
        try:
            placements = session.query(Placement).filter(
                Placement.status == PlacementStatus.completed
            ).order_by(Placement.end_date.desc()).all()
            
            result = []
            for placement in placements:
                placement_dict = self._placement_to_dict(placement)
                student = self.get_student(placement.student_id)
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
                    can_complete = date.today() > placement.end_date
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
                if skip_weekends and current_date.weekday() >= 5:  # 5=Saturday, 6=Sunday
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
                if skip_weekends and current_date.weekday() >= 5:  # 5=Saturday, 6=Sunday
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
            if current_date.weekday() < 5:  # Monday=0, Friday=4
                # TODO: Add logic to skip specific no-lunch days (early dismissal, etc.)
                # For now, just add all weekdays with lunch
                scheduled_dates.append(current_date)
            
            current_date += timedelta(days=1)
        
        return scheduled_dates
    
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
    
    def get_todays_sessions(self) -> List[Dict[str, Any]]:
        """Get all sessions scheduled for today with student and placement info."""
        db_session = self.get_session()
        try:
            today = date.today()
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
    
    # Daily Log operations
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
                log.finalized_at = datetime.now()
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
    
    def complete_placement_day(self, placement_id: str, log_date: str, completed_by: str) -> bool:
        """Mark a placement day as complete by setting daily_fulfillment to 'yes'.
        
        This method supports retroactive completion - staff can mark incomplete
        records from past dates as complete while preserving alert history.
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
                    finalized_at=datetime.now()
                )
                session.add(log)
            else:
                old_fulfillment = log.daily_fulfillment
                log.daily_fulfillment = 'yes'
                log.finalized_by = completed_by
                log.finalized_at = datetime.now()
                # Note: We preserve alert_flag for audit history (if alerts were sent for incomplete records)
                # The record is now completed, but the alert history is maintained for accountability
                
                placement = session.query(Placement).filter(Placement.id == placement_id).first()
                if placement and old_fulfillment != 'yes':
                    placement.days_completed = (placement.days_completed or 0) + 1
            
            session.commit()
            return True
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
    
    # Point Event operations
    def add_point_event(self, event_data: Dict[str, Any]) -> str:
        """Add a point event."""
        session = self.get_session()
        try:
            event_id = self.generate_id()
            event = PointEvent(
                id=event_id,
                student_id=event_data['studentId'],
                placement_id=event_data['placementId'],
                session_id=event_data.get('sessionId'),  # Optional session_id for partial-day sessions
                date=datetime.fromisoformat(event_data['date']).date(),
                type=PointEventType[event_data['type']],
                code=event_data['code'],
                value=event_data['value'],
                notes=event_data.get('notes'),
                created_by=event_data.get('createdBy'),
                created_at=datetime.fromisoformat(event_data.get('createdAt', datetime.now().isoformat()))
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
        today = date.today().isoformat()
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
        """Get all assignments with student information."""
        session = self.get_session()
        try:
            assignments = session.query(Assignment).all()
            result = []
            for assignment in assignments:
                student = self.get_student(assignment.student_id)
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
                created_at=datetime.fromisoformat(note_data.get('createdAt', datetime.now().isoformat()))
            )
            session.add(note)
            session.commit()
            return note_id
        finally:
            session.close()
    
    def get_all_notes_with_students(self) -> List[Dict[str, Any]]:
        """Get all notes with student information."""
        session = self.get_session()
        try:
            notes = session.query(Note).order_by(Note.created_at.desc()).all()
            result = []
            for note in notes:
                student = self.get_student(note.student_id)
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
            'startDate': placement.start_date.isoformat(),
            'endDate': placement.end_date.isoformat() if placement.end_date else None,
            'startPeriod': placement.start_period,
            'endPeriod': placement.end_period,
            'scheduledIssDates': placement.scheduled_iss_dates or [],
            'servedDates': placement.served_dates or [],
            'status': placement.status.value,
            'createdBy': placement.created_by,
            'createdAt': placement.created_at.isoformat() if placement.created_at else None
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
            'notes': log.notes
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
    
    def process_end_of_day(self, target_date: date) -> int:
        """Process end-of-day for a specific date.
        
        Finds all DailyLog records for the date where daily_fulfillment is not 'yes',
        marks them as 'no', sets alert_flag to True, and records the processing.
        
        Args:
            target_date: The date to process (typically yesterday)
            
        Returns:
            Number of incomplete records found and marked
        """
        session = self.get_session()
        try:
            # Check if this date has already been processed
            existing = session.query(EndOfDayProcessing).filter(
                EndOfDayProcessing.processing_date == target_date
            ).first()
            
            if existing:
                return 0  # Already processed
            
            # Find all DailyLog records for this date where daily_fulfillment is not 'yes'
            # This includes NULL values and 'no' values
            incomplete_logs = session.query(DailyLog).filter(
                DailyLog.date == target_date,
                or_(DailyLog.daily_fulfillment != 'yes', DailyLog.daily_fulfillment.is_(None))
            ).all()
            
            # Mark each as 'no' and set alert_flag
            for log in incomplete_logs:
                log.daily_fulfillment = 'no'
                log.alert_flag = True
            
            # Record the processing
            processing_id = self.generate_id()
            processing_record = EndOfDayProcessing(
                id=processing_id,
                processing_date=target_date,
                processed_at=datetime.now(),
                incomplete_count=len(incomplete_logs),
                notification_sent=True
            )
            session.add(processing_record)
            session.commit()
            
            return len(incomplete_logs)
        except Exception as e:
            session.rollback()
            print(f"Error processing end-of-day for {target_date}: {e}")
            return 0
        finally:
            session.close()
    
    def check_and_process_pending_dates(self) -> List[Dict[str, Any]]:
        """Check for dates that need end-of-day processing and process them.
        
        Returns list of processing results with date and incomplete count.
        """
        session = self.get_session()
        results = []
        
        try:
            # Get the most recent processing date
            latest_processing = session.query(EndOfDayProcessing).order_by(
                EndOfDayProcessing.processing_date.desc()
            ).first()
            
            # Determine start date for checking
            today = date.today()
            yesterday = today - timedelta(days=1)
            
            if latest_processing:
                last_processed_date = latest_processing.processing_date
                # Start checking from the day after the last processed date
                check_date = last_processed_date + timedelta(days=1)
            else:
                # No previous processing - start from 7 days ago to avoid processing too far back
                check_date = yesterday - timedelta(days=6)
            
            # Process each date from check_date up to (but not including) today
            current_date = check_date
            while current_date < today:
                if current_date.weekday() < 5:  # Only process weekdays (Monday=0, Friday=4)
                    incomplete_count = self.process_end_of_day(current_date)
                    if incomplete_count > 0:
                        results.append({
                            'date': current_date.isoformat(),
                            'incomplete_count': incomplete_count
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
