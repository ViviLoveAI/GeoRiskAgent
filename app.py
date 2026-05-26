"""Streamlit app for GeoRisk Transmission Analyzer."""

import streamlit as st

from src.pipeline import run_pipeline
from src.report_formatter import EVENT_TYPE_LABELS, NODE_LABELS, format_concise_report


EXAMPLE_EVENTS = [
    {
        "label": "Red Sea Shipping Disruption",
        "news": "Red Sea shipping routes face disruption due to escalating regional conflict.",
        "description": (
            "Maritime chokepoint risk across shipping, LNG, oil transport, "
            "logistics, and insurance."
        ),
    },
    {
        "label": "Semiconductor Export Controls",
        "news": (
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
        "news": (
            "Russia-related gas supply disruptions raise concerns over European "
            "fertilizer production and food input costs."
        ),
        "description": (
            "Energy-input risk across natural gas, fertilizer, agriculture, and "
            "food supply chains."
        ),
    },
]
EVIDENCE_GROUPS = ["historical_supported", "sector_proxy", "inference_only"]
EVIDENCE_LABELS = {
    "historical_supported": "🟢 Historical Supported",
    "sector_proxy": "🟡 Sector Proxy",
    "inference_only": "🔴 Inference Only",
}


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


def _render_home_page() -> None:
    """Render the event dashboard home page."""

    st.title("GeoRisk Transmission Analyzer")
    st.markdown(
        "Analyze geopolitical news through historical case retrieval, "
        "transmission-chain reasoning, and evidence-graded secondary asset mapping."
    )
    st.caption("Risk watchlist generation only. Not price prediction or investment advice.")

    st.header("Quick Event Examples")
    columns = st.columns(3)
    for column, event in zip(columns, EXAMPLE_EVENTS, strict=False):
        with column:
            with st.container(border=True):
                st.subheader(event["label"])
                st.write(event["description"])
                if st.button(f"Analyze {event['label']}", key=f"example_{event['label']}"):
                    _analyze_and_open_report(event["news"], event["label"])

    st.header("Analyze Your Own Event")
    custom_news = st.text_area(
        "Paste a geopolitical news headline or paragraph:",
        key="custom_news_text",
        height=150,
        placeholder="Paste a geopolitical news headline or paragraph here...",
    )
    if st.button("Analyze Custom Event", type="primary"):
        if not custom_news.strip():
            st.warning("Please enter geopolitical news text to analyze.")
            return
        _analyze_and_open_report(custom_news, "Custom Event")


def _analyze_and_open_report(news_text: str, event_label: str) -> None:
    """Run the pipeline, store the result, and open the report page."""

    with st.spinner("Analyzing risk transmission channels..."):
        st.session_state.report = run_pipeline(news_text, top_k=3)
        st.session_state.selected_event_label = event_label
        st.session_state.page = "report"
    st.rerun()


def _render_report_page() -> None:
    """Render the report detail page."""

    if st.button("← Back to Event Dashboard"):
        st.session_state.page = "home"
        st.rerun()

    report = st.session_state.report
    selected_event_label = st.session_state.get("selected_event_label", "Analyzed Event")

    st.title("GeoRisk Transmission Report")
    st.caption(selected_event_label)

    overview_tab, cases_tab, chain_tab, watchlist_tab, disclaimer_tab = st.tabs(
        [
            "Overview",
            "Historical Cases",
            "Transmission Chain",
            "Asset Watchlist",
            "Disclaimer",
        ]
    )

    with overview_tab:
        _render_overview_tab(report)
    with cases_tab:
        _render_historical_cases_tab(report)
    with chain_tab:
        _render_transmission_chain_tab(report)
    with watchlist_tab:
        _render_watchlist_tab(report)
    with disclaimer_tab:
        _render_disclaimer_tab(report)


def _render_overview_tab(report) -> None:
    """Render event overview information."""

    st.subheader("Event Summary")
    st.markdown(
        "\n".join(
            [
                f"- **Type:** {_event_type_label(report.event.event_type)}",
                f"- **Regions:** {', '.join(report.event.regions) or 'unspecified'}",
                f"- **Key Nodes:** {_format_nodes(report.event.supply_chain_nodes)}",
                f"- **Summary:** {report.event.summary}",
            ]
        )
    )


def _render_historical_cases_tab(report) -> None:
    """Render retrieved historical case summaries."""

    st.subheader("Top Retrieved Historical Cases")
    for case in report.retrieved_case_summaries[:3]:
        with st.container(border=True):
            st.markdown(f"**{case.get('event_name', 'Unknown case')}**")
            st.caption(case.get("event_type", "unknown"))
            st.write(case.get("summary", ""))


def _render_transmission_chain_tab(report) -> None:
    """Render compact natural-language transmission chain steps."""

    st.subheader("Transmission Chain")
    concise_sections = format_concise_report(report).split("\n\n")
    transmission_section = next(
        section for section in concise_sections if section.startswith("## Transmission Chain")
    )
    st.markdown("\n".join(transmission_section.splitlines()[1:]))


def _render_watchlist_tab(report) -> None:
    """Render asset watchlist tables grouped by evidence level."""

    st.subheader("Secondary Asset Watchlist")
    st.markdown("**Confidence Guide:**")
    st.markdown("- 🟢 Historical Supported — Similar historical cases directly support the channel.")
    st.markdown("- 🟡 Sector Proxy — Historical cases support the sector or supply-chain node.")
    st.markdown("- 🔴 Inference Only — Based mainly on logical mapping with limited historical support.")
    st.caption("Confidence reflects evidence strength, not probability of price movement.")

    metric_cols = st.columns(3)
    metric_cols[0].metric(
        "Historical Supported",
        len(report.secondary_asset_watchlist.get("historical_supported", [])),
    )
    metric_cols[1].metric(
        "Sector Proxy",
        len(report.secondary_asset_watchlist.get("sector_proxy", [])),
    )
    metric_cols[2].metric(
        "Inference Only",
        len(report.secondary_asset_watchlist.get("inference_only", [])),
    )

    for evidence_level in EVIDENCE_GROUPS:
        assets = report.secondary_asset_watchlist.get(evidence_level, [])
        if evidence_level == "inference_only" and not assets:
            continue

        st.markdown(f"### {EVIDENCE_LABELS[evidence_level].split(' ', maxsplit=1)[1]}")
        if not assets:
            st.write("None")
            continue

        rows = [
            {
                "Evidence": EVIDENCE_LABELS[evidence_level],
                "Ticker": asset.get("ticker"),
                "Asset": asset.get("asset_name"),
                "Exposure Node": _format_node_title(asset.get("supply_chain_node")),
                "Confidence": _format_confidence(asset.get("confidence")),
            }
            for asset in assets
        ]
        st.dataframe(rows, hide_index=True, use_container_width=True)


def _render_disclaimer_tab(report) -> None:
    """Render disclaimer and limitations."""

    st.subheader("Disclaimer")
    st.markdown("Risk watchlist only. Not price prediction or investment advice.")

    if report.limitations:
        st.subheader("Limitations")
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
    return node.replace("_", " ").title()


def _event_type_label(event_type: str) -> str:
    """Format normalized event types as readable labels."""

    return EVENT_TYPE_LABELS.get(event_type, event_type.replace("_", " ").title())


def _format_confidence(confidence: float | None) -> str:
    """Format confidence as a two-decimal evidence-strength score."""

    if confidence is None:
        return "n/a"
    return f"{confidence:.2f}"


if __name__ == "__main__":
    main()
