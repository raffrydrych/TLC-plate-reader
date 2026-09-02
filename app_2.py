import base64
import csv
import io
import uuid

import numpy as np
import streamlit as st
import streamlit.components.v1 as components
from streamlit_image_coordinates import streamlit_image_coordinates
from PIL import Image, ImageDraw
from skimage import exposure
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
if "region" not in st.session_state:
    st.session_state.region = None  # dict: x0, y0, x1, y1
if "region_start" not in st.session_state:
    st.session_state.region_start = None  # (x, y) pierwszego rogu, w trakcie zaznaczania


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


LIGHT_MODES = {
    "white": "Światło białe (widzialne) - plamki ciemne/kolorowe na jasnym tle",
    "uv254": "UV 254 nm - wygaszenie fluorescencji, plamki ciemne na zielonym tle",
    "uv366": "UV 366 nm - plamki fluoryzują jasno na ciemnym tle",
}


def prepare_detection_crop(image, x0, y0, x1, y1, light_mode="white"):
    """Zwraca znormalizowany kontrastowo wycinek (0-1), w którym szukane
    plamki są jasnymi 'blobami' - niezależnie od trybu oświetlenia:

    - white: plamki są ciemniejsze niż jasne tło płytki -> używamy jasności
      (skala szarości) i odwracamy (1 - jasność).
    - uv254: podłoże zawiera wskaźnik fluorescencyjny i pod UV 254 nm świeci
      na zielono; plamki gaszą tę fluorescencję i wychodzą ciemne na zielonym
      tle -> kanał zielony daje najlepszy kontrast, też odwracamy.
    - uv366: związki fluoryzują i są jasne na ciemnym tle -> używamy
      maksymalnej jasności spośród kanałów RGB i NIE odwracamy (plamki są
      już jasne, to tło jest ciemne).

    Rozciąganie kontrastu (2-98 percentyl) sprawia, że działa niezależnie od
    tego, jak jasne/ciemne jest oryginalne zdjęcie."""
    crop = image.crop((x0, y0, x1, y1))
    arr = np.array(crop).astype(float) / 255.0  # H, W, 3

    if light_mode == "uv254":
        intensity = arr[..., 1]  # kanał zielony - najlepszy kontrast wygaszenia
        detection_map = 1.0 - intensity
    elif light_mode == "uv366":
        intensity = arr.max(axis=-1)  # jasność niezależna od koloru fluorescencji
        detection_map = intensity
    else:  # white
        intensity = np.array(crop.convert("L")).astype(float) / 255.0
        detection_map = 1.0 - intensity

    p2, p98 = np.percentile(detection_map, (2, 98))
    if p98 > p2:
        detection_map = exposure.rescale_intensity(detection_map, in_range=(p2, p98), out_range=(0, 1))
    return detection_map


def detect_spots(image, x0, y0, x1, y1, threshold, min_sigma, max_sigma, light_mode="white"):
    detection_map = prepare_detection_crop(image, x0, y0, x1, y1, light_mode)
    blobs = blob_log(
        detection_map, min_sigma=min_sigma, max_sigma=max_sigma, num_sigma=8, threshold=threshold
    )
    return [(int(bx) + x0, int(by) + y0) for by, bx, _sigma in blobs]


uploaded_file = st.file_uploader("Wgraj zdjęcie płytki TLC", type=["png", "jpg", "jpeg"])

mode = st.radio(
    "Co zaznaczasz kolejnym kliknięciem na zdjęciu?",
    [
        "1) Baseline (linia startu)",
        "2) Front (czoło rozpuszczalnika)",
        "3) Plamka (dodaj ręcznie klikając)",
        "4) Obszar wykrywania (2 kliknięcia = 2 rogi)",
    ],
    horizontal=True,
)

btn_col1, btn_col2, btn_col3 = st.columns([1, 1, 1])
with btn_col1:
    if st.button("🔄 Resetuj wszystko"):
        st.session_state.baseline_y = None
        st.session_state.front_y = None
        st.session_state.spots = []
        st.session_state.last_processed_click = None
        st.session_state.region = None
        st.session_state.region_start = None
        st.rerun()
with btn_col3:
    if st.button("✖️ Wyczyść obszar wykrywania"):
        st.session_state.region = None
        st.session_state.region_start = None
        st.rerun()

