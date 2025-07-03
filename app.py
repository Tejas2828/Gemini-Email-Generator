# app.py - v5 "Full Prof" Version with Temporary API Key Management

# ==============================================================================
# IMPORTS
# ==============================================================================
import streamlit as st
import pandas as pd
import time
import json
import google.generativeai as genai
import requests
from bs4 import BeautifulSoup
import io

# ==============================================================================
# HELPER FUNCTIONS
# ==============================================================================
def get_website_text(url):
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        response = requests.get(url, headers=headers, timeout=15, verify=False)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        for s in soup(["script", "style"]): s.decompose()
        text = soup.get_text(separator=' ', strip=True)
        return text[:3500]
    except requests.exceptions.RequestException:
        return None

@st.cache_data
def to_excel(df):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Generated Emails')
    processed_data = output.getvalue()
    return processed_data

def calculate_stats(df):
    if df is None or "Email Body" not in df.columns:
        return {"generated": 0, "errors": 0, "total_processed": 0, "total_rows": 0}
    
    generated_count = df["Email Body"].str.contains("ERROR:", na=False).ne(True) & df["Email Body"].str.len().gt(10)
    error_count = df["Email Body"].str.startswith("ERROR:", na=False)
    
    return {
        "generated": int(generated_count.sum()), "errors": int(error_count.sum()),
        "total_processed": int(generated_count.sum() + error_count.sum()), "total_rows": len(df)
    }

# --- Session State Initialization ---
if 'stop_processing' not in st.session_state: st.session_state.stop_processing = False
if 'generation_started' not in st.session_state: st.session_state.generation_started = False
if 'results_df' not in st.session_state: st.session_state.results_df = None
if 'temp_api_keys' not in st.session_state: st.session_state.temp_api_keys = {}

# ==============================================================================
# STREAMLIT APP UI
# ==============================================================================
st.set_page_config(page_title="Cad & Cart AI Email Generator", page_icon="📧", layout="wide")

# --- Sidebar UI ---
st.sidebar.title("Cad & Cart")
st.sidebar.header("⚙️ Configuration")

# --- NEW: Merging permanent and temporary keys for the dropdown ---
permanent_keys = st.secrets.get("api_keys", {})
all_api_keys = {**permanent_keys, **st.session_state.temp_api_keys}
api_key_options = list(all_api_keys.keys())

if not api_key_options:
    st.sidebar.warning("No permanent API keys found. Please add one below.")
    selected_api_key_name = None
else:
    selected_api_key_name = st.sidebar.selectbox("Select API Key to Use", options=api_key_options)

delay_seconds = st.sidebar.number_input(
    "Adjustable Delay (seconds)", min_value=1, max_value=10, value=2, step=1,
    help="Pause between API calls."
)

# --- NEW: UI for adding a temporary API key ---
with st.sidebar.expander("🔑 Add a Temporary API Key for this Session"):
    with st.form("new_api_key_form"):
        new_key_name = st.text_input("Key Name (e.g., 'My Temp Key')")
        new_key_value = st.text_input("API Key Value", type="password")
        submitted = st.form_submit_button("Add Key")
        
        if submitted:
            if new_key_name and new_key_value:
                st.session_state.temp_api_keys[new_key_name] = new_key_value
                st.toast(f"✅ Added temporary key: {new_key_name}")
                time.sleep(1) # Give toast time to show
                st.rerun()
            else:
                st.error("Please provide both a name and a value for the key.")

with st.sidebar.expander("👉 How to Use This App"):
    st.markdown("1. **Select API Key** (or add a temporary one)\n2. **Adjust Delay**\n3. **Upload CSV**\n4. **Generate/Stop**\n5. **Download**")
st.sidebar.markdown("---")

# --- Main Page UI ---
st.title("📧 AI-Powered Email Body Generator")
uploaded_file = st.file_uploader("Upload your CSV file to begin", type=["csv"])

