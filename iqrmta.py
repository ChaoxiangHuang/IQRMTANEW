import streamlit as st
import json
import os
import re
import pandas as pd
from openai import OpenAI

# --- Page Configuration ---
st.set_page_config(layout="wide")

# --- Constants and Configuration ---
CLASS_DATA_FILE = "iqrm_summaries_answers.json"
COURSE_INFO_FILE = "course_info.json"
EXCEL_DATA_DIR = "class_data"
API_KEY = "sk-e5UCdVT-knC7iEtrKwccstG3yZrf_i-hrKJ4dv-QpsT3BlbkFJr8PMyVYX7MJ7XipoyCL8HbAtYrbikPRvaioYVwkakA"
client = OpenAI(api_key=API_KEY)

# --- Data Loading & Helper Functions ---
@st.cache_data
def load_class_data(file_path):
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            sorted_keys = sorted(
                [key for key in data if key.startswith('chapter_')],
                key=lambda x: int(x.split('_')[1])
            )
            return {key: data[key] for key in sorted_keys}
    except Exception:
        return {}

@st.cache_data
def load_course_info(file_path):
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {"syllabus_summary": "Syllabus not found.", "answers": {}}

@st.cache_data
def get_class_context_for_llm(class_key):
    class_data = ALL_CLASS_DATA.get(class_key, {})
    json_context = f"The class session covers the following topics and concepts:\n{json.dumps(class_data, indent=2)}\n\n"
    class_num = class_key.split('_')[1]
    excel_path = os.path.join(EXCEL_DATA_DIR, f"iQRM_Class_{int(class_num):02d}.xlsx")
    excel_context = ""
    if os.path.exists(excel_path):
        try:
            xls = pd.ExcelFile(excel_path)
            excel_context += f"Data from the workbook '{os.path.basename(excel_path)}' shows:\n"
            for sheet_name in xls.sheet_names:
                df = pd.read_excel(xls, sheet_name=sheet_name)
                excel_context += f"- Sheet '{sheet_name}' with columns: {', '.join(df.columns)}\n"
        except Exception as e:
            excel_context += f"Could not read Excel workbook: {e}\n"
    else:
        excel_context = "No Excel workbook found for this class.\n"
    return json_context + excel_context

def get_ai_response(prompt, context):
    if not client: return "Chatbot is disabled due to missing API key."
    system_prompt = "You are an AI Teaching Assistant for QRM. Based *only* on the provided context, answer the user's question. If the answer isn't in the context, say so."
    user_prompt = f"CONTEXT:\n{context}\n\nUSER'S QUESTION:\n{prompt}"
    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
            temperature=0.3,
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"An error occurred: {e}"

# --- NEW: Function to read class from URL on first load ---
def get_class_key_from_url():
    param_value = st.query_params.get("info")
    if not param_value:
        return None
    match = re.match(r"chapter(\d+)", param_value, re.IGNORECASE)
    if match:
        class_num = match.group(1)
        class_key = f"chapter_{class_num}"
        if class_key in ALL_CLASS_DATA:
            return class_key
    return None

# --- Callback Function to Handle Dropdown Actions ---
def process_action():
    class_key = st.session_state.class_key
    action_key = f"action_selector_{class_key}"
    selected_action = st.session_state.get(action_key)
    if not selected_action: return

    chat_key = f"chat_{class_key}"
    st.session_state[chat_key].append({"role": "user", "content": selected_action})
    class_data = ALL_CLASS_DATA.get(class_key, {})
    response = ""

    if selected_action == "List the topics in this class":
        topics = list(class_data.keys())
        response = "Here are the topics for this class session:\n\n" + "\n".join([f"* **{topic}**" for topic in topics]) if topics else "No topics found."
    elif selected_action == "Get a tutorial on a topic":
        tutorial_content = [f"**{topic}** - {data.get('summary', 'Not available.')}" for topic, data in class_data.items()]
        response = "Here is a tutorial summary for each topic:\n\n" + "\n\n".join(tutorial_content) if tutorial_content else "No summaries found."
    elif "quizzing" in selected_action or "mastery" in selected_action:
        st.session_state.quiz_mode = "learning" if "learning" in selected_action else "mastery"
        all_questions = [q for topic in class_data.values() for q in topic.get("quiz_questions", [])]
        if not all_questions:
            response = "There are no quiz questions available for this class."
        else:
            if st.session_state.quiz_mode == 'mastery':
                all_questions.sort(key=lambda x: len(x.get("question", "")), reverse=True)
            st.session_state.quiz_questions_list = all_questions
            st.session_state.current_question_index = 0
            st.session_state.score = 0
            st.session_state.last_answer_feedback = "Starting the quiz! Here is your first question."
    
    if response:
         st.session_state[chat_key].append({"role": "assistant", "content": response})

# --- UI Rendering Functions ---
def render_landing_page():
    # Unchanged
    st.title("Welcome to the iQRM Coursebot!")
    st.markdown("You can ask general questions about the course below, or select a class from the menu on the left to begin.")
    if "main_messages" not in st.session_state: st.session_state.main_messages = []
    for message in st.session_state.main_messages:
        with st.chat_message(message["role"]): st.markdown(message["content"])
    course_info = load_course_info(COURSE_INFO_FILE)
    predefined_questions = list(course_info.get("answers", {}).keys())
    selected_question = st.selectbox("Or, select from the dropdown box below:", options=predefined_questions, index=None, placeholder="Select a common question...")
    if selected_question and st.session_state.get("last_question") != selected_question:
        st.session_state.last_question = selected_question
        answer = course_info["answers"].get(selected_question, "I don't have an answer for that.")
        st.session_state.main_messages.append({"role": "user", "content": selected_question})
        st.session_state.main_messages.append({"role": "assistant", "content": answer})
        st.rerun()
    if prompt := st.chat_input("Ask me questions about the course..."):
        st.session_state.main_messages.append({"role": "user", "content": prompt})
        context = course_info.get("syllabus_summary", "")
        response = get_ai_response(prompt, context)
        st.session_state.main_messages.append({"role": "assistant", "content": response})
        st.rerun()

