import streamlit as st
import time
from datetime import datetime, timezone
import random
import json
import os
from filelock import FileLock
from streamlit_server_state import server_state, server_state_lock

DATA_FILE = "game_state.json"
LOCK_FILE = "game_state.lock"


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
    def __init__(self, username):
        state = load_state()
        self.id = str(len(state["users"]) + 1)
        self.username = username
        self.rating = 1000
        state["users"][self.id] = self.__dict__
        save_state(state)


class Duel:
    def __init__(self, user1_id, user2_id):
        self.id = str(int(time.time() * 1000))
        self.user1_id = user1_id
        self.user2_id = user2_id
        self.winner_id = None
        self.code_snippet, self.error_lines = generate_code_snippet()
        self.start_time = datetime.now(timezone.utc).isoformat()
        self.errors_found = {user1_id: [], user2_id: []}
        self.accepted_by = []


def generate_code_snippet():
    snippets = [
        ("""
def calculate_sum(a, b):
    return a - b  # Error: should be addition

result = calculates_um(5, 3)  # Error: function name is incorrect
print("The sum is: " + result)  # Error: result is int, not string
        """, [2, 4, 5]),
        ("""
def find_max(numbers):
    max_num = numbers[0]
    for num in numbers
        if num > max_num:
            max_num = num
    return max_num

numbers = [1, 5, 3, 8, 2]
result = findmax(numbers)
print(f"The maximum number is: {results}")
        """, [4, 9, 10])
    ]
    return random.choice(snippets)


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


def update_ratings(winner_id, loser_id):
    state = load_state()
    K = 32
    winner = state["users"][winner_id]
    loser = state["users"][loser_id]

    expected_winner = 1 / (1 + 10 ** ((loser["rating"] - winner["rating"]) / 400))
    expected_loser = 1 - expected_winner

    winner["rating"] += K * (1 - expected_winner)
    loser["rating"] += K * (0 - expected_loser)

    state["users"][winner_id] = winner
    state["users"][loser_id] = loser
    save_state(state)

    return winner["rating"], loser["rating"]


def end_duel(duel_id, winner_id):
    state = load_state()
    duel = state["duels"][duel_id]
    loser_id = duel["user1_id"] if winner_id == duel["user2_id"] else duel["user2_id"]

    winner_rating, loser_rating = update_ratings(winner_id, loser_id)
    duel["winner_id"] = winner_id
    save_state(state)

    # Notify both users about the duel result and updated ratings
    with server_state_lock["sse_events"]:
        server_state.sse_events[winner_id] = json.dumps({
            "type": "duel_result",
            "result": "win",
            "new_rating": winner_rating
        })
        server_state.sse_events[loser_id] = json.dumps({
            "type": "duel_result",
            "result": "lose",
            "new_rating": loser_rating
        })


def get_leaderboard():
    state = load_state()
    sorted_users = sorted(state["users"].values(), key=lambda x: x["rating"], reverse=True)
    return [{"username": user["username"], "rating": user["rating"]} for user in sorted_users[:5]]


def initialize_sse_events():
    with server_state_lock["sse_events"]:
        if "sse_events" not in server_state:
            server_state.sse_events = {}


