from __future__ import annotations

from typing import Any

import streamlit as st


_PENDING_KEY = "_pending_state_updates"


def queue_state_updates(**updates: Any) -> None:
    """Apply widget-bound session-state changes safely on the next rerun."""
    pending = dict(st.session_state.get(_PENDING_KEY, {}))
    pending.update(updates)
    st.session_state[_PENDING_KEY] = pending
    st.rerun()


def apply_pending_state_updates() -> None:
    """Apply queued changes before any widgets using those keys are created."""
    pending = st.session_state.pop(_PENDING_KEY, {})
    for key, value in pending.items():
        st.session_state[key] = value
