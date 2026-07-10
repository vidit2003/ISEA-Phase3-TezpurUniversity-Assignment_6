import csv
import os
import time
import socket
import threading
from datetime import datetime

HOST = "0.0.0.0"
PORT = 5000

# -----------------------------
# Server Data
# -----------------------------

clients = {}          # username -> socket
client_info = {}      # username -> details
lock = threading.Lock()

CHAT_HISTORY = "chat_history.csv"

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

def current_time():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

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

    if username in client_info:
        client_info[username]["status"] = "Offline"

    print(f"[DISCONNECTED] {username}")

    broadcast(f"\n*** {username} left the chat ***\n")

    print_stats()


# -----------------------------
# Client Thread
# -----------------------------

def handle_client(client_socket, address):

    username = None

    try:

        client_socket.send("Enter username: ".encode())

        username = client_socket.recv(1024).decode().strip()

        if username == "":
            client_socket.close()
            return

        with lock:

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
                "status": "Online"
            }

        print(f"[CONNECTED] {username} ({address[0]}:{address[1]})")

        broadcast(f"\n*** {username} joined the chat ***\n", username)

        print_stats()

        client_socket.send(
            "\nWelcome to TCP Chat Server!\n".encode()
        )

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

            data = client_socket.recv(1024)

            if not data:
                break 
            message = data.decode().strip()

            if message == "":
                continue

            # ----------------------------------
            # LIST COMMAND
            # ----------------------------------
            if message == "/list":
                send_user_list(client_socket)
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
