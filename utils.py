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

def get_placement_type_label(placement: dict) -> str:
    """Generate a descriptive label for placement type with date/period information.
    
    Returns labels like:
    - ISS – Multi-Day (Jan 15–Jan 19)
    - ISS – Single Day (Jan 15)
    - Lunch Detention – Multi-Day (Jan 15–Jan 19)
    - Lunch Detention – Single Day (Jan 15)
    - Class Period Referral – Periods 2–4 (Jan 15)
    - Cool-Down – Period 3 (Jan 15)
    
    Args:
        placement: Placement dictionary with all relevant fields
        
    Returns:
        Formatted placement type label string
    """
    # Normalize placement_type
    placement_type = placement.get('placementType') or placement.get('placement_type', '')
    if isinstance(placement_type, str):
        placement_type = placement_type.upper()
    
    # Get start date
    start_date_str = placement.get('startDate') or placement.get('start_date')
    if start_date_str:
        try:
            start_date = datetime.fromisoformat(start_date_str).date()
            start_formatted = start_date.strftime("%b %d")
        except (ValueError, TypeError):
            start_formatted = "N/A"
    else:
        start_formatted = "N/A"
    
    # Handle ISS and Lunch Detention
    if placement_type in ['ISS', 'LUNCH_DETENTION']:
        days_assigned = placement.get('daysAssigned') or placement.get('days_assigned', 0)
        
        # Determine type name
        if placement_type == 'ISS':
            type_name = "In-School Suspension (ISS)"
        else:
            type_name = "Lunch Detention"
        
        # Multi-day or single day
        if days_assigned > 1:
            # Calculate end date
            if start_date_str:
                try:
                    start_date = datetime.fromisoformat(start_date_str).date()
                    end_date = add_business_days(start_date, days_assigned)
                    end_formatted = end_date.strftime("%b %d")
                    return f"{type_name} – Multi-Day ({start_formatted}–{end_formatted})"
                except (ValueError, TypeError):
                    return f"{type_name} – Multi-Day"
            return f"{type_name} – Multi-Day"
        else:
            return f"{type_name} – Single Day ({start_formatted})"
    
    # Handle Class Referral and Cool-Down
    elif placement_type in ['CLASS_REFERRAL', 'COOL_DOWN']:
        start_period = placement.get('startPeriod') or placement.get('start_period')
        end_period = placement.get('endPeriod') or placement.get('end_period')
        
        # Determine type name
        if placement_type == 'CLASS_REFERRAL':
            type_name = "Class Period Referral"
        else:
            type_name = "Cool-Down Referral"
        
        # Generate period label
        if start_period is not None and end_period is not None:
            if start_period == end_period:
                period_label = f"Period {start_period}"
            else:
                period_label = f"Periods {start_period}–{end_period}"
            
            return f"{type_name} – {period_label} ({start_formatted})"
        else:
            return f"{type_name} ({start_formatted})"
    
    # Fallback
    return f"Placement ({start_formatted})"

def is_placement_active_today(placement: dict) -> bool:
    """Check if a placement is active today.
    
    For period-based placements (Class Referral, Cool-Down), checks if start_date == today.
    For multi-day placements (ISS, Lunch Detention), checks if today falls within the placement range.
    
    Args:
        placement: Placement dictionary with placementType, startDate, daysAssigned
        
    Returns:
        True if placement is active today, False otherwise
    """
    today = date.today()
    
    # Normalize placement_type
    placement_type = placement.get('placementType') or placement.get('placement_type', '')
    if isinstance(placement_type, str):
        placement_type = placement_type.upper()
    
    # Get start date
    start_date_str = placement.get('startDate') or placement.get('start_date')
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
    days_assigned = placement.get('daysAssigned') or placement.get('days_assigned', 0)
    
    if days_assigned == 0:
        return False
    
    # Calculate the effective end date using business days
    effective_end_date = add_business_days(start_date, days_assigned)
    
    # Check if today falls within the placement range (inclusive)
    return start_date <= today <= effective_end_date

