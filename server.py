import json
import hashlib
import re
import csv
import os
import time
import socket
import threading
from datetime import datetime

HOST = "0.0.0.0"
PORT = 5000

MAX_MESSAGE_LENGTH = 200
MAX_ATTEMPTS = 5
BLOCK_TIME = 60

# -----------------------------
# Server Data
# -----------------------------

clients = {}          # username -> socket
client_info = {}      # username -> details
logged_in_users = set()
lock = threading.Lock()
failed_attempts = {}
blocked_until = {}

CHAT_HISTORY = "chat_history.csv"
SECURITY_LOG = "security_log.txt"
SESSION_TIMEOUT = 300    # 5 minutes

if (not os.path.exists(CHAT_HISTORY)) or os.path.getsize(CHAT_HISTORY) == 0:

    with open(CHAT_HISTORY, "w", newline="") as file:

        writer = csv.writer(file)

        writer.writerow([
            "timestamp",
            "sender",
            "receiver",
            "message_type",
            "message"
        ])

stats = {
    "total_messages": 0,
    "broadcast_messages": 0,
    "private_messages": 0
}

performance = {
    "start_time": time.perf_counter(),
    "delivery_times": []
}

# -----------------------------
# Helper Functions
# -----------------------------

USERS_FILE = "users.json"

def valid_username(username):
    return re.match(r"^[A-Za-z0-9_]{3,20}$", username)

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()


def load_users():
    if not os.path.exists(USERS_FILE):
        return {}

    with open(USERS_FILE, "r") as f:
        return json.load(f)

def current_time():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def log_security_event(username, event):

    with open(SECURITY_LOG, "a") as file:

        file.write(
            f"{current_time()} | {username} | {event}\n"
        )

def save_message(sender, receiver, msg_type, message):

    with open(CHAT_HISTORY, "a", newline="") as file:

        writer = csv.writer(file)

        writer.writerow([
            current_time(),
            sender,
            receiver,
            msg_type,
            message
        ])

def load_last_messages(username):

    messages = []

    if not os.path.exists(CHAT_HISTORY):
        return messages

    with open(CHAT_HISTORY, "r", newline="") as file:

        reader = csv.DictReader(file)

        for row in reader:

            if row.get("sender") == username:
                messages.append(row)

    return messages[-5:]

def print_stats():
    print("\n========== SERVER STATS ==========")
    print("Connected Users :", len(clients))
    print("Broadcast Msgs  :", stats["broadcast_messages"])
    print("Private Msgs    :", stats["private_messages"])
    print("Total Messages  :", stats["total_messages"])
    print("==================================\n")

def save_performance_result(num_clients):

    elapsed = time.perf_counter() - performance["start_time"]

    if performance["delivery_times"]:
        avg_delay = sum(performance["delivery_times"]) / len(performance["delivery_times"])
    else:
        avg_delay = 0

    if elapsed > 0:
        throughput = stats["total_messages"] / elapsed
    else:
        throughput = 0

    with open("performance_results.csv", "a", newline="") as file:

        writer = csv.writer(file)

        writer.writerow([
            num_clients,
            stats["broadcast_messages"],
            stats["private_messages"],
            round(avg_delay, 2),
            round(throughput, 2)
        ])

def broadcast(message, exclude=None):
    """
    Send a message to every connected client.
    """

    with lock:
        dead_clients = []

        for username, sock in clients.items():

            if username == exclude:
                continue

            try:
                sock.send(message.encode())

            except:
                dead_clients.append(username)

        for username in dead_clients:
            remove_client(username)


# -----------------------------
# Private Messaging
# -----------------------------
def private_message(sender, receiver, message):

    with lock:

        if receiver not in clients:
            return False

        try:
            clients[receiver].send(
                f"[PRIVATE] {sender}: {message}".encode()
            )
# Save private message 
            save_message(
                sender,
                receiver,
                "private",
                message
            )

            stats["private_messages"] += 1
            stats["total_messages"] += 1

            return True

        except:
            remove_client(receiver)
            return False