with st.expander("⚙️ Ustawienia automatycznego wykrywania plamek", expanded=True):
    LIGHT_DEFAULTS = {
        "white": {"threshold": 0.05, "min_sigma": 3, "max_sigma": 20},
        "uv254": {"threshold": 0.04, "min_sigma": 3, "max_sigma": 20},
        "uv366": {"threshold": 0.08, "min_sigma": 3, "max_sigma": 25},
    }
    light_mode = st.selectbox(
        "Typ oświetlenia / wizualizacji plamek",
        options=list(LIGHT_MODES.keys()),
        format_func=lambda k: LIGHT_MODES[k],
    )
    _d = LIGHT_DEFAULTS[light_mode]
    # klucz zawiera tryb oświetlenia - każdy tryb pamięta swoje własne,
    # osobno dostrojone ustawienia po przełączeniu
    det_threshold = st.slider(
        "Czułość wykrywania (niższa = wykryje więcej)",
        0.01, 0.5, _d["threshold"], 0.01, key=f"thr_{light_mode}",
    )
    det_min_sigma = st.slider("Min. rozmiar plamki (px)", 1, 20, _d["min_sigma"], key=f"min_{light_mode}")
    det_max_sigma = st.slider("Maks. rozmiar plamki (px)", 5, 60, _d["max_sigma"], key=f"max_{light_mode}")
    show_debug_preview = st.checkbox("Pokaż podgląd analizowanego obszaru (do debugowania)", value=False)

col1, col2 = st.columns([3, 1])

if uploaded_file is not None:
    base_image = Image.open(uploaded_file).convert("RGB")
    w, h = base_image.size

    with btn_col2:
        detect_help = (
            "Szuka tylko w zaznaczonym obszarze (tryb 4)."
            if st.session_state.region
            else "Brak zaznaczonego obszaru - przeszuka cały pas między baseline a front (albo całe zdjęcie)."
        )
        if st.button("🔎 Wykryj plamki automatycznie", help=detect_help):
            if st.session_state.region:
                x0, y0 = st.session_state.region["x0"], st.session_state.region["y0"]
                x1, y1 = st.session_state.region["x1"], st.session_state.region["y1"]
            else:
                x0, x1 = 0, w
                if st.session_state.baseline_y is not None and st.session_state.front_y is not None:
                    y0, y1 = sorted([st.session_state.baseline_y, st.session_state.front_y])
                else:
                    y0, y1 = 0, h

            found = detect_spots(
                base_image, x0, y0, x1, y1, det_threshold, det_min_sigma, det_max_sigma, light_mode
            )
            added = 0
            for x, y in found:
                if is_far_enough(x, y, st.session_state.spots):
                    add_spot(x, y)
                    added += 1
            skipped = len(found) - added
            st.session_state["_last_detect_msg"] = (
                f"Znaleziono {len(found)} potencjalnych plamek, dodano {added} nowych"
                + (f" (pominięto {skipped} jako zbyt blisko istniejących)." if skipped else ".")
            )
            if len(found) == 0:
                st.session_state["_last_detect_msg"] += (
                    " Nic nie znaleziono - spróbuj obniżyć czułość w ustawieniach (mniejsza wartość)"
                    " albo poszerzyć zakres rozmiaru plamki."
                )
            st.rerun()

    if st.session_state.get("_last_detect_msg"):
        st.info(st.session_state["_last_detect_msg"])

    if show_debug_preview:
        if st.session_state.region:
            dx0, dy0 = st.session_state.region["x0"], st.session_state.region["y0"]
            dx1, dy1 = st.session_state.region["x1"], st.session_state.region["y1"]
        else:
            dx0, dx1 = 0, w
            if st.session_state.baseline_y is not None and st.session_state.front_y is not None:
                dy0, dy1 = sorted([st.session_state.baseline_y, st.session_state.front_y])
            else:
                dy0, dy1 = 0, h
        preview = prepare_detection_crop(base_image, dx0, dy0, dx1, dy1, light_mode)
        st.caption("Podgląd: obszar analizowany przez detektor (jasne plamy = potencjalne plamki)")
        st.image(preview, clamp=True, use_container_width=True)

    # kopia obrazu z narysowanymi liniami baseline/front, obszarem i plamkami
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

    if st.session_state.region:
        r = st.session_state.region
        draw.rectangle([r["x0"], r["y0"], r["x1"], r["y1"]], outline="orange", width=3)
    elif st.session_state.region_start:
        sx, sy = st.session_state.region_start
        rr = 5
        draw.ellipse([sx - rr, sy - rr, sx + rr, sy + rr], outline="orange", width=2)
        draw.text((sx + 8, sy - 8), "1. róg zaznaczony - kliknij 2. róg", fill="orange")

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

            elif mode.startswith("3"):  # Plamka - dodanie ręczne
                if st.session_state.baseline_y is None or st.session_state.front_y is None:
                    st.warning("Najpierw zaznacz baseline i front (tryby 1 i 2).")
                else:
                    add_spot(x, y)
                    st.rerun()

            else:  # Obszar wykrywania - dwa kliknięcia (dwa rogi)
                if st.session_state.region_start is None:
                    st.session_state.region_start = (x, y)
                else:
                    sx, sy = st.session_state.region_start
                    st.session_state.region = {
                        "x0": min(sx, x),
                        "y0": min(sy, y),
                        "x1": max(sx, x),
                        "y1": max(sy, y),
                    }
                    st.session_state.region_start = None
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
        if st.session_state.region:
            r = st.session_state.region
            st.write(f"Obszar wykrywania: ({r['x0']},{r['y0']}) → ({r['x1']},{r['y1']})")
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