def add_business_days(start_date: date, num_business_days: int) -> date:
    """Add a specified number of business days to a date, skipping weekends.
    
    The start_date counts as the first business day if it's a weekday.
    For example: add_business_days(Monday, 1) returns Monday (same day).
    """
    if num_business_days == 0:
        return start_date
    
    current_date = start_date
    days_added = 0
    
    # If start_date is a weekday, count it as day 1
    if current_date.weekday() < 5:
        days_added = 1
    
    # Add remaining business days
    while days_added < num_business_days:
        current_date += timedelta(days=1)
        if current_date.weekday() < 5:  # Monday=0, Friday=4
            days_added += 1
    
    return current_date

def calculate_days_remaining(start_date: str, days_assigned: int, days_completed: int = 0) -> int:
    """Calculate how many days remain in a placement, accounting for completed days through daily fulfillment.
    
    This function skips weekends when calculating remaining days, ensuring that only business days
    (Monday-Friday) count toward placement duration for ISS and Lunch Detention placements.
    
    Returns the number of business days remaining based on:
    - days_assigned: total business days in the placement
    - days_completed: business days already fulfilled
    """
    try:
        # Simple calculation: remaining = assigned - completed
        # The days_assigned already accounts for weekends (calculated during placement creation)
        # The days_completed is tracked through session fulfillment
        return max(0, days_assigned - days_completed)
    except (ValueError, TypeError):
        return 0

def get_placement_type_display_name(placement_type: str) -> str:
    """Convert placement type code to human-readable label.
    
    Args:
        placement_type: Internal placement type code (ISS, LUNCH_DETENTION, CLASS_REFERRAL, COOL_DOWN)
        
    Returns:
        Human-readable placement type label
    """
    if isinstance(placement_type, str):
        placement_type = placement_type.upper()
    
    type_labels = {
        'ISS': 'In-School Suspension (ISS)',
        'LUNCH_DETENTION': 'Lunch Detention',
        'CLASS_REFERRAL': 'Class Period Referral',
        'COOL_DOWN': 'Cool-Down Referral'
    }
    return type_labels.get(placement_type, placement_type)

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

def is_school_day(date_obj: date) -> bool:
    """Check if a date is a school day (not weekend or holiday).
    
    Currently only checks for weekends. Future enhancement: add holiday checking.
    This structure allows easy extension to exclude specific holidays or no-school days.
    
    Args:
        date_obj: Date to check (can be date object or ISO string)
        
    Returns:
        True if the date is a school day (Monday-Friday), False otherwise
        
    Future usage:
        # Add holiday list checking
        holidays = get_school_holidays()  # Could load from database or config
        if date_obj in holidays:
            return False
    """
    if isinstance(date_obj, str):
        try:
            date_obj = datetime.fromisoformat(date_obj).date()
        except (ValueError, TypeError):
            return False
    
    # Currently only checks weekends; extend here for holidays
    return not is_weekend(date_obj)

def calculate_school_day_number(placement_start_date: str, current_date: str) -> int:
    """Calculate which school day number the current date represents in a placement.
    
    Only counts school days (Monday-Friday). Weekends are skipped.
    Returns 0 if current_date is before placement start or is not a school day.
    
    Example:
        Placement starts Thursday (Nov 13)
        - Thursday Nov 13 = Day 1
        - Friday Nov 14 = Day 2
        - Saturday Nov 15 = Not counted (weekend)
        - Sunday Nov 16 = Not counted (weekend)
        - Monday Nov 17 = Day 3
    
    Args:
        placement_start_date: ISO format date string when placement started
        current_date: ISO format date string to calculate day number for
        
    Returns:
        The school day number (1-indexed), or 0 if not a valid school day
    """
    try:
        start = datetime.fromisoformat(placement_start_date).date()
        current = datetime.fromisoformat(current_date).date()
        
        # If current date is before start, return 0
        if current < start:
            return 0
        
        # If current date is not a school day, return 0
        if not is_school_day(current):
            return 0
        
        # Count school days from start to current (inclusive)
        day_number = 0
        check_date = start
        
        while check_date <= current:
            if is_school_day(check_date):
                day_number += 1
            check_date += timedelta(days=1)
        
        return day_number
    except (ValueError, TypeError):
        return 0


