"""Streamlit app for GeoRisk Transmission Analyzer."""

import logging

import requests
import streamlit as st

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
    ("summary", "1 · Summary"),
    ("watchlist", "2 · Asset Watchlist"),
    ("transmission", "3 · Transmission Path"),
    ("evidence", "4 · Historical Evidence"),
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
            --georisk-muted: #607086;
            --georisk-blue: #2457e6;
            --georisk-blue-dark: #173ba6;
            --georisk-soft: #f4f7fc;
            --georisk-line: #dfe6f1;
        }
        .stApp {
            background:
                radial-gradient(circle at 92% 4%, rgba(36, 87, 230, 0.08), transparent 24rem),
                #ffffff;
            color: var(--georisk-ink);
        }
        .block-container {
            max-width: 1180px;
            padding-top: 2.2rem;
            padding-bottom: 4rem;
        }
        h1, h2, h3 { letter-spacing: -0.025em; }
        .georisk-hero {
            padding: 2.7rem 3rem;
            border: 1px solid var(--georisk-line);
            border-radius: 24px;
            background: linear-gradient(135deg, #f8faff 0%, #eef3ff 55%, #f8fbff 100%);
            box-shadow: 0 20px 50px rgba(27, 49, 92, 0.08);
            margin-bottom: 1.5rem;
        }
        .georisk-eyebrow {
            color: var(--georisk-blue);
            font-size: 0.78rem;
            font-weight: 750;
            letter-spacing: 0.12em;
            text-transform: uppercase;
            margin-bottom: 0.8rem;
        }
        .georisk-hero h1 {
            color: var(--georisk-ink);
            font-size: clamp(2.2rem, 5vw, 4.25rem);
            line-height: 1.02;
            max-width: 850px;
            margin: 0 0 1rem;
        }
        .georisk-hero p {
            color: var(--georisk-muted);
            font-size: 1.1rem;
            line-height: 1.7;
            max-width: 790px;
            margin: 0;
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
        .georisk-footer-note {
            color: var(--georisk-muted);
            font-size: 0.82rem;
            text-align: center;
            padding-top: 1.2rem;
        }
        .georisk-why {
            position: relative;
            overflow: hidden;
            margin-top: 3rem;
            padding: 3.2rem;
            border-radius: 26px;
            background:
                radial-gradient(circle at 88% 5%, rgba(90, 127, 255, 0.38), transparent 22rem),
                linear-gradient(145deg, #111a31 0%, #182443 58%, #10182c 100%);
            box-shadow: 0 24px 60px rgba(15, 28, 58, 0.2);
            color: #ffffff;
        }
        .georisk-why-kicker {
            color: #91adff;
            font-size: 0.76rem;
            font-weight: 800;
            letter-spacing: 0.14em;
            text-transform: uppercase;
        }
        .georisk-why h2 {
            color: #ffffff;
            font-size: clamp(2rem, 4vw, 3.35rem);
            line-height: 1.08;
            max-width: 800px;
            margin: 0.8rem 0 1rem;
        }
        .georisk-why-lead {
            color: #c3cee6;
            font-size: 1.03rem;
            line-height: 1.65;
            max-width: 790px;
            margin: 0 0 2rem;
        }
        .georisk-why-grid {
            display: grid;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            gap: 1rem;
        }
        .georisk-why-card {
            position: relative;
            min-height: 170px;
            padding: 1.4rem;
            border: 1px solid rgba(255, 255, 255, 0.15);
            border-radius: 17px;
            background: rgba(255, 255, 255, 0.07);
            backdrop-filter: blur(8px);
        }
        .georisk-why-number {
            color: #91adff;
            font-size: 0.75rem;
            font-weight: 800;
            letter-spacing: 0.12em;
        }
        .georisk-why-card h3 {
            color: #ffffff;
            font-size: 1.42rem;
            line-height: 1.25;
            margin: 2.3rem 0 0;
        }
        .georisk-why-flow {
            margin-top: 1.2rem;
            padding: 0.9rem 1rem;
            border: 1px solid rgba(145, 173, 255, 0.25);
            border-radius: 12px;
            background: rgba(9, 15, 30, 0.35);
            color: #dce5fa;
            font-size: 0.84rem;
            font-weight: 650;
            letter-spacing: 0.02em;
            text-align: center;
        }
        @media (max-width: 720px) {
            .block-container { padding-top: 1rem; }
            .georisk-hero { padding: 1.8rem 1.4rem; border-radius: 18px; }
            .georisk-hero h1 { font-size: 2.35rem; }
            .georisk-why { padding: 2rem 1.3rem; border-radius: 20px; }
            .georisk-why-grid { grid-template-columns: 1fr; }
            .georisk-why-card { min-height: 125px; }
            .georisk-why-card h3 { margin-top: 1.4rem; }
            .georisk-why-flow { line-height: 1.8; }
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


def _render_home_page() -> None:
    """Render the event dashboard home page."""

    _render_service_status_message()

    st.markdown(
        """
        <section class="georisk-hero">
          <div class="georisk-eyebrow">Geopolitical risk intelligence</div>
          <h1>See where a geopolitical shock travels next.</h1>
          <p>GeoRisk turns an event into a reviewable transmission map—connecting
          direct impact, historical analogs, downstream exposure channels, and
          evidence-qualified assets.</p>
        </section>
        """,
        unsafe_allow_html=True,
    )

    st.markdown('<div class="georisk-step">01 · Start an analysis</div>', unsafe_allow_html=True)
    st.header("What event do you want to understand?")
    st.markdown(
        '<p class="georisk-section-intro">Enter a conflict, policy action, trade restriction, supply shock, or logistics disruption. A short headline is enough.</p>',
        unsafe_allow_html=True,
    )
    with st.form("event_analysis_form", border=True):
        custom_event = st.text_input(
            "Event",
            key="custom_event",
            placeholder="e.g. Red Sea shipping disruption",
            help="Name the geopolitical event, policy action, shock, or crisis you want to analyze.",
        )
        custom_context = st.text_area(
            "Context (optional)",
            key="custom_news_text",
            height=100,
            placeholder="Add one or two sentences if you want GeoRisk to focus on a specific development.",
            help=(
                "Add one or two sentences if the event name alone is ambiguous "
                "or if you want GeoRisk to focus on a specific development."
            ),
        )
        submitted = st.form_submit_button(
            "Analyze transmission risk  →",
            type="primary",
            use_container_width=True,
        )
        if submitted:
            _handle_custom_event_submit(custom_event, custom_context)

    st.markdown('<div class="georisk-step">02 · Or explore an example</div>', unsafe_allow_html=True)
    st.header("See GeoRisk in action")
    columns = st.columns(len(EXAMPLE_EVENTS))
    for index, (column, event) in enumerate(zip(columns, EXAMPLE_EVENTS, strict=False)):
        with column:
            with st.container(border=True, height=265, key=f"example_card_{index}"):
                st.subheader(event["label"])
                st.write(event["description"])
                if st.button(
                    f"Analyze example  →",
                    key=f"example_{event['label']}",
                    use_container_width=True,
                ):
                    _analyze_and_open_report(
                        event["event"],
                        event["label"],
                        event_year=event.get("year"),
                        context=event.get("context"),
                    )

    _render_why_georisk()
    _render_runtime_status()


def _render_why_georisk() -> None:
    """Explain the product value once on the home page."""

    st.markdown(
        """
        <section class="georisk-why">
          <div class="georisk-why-kicker">Why GeoRisk</div>
          <h2>See what the headline leaves below the surface.</h2>
          <p class="georisk-why-lead">The obvious market impact is only the starting point.
          GeoRisk follows the shock further—showing how risk moves through supply chains,
          reaches downstream exposure channels, and connects to reviewable assets.</p>
          <div class="georisk-why-grid">
            <article class="georisk-why-card">
              <div class="georisk-why-number">01</div>
              <h3>Discover the hidden second-order impact</h3>
            </article>
            <article class="georisk-why-card">
              <div class="georisk-why-number">02</div>
              <h3>Follow the transmission chain</h3>
            </article>
            <article class="georisk-why-card">
              <div class="georisk-why-number">03</div>
              <h3>Review the evidence faster</h3>
            </article>
          </div>
          <div class="georisk-why-flow">Headline &nbsp;→&nbsp; Direct shock &nbsp;→&nbsp; Transmission channels &nbsp;→&nbsp; Evidence-backed watchlist</div>
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
        st.markdown('<div class="georisk-step">Analysis complete</div>', unsafe_allow_html=True)
        st.title("GeoRisk Transmission Report")
        st.caption(selected_event_label)
    with header_right:
        if st.button("＋ New analysis", use_container_width=True):
            _start_new_analysis()

    _render_report_navigation()
    section = st.session_state.get("report_section", "summary")
    if section == "summary":
        _render_overview_tab(report)
        _render_continue_button("watchlist", "Continue to Asset Watchlist  →")
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
    st.rerun()


def _render_report_end_actions() -> None:
    """Offer clear next actions at the end of the report journey."""

    st.divider()
    st.subheader("What would you like to do next?")
    back_column, new_column = st.columns(2)
    with back_column:
        if st.button("← Back to Summary", use_container_width=True):
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
        if st.button(label, key=f"continue_{section}", type="primary", use_container_width=True):
            st.session_state.report_section = section
            st.rerun()


def _render_overview_tab(report) -> None:
    """Render event overview information."""

    title = getattr(report, "input_title", None) or report.event.title
    original_text = getattr(report, "original_event_text", None)
    normalized_text = getattr(report, "normalized_event_text", None)
    language = getattr(report, "input_language", None)
    normalization_applied = bool(getattr(report, "input_normalization_applied", False))

    st.subheader("Event Summary")
    st.markdown(f"### {title}")
    st.write(report.event.summary)

    if original_text and language and language != "English":
        with st.expander("Original and normalized event text", expanded=False):
            st.markdown("**Original event**")
            st.write(original_text)
            if normalization_applied and normalized_text and normalized_text != original_text:
                st.markdown("**Normalized for analysis**")
                st.write(normalized_text)
            else:
                st.caption("English normalization was unavailable; GeoRisk analyzed the supplied text.")

    st.subheader("Event Classification")
    overview_rows = [
        ("Event type", _event_type_label(report.event.event_type)),
        ("Regions", ", ".join(report.event.regions) or "Unspecified"),
        ("Industries", ", ".join(report.event.industries) or "Unspecified"),
        ("Shock direction", _format_node_title(report.event.shock_direction)),
        ("Direct exposure nodes", _format_nodes(report.event.supply_chain_nodes)),
    ]
    columns = st.columns(2)
    for index, (label, value) in enumerate(overview_rows):
        with columns[index % 2]:
            st.markdown(f"**{label}**")
            st.write(value)

    event_metadata = []
    if getattr(report, "input_event_year", None):
        event_metadata.append(f"Event year: {report.input_event_year}")
    if getattr(report, "input_event_date", None):
        event_metadata.append(f"Event date: {report.input_event_date}")
    if event_metadata:
        st.caption(" · ".join(event_metadata))

    with st.expander("Normalized event summary", expanded=False):
        st.write(report.event_summary)


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
