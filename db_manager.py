import os
import uuid
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional, Any
from sqlalchemy import create_engine, Column, String, Integer, Boolean, DateTime, Date, JSON, Text, Enum as SQLEnum, UniqueConstraint
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
import enum

Base = declarative_base()

# Define enums
class StudentStatus(enum.Enum):
    active = "active"
    deleted = "deleted"

class PlacementStatus(enum.Enum):
    active = "active"
    completed = "completed"

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
    days_assigned = Column(Integer, nullable=False)
    start_date = Column(Date, nullable=False)
    status = Column(SQLEnum(PlacementStatus), default=PlacementStatus.active)
    created_by = Column(String)
    created_at = Column(DateTime, default=datetime.now)

class DailyLog(Base):
    __tablename__ = 'daily_logs'
    
    id = Column(String, primary_key=True)
    placement_id = Column(String, nullable=False)
    date = Column(Date, nullable=False)
    positive_total = Column(Integer, default=0)
    negative_total = Column(Integer, default=0)
    daily_total = Column(Integer, default=0)
    readiness = Column(String, default='continue')
    finalized_by = Column(String)
    finalized_at = Column(DateTime)
    
    __table_args__ = (UniqueConstraint('placement_id', 'date', name='uix_placement_date'),)

class PointEvent(Base):
    __tablename__ = 'point_events'
    
    id = Column(String, primary_key=True)
    student_id = Column(String, nullable=False)
    placement_id = Column(String, nullable=False)
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
            self.engine = create_engine(database_url)
            Base.metadata.create_all(self.engine)
            self.SessionLocal = sessionmaker(bind=self.engine)
        except Exception as e:
            import streamlit as st
            st.error(f"❌ Database connection failed: {str(e)}")
            st.info("Please ensure DATABASE_URL is properly configured and the database is accessible.")
            st.stop()
    
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
            placement = Placement(
                id=placement_id,
                student_id=placement_data['studentId'],
                homeroom_teacher_id=placement_data.get('homeroomTeacherId'),
                reason=placement_data['reason'],
                days_assigned=placement_data['daysAssigned'],
                start_date=datetime.fromisoformat(placement_data['startDate']).date(),
                status=PlacementStatus.active,
                created_by=placement_data.get('createdBy'),
                created_at=datetime.fromisoformat(placement_data.get('createdAt', datetime.now().isoformat()))
            )
            session.add(placement)
            session.commit()
            return placement_id
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
        """Get active placements with student information."""
        active_placements = self.get_active_placements()
        result = []
        
        for placement in active_placements:
            student = self.get_student(placement['studentId'])
            if student:
                placement_with_student = placement.copy()
                placement_with_student['student'] = student
                result.append(placement_with_student)
        
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
                session.commit()
                return True
            return False
        finally:
            session.close()
    
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
    
    def finalize_daily_log(self, log_id: str, readiness: str, finalized_by: str) -> bool:
        """Finalize a daily log."""
        session = self.get_session()
        try:
            log = session.query(DailyLog).filter(DailyLog.id == log_id).first()
            if log:
                log.readiness = readiness
                log.finalized_by = finalized_by
                log.finalized_at = datetime.now()
                session.commit()
                return True
            return False
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
            'status': student.status.value
        }
    
    def _placement_to_dict(self, placement: Placement) -> Dict[str, Any]:
        """Convert Placement ORM object to dictionary."""
        return {
            '_id': placement.id,
            'studentId': placement.student_id,
            'homeroomTeacherId': placement.homeroom_teacher_id,
            'reason': placement.reason,
            'daysAssigned': placement.days_assigned,
            'startDate': placement.start_date.isoformat(),
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
            'finalizedBy': log.finalized_by,
            'finalizedAt': log.finalized_at.isoformat() if log.finalized_at else None
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