def calculate_total_duration(placement: dict) -> dict:
    """Calculate total duration for any placement type.
    
    Returns a dictionary with duration information:
    - unit: 'school_days' or 'periods'
    - total: total number of units
    - label: human-readable description
    
    Args:
        placement: Placement dictionary with all relevant fields
        
    Returns:
        Dictionary with 'unit', 'total', and 'label' keys
    """
    # Normalize placement_type (handle both camelCase and snake_case from different sources)
    placement_type = placement.get('placementType') or placement.get('placement_type', '')
    if isinstance(placement_type, str):
        placement_type = placement_type.upper()
    
    # ISS and Lunch Detention use school days
    if placement_type in ['ISS', 'LUNCH_DETENTION']:
        # Try daysAssigned (from DB) or days_assigned (from API)
        total_days = placement.get('daysAssigned') or placement.get('days_assigned', 0)
        
        # If no days_assigned, compute from date range (try both camelCase and snake_case)
        if not total_days:
            start_date_str = placement.get('startDate') or placement.get('start_date')
            end_date_str = placement.get('endDate') or placement.get('end_date')
            
            if start_date_str and end_date_str:
                total_days = get_business_days_between(start_date_str, end_date_str)
        
        return {
            'unit': 'school_days',
            'total': total_days,
            'label': f"{total_days} school day{'s' if total_days != 1 else ''}"
        }
    
    # Class Referral and Cool-Down use periods
    elif placement_type in ['CLASS_REFERRAL', 'COOL_DOWN']:
        # Try both camelCase and snake_case field names
        start_period = placement.get('startPeriod') or placement.get('start_period')
        end_period = placement.get('endPeriod') or placement.get('end_period')
        
        if start_period is not None and end_period is not None:
            total_periods = end_period - start_period + 1
            if total_periods == 1:
                label = f"Period {start_period}"
            else:
                label = f"Periods {start_period}-{end_period}"
            
            return {
                'unit': 'periods',
                'total': total_periods,
                'label': label
            }
        else:
            # Missing period information
            return {
                'unit': 'periods',
                'total': 0,
                'label': 'No period information'
            }
    
    # Fallback
    return {
        'unit': 'unknown',
        'total': 0,
        'label': 'Unknown duration'
    }


def placement_is_active_today(placement: dict, reference_date: date = None) -> bool:
    """Check if a placement is active on a given date.
    
    Args:
        placement: Placement dictionary with all relevant fields
        reference_date: Date to check (defaults to today)
        
    Returns:
        True if placement is active on the reference date
    """
    if reference_date is None:
        reference_date = date.today()
    
    # Convert reference_date to date object if it's a string
    if isinstance(reference_date, str):
        try:
            reference_date = datetime.fromisoformat(reference_date).date()
        except (ValueError, TypeError):
            return False
    
    # Normalize field names (handle both camelCase from DB and snake_case)
    placement_type = placement.get('placementType') or placement.get('placement_type', '')
    if isinstance(placement_type, str):
        placement_type = placement_type.upper()
    
    # Normalize status (handle enum instances, case variations)
    status = placement.get('status', '')
    if hasattr(status, 'value'):
        # Handle enum instances (e.g., PlacementStatus.active)
        status = status.value
    if isinstance(status, str):
        status = status.lower()
    
    # Placement must have active status
    if status != 'active':
        return False
    
    # For ISS and Lunch Detention, check date range
    if placement_type in ['ISS', 'LUNCH_DETENTION']:
        start_date_str = placement.get('startDate') or placement.get('start_date')
        end_date_str = placement.get('endDate') or placement.get('end_date')
        
        if not start_date_str:
            return False
        
        try:
            start_date_obj = datetime.fromisoformat(start_date_str).date()
            
            # Compute end_date if not provided
            if not end_date_str:
                days_assigned = placement.get('daysAssigned') or placement.get('days_assigned', 0)
                if days_assigned > 0:
                    end_date_obj = add_business_days(start_date_obj, days_assigned)
                else:
                    # If no days_assigned and no end_date, can't determine range
                    return False
            else:
                end_date_obj = datetime.fromisoformat(end_date_str).date()
            
            # Check if reference_date is within the range and is a school day
            return start_date_obj <= reference_date <= end_date_obj and is_school_day(reference_date)
        except (ValueError, TypeError):
            return False
    
    # For Class Referral and Cool-Down, check single date
    elif placement_type in ['CLASS_REFERRAL', 'COOL_DOWN']:
        # These use startDate as the single date
        placement_date_str = placement.get('startDate') or placement.get('start_date')
        
        if not placement_date_str:
            return False
        
        try:
            placement_date = datetime.fromisoformat(placement_date_str).date()
            return placement_date == reference_date
        except (ValueError, TypeError):
            return False
    
    return False


