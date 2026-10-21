import streamlit as st
import pandas as pd
import json
import base64
import io
import requests
from PIL import Image

# 1. Cấu hình trang tối ưu cho màn hình dọc điện thoại
st.set_page_config(page_title="Tính VW & CBM", page_icon="📦", layout="centered")

st.markdown("""
    <style>
    .block-container { padding-top: 1.2rem; padding-bottom: 2rem; max-width: 500px; }
    div[data-testid="stMetricValue"] { font-size: 1.4rem; font-weight: 700; }
    </style>
""", unsafe_allow_html=True)

st.title("📦 Tính Nhanh VW / CBM")

# 2. Kiểm tra Gemini API Key từ Secrets
if "GEMINI_API_KEY" not in st.secrets:
    st.error("⚠️ Chưa cấu hình GEMINI_API_KEY trong phần Secrets!")
    st.stop()

API_KEY = st.secrets["GEMINI_API_KEY"].strip()

# Hàm gọi trực tiếp Gemini API qua HTTPS (Dùng gemini-3.8-flash)
def analyze_image_with_gemini(pil_img, api_key):
    buffered = io.BytesIO()
    pil_img.convert("RGB").save(buffered, format="JPEG", quality=85)
    img_b64 = base64.b64encode(buffered.getvalue()).decode("utf-8")

    # Dùng model gemini-3.8-flash chuẩn hiện tại
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent?key={api_key}"
    
    prompt = """
    Bạn là trợ lý kiểm nhận hàng không. Hãy đọc phiếu Hướng dẫn gửi hàng trong ảnh và trả về JSON.
    1. Tìm 'declared_pcs' tại ô 'Số kiện (No of pcs)' (nếu không rõ trả về 0).
    2. Tìm 'gross_weight' tại ô 'Trọng lượng (Gross weight)' (nếu không rõ trả về 0).
    3. Đọc toàn bộ các dòng viết tay ở phần 'Kích thước (Dimensions)' có cấu trúc: Dài * Rộng * Cao / Số_kiện.
    Lưu ý: Bỏ qua dòng tổng kết cuối cùng (ví dụ dòng có ký hiệu Sigma ∑ 10 DIM / 202).
    Trả về đúng định dạng JSON sau:
    {
      "declared_pcs": 202,
      "gross_weight": 2102.0,
      "dims": [
        {"L": 61, "W": 31, "H": 31, "pcs": 126}
      ]
    }
    """

    payload = {
        "contents": [{
            "parts": [
                {"text": prompt},
                {"inline_data": {"mime_type": "image/jpeg", "data": img_b64}}
            ]
        }],
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": 0.0
        }
    }

    res = requests.post(url, json=payload, timeout=30)
    if res.status_code != 200:
        raise Exception(f"Lỗi API ({res.status_code}): {res.text}")
    
    res_json = res.json()
    text_out = res_json["candidates"][0]["content"]["parts"][0]["text"]
    return json.loads(text_out)

# 3. Nút xóa nhanh để chụp lô hàng tiếp theo
if "last_file" in st.session_state:
    if st.button("🔄 Xóa / Chụp phiếu mới", use_container_width=True):
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.rerun()

# 4. Khung chụp ảnh / chọn ảnh
uploaded_file = st.file_uploader(
    "📸 Chạm vào đây để Chụp ảnh phiếu hoặc Chọn ảnh", 
    type=["jpg", "jpeg", "png", "webp"]
)

