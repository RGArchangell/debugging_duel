import streamlit as st
import time
from datetime import datetime, timezone
import random
import json
import os
from filelock import FileLock
from streamlit_server_state import server_state, server_state_lock
from hyperskill_ai_api import HyperskillAIAPI
from topics import TOPICS_LIST
import bcrypt
import secrets
import logging
from streamlit.runtime.scriptrunner import add_script_run_ctx
import threading
from queue import Queue

logging.basicConfig(level=logging.INFO)

DATA_FILE = "game_state.json"
LOCK_FILE = "game_state.lock"

ai_api = HyperskillAIAPI(os.environ["AI_API_KEY"], "claude-3-5-sonnet-20240620")

# Initialize session state variables
if 'user_id' not in st.session_state:
    st.session_state['user_id'] = None
if 'in_queue' not in st.session_state:
    st.session_state.in_queue = False
if 'duel_id' not in st.session_state:
    st.session_state.duel_id = None
if 'selected_lines' not in st.session_state:
    st.session_state.selected_lines = []
if 'last_update' not in st.session_state:
    st.session_state.last_update = time.time()
if 'secret_key' not in st.session_state:
    st.session_state['secret_key'] = secrets.token_hex(16)
if 'current_topic' not in st.session_state:
    st.session_state.current_topic = random.choice(TOPICS_LIST)

# Initialize update queue
update_queue = Queue()


def load_state():
    with FileLock(LOCK_FILE):
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, "r") as f:
                return json.load(f)
        return {"users": {}, "queue": [], "duels": {}}


def save_state(state):
    with FileLock(LOCK_FILE):
        with open(DATA_FILE, "w") as f:
            json.dump(state, f)


class User:
    def __init__(self, username, password):
        state = load_state()
        self.id = str(len(state["users"]) + 1)
        self.username = username
        self.password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        self.rating = 1000
        state["users"][self.id] = self.__dict__
        save_state(state)


def authenticate_user(username, password):
    state = load_state()
    for user in state["users"].values():
        if user["username"] == username and bcrypt.checkpw(password.encode('utf-8'), user["password"].encode('utf-8')):
            return user["id"]
    return None


def login_user():
    st.subheader("Login")
    username = st.text_input("Username", key="login_username")
    password = st.text_input("Password", type="password", key="login_password")
    if st.button("Login"):
        user_id = authenticate_user(username, password)
        if user_id:
            st.session_state['user_id'] = user_id
            st.success(f"Welcome back, {username}!")
            st.rerun()
        else:
            st.error("Invalid username or password")


def register_user():
    st.subheader("Register")
    username = st.text_input("Choose a username", key="register_username")
    password = st.text_input("Choose a password", type="password", key="register_password")
    confirm_password = st.text_input("Confirm password", type="password", key="register_confirm_password")
    if st.button("Register"):
        if password != confirm_password:
            st.error("Passwords do not match")
        elif not username or not password:
            st.error("Username and password are required")
        else:
            state = load_state()
            if any(user["username"] == username for user in state["users"].values()):
                st.error("Username already exists")
            else:
                new_user = User(username, password)
                st.session_state['user_id'] = new_user.id
                st.success("Registration successful!")
                st.rerun()


def logout_user():
    if st.sidebar.button("Logout"):
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.rerun()


def generate_code_snippet():
    topic = random.choice(TOPICS_LIST)

    system_prompt = f"""
    You are a mischievous coding assistant tasked with creating intentionally flawed code snippets. Your goal is to generate a code snippet on the specified {topic[0]} using the {topic[1]}. However, you MUST introduce EXACTLY THREE BUGS into the code that are DIRECTLY RELATED to the given topic. These bugs should be subtle enough to not be immediately obvious, but significant enough to cause issues when the code is run or implemented.
    """
    user_prompt = f"""
    Do not provide any explanations, comments, or annotations within the code. Output only the raw code snippet with the embedded bugs. The bugs should be logical errors, syntax mistakes, or implementation flaws that are specific to the topic and programming language provided.

    Remember, your task is to create code that appears functional at first glance but contains hidden flaws. Be creative in your bug placement, ensuring they are diverse and not trivially fixable. The code should compile (if applicable to the language) but fail or produce incorrect results when executed.
    DO NOT write empty lines in the code snippet!
    MAXIMUM AMOUNT OF LINES IN CODE SNIPPET: 10. NO MORE!
    After generated code, explain the errors in generated code snippet in the following format:
    **BUGS LIST**
    Line number: correct implementation for this line (with fixed bug)
    DO NOT WRITE ANYTHING OTHER THAN THAT!
    Remember: there are EXACLTY 3 LINES WITH BUGS! NO MORE!
    """

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    result = ai_api.get_chat_completion(messages)
    code_part, bugs_part = result.split("**BUGS LIST**")

    bug_lines = []
    for line in bugs_part.strip().split('\n'):
        line_number = int(line.split(':')[0].split()[-1])
        bug_lines.append(line_number)
    return code_part.strip(), bug_lines


