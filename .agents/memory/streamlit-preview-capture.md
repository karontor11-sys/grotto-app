---
name: Streamlit preview capture limitation
description: App screenshots can be blank even when the Streamlit server is healthy.
---

The app-preview screenshot has repeatedly returned a blank white frame while the Streamlit workflow is running and its health endpoint responds successfully.

**Why:** A blank capture by itself has not been reliable evidence of a server crash or of what the authenticated Dashboard displays.

**How to apply:** Check workflow logs and health independently, and use isolated code or database tests for affected flows. Do not claim visual verification of authenticated screens from a blank screenshot.