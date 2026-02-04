from datetime import date
from typing import Dict, List, Tuple, Any
import streamlit as st

class PointSystem:
    def __init__(self):
        """Initialize the point system with predefined menus."""
        self.positive_point_menu = [
            {"label": "Repair the harm – written (+1)", "code": "REPAIR_WRITTEN", "value": 1, "limit": "once_per_placement", "mutex": "REPAIR_VERBAL"},
            {"label": "Repair the harm – verbal (+2)", "code": "REPAIR_VERBAL", "value": 2, "limit": "once_per_placement", "mutex": "REPAIR_WRITTEN"},
            {"label": "Complete an assignment (+1)", "code": "COMPLETE_ASSIGNMENT", "value": 1},
            {"label": "Read a chapter (+1)", "code": "READ_CHAPTER", "value": 1},
            {"label": "Meet with counselor (+1)", "code": "MEET_COUNSELOR", "value": 1},
            {"label": "Restorative discussion (+1)", "code": "RESTORATIVE_DISCUSSION", "value": 1},
            {"label": "Helpful task (+1)", "code": "HELPFUL_TASK", "value": 1},
            {"label": "Grotto is clean & damage free (+1)", "code": "CLEAN_ROOM", "value": 1},
            {"label": "Other (+1)", "code": "OTHER_POSITIVE", "value": 1}
        ]
        
        self.negative_point_menu = [
            {"label": "Behavior redirection (–1)", "code": "NEG_REDIRECTION", "value": -1},
            {"label": "Unauthorized computer use (–1)", "code": "NEG_COMPUTER", "value": -1},
            {"label": "Refusing to do classwork (–1)", "code": "NEG_REFUSAL", "value": -1},
            {"label": "Sleeping or head on desk (–1)", "code": "NEG_SLEEPING", "value": -1},
            {"label": "Leaving without permission (–1)", "code": "NEG_LEAVING", "value": -1},
            {"label": "Disrespectful behavior or language (–1)", "code": "NEG_DISRESPECT", "value": -1},
            {"label": "Disruptive or loud behavior (–1)", "code": "NEG_DISRUPTIVE", "value": -1},
            {"label": "Other (–1)", "code": "OTHER_NEGATIVE", "value": -1}
        ]
        
        # Create a combined lookup dictionary
        self.all_point_items = {}
        for item in self.positive_point_menu + self.negative_point_menu:
            self.all_point_items[item['code']] = item
        
        # Session type filtering configuration
        # Maps session types to allowed behavior codes
        self.session_type_filters = {
            'iss_full_day': {
                'positive': 'all',  # Show all positive behaviors
                'negative': 'all'   # Show all negative behaviors
            },
            'periods': {
                'positive': [
                    'REPAIR_WRITTEN', 'REPAIR_VERBAL', 'COMPLETE_ASSIGNMENT',
                    'MEET_COUNSELOR', 'RESTORATIVE_DISCUSSION', 'HELPFUL_TASK',
                    'CLEAN_ROOM', 'OTHER_POSITIVE'
                ],  # Hide READ_CHAPTER as it's optional/out-of-scope
                'negative': 'all'
            },
            'referral': {
                'positive': [
                    'REPAIR_WRITTEN', 'REPAIR_VERBAL', 'COMPLETE_ASSIGNMENT',
                    'MEET_COUNSELOR', 'RESTORATIVE_DISCUSSION', 'HELPFUL_TASK',
                    'CLEAN_ROOM', 'OTHER_POSITIVE'
                ],  # Same as periods
                'negative': 'all'
            },
            'lunch': {
                'positive': [
                    'HELPFUL_TASK', 'CLEAN_ROOM', 'OTHER_POSITIVE'
                ],  # Simplified: on-time, respectful, quiet task
                'negative': [
                    'NEG_REDIRECTION', 'NEG_DISRESPECT', 'NEG_DISRUPTIVE',
                    'OTHER_NEGATIVE'
                ]  # Simplified negatives
            },
            'cool_down': {
                'positive': ['OTHER_POSITIVE'],  # Minimal - use "Other" for "returned to class ready"
                'negative': []  # Hide points by default
            }
        }
    
    def get_positive_point_menu(self, session_type: str = None) -> List[Dict[str, Any]]:
        """
        Get the positive point menu, optionally filtered by session type.
        
        Args:
            session_type: Optional session type to filter behaviors (e.g., 'periods', 'lunch', 'cool_down')
        
        Returns:
            List of positive behavior items, filtered if session_type is provided
        """
        if session_type and session_type in self.session_type_filters:
            allowed_codes = self.session_type_filters[session_type]['positive']
            
            # If 'all', return full menu
            if allowed_codes == 'all':
                return self.positive_point_menu
            
            # Filter to only allowed codes
            return [item for item in self.positive_point_menu if item['code'] in allowed_codes]
        
        return self.positive_point_menu
    
    def get_negative_point_menu(self, session_type: str = None) -> List[Dict[str, Any]]:
        """
        Get the negative point menu, optionally filtered by session type.
        
        Args:
            session_type: Optional session type to filter behaviors (e.g., 'periods', 'lunch', 'cool_down')
        
        Returns:
            List of negative behavior items, filtered if session_type is provided
        """
        if session_type and session_type in self.session_type_filters:
            allowed_codes = self.session_type_filters[session_type]['negative']
            
            # If 'all', return full menu
            if allowed_codes == 'all':
                return self.negative_point_menu
            
            # Filter to only allowed codes
            return [item for item in self.negative_point_menu if item['code'] in allowed_codes]
        
        return self.negative_point_menu
    
    def get_point_item_by_code(self, code: str) -> Dict[str, Any]:
        """Get point item details by code."""
        return self.all_point_items.get(code, {"label": "Unknown", "value": 0})
    
    def can_add_point_event(self, placement_id: str, student_id: str, code: str, event_date: str) -> Tuple[bool, str]:
        """
        Check if a point event can be added based on limits and caps.
        Returns (can_add, reason_if_not)
        """
        dm = st.session_state.data_manager
        point_item = self.get_point_item_by_code(code)
        
        if not point_item:
            return False, "Invalid point code"
        
        existing_events = dm.get_all_point_events_for_placement(placement_id)
        
        # Check placement-level limits (once per placement)
        if point_item.get('limit') == 'once_per_placement':
            if any(event['code'] == code for event in existing_events):
                return False, f"Already used during this placement"
            
            # Check mutex (mutually exclusive) - if one is used, the other can't be
            mutex_code = point_item.get('mutex')
            if mutex_code and any(event['code'] == mutex_code for event in existing_events):
                return False, f"Cannot use both repair options"
        
        # Check total caps (total times across entire placement)
        if 'totalCap' in point_item:
            total_cap = point_item['totalCap']
            total_count = len([event for event in existing_events if event['code'] == code])
            
            if total_count >= total_cap:
                return False, f"Max {total_cap} times per placement"
        
        # Check daily caps
        if 'dailyCap' in point_item:
            daily_cap = point_item['dailyCap']
            daily_events = dm.get_point_events_for_date(placement_id, event_date)
            daily_count = len([event for event in daily_events if event['code'] == code])
            
            if daily_count >= daily_cap:
                return False, f"Daily limit reached ({daily_cap} per day)"
        
        return True, ""
    
    def calculate_point_summary(self, placement_id: str) -> Dict[str, Any]:
        """Calculate comprehensive point summary for a placement."""
        dm = st.session_state.data_manager
        all_events = dm.get_all_point_events_for_placement(placement_id)
        
        summary = {
            'total_positive': 0,
            'total_negative': 0,
            'cumulative_total': 0,
            'event_count': len(all_events),
            'events_by_type': {},
            'daily_breakdown': {}
        }
        
        for event in all_events:
            # Total calculations
            if event['type'] == 'positive':
                summary['total_positive'] += event['value']
            else:
                summary['total_negative'] += event['value']
            
            summary['cumulative_total'] += event['value']
            
            # Event type breakdown
            if event['code'] not in summary['events_by_type']:
                summary['events_by_type'][event['code']] = {
                    'count': 0,
                    'total_value': 0,
                    'label': self.get_point_item_by_code(event['code'])['label']
                }
            
            summary['events_by_type'][event['code']]['count'] += 1
            summary['events_by_type'][event['code']]['total_value'] += event['value']
            
            # Daily breakdown
            event_date = event['date']
            if event_date not in summary['daily_breakdown']:
                summary['daily_breakdown'][event_date] = {
                    'positive': 0,
                    'negative': 0,
                    'total': 0
                }
            
            if event['type'] == 'positive':
                summary['daily_breakdown'][event_date]['positive'] += event['value']
            else:
                summary['daily_breakdown'][event_date]['negative'] += event['value']
            
            summary['daily_breakdown'][event_date]['total'] += event['value']
        
        return summary