class Duel:
    def __init__(self, user1_id, user2_id):
        self.id = str(int(time.time() * 1000))
        self.user1_id = user1_id
        self.user2_id = user2_id
        self.winner_id = None
        self.code_snippet, self.error_lines = generate_code_snippet()
        self.start_time = datetime.now(timezone.utc).isoformat()
        self.errors_found = {user1_id: [], user2_id: []}
        self.submission_time = {user1_id: None, user2_id: None}
        self.accepted_by = []


def find_opponent():
    state = load_state()
    if len(state["queue"]) > 1:
        user1_id = state["queue"].pop(0)
        user2_id = state["queue"].pop(0)
        new_duel = Duel(user1_id, user2_id)
        state["duels"][new_duel.id] = new_duel.__dict__
        save_state(state)
        return str(new_duel.id)
    return None


def check_for_active_duel(user_id):
    state = load_state()
    for duel_id, duel in state["duels"].items():
        if user_id in [duel["user1_id"], duel["user2_id"]] and duel["winner_id"] is None:
            return duel_id
    return None


def end_duel(duel_id, winner_id):
    state = load_state()
    duel = state["duels"][duel_id]
    loser_id = duel["user2_id"] if winner_id == duel["user1_id"] else duel["user1_id"]

    logging.info(f"Ending duel {duel_id}. Winner: {winner_id}, Loser: {loser_id}")

    winner_rating_before = state["users"][winner_id]["rating"]
    loser_rating_before = state["users"][loser_id]["rating"]

    winner_rating, loser_rating = update_ratings(winner_id, loser_id)

    logging.info(f"Winner rating: {winner_rating_before} -> {winner_rating}")
    logging.info(f"Loser rating: {loser_rating_before} -> {loser_rating}")

    state["users"][winner_id]["rating"] = winner_rating
    state["users"][loser_id]["rating"] = loser_rating
    duel["winner_id"] = winner_id

    save_state(state)

    verification_state = load_state()
    logging.info(f"Verified winner rating: {verification_state['users'][winner_id]['rating']}")
    logging.info(f"Verified loser rating: {verification_state['users'][loser_id]['rating']}")

    update_queue.put({
        'type': 'duel_result',
        'winner_id': winner_id,
        'loser_id': loser_id,
        'winner_rating': winner_rating,
        'loser_rating': loser_rating
    })


def update_ratings(winner_id, loser_id):
    state = load_state()
    K = 32
    winner = state["users"][winner_id]
    loser = state["users"][loser_id]

    expected_winner = 1 / (1 + 10 ** ((loser["rating"] - winner["rating"]) / 400))
    expected_loser = 1 - expected_winner

    new_winner_rating = winner["rating"] + K * (1 - expected_winner)
    new_loser_rating = loser["rating"] + K * (0 - expected_loser)

    logging.info(f"Calculated new ratings - Winner: {new_winner_rating}, Loser: {new_loser_rating}")

    return new_winner_rating, new_loser_rating


def get_leaderboard():
    state = load_state()
    sorted_users = sorted(state["users"].values(), key=lambda x: x["rating"], reverse=True)
    return [{"username": user["username"], "rating": user["rating"]} for user in sorted_users[:5]]


