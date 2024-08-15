import streamlit as st
import time
from datetime import datetime
import random
import json
import os
from filelock import FileLock

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
        state = load_state()
        self.id = str(len(state["duels"]) + 1)
        self.user1_id = user1_id
        self.user2_id = user2_id
        self.winner_id = None
        self.code_snippet = generate_code_snippet()
        self.start_time = str(datetime.now())
        self.errors_found = {user1_id: [], user2_id: []}
        state["duels"][self.id] = self.__dict__
        save_state(state)


def generate_code_snippet():
    snippets = [
        """
def calculate_sum(a, b):
    return a - b  # Error: should be addition

result = calculates_um(5, 3)  # Error: function name is incorrect
print("The sum is: " + result)  # Error: result is int, not string
        """,
        """
def find_max(numbers):
    max_num = numbers[0]
    for num in numbers
        if num > max_num:
            max_num = num
    return max_num

numbers = [1, 5, 3, 8, 2]
result = findmax(numbers)
print(f"The maximum number is: {results}")
        """
    ]
    return random.choice(snippets)


def find_opponent():
    state = load_state()
    if len(state["queue"]) > 1:
        user1_id = state["queue"].pop(0)
        user2_id = state["queue"].pop(0)
        new_duel = Duel(user1_id, user2_id)
        state["duels"][new_duel.id] = new_duel.__dict__
        # Remove both users from the queue
        state["queue"] = [uid for uid in state["queue"] if uid not in [user1_id, user2_id]]
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

    save_state(state)


def main():
    st.set_page_config(page_title="Debug Duel", page_icon="🐞", layout="wide")
    st.title("🐞 Debug Duel")

    if "user_id" not in st.session_state:
        st.session_state.user_id = None
    if "in_queue" not in st.session_state:
        st.session_state.in_queue = False
    if "duel_id" not in st.session_state:
        st.session_state.duel_id = None

    state = load_state()

    if not st.session_state.user_id:
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("""
            # Welcome to Debug Duel!
            Test your debugging skills against other players in real-time.
            How to play:
            1. Enter your username
            2. Click 'Start' to join
            3. Find an opponent
            4. Debug the code snippet faster than your opponent
            5. Climb the leaderboard!
            """)
        with col2:
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
            # Check if the user is in an active duel
            active_duel_id = check_for_active_duel(user_id)

            if active_duel_id:
                st.session_state.duel_id = active_duel_id
                st.session_state.in_queue = False

            if not st.session_state.duel_id:
                if not st.session_state.in_queue:
                    if st.button("Find Opponent"):
                        state["queue"].append(user_id)
                        save_state(state)
                        st.session_state.in_queue = True
                        st.info("Searching for an opponent...")
                        st.rerun()
                else:
                    st.info("Searching for an opponent...")
                    duel_id = find_opponent()
                    if duel_id:
                        st.session_state.duel_id = duel_id
                        st.session_state.in_queue = False
                        st.success("Opponent found! Starting duel...")
                        st.rerun()
                    else:
                        if st.button("Leave Queue"):
                            state["queue"] = [uid for uid in state["queue"] if uid != user_id]
                            save_state(state)
                            st.session_state.in_queue = False
                            st.rerun()

            else:
                duel_id = st.session_state.duel_id
                if duel_id in state["duels"]:
                    duel = state["duels"][duel_id]
                    opponent_id = duel["user2_id"] if user_id == duel["user1_id"] else duel["user1_id"]
                    opponent = state["users"][opponent_id]

                    col1, col2 = st.columns(2)
                    with col1:
                        st.write(f"Your opponent: {opponent['username']}")
                    with col2:
                        elapsed_time = datetime.now() - datetime.fromisoformat(duel["start_time"])
                        st.write(f"Time elapsed: {elapsed_time.seconds} seconds")

                    st.write("Debug the following code:")
                    st.code(duel["code_snippet"], language="python")

                    error_lines = st.multiselect("Select the lines containing errors:",
                                                 options=list(range(1, len(duel["code_snippet"].split('\n')) + 1)),
                                                 default=duel["errors_found"].get(user_id, []))

                    if st.button("Submit Errors"):
                        duel["errors_found"][user_id] = error_lines
                        save_state(state)
                        st.success(f"You found {len(error_lines)} errors!")

                        if duel["errors_found"].get(opponent_id):
                            # Both players have submitted, end the duel
                            if len(error_lines) > len(duel["errors_found"][opponent_id]):
                                winner_id, loser_id = user_id, opponent_id
                            elif len(error_lines) < len(duel["errors_found"][opponent_id]):
                                winner_id, loser_id = opponent_id, user_id
                            else:
                                # If tie, player who submitted first wins
                                winner_id = user_id if user_id == duel["user1_id"] else opponent_id
                                loser_id = opponent_id if winner_id == user_id else user_id

                            update_ratings(winner_id, loser_id)
                            st.session_state.duel_id = None
                            winner = state["users"][winner_id]
                            st.success(f"Duel ended! Winner: {winner['username']}")
                            st.rerun()
                else:
                    st.error("Duel not found. Starting a new search.")
                    st.session_state.duel_id = None
                    st.session_state.in_queue = False
                    st.rerun()

        else:
            st.error("User data not found. Please log in again.")
            st.session_state.user_id = None
            st.rerun()

    # Display leaderboard
    st.sidebar.write("---")
    st.sidebar.write("Leaderboard:")
    sorted_users = sorted(state["users"].values(), key=lambda x: x["rating"], reverse=True)
    for i, user in enumerate(sorted_users[:5], 1):
        st.sidebar.write(f"{i}. {user['username']}: {user['rating']:.0f}")

    # Debug info
    st.sidebar.write("---")
    st.sidebar.write("Debug Info:")
    st.sidebar.write(f"Number of users: {len(state['users'])}")
    st.sidebar.write(f"Queue length: {len(state['queue'])}")
    st.sidebar.write("Users in queue:")
    for user_id in state["queue"]:
        st.sidebar.write(f"- {state['users'][user_id]['username']}")
    st.sidebar.write("Active duels:")
    for duel_id, duel in state["duels"].items():
        st.sidebar.write(f"- Duel {duel_id}: {state['users'][duel['user1_id']]['username']} vs {state['users'][duel['user2_id']]['username']}")


if __name__ == "__main__":
    main()