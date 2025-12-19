from datetime import datetime, date, timedelta
from typing import Dict, List, Any
import pandas as pd
from utils import central_today

class AnalyticsEngine:
    """Analytics engine for generating reports and insights."""
    
    def __init__(self, db_manager):
        self.db = db_manager
    
    def get_placement_statistics(self) -> Dict[str, Any]:
        """Get overall placement statistics."""
        session = self.db.get_session()
        try:
            from db_manager import Placement, PlacementStatus
            
            all_placements = session.query(Placement).all()
            active_placements = [p for p in all_placements if p.status == PlacementStatus.active]
            completed_placements = [p for p in all_placements if p.status == PlacementStatus.completed]
            
            # Calculate average days assigned
            total_days = sum(p.days_assigned for p in all_placements) if all_placements else 0
            avg_days = total_days / len(all_placements) if all_placements else 0
            
            # Calculate completion rate
            completion_rate = (len(completed_placements) / len(all_placements) * 100) if all_placements else 0
            
            return {
                'total_placements': len(all_placements),
                'active_placements': len(active_placements),
                'completed_placements': len(completed_placements),
                'average_days_assigned': round(avg_days, 1),
                'completion_rate': round(completion_rate, 1)
            }
        finally:
            session.close()
    
    def get_student_statistics(self) -> Dict[str, Any]:
        """Get student enrollment statistics."""
        session = self.db.get_session()
        try:
            from db_manager import Student, StudentStatus
            
            all_students = session.query(Student).all()
            active_students = [s for s in all_students if s.status == StudentStatus.active]
            
            # Grade distribution
            grade_counts = {}
            for student in active_students:
                grade = student.grade
                grade_counts[grade] = grade_counts.get(grade, 0) + 1
            
            return {
                'total_students': len(all_students),
                'active_students': len(active_students),
                'grade_distribution': grade_counts
            }
        finally:
            session.close()
    
    def get_point_trends(self, days: int = 30) -> Dict[str, Any]:
        """Get point trends over the last N days."""
        session = self.db.get_session()
        try:
            from db_manager import PointEvent, PointEventType
            
            start_date = central_today() - timedelta(days=days)
            
            events = session.query(PointEvent).filter(
                PointEvent.date >= start_date
            ).all()
            
            # Daily breakdown
            daily_totals = {}
            positive_by_day = {}
            negative_by_day = {}
            
            for event in events:
                day_str = event.date.isoformat()
                
                if day_str not in daily_totals:
                    daily_totals[day_str] = 0
                    positive_by_day[day_str] = 0
                    negative_by_day[day_str] = 0
                
                daily_totals[day_str] += event.value
                
                if event.type == PointEventType.positive:
                    positive_by_day[day_str] += event.value
                else:
                    negative_by_day[day_str] += event.value
            
            # Code frequency
            code_frequency = {}
            for event in events:
                code_frequency[event.code] = code_frequency.get(event.code, 0) + 1
            
            return {
                'daily_totals': daily_totals,
                'positive_by_day': positive_by_day,
                'negative_by_day': negative_by_day,
                'code_frequency': code_frequency,
                'total_events': len(events)
            }
        finally:
            session.close()
    
    def get_behavior_patterns(self) -> Dict[str, Any]:
        """Analyze behavior patterns across all placements."""
        session = self.db.get_session()
        try:
            from db_manager import PointEvent
            
            events = session.query(PointEvent).all()
            
            # Most common positive behaviors
            positive_codes = {}
            negative_codes = {}
            
            for event in events:
                if event.type.value == 'positive':
                    positive_codes[event.code] = positive_codes.get(event.code, 0) + 1
                else:
                    negative_codes[event.code] = negative_codes.get(event.code, 0) + 1
            
            # Sort by frequency
            top_positive = sorted(positive_codes.items(), key=lambda x: x[1], reverse=True)[:5]
            top_negative = sorted(negative_codes.items(), key=lambda x: x[1], reverse=True)[:5]
            
            return {
                'top_positive_behaviors': top_positive,
                'top_negative_behaviors': top_negative,
                'total_positive_events': sum(positive_codes.values()),
                'total_negative_events': sum(negative_codes.values())
            }
        finally:
            session.close()
    
    def get_student_performance_summary(self) -> List[Dict[str, Any]]:
        """Get performance summary for all students with active placements."""
        active_placements = self.db.get_active_placements_with_students()
        
        summary = []
        for placement in active_placements:
            student = placement['student']
            
            # Get cumulative points
            cumulative = self.db.get_cumulative_total(placement['_id'])
            
            # Get all events for this placement
            events = self.db.get_all_point_events_for_placement(placement['_id'])
            
            # Calculate averages
            total_days_with_events = len(set(e['date'] for e in events)) if events else 1
            avg_daily_points = cumulative / total_days_with_events if total_days_with_events > 0 else 0
            
            # Count positive vs negative events
            positive_count = len([e for e in events if e['type'] == 'positive'])
            negative_count = len([e for e in events if e['type'] == 'negative'])
            
            summary.append({
                'student_name': f"{student['firstName']} {student['lastName']}",
                'grade': student['grade'],
                'homeroom_teacher': student['homeroomTeacher'],
                'placement_id': placement['_id'],
                'days_assigned': placement['daysAssigned'],
                'cumulative_points': cumulative,
                'avg_daily_points': round(avg_daily_points, 1),
                'positive_events': positive_count,
                'negative_events': negative_count,
                'total_events': len(events)
            })
        
        # Sort by cumulative points (descending)
        summary.sort(key=lambda x: x['cumulative_points'], reverse=True)
        
        return summary
    
    def get_assignment_statistics(self) -> Dict[str, Any]:
        """Get assignment completion statistics."""
        session = self.db.get_session()
        try:
            from db_manager import Assignment, AssignmentStatus
            
            assignments = session.query(Assignment).all()
            
            status_counts = {
                'assigned': 0,
                'in_progress': 0,
                'completed': 0
            }
            
            for assignment in assignments:
                status_counts[assignment.status.value] += 1
            
            completion_rate = (status_counts['completed'] / len(assignments) * 100) if assignments else 0
            
            # Overdue assignments (past due date and not completed)
            today = central_today()
            overdue = [a for a in assignments 
                      if a.due_date and a.due_date < today 
                      and a.status != AssignmentStatus.completed]
            
            return {
                'total_assignments': len(assignments),
                'assigned': status_counts['assigned'],
                'in_progress': status_counts['in_progress'],
                'completed': status_counts['completed'],
                'completion_rate': round(completion_rate, 1),
                'overdue': len(overdue)
            }
        finally:
            session.close()
    
    def get_daily_log_compliance(self) -> Dict[str, Any]:
        """Get daily log finalization compliance."""
        session = self.db.get_session()
        try:
            from db_manager import DailyLog
            
            # Get logs from last 30 days
            start_date = central_today() - timedelta(days=30)
            logs = session.query(DailyLog).filter(
                DailyLog.date >= start_date
            ).all()
            
            finalized_count = len([log for log in logs if log.finalized_by])
            total_logs = len(logs)
            
            compliance_rate = (finalized_count / total_logs * 100) if total_logs > 0 else 0
            
            # Readiness distribution
            readiness_counts = {'ready': 0, 'continue': 0}
            for log in logs:
                if log.finalized_by:
                    readiness_counts[log.readiness] = readiness_counts.get(log.readiness, 0) + 1
            
            return {
                'total_logs': total_logs,
                'finalized': finalized_count,
                'pending': total_logs - finalized_count,
                'compliance_rate': round(compliance_rate, 1),
                'readiness_counts': readiness_counts
            }
        finally:
            session.close()
    
    def get_placement_trends_by_month(self, months: int = 6) -> Dict[str, List]:
        """Get placement creation trends by month."""
        session = self.db.get_session()
        try:
            from db_manager import Placement
            
            placements = session.query(Placement).all()
            
            # Group by month
            monthly_data = {}
            
            for placement in placements:
                if placement.created_at:
                    month_key = placement.created_at.strftime('%Y-%m')
                    if month_key not in monthly_data:
                        monthly_data[month_key] = {'count': 0, 'total_days': 0}
                    
                    monthly_data[month_key]['count'] += 1
                    monthly_data[month_key]['total_days'] += placement.days_assigned
            
            # Calculate averages
            for month in monthly_data:
                count = monthly_data[month]['count']
                monthly_data[month]['avg_days'] = round(monthly_data[month]['total_days'] / count, 1) if count > 0 else 0
            
            return monthly_data
        finally:
            session.close()
