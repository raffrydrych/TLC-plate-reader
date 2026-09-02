import streamlit as st
from streamlit_image_coordinates import streamlit_image_coordinates
from PIL import Image

st.set_page_config(page_title="Zaznacz punkt na płytce", layout="wide")
st.title("📷 Zaznacz punkt na zdjęciu płytki")

if "history" not in st.session_state:
    st.session_state.history = []

uploaded_file = st.file_uploader("Wgraj zdjęcie płytki", type=["png", "jpg", "jpeg"])

col1, col2 = st.columns([3, 1])

if uploaded_file is not None:
    image = Image.open(uploaded_file)

    with col1:
        st.write("Kliknij na zdjęciu, aby zaznaczyć punkt:")
        coords = streamlit_image_coordinates(image, key="board_image")

    with col2:
        st.subheader("Współrzędne")
        if coords is not None:
            st.metric("X (px)", coords["x"])
            st.metric("Y (px)", coords["y"])

            # zapamiętaj ostatnie kliknięcia (opcjonalnie, do podglądu historii)
            last = st.session_state.history[-1] if st.session_state.history else None
            if last != (coords["x"], coords["y"]):
                st.session_state.history.append((coords["x"], coords["y"]))
        else:
            st.info("Kliknij na obrazku, aby zobaczyć współrzędne.")

        if st.session_state.history:
            st.divider()
            st.caption("Historia kliknięć:")
            for i, (x, y) in enumerate(reversed(st.session_state.history[-10:]), 1):
                st.text(f"{i}. X={x}, Y={y}")

            if st.button("Wyczyść historię"):
                st.session_state.history = []
                st.rerun()
else:
    st.info("Wgraj zdjęcie (PNG/JPG), aby rozpocząć.")
