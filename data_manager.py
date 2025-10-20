import uuid
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional, Any

class DataManager:
    def __init__(self):
        """Initialize the data manager with empty collections."""
        self.data = {
            'Students': {},
            'Placements': {},
            'DailyLogs': {},
            'PointEvents': {},
            'Assignments': {},
            'Notes': {}
        }
    
    def generate_id(self) -> str:
        """Generate a unique identifier."""
        return str(uuid.uuid4())
    
    # Student operations
    def add_student(self, student_data: Dict[str, Any]) -> str:
        """Add a new student."""
        student_id = self.generate_id()
        student_data['_id'] = student_id
        self.data['Students'][student_id] = student_data
        return student_id
    
    def get_all_students(self) -> List[Dict[str, Any]]:
        """Get all active students."""
        return [s for s in self.data['Students'].values() if s.get('status', 'active') == 'active']
    
    def get_student(self, student_id: str) -> Optional[Dict[str, Any]]:
        """Get a specific student by ID."""
        return self.data['Students'].get(student_id)
    
    def update_student(self, student_id: str, updated_data: Dict[str, Any]) -> bool:
        """Update a student's information."""
        if student_id in self.data['Students']:
            self.data['Students'][student_id].update(updated_data)
            return True
        return False
    
    def delete_student(self, student_id: str) -> bool:
        """Soft delete a student."""
        if student_id in self.data['Students']:
            self.data['Students'][student_id]['status'] = 'deleted'
            return True
        return False
    
    # Placement operations
    def add_placement(self, placement_data: Dict[str, Any]) -> str:
        """Add a new placement."""
        placement_id = self.generate_id()
        placement_data['_id'] = placement_id
        self.data['Placements'][placement_id] = placement_data
        return placement_id
    
    def get_active_placements(self) -> List[Dict[str, Any]]:
        """Get all active placements."""
        return [p for p in self.data['Placements'].values() if p.get('status') == 'active']
    
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
            start_date = datetime.fromisoformat(placement['startDate']).date()
            end_date = start_date + timedelta(days=placement['daysAssigned'])
            
            if start_date <= target_date <= end_date:
                result.append(placement)
        
        return result
    
    def complete_placement(self, placement_id: str) -> bool:
        """Complete a placement."""
        if placement_id in self.data['Placements']:
            self.data['Placements'][placement_id]['status'] = 'completed'
            return True
        return False
    
    # Daily Log operations
    def get_or_create_daily_log(self, placement_id: str, log_date: str) -> Dict[str, Any]:
        """Get or create a daily log for a placement on a specific date."""
        # Check if log already exists
        for log in self.data['DailyLogs'].values():
            if log['placementId'] == placement_id and log['date'] == log_date:
                return log
        
        # Create new daily log
        log_id = self.generate_id()
        daily_log = {
            '_id': log_id,
            'placementId': placement_id,
            'date': log_date,
            'positiveTotal': 0,
            'negativeTotal': 0,
            'dailyTotal': 0,
            'readiness': 'continue'
        }
        
        self.data['DailyLogs'][log_id] = daily_log
        return daily_log
    
    def finalize_daily_log(self, log_id: str, readiness: str, finalized_by: str) -> bool:
        """Finalize a daily log."""
        if log_id in self.data['DailyLogs']:
            self.data['DailyLogs'][log_id].update({
                'readiness': readiness,
                'finalizedBy': finalized_by,
                'finalizedAt': datetime.now().isoformat()
            })
            return True
        return False
    
    def update_daily_log_totals(self, placement_id: str, log_date: str):
        """Update daily log totals based on point events."""
        daily_log = self.get_or_create_daily_log(placement_id, log_date)
        
        # Calculate totals from point events
        positive_total = 0
        negative_total = 0
        
        for event in self.data['PointEvents'].values():
            if event['placementId'] == placement_id and event['date'] == log_date:
                if event['type'] == 'positive':
                    positive_total += event['value']
                else:
                    negative_total += event['value']
        
        # Update daily log
        self.data['DailyLogs'][daily_log['_id']].update({
            'positiveTotal': positive_total,
            'negativeTotal': negative_total,
            'dailyTotal': positive_total + negative_total
        })
    
    # Point Event operations
    def add_point_event(self, event_data: Dict[str, Any]) -> str:
        """Add a point event."""
        event_id = self.generate_id()
        event_data['_id'] = event_id
        self.data['PointEvents'][event_id] = event_data
        
        # Update daily log totals
        self.update_daily_log_totals(event_data['placementId'], event_data['date'])
        
        return event_id
    
    def get_point_events_for_date(self, placement_id: str, event_date: str) -> List[Dict[str, Any]]:
        """Get all point events for a placement on a specific date."""
        return [
            event for event in self.data['PointEvents'].values()
            if event['placementId'] == placement_id and event['date'] == event_date
        ]
    
    def get_all_point_events_for_placement(self, placement_id: str) -> List[Dict[str, Any]]:
        """Get all point events for a placement."""
        events = [
            event for event in self.data['PointEvents'].values()
            if event['placementId'] == placement_id
        ]
        # Sort by date and creation time
        return sorted(events, key=lambda x: (x['date'], x.get('createdAt', '')), reverse=True)
    
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
        assignment_id = self.generate_id()
        assignment_data['_id'] = assignment_id
        self.data['Assignments'][assignment_id] = assignment_data
        return assignment_id
    
    def get_all_assignments_with_students(self) -> List[Dict[str, Any]]:
        """Get all assignments with student information."""
        result = []
        
        for assignment in self.data['Assignments'].values():
            student = self.get_student(assignment['studentId'])
            if student:
                assignment_with_student = assignment.copy()
                assignment_with_student['student'] = student
                result.append(assignment_with_student)
        
        return result
    
    def update_assignment_status(self, assignment_id: str, new_status: str) -> bool:
        """Update an assignment's status."""
        if assignment_id in self.data['Assignments']:
            self.data['Assignments'][assignment_id]['status'] = new_status
            return True
        return False
    
    # Notes operations
    def add_note(self, note_data: Dict[str, Any]) -> str:
        """Add a new note."""
        note_id = self.generate_id()
        note_data['_id'] = note_id
        self.data['Notes'][note_id] = note_data
        return note_id
    
    def get_all_notes_with_students(self) -> List[Dict[str, Any]]:
        """Get all notes with student information."""
        result = []
        
        for note in self.data['Notes'].values():
            student = self.get_student(note['studentId'])
            if student:
                note_with_student = note.copy()
                note_with_student['student'] = student
                result.append(note_with_student)
        
        # Sort by creation date (most recent first)
        return sorted(result, key=lambda x: x.get('createdAt', ''), reverse=True)