# -----------------------------
# Online User List
# -----------------------------
def send_user_list(client_socket):

    with lock:

        online_users = []

        for username, info in client_info.items():

            if info["status"] == "Online":
                online_users.append(username)

        response = "\n===== ONLINE USERS =====\n"

        if len(online_users) == 0:
            response += "No users online.\n"
        else:
            for user in online_users:
                response += f"- {user}\n"

        response += "========================\n"

        client_socket.send(response.encode())

def remove_client(username):
    """
    Remove disconnected client.
    """

    if username not in clients:
        return

    try:
        clients[username].close()
    except:
        pass

    del clients[username]
    
    # Remove from logged-in users
    logged_in_users.discard(username)

    if username in client_info:
        client_info[username]["status"] = "Offline"
    log_security_event(
        username,
        "DISCONNECTED"
    )
    print(f"[DISCONNECTED] {username}")
    broadcast(f"\n*** {username} left the chat ***\n")

    print_stats()


# -----------------------------
# Client Thread
# -----------------------------

def handle_client(client_socket, address):

    username = None

    try:

        client_socket.send("Enter username,password: ".encode())

        login_data = client_socket.recv(1024).decode().strip()

        username, password = login_data.split(",", 1)

# -------------------------------
# CHECK IF ACCOUNT IS BLOCKED
# -------------------------------
        current = time.time()

        if username in blocked_until:

            if current < blocked_until[username]:

                remaining = int(blocked_until[username] - current)
 
                log_security_event(
                   username,
                   "LOGIN ATTEMPT WHILE BLOCKED"
                )
                client_socket.send(
                    f"Account blocked. Try again in {remaining} seconds.".encode()
                )

                client_socket.close()
                return

        # Validate password length
        if password.strip() == "":

            client_socket.send(
                "Password cannot be empty.".encode()
            )

            client_socket.close()
            return

        if len(password) < 6:

            client_socket.send(
                "Password must be at least 6 characters.".encode()
            )

            client_socket.close()
            return

        if not valid_username(username):
            client_socket.send(
                "Invalid username.\n".encode()
            )

            client_socket.close()
            return

        users = load_users()

        if username not in users:

            client_socket.send(
                "User not found.\n".encode()
            )

            client_socket.close()
            return

        if users[username] != hash_password(password):
            # 1. Increase failed attempts
            failed_attempts[username] = failed_attempts.get(username, 0) + 1

            # 2. Check if maximum attempts reached
            if failed_attempts[username] >= MAX_ATTEMPTS:

               blocked_until[username] = time.time() + BLOCK_TIME

               log_security_event(
                   username,
                   "LOGIN BLOCKED"
               )
               client_socket.send(
                   "Too many failed attempts. Login blocked for 60 seconds.".encode()
               )

               client_socket.close()
               return

            # 3. If not blocked, tell the user how many attempts remain
            remaining = MAX_ATTEMPTS - failed_attempts[username]

            client_socket.send(
                f"Wrong password. {remaining} attempts remaining.".encode()
            )

            client_socket.close()
            return

            # Password is correct
        failed_attempts[username] = 0

        with lock:

            if username in logged_in_users:

                log_security_event(
                   username,
                   "DUPLICATE LOGIN BLOCKED"
                )

                client_socket.send(
                    "LOGIN_FAILED: User already logged in.".encode()
                )

                client_socket.close()
                return

            logged_in_users.add(username)

            if username in clients:

                client_socket.send(
                    "Username already exists.\n".encode()
                )

                client_socket.close()
                return

            clients[username] = client_socket

            client_info[username] = {
                "ip": address[0],
                "port": address[1],
                "login_time": current_time(),
                "last_activity": time.time(),
                "status": "Online"
            }

        print(f"[CONNECTED] {username} ({address[0]}:{address[1]})")
        log_security_event(
            username,
            "LOGIN SUCCESS"
        )

        broadcast(f"\n*** {username} joined the chat ***\n", username)

        print_stats()

        client_socket.send(
            "LOGIN_SUCCESS\nWelcome to TCP Chat Server!\n".encode()
        )
        client_socket.settimeout(1)

        history = load_last_messages(username)

        if history:

            client_socket.send(
                "\n===== Your Last 5 Messages =====\n".encode()
            )

            for row in history:

                line = (
                    f"{row['timestamp']} | "
                    f"{row['message_type']} | "
                    f"{row['receiver']} | "
                    f"{row['message']}\n"
                )

                client_socket.send(line.encode())

            client_socket.send(
                "===============================\n".encode()
            )

        while True:

            try:
                data = client_socket.recv(1024)

            except socket.timeout:

                if (
                    time.time()
                    - client_info[username]["last_activity"]
                ) > SESSION_TIMEOUT:

                    client_socket.send(
                        "Session expired due to inactivity.".encode()
                    )

                    log_security_event(
                        username,
                        "SESSION TIMEOUT"
                    )

                    break

                continue

            if not data:
                break 
            message = data.decode().strip()

            client_info[username]["last_activity"] = time.time()

            if len(message) > MAX_MESSAGE_LENGTH:

                client_socket.send(
                    "Message exceeds maximum length.".encode()
                )

                continue

            if message == "":
                continue

            # ----------------------------------
            # LIST COMMAND
            # ----------------------------------
            if message == "/list":
                send_user_list(client_socket)
                continue
            if message == "/logout":

                client_socket.send(
                    "Logging out...".encode()
                )

                log_security_event(
                    username,
                    "LOGOUT"
                )

                break

            # ----------------------------------
            # UNSUPPORTED COMMANDS
            # ----------------------------------
            if (
                message.startswith("/")
                and not message.startswith("/msg")
                and message not in ["/list", "/logout"]
            ):

                client_socket.send(
                    "Unsupported command.\n".encode()
                )

                log_security_event(
                    username,
                    "UNSUPPORTED COMMAND"
                )

                continue

            # ----------------------------------
            # PRIVATE MESSAGE
            # ----------------------------------
            if message.startswith("/msg "):

                parts = message.split(" ", 2)

                if len(parts) < 3:
                    client_socket.send(
                        "Usage: /msg <username> <message>\n".encode()
                    )
                    continue

                receiver = parts[1]
                private_text = parts[2]

                success = private_message(
                    username,
                    receiver,
                    private_text
                )

                if success:
                    client_socket.send(
                        f"[PRIVATE to {receiver}] {private_text}\n".encode()
                    )
                else:
                    client_socket.send(
                        "User not found.\n".encode()
                    )

                print_stats()
                continue

            # ----------------------------------
            # BROADCAST
            # ----------------------------------
            stats["broadcast_messages"] += 1
            stats["total_messages"] += 1

            print(f"[{username}] {message}")

            save_message(
                username,
                "ALL",
                "broadcast",
                message
            )
            start = time.perf_counter()

            broadcast(
                f"{username}: {message}",
                username
            )
            
            end = time.perf_counter()

            delay_ms = (end - start) * 1000

            performance["delivery_times"].append(delay_ms)
 
            print_stats()

    except Exception as e:
        print("Error:", e)

    finally:
        if username:
            remove_client(username)


# -----------------------------
# Main Server
# -----------------------------

def start_server():

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    server.bind((HOST, PORT))

    server.listen(10)

    print("=" * 50)
    print(" Advanced Multi-Client TCP Chat Server ")
    print("=" * 50)
    print(f"Listening on {HOST}:{PORT}")
    print("=" * 50)

    while True:

        client_socket, address = server.accept()

        thread = threading.Thread(
            target=handle_client,
            args=(client_socket, address),
            daemon=True
        )

        thread.start()


if __name__ == "__main__":
    start_server()