def get_placement_duration_info(placement: dict, reference_date: date = None) -> dict:
    """Get comprehensive duration information for any placement type.
    
    This provides a unified interface for querying placement duration across
    all placement types (ISS, Lunch Detention, Class Referral, Cool-Down).
    
    Args:
        placement: Placement dictionary with all relevant fields
        reference_date: Date for progress calculation (defaults to today)
        
    Returns:
        Dictionary with:
        - placement_type: Type of placement
        - duration_unit: 'school_days' or 'periods'
        - total_duration: Total duration in the appropriate unit
        - duration_label: Human-readable duration description
        - is_active_today: Whether placement is active on reference_date
        - current_progress: Current progress (for multi-day placements)
        - progress_label: Human-readable progress (e.g., "Day 2 of 5")
        - days_remaining: Remaining days/periods (for active placements)
    """
    if reference_date is None:
        reference_date = date.today()
    
    # Convert reference_date to date object if it's a string
    if isinstance(reference_date, str):
        try:
            reference_date = datetime.fromisoformat(reference_date).date()
        except (ValueError, TypeError):
            reference_date = date.today()
    
    # Normalize field names
    placement_type = placement.get('placementType') or placement.get('placement_type', '')
    if isinstance(placement_type, str):
        placement_type = placement_type.upper()
    
    # Get total duration
    duration = calculate_total_duration(placement)
    
    # Check if active today
    is_active = placement_is_active_today(placement, reference_date)
    
    # Calculate progress for multi-day placements
    current_progress = None
    progress_label = None
    days_remaining = None
    
    if placement_type in ['ISS', 'LUNCH_DETENTION']:
        start_date_str = placement.get('startDate') or placement.get('start_date')
        if start_date_str:
            day_number = calculate_school_day_number(
                start_date_str,
                reference_date.isoformat()
            )
            total_days = duration['total']
            
            # Only show progress if within placement range
            if day_number > 0 and day_number <= total_days:
                current_progress = day_number
                progress_label = f"Day {day_number} of {total_days}"
                days_remaining = max(0, total_days - day_number)
            elif day_number > total_days:
                # Placement should be completed
                current_progress = total_days
                progress_label = f"Completed ({total_days} of {total_days})"
                days_remaining = 0
    
    return {
        'placement_type': placement_type,
        'duration_unit': duration['unit'],
        'total_duration': duration['total'],
        'duration_label': duration['label'],
        'is_active_today': is_active,
        'current_progress': current_progress,
        'progress_label': progress_label,
        'days_remaining': days_remaining
    }


def get_school_days(start_date: date, days_needed: int) -> list:
    """Generate a list of school days (weekdays) starting from start_date.
    
    Args:
        start_date: The starting date (must be a weekday)
        days_needed: Number of school days to include
        
    Returns:
        List of date objects representing scheduled school days (ISO format strings)
    """
    school_dates = []
    current_date = start_date
    
    while len(school_dates) < days_needed:
        if is_school_day(current_date):
            school_dates.append(current_date.isoformat())
        current_date += timedelta(days=1)
    
    return school_dates
