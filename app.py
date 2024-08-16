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
from enum import Enum

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

class BotDifficulty(Enum):
    EASY = "easy"
    HARD = "hard"


def generate_bot_response(duel):
    system_prompt = f"""
    You are an AI assistant tasked with explaining the bugs in a code snippet. The code snippet contains exactly three bugs related to the topic of {duel['topic']}. Your task is to explain these bugs concisely and accurately.
    """
    user_prompt = f"""
    Here is the code snippet with three bugs:

    {duel['code_snippet']}

    Please explain the three bugs in this code snippet. Be concise and accurate in your explanations. Format your response as a list with three items, each explaining one bug.
    """

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    result = ai_api.get_chat_completion(messages)
    return result


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
        self.is_bot_duel = False
        self.bot_difficulty = None  # This will be a string now
        self.topic = random.choice(TOPICS_LIST)


def create_bot_duel(user_id, difficulty):
    bot_id = f"bot_{difficulty.value}"
    new_duel = Duel(user_id, bot_id)
    new_duel.is_bot_duel = True
    new_duel.bot_difficulty = difficulty.value  # Store as a string
    state = load_state()
    state["duels"][new_duel.id] = new_duel.__dict__
    save_state(state)
    return str(new_duel.id)


def bot_find_errors(duel):
    difficulty = BotDifficulty(duel["bot_difficulty"])  # Convert string back to enum
    if difficulty == BotDifficulty.HARD:
        return duel["error_lines"]
    elif difficulty == BotDifficulty.EASY:
        correct_lines = duel["error_lines"]
        all_lines = range(1, len(duel["code_snippet"].split('\n')) + 1)
        wrong_lines = [line for line in all_lines if line not in correct_lines]

        num_correct = random.randint(1, len(correct_lines))
        num_wrong = random.randint(0, 2)

        bot_guess = random.sample(correct_lines, num_correct) + random.sample(wrong_lines, num_wrong)
        return sorted(bot_guess)


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


def send_sse_event(user_id, event_type, data):
    with server_state_lock["sse_events"]:
        server_state.sse_events[user_id] = json.dumps({
            "type": event_type,
            **data
        })


def end_duel(duel_id, winner_id):
    state = load_state()
    duel = state["duels"][duel_id]

    if duel["is_bot_duel"]:
        user_id = duel["user1_id"]
        bot_id = duel["user2_id"]
        user = state["users"][user_id]

        if winner_id == user_id:
            # User wins against bot
            rating_change = 10 if duel["bot_difficulty"] == BotDifficulty.EASY.value else 20
            user["rating"] += rating_change
        else:
            # User loses against bot
            rating_change = -5 if duel["bot_difficulty"] == BotDifficulty.EASY.value else -10
            user["rating"] += rating_change

        duel["winner_id"] = winner_id
        save_state(state)

        send_sse_event(user_id, "duel_result", {
            "result": "win" if winner_id == user_id else "lose",
            "new_rating": user["rating"],
            "rating_change": rating_change
        })
    else:
        loser_id = duel["user2_id"] if winner_id == duel["user1_id"] else duel["user1_id"]

        logging.info(f"Ending duel {duel_id}. Winner: {winner_id}, Loser: {loser_id}")

        winner_rating_before = state["users"][winner_id]["rating"]
        loser_rating_before = state["users"][loser_id]["rating"]

        winner_rating, loser_rating = update_ratings(winner_id, loser_id)

        logging.info(f"Winner rating: {winner_rating_before} -> {winner_rating}")
        logging.info(f"Loser rating: {loser_rating_before} -> {loser_rating}")

        # Update the state with new ratings
        state["users"][winner_id]["rating"] = winner_rating
        state["users"][loser_id]["rating"] = loser_rating
        duel["winner_id"] = winner_id

        save_state(state)

        # Verify the state was saved correctly
        verification_state = load_state()
        logging.info(f"Verified winner rating: {verification_state['users'][winner_id]['rating']}")
        logging.info(f"Verified loser rating: {verification_state['users'][loser_id]['rating']}")

        # Notify both users about the duel result and updated ratings
        send_sse_event(winner_id, "duel_result", {
            "result": "win",
            "new_rating": winner_rating
        })
        send_sse_event(loser_id, "duel_result", {
            "result": "lose",
            "new_rating": loser_rating
        })

        # Update leaderboard for all users
    update_leaderboard_for_all_users()


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


def update_leaderboard_for_all_users():
    state = load_state()  # Ensure we're using the most recent state
    leaderboard = get_leaderboard()
    logging.info(f"Updating leaderboard: {leaderboard}")
    for user_id in state["users"]:
        send_sse_event(user_id, "leaderboard_update", {
            "leaderboard": leaderboard
        })
        # Also send an update for the user's personal rating
        send_sse_event(user_id, "rating_update", {
            "new_rating": state["users"][user_id]["rating"]
        })


