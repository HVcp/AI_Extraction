
import streamlit as st
import requests

BACKEND = "http://localhost:8000"

st.title("WT Headcount — Step 1: Doc Intelligence")

uploaded = st.file_uploader(
    "Upload worker document image",
    type=["jpg", "jpeg", "png"]
)

if uploaded:
    st.image(uploaded, caption="Uploaded image", width=400)

    if st.button("Extract Text"):
        with st.spinner("Sending to Azure Doc Intelligence..."):
            response = requests.post(
                f"{BACKEND}/extract",
                files={"file": (uploaded.name,
                                uploaded.getvalue(),
                                uploaded.type)}
            )

        if response.ok:
            data = response.json()

            st.success("Extraction done!")

            st.subheader("Full Text")
            st.write(data["full_text"])

            st.subheader("Words + Confidence Scores")
            for word in data["words"]:
                conf = word["confidence"]

                # colour based on confidence
                if conf >= 0.85:
                    colour = "🟢"
                elif conf >= 0.60:
                    colour = "🟡"
                else:
                    colour = "🔴"

                st.write(f"{colour}  `{word['text']}`  →  {conf}")

        else:
            st.error(f"Failed: {response.text}")
            
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    