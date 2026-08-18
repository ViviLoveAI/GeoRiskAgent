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
SECOND_ORDER_EMPTY_STATE_TITLE = "No qualified second-order exposures identified"
SECOND_ORDER_EMPTY_STATE_BODY = (
    "GeoRisk identified direct exposure channels for this event, but no "
    "secondary assets met the current V4 historical-support and transmission "
    "requirements. Direct exposures remain available in the Transmission Chain "
    "as reference anchors."
)
REPORT_TAB_LABELS = [
    "Overview",
    "Asset Watchlist",
    "Transmission Chain",
    "Historical Cases",
]
DIRECT_REFERENCE_INITIAL_GROUPS = 6
REPORT_FOOTER_DISCLAIMER = (
    "GeoRisk surfaces market-risk exposure candidates from historical analogs. "
    "Outputs are not price forecasts, market probabilities, trading signals, "
    "or investment advice."
)
METHODOLOGY_LIMITATIONS = [
    "Evidence levels describe historical/evidential support strength.",
    "Retrieved historical cases are analogs, not forecasts.",
    "Mapped assets are risk-watchlist candidates, not trading signals.",
    (
        "Evidence scores are not expected-return estimates or probabilities "
        "of price movement."
    ),
]


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
        layout="wide",
    )
    _initialize_state()

    if st.session_state.page == "report" and "report" in st.session_state:
        _render_report_page()
    else:
        _render_home_page()


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


def _render_home_page() -> None:
    """Render the event dashboard home page."""

    _render_runtime_status()
    _render_service_status_message()

    st.title("GeoRisk Transmission Analyzer")
    st.markdown(
        "GeoRisk maps direct market exposures to geopolitical events and "
        "surfaces historically grounded second-order transmission risks."
    )
    st.caption("Risk watchlist generation only. Not price prediction or investment advice.")

    st.header("Try an example")
    columns = st.columns(len(EXAMPLE_EVENTS))
    for column, event in zip(columns, EXAMPLE_EVENTS, strict=False):
        with column:
            with st.container(border=True):
                st.subheader(event["label"])
                st.write(event["description"])
                if st.button(f"Analyze {event['label']}", key=f"example_{event['label']}"):
                    _analyze_and_open_report(
                        event["event"],
                        event["label"],
                        event_year=event.get("year"),
                        context=event.get("context"),
                    )

    st.header("Analyze an Event")
    custom_event = st.text_input(
        "Event *",
        key="custom_event",
        placeholder="Red Sea Shipping Disruption",
        help="Name the geopolitical event, policy action, shock, or crisis you want to analyze.",
    )
    with st.expander("Add context (optional)", expanded=False):
        custom_context = st.text_area(
            "Additional Context",
            key="custom_news_text",
            height=110,
            placeholder="Several carriers are rerouting around the Cape of Good Hope as regional security risks increase.",
            help=(
                "Add one or two sentences if the event name alone is ambiguous "
                "or if you want GeoRisk to focus on a specific development."
            ),
        )
    if st.button("Analyze Risk Transmission", type="primary"):
        _handle_custom_event_submit(custom_event, custom_context)


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

    if st.button("← Back to Event Dashboard"):
        st.session_state.page = "home"
        st.rerun()

    report = st.session_state.report
    selected_event_label = st.session_state.get("selected_event_label", "Analyzed Event")

    st.title("GeoRisk Transmission Report")
    st.caption(selected_event_label)

    overview_tab, watchlist_tab, chain_tab, cases_tab = st.tabs(REPORT_TAB_LABELS)

    with overview_tab:
        _render_overview_tab(report)
    with cases_tab:
        _render_historical_cases_tab(report)
    with chain_tab:
        _render_transmission_chain_tab(report)
    with watchlist_tab:
        _render_watchlist_tab(report)
    _render_report_footer(report)


def _render_overview_tab(report) -> None:
    """Render event overview information."""

    st.subheader("What GeoRisk Understood")
    title = getattr(report, "input_title", None) or report.event.title
    st.markdown(f"### {title}")
    if getattr(report, "input_event_year", None):
        st.caption(f"Event year: {report.input_event_year}")
    if getattr(report, "input_event_date", None):
        st.caption(f"Event date: {report.input_event_date}")

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

    original_text = getattr(report, "original_event_text", None)
    normalized_text = getattr(report, "normalized_event_text", None)
    language = getattr(report, "input_language", None)
    normalization_applied = bool(getattr(report, "input_normalization_applied", False))
    if original_text and language and language != "English":
        st.markdown("### Original Event")
        st.write(original_text)
        if normalization_applied and normalized_text and normalized_text != original_text:
            st.markdown("### Normalized for Analysis")
            st.write(normalized_text)
            st.caption("Non-English inputs are translated and normalized before event extraction.")
        else:
            st.caption(
                "Non-English input was detected, but English normalization was unavailable; "
                "GeoRisk analyzed the original supplied text."
            )
        st.markdown("### Event Summary")
        st.write(report.event.summary)
    else:
        st.markdown("### Event Summary")
        st.write(report.event.summary)

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
            relevance = case.get("relevance")
            if relevance and relevance != "not scored":
                st.caption(f"Retrieval relevance: {relevance}")


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

    if getattr(report.transmission_chain, "rationale", None):
        with st.expander("Why this transmission?"):
            st.write(report.transmission_chain.rationale)