def main():
    initialize_sse_events()

    st.set_page_config(page_title="Debug Duel", page_icon="🐞", layout="wide")
    st.title("🐞 Debug Duel")

    if "user_id" not in st.session_state:
        st.session_state.user_id = None
    if "in_queue" not in st.session_state:
        st.session_state.in_queue = False
    if "duel_id" not in st.session_state:
        st.session_state.duel_id = None
    if "selected_lines" not in st.session_state:
        st.session_state.selected_lines = []
    if "last_update" not in st.session_state:
        st.session_state.last_update = time.time()

    state = load_state()

    if not st.session_state.user_id:
        username = st.text_input("Enter your username")
        if st.button("Start"):
            new_user = User(username)
            st.session_state.user_id = new_user.id
            st.success(f"Welcome, {username}!")
            st.rerun()

    else:
        user_id = st.session_state.user_id
        if user_id in state["users"]:
            user = state["users"][user_id]
            st.sidebar.write(f"Player: {user['username']}")
            st.sidebar.write(f"Rating: {user['rating']:.0f}")

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
                duel_id = find_opponent()
                if duel_id:
                    st.session_state.duel_id = duel_id
                    st.session_state.in_queue = False
                    # Notify both users about the new duel
                    with server_state_lock["sse_events"]:
                        duel = state["duels"].get(duel_id)
                        if duel:
                            for participant_id in [duel.get("user1_id"), duel.get("user2_id")]:
                                if participant_id:
                                    server_state.sse_events[participant_id] = json.dumps(
                                        {"type": "new_duel", "duel_id": duel_id})
                        else:
                            st.error(f"Duel with id {duel_id} not found in state.")
                    st.rerun()
                elif st.button("Leave Queue", key="leave_queue"):
                    state["queue"] = [uid for uid in state["queue"] if uid != user_id]
                    save_state(state)
                    st.session_state.in_queue = False
                    st.rerun()

        else:
            st.error("User data not found. Please log in again.")
            st.session_state.user_id = None
            st.rerun()

    # Display leaderboard
    st.sidebar.write("---")
    st.sidebar.write("Leaderboard:")
    leaderboard_placeholder = st.sidebar.empty()
    update_leaderboard(leaderboard_placeholder)

    # Add JavaScript for SSE and real-time updates
    st.markdown("""
    <script>
    const evtSource = new EventSource("/stream");
    evtSource.onmessage = function(event) {
        const data = JSON.parse(event.data);
        if (data.type === "duel_result") {
            if (data.result === "win") {
                alert("Congratulations! You won the duel!");
            } else {
                alert("You lost the duel. Better luck next time!");
            }
            // Update personal rating
            const ratingElement = document.querySelector('p:contains("Rating:")');
            if (ratingElement) {
                ratingElement.textContent = `Rating: ${data.new_rating.toFixed(0)}`;
            }
            // Trigger page reload to update leaderboard
            location.reload();
        } else if (data.type === "new_duel") {
            alert("Opponent found! The duel is starting.");
            location.reload();
        }
    }
    </script>
    """, unsafe_allow_html=True)

    # Periodically check for updates
    if time.time() - st.session_state.last_update > 5:  # Check every 5 seconds
        st.session_state.last_update = time.time()
        st.rerun()


def update_leaderboard(placeholder):
    leaderboard = get_leaderboard()
    placeholder.write(
        "\n".join([f"{i + 1}. {user['username']}: {user['rating']:.0f}" for i, user in enumerate(leaderboard)]))


def show_duel_interface(duel_id, user_id):
    state = load_state()
    duel = state["duels"][duel_id]
    opponent_id = duel["user2_id"] if user_id == duel["user1_id"] else duel["user1_id"]
    opponent = state["users"][opponent_id]

    if duel["winner_id"]:
        if duel["winner_id"] == user_id:
            st.success("Congratulations! You won the duel!")
        else:
            st.error("You lost the duel. Better luck next time!")
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

    st.write("Debug the following code:")
    code_lines = duel["code_snippet"].strip().split('\n')
    for i, line in enumerate(code_lines, 1):
        col1, col2 = st.columns([10, 1])
        with col1:
            st.code(line, language="python")
        with col2:
            if st.checkbox(f"Error in line {i}", key=f"line_{i}", value=i in st.session_state.selected_lines):
                if i not in st.session_state.selected_lines:
                    st.session_state.selected_lines.append(i)
            else:
                if i in st.session_state.selected_lines:
                    st.session_state.selected_lines.remove(i)

    st.write("Selected error lines:", ", ".join(map(str, sorted(st.session_state.selected_lines))))

    if st.button("Submit Guesses", key="submit_guesses"):
        duel["errors_found"][user_id] = st.session_state.selected_lines
        save_state(state)

        if set(duel["errors_found"][user_id]) == set(duel["error_lines"]):
            end_duel(duel_id, user_id)
            st.success("Congratulations! You found all the errors and won the duel!")
            st.rerun()
        else:
            st.write("Correct errors found:", ", ".join(
                map(str, sorted([line for line in duel["errors_found"][user_id] if line in duel["error_lines"]]))))
            if set(duel["errors_found"][opponent_id]) == set(duel["error_lines"]):
                end_duel(duel_id, opponent_id)
                st.error("Your opponent found all the errors first. Better luck next time!")
                st.rerun()


if __name__ == "__main__":
    initialize_sse_events()
    main()