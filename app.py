import streamlit as st
import time
from datetime import datetime
import random

# Use streamlit's session state to persist data across reruns
if 'global_users' not in st.session_state:
    st.session_state.global_users = {}
if 'global_duels' not in st.session_state:
    st.session_state.global_duels = {}
if 'global_queue' not in st.session_state:
    st.session_state.global_queue = []


class User:
    def __init__(self, username):
        self.id = len(st.session_state.global_users) + 1
        self.username = username
        self.rating = 1000


class Duel:
    def __init__(self, user1_id, user2_id):
        self.id = len(st.session_state.global_duels) + 1
        self.user1_id = user1_id
        self.user2_id = user2_id
        self.winner_id = None
        self.code_snippet = generate_code_snippet()
        self.start_time = datetime.now()
        self.errors_found = {user1_id: [], user2_id: []}


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
    if len(st.session_state.global_queue) > 1:
        user1 = st.session_state.global_queue.pop(0)
        user2 = st.session_state.global_queue.pop(0)
        new_duel = Duel(user1, user2)
        st.session_state.global_duels[new_duel.id] = new_duel
        return new_duel.id
    return None


def update_ratings(winner_id, loser_id):
    K = 32
    winner = st.session_state.global_users[winner_id]
    loser = st.session_state.global_users[loser_id]

    expected_winner = 1 / (1 + 10 ** ((loser.rating - winner.rating) / 400))
    expected_loser = 1 - expected_winner

    winner.rating += K * (1 - expected_winner)
    loser.rating += K * (0 - expected_loser)


def initialize_session_state():
    if 'user_id' not in st.session_state:
        st.session_state.user_id = None
    if 'in_queue' not in st.session_state:
        st.session_state.in_queue = False
    if 'duel_id' not in st.session_state:
        st.session_state.duel_id = None


def main():
    st.set_page_config(page_title="Debug Duel", page_icon="🐞", layout="wide")
    st.title("🐞 Debug Duel")

    initialize_session_state()

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
                st.session_state.global_users[new_user.id] = new_user
                st.session_state.user_id = new_user.id
                st.success(f"Welcome, {username}!")
                st.rerun()

    else:
        user_id = st.session_state.user_id
        if user_id in st.session_state.global_users:
            user = st.session_state.global_users[user_id]
            st.sidebar.write(f"Player: {user.username}")
            st.sidebar.write(f"Rating: {user.rating:.0f}")

            if not st.session_state.duel_id:
                if not st.session_state.in_queue:
                    if st.button("Find Opponent"):
                        st.session_state.global_queue.append(user.id)
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
                            st.session_state.global_queue.remove(user.id)
                            st.session_state.in_queue = False
                            st.rerun()

            else:
                duel = st.session_state.global_duels[st.session_state.duel_id]
                opponent_id = duel.user2_id if user.id == duel.user1_id else duel.user1_id
                opponent = st.session_state.global_users[opponent_id]

                col1, col2 = st.columns(2)
                with col1:
                    st.write(f"Your opponent: {opponent.username}")
                with col2:
                    elapsed_time = datetime.now() - duel.start_time
                    st.write(f"Time elapsed: {elapsed_time.seconds} seconds")

                st.write("Debug the following code:")
                st.code(duel.code_snippet, language="python")

                error_lines = st.multiselect("Select the lines containing errors:",
                                             options=list(range(1, len(duel.code_snippet.split('\n')) + 1)),
                                             default=duel.errors_found[user.id])

                if st.button("Submit Errors"):
                    duel.errors_found[user.id] = error_lines
                    st.success(f"You found {len(error_lines)} errors!")

                    if len(duel.errors_found[opponent_id]) > 0:
                        # Both players have submitted, end the duel
                        if len(error_lines) > len(duel.errors_found[opponent_id]):
                            winner_id, loser_id = user.id, opponent_id
                        elif len(error_lines) < len(duel.errors_found[opponent_id]):
                            winner_id, loser_id = opponent_id, user.id
                        else:
                            # If tie, player who submitted first wins
                            winner_id = user.id if user.id == duel.user1_id else opponent_id
                            loser_id = opponent_id if winner_id == user.id else user.id

                        update_ratings(winner_id, loser_id)
                        st.session_state.duel_id = None
                        winner = st.session_state.global_users[winner_id]
                        st.success(f"Duel ended! Winner: {winner.username}")
                        st.rerun()

            # Display leaderboard
            st.sidebar.write("---")
            st.sidebar.write("Leaderboard:")
            sorted_users = sorted(st.session_state.global_users.values(), key=lambda x: x.rating, reverse=True)
            for i, user in enumerate(sorted_users[:5], 1):
                st.sidebar.write(f"{i}. {user.username}: {user.rating:.0f}")
        else:
            st.error("User data not found. Please log in again.")
            st.session_state.user_id = None
            st.rerun()


if __name__ == "__main__":
    main()