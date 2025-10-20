from datetime import date
from typing import Dict, List, Tuple, Any
import streamlit as st

class PointSystem:
    def __init__(self):
        """Initialize the point system with predefined menus."""
        self.positive_point_menu = [
            {"label": "Repair the harm – Written", "code": "REPAIR_WRITTEN", "value": 1, "limit": "once_per_placement"},
            {"label": "Repair the harm – Verbal", "code": "REPAIR_VERBAL", "value": 2, "limit": "once_per_placement"},
            {"label": "Complete an assignment", "code": "COMPLETE_ASSIGNMENT", "value": 1},
            {"label": "Read a chapter", "code": "READ_CHAPTER", "value": 1, "dailyCap": 4},
            {"label": "Grotto clean & damage-free", "code": "CLEAN_ROOM", "value": 1, "dailyCap": 1},
            {"label": "Meet with a counselor", "code": "MEET_COUNSELOR", "value": 1, "dailyCap": 1},
            {"label": "Complete a helpful task", "code": "HELPFUL_TASK", "value": 1}
        ]
        
        self.negative_point_menu = [
            {"label": "Behavior redirection from staff", "code": "NEG_REDIRECTION", "value": -1},
            {"label": "Playing games without permission", "code": "NEG_GAMES", "value": -1},
            {"label": "Refusing to do classwork", "code": "NEG_REFUSAL", "value": -1},
            {"label": "Sleeping or resting head on desk", "code": "NEG_SLEEPING", "value": -1},
            {"label": "Leaving The Grotto without permission", "code": "NEG_LEAVING", "value": -1},
            {"label": "Disrespect toward others", "code": "NEG_DISRESPECT", "value": -1},
            {"label": "Disruptive or loud behavior", "code": "NEG_DISRUPTIVE", "value": -1}
        ]
        
        # Create a combined lookup dictionary
        self.all_point_items = {}
        for item in self.positive_point_menu + self.negative_point_menu:
            self.all_point_items[item['code']] = item
    
    def get_positive_point_menu(self) -> List[Dict[str, Any]]:
        """Get the positive point menu."""
        return self.positive_point_menu
    
    def get_negative_point_menu(self) -> List[Dict[str, Any]]:
        """Get the negative point menu."""
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
        
        # Check placement-level limits (once per placement)
        if point_item.get('limit') == 'once_per_placement':
            existing_events = dm.get_all_point_events_for_placement(placement_id)
            if any(event['code'] == code for event in existing_events):
                return False, f"This action can only be performed once per placement"
        
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