def render_quiz_interface(class_key):
    # Unchanged
    st.subheader(f"Quiz Mode: {st.session_state.quiz_mode.capitalize()}")
    q_index = st.session_state.current_question_index
    questions_list = st.session_state.quiz_questions_list
    if not questions_list:
        st.warning("No quiz questions found for this class."); st.session_state.quiz_mode = None; st.rerun()
    q_data = questions_list[q_index]
    st.progress((q_index + 1) / len(questions_list), text=f"Question {q_index + 1} of {len(questions_list)}")
    if "last_answer_feedback" in st.session_state:
        st.info(st.session_state.last_answer_feedback)
    with st.form(key=f"quiz_form_{class_key}_{q_index}"):
        question_text, choices_dict = q_data.get("question"), q_data.get("choices", {})
        formatted_options = [f"{key}: {value}" for key, value in choices_dict.items()]
        user_answer = st.radio(f"**{question_text}**", options=formatted_options, index=None)
        submitted = st.form_submit_button("Submit Answer")
        if st.form_submit_button("Exit Quiz", type="secondary"):
            st.session_state.quiz_mode = None; st.session_state.last_answer_feedback = None; st.rerun()
    if submitted:
        user_choice = user_answer.split(':')[0] if user_answer else None
        correct_choice = q_data.get("correct")
        if user_choice == correct_choice:
            st.session_state.score += 1; st.session_state.last_answer_feedback = "Correct! 🎉 Here is the next question."
        else:
            st.session_state.last_answer_feedback = f"Not quite. The correct answer was **{correct_choice}**. Here is the next question."
        if q_index + 1 < len(questions_list):
            st.session_state.current_question_index += 1
        else:
            st.success(f"Quiz complete! Your final score is {st.session_state.score}/{len(questions_list)}.")
            st.session_state.quiz_mode = None; st.session_state.last_answer_feedback = None
        st.rerun()

def render_class_page(class_key):
    # Unchanged
    class_num = class_key.split('_')[1]
    st.title(f"Welcome to iQRM Classbot {int(class_num):02d}")
    if st.session_state.get("quiz_mode"):
        render_quiz_interface(class_key); return
    chat_key = f"chat_{class_key}"
    action_key = f"action_selector_{class_key}"
    if chat_key not in st.session_state: st.session_state[chat_key] = []
    for message in st.session_state[chat_key]:
        with st.chat_message(message["role"]): st.markdown(message["content"])
    actions = ["List the topics in this class", "Learn through quizzing", "Test for mastery", "Get a tutorial on a topic"]
    st.selectbox("Select an action:", options=actions, index=None, placeholder="Choose an action...", key=action_key, on_change=process_action)
    if prompt := st.chat_input(f"Ask Classbot {int(class_num):02d} something else..."):
        context = get_class_context_for_llm(class_key)
        llm_response = get_ai_response(prompt, context)
        st.session_state[chat_key].append({"role": "user", "content": prompt})
        st.session_state[chat_key].append({"role": "assistant", "content": llm_response})
        st.rerun()

# --- Main Application Logic & Router ---
ALL_CLASS_DATA = load_class_data(CLASS_DATA_FILE)

# --- MODIFIED: Initialization logic now checks the URL ---
# This block runs only ONCE per session.
if 'session_initialized' not in st.session_state:
    st.session_state.session_initialized = True
    st.session_state.class_key = None
    st.session_state.quiz_mode = None
    
    # Check the URL for a class key on this first run
    class_key_from_url = get_class_key_from_url()
    if class_key_from_url:
        st.session_state.class_key = class_key_from_url
        st.rerun() # Rerun immediately to load the class page

# --- Sidebar Navigation ---
st.sidebar.title("Classes")
if st.sidebar.button("Home (Coursebot)", use_container_width=True):
    st.session_state.class_key = None
    st.session_state.quiz_mode = None
    if 'info' in st.query_params: st.query_params.clear()
    st.rerun()
st.sidebar.markdown("---")

class_keys = list(ALL_CLASS_DATA.keys())
try:
    current_class_index = class_keys.index(st.session_state.class_key)
except (ValueError, TypeError):
    current_class_index = None

# This selectbox now reads its default value from the session state,
# which may have been set by the URL on the first run.
selected_class = st.sidebar.selectbox(
    "Select a Class Session",
    options=class_keys,
    format_func=lambda key: f"Class {int(key.split('_')[1]):02d}",
    index=current_class_index,
    placeholder="Select a class..."
)
if selected_class != st.session_state.class_key:
    st.session_state.class_key = selected_class
    st.session_state.quiz_mode = None # Reset quiz mode on class change
    if 'info' in st.query_params: st.query_params.clear() # Clear param when navigating manually
    st.rerun()

# --- Page Router ---
if st.session_state.class_key:
    render_class_page(st.session_state.class_key)
else:
    render_landing_page()