def _render_watchlist_tab(report) -> None:
    """Render the two-layer asset report."""

    st.subheader("Asset Watchlist")
    st.caption(
        "Direct exposures provide the baseline; GeoRisk's ranked output focuses "
        "on historically supported downstream risk transmission."
    )

    ranked_second, direct_references, unclassified = _partition_watchlist_assets(report)
    if unclassified:
        logger.warning("Omitting %s unclassified assets from ranked Watchlist.", len(unclassified))

    st.markdown("### Ranked Second-Order Exposures")
    st.caption("Differentiated downstream exposure candidates surfaced through historical transmission patterns.")
    st.caption(
        "Evidence scores reflect strength of historical support, not expected "
        "return or probability of price movement."
    )
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


def _render_report_footer(report) -> None:
    """Render lightweight scope and methodology caveats below the report."""

    st.divider()
    st.subheader("Limitations & Disclaimer")
    st.markdown(REPORT_FOOTER_DISCLAIMER)
    with st.expander("Methodology limitations", expanded=False):
        for limitation in METHODOLOGY_LIMITATIONS:
            st.markdown(f"- {limitation}")
        for limitation in report.limitations:
            st.markdown(f"- {limitation}")


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


def _format_confidence(confidence: float | None) -> str:
    """Format confidence as a two-decimal evidence-strength score."""

    if confidence is None:
        return "n/a"
    return f"{confidence:.2f}"


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

    st.markdown("#### Why These Assets?")
    for asset in assets:
        label = (
            f"#{_rank_display(asset)} {asset.get('ticker') or 'n/a'} — "
            f"{asset.get('asset_name') or asset.get('asset') or 'Unknown asset'}"
        )
        with st.expander(label):
            st.markdown(f"**Exposure channel:** {_format_node_title(str(asset.get('supply_chain_node') or ''))}")
            rationale = asset.get("ranking_rationale") or asset.get("reason")
            st.markdown(f"**Why it was surfaced:** {rationale or 'No ranking rationale available in this report.'}")
            st.markdown(f"**Evidence:** {_evidence_badge(asset.get('evidence_level'))}")
            st.markdown(f"**Evidence score:** {_format_confidence_value(asset.get('confidence'))}")
            _render_support_summary(asset)
            _render_supporting_cases(asset, report)


def _render_support_summary(asset: dict[str, object]) -> None:
    """Render truthful node-qualification versus asset-evidence support counts."""

    qualification_count = _int_or_none(asset.get("qualification_case_count"))
    supporting_count = _int_or_none(asset.get("supporting_case_count"))
    if qualification_count is None and isinstance(asset.get("qualification_case_ids"), list):
        qualification_count = len(set(asset["qualification_case_ids"]))
    if supporting_count is None and isinstance(asset.get("supporting_case_ids"), list):
        supporting_count = len(set(asset["supporting_case_ids"]))

    if qualification_count:
        st.markdown(
            "**Node qualification:** "
            f"{qualification_count} mechanism-compatible historical case(s)"
        )
    if supporting_count is not None:
        st.markdown(
            "**Asset evidence:** "
            f"{supporting_count} asset-level supporting case(s)"
        )


def _render_supporting_cases(asset: dict[str, object], report) -> None:
    """Render supporting historical case metadata when present."""

    qualification_count = _int_or_none(asset.get("qualification_case_count"))
    supporting_count = _int_or_none(asset.get("supporting_case_count"))
    if qualification_count and supporting_count != qualification_count:
        st.markdown("**Asset-level supporting historical cases:**")
    else:
        st.markdown("**Supporting historical cases:**")
    case_titles = _case_title_lookup(report)
    details = asset.get("supporting_case_details")
    if isinstance(details, list) and details:
        for detail in details:
            if not isinstance(detail, dict):
                continue
            case_id = detail.get("case_id") or "unknown_case"
            title = detail.get("title") or detail.get("event_name") or case_titles.get(str(case_id))
            rank = detail.get("retrieval_rank")
            suffix = f" (retrieval rank {rank})" if rank else ""
            if title:
                st.markdown(f"- {title} (`{case_id}`){suffix}")
            else:
                st.markdown(f"- `{case_id}`{suffix}")
        return

    case_ids = asset.get("supporting_case_ids")
    if isinstance(case_ids, list) and case_ids:
        for case_id in case_ids:
            title = case_titles.get(str(case_id))
            if title:
                st.markdown(f"- {title} (`{case_id}`)")
            else:
                st.markdown(f"- `{case_id}`")
        return

    st.markdown("- No supporting case IDs available in this report.")


def _int_or_none(value: object) -> int | None:
    """Return an int for safe count rendering, otherwise None."""

    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


def _case_title_lookup(report) -> dict[str, str]:
    """Return case titles from report metadata when available."""

    lookup: dict[str, str] = {}
    for case in getattr(report, "retrieved_case_summaries", []) or []:
        if isinstance(case, dict) and case.get("case_id"):
            lookup[str(case["case_id"])] = str(case.get("event_name") or case["case_id"])
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


def _format_confidence_value(confidence: object) -> str:
    """Format evidence score without implying market probability."""

    try:
        return f"{float(confidence):.2f}"
    except (TypeError, ValueError):
        return "n/a"


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
    support_map = getattr(report.transmission_chain, "node_supporting_case_ids", {}) or {}
    for node in second_order_nodes:
        case_ids = support_map.get(node, [])
        if case_ids:
            notes.append(
                f"{_format_node_title(node)} supported by "
                f"{len(case_ids)} historical case(s): "
                + ", ".join(f"`{case_id}`" for case_id in case_ids[:5])
            )
    supporting_case_ids = getattr(report.transmission_chain, "supporting_case_ids", []) or []
    if supporting_case_ids and not notes:
        notes.append(
            "Supporting historical analogs: "
            + ", ".join(f"`{case_id}`" for case_id in supporting_case_ids[:6])
        )
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