def get_leaderboard():
    state = load_state()
    sorted_users = sorted(state["users"].values(), key=lambda x: x["rating"], reverse=True)
    return [{"username": user["username"], "rating": user["rating"]} for user in sorted_users[:5]]


def show_duel_interface(duel_id, user_id):
    state = load_state()
    duel = state["duels"][duel_id]

    if duel["is_bot_duel"]:
        opponent_id = duel["user2_id"]  # This should be the bot's ID (e.g., "bot_easy" or "bot_hard")
        opponent = {"username": f"{duel['bot_difficulty'].capitalize()} Bot"}
    else:
        opponent_id = duel["user2_id"] if user_id == duel["user1_id"] else duel["user1_id"]
        opponent = state["users"][opponent_id]

    # Check if the duel has already ended
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

        if duel["is_bot_duel"]:
            st.write(
                f"Bot correct errors: {len([e for e in duel['errors_found'][opponent_id] if e in duel['error_lines']])}")
            st.write(
                f"Bot incorrect errors: {len([e for e in duel['errors_found'][opponent_id] if e not in duel['error_lines']])}")
        else:
            st.write(
                f"Opponent correct errors: {len([e for e in duel['errors_found'][opponent_id] if e in duel['error_lines']])}")
            st.write(
                f"Opponent incorrect errors: {len([e for e in duel['errors_found'][opponent_id] if e not in duel['error_lines']])}")

        if st.button("Start New Duel"):
            st.session_state.duel_id = None
            st.session_state.selected_lines = []
            st.rerun()
        return

    # Initialize selected_lines if not present
    if "selected_lines" not in st.session_state:
        st.session_state.selected_lines = []

    col1, col2 = st.columns(2)
    with col1:
        st.write(f"Your opponent: {opponent['username']}")
    with col2:
        elapsed_time = datetime.now(timezone.utc) - datetime.fromisoformat(duel["start_time"])
        st.write(f"Time elapsed: {elapsed_time.total_seconds():.0f} seconds")

    st.write("Find bugs in the following code before your opponent does!")

    # Display unified code block
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

        if duel["is_bot_duel"]:
            bot_errors = bot_find_errors(duel)
            duel["errors_found"][opponent_id] = bot_errors
            duel["submission_time"][opponent_id] = datetime.now(timezone.utc).isoformat()
            save_state(state)
            determine_winner(duel_id)
            st.rerun()
        else:
            save_state(state)
            if duel["submission_time"][user_id] and duel["submission_time"][opponent_id]:
                determine_winner(duel_id)
                st.rerun()
            else:
                st.info("Waiting for your opponent to submit their guesses...")
                st.rerun()

    # Display opponent's progress
    if duel["is_bot_duel"]:
        st.write("Bot will submit its guesses after you.")
    else:
        opponent_errors_found = len(duel['errors_found'][opponent_id]) if opponent_id in duel['errors_found'] else 0
        st.write(f"Opponent errors found: {opponent_errors_found}")


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
        winner_id = None  # It's a tie

    if winner_id:
        end_duel(duel_id, winner_id)
    else:
        # Handle tie
        duel["winner_id"] = "tie"
        save_state(state)
        if duel["is_bot_duel"]:
            send_sse_event(user1_id, "duel_result", {"result": "tie"})
        else:
            send_sse_event(user1_id, "duel_result", {"result": "tie"})
            send_sse_event(user2_id, "duel_result", {"result": "tie"})


def update_leaderboard(placeholder):
    leaderboard = get_leaderboard()
    placeholder.write(
        "\n".join([f"{i + 1}. {user['username']}: {user['rating']:.0f}" for i, user in enumerate(leaderboard)]))


def initialize_sse_events():
    with server_state_lock["sse_events"]:
        if "sse_events" not in server_state:
            server_state.sse_events = {}


def get_random_topic():
    return random.choice(TOPICS_LIST)


