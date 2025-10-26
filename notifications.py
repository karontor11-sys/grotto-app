from datetime import datetime, date, timedelta
from typing import List, Dict, Any

class NotificationManager:
    """Manager for generating and displaying notifications."""
    
    def __init__(self, db_manager):
        self.db = db_manager
    
    def get_recent_placement_notifications(self, days: int = 7) -> List[Dict[str, Any]]:
        """Get notifications for recently created placements."""
        session = self.db.get_session()
        try:
            from db_manager import Placement, Student
            
            cutoff_date = datetime.now() - timedelta(days=days)
            
            placements = session.query(Placement).filter(
                Placement.created_at >= cutoff_date
            ).order_by(Placement.created_at.desc()).all()
            
            notifications = []
            for placement in placements:
                student = session.query(Student).filter(Student.id == placement.student_id).first()
                if student:
                    notifications.append({
                        'type': 'placement_created',
                        'severity': 'info',
                        'timestamp': placement.created_at,
                        'title': 'New Placement Created',
                        'message': f"{student.first_name} {student.last_name} placed in The Grotto starting {placement.start_date.strftime('%m/%d/%Y')} for {placement.days_assigned} days. Reason: {placement.reason}",
                        'student_id': student.id,
                        'student_name': f"{student.first_name} {student.last_name}",
                        'homeroom_teacher': placement.homeroom_teacher_id or student.homeroom_teacher
                    })
            
            return notifications
        except Exception as e:
            # Log error but don't crash - return empty list
            print(f"Error fetching placement notifications: {e}")
            return []
        finally:
            session.close()
    
    def get_placement_completion_notifications(self, days: int = 7) -> List[Dict[str, Any]]:
        """Get notifications for recently completed placements."""
        session = self.db.get_session()
        try:
            from db_manager import Placement, Student, PlacementStatus
            
            cutoff_date = datetime.now() - timedelta(days=days)
            
            placements = session.query(Placement).filter(
                Placement.status == PlacementStatus.completed
            ).all()
            
            notifications = []
            for placement in placements:
                student = session.query(Student).filter(Student.id == placement.student_id).first()
                if student:
                    # Get cumulative total
                    cumulative = self.db.get_cumulative_total(placement.id)
                    
                    notifications.append({
                        'type': 'placement_completed',
                        'severity': 'success',
                        'timestamp': placement.created_at,
                        'title': 'Placement Completed',
                        'message': f"{student.first_name} {student.last_name} completed The Grotto. Final cumulative total: {cumulative} points",
                        'student_id': student.id,
                        'student_name': f"{student.first_name} {student.last_name}",
                        'homeroom_teacher': placement.homeroom_teacher_id or student.homeroom_teacher,
                        'cumulative_points': cumulative
                    })
            
            return notifications
        except Exception as e:
            print(f"Error fetching completion notifications: {e}")
            return []
        finally:
            session.close()
    
    def get_daily_log_finalization_notifications(self, target_date: date = None) -> List[Dict[str, Any]]:
        """Get notifications for finalized daily logs."""
        if target_date is None:
            target_date = date.today()
        
        session = self.db.get_session()
        try:
            from db_manager import DailyLog, Placement, Student
            
            logs = session.query(DailyLog).filter(
                DailyLog.date == target_date,
                DailyLog.finalized_by.isnot(None)
            ).all()
            
            notifications = []
            for log in logs:
                placement = session.query(Placement).filter(Placement.id == log.placement_id).first()
                if placement:
                    student = session.query(Student).filter(Student.id == placement.student_id).first()
                    if student:
                        notifications.append({
                            'type': 'daily_log_finalized',
                            'severity': 'info',
                            'timestamp': log.finalized_at,
                            'title': 'Daily Log Finalized',
                            'message': f"Daily summary for {student.first_name} {student.last_name}: total {log.daily_total}, readiness {log.readiness}",
                            'student_id': student.id,
                            'student_name': f"{student.first_name} {student.last_name}",
                            'homeroom_teacher': placement.homeroom_teacher_id or student.homeroom_teacher,
                            'daily_total': log.daily_total,
                            'readiness': log.readiness
                        })
            
            return notifications
        except Exception as e:
            print(f"Error fetching daily log notifications: {e}")
            return []
        finally:
            session.close()
    
    def get_pending_daily_logs(self) -> List[Dict[str, Any]]:
        """Get notifications for daily logs that need finalization."""
        session = self.db.get_session()
        try:
            from db_manager import DailyLog, Placement, Student
            
            # Get logs from yesterday that haven't been finalized
            yesterday = date.today() - timedelta(days=1)
            
            logs = session.query(DailyLog).filter(
                DailyLog.date == yesterday,
                DailyLog.finalized_by.is_(None)
            ).all()
            
            notifications = []
            for log in logs:
                placement = session.query(Placement).filter(Placement.id == log.placement_id).first()
                if placement:
                    student = session.query(Student).filter(Student.id == placement.student_id).first()
                    if student:
                        notifications.append({
                            'type': 'daily_log_pending',
                            'severity': 'warning',
                            'timestamp': datetime.now(),
                            'title': 'Daily Log Pending',
                            'message': f"Yesterday's daily log for {student.first_name} {student.last_name} needs finalization",
                            'student_id': student.id,
                            'student_name': f"{student.first_name} {student.last_name}",
                            'log_date': yesterday.isoformat()
                        })
            
            return notifications
        except Exception as e:
            print(f"Error fetching pending daily logs: {e}")
            return []
        finally:
            session.close()
    
    def get_overdue_assignments(self) -> List[Dict[str, Any]]:
        """Get notifications for overdue assignments."""
        session = self.db.get_session()
        try:
            from db_manager import Assignment, Student, AssignmentStatus
            
            today = date.today()
            
            assignments = session.query(Assignment).filter(
                Assignment.due_date < today,
                Assignment.status != AssignmentStatus.completed
            ).all()
            
            notifications = []
            for assignment in assignments:
                student = session.query(Student).filter(Student.id == assignment.student_id).first()
                if student:
                    days_overdue = (today - assignment.due_date).days
                    notifications.append({
                        'type': 'assignment_overdue',
                        'severity': 'warning',
                        'timestamp': datetime.now(),
                        'title': 'Assignment Overdue',
                        'message': f"{student.first_name} {student.last_name} has an overdue assignment: {assignment.title} (Due: {assignment.due_date.strftime('%m/%d/%Y')}, {days_overdue} days overdue)",
                        'student_id': student.id,
                        'student_name': f"{student.first_name} {student.last_name}",
                        'assignment_title': assignment.title,
                        'days_overdue': days_overdue
                    })
            
            return notifications
        except Exception as e:
            print(f"Error fetching overdue assignments: {e}")
            return []
        finally:
            session.close()
    
    def get_placement_ending_soon(self, days_threshold: int = 2) -> List[Dict[str, Any]]:
        """Get notifications for placements ending soon."""
        try:
            active_placements = self.db.get_active_placements_with_students()
            
            notifications = []
            today = date.today()
            
            for placement in active_placements:
                student = placement['student']
                start_date = datetime.fromisoformat(placement['startDate']).date() if isinstance(placement['startDate'], str) else placement['startDate']
                end_date = start_date + timedelta(days=placement['daysAssigned'])
                days_remaining = (end_date - today).days
                
                if 0 <= days_remaining <= days_threshold:
                    notifications.append({
                        'type': 'placement_ending_soon',
                        'severity': 'info',
                        'timestamp': datetime.now(),
                        'title': 'Placement Ending Soon',
                        'message': f"{student['firstName']} {student['lastName']}'s placement ends in {days_remaining} day(s)",
                        'student_id': student['_id'],
                        'student_name': f"{student['firstName']} {student['lastName']}",
                        'days_remaining': days_remaining
                    })
            
            return notifications
        except Exception as e:
            print(f"Error fetching placements ending soon: {e}")
            return []
    
    def get_all_notifications(self) -> List[Dict[str, Any]]:
        """Get all notifications sorted by timestamp."""
        all_notifications = []
        
        # Gather all notification types
        all_notifications.extend(self.get_recent_placement_notifications(days=7))
        all_notifications.extend(self.get_placement_completion_notifications(days=7))
        all_notifications.extend(self.get_daily_log_finalization_notifications())
        all_notifications.extend(self.get_pending_daily_logs())
        all_notifications.extend(self.get_overdue_assignments())
        all_notifications.extend(self.get_placement_ending_soon(days_threshold=2))
        
        # Sort by timestamp (most recent first)
        all_notifications.sort(key=lambda x: x.get('timestamp', datetime.min), reverse=True)
        
        return all_notifications
    
    def get_notifications_by_severity(self, severity: str = None) -> Dict[str, List[Dict[str, Any]]]:
        """Get notifications grouped by severity."""
        all_notifications = self.get_all_notifications()
        
        if severity:
            return [n for n in all_notifications if n.get('severity') == severity]
        
        grouped = {
            'warning': [],
            'info': [],
            'success': []
        }
        
        for notification in all_notifications:
            sev = notification.get('severity', 'info')
            if sev in grouped:
                grouped[sev].append(notification)
        
        return grouped
