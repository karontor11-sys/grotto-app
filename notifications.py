from datetime import datetime, date, timedelta
from typing import List, Dict, Any
import hashlib
from utils import central_today, central_now_naive

class NotificationManager:
    """Manager for generating and displaying notifications."""
    
    def __init__(self, db_manager):
        self.db = db_manager
    
    def _generate_notification_id(self, notification_type: str, record_id: str, date_str: str = None) -> str:
        """Generate a unique, consistent notification ID.
        
        Args:
            notification_type: The type of notification (e.g., 'placement_created')
            record_id: The primary record ID (e.g., placement_id, student_id)
            date_str: Optional date string for date-specific notifications
            
        Returns:
            A unique notification ID string
        """
        components = [notification_type, str(record_id)]
        if date_str:
            components.append(date_str)
        return ":".join(components)
    
    def get_recent_placement_notifications(self, days: int = 7) -> List[Dict[str, Any]]:
        """Get notifications for recently created placements."""
        session = self.db.get_session()
        try:
            from db_manager import Placement, Student
            
            cutoff_date = central_now_naive() - timedelta(days=days)
            
            placements = session.query(Placement).filter(
                Placement.created_at >= cutoff_date
            ).order_by(Placement.created_at.desc()).all()
            
            notifications = []
            for placement in placements:
                student = session.query(Student).filter(Student.id == placement.student_id).first()
                if student:
                    notif_id = self._generate_notification_id('placement_created', placement.id)
                    notifications.append({
                        'notification_id': notif_id,
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
            
            cutoff_date = central_now_naive() - timedelta(days=days)
            
            placements = session.query(Placement).filter(
                Placement.status == PlacementStatus.completed
            ).all()
            
            notifications = []
            for placement in placements:
                student = session.query(Student).filter(Student.id == placement.student_id).first()
                if student:
                    cumulative = self.db.get_cumulative_total(placement.id)
                    notif_id = self._generate_notification_id('placement_completed', placement.id)
                    notifications.append({
                        'notification_id': notif_id,
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
            target_date = central_today()
        
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
                        notif_id = self._generate_notification_id('daily_log_finalized', log.id, log.date.isoformat() if log.date else None)
                        notifications.append({
                            'notification_id': notif_id,
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
            yesterday = central_today() - timedelta(days=1)
            
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
                        notif_id = self._generate_notification_id('daily_log_pending', log.id, yesterday.isoformat())
                        notifications.append({
                            'notification_id': notif_id,
                            'type': 'daily_log_pending',
                            'severity': 'warning',
                            'timestamp': central_now_naive(),
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
            
            today = central_today()
            
            assignments = session.query(Assignment).filter(
                Assignment.due_date < today,
                Assignment.status != AssignmentStatus.completed
            ).all()
            
            notifications = []
            for assignment in assignments:
                student = session.query(Student).filter(Student.id == assignment.student_id).first()
                if student:
                    days_overdue = (today - assignment.due_date).days
                    notif_id = self._generate_notification_id('assignment_overdue', assignment.id)
                    notifications.append({
                        'notification_id': notif_id,
                        'type': 'assignment_overdue',
                        'severity': 'warning',
                        'timestamp': central_now_naive(),
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
            today = central_today()
            
            for placement in active_placements:
                student = placement['student']
                start_date = datetime.fromisoformat(placement['startDate']).date() if isinstance(placement['startDate'], str) else placement['startDate']
                end_date = start_date + timedelta(days=placement['daysAssigned'])
                days_remaining = (end_date - today).days
                
                if 0 <= days_remaining <= days_threshold:
                    notif_id = self._generate_notification_id('placement_ending_soon', placement['_id'])
                    notifications.append({
                        'notification_id': notif_id,
                        'type': 'placement_ending_soon',
                        'severity': 'info',
                        'timestamp': central_now_naive(),
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
    
    def get_end_of_day_incomplete_notifications(self, days_back: int = 7) -> List[Dict[str, Any]]:
        """Get notifications for records marked as incomplete during end-of-day processing.
        
        Args:
            days_back: Number of days to look back for incomplete records
            
        Returns:
            List of notifications for incomplete records
        """
        notifications = []
        today = central_today()
        
        for i in range(1, days_back + 1):
            check_date = today - timedelta(days=i)
            
            incomplete_records = self.db.get_eod_incomplete_records(check_date)
            
            if incomplete_records:
                student_names = [rec['student_name'] for rec in incomplete_records]
                notif_id = self._generate_notification_id('end_of_day_incomplete', 'eod', check_date.isoformat())
                notifications.append({
                    'notification_id': notif_id,
                    'type': 'end_of_day_incomplete',
                    'severity': 'warning',
                    'timestamp': datetime.combine(check_date, datetime.min.time()),
                    'title': f'Incomplete Records - {check_date.strftime("%m/%d/%Y")}',
                    'message': f"{len(incomplete_records)} student(s) did not complete their placement requirements: {', '.join(student_names)}",
                    'date': check_date.isoformat(),
                    'incomplete_count': len(incomplete_records),
                    'recipients': ['Aaron Toronto', 'Matthew Christie']
                })
        
        return notifications
    
    def get_placement_no_show_notifications(self, days_back: int = 7) -> List[Dict[str, Any]]:
        """Get unified no-show notifications for all placement types.
        
        Detects no-shows for ISS, Lunch Detention, Class Period Referral (and subtypes)
        by checking scheduled placement days against attendance records.
        
        Args:
            days_back: Number of days to look back for no-show events
            
        Returns:
            List of Placement No-Show notifications for all placement types
        """
        session = self.db.get_session()
        notifications = []
        
        try:
            from db_manager import (
                Placement, Student, DailyLog, PartialDaySession,
                PlacementCategory, PlacementStatus, SessionStatus
            )
            from sqlalchemy import or_
            
            today = central_today()
            cutoff_date = today - timedelta(days=days_back)
            
            # Helper to get readable placement type name
            def get_placement_type_display(placement):
                if placement.placement_type == PlacementCategory.ISS:
                    return "ISS"
                elif placement.placement_type == PlacementCategory.LUNCH_DETENTION:
                    return "Lunch Detention"
                elif placement.placement_type == PlacementCategory.CLASS_REFERRAL:
                    subtype = placement.referral_subtype or 'behavior'
                    if subtype == 'pre_planned':
                        return "Pre-Planned Referral"
                    elif subtype == 'cool_down':
                        return "Cool-Down Referral"
                    else:
                        return "Behavior Referral"
                elif placement.placement_type == PlacementCategory.COOL_DOWN:
                    return "Cool-Down"
                elif placement.placement_type == PlacementCategory.PRE_PLANNED_REFERRAL:
                    return "Pre-Planned Referral"
                else:
                    return "Placement"
            
            # Track already-notified combinations to avoid duplicates
            notified_keys = set()
            
            # 1. Check DailyLogs with explicit no_show flag or absent/not checked in on scheduled dates
            no_show_logs = session.query(DailyLog).filter(
                DailyLog.date >= cutoff_date,
                DailyLog.date < today,
                or_(
                    DailyLog.no_show == True,
                    DailyLog.day_type == 'absent'
                )
            ).all()
            
            for log in no_show_logs:
                placement = session.query(Placement).filter(Placement.id == log.placement_id).first()
                if not placement:
                    continue
                    
                # Skip completed placements
                if placement.status == PlacementStatus.completed:
                    continue
                    
                student = session.query(Student).filter(Student.id == placement.student_id).first()
                if not student:
                    continue
                
                # Create unique key to avoid duplicates
                key = (placement.id, log.date.isoformat())
                if key in notified_keys:
                    continue
                notified_keys.add(key)
                
                student_name = f"{student.first_name} {student.last_name}"
                placement_type = get_placement_type_display(placement)
                date_str = log.date.strftime('%m/%d/%Y')
                notif_id = self._generate_notification_id('placement_no_show', placement.id, log.date.isoformat())
                notifications.append({
                    'notification_id': notif_id,
                    'type': 'placement_no_show',
                    'severity': 'warning',
                    'timestamp': datetime.combine(log.date, datetime.min.time()),
                    'title': f"No-Show: {student_name} – {placement_type}",
                    'message': f"{student_name} did not attend their scheduled {placement_type} on {date_str}.",
                    'student_id': student.id,
                    'student_name': student_name,
                    'placement_id': placement.id,
                    'placement_type': placement_type,
                    'date': log.date.isoformat()
                })
            
            # 2. Check PartialDaySessions with no_show status
            no_show_sessions = session.query(PartialDaySession).filter(
                PartialDaySession.date >= cutoff_date,
                PartialDaySession.date < today,
                PartialDaySession.status == SessionStatus.no_show
            ).all()
            
            for sess in no_show_sessions:
                placement = session.query(Placement).filter(Placement.id == sess.placement_id).first()
                if not placement:
                    continue
                    
                # Skip completed placements
                if placement.status == PlacementStatus.completed:
                    continue
                    
                student = session.query(Student).filter(Student.id == placement.student_id).first()
                if not student:
                    continue
                
                # Create unique key to avoid duplicates
                key = (placement.id, sess.date.isoformat())
                if key in notified_keys:
                    continue
                notified_keys.add(key)
                
                student_name = f"{student.first_name} {student.last_name}"
                placement_type = get_placement_type_display(placement)
                date_str = sess.date.strftime('%m/%d/%Y')
                notif_id = self._generate_notification_id('placement_no_show', placement.id, sess.date.isoformat())
                notifications.append({
                    'notification_id': notif_id,
                    'type': 'placement_no_show',
                    'severity': 'warning',
                    'timestamp': sess.alert_timestamp or datetime.combine(sess.date, datetime.min.time()),
                    'title': f"No-Show: {student_name} – {placement_type}",
                    'message': f"{student_name} did not attend their scheduled {placement_type} on {date_str}.",
                    'student_id': student.id,
                    'student_name': student_name,
                    'placement_id': placement.id,
                    'placement_type': placement_type,
                    'session_id': sess.id,
                    'date': sess.date.isoformat()
                })
            
            # 3. Check ISS scheduled dates not served (for ISS placements with scheduled_iss_dates)
            iss_placements = session.query(Placement).filter(
                Placement.placement_type == PlacementCategory.ISS,
                Placement.status != PlacementStatus.completed
            ).all()
            
            for placement in iss_placements:
                scheduled_dates = placement.scheduled_iss_dates or []
                served_dates = placement.served_dates or []
                
                student = session.query(Student).filter(Student.id == placement.student_id).first()
                if not student:
                    continue
                
                student_name = f"{student.first_name} {student.last_name}"
                placement_type = "ISS"
                
                for date_str in scheduled_dates:
                    try:
                        check_date = datetime.fromisoformat(date_str).date()
                    except:
                        continue
                    
                    # Only check past dates within the window
                    if check_date >= today or check_date < cutoff_date:
                        continue
                    
                    # Skip if already served
                    if date_str in served_dates:
                        continue
                    
                    # Check if there's a daily log with check-in or valid attendance
                    log = session.query(DailyLog).filter(
                        DailyLog.placement_id == placement.id,
                        DailyLog.date == check_date
                    ).first()
                    
                    # If checked in, not a no-show
                    if log and log.checked_in:
                        continue
                    
                    # Create unique key
                    key = (placement.id, date_str)
                    if key in notified_keys:
                        continue
                    notified_keys.add(key)
                    
                    display_date = check_date.strftime('%m/%d/%Y')
                    notif_id = self._generate_notification_id('placement_no_show', placement.id, date_str)
                    notifications.append({
                        'notification_id': notif_id,
                        'type': 'placement_no_show',
                        'severity': 'warning',
                        'timestamp': datetime.combine(check_date, datetime.min.time()),
                        'title': f"No-Show: {student_name} – {placement_type}",
                        'message': f"{student_name} did not attend their scheduled {placement_type} on {display_date}.",
                        'student_id': student.id,
                        'student_name': student_name,
                        'placement_id': placement.id,
                        'placement_type': placement_type,
                        'date': date_str
                    })
            
            # 4. Check Lunch Detention scheduled dates not served
            lunch_placements = session.query(Placement).filter(
                Placement.placement_type == PlacementCategory.LUNCH_DETENTION,
                Placement.status != PlacementStatus.completed
            ).all()
            
            for placement in lunch_placements:
                scheduled_dates = placement.scheduled_lunch_dates or []
                served_dates = placement.served_dates or []
                
                student = session.query(Student).filter(Student.id == placement.student_id).first()
                if not student:
                    continue
                
                student_name = f"{student.first_name} {student.last_name}"
                placement_type = "Lunch Detention"
                
                for date_str in scheduled_dates:
                    try:
                        check_date = datetime.fromisoformat(date_str).date()
                    except:
                        continue
                    
                    # Only check past dates within the window
                    if check_date >= today or check_date < cutoff_date:
                        continue
                    
                    # Skip if already served
                    if date_str in served_dates:
                        continue
                    
                    # Create unique key
                    key = (placement.id, date_str)
                    if key in notified_keys:
                        continue
                    notified_keys.add(key)
                    
                    display_date = check_date.strftime('%m/%d/%Y')
                    notif_id = self._generate_notification_id('placement_no_show', placement.id, date_str)
                    notifications.append({
                        'notification_id': notif_id,
                        'type': 'placement_no_show',
                        'severity': 'warning',
                        'timestamp': datetime.combine(check_date, datetime.min.time()),
                        'title': f"No-Show: {student_name} – {placement_type}",
                        'message': f"{student_name} did not attend their scheduled {placement_type} on {display_date}.",
                        'student_id': student.id,
                        'student_name': student_name,
                        'placement_id': placement.id,
                        'placement_type': placement_type,
                        'date': date_str
                    })
            
            return notifications
        except Exception as e:
            print(f"Error fetching placement no-show notifications: {e}")
            return []
        finally:
            session.close()
    
    def _get_all_raw_notifications(self) -> List[Dict[str, Any]]:
        """Get all notifications without filtering dismissed ones."""
        all_notifications = []
        
        all_notifications.extend(self.get_recent_placement_notifications(days=7))
        all_notifications.extend(self.get_placement_completion_notifications(days=7))
        all_notifications.extend(self.get_daily_log_finalization_notifications())
        all_notifications.extend(self.get_pending_daily_logs())
        all_notifications.extend(self.get_overdue_assignments())
        all_notifications.extend(self.get_placement_ending_soon(days_threshold=2))
        all_notifications.extend(self.get_end_of_day_incomplete_notifications(days_back=7))
        all_notifications.extend(self.get_placement_no_show_notifications(days_back=7))
        
        # Sort by timestamp (most recent first)
        all_notifications.sort(key=lambda x: x.get('timestamp', datetime.min), reverse=True)
        
        return all_notifications
    
    def get_all_notifications(self, include_dismissed: bool = False) -> List[Dict[str, Any]]:
        """Get all active notifications sorted by timestamp (excludes dismissed by default).
        
        Args:
            include_dismissed: If True, returns all notifications including dismissed ones
            
        Returns:
            List of active notification dictionaries
        """
        all_notifications = self._get_all_raw_notifications()
        
        if include_dismissed:
            return all_notifications
        
        # Filter out dismissed notifications
        dismissed_ids = self.db.get_dismissed_notification_ids()
        return [n for n in all_notifications if n.get('notification_id') not in dismissed_ids]
    
    def get_notifications_by_severity(self, severity: str = None) -> Dict[str, List[Dict[str, Any]]]:
        """Get active notifications grouped by severity (excludes dismissed)."""
        all_notifications = self.get_all_notifications(include_dismissed=False)
        
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
    
    def get_dismissed_notifications(self) -> List[Dict[str, Any]]:
        """Get all dismissed notifications from the database.
        
        Returns:
            List of dismissed notification dictionaries with dismissed_at timestamps
        """
        return self.db.get_dismissed_notifications()
    
    def dismiss_notification(self, notification_id: str, notification_data: Dict[str, Any]) -> bool:
        """Dismiss a notification.
        
        Args:
            notification_id: The unique notification identifier
            notification_data: The notification data to store for historical display
            
        Returns:
            True if successfully dismissed, False otherwise
        """
        return self.db.dismiss_notification(notification_id, notification_data)
    
    def restore_notification(self, notification_id: str) -> bool:
        """Restore a dismissed notification back to active state.
        
        Args:
            notification_id: The unique notification identifier
            
        Returns:
            True if successfully restored, False otherwise
        """
        return self.db.restore_notification(notification_id)
