# app/ui/parameter_controls.py
# Renders the right-hand column with generation parameter controls.
import streamlit as st
import logging
from app.state import manager as state_manager # Use state manager
from app.logic import api_client # For defaults/limits

logger = logging.getLogger(__name__)

def display_parameter_controls():
    """Displays sliders and controls for generation parameters."""
    # IN: None; OUT: None # Renders parameter sliders/toggles in right column.
    st.header("Parameters")
    st.markdown("---")

    # Retrieve limits/values from state or defaults
    model_max_limit = st.session_state.get('current_model_max_output_tokens', api_client.FALLBACK_MODEL_MAX_OUTPUT_TOKENS)
    if 'max_output_tokens' not in st.session_state:
        st.session_state.max_output_tokens = state_manager.DEFAULT_GEN_CONFIG['max_output_tokens']

    state_manager.clamp_max_tokens() # Clamp before rendering

    # Max Output Tokens Slider
    st.session_state.max_output_tokens = st.slider(
        f"Max Output Tokens (Limit: {model_max_limit:,})", min_value=1,
        max_value=max(1, model_max_limit), value=st.session_state.max_output_tokens,
        step=max(1, model_max_limit // 256) if model_max_limit > 1 else 1,
        key="maxoutput_slider", help=f"Max tokens per response. Model limit: {model_max_limit:,}"
    )
    # Temperature Slider
    st.session_state.temperature = st.slider(
        "Temperature:", 0.0, 2.0, step=0.05,
        value=st.session_state.get("temperature", state_manager.DEFAULT_GEN_CONFIG["temperature"]),
        key="temp_slider", help="Randomness (0=deterministic). Default: 0.7"
    )
    # Top P Slider
    st.session_state.top_p = st.slider(
        "Top P:", 0.0, 1.0, step=0.01,
        value=st.session_state.get("top_p", state_manager.DEFAULT_GEN_CONFIG["top_p"]),
        key="topp_slider", help="Nucleus sampling probability. Default: 1.0"
    )
    # Top K Slider
    st.session_state.top_k = st.slider(
        "Top K:", 1, 100, step=1,
        value=st.session_state.get("top_k", state_manager.DEFAULT_GEN_CONFIG["top_k"]),
        key="topk_slider", help="Consider top K likely tokens. Default: 40"
    )
    st.markdown("---")
    # Stop Sequences Text Area
    st.session_state.stop_sequences_str = st.text_area(
        "Stop Sequences (one per line):",
        value=st.session_state.get("stop_sequences_str", state_manager.DEFAULT_GEN_CONFIG["stop_sequences_str"]),
        key="stopseq_textarea", height=80,
        help="Stop generation if these exact sequences appear."
    )
    # JSON Mode Toggle
    st.session_state.json_mode = st.toggle(
        "JSON Output Mode",
        value=st.session_state.get("json_mode", state_manager.DEFAULT_GEN_CONFIG["json_mode"]),
        key="json_toggle",
        help="Request structured JSON output (model must support)."
    )

    # --- Grounding Controls --- ADDED/MODIFIED ---
    st.markdown("---")
    st.subheader("Grounding")
    st.session_state.enable_grounding = st.toggle(
        "Enable Grounding (via Google Search)",
        value=st.session_state.get("enable_grounding", state_manager.DEFAULT_GEN_CONFIG["enable_grounding"]),
        key="grounding_toggle",
        help="Allow the model to use Google Search to improve factual accuracy."
    )
    # Grounding Threshold Slider (Only enable if grounding is toggled on)
    grounding_threshold_disabled = not st.session_state.enable_grounding
    st.session_state.grounding_threshold = st.slider(
        "Grounding Confidence Threshold:", 0.0, 1.0, step=0.05,
        value=st.session_state.get("grounding_threshold", state_manager.DEFAULT_GEN_CONFIG["grounding_threshold"]),
        key="grounding_thresh_slider",
        disabled=grounding_threshold_disabled,
        help="Controls when grounding is used (0.0 = always try if enabled, higher = requires more confidence). Disable grounding toggle to fully turn off."
    )