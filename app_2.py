import base64
import csv
import io
import uuid

import numpy as np
import streamlit as st
import streamlit.components.v1 as components
from streamlit_image_coordinates import streamlit_image_coordinates
from PIL import Image, ImageDraw
from skimage.feature import blob_log

st.set_page_config(page_title="Płytka TLC - obliczanie Rf", layout="wide")
st.title("🧪 Płytka TLC - zaznaczanie linii i obliczanie Rf")

# ---------------------------------------------------------------------------
# Czerwony krzyżyk jako kursor nad obrazkiem (best-effort, wstrzykiwane do
# iframe komponentu streamlit-image-coordinates).
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
    st.session_state.spots = []  # lista dict: id, x, y, rf, name
if "last_processed_click" not in st.session_state:
    st.session_state.last_processed_click = None


def calc_rf(y):
    baseline_y = st.session_state.baseline_y
    front_y = st.session_state.front_y
    if baseline_y is None or front_y is None:
        return None
    denom = baseline_y - front_y
    if denom == 0:
        return None
    return (baseline_y - y) / denom


def add_spot(x, y, name=None):
    st.session_state.spots.append(
        {
            "id": str(uuid.uuid4()),
            "x": x,
            "y": y,
            "rf": calc_rf(y),
            "name": name or f"Plamka {len(st.session_state.spots) + 1}",
        }
    )


def recalc_all_rf():
    for s in st.session_state.spots:
        s["rf"] = calc_rf(s["y"])


def is_far_enough(x, y, spots, min_dist=20):
    for s in spots:
        if (s["x"] - x) ** 2 + (s["y"] - y) ** 2 < min_dist ** 2:
            return False
    return True


def detect_spots(image, y0, y1, threshold, min_sigma, max_sigma):
    gray = np.array(image.convert("L").crop((0, y0, image.width, y1))) / 255.0
    inverted = 1.0 - gray  # plamki zwykle są ciemniejsze niż tło płytki
    blobs = blob_log(
        inverted, min_sigma=min_sigma, max_sigma=max_sigma, num_sigma=8, threshold=threshold
    )
    return [(int(bx), int(by) + y0) for by, bx, _sigma in blobs]


uploaded_file = st.file_uploader("Wgraj zdjęcie płytki TLC", type=["png", "jpg", "jpeg"])

mode = st.radio(
    "Co zaznaczasz kolejnym kliknięciem na zdjęciu?",
    [
        "1) Baseline (linia startu)",
        "2) Front (czoło rozpuszczalnika)",
        "3) Plamka (dodaj ręcznie klikając)",
    ],
    horizontal=True,
)

btn_col1, btn_col2 = st.columns([1, 1])
with btn_col1:
    if st.button("🔄 Resetuj wszystko"):
        st.session_state.baseline_y = None
        st.session_state.front_y = None
        st.session_state.spots = []
        st.session_state.last_processed_click = None
        st.rerun()

with st.expander("⚙️ Ustawienia automatycznego wykrywania plamek"):
    det_threshold = st.slider("Czułość wykrywania (niższa = wykryje więcej)", 0.02, 0.5, 0.12, 0.01)
    det_min_sigma = st.slider("Min. rozmiar plamki (px)", 1, 20, 3)
    det_max_sigma = st.slider("Maks. rozmiar plamki (px)", 5, 60, 20)

col1, col2 = st.columns([3, 1])

if uploaded_file is not None:
    base_image = Image.open(uploaded_file).convert("RGB")
    w, h = base_image.size

    with btn_col2:
        if st.button("🔎 Wykryj plamki automatycznie"):
            if st.session_state.baseline_y is not None and st.session_state.front_y is not None:
                y0, y1 = sorted([st.session_state.baseline_y, st.session_state.front_y])
            else:
                y0, y1 = 0, h
            found = detect_spots(base_image, y0, y1, det_threshold, det_min_sigma, det_max_sigma)
            added = 0
            for x, y in found:
                if is_far_enough(x, y, st.session_state.spots):
                    add_spot(x, y)
                    added += 1
            st.toast(f"Wykryto i dodano {added} nowych plamek.")
            st.rerun()

    # kopia obrazu z narysowanymi liniami baseline/front oraz plamkami
    display_image = base_image.copy()
    draw = ImageDraw.Draw(display_image)

    if st.session_state.baseline_y is not None:
        y = st.session_state.baseline_y
        draw.line([(0, y), (w, y)], fill="blue", width=3)
        draw.text((5, max(0, y - 18)), "baseline", fill="blue")

    if st.session_state.front_y is not None:
        y = st.session_state.front_y
        draw.line([(0, y), (w, y)], fill="green", width=3)
        draw.text((5, min(h - 15, y + 5)), "front", fill="green")

    for s in st.session_state.spots:
        r = 5
        x, y = s["x"], s["y"]
        draw.ellipse([x - r, y - r, x + r, y + r], fill="red", outline="black")
        draw.text((x + 8, y - 8), s["name"], fill="red")

    with col1:
        st.caption("Kliknij na zdjęciu zgodnie z wybranym trybem powyżej.")
        coords = streamlit_image_coordinates(display_image, key="tlc_image")

    # Przetwarzamy TYLKO faktycznie nowe kliknięcie (inne niż ostatnio obsłużone),
    # żeby zmiana trybu bez nowego kliknięcia niczego nie dodawała.
    if coords is not None:
        click = (coords["x"], coords["y"])
        if click != st.session_state.last_processed_click:
            st.session_state.last_processed_click = click
            x, y = click

            if mode.startswith("1"):
                st.session_state.baseline_y = y
                recalc_all_rf()
                st.rerun()

            elif mode.startswith("2"):
                st.session_state.front_y = y
                recalc_all_rf()
                st.rerun()

            else:  # Plamka - dodanie ręczne
                if st.session_state.baseline_y is None or st.session_state.front_y is None:
                    st.warning("Najpierw zaznacz baseline i front (tryby 1 i 2).")
                else:
                    add_spot(x, y)
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
            for s in st.session_state.spots:
                c_name, c_rf, c_del = st.columns([3, 2, 1])
                with c_name:
                    new_name = st.text_input(
                        "Nazwa",
                        value=s["name"],
                        key=f"name_{s['id']}",
                        label_visibility="collapsed",
                    )
                    if new_name != s["name"]:
                        s["name"] = new_name
                with c_rf:
                    rf_text = f"Rf = {s['rf']:.3f}" if s["rf"] is not None else "Rf = —"
                    st.write(rf_text)
                with c_del:
                    if st.button("🗑", key=f"del_{s['id']}"):
                        st.session_state.spots = [
                            sp for sp in st.session_state.spots if sp["id"] != s["id"]
                        ]
                        st.rerun()

            st.divider()
            csv_buffer = io.StringIO()
            writer = csv.writer(csv_buffer)
            writer.writerow(["Baseline (y, px)", st.session_state.baseline_y])
            writer.writerow(["Front (y, px)", st.session_state.front_y])
            writer.writerow([])
            writer.writerow(["Nazwa", "X (px)", "Y (px)", "Rf"])
            for s in st.session_state.spots:
                rf_val = f"{s['rf']:.4f}" if s["rf"] is not None else ""
                writer.writerow([s["name"], s["x"], s["y"], rf_val])

            st.download_button(
                "⬇️ Eksportuj wyniki do CSV",
                data=csv_buffer.getvalue(),
                file_name="wyniki_rf.csv",
                mime="text/csv",
            )
        else:
            st.info("Brak zaznaczonych plamek.")
else:
    st.info("Wgraj zdjęcie, aby rozpocząć.")