if uploaded_file is not None:
    image = Image.open(uploaded_file)
    
    with st.expander("🔍 Xem lại ảnh phiếu đã chụp", expanded=False):
        st.image(image, use_container_width=True)

    file_id = f"{uploaded_file.name}_{uploaded_file.size}"
    if st.session_state.get("last_file") != file_id:
        with st.spinner("⏳ Đang đọc số liệu viết tay (2-3 giây)..."):
            try:
                data = analyze_image_with_gemini(image, API_KEY)
                st.session_state.declared_pcs = int(data.get("declared_pcs", 0) or 0)
                st.session_state.gross_weight = float(data.get("gross_weight", 0.0) or 0.0)
                
                dims_list = data.get("dims", [])
                if dims_list:
                    st.session_state.df_dims = pd.DataFrame(dims_list)
                else:
                    st.session_state.df_dims = pd.DataFrame(columns=["L", "W", "H", "pcs"])
                
                st.session_state.last_file = file_id
            except Exception as e:
                st.error(f"❌ Không đọc được ảnh. Chi tiết: {e}")

    # 5. Khu vực kiểm tra & chỉnh sửa trực tiếp
    if "df_dims" in st.session_state:
        st.subheader("1. Thông tin khai báo trên phiếu")
        c1, c2 = st.columns(2)
        declared_pcs = c1.number_input("Số kiện trên phiếu (Pcs)", min_value=0, value=st.session_state.declared_pcs, step=1)
        gw = c2.number_input("Gross Weight (kg)", min_value=0.0, value=st.session_state.gross_weight, step=0.5, format="%.1f")

        st.subheader("2. Bảng kích thước (Chạm vào ô để sửa)")
        st.caption("💡 *Nếu chữ viết tay xấu bị nhầm, chạm trực tiếp vào ô số để sửa hoặc bấm dấu `+` ở cuối bảng để thêm dòng:*")

        edited_df = st.data_editor(
            st.session_state.df_dims,
            num_rows="dynamic",
            use_container_width=True,
            hide_index=False,
            column_config={
                "L": st.column_config.NumberColumn("Dài (cm)", min_value=1, step=1, format="%d", required=True),
                "W": st.column_config.NumberColumn("Rộng (cm)", min_value=1, step=1, format="%d", required=True),
                "H": st.column_config.NumberColumn("Cao (cm)", min_value=1, step=1, format="%d", required=True),
                "pcs": st.column_config.NumberColumn("Số kiện", min_value=1, step=1, format="%d", required=True),
            }
        )

        # 6. Tính toán tự động ngay lập tức
        if not edited_df.empty:
            calc_df = edited_df.fillna(0).copy()
            calc_df["Vol_cm3"] = calc_df["L"] * calc_df["W"] * calc_df["H"] * calc_df["pcs"]
            calc_df["CBM"] = calc_df["Vol_cm3"] / 1_000_000
            calc_df["VW (kg)"] = calc_df["Vol_cm3"] / 6_000

            total_pcs = int(calc_df["pcs"].sum())
            total_dims = len(calc_df)
            total_cbm = calc_df["CBM"].sum()
            total_vw = calc_df["VW (kg)"].sum()

            st.divider()
            st.subheader("3. Kết quả tính toán")

            if declared_pcs > 0:
                if total_pcs == declared_pcs:
                    st.success(f"✅ **KHỚP SỐ KIỆN:** Tổng cộng **{total_pcs} kiện** ({total_dims} DIM)")
                else:
                    diff = total_pcs - declared_pcs
                    dau = "+" if diff > 0 else ""
                    st.error(f"⚠️ **LỆCH SỐ KIỆN:** Cộng DIM ra **{total_pcs} kiện**, nhưng phiếu ghi **{declared_pcs} kiện** (Lệch **{dau}{diff} kiện**)")
            else:
                st.info(f"🔢 **Tổng đếm từ DIM:** {total_pcs} kiện ({total_dims} DIM)")

            m1, m2, m3 = st.columns(3)
            m1.metric("Tổng VW (÷6000)", f"{total_vw:,.2f} kg")
            m2.metric("Tổng CBM", f"{total_cbm:,.3f} m³")
            
            if gw > 0:
                cw = max(gw, total_vw)
                loai = "GW" if gw >= total_vw else "VW"
                m3.metric(f"CW (Ăn theo {loai})", f"{cw:,.1f} kg")
            else:
                m3.metric("Làm tròn 0.5kg", f"{round(total_vw * 2) / 2:,.1f} kg")

            with st.expander("📋 Xem chi tiết VW & CBM từng dòng DIM"):
                detail_view = calc_df[["L", "W", "H", "pcs", "CBM", "VW (kg)"]].copy()
                detail_view.columns = ["Dài", "Rộng", "Cao", "Kiện", "CBM (m³)", "VW (kg)"]
                st.dataframe(
                    detail_view.style.format({"CBM (m³)": "{:.4f}", "VW (kg)": "{:.2f}"}),
                    use_container_width=True
                )
