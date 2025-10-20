import csv
import io
from datetime import datetime
from typing import List, Dict, Any
import pandas as pd

class ImportExportManager:
    """Manager for bulk import/export operations."""
    
    def __init__(self, db_manager):
        self.db = db_manager
    
    # Student Import/Export
    def export_students_csv(self) -> str:
        """Export all students to CSV format."""
        students = self.db.get_all_students()
        
        if not students:
            return ""
        
        output = io.StringIO()
        fieldnames = ['firstName', 'lastName', 'grade', 'homeroomTeacher', 'status']
        
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        
        for student in students:
            writer.writerow({
                'firstName': student['firstName'],
                'lastName': student['lastName'],
                'grade': student['grade'],
                'homeroomTeacher': student['homeroomTeacher'],
                'status': student.get('status', 'active')
            })
        
        return output.getvalue()
    
    def import_students_csv(self, csv_content: str) -> Dict[str, Any]:
        """
        Import students from CSV content.
        Returns dict with success count and errors.
        """
        results = {
            'success_count': 0,
            'error_count': 0,
            'errors': []
        }
        
        try:
            csv_file = io.StringIO(csv_content)
            reader = csv.DictReader(csv_file)
            
            required_fields = ['firstName', 'lastName', 'grade', 'homeroomTeacher']
            
            for row_num, row in enumerate(reader, start=2):
                try:
                    # Validate required fields
                    missing_fields = [f for f in required_fields if not row.get(f)]
                    if missing_fields:
                        results['errors'].append(
                            f"Row {row_num}: Missing required fields: {', '.join(missing_fields)}"
                        )
                        results['error_count'] += 1
                        continue
                    
                    # Create student data
                    student_data = {
                        'firstName': row['firstName'].strip(),
                        'lastName': row['lastName'].strip(),
                        'grade': row['grade'].strip(),
                        'homeroomTeacher': row['homeroomTeacher'].strip(),
                        'guardianContacts': [],
                        'status': 'active'
                    }
                    
                    # Add student to database
                    self.db.add_student(student_data)
                    results['success_count'] += 1
                    
                except Exception as e:
                    results['errors'].append(f"Row {row_num}: {str(e)}")
                    results['error_count'] += 1
            
        except Exception as e:
            results['errors'].append(f"File parsing error: {str(e)}")
            results['error_count'] += 1
        
        return results
    
    # Placement Import/Export
    def export_placements_csv(self) -> str:
        """Export all placements to CSV format."""
        session = self.db.get_session()
        try:
            from db_manager import Placement, Student
            
            placements = session.query(Placement).all()
            
            if not placements:
                return ""
            
            output = io.StringIO()
            fieldnames = [
                'studentFirstName', 'studentLastName', 'reason', 
                'daysAssigned', 'startDate', 'status', 'createdBy', 'createdAt'
            ]
            
            writer = csv.DictWriter(output, fieldnames=fieldnames)
            writer.writeheader()
            
            for placement in placements:
                student = session.query(Student).filter(Student.id == placement.student_id).first()
                if student:
                    writer.writerow({
                        'studentFirstName': student.first_name,
                        'studentLastName': student.last_name,
                        'reason': placement.reason,
                        'daysAssigned': placement.days_assigned,
                        'startDate': placement.start_date.isoformat(),
                        'status': placement.status.value,
                        'createdBy': placement.created_by or '',
                        'createdAt': placement.created_at.isoformat() if placement.created_at else ''
                    })
            
            return output.getvalue()
        finally:
            session.close()
    
    def export_point_events_csv(self) -> str:
        """Export all point events to CSV format."""
        session = self.db.get_session()
        try:
            from db_manager import PointEvent, Student
            
            events = session.query(PointEvent).all()
            
            if not events:
                return ""
            
            output = io.StringIO()
            fieldnames = [
                'studentFirstName', 'studentLastName', 'date', 
                'type', 'code', 'value', 'notes', 'createdBy', 'createdAt'
            ]
            
            writer = csv.DictWriter(output, fieldnames=fieldnames)
            writer.writeheader()
            
            for event in events:
                student = session.query(Student).filter(Student.id == event.student_id).first()
                if student:
                    writer.writerow({
                        'studentFirstName': student.first_name,
                        'studentLastName': student.last_name,
                        'date': event.date.isoformat(),
                        'type': event.type.value,
                        'code': event.code,
                        'value': event.value,
                        'notes': event.notes or '',
                        'createdBy': event.created_by or '',
                        'createdAt': event.created_at.isoformat() if event.created_at else ''
                    })
            
            return output.getvalue()
        finally:
            session.close()
    
    def export_assignments_csv(self) -> str:
        """Export all assignments to CSV format."""
        session = self.db.get_session()
        try:
            from db_manager import Assignment, Student
            
            assignments = session.query(Assignment).all()
            
            if not assignments:
                return ""
            
            output = io.StringIO()
            fieldnames = [
                'studentFirstName', 'studentLastName', 'title', 
                'teacherId', 'dueDate', 'status', 'linkOrFileRef', 'notes'
            ]
            
            writer = csv.DictWriter(output, fieldnames=fieldnames)
            writer.writeheader()
            
            for assignment in assignments:
                student = session.query(Student).filter(Student.id == assignment.student_id).first()
                if student:
                    writer.writerow({
                        'studentFirstName': student.first_name,
                        'studentLastName': student.last_name,
                        'title': assignment.title,
                        'teacherId': assignment.teacher_id or '',
                        'dueDate': assignment.due_date.isoformat() if assignment.due_date else '',
                        'status': assignment.status.value,
                        'linkOrFileRef': assignment.link_or_file_ref or '',
                        'notes': assignment.notes or ''
                    })
            
            return output.getvalue()
        finally:
            session.close()
    
    def export_notes_csv(self) -> str:
        """Export all notes to CSV format."""
        session = self.db.get_session()
        try:
            from db_manager import Note, Student
            
            notes = session.query(Note).all()
            
            if not notes:
                return ""
            
            output = io.StringIO()
            fieldnames = [
                'studentFirstName', 'studentLastName', 'authorId', 
                'text', 'shareWithParent', 'createdAt'
            ]
            
            writer = csv.DictWriter(output, fieldnames=fieldnames)
            writer.writeheader()
            
            for note in notes:
                student = session.query(Student).filter(Student.id == note.student_id).first()
                if student:
                    writer.writerow({
                        'studentFirstName': student.first_name,
                        'studentLastName': student.last_name,
                        'authorId': note.author_id,
                        'text': note.text,
                        'shareWithParent': 'Yes' if note.share_with_parent else 'No',
                        'createdAt': note.created_at.isoformat() if note.created_at else ''
                    })
            
            return output.getvalue()
        finally:
            session.close()
    
    def export_daily_logs_csv(self) -> str:
        """Export all daily logs to CSV format."""
        session = self.db.get_session()
        try:
            from db_manager import DailyLog, Placement, Student
            
            logs = session.query(DailyLog).all()
            
            if not logs:
                return ""
            
            output = io.StringIO()
            fieldnames = [
                'studentFirstName', 'studentLastName', 'date', 
                'positiveTotal', 'negativeTotal', 'dailyTotal', 
                'readiness', 'finalizedBy', 'finalizedAt'
            ]
            
            writer = csv.DictWriter(output, fieldnames=fieldnames)
            writer.writeheader()
            
            for log in logs:
                placement = session.query(Placement).filter(Placement.id == log.placement_id).first()
                if placement:
                    student = session.query(Student).filter(Student.id == placement.student_id).first()
                    if student:
                        writer.writerow({
                            'studentFirstName': student.first_name,
                            'studentLastName': student.last_name,
                            'date': log.date.isoformat(),
                            'positiveTotal': log.positive_total,
                            'negativeTotal': log.negative_total,
                            'dailyTotal': log.daily_total,
                            'readiness': log.readiness,
                            'finalizedBy': log.finalized_by or '',
                            'finalizedAt': log.finalized_at.isoformat() if log.finalized_at else ''
                        })
            
            return output.getvalue()
        finally:
            session.close()
    
    def get_student_template_csv(self) -> str:
        """Generate a CSV template for student import."""
        output = io.StringIO()
        fieldnames = ['firstName', 'lastName', 'grade', 'homeroomTeacher']
        
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        
        # Add example row
        writer.writerow({
            'firstName': 'John',
            'lastName': 'Doe',
            'grade': '5',
            'homeroomTeacher': 'Ms. Smith'
        })
        
        return output.getvalue()
