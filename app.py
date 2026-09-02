"""Streamlit app for GeoRisk Transmission Analyzer."""

import html
import logging

import requests
import streamlit as st
import streamlit.components.v1 as components

from src.config import GEORISK_API_TIMEOUT_SECONDS, GEORISK_API_URL
from src.report_formatter import EVENT_TYPE_LABELS, NODE_LABELS
from src.schemas import FinalReport


logger = logging.getLogger(__name__)

EXAMPLE_EVENTS = [
    {
        "label": "Semiconductor Export Controls",
        "event": "Semiconductor Export Controls",
        "year": 2026,
        "context": (
            "The U.S. expands export controls on advanced AI chips and "
            "semiconductor equipment to China."
        ),
        "description": (
            "Technology-access risk across AI chips, semiconductor equipment, "
            "foundries, and EDA software."
        ),
    },
    {
        "label": "Energy & Fertilizer Shock",
        "event": "Energy & Fertilizer Shock",
        "year": 2026,
        "context": (
            "Russia-related gas supply disruptions raise concerns over European "
            "fertilizer production and food input costs."
        ),
        "description": (
            "Energy-input risk across natural gas, fertilizer, agriculture, and "
            "food supply chains."
        ),
    },
]
EVIDENCE_LABELS = {
    "historical_supported": "🟢 Historical Supported",
    "sector_proxy": "🟡 Sector Proxy",
    "inference_only": "⚪ Inference Only",
}
EVIDENCE_GUIDE = [
    (
        "🟢 Historical Supported",
        "Historical events directly support the asset or its exposure channel.",
    ),
    (
        "🟡 Sector Proxy",
        "History supports the broader sector or supply-chain channel, not the exact asset.",
    ),
    (
        "⚪ Inference Only",
        "The mapping is plausible, but the retrieved history does not directly corroborate it.",
    ),
]
SECOND_ORDER_EMPTY_STATE_TITLE = "No qualified second-order exposures identified"
SECOND_ORDER_EMPTY_STATE_BODY = (
    "GeoRisk identified direct exposure channels for this event, but no "
    "secondary assets met the current historical-support and transmission "
    "requirements. Direct exposures remain available in the Transmission Path "
    "as reference anchors."
)
REPORT_SECTIONS = [
    ("summary", "Overview"),
    ("watchlist", "Watchlist"),
    ("transmission", "Transmission"),
    ("evidence", "Evidence"),
]
DIRECT_REFERENCE_INITIAL_GROUPS = 6
REPORT_FOOTER_DISCLAIMER = (
    "GeoRisk surfaces market-risk exposure candidates from historical analogs. "
    "Outputs are not price forecasts, market probabilities, trading signals, "
    "or investment advice."
)
class GeoRiskAPIClientError(RuntimeError):
    """Raised for user-safe frontend API failures."""

    def __init__(self, user_message: str, *, status_code: int | None = None) -> None:
        super().__init__(user_message)
        self.user_message = user_message
        self.status_code = status_code


def main() -> None:
    """Render the Streamlit application."""

    st.set_page_config(
        page_title="GeoRisk Transmission Analyzer",
        page_icon="🌐",
        layout="wide",
        initial_sidebar_state="collapsed",
    )
    _inject_global_styles()
    _initialize_state()
    _scroll_to_top_if_requested()

    if st.session_state.page == "report" and "report" in st.session_state:
        _render_report_page()
    else:
        _render_home_page()