if uploaded_file is not None:
    if not st.session_state.generation_started:
        if st.button("🚀 Generate Emails", type="primary", use_container_width=True, disabled=(not selected_api_key_name)):
            st.session_state.generation_started = True
            st.session_state.stop_processing = False
            df = pd.read_csv(uploaded_file)
            if "Email Body" not in df.columns: df["Email Body"] = ""
            st.session_state.results_df = df
            st.rerun()

    if st.session_state.generation_started:
        df = st.session_state.results_df
        st.header("📊 Generation Progress")
        progress_bar = st.progress(0, text="Starting...")
        col1, col2, col3 = st.columns(3)
        success_placeholder = col1.empty()
        error_placeholder = col2.empty()
        status_placeholder = col3.empty()
        stop_button_placeholder = st.empty()
        if stop_button_placeholder.button("⏹️ Stop Processing", use_container_width=True):
            st.session_state.stop_processing = True

        try:
            api_key = all_api_keys[selected_api_key_name]
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel("gemini-1.5-flash")
            with open('company_info.txt', 'r', encoding='utf-8') as f: company_info_text = f.read()
            with open('sample_emails.json', 'r', encoding='utf-8') as f: sample_emails = json.load(f)
            few_shot_examples_text = "".join([f"--- EXAMPLE {i+1} ({ex['industry']}) ---\n{ex['email_body']}\n\n" for i, ex in enumerate(sample_emails)])
            
            client_references = {
                "automation": ["Unbox Robotics", "Yantrana Systems", "Uno Minda", "Plexware Automation"],
                "aerospace": ["Sagar Defence", "DRDO", "Ikran Aerospace", "EtherealX", "Manstu Aerospace", "TMPL"],
                "industrial": ["Proarc", "Kirloskar Pneumatics", "Yazaki", "V-Tech Engineering", "Zimmer Group", "Warade Pactech"],
                "automobile": ["Octarange Technology", "Hyrovert", "Tritium Motors", "Ground Mobile", "Navnit Motors", "Clean Electric"]
            }
            
            processed_emails_cache, total_rows = {}, len(df)

            for i, row in df.iterrows():
                if pd.notna(row.get("Email Body")) and len(str(row.get("Email Body"))) > 10: continue
                if st.session_state.stop_processing:
                    st.warning("Processing stopped by user."); break
                try:
                    current_stats = calculate_stats(df)
                    progress_bar.progress((i + 1) / total_rows, text=f"Processing row {i+1} of {total_rows}")
                    success_placeholder.metric("✅ Generated", f"{current_stats['generated']}")
                    error_placeholder.metric("❌ Errors", f"{current_stats['errors']}")
                    status_placeholder.text(f"Current: {row['Company']}")

                    company, website, industry = str(row["Company"]), str(row["Website"]), str(row["Industry"]).lower()
                    normalized_company = company.lower().strip()

                    if normalized_company in processed_emails_cache:
                        df.at[i, "Email Body"] = processed_emails_cache[normalized_company]
                    elif not website.startswith("http"):
                        df.at[i, "Email Body"] = "ERROR: Invalid website URL"
                    else:
                        website_text = get_website_text(website)
                        if not website_text:
                            df.at[i, "Email Body"] = "ERROR: Could not fetch website"
                        else:
                            industry_key = next((key for key in client_references if key in industry), None)
                            past_clients = client_references.get(industry_key, [])
                            client_reference_text = ', '.join(past_clients) if past_clients else 'top-tier clients'

                            # --- FULL, DETAILED PROMPT IS INCLUDED ---
                            final_prompt = f"""
**Your Role:** You are a highly skilled salesperson for "Cad & Cart." Your goal is to write a personalized, impressive, and effective cold email.

**Knowledge Base 1: Your Company's Information (Cad & Cart):**
{company_info_text}

**Knowledge Base 2: Prospect Company "{company}" Information:**
Here is the raw text from their website. Find specific, impressive details to use in the opening hook.
---
{website_text}
---

**Gold Standard Examples (Learn from this style, tone, and quality):**
{few_shot_examples_text}

**Your Final Task - Write the Email:**
Now, write a new, unique email body for "{company}".
Act as a salesperson for Cad & Cart when writing emails. Emails should be:
- Focused and goal-oriented
- Conversational yet formal
- Personalized with uncommon commonalities
- Concise and easy to read
- Credible (include useful data or connections)
- Reader-centric (address their problems)
- Respectful of the recipient's time (no demands)
- Include a clear call to action
Follow these rules STRICTLY:
1.  **Opening:** Start with a strong, personalized opening hook based on the Prospect's website text. DO NOT use generic lead-ins like "Given that..." or "Based on...".
2.  **Content:** Seamlessly integrate Cad & Cart's capabilities. Reference our work with companies like {client_reference_text}.
3.  **Closing:** End with a soft call to action for a short call or discussion.
4.  **Formatting:** Use plain text only. No markdown (like bold or asterisks).
5.  **Crucial Instruction on Output:** You MUST generate ONLY the email body. Your entire output must start with the first sentence of the email (e.g., "We've been following...") and end with the last sentence of the call to action (e.g., "...another way."). Do NOT include a subject line, a greeting (like "Dear..."), or any sign-off (like "Sincerely," or your name).
"""
                            response = model.generate_content(final_prompt)
                            email_body = response.text.strip()
                            df.at[i, "Email Body"] = email_body
                            processed_emails_cache[normalized_company] = email_body
                    time.sleep(delay_seconds)
                except Exception as e:
                    df.at[i, "Email Body"] = f"ERROR: {e}"
                    continue
                finally:
                    st.session_state.results_df = df.copy()
        finally:
            st.session_state.generation_started = False
            stop_button_placeholder.empty()
            st.rerun()

if st.session_state.results_df is not None:
    st.header("📋 Results")
    st.dataframe(st.session_state.results_df)

    final_stats = calculate_stats(st.session_state.results_df)
    with st.container(border=True):
        st.subheader("Generation Summary:")
        st.markdown(f"""
            - **Emails generated:** {final_stats['generated']}
            - **Errors encountered:** {final_stats['errors']}
            - **Total rows processed:** {final_stats['total_processed']} / {final_stats['total_rows']}
        """)
        st.info("⬇️ The Excel file below contains all results generated so far.")

    excel_data = to_excel(st.session_state.results_df)
    st.download_button(
        label="📥 Download Results as Excel", data=excel_data, file_name=f"generated_emails_{int(time.time())}.xlsx",
        mime="application/vnd.ms-excel", type="primary", use_container_width=True
    )