def main():
    initialize_sse_events()

    st.set_page_config(page_title="Debug Duel", page_icon="🐞", layout="wide")
    st.title("🐞 Debug Duel")

    state = load_state()

    if not st.session_state['user_id']:
        col1, col2 = st.columns(2)
        with col1:
            login_user()
        with col2:
            register_user()
    else:
        logout_user()
        user_id = st.session_state['user_id']
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
                st.subheader("Choose Your Opponent")
                col1, col2, col3 = st.columns(3)
                with col1:
                    if st.button("Find Human Opponent", key="find_opponent"):
                        state["queue"].append(user_id)
                        save_state(state)
                        st.session_state.in_queue = True
                        st.rerun()
                with col2:
                    if st.button("Play Against Easy Bot", key="easy_bot"):
                        duel_id = create_bot_duel(user_id, BotDifficulty.EASY)
                        st.session_state.duel_id = duel_id
                        st.rerun()
                with col3:
                    if st.button("Play Against Hard Bot", key="hard_bot"):
                        duel_id = create_bot_duel(user_id, BotDifficulty.HARD)
                        st.session_state.duel_id = duel_id
                        st.rerun()
            else:
                st.info("Searching for a human opponent...")
                topic_placeholder = st.empty()
                duel_id = find_opponent()
                if duel_id:
                    st.session_state.duel_id = duel_id
                    st.session_state.in_queue = False
                    # Notify both users about the new duel
                    with server_state_lock["sse_events"]:
                        duel = state["duels"].get(duel_id)
                        if duel:
                            for participant_id in [duel["user1_id"], duel["user2_id"]]:
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
            st.session_state['user_id'] = None
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
        switch(data.type) {
            case "duel_result":
                handleDuelResult(data);
                break;
            case "leaderboard_update":
                updateLeaderboard(data.leaderboard);
                break;
            case "duel_update":
                updateDuelInterface(data);
                break;
            case "new_duel":
                handleNewDuel(data);
                break;
            case "rating_update":
                updatePersonalRating(data.new_rating);
                break;
        }
    }

    function handleDuelResult(data) {
        if (data.result === "win") {
            alert(`Congratulations! You won the duel! Rating change: ${data.rating_change}`);
        } else if (data.result === "lose") {
            alert(`You lost the duel. Better luck next time! Rating change: ${data.rating_change}`);
        } else if (data.result === "tie") {
            alert("The duel ended in a tie!");
        }
        updatePersonalRating(data.new_rating);
    }

    function updateLeaderboard(leaderboard) {
        const leaderboardElement = document.querySelector('.element-container:contains("Leaderboard:")');
        if (leaderboardElement) {
            const leaderboardHtml = leaderboard.map((user, index) => 
                `${index + 1}. ${user.username}: ${user.rating.toFixed(0)}`
            ).join('<br>');
            leaderboardElement.innerHTML = `<p>Leaderboard:</p>${leaderboardHtml}`;
        }
    }

    function updatePersonalRating(newRating) {
        const ratingElement = document.querySelector('p:contains("Rating:")');
        if (ratingElement) {
            ratingElement.textContent = `Rating: ${newRating.toFixed(0)}`;
        }
    }

    function updateDuelInterface(data) {
        const opponentErrorsElement = document.querySelector('p:contains("Opponent errors found:")');
        if (opponentErrorsElement) {
            opponentErrorsElement.textContent = `Opponent errors found: ${data.opponent_errors}`;
        }
    }

    function handleNewDuel(data) {
        alert("Opponent found! The duel is starting.");
        location.reload();
    }

    // Function to update the current topic with blinking effect
    function updateTopic() {
        const topicElement = document.querySelector('div[data-testid="stText"] p:contains("Current topic:")');
        if (topicElement) {
            topicElement.style.transition = 'opacity 0.5s';
            topicElement.style.opacity = 0;
            setTimeout(() => {
                topicElement.style.opacity = 1;
            }, 500);
        }
    }

    // Update topic every second while in queue
    let topicInterval;
    function startTopicUpdate() {
        topicInterval = setInterval(updateTopic, 1000);
    }

    function stopTopicUpdate() {
        clearInterval(topicInterval);
    }

    // Check if in queue and start/stop topic update accordingly
    function checkQueueStatus() {
        const inQueue = document.querySelector('div:contains("Searching for a human opponent...")');
        if (inQueue) {
            startTopicUpdate();
        } else {
            stopTopicUpdate();
        }
    }

    // Initial check and periodic check for queue status
    checkQueueStatus();
    setInterval(checkQueueStatus, 1000);
    </script>
    """, unsafe_allow_html=True)

    # Periodically check for updates and update the topic
    if st.session_state.in_queue:
        current_time = time.time()
        if 'last_topic_update' not in st.session_state or current_time - st.session_state.last_topic_update > 1:
            st.session_state.last_topic_update = current_time
            topic = get_random_topic()
            topic_placeholder.write(f"Current topic: {topic[0]} - {topic[1]}")
            st.rerun()

    if time.time() - st.session_state.last_update > 15:  # Check every 15 seconds
        st.session_state.last_update = time.time()
        st.rerun()


if __name__ == "__main__":
    initialize_sse_events()
    main()