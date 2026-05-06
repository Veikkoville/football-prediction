"""
Ottelukohtaiset Plotly-visualisoinnit: 1X2-pylvaat, score-heatmap, ottelukortti.
"""

from __future__ import annotations

import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots


def render_1x2_bars(
    p_home: float, p_draw: float, p_away: float,
    koti: str, vieras: str,
    koti_color: str = "#888", vieras_color: str = "#888",
):
    """
    Horisontaalinen pylvasdiagram 1X2-todennakoisyyksille.
    Kayttaa joukkueiden brandivareja, animoituu auki.
    """
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=[p_home * 100, p_draw * 100, p_away * 100],
        y=[f"1 — {koti}", "X — Tasapeli", f"2 — {vieras}"],
        orientation="h",
        marker=dict(
            color=[koti_color, "#9CA3AF", vieras_color],
            line=dict(width=0),
        ),
        text=[
            f"<b>{p_home*100:.1f}%</b>  ({1/max(p_home,0.001):.2f})",
            f"<b>{p_draw*100:.1f}%</b>  ({1/max(p_draw,0.001):.2f})",
            f"<b>{p_away*100:.1f}%</b>  ({1/max(p_away,0.001):.2f})",
        ],
        textposition="outside",
        textfont=dict(size=14),
        hoverinfo="skip",
    ))
    fig.update_layout(
        xaxis=dict(range=[0, 110], showticklabels=False, showgrid=False, zeroline=False),
        yaxis=dict(showgrid=False),
        height=200,
        margin=dict(l=0, r=20, t=10, b=0),
        showlegend=False,
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(size=13),
    )
    return fig


def render_ou_btts_bars(
    p_over: float, p_under: float,
    p_btts_yes: float, p_btts_no: float,
    line: float = 2.5,
):
    """Kaksi pylvasryhmaa: O/U + BTTS."""
    fig = make_subplots(
        rows=1, cols=2,
        subplot_titles=(f"Yli/Alle {line} maalia", "BTTS — molemmat tekevat"),
        horizontal_spacing=0.15,
    )
    # O/U
    fig.add_trace(go.Bar(
        x=[p_over * 100, p_under * 100],
        y=[f"Yli {line}", f"Alle {line}"],
        orientation="h",
        marker=dict(color=["#10B981", "#EF4444"]),
        text=[f"<b>{p_over*100:.1f}%</b>", f"<b>{p_under*100:.1f}%</b>"],
        textposition="outside",
        showlegend=False,
        hoverinfo="skip",
    ), row=1, col=1)
    # BTTS
    fig.add_trace(go.Bar(
        x=[p_btts_yes * 100, p_btts_no * 100],
        y=["Kylla", "Ei"],
        orientation="h",
        marker=dict(color=["#10B981", "#EF4444"]),
        text=[f"<b>{p_btts_yes*100:.1f}%</b>", f"<b>{p_btts_no*100:.1f}%</b>"],
        textposition="outside",
        showlegend=False,
        hoverinfo="skip",
    ), row=1, col=2)

    fig.update_xaxes(range=[0, 115], showticklabels=False, showgrid=False, zeroline=False)
    fig.update_yaxes(showgrid=False)
    fig.update_layout(
        height=200,
        margin=dict(l=0, r=20, t=40, b=0),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(size=13),
    )
    return fig


def render_score_heatmap(
    score_matrix: np.ndarray, koti: str, vieras: str,
    max_display: int = 6, koti_color: str = "#0057B8",
):
    """
    Lampokartta tarkoista tuloksista. Y-akseli = koti maalit, X-akseli = vieras.
    Korkeampi todennakoisyys = tummempi sininen.
    """
    M = score_matrix[:max_display + 1, :max_display + 1] * 100
    labels = list(range(max_display + 1))

    # Etsi top-3 todennakoisinta tulosta — naita korostetaan
    flat_idx = np.argsort(M.flatten())[::-1][:3]
    top_coords = [(idx // M.shape[1], idx % M.shape[1]) for idx in flat_idx]

    text_matrix = []
    for i in range(M.shape[0]):
        row = []
        for j in range(M.shape[1]):
            val = M[i, j]
            if (i, j) in top_coords and val > 1:
                row.append(f"<b>{val:.1f}%</b>")
            elif val >= 1.0:
                row.append(f"{val:.1f}%")
            else:
                row.append("")
        text_matrix.append(row)

    fig = go.Figure(data=go.Heatmap(
        z=M,
        x=labels,
        y=labels,
        colorscale=[
            [0.0, "rgba(255,255,255,0.05)"],
            [0.05, "rgba(99,102,241,0.2)"],
            [0.3, "rgba(99,102,241,0.6)"],
            [1.0, "rgba(99,102,241,1.0)"],
        ],
        text=text_matrix,
        texttemplate="%{text}",
        textfont=dict(size=11, color="white"),
        showscale=False,
        hovertemplate=(
            f"<b>{koti}</b> %{{y}} - %{{x}} <b>{vieras}</b><br>"
            "Todennakoisyys: %{z:.2f}%<extra></extra>"
        ),
    ))

    fig.update_layout(
        xaxis=dict(
            title=dict(text=f"<b>{vieras}</b> maalit", font=dict(size=13)),
            tickmode="array", tickvals=labels, ticktext=labels,
            showgrid=False,
        ),
        yaxis=dict(
            title=dict(text=f"<b>{koti}</b> maalit", font=dict(size=13)),
            tickmode="array", tickvals=labels, ticktext=labels,
            autorange="reversed",
            showgrid=False,
        ),
        height=420,
        margin=dict(l=0, r=0, t=10, b=0),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
    )
    return fig


def render_match_card(
    koti: str, vieras: str,
    lam: float, mu: float,
    koti_color: str = "#888", vieras_color: str = "#888",
    koti_logo: str | None = None, vieras_logo: str | None = None,
) -> str:
    """
    Tuottaa HTML-stringin "ottelukortti"-tyyliselle headerille.
    Kayta: st.markdown(html, unsafe_allow_html=True).
    """
    def _logo_block(logo, color, name, xg):
        if logo:
            img = f'<img src="{logo}" style="height:48px;margin-bottom:8px"/>'
        else:
            initials = "".join(w[0] for w in name.split()[:2]).upper()
            img = (
                f'<div style="height:48px;width:48px;display:inline-flex;'
                f'align-items:center;justify-content:center;background:{color};'
                f'color:white;border-radius:50%;font-weight:bold;font-size:18px;'
                f'margin-bottom:8px">{initials}</div>'
            )
        return (
            f'<div style="text-align:center;flex:1">'
            f'{img}'
            f'<div style="font-weight:600;font-size:16px;color:{color}">{name}</div>'
            f'<div style="opacity:0.7;font-size:13px">xG {xg:.2f}</div>'
            f'</div>'
        )

    return (
        f'<div style="display:flex;align-items:center;justify-content:space-around;'
        f'padding:16px;border-radius:12px;background:rgba(255,255,255,0.03);'
        f'border:1px solid rgba(255,255,255,0.08);margin-bottom:16px">'
        + _logo_block(koti_logo, koti_color, koti, lam)
        + '<div style="text-align:center;font-size:22px;font-weight:700;opacity:0.6">VS</div>'
        + _logo_block(vieras_logo, vieras_color, vieras, mu)
        + '</div>'
    )
