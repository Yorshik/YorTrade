import base64
from io import BytesIO

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


def _build_x_axis(history_length: int, tick_seconds: int) -> list[int]:
    return [index * tick_seconds for index in range(history_length)]


def _figure_to_base64(fig) -> str:
    buffer = BytesIO()
    fig.savefig(buffer, format="png", dpi=140, bbox_inches="tight")
    plt.close(fig)
    buffer.seek(0)
    return base64.b64encode(buffer.read()).decode("ascii")


def generate_asset_price_chart(asset_state: dict, tick_seconds: int) -> str:
    history = asset_state.get("history", [])
    x_axis = _build_x_axis(len(history), tick_seconds)
    fig, ax = plt.subplots(figsize=(8, 4.5), facecolor="#f6f7f9")
    ax.set_facecolor("#ffffff")
    ax.plot(x_axis, history, color="#0f766e", linewidth=2.6)
    ax.fill_between(x_axis, history, color="#99f6e4", alpha=0.35)
    ax.set_title(asset_state["name"])
    ax.set_xlabel("Секунды")
    ax.set_ylabel("Цена")
    ax.grid(alpha=0.25)
    fig.tight_layout()
    return _figure_to_base64(fig)


def generate_private_main_chart(assets_list: list[dict], tick_seconds: int) -> str:
    """Multi-line chart for up to 6 assets on the current private-chat page."""
    colors = ["#0f766e", "#1d4ed8", "#b45309", "#be123c", "#6d28d9", "#0891b2"]
    fig, ax = plt.subplots(figsize=(8, 4), facecolor="#f6f7f9")
    ax.set_facecolor("#ffffff")

    has_data = False
    for i, asset in enumerate(assets_list[:6]):
        history = asset.get("history", [])
        if len(history) < 2:
            continue
        has_data = True
        x_axis = _build_x_axis(len(history), tick_seconds)
        name = asset["name"]
        label = name[:13] + "…" if len(name) > 14 else name
        ax.plot(
            x_axis, history, color=colors[i % len(colors)], linewidth=2.0, label=label
        )

    if has_data:
        ax.legend(loc="best", fontsize=7, ncol=2)
    else:
        ax.text(
            0.5, 0.5, "Нет данных", ha="center", va="center", transform=ax.transAxes
        )

    ax.set_xlabel("Секунды", fontsize=8)
    ax.set_ylabel("Цена", fontsize=8)
    ax.tick_params(labelsize=7)
    ax.grid(alpha=0.25)
    fig.tight_layout()
    return _figure_to_base64(fig)


def generate_market_overview_chart(state: dict, tick_seconds: int) -> str:
    assets = list(state.get("assets", {}).values())
    fig, ax = plt.subplots(figsize=(10, 4.8), facecolor="#f6f7f9")
    ax.set_facecolor("#ffffff")
    ax.set_title("Тренд рынка (средняя цена компаний)")
    ax.set_xlabel("Секунды")
    ax.set_ylabel("Средняя цена")
    ax.grid(alpha=0.25)

    histories = [asset.get("history", []) for asset in assets if asset.get("history")]
    if histories:
        max_len = min(len(history) for history in histories)
        averages: list[float] = []
        for history_index in range(max_len):
            prices = [float(history[history_index]) for history in histories]
            averages.append(sum(prices) / len(prices))
        x_axis = _build_x_axis(max_len, tick_seconds)
        ax.plot(x_axis, averages, linewidth=2.4, color="#1d4ed8")
        ax.fill_between(x_axis, averages, color="#93c5fd", alpha=0.3)
    else:
        ax.text(
            0.5,
            0.5,
            "Недостаточно данных для графика",
            ha="center",
            va="center",
            transform=ax.transAxes,
        )

    fig.tight_layout()
    return _figure_to_base64(fig)
