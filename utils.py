from datetime import datetime, date, timedelta
from typing import Any

def format_date(date_obj: date) -> str:
    """Format a date object for display."""
    if isinstance(date_obj, str):
        try:
            date_obj = datetime.fromisoformat(date_obj).date()
        except (ValueError, TypeError):
            return date_obj
    
    if isinstance(date_obj, date):
        return date_obj.strftime("%B %d, %Y")
    
    return str(date_obj)

def calculate_days_remaining(start_date: str, days_assigned: int, days_completed: int = 0) -> int:
    """Calculate how many days remain in a placement, accounting for completed days through daily fulfillment."""
    try:
        start = datetime.fromisoformat(start_date).date()
        # Subtract days_completed from days_assigned to get effective days
        effective_days = max(0, days_assigned - days_completed)
        end_date = start + timedelta(days=effective_days)
        today = date.today()
        
        if today > end_date:
            return 0
        
        remaining = (end_date - today).days
        return max(0, remaining)
    except (ValueError, TypeError):
        return 0

def get_status_color(status: str) -> str:
    """Get color for status display."""
    status_colors = {
        'active': 'green',
        'completed': 'blue',
        'assigned': 'orange',
        'in_progress': 'yellow',
        'deleted': 'red'
    }
    return status_colors.get(status, 'gray')

def format_datetime(datetime_str: str) -> str:
    """Format a datetime string for display."""
    try:
        dt = datetime.fromisoformat(datetime_str)
        return dt.strftime("%B %d, %Y at %I:%M %p")
    except (ValueError, TypeError):
        return datetime_str

def validate_email(email: str) -> bool:
    """Basic email validation."""
    import re
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(pattern, email) is not None

def validate_phone(phone: str) -> bool:
    """Basic phone number validation."""
    import re
    # Remove common separators
    clean_phone = re.sub(r'[^\d]', '', phone)
    # Check if it's a reasonable length (7-15 digits)
    return 7 <= len(clean_phone) <= 15

def get_grade_order(grade: str) -> int:
    """Get numeric order for grade sorting."""
    grade_order = {
        'K': 0, '1': 1, '2': 2, '3': 3, '4': 4, '5': 5,
        '6': 6, '7': 7, '8': 8, '9': 9, '10': 10, '11': 11, '12': 12
    }
    return grade_order.get(grade, 99)

def calculate_placement_progress(start_date: str, days_assigned: int) -> float:
    """Calculate placement progress as a percentage."""
    try:
        start = datetime.fromisoformat(start_date).date()
        today = date.today()
        days_elapsed = (today - start).days
        
        if days_elapsed < 0:
            return 0.0
        elif days_elapsed >= days_assigned:
            return 100.0
        else:
            return (days_elapsed / days_assigned) * 100
    except (ValueError, TypeError):
        return 0.0

def is_weekend(date_obj: date) -> bool:
    """Check if a date falls on a weekend."""
    if isinstance(date_obj, str):
        try:
            date_obj = datetime.fromisoformat(date_obj).date()
        except (ValueError, TypeError):
            return False
    
    return date_obj.weekday() >= 5  # Saturday = 5, Sunday = 6

def get_business_days_between(start_date: str, end_date: str) -> int:
    """Calculate business days between two dates."""
    try:
        start = datetime.fromisoformat(start_date).date()
        end = datetime.fromisoformat(end_date).date()
        
        business_days = 0
        current_date = start
        
        while current_date <= end:
            if not is_weekend(current_date):
                business_days += 1
            current_date += timedelta(days=1)
        
        return business_days
    except (ValueError, TypeError):
        return 0