def show_duel_interface(duel_id, user_id):
    state = load_state()
    duel = state["duels"][duel_id]
    opponent_id = duel["user2_id"] if user_id == duel["user1_id"] else duel["user1_id"]
    opponent = state["users"][opponent_id]

    if duel["winner_id"]:
        if duel["winner_id"] == user_id:
            st.success("Congratulations! You won the duel!")
        elif duel["winner_id"] == "tie":
            st.info("The duel ended in a tie!")
        else:
            st.error(f"The duel has ended. {opponent['username']} found more correct errors.")

        st.write("Final results:")
        st.write(f"Your correct errors: {len([e for e in duel['errors_found'][user_id] if e in duel['error_lines']])}")
        st.write(
            f"Your incorrect errors: {len([e for e in duel['errors_found'][user_id] if e not in duel['error_lines']])}")
        st.write(
            f"Opponent correct errors: {len([e for e in duel['errors_found'][opponent_id] if e in duel['error_lines']])}")
        st.write(
            f"Opponent incorrect errors: {len([e for e in duel['errors_found'][opponent_id] if e not in duel['error_lines']])}")

        if st.button("Start New Duel"):
            st.session_state.duel_id = None
            st.session_state.selected_lines = []
            st.rerun()
        return

    col1, col2 = st.columns(2)
    with col1:
        st.write(f"Your opponent: {opponent['username']}")
    with col2:
        elapsed_time = datetime.now(timezone.utc) - datetime.fromisoformat(duel["start_time"])
        st.write(f"Time elapsed: {elapsed_time.total_seconds():.0f} seconds")

    st.write("Find bugs in the following code before your opponent does!")

    st.code(duel["code_snippet"].strip(), language="cpp")

    st.write("Select the lines containing errors:")

    code_lines = duel["code_snippet"].strip().split('\n')
    for i, line in enumerate(code_lines, 1):
        col1, col2 = st.columns([10, 1])
        with col1:
            st.code(line, language="cpp")
        with col2:
            if st.checkbox("", key=f"line_{i}", value=i in st.session_state.selected_lines):
                if i not in st.session_state.selected_lines:
                    st.session_state.selected_lines.append(i)
            else:
                if i in st.session_state.selected_lines:
                    st.session_state.selected_lines.remove(i)

    st.write("Selected error lines:", ", ".join(map(str, sorted(st.session_state.selected_lines))))

    if st.button("Submit Guesses", key="submit_guesses"):
        duel["errors_found"][user_id] = st.session_state.selected_lines
        duel["submission_time"][user_id] = datetime.now(timezone.utc).isoformat()
        save_state(state)

        if duel["submission_time"][user_id] and duel["submission_time"][opponent_id]:
            determine_winner(duel_id)
            st.rerun()
        else:
            st.info("Waiting for your opponent to submit their guesses...")
            st.rerun()

    st.write(f"Opponent errors found: {len(duel['errors_found'][opponent_id])}")


def determine_winner(duel_id):
    state = load_state()
    duel = state["duels"][duel_id]
    user1_id, user2_id = duel["user1_id"], duel["user2_id"]

    user1_correct = len([e for e in duel['errors_found'][user1_id] if e in duel['error_lines']])
    user1_incorrect = len([e for e in duel['errors_found'][user1_id] if e not in duel['error_lines']])
    user2_correct = len([e for e in duel['errors_found'][user2_id] if e in duel['error_lines']])
    user2_incorrect = len([e for e in duel['errors_found'][user2_id] if e not in duel['error_lines']])

    if user1_correct > user2_correct or (user1_correct == user2_correct and user1_incorrect < user2_incorrect):
        winner_id = user1_id
    elif user2_correct > user1_correct or (user1_correct == user2_correct and user2_incorrect < user1_incorrect):
        winner_id = user2_id
    else:
        winner_id = "tie"

    if winner_id != "tie":
        end_duel(duel_id, winner_id)
    else:
        # Handle tie
        duel["winner_id"] = "tie"
        save_state(state)
        update_queue.put({
            'type': 'duel_result',
            'result': 'tie',
            'duel_id': duel_id
        })


@st.cache_data(ttl=1)
def get_current_state():
    return load_state()


def check_for_updates(user_id):
    state = get_current_state()

    # Check for new duels
    for duel_id, duel in state['duels'].items():
        if user_id in [duel['user1_id'], duel['user2_id']] and duel['winner_id'] is None:
            if st.session_state.get('duel_id') != duel_id:
                return {'type': 'new_duel', 'duel_id': duel_id}

    # Check for duel results
    active_duel_id = st.session_state.get('duel_id')
    if active_duel_id and active_duel_id in state['duels']:
        duel = state['duels'][active_duel_id]
        if duel['winner_id']:
            result = 'win' if duel['winner_id'] == user_id else 'lose'
            if duel['winner_id'] == 'tie':
                result = 'tie'
            return {
                'type': 'duel_result',
                'result': result,
                'new_rating': state['users'][user_id]['rating']
            }

    return None


def start_update_checker():
    update_thread = threading.Thread(target=check_for_updates, daemon=True)
    add_script_run_ctx(update_thread)
    update_thread.start()


