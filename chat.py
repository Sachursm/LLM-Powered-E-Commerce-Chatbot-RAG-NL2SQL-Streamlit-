"""
====================================================
  Streamlit Chatbot UI - Plug in your own function
====================================================
  HOW TO USE:
  1. Replace the get_bot_response() function below
     with your own chatbot logic.
  2. Your function receives the full chat history
     (list of dicts) and must return a string reply.
====================================================
"""

import streamlit as st
from faq import get_faq_answer, chain, load_faq_data, generate_answer
from router import rt
import pandas as pd
from pathlib import Path

# ─────────────────────────────────────────────
#  CONFIG — Customize these
# ─────────────────────────────────────────────

PAGE_TITLE = "My Chatbot"    # Browser tab title
BOT_NAME   = "Bot"           # Name shown in chat bubbles

# ─────────────────────────────────────────────
#  YOUR FUNCTION — Replace this with your own!
#  Input : history (list of {"role": ..., "content": ...})
#  Output: reply string
# ─────────────────────────────────────────────
# ── Import your modules
faq_path = Path(__file__).parent / "app/resources/faq_data.csv"
load_faq_data(faq_path)


def get_bot_response(history: list) -> str:
    query = history[-1]["content"]   # ← user's typed message

    # Step 1: Check query type using semantic router
    route_name = rt(query).name    # returns "faq" or "sql"
    route_name = route_name.lower() if route_name else "unknown"
    print(route_name)
    print(f"Route detected: {route_name}")
    # Step 2: Route to correct function
    if route_name == "faq":
        raw = get_faq_answer(query)  # retrieval results
        answer = chain(query)        # final LLM answer
        return answer

    elif route_name == "sql":
        return "SQL questions are not implemented yet."

    else:
        return generate_answer(query,context=history)  # default to LLM answer for unknown routes

# ─────────────────────────────────────────────
#  PAGE SETUP
# ─────────────────────────────────────────────

st.set_page_config(page_title=PAGE_TITLE, page_icon="🤖", layout="centered")

# ─────────────────────────────────────────────
#  CUSTOM CSS — Modify colors/styles here
# ─────────────────────────────────────────────

st.markdown("""
    <style>
        .stApp { background-color: #f5f7fb; }

        /* User bubble — right aligned */
        .user-bubble {
            background-color: #4f8ef7;
            color: white;
            padding: 10px 15px;
            border-radius: 18px 18px 4px 18px;
            margin: 6px 0;
            max-width: 80%;
            margin-left: auto;
            text-align: right;
        }

        /* Bot bubble — left aligned */
        .bot-bubble {
            background-color: #ffffff;
            color: #333;
            padding: 10px 15px;
            border-radius: 18px 18px 18px 4px;
            margin: 6px 0;
            max-width: 80%;
            border: 1px solid #e0e0e0;
        }

        .label { font-size: 12px; color: #888; margin-bottom: 2px; }
    </style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────
#  CHAT HISTORY — Saved in session_state
#  Format: [{"role": "user"/"assistant", "content": "..."}]
#  Access anywhere via: st.session_state.chat_history
# ─────────────────────────────────────────────

if "chat_history" not in st.session_state:
    st.session_state.chat_history = []   # ← your saved Q&A list lives here

# ─────────────────────────────────────────────
#  UI: Header
# ─────────────────────────────────────────────

st.title(f"🤖 {BOT_NAME}")
st.divider()

# ─────────────────────────────────────────────
#  UI: Display Chat History (all previous Q&A)
# ─────────────────────────────────────────────

if not st.session_state.chat_history:
    st.markdown("<p style='color:#aaa;text-align:center;'>No messages yet. Ask something below! 👇</p>", unsafe_allow_html=True)
else:
    for message in st.session_state.chat_history:
        if message["role"] == "user":
            st.markdown(
                f"<div class='label' style='text-align:right;'>You</div>"
                f"<div class='user-bubble'>{message['content']}</div>",
                unsafe_allow_html=True
            )
        else:
            st.markdown(
                f"<div class='label'>{BOT_NAME}</div>"
                f"<div class='bot-bubble'>{message['content']}</div>",
                unsafe_allow_html=True
            )

# ─────────────────────────────────────────────
#  UI: Input box + Send button
# ─────────────────────────────────────────────

st.divider()

with st.form(key="chat_form", clear_on_submit=True):
    col1, col2 = st.columns([5, 1])
    with col1:
        user_input = st.text_input("Message", placeholder="Type your question...", label_visibility="collapsed")
    with col2:
        send_button = st.form_submit_button("Send 🚀")

# ─────────────────────────────────────────────
#  LOGIC: On submit — save input, call your
#         function, save reply, refresh UI
# ─────────────────────────────────────────────

if send_button and user_input.strip():

    # 1. Append user message to history
    st.session_state.chat_history.append({"role": "user", "content": user_input.strip()})

    # 2. Call YOUR function to get a reply
    with st.spinner("Thinking..."):
        try:
            reply = get_bot_response(st.session_state.chat_history)  # ← your function called here
        except Exception as e:
            reply = f"⚠️ Error: {str(e)}"   # graceful error display

    # 3. Append bot reply to history
    st.session_state.chat_history.append({"role": "assistant", "content": reply})

    # 4. Rerun to refresh the chat display
    st.rerun()

# ─────────────────────────────────────────────
#  SIDEBAR: Stats + Clear button
# ─────────────────────────────────────────────

with st.sidebar:
    st.metric("Messages saved", len(st.session_state.chat_history))

    if st.button("🗑️ Clear History", use_container_width=True):
        st.session_state.chat_history = []   # reset history variable
        st.rerun()

    # Uncomment to debug the raw history list:
    # st.json(st.session_state.chat_history)