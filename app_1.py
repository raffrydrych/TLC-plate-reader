import base64

import streamlit as st
import streamlit.components.v1 as components
from streamlit_image_coordinates import streamlit_image_coordinates
from PIL import Image, ImageDraw

st.set_page_config(page_title="Płytka TLC - obliczanie Rf", layout="wide")
st.title("TLC_tracker")

# ---------------------------------------------------------------------------
# Czerwony krzyżyk jako kursor nad obrazkiem.
# streamlit-image-coordinates renderuje obrazek wewnątrz osobnego komponentu
# (iframe), dlatego zwykłe st.markdown z CSS go nie dosięgnie. Ten skrypt
# co ok. 400 ms szuka iframe'ów na stronie i wstrzykuje do nich styl kursora.
# To rozwiązanie "best-effort" - w większości przeglądarek działa, bo
# komponenty Streamlit są serwowane z tego samego originu.
# ---------------------------------------------------------------------------
CURSOR_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="22" height="22">'
    '<line x1="11" y1="0" x2="11" y2="22" stroke="red" stroke-width="2"/>'
    '<line x1="0" y1="11" x2="22" y2="11" stroke="red" stroke-width="2"/>'
    '</svg>'
)
cursor_b64 = base64.b64encode(CURSOR_SVG.encode()).decode()

components.html(
    f"""
    <script>
    function paintCursor() {{
        try {{
            const iframes = window.parent.document.querySelectorAll('iframe');
            iframes.forEach(f => {{
                try {{
                    const doc = f.contentDocument || f.contentWindow.document;
                    if (doc && !doc.getElementById('red-cursor-style')) {{
                        const style = doc.createElement('style');
                        style.id = 'red-cursor-style';
                        style.innerHTML = `img {{
                            cursor: url('data:image/svg+xml;base64,{cursor_b64}') 11 11, crosshair !important;
                        }}`;
                        doc.head.appendChild(style);
                    }}
                }} catch (e) {{}}
            }});
        }} catch (e) {{}}
    }}
    setInterval(paintCursor, 400);
    </script>
    """,
    height=0,
)

# ---------------------------------------------------------------------------
# Stan aplikacji
# ---------------------------------------------------------------------------
if "baseline_y" not in st.session_state:
    st.session_state.baseline_y = None
if "front_y" not in st.session_state:
    st.session_state.front_y = None
if "spots" not in st.session_state:
    st.session_state.spots = []  # lista (x, y, rf)

uploaded_file = st.file_uploader("Wgraj zdjęcie płytki TLC", type=["png", "jpg", "jpeg"])

mode = st.radio(
    "Co zaznaczasz kolejnym kliknięciem na zdjęciu?",
    ["1) Baseline (linia startu)", "2) Front (czoło rozpuszczalnika)", "3) Plamka"],
    horizontal=True,
)

if st.button("🔄 Resetuj wszystko"):
    st.session_state.baseline_y = None
    st.session_state.front_y = None
    st.session_state.spots = []
    st.rerun()

col1, col2 = st.columns([3, 1])

if uploaded_file is not None:
    base_image = Image.open(uploaded_file).convert("RGB")

    # rysujemy kopię obrazu z liniami baseline/front oraz kropkami plamek
    display_image = base_image.copy()
    draw = ImageDraw.Draw(display_image)
    w, h = display_image.size

    if st.session_state.baseline_y is not None:
        y = st.session_state.baseline_y
        draw.line([(0, y), (w, y)], fill="blue", width=3)
        draw.text((5, max(0, y - 18)), "baseline", fill="blue")

    if st.session_state.front_y is not None:
        y = st.session_state.front_y
        draw.line([(0, y), (w, y)], fill="green", width=3)
        draw.text((5, min(h - 15, y + 5)), "front", fill="green")

    for i, (x, y, rf) in enumerate(st.session_state.spots, start=1):
        r = 5
        draw.ellipse([x - r, y - r, x + r, y + r], fill="red", outline="black")
        draw.text((x + 8, y - 8), str(i), fill="red")

    with col1:
        st.caption("Kliknij na zdjęciu zgodnie z wybranym trybem powyżej.")
        coords = streamlit_image_coordinates(display_image, key="tlc_image")

    if coords is not None:
        x, y = coords["x"], coords["y"]

        if mode.startswith("1"):
            if st.session_state.baseline_y != y:
                st.session_state.baseline_y = y
                st.rerun()

        elif mode.startswith("2"):
            if st.session_state.front_y != y:
                st.session_state.front_y = y
                st.rerun()

        else:  # Plamka
            if st.session_state.baseline_y is None or st.session_state.front_y is None:
                st.warning("Najpierw zaznacz baseline i front (tryby 1 i 2).")
            else:
                baseline_y = st.session_state.baseline_y
                front_y = st.session_state.front_y
                denom = baseline_y - front_y
                already = [(sx, sy) for sx, sy, _ in st.session_state.spots]
                if denom == 0:
                    st.error("Baseline i front mają tę samą wysokość - popraw zaznaczenie.")
                elif (x, y) not in already:
                    rf = (baseline_y - y) / denom
                    st.session_state.spots.append((x, y, rf))
                    st.rerun()

    with col2:
        st.subheader("Wyniki")
        st.write(
            f"Baseline (y): "
            f"{st.session_state.baseline_y if st.session_state.baseline_y is not None else '—'}"
        )
        st.write(
            f"Front (y): "
            f"{st.session_state.front_y if st.session_state.front_y is not None else '—'}"
        )
        st.divider()
        if st.session_state.spots:
            for i, (x, y, rf) in enumerate(st.session_state.spots, start=1):
                st.metric(f"Plamka {i} — Rf", f"{rf:.3f}", help=f"X={x}, Y={y}")
        else:
            st.info("Brak zaznaczonych plamek.")
else:
    st.info("Wgraj zdjęcie, aby rozpocząć.")