def process_updates():
    while not update_queue.empty():
        update = update_queue.get()
        if update['type'] == 'new_duel':
            st.session_state.duel_id = update['duel_id']
            st.session_state.in_queue = False
            st.rerun()
        elif update['type'] == 'duel_result':
            st.session_state.duel_result = update
            st.rerun()


def initialize_server_state():
    with server_state_lock["sse_events"]:
        if "sse_events" not in server_state:
            server_state.sse_events = {}


def get_random_topic():
    return random.choice(TOPICS_LIST)


def main():
    st.set_page_config(page_title="Debug Duel", page_icon="🐞", layout="wide")
    st.title("🐞 Debug Duel")

    # Initialize session state variables if not present
    if 'user_id' not in st.session_state:
        st.session_state['user_id'] = None
    if 'in_queue' not in st.session_state:
        st.session_state.in_queue = False
    if 'duel_id' not in st.session_state:
        st.session_state.duel_id = None
    if 'selected_lines' not in st.session_state:
        st.session_state.selected_lines = []

    # User Authentication
    if not st.session_state['user_id']:
        col1, col2 = st.columns(2)
        with col1:
            login_user()
        with col2:
            register_user()
    else:
        # Logout button
        if st.sidebar.button("Logout"):
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.rerun()

        user_id = st.session_state['user_id']
        state = get_current_state()

        if user_id in state["users"]:
            user = state["users"][user_id]
            st.sidebar.write(f"Player: {user['username']}")
            st.sidebar.write(f"Rating: {user['rating']:.0f}")

            # Check for updates
            update = check_for_updates(user_id)
            if update:
                if update['type'] == 'new_duel':
                    st.session_state.duel_id = update['duel_id']
                    st.session_state.in_queue = False
                    st.rerun()
                elif update['type'] == 'duel_result':
                    st.session_state.duel_result = update
                    st.rerun()

            # Display duel result if available
            if 'duel_result' in st.session_state:
                result = st.session_state.duel_result
                if result['result'] == 'win':
                    st.success("Congratulations! You won the duel!")
                elif result['result'] == 'tie':
                    st.info("The duel ended in a tie!")
                else:
                    st.error("You lost the duel. Better luck next time!")
                st.write(f"Your new rating: {result['new_rating']:.0f}")
                if st.button("Start New Duel"):
                    del st.session_state['duel_result']
                    st.session_state.duel_id = None
                    st.session_state.selected_lines = []
                    st.rerun()
                return

            # Active duel, queue, or find opponent
            active_duel_id = check_for_active_duel(user_id)
            if active_duel_id:
                st.session_state.duel_id = active_duel_id
                st.session_state.in_queue = False

            if st.session_state.duel_id:
                show_duel_interface(st.session_state.duel_id, user_id)
            elif not st.session_state.in_queue:
                if st.button("Find Opponent", key="find_opponent"):
                    state["queue"].append(user_id)
                    save_state(state)
                    st.session_state.in_queue = True
                    st.rerun()
            else:
                st.info("Searching for an opponent...")
                topic_placeholder = st.empty()
                duel_id = find_opponent()
                if duel_id:
                    st.session_state.duel_id = duel_id
                    st.session_state.in_queue = False
                    st.rerun()
                elif st.button("Leave Queue", key="leave_queue"):
                    state["queue"] = [uid for uid in state["queue"] if uid != user_id]
                    save_state(state)
                    st.session_state.in_queue = False
                    st.rerun()

            # Display leaderboard
            st.sidebar.write("---")
            st.sidebar.write("Leaderboard:")
            leaderboard = get_leaderboard()
            for i, user in enumerate(leaderboard, 1):
                st.sidebar.write(f"{i}. {user['username']}: {user['rating']:.0f}")

            # Update current topic while in queue
            if st.session_state.in_queue:
                current_time = time.time()
                if 'last_topic_update' not in st.session_state or current_time - st.session_state.last_topic_update > 1:
                    st.session_state.last_topic_update = current_time
                    topic = get_random_topic()
                    topic_placeholder.write(f"Current topic: {topic[0]} - {topic[1]}")

        else:
            st.error("User data not found. Please log in again.")
            st.session_state['user_id'] = None
            st.rerun()

    # Trigger rerun every second to check for updates
    if st.session_state.get('user_id'):
        time.sleep(1)
        st.rerun()

if __name__ == "__main__":
    main()