def _inject_global_styles() -> None:
    """Apply the shared visual system for the Streamlit application."""

    st.markdown(
        """
        <style>
        :root {
            --georisk-ink: #172033;
            --georisk-muted: #667085;
            --georisk-blue: #3157d5;
            --georisk-blue-dark: #2447b8;
            --georisk-navy: #14213d;
            --georisk-soft: #f6f8fc;
            --georisk-line: #e1e7f0;
        }
        .stApp {
            background: var(--georisk-soft);
            color: var(--georisk-ink);
        }
        .block-container {
            max-width: 1220px;
            padding-top: 2.2rem;
            padding-bottom: 4rem;
        }
        h1, h2, h3 { letter-spacing: -0.025em; }
        [data-testid="stHeaderActionElements"] { display: none !important; }
        .st-key-home_hero {
            padding: 3rem;
            border: 1px solid var(--georisk-line);
            border-radius: 26px;
            background:
                radial-gradient(circle at 8% 4%, rgba(49, 87, 213, 0.11), transparent 24rem),
                radial-gradient(circle at 96% 92%, rgba(118, 144, 224, 0.09), transparent 22rem),
                linear-gradient(145deg, #fbfcff 0%, #f1f5ff 48%, #eef2fb 100%);
            box-shadow: 0 22px 55px rgba(29, 52, 95, 0.09);
            margin-bottom: 2rem;
        }
        .georisk-eyebrow {
            color: var(--georisk-blue);
            font-size: 0.78rem;
            font-weight: 750;
            letter-spacing: 0.12em;
            text-transform: uppercase;
            margin-bottom: 0.8rem;
        }
        .georisk-hero-copy h1 {
            color: var(--georisk-ink);
            font-size: clamp(2.5rem, 4.4vw, 4.1rem);
            line-height: 1.04;
            max-width: 650px;
            margin: 0 0 1rem;
        }
        .georisk-hero-copy > p {
            color: var(--georisk-muted);
            font-size: 1.04rem;
            line-height: 1.68;
            max-width: 590px;
            margin: 0;
        }
        .georisk-value-list {
            display: grid;
            gap: 0.7rem;
            margin-top: 1.7rem;
        }
        .georisk-value-item {
            display: flex;
            align-items: center;
            gap: 0.8rem;
            color: var(--georisk-ink);
            font-size: 0.94rem;
            font-weight: 700;
        }
        .georisk-value-icon {
            display: grid;
            place-items: center;
            flex: 0 0 2rem;
            width: 2rem;
            height: 2rem;
            color: var(--georisk-blue-dark);
            border: 1px solid #ced9fa;
            border-radius: 9px;
            background: rgba(255, 255, 255, 0.72);
        }
        .georisk-value-icon svg {
            width: 1.05rem;
            height: 1.05rem;
            fill: none;
            stroke: currentColor;
            stroke-width: 1.8;
            stroke-linecap: round;
            stroke-linejoin: round;
        }
        .st-key-hero_input {
            padding: 1.5rem;
            border: 1px solid var(--georisk-line);
            border-radius: 19px;
            background: #ffffff;
            box-shadow: 0 14px 36px rgba(31, 49, 83, 0.09);
        }
        .georisk-form-kicker {
            color: var(--georisk-muted);
            font-size: 0.74rem;
            font-weight: 750;
            letter-spacing: 0.09em;
            text-transform: uppercase;
        }
        .georisk-form-title {
            color: var(--georisk-ink);
            font-size: 1.45rem;
            font-weight: 760;
            margin: 0.35rem 0 0.2rem;
        }
        .georisk-section-intro {
            color: var(--georisk-muted);
            max-width: 760px;
            margin: -0.3rem 0 1.2rem;
        }
        .georisk-step {
            color: var(--georisk-blue);
            font-size: 0.75rem;
            font-weight: 750;
            letter-spacing: 0.08em;
            text-transform: uppercase;
        }
        div[data-testid="stForm"], div[data-testid="stVerticalBlockBorderWrapper"] {
            border-color: var(--georisk-line);
            border-radius: 18px;
            background: #ffffff;
        }
        div[data-testid="stButton"] > button[kind="primary"],
        div[data-testid="stFormSubmitButton"] > button {
            background: var(--georisk-blue) !important;
            border-color: var(--georisk-blue) !important;
            color: #ffffff !important;
            border-radius: 10px;
            font-weight: 700;
            min-height: 2.75rem;
        }
        div[data-testid="stButton"] > button[kind="primary"]:hover,
        div[data-testid="stFormSubmitButton"] > button:hover {
            background: var(--georisk-blue-dark) !important;
            border-color: var(--georisk-blue-dark) !important;
        }
        .georisk-report-nav-label {
            color: var(--georisk-muted);
            font-size: 0.78rem;
            margin: 0.25rem 0 0.7rem;
        }
        [class*="st-key-example_card_"] > div[data-testid="stElementContainer"]:has(div[data-testid="stButton"]) {
            margin-top: auto;
        }
        .georisk-example-copy { display: flex; flex-direction: column; }
        .georisk-example-label {
            color: var(--georisk-muted);
            font-size: 0.73rem;
            letter-spacing: 0.07em;
            text-transform: uppercase;
            margin-bottom: 1.15rem;
        }
        .georisk-example-copy h3 {
            color: var(--georisk-ink);
            font-size: 1.55rem;
            line-height: 1.22;
            min-height: 3.8rem;
            margin: 0 0 0.8rem;
        }
        .georisk-example-copy p {
            color: var(--georisk-ink);
            font-size: 0.94rem;
            line-height: 1.55;
            min-height: 4.5rem;
            margin: 0;
        }
        div[class*="st-key-report_nav_"] div[data-testid="stButton"] > button[data-testid="stBaseButton-primary"] {
            background: #e9efff !important;
            border-color: #c9d5fa !important;
            color: var(--georisk-blue-dark) !important;
        }
        div[class*="st-key-report_nav_"] div[data-testid="stButton"] > button[data-testid="stBaseButton-primary"]:hover {
            background: #dde7ff !important;
            border-color: #b9c9f8 !important;
            color: var(--georisk-blue-dark) !important;
        }
        .georisk-footer-note {
            color: var(--georisk-muted);
            font-size: 0.82rem;
            text-align: center;
            padding-top: 1.2rem;
        }
        .georisk-process {
            margin-top: 2.8rem;
            padding: 2.3rem;
            border: 1px solid var(--georisk-line);
            border-radius: 22px;
            background: #ffffff;
        }
        .georisk-process-kicker {
            color: var(--georisk-blue);
            font-size: 0.75rem;
            font-weight: 800;
            letter-spacing: 0.1em;
            text-transform: uppercase;
        }
        .georisk-process h2 {
            color: var(--georisk-ink);
            font-size: 2rem;
            margin: 0.55rem 0 1.6rem;
        }
        .georisk-process-grid {
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: 0.85rem;
            align-items: stretch;
            counter-reset: georisk-stage;
        }
        .georisk-process-item {
            display: flex;
            flex-direction: column;
            min-height: 205px;
            padding: 1.25rem;
            border: 1px solid #e4e9f3;
            border-radius: 16px;
            background: linear-gradient(145deg, #fbfcff 0%, #f3f6fc 100%);
            box-shadow: 0 8px 24px rgba(31, 49, 83, 0.035);
        }
        .georisk-process-meta {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 0.8rem;
        }
        .georisk-process-number {
            display: grid;
            place-items: center;
            width: 2rem;
            height: 2rem;
            color: var(--georisk-blue);
            background: #e8eeff;
            border-radius: 999px;
            font-size: 0.68rem;
            font-weight: 800;
            letter-spacing: 0.1em;
        }
        .georisk-process-label {
            color: #7a879e;
            font-size: 0.65rem;
            font-weight: 800;
            letter-spacing: 0.08em;
            text-transform: uppercase;
        }
        .georisk-process-item h3 {
            color: var(--georisk-ink);
            font-size: 1.04rem;
            min-height: 2.6rem;
            margin: 1.1rem 0 0.55rem;
        }
        .georisk-process-item p {
            color: var(--georisk-muted);
            font-size: 0.84rem;
            line-height: 1.5;
            margin: 0;
        }
        @media (max-width: 900px) {
            .st-key-home_hero div[data-testid="stHorizontalBlock"] {
                flex-direction: column;
            }
            .st-key-home_hero div[data-testid="stColumn"] {
                width: 100% !important;
                flex: 1 1 100% !important;
            }
        }
        @media (min-width: 721px) and (max-width: 1000px) {
            .georisk-process-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
        }
        @media (max-width: 720px) {
            .block-container { padding-top: 1rem; }
            .st-key-home_hero { padding: 1.5rem; border-radius: 19px; }
            .georisk-hero-copy h1 { font-size: 2.45rem; }
            .georisk-process { padding: 1.5rem; }
            .georisk-process-grid { grid-template-columns: 1fr; gap: 0.8rem; }
            .georisk-process-item h3 { min-height: auto; }
            .st-key-overview_previews > div[data-testid="stLayoutWrapper"] > div[data-testid="stHorizontalBlock"] {
                flex-direction: column;
            }
            .st-key-overview_previews > div[data-testid="stLayoutWrapper"] > div[data-testid="stHorizontalBlock"] > div[data-testid="stColumn"] {
                width: 100% !important;
                flex: 1 1 100% !important;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _initialize_state() -> None:
    """Initialize Streamlit session state."""

    if "page" not in st.session_state:
        st.session_state.page = "home"
    if "custom_news_text" not in st.session_state:
        st.session_state.custom_news_text = ""
    if "custom_event" not in st.session_state:
        st.session_state.custom_event = ""
    if "service_error" not in st.session_state:
        st.session_state.service_error = ""
    if "report_section" not in st.session_state:
        st.session_state.report_section = "summary"


def _scroll_to_top_if_requested() -> None:
    """Reset browser scroll after a logical page transition."""

    if not st.session_state.get("scroll_to_top"):
        return
    st.session_state.scroll_to_top = False
    components.html(
        """
        <script>
          try {
            const parentWindow = window.parent;
            parentWindow.history.replaceState(
              null,
              "",
              parentWindow.location.pathname + parentWindow.location.search
            );
            const mainScroller = parentWindow.document.querySelector('[data-testid="stMain"]');
            if (mainScroller) {
              mainScroller.scrollTo({ top: 0, left: 0, behavior: "auto" });
            }
            parentWindow.scrollTo({ top: 0, left: 0, behavior: "auto" });
          } catch (error) {
            window.parent.scrollTo(0, 0);
          }
        </script>
        """,
        height=0,
        width=0,
    )


def _render_home_page() -> None:
    """Render the event dashboard home page."""

    _render_service_status_message()
    with st.container(key="home_hero"):
        story_column, input_column = st.columns([1.08, 0.92], gap="large", vertical_alignment="center")
        with story_column:
            st.markdown(
                """
                <div class="georisk-hero-copy">
                  <div class="georisk-eyebrow">Geopolitical risk intelligence</div>
                  <h1>See the risk beneath the headline.</h1>
                  <p>Paste a geopolitical event. GeoRisk structures the shock, finds relevant
                  historical analogs, traces direct and second-order transmission channels, and
                  returns an evidence-labeled asset watchlist for human review.</p>
                  <div class="georisk-value-list">
                    <div class="georisk-value-item">
                      <span class="georisk-value-icon" aria-hidden="true">
                        <svg viewBox="0 0 24 24"><circle cx="7" cy="7" r="3"></circle><circle cx="17" cy="17" r="3"></circle><path d="M9.5 9.5l5 5M14 7h3v3"></path></svg>
                      </span>
                      <span>Find the hidden second-order impact</span>
                    </div>
                    <div class="georisk-value-item">
                      <span class="georisk-value-icon" aria-hidden="true">
                        <svg viewBox="0 0 24 24"><circle cx="5" cy="12" r="2"></circle><circle cx="12" cy="6" r="2"></circle><circle cx="19" cy="12" r="2"></circle><path d="M7 11l3.5-3.5M13.5 7.5L17 11M7 13h10"></path></svg>
                      </span>
                      <span>Follow the transmission chain step by step</span>
                    </div>
                    <div class="georisk-value-item">
                      <span class="georisk-value-icon" aria-hidden="true">
                        <svg viewBox="0 0 24 24"><path d="M6 3h9l3 3v15H6z"></path><path d="M14 3v4h4M9 13l2 2 4-5"></path></svg>
                      </span>
                      <span>Review the evidence faster</span>
                    </div>
                  </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        with input_column:
            with st.container(border=True, key="hero_input"):
                st.markdown(
                    '<div class="georisk-form-kicker">Start an analysis</div>'
                    '<div class="georisk-form-title">What event do you want to understand?</div>',
                    unsafe_allow_html=True,
                )
                with st.form("event_analysis_form", border=False):
                    custom_event = st.text_input(
                        "Event",
                        key="custom_event",
                        placeholder="e.g. Red Sea shipping disruption",
                        help="Name the geopolitical event, policy action, shock, or crisis you want to analyze.",
                    )
                    custom_context = st.text_area(
                        "Context (optional)",
                        key="custom_news_text",
                        height=92,
                        placeholder="Add one or two sentences to focus the analysis.",
                    )
                    submitted = st.form_submit_button(
                        "Analyze transmission risk  →",
                        type="primary",
                        use_container_width=True,
                    )
                    if submitted:
                        _handle_custom_event_submit(custom_event, custom_context)

    _render_example_gallery()
    _render_process_overview()
    _render_runtime_status()


def _render_example_gallery() -> None:
    """Render curated examples as clearly labeled sample-report cards."""

    st.markdown('<div class="georisk-step">Try the examples</div>', unsafe_allow_html=True)
    st.header("Explore a sample report")
    st.markdown(
        '<p class="georisk-section-intro">Start with a prepared scenario to see the complete report experience.</p>',
        unsafe_allow_html=True,
    )
    columns = st.columns(len(EXAMPLE_EVENTS))
    for index, (column, event) in enumerate(zip(columns, EXAMPLE_EVENTS, strict=False)):
        with column:
            with st.container(border=True, height=315, key=f"example_card_{index}"):
                st.markdown(
                    '<div class="georisk-example-copy">'
                    '<div class="georisk-example-label">Sample scenario</div>'
                    f'<h3>{html.escape(event["label"])}</h3>'
                    f'<p>{html.escape(event["description"])}</p>'
                    '</div>',
                    unsafe_allow_html=True,
                )
                if st.button(
                    "Open sample report  →",
                    key=f"example_{event['label']}",
                    use_container_width=True,
                ):
                    _analyze_and_open_report(
                        event["event"],
                        event["label"],
                        event_year=event.get("year"),
                        context=event.get("context"),
                        report_source="example",
                    )


def _render_process_overview() -> None:
    """Render a compact explanation of the analysis workflow."""

    st.markdown(
        """
        <section class="georisk-process">
          <div class="georisk-process-kicker">How GeoRisk works</div>
          <h2>How an event becomes a reviewable risk map</h2>
          <div class="georisk-process-grid">
            <article class="georisk-process-item">
              <div class="georisk-process-meta"><div class="georisk-process-number">01</div><div class="georisk-process-label">Input</div></div>
              <h3>Understand the event</h3>
              <p>Turn the headline into regions, industries, shocks, and direct exposure nodes.</p>
            </article>
            <article class="georisk-process-item">
              <div class="georisk-process-meta"><div class="georisk-process-number">02</div><div class="georisk-process-label">Ground</div></div>
              <h3>Find historical analogs</h3>
              <p>Retrieve past events that share a relevant geopolitical mechanism.</p>
            </article>
            <article class="georisk-process-item">
              <div class="georisk-process-meta"><div class="georisk-process-number">03</div><div class="georisk-process-label">Trace</div></div>
              <h3>Build the transmission chain</h3>
              <p>Follow the shock from direct impact into downstream supply-chain channels.</p>
            </article>
            <article class="georisk-process-item">
              <div class="georisk-process-meta"><div class="georisk-process-number">04</div><div class="georisk-process-label">Review</div></div>
              <h3>Map evidence to assets</h3>
              <p>Review candidate assets with their transmission path and evidence strength.</p>
            </article>
          </div>
        </section>
        """,
        unsafe_allow_html=True,
    )


def _handle_custom_event_submit(
    custom_event: str,
    custom_context: str,
) -> None:
    """Validate the custom event form and submit it to the API-backed analysis path."""

    event = custom_event.strip()
    if not event:
        st.warning("Enter an event to continue.")
        return
    _analyze_and_open_report(
        event,
        event,
        context=custom_context.strip() or None,
    )


def _analyze_and_open_report(
    event: str,
    event_label: str,
    *,
    event_year: int | None = None,
    context: str | None = None,
    report_source: str = "custom",
) -> None:
    """Request an analysis from the FastAPI backend and open the report page."""

    if not event.strip():
        st.warning("Please enter an event to analyze.")
        return

    with st.spinner("Analyzing risk transmission channels..."):
        try:
            st.session_state.report = _request_analysis(
                event,
                event_year=event_year,
                context=context,
            )
        except GeoRiskAPIClientError as exc:
            logger.warning(
                "GeoRisk frontend analysis request failed: status=%s message=%s",
                exc.status_code,
                exc.user_message,
            )
            st.session_state.service_error = exc.user_message
            st.rerun()
            return

        st.session_state.selected_event_label = event_label
        st.session_state.service_error = ""
        st.session_state.page = "report"
        st.session_state.report_section = "summary"
        st.session_state.report_source = report_source
        st.session_state.scroll_to_top = True
    st.rerun()


def _request_analysis(
    event: str,
    *,
    title: str | None = None,
    event_year: int | None = None,
    context: str | None = None,
) -> FinalReport:
    """Call the FastAPI production backend and parse a GeoRisk report."""

    payload: dict[str, object] = {"event": event}
    if title:
        payload["title"] = title
    if event_year is not None:
        payload["event_year"] = event_year
    if context:
        payload["context"] = context

    try:
        logger.info("GeoRisk Streamlit requesting analysis via FastAPI: %s/analyze", GEORISK_API_URL)
        response = requests.post(
            f"{GEORISK_API_URL}/analyze",
            json=payload,
            timeout=GEORISK_API_TIMEOUT_SECONDS,
        )
    except requests.Timeout as exc:
        raise GeoRiskAPIClientError(
            "The analysis is taking longer than expected. Please try again."
        ) from exc
    except requests.RequestException as exc:
        raise GeoRiskAPIClientError(
            "GeoRisk analysis service is temporarily unavailable. Please try again shortly."
        ) from exc

    if response.status_code == 422:
        raise GeoRiskAPIClientError(
            "Please enter a geopolitical event to analyze.",
            status_code=response.status_code,
        )
    if response.status_code == 503:
        raise GeoRiskAPIClientError(
            _api_detail_message(
                response,
                default="Historical-case retrieval is temporarily unavailable. Please try again later.",
            ),
            status_code=response.status_code,
        )
    if response.status_code >= 400:
        raise GeoRiskAPIClientError(
            "GeoRisk could not complete this analysis. Please try again.",
            status_code=response.status_code,
        )

    try:
        return FinalReport.model_validate(response.json())
    except Exception as exc:
        logger.exception("GeoRisk frontend could not parse API report response.")
        raise GeoRiskAPIClientError(
            "GeoRisk returned an unreadable report. Please try again."
        ) from exc


def _api_detail_message(response: requests.Response, *, default: str) -> str:
    """Return a safe API error detail if one is available."""

    try:
        payload = response.json()
    except ValueError:
        return default
    detail = payload.get("detail") if isinstance(payload, dict) else None
    if isinstance(detail, str):
        if "retrieval" in detail.lower() or "vector" in detail.lower():
            return "Historical-case retrieval is temporarily unavailable. Please try again later."
        return default
    if isinstance(detail, dict):
        vector = detail.get("vector_store")
        if isinstance(vector, dict) and vector.get("status") != "ready":
            return "Historical-case retrieval is temporarily unavailable. Please try again later."
    return default


def _render_runtime_status() -> None:
    """Render a subtle production-version indicator from the API."""

    version = _get_api_version()
    if version:
        production_version = version.get("production_version") or version.get("version", "V4")
        methodology_version = version.get("methodology_version", "V4")
        st.caption(
            f"{version.get('system', 'GeoRisk')} {production_version} · "
            f"{methodology_version} methodology · Production"
        )
    else:
        st.caption("GeoRisk V4 · Production backend unavailable")


def _render_service_status_message() -> None:
    """Render service-level backend failures outside individual event cards."""

    message = st.session_state.get("service_error", "")
    if message:
        st.error(message)


def _get_api_version() -> dict[str, object] | None:
    """Fetch safe API version metadata for display."""

    cache_key = "api_version"
    if cache_key in st.session_state:
        return st.session_state[cache_key]
    try:
        response = requests.get(
            f"{GEORISK_API_URL}/version",
            timeout=min(GEORISK_API_TIMEOUT_SECONDS, 10),
        )
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException:
        logger.info("GeoRisk frontend could not fetch API version metadata.")
        st.session_state[cache_key] = None
        return None
    st.session_state[cache_key] = payload
    return payload


def _render_report_page() -> None:
    """Render the report detail page."""

    report = st.session_state.report
    selected_event_label = st.session_state.get("selected_event_label", "Analyzed Event")

    header_left, header_right = st.columns([4, 1], vertical_alignment="bottom")
    with header_left:
        report_kicker = (
            "Sample report"
            if st.session_state.get("report_source") == "example"
            else "Analysis complete"
        )
        st.markdown(f'<div class="georisk-step">{report_kicker}</div>', unsafe_allow_html=True)
        st.title("GeoRisk Transmission Report")
        st.caption(selected_event_label)
    with header_right:
        if st.button("＋ New analysis", use_container_width=True):
            _start_new_analysis()

    _render_report_navigation()
    section = st.session_state.get("report_section", "summary")
    if section == "summary":
        _render_overview_tab(report)
    elif section == "watchlist":
        _render_watchlist_tab(report)
        _render_continue_button("transmission", "Continue to Transmission Path  →")
    elif section == "transmission":
        _render_transmission_chain_tab(report)
        _render_continue_button("evidence", "Continue to Historical Evidence  →")
    else:
        _render_historical_cases_tab(report)
        _render_report_end_actions()


def _start_new_analysis() -> None:
    """Return to a clean event form for a new analysis."""

    st.session_state.page = "home"
    st.session_state.report_section = "summary"
    st.session_state.custom_event = ""
    st.session_state.custom_news_text = ""
    st.session_state.scroll_to_top = True
    st.rerun()


def _render_report_end_actions() -> None:
    """Offer clear next actions at the end of the report journey."""

    st.divider()
    st.subheader("What would you like to do next?")
    back_column, new_column = st.columns(2)
    with back_column:
        if st.button("← Back to Overview", use_container_width=True):
            st.session_state.report_section = "summary"
            st.rerun()
    with new_column:
        if st.button("＋ Analyze another event", type="primary", use_container_width=True):
            _start_new_analysis()


def _render_report_navigation() -> None:
    """Render prominent report-section navigation buttons."""

    st.markdown(
        '<p class="georisk-report-nav-label">Explore the report</p>',
        unsafe_allow_html=True,
    )
    active_section = st.session_state.get("report_section", "summary")
    columns = st.columns(len(REPORT_SECTIONS))
    for column, (section, label) in zip(columns, REPORT_SECTIONS, strict=False):
        with column:
            if st.button(
                label,
                key=f"report_nav_{section}",
                type="primary" if section == active_section else "secondary",
                use_container_width=True,
            ):
                st.session_state.report_section = section
                st.rerun()


def _render_continue_button(section: str, label: str) -> None:
    """Render an explicit next-step button within the report journey."""

    st.divider()
    left, right = st.columns([2, 1])
    with left:
        st.caption(
            "Use the report navigation above at any time, or continue through the analysis in order."
        )
    with right:
        if st.button(label, key=f"continue_{section}", use_container_width=True):
            st.session_state.report_section = section
            st.rerun()


def _render_overview_tab(report) -> None:
    """Render event overview information."""

    title = getattr(report, "input_title", None) or report.event.title
    original_text = getattr(report, "original_event_text", None)
    normalized_text = getattr(report, "normalized_event_text", None)
    language = getattr(report, "input_language", None)
    normalization_applied = bool(getattr(report, "input_normalization_applied", False))

    st.markdown('<div class="georisk-step">Event summary</div>', unsafe_allow_html=True)
    st.markdown(f"## {title}")
    st.write(report.event.summary)

    event_metadata = []
    if getattr(report, "input_event_year", None):
        event_metadata.append(str(report.input_event_year))
    if getattr(report, "input_event_date", None):
        event_metadata.append(str(report.input_event_date))
    event_metadata.extend(
        [
            _event_type_label(report.event.event_type),
            ", ".join(report.event.regions) or "Unspecified region",
            ", ".join(report.event.industries) or "Unspecified industry",
        ]
    )
    st.caption(" · ".join(event_metadata))

    if original_text and language and language != "English":
        with st.expander("Original and normalized event text", expanded=False):
            st.markdown("**Original event**")
            st.write(original_text)
            if normalization_applied and normalized_text and normalized_text != original_text:
                st.markdown("**Normalized for analysis**")
                st.write(normalized_text)
            else:
                st.caption("English normalization was unavailable; GeoRisk analyzed the supplied text.")

    st.markdown("### What GeoRisk surfaced")
    _, second_order_nodes, _ = _partition_transmission_nodes(report)
    ranked_second, _, _ = _partition_watchlist_assets(report)
    with st.container(key="overview_previews"):
        transmission_column, watchlist_column = st.columns(2, gap="large")

        with transmission_column:
            with st.container(border=True, key="overview_transmission_preview"):
                st.caption("TRANSMISSION AT A GLANCE")
                st.markdown(f"**{_event_type_label(report.event.event_type)}**")
                st.markdown("↓")
                st.markdown(
                    "**Direct impact**  \n"
                    + _compact_node_list(report.event.supply_chain_nodes, limit=4)
                )
                st.markdown("↓")
                st.markdown(
                    "**Downstream channels**  \n"
                    + _compact_node_list(second_order_nodes, limit=4)
                )
            if st.button(
                "Explore the full transmission  →",
                key="overview_to_transmission",
                use_container_width=True,
            ):
                st.session_state.report_section = "transmission"
                st.rerun()

        with watchlist_column:
            with st.container(border=True, key="overview_watchlist_preview"):
                st.caption("SECOND-ORDER WATCHLIST")
                if ranked_second:
                    for asset in ranked_second[:3]:
                        st.markdown(f"**#{_rank_display(asset)} {asset.get('ticker') or 'n/a'}**")
                        st.caption(
                            f"{_format_node_title(str(asset.get('supply_chain_node') or ''))} · "
                            f"{_evidence_badge(asset.get('evidence_level'))}"
                        )
                    if len(ranked_second) > 3:
                        st.caption(f"+ {len(ranked_second) - 3} more exposure candidate(s)")
                else:
                    st.markdown("**No qualified second-order exposures**")
                    st.write("Direct exposure references are still available for context.")
            if st.button(
                "View the full watchlist  →",
                key="overview_to_watchlist",
                use_container_width=True,
            ):
                st.session_state.report_section = "watchlist"
                st.rerun()


def _compact_node_list(nodes: list[str], *, limit: int) -> str:
    """Return a compact readable node list with an overflow count."""

    if not nodes:
        return "None identified"
    labels = [_format_node_title(node) for node in nodes[:limit]]
    extra = len(nodes) - len(labels)
    if extra > 0:
        labels.append(f"+{extra} more")
    return " · ".join(labels)


def _render_historical_cases_tab(report) -> None:
    """Render retrieved historical case summaries."""

    st.subheader("Similar Historical Events")
    st.caption("Historical analogs ground the transmission analysis; they are not forecasts.")
    for case in report.retrieved_case_summaries[:5]:
        with st.container(border=True):
            st.markdown(f"**{case.get('event_name', 'Unknown case')}**")
            st.caption(_event_type_label(str(case.get("event_type", "unknown"))))
            st.write(case.get("summary", ""))


def _render_transmission_chain_tab(report) -> None:
    """Render transmission data as a readable risk path."""

    st.subheader("Transmission Chain")
    st.caption(
        "How the event moves from direct impact into secondary exposure channels."
    )

    first_order_nodes, second_order_nodes, other_nodes = _partition_transmission_nodes(report)
    direct_references = _reference_first_order_assets(report)
    ranked_by_node = _ranked_second_order_assets_by_node(report)

    flow = [
        (
            "Event Shock",
            _event_type_label(report.event.event_type),
            report.event.summary,
        ),
        (
            "Direct / First-Order Exposure",
            "Current-event exposure nodes",
            _format_node_list(first_order_nodes),
        ),
        (
            "Direct-Exposure Reference Assets",
            "Reference anchors — not ranked",
            _direct_reference_asset_summary(direct_references),
        ),
        (
            "Transmission / Spillover",
            "Existing chain language",
            _format_chain_mechanisms(report.transmission_chain.chain_steps),
        ),
        (
            "Secondary Exposure Channels",
            "Case-grounded downstream nodes",
            _secondary_channel_summary(second_order_nodes, ranked_by_node),
        ),
    ]

    for index, (label, eyebrow, body) in enumerate(flow):
        with st.container(border=True):
            st.caption(eyebrow)
            st.markdown(f"**{label}**")
            st.markdown(str(body))
        if index < len(flow) - 1:
            st.markdown("<div style='text-align:center; font-size: 1.25rem;'>↓</div>", unsafe_allow_html=True)

    evidence_notes = _transmission_evidence_notes(report, second_order_nodes)
    if evidence_notes or other_nodes:
        with st.expander("Evidence supporting the transmission"):
            for note in evidence_notes:
                st.markdown(f"- {note}")
            if other_nodes:
                st.markdown(f"- Other affected nodes: {_format_node_list(other_nodes)}")

def _render_watchlist_tab(report) -> None:
    """Render the two-layer asset report."""

    st.subheader("Asset Watchlist")
    st.caption(
        "Direct exposures provide the baseline; GeoRisk's ranked output focuses "
        "on historically supported downstream risk transmission."
    )
    _render_evidence_guide()

    ranked_second, direct_references, unclassified = _partition_watchlist_assets(report)
    if unclassified:
        logger.warning("Omitting %s unclassified assets from ranked Watchlist.", len(unclassified))

    st.markdown("### Ranked Second-Order Exposures")
    st.caption("Differentiated downstream exposure candidates surfaced through historical transmission patterns.")
    if not ranked_second:
        _render_empty_second_order_state()
    else:
        st.caption(f"{len(ranked_second)} ranked exposure candidate(s)")
        _render_asset_table(ranked_second, show_rank=True, include_transmission=False)
        _render_second_order_explainers(ranked_second, report)

    st.markdown("### Direct Exposure References")
    st.caption(
        "Assets mapped to the event's direct exposure nodes. Shown as context, "
        "not ranked."
    )
    if direct_references:
        _render_direct_reference_groups(direct_references)
    else:
        st.write("No direct exposure reference assets are available in this report.")
    _render_watchlist_disclaimer()


def _render_evidence_guide() -> None:
    """Explain the three user-facing evidence tiers before showing assets."""

    st.markdown("#### How to read the evidence colors")
    columns = st.columns(len(EVIDENCE_GUIDE))
    for column, (label, description) in zip(columns, EVIDENCE_GUIDE, strict=False):
        with column:
            with st.container(border=True, height=165):
                st.markdown(f"**{label}**")
                st.caption(description)


def _render_watchlist_disclaimer() -> None:
    """Render the report scope as quiet supporting copy on the results page."""

    st.divider()
    st.caption(REPORT_FOOTER_DISCLAIMER)


def _format_nodes(nodes: list[str]) -> str:
    """Format normalized nodes as readable labels."""

    if not nodes:
        return "unspecified"
    return ", ".join(_format_node(node) for node in nodes)


def _format_node(node: str | None) -> str:
    """Format a single normalized node as a readable label."""

    if not node:
        return "unspecified"
    return NODE_LABELS.get(node, node.replace("_", " "))


def _format_node_title(node: str | None) -> str:
    """Format a node for table display without mutating backend data."""

    if not node:
        return "Unspecified"
    if node in NODE_LABELS:
        return _title_label(NODE_LABELS[node])
    return _title_label(node.replace("_", " "))


def _title_label(label: str) -> str:
    """Title-case display labels while preserving acronyms."""

    return " ".join(word if word.isupper() else word.capitalize() for word in label.split())


def _event_type_label(event_type: str) -> str:
    """Format normalized event types as readable labels."""

    return EVENT_TYPE_LABELS.get(event_type, event_type.replace("_", " ").title())


def _all_watchlist_assets(report) -> list[dict[str, object]]:
    """Return watchlist rows from current or legacy grouped reports."""

    watchlist = getattr(report, "secondary_asset_watchlist", {}) or {}
    assets: list[dict[str, object]] = []
    for evidence_level, value in watchlist.items():
        if isinstance(value, list):
            for asset in value:
                if not isinstance(asset, dict):
                    continue
                row = dict(asset)
                row.setdefault("evidence_level", evidence_level)
                assets.append(row)
    if assets:
        return assets

    for result in getattr(report, "evidence_results", []) or []:
        if hasattr(result, "model_dump"):
            row = result.model_dump()
            asset = row.get("asset") if isinstance(row.get("asset"), dict) else {}
            row.setdefault("asset_name", asset.get("asset_name") or asset.get("name"))
            row.setdefault("supply_chain_node", asset.get("supply_chain_node"))
            assets.append(row)
    return assets


def _normalize_scope(scope: object) -> str:
    """Normalize ranking-scope labels without inferring missing values."""

    return str(scope or "").strip().lower().replace(" ", "_").replace("-", "_")


def _partition_watchlist_assets(report) -> tuple[list[dict[str, object]], list[dict[str, object]], list[dict[str, object]]]:
    """Partition assets by explicit ranking scope."""

    ranked_second: list[dict[str, object]] = []
    direct_references: list[dict[str, object]] = []
    unclassified: list[dict[str, object]] = []

    for asset in _all_watchlist_assets(report):
        scope = _normalize_scope(asset.get("ranking_scope"))
        if scope == "ranked_second_order":
            ranked_second.append(asset)
        elif scope == "reference_first_order":
            direct_references.append(asset)
        else:
            unclassified.append(asset)

    ranked_second.sort(key=lambda asset: (_rank_sort_value(asset), str(asset.get("ticker") or "")))
    direct_references.sort(key=lambda asset: (_evidence_sort_value(asset), str(asset.get("ticker") or "")))
    unclassified.sort(key=lambda asset: (_rank_sort_value(asset), str(asset.get("ticker") or "")))
    return ranked_second, direct_references, unclassified


def _rank_sort_value(asset: dict[str, object]) -> int:
    """Return a stable integer rank sort value."""

    rank = asset.get("rank_within_order") or asset.get("rank")
    try:
        return int(rank)
    except (TypeError, ValueError):
        return 10_000


def _evidence_sort_value(asset: dict[str, object]) -> int:
    """Sort stronger evidence first without changing backend labels."""

    order = {
        "historical_supported": 0,
        "sector_proxy": 1,
        "inference_only": 2,
    }
    return order.get(str(asset.get("evidence_level") or ""), 3)


def _render_asset_table(
    assets: list[dict[str, object]],
    *,
    show_rank: bool,
    include_transmission: bool = True,
) -> None:
    """Render a compact asset table for the watchlist."""

    if not assets:
        st.write("No assets to display.")
        return

    st.dataframe(
        _asset_table_rows(
            assets,
            show_rank=show_rank,
            include_transmission=include_transmission,
        ),
        hide_index=True,
        use_container_width=True,
    )


def _asset_table_rows(
    assets: list[dict[str, object]],
    *,
    show_rank: bool,
    include_transmission: bool = True,
) -> list[dict[str, object]]:
    """Return compact table rows for ranked or direct-reference assets."""

    rows = []
    for asset in assets:
        row = {
            "Ticker": asset.get("ticker") or "n/a",
            "Asset": asset.get("asset_name") or asset.get("asset") or "Unknown asset",
            "Exposure Channel": _format_node_title(str(asset.get("supply_chain_node") or asset.get("exposure_node") or "")),
            "Evidence": _evidence_badge(asset.get("evidence_level")),
        }
        if include_transmission:
            row["Transmission"] = _format_transmission_order(
                str(asset.get("transmission_order") or asset.get("transmission") or "")
            )
        if show_rank:
            row = {"Rank": _rank_display(asset), **row}
        rows.append(row)
    return rows


def _render_direct_reference_groups(assets: list[dict[str, object]]) -> None:
    """Render direct references as compact grouped node rows."""

    groups = _direct_reference_groups(assets)
    visible_groups = groups[:DIRECT_REFERENCE_INITIAL_GROUPS]
    hidden_groups = groups[DIRECT_REFERENCE_INITIAL_GROUPS:]

    for group in visible_groups:
        _render_direct_reference_group_row(group)

    if hidden_groups:
        with st.expander("Show all direct exposure references", expanded=False):
            for group in hidden_groups:
                _render_direct_reference_group_row(group)

    with st.expander("Direct reference details", expanded=False):
        for group in groups:
            st.markdown(f"**{group['node_label']}**")
            for asset in group["assets"]:
                st.markdown(
                    "- "
                    f"{asset.get('ticker') or 'n/a'} - "
                    f"{asset.get('asset_name') or asset.get('asset') or 'Unknown asset'} "
                    f"({_evidence_badge(asset.get('evidence_level'))})"
                )


def _render_direct_reference_group_row(group: dict[str, object]) -> None:
    """Render one compact direct-reference node group."""

    left, right = st.columns([1, 3])
    with left:
        st.markdown(f"**{group['node_label']}**")
    with right:
        st.markdown(str(group["ticker_text"]))


def _direct_reference_groups(
    assets: list[dict[str, object]],
) -> list[dict[str, object]]:
    """Group direct-reference assets by exposure node for compact display."""

    grouped: dict[str, list[dict[str, object]]] = {}
    for asset in assets:
        node = str(asset.get("supply_chain_node") or asset.get("exposure_node") or "unspecified")
        grouped.setdefault(node, []).append(asset)

    groups: list[dict[str, object]] = []
    for node, node_assets in grouped.items():
        ordered_assets = sorted(
            node_assets,
            key=lambda asset: (
                _evidence_sort_value(asset),
                str(asset.get("ticker") or ""),
            ),
        )
        tickers = [
            str(asset.get("ticker") or "n/a")
            for asset in ordered_assets
        ]
        groups.append(
            {
                "node": node,
                "node_label": _format_node_title(node),
                "ticker_text": " · ".join(dict.fromkeys(tickers)),
                "assets": ordered_assets,
            }
        )

    groups.sort(key=lambda group: str(group["node_label"]))
    return groups


def _render_empty_second_order_state() -> None:
    """Render a valid analytical-abstention state for the Watchlist."""

    with st.container(border=True):
        st.markdown(f"**{SECOND_ORDER_EMPTY_STATE_TITLE}**")
        st.write(SECOND_ORDER_EMPTY_STATE_BODY)
        st.caption("Review Direct Exposure References below for baseline context.")


def _render_second_order_explainers(assets: list[dict[str, object]], report) -> None:
    """Render explainability expanders for ranked second-order assets."""

    if not assets:
        return

    st.markdown("#### How Each Exposure Reaches the Asset")
    for asset in assets:
        label = (
            f"#{_rank_display(asset)} {asset.get('ticker') or 'n/a'} — "
            f"{asset.get('asset_name') or asset.get('asset') or 'Unknown asset'}"
        )
        with st.expander(label):
            st.markdown(f"**Evidence:** {_evidence_badge(asset.get('evidence_level'))}")
            st.markdown("**Transmission path**")
            for step_number, (step_label, step_value) in enumerate(
                _asset_transmission_path_steps(asset, report),
                start=1,
            ):
                st.markdown(f"{step_number}. **{step_label}** — {step_value}")
            _render_supporting_cases(asset, report)


def _asset_transmission_path_steps(
    asset: dict[str, object],
    report,
) -> list[tuple[str, str]]:
    """Build a readable event-to-asset path from existing report evidence."""

    event_title = getattr(report, "input_title", None) or report.event.title
    direct_nodes = _format_node_list(report.event.supply_chain_nodes)
    chain_steps = [
        _format_node_title(step) if _looks_like_enum(step) else step
        for step in (getattr(report.transmission_chain, "chain_steps", []) or [])
        if step
    ]
    mechanism = " → ".join(dict.fromkeys(chain_steps[:4]))
    channel = _format_node_title(
        str(asset.get("supply_chain_node") or asset.get("exposure_node") or "")
    )
    ticker = str(asset.get("ticker") or "n/a")
    asset_name = str(asset.get("asset_name") or asset.get("asset") or "Unknown asset")

    steps = [
        ("Current event", str(event_title)),
        ("Direct impact", direct_nodes),
    ]
    if mechanism:
        steps.append(("Spillover mechanism", mechanism))
    steps.extend(
        [
            ("Downstream exposure channel", channel),
            ("Mapped asset", f"{ticker} — {asset_name}"),
        ]
    )
    return steps


def _render_supporting_cases(asset: dict[str, object], report) -> None:
    """Render supporting historical case metadata when present."""

    st.markdown("**Historical events supporting this path**")
    case_titles = _case_title_lookup(report)
    details = asset.get("supporting_case_details")
    if isinstance(details, list) and details:
        for detail in details:
            if not isinstance(detail, dict):
                continue
            case_id = detail.get("case_id") or "unknown_case"
            title = detail.get("title") or detail.get("event_name") or case_titles.get(str(case_id))
            if title:
                st.markdown(f"- {title}")
        return

    case_ids = asset.get("supporting_case_ids")
    if isinstance(case_ids, list) and case_ids:
        for case_id in case_ids:
            title = case_titles.get(str(case_id))
            if title:
                st.markdown(f"- {title}")
        return

    st.markdown("- No named supporting historical events are available in this report.")


def _case_title_lookup(report) -> dict[str, str]:
    """Return case titles from report metadata when available."""

    lookup: dict[str, str] = {}
    for case in getattr(report, "retrieved_case_summaries", []) or []:
        if isinstance(case, dict) and case.get("case_id") and case.get("event_name"):
            lookup[str(case["case_id"])] = str(case["event_name"])
    for case in getattr(report, "retrieved_cases", []) or []:
        case_id = getattr(case, "case_id", None)
        title = getattr(case, "title", None)
        if case_id and title:
            lookup[str(case_id)] = str(title)
    return lookup


def _evidence_badge(evidence_level: object) -> str:
    """Return a human-readable evidence badge."""

    level = str(evidence_level or "").strip().lower()
    return EVIDENCE_LABELS.get(level, _format_priority_tier(level) if level else "⚪ Unknown")


def _rank_display(asset: dict[str, object]) -> str:
    """Display rank only when the backend provided one."""

    rank = asset.get("rank_within_order") or asset.get("rank")
    return str(rank) if rank not in {None, ""} else "—"


def _partition_transmission_nodes(report) -> tuple[list[str], list[str], list[str]]:
    """Partition affected nodes using backend node evidence tiers."""

    evidence_levels = getattr(report.transmission_chain, "node_evidence_levels", {}) or {}
    affected_nodes = getattr(report.transmission_chain, "affected_nodes", []) or []
    first_order = [node for node in affected_nodes if evidence_levels.get(node) == "event_node"]
    second_order = [node for node in affected_nodes if evidence_levels.get(node) == "case_grounded"]
    known = set(first_order) | set(second_order)
    other = [node for node in affected_nodes if node not in known]
    return first_order, second_order, other


def _format_node_list(nodes: list[str]) -> str:
    """Format a node list for display."""

    if not nodes:
        return "None identified in this report"
    return ", ".join(_format_node_title(node) for node in nodes)


def _format_chain_mechanisms(chain_steps: list[str]) -> str:
    """Display existing chain steps as mechanism text, excluding raw enum-like noise."""

    if not chain_steps:
        return "No chain steps available in this report"
    readable_steps = [
        step
        for step in chain_steps
        if step and not _looks_like_enum(step)
    ]
    if not readable_steps:
        readable_steps = chain_steps[:3]
    formatted = [_format_chain_step(step) for step in readable_steps[:4]]
    if len(formatted) == 1:
        return f"- {formatted[0]}"
    return "\n".join(f"- {step}" for step in formatted)


def _format_chain_step(step: str) -> str:
    """Format one existing chain step for display."""

    if _looks_like_enum(step):
        return step.replace("_", " ")
    return step


def _looks_like_enum(value: str) -> bool:
    """Return true for short normalized enum/node labels."""

    return "_" in value and len(value.split()) == 1 and len(value) < 60


def _ranked_asset_summary(report) -> str:
    """Summarize ranked second-order assets without inventing outputs."""

    ranked_second, _, _ = _partition_watchlist_assets(report)
    if not ranked_second:
        return "No ranked second-order assets in this report"
    labels = [
        f"#{_rank_display(asset)} {asset.get('ticker') or 'n/a'}"
        for asset in ranked_second[:5]
    ]
    extra = len(ranked_second) - len(labels)
    if extra > 0:
        labels.append(f"+{extra} more")
    return ", ".join(labels)


def _reference_first_order_assets(report) -> list[dict[str, object]]:
    """Return direct first-order reference assets for explanation only."""

    _, direct_references, _ = _partition_watchlist_assets(report)
    return direct_references


def _direct_reference_asset_summary(assets: list[dict[str, object]]) -> str:
    """Group direct-reference assets by exposure node without ranking them."""

    if not assets:
        return "No direct-reference assets are available in this report."
    grouped: dict[str, list[str]] = {}
    for asset in assets:
        node = str(asset.get("supply_chain_node") or asset.get("exposure_node") or "unspecified")
        grouped.setdefault(node, []).append(_asset_ticker(asset))

    lines = []
    for node, tickers in sorted(grouped.items()):
        unique_tickers = sorted(dict.fromkeys(tickers))
        lines.append(f"**{_format_node_title(node)}**\n" + " · ".join(unique_tickers[:8]))
    return "\n\n".join(lines)


def _ranked_second_order_assets_by_node(report) -> dict[str, list[dict[str, object]]]:
    """Group ranked second-order assets by their exposure channel."""

    ranked_second, _, _ = _partition_watchlist_assets(report)
    grouped: dict[str, list[dict[str, object]]] = {}
    for asset in ranked_second:
        node = str(asset.get("supply_chain_node") or asset.get("exposure_node") or "unknown")
        grouped.setdefault(node, []).append(asset)
    return grouped


def _secondary_channel_summary(
    second_order_nodes: list[str],
    ranked_by_node: dict[str, list[dict[str, object]]],
) -> str:
    """Summarize secondary channels and related ranked tickers."""

    if not second_order_nodes:
        return "No case-grounded secondary exposure channels were accepted in this report."
    lines = []
    for node in second_order_nodes:
        tickers = [_asset_ticker(asset) for asset in ranked_by_node.get(node, [])[:4]]
        suffix = f" -> {' · '.join(tickers)}" if tickers else ""
        lines.append(f"{_format_node_title(node)}{suffix}")
    return "\n".join(lines)


def _asset_ticker(asset: dict[str, object]) -> str:
    """Return a display ticker for an asset row."""

    return str(asset.get("ticker") or "n/a")


def _transmission_evidence_notes(report, second_order_nodes: list[str]) -> list[str]:
    """Return evidence notes derived from existing transmission metadata."""

    notes: list[str] = []
    case_titles = _case_title_lookup(report)
    support_map = getattr(report.transmission_chain, "node_supporting_case_ids", {}) or {}
    for node in second_order_nodes:
        case_ids = support_map.get(node, [])
        if case_ids:
            titles = [case_titles[str(case_id)] for case_id in case_ids if str(case_id) in case_titles]
            if titles:
                notes.append(
                    f"{_format_node_title(node)} supported by: "
                    + "; ".join(dict.fromkeys(titles[:5]))
                )
            else:
                notes.append(f"{_format_node_title(node)} has compatible historical support.")
    supporting_case_ids = getattr(report.transmission_chain, "supporting_case_ids", []) or []
    if supporting_case_ids and not notes:
        titles = [
            case_titles[str(case_id)]
            for case_id in supporting_case_ids
            if str(case_id) in case_titles
        ]
        if titles:
            notes.append("Supporting historical analogs: " + "; ".join(dict.fromkeys(titles[:6])))
        else:
            notes.append("Compatible historical analogs support this transmission path.")
    return notes


def _format_priority_tier(priority_tier: str | None) -> str:
    """Format priority tiers for table display."""

    if not priority_tier:
        return "Unranked"
    return priority_tier.replace("_", " ").title()


def _format_transmission_order(transmission_order: str | None) -> str:
    """Format transmission-order labels for table display."""

    labels = {
        "first_order": "First Order",
        "second_order": "Second Order",
        "unmapped": "Unmapped",
    }
    return labels.get(transmission_order or "", "Unknown")


if __name__ == "__main__":
    main()
