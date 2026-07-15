import queue
import socket
import threading
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk

SERVER_PORT = 5000
RECV_BUFFER = 4096


class ChatClientGUI:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("TCP Chat Client")
        self.root.geometry("760x500")
        self.root.minsize(700, 460)

        self.client_socket: socket.socket | None = None
        self.receiver_thread: threading.Thread | None = None
        self.running = False
        self.connected = False

        self.incoming_queue: queue.Queue[str] = queue.Queue()
        self.online_users: set[str] = set()

        self.server_ip_var = tk.StringVar(value="10.0.0.1")
        self.username_var = tk.StringVar()
        self.password_var = tk.StringVar()  # Optional field; not sent to server.
        self.message_var = tk.StringVar()
        self.private_to_var = tk.StringVar(value="Broadcast")
        self.status_var = tk.StringVar(value="Not connected")
        self.connection_var = tk.StringVar(value="Disconnected")

        self.login_frame = None
        self.chat_frame = None
        self.chat_display = None
        self.users_listbox = None
        self.message_entry = None
        self.send_button = None
        self.disconnect_button = None
        self.private_combo = None

        self._build_login_ui()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.after(100, self._process_queue)

    # ------------------------- UI BUILDERS -------------------------

    def _build_login_ui(self) -> None:
        self.login_frame = ttk.Frame(self.root, padding=20)
        self.login_frame.pack(fill="both", expand=True)

        title = ttk.Label(
            self.login_frame,
            text="TCP Chat Login",
            font=("Arial", 18, "bold"),
        )
        title.pack(pady=(0, 18))

        form = ttk.Frame(self.login_frame)
        form.pack(fill="x", expand=False)

        ttk.Label(form, text="Server IP:").grid(row=0, column=0, sticky="w", pady=6)
        ttk.Entry(form, textvariable=self.server_ip_var, width=28).grid(
            row=0, column=1, sticky="ew", pady=6
        )

        ttk.Label(form, text="Username:").grid(row=1, column=0, sticky="w", pady=6)
        ttk.Entry(form, textvariable=self.username_var, width=28).grid(
            row=1, column=1, sticky="ew", pady=6
        )

        ttk.Label(form, text="Password:").grid(
            row=2, column=0, sticky="w", pady=6
        )
        ttk.Entry(form, textvariable=self.password_var, show="*", width=28).grid(
            row=2, column=1, sticky="ew", pady=6
        )

        form.columnconfigure(1, weight=1)

        button_row = ttk.Frame(self.login_frame)
        button_row.pack(pady=18)

        ttk.Button(button_row, text="Connect", command=self.connect_to_server).pack(
            side="left", padx=6
        )
        ttk.Button(button_row, text="Exit", command=self.on_close).pack(
            side="left", padx=6
        )

        ttk.Label(
            self.login_frame,
            textvariable=self.status_var,
            foreground="#444",
        ).pack(pady=(10, 0))

        self.root.bind("<Return>", lambda _e: self.connect_to_server())

    def _build_chat_ui(self) -> None:
        self.chat_frame = ttk.Frame(self.root, padding=10)
        self.chat_frame.pack(fill="both", expand=True)

        header = ttk.Frame(self.chat_frame)
        header.pack(fill="x", pady=(0, 8))

        ttk.Label(
            header,
            text="TCP Chat Application",
            font=("Arial", 16, "bold"),
        ).pack(side="left")

        ttk.Label(
            header,
            textvariable=self.connection_var,
            font=("Arial", 10, "bold"),
        ).pack(side="right")

        main = ttk.Frame(self.chat_frame)
        main.pack(fill="both", expand=True)

        left = ttk.Frame(main)
        left.pack(side="left", fill="both", expand=True, padx=(0, 8))

        right = ttk.Frame(main, width=220)
        right.pack(side="right", fill="y")

        # Chat display
        ttk.Label(left, text="Messages").pack(anchor="w")
        self.chat_display = scrolledtext.ScrolledText(
            left,
            wrap=tk.WORD,
            height=20,
            state="disabled",
            font=("Consolas", 10),
        )
        self.chat_display.pack(fill="both", expand=True, pady=(4, 10))

        # Message compose area
        compose = ttk.Frame(left)
        compose.pack(fill="x", pady=(0, 8))

        ttk.Label(compose, text="Recipient:").grid(row=0, column=0, sticky="w")
        self.private_combo = ttk.Combobox(
            compose,
            textvariable=self.private_to_var,
            values=["Broadcast"],
            state="readonly",
            width=20,
        )
        self.private_combo.grid(row=0, column=1, sticky="w", padx=(6, 14))
        self.private_combo.bind("<<ComboboxSelected>>", self._recipient_selected)

        ttk.Label(compose, text="Message:").grid(row=1, column=0, sticky="w", pady=(10, 0))
        self.message_entry = ttk.Entry(compose, textvariable=self.message_var)
        self.message_entry.grid(row=1, column=1, sticky="ew", padx=(6, 8), pady=(10, 0))

        self.send_button = ttk.Button(compose, text="Send", command=self.send_message)
        self.send_button.grid(row=1, column=2, sticky="e", pady=(10, 0))

        compose.columnconfigure(1, weight=1)

        # Right panel: online users
        ttk.Label(right, text="Online Users").pack(anchor="w")
        self.users_listbox = tk.Listbox(right, height=18)
        self.users_listbox.pack(fill="both", expand=True, pady=(4, 8))
        self.users_listbox.bind("<<ListboxSelect>>", self._on_user_select)

        ttk.Button(right, text="Refresh Users", command=self.request_user_list).pack(
            fill="x", pady=(0, 8)
        )
        self.disconnect_button = ttk.Button(
            right, text="Disconnect", command=self.disconnect
        )
        self.disconnect_button.pack(fill="x")

        status_bar = ttk.Frame(self.chat_frame)
        status_bar.pack(fill="x", pady=(8, 0))

        ttk.Label(status_bar, text="Status:").pack(side="left")
        ttk.Label(status_bar, textvariable=self.status_var).pack(side="left", padx=(6, 0))

        self.message_entry.focus_set()
        self.root.bind("<Return>", lambda _e: self.send_message())
        self.root.bind("<Escape>", lambda _e: self.disconnect())

    # ------------------------- CONNECTION -------------------------

    def connect_to_server(self) -> None:
        if self.connected:
            return

        server_ip = self.server_ip_var.get().strip()
        username = self.username_var.get().strip()

        if not server_ip:
            messagebox.showerror("Input Error", "Please enter a server IP address.")
            return

        if not username:
            messagebox.showerror("Input Error", "Username cannot be empty.")
            return

        self.status_var.set("Connecting...")
        self.root.update_idletasks()

        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.connect((server_ip, SERVER_PORT))
            sock.settimeout(0.5)
            self.client_socket = sock
        except Exception as exc:
            self.client_socket = None
            self.status_var.set("Disconnected")
            messagebox.showerror("Connection Failed", f"Unable to connect:\n{exc}")
            return

        # Receive server username prompt.
        try:
            prompt = self.client_socket.recv(RECV_BUFFER).decode(errors="ignore")
            if prompt:
                self._append_message(prompt.rstrip())
        except Exception:
            pass

        try:
            password = self.password_var.get()
            login_data = f"{username},{password}"
            self.client_socket.send(login_data.encode())
        except Exception as exc:
            messagebox.showerror("Login Failed", f"Could not send username:\n{exc}")
            self._safe_close_socket()
            return

        # Wait for authentication response from server
        try:
            response = self.client_socket.recv(RECV_BUFFER).decode(errors="ignore").strip()
        except Exception as exc:
            messagebox.showerror("Login Failed", str(exc))
            self._safe_close_socket()
            return

        # Login failed
        if (
            "Wrong password" in response
            or "User not found" in response
            or "Password must" in response
            or "Password cannot" in response
            or "Invalid username" in response
            or "LOGIN_FAILED" in response
            or "Account blocked" in response
            or "Too many failed attempts" in response
        ):
            messagebox.showerror("Login Failed", response)
            self._safe_close_socket()
            self.status_var.set("Disconnected")
            return

        # Login successful
        self.connected = True
        self.running = True

        self.status_var.set(f"Connected as {username}")
        self.connection_var.set("Connected")

        self._swap_to_chat_ui()

        # Show welcome message
        if response:
            self._append_message(response)

        self.receiver_thread = threading.Thread(
            target=self._receive_loop,
            daemon=True,
        )
        self.receiver_thread.start()

        self.root.after(400, self.request_user_list)

        messagebox.showinfo(
            "Success",
            f"Connected as {username}"
        )

    def _swap_to_chat_ui(self) -> None:
        if self.login_frame is not None:
            self.login_frame.destroy()
            self.login_frame = None

        self._build_chat_ui()

    # ------------------------- RECEIVER -------------------------

    def _receive_loop(self) -> None:
        while self.running and self.client_socket is not None:
            try:
                data = self.client_socket.recv(RECV_BUFFER)
                if not data:
                    self.incoming_queue.put("__DISCONNECTED__")
                    break

                message = data.decode(errors="ignore")
                if message:
                    self.incoming_queue.put(message)
            except socket.timeout:
                continue
            except OSError:
                break
            except Exception as exc:
                self.incoming_queue.put(f"[System] Receive error: {exc}")
                break

        self.incoming_queue.put("__DISCONNECTED__")

    def _process_queue(self) -> None:
        try:
            while True:
                item = self.incoming_queue.get_nowait()
                if item == "__DISCONNECTED__":
                    if self.connected:
                        self._handle_remote_disconnect()
                    continue
                self._handle_incoming_message(item)
        except queue.Empty:
            pass

        self.root.after(100, self._process_queue)

    # ------------------------- MESSAGE HANDLING -------------------------

    def _handle_incoming_message(self, raw_message: str) -> None:
        text = raw_message.replace("\r", "")
        stripped = text.strip()

        if not stripped:
            return

        # Online user list parsing
        if "ONLINE USERS" in text:
            self._parse_user_list(text)
            self._append_message(text.rstrip())
            return

        # Join/leave notifications: keep local user list in sync.
        if "joined the chat" in stripped:
            username = self._extract_username_from_notification(stripped, "joined the chat")
            if username:
                self.online_users.add(username)
                self._refresh_user_widgets()
                self._append_message(stripped)
                return

        if "left the chat" in stripped:
            username = self._extract_username_from_notification(stripped, "left the chat")
            if username and username in self.online_users:
                self.online_users.discard(username)
                self._refresh_user_widgets()
            self._append_message(stripped)
            return

        # Server messages
        self._append_message(stripped)

    def _parse_user_list(self, text: str) -> None:
        users: set[str] = set()

        for line in text.splitlines():
            line = line.strip()
            if line.startswith("- "):
                users.add(line[2:].strip())

        if users:
            self.online_users = users
            self._refresh_user_widgets()

    @staticmethod
    def _extract_username_from_notification(message: str, phrase: str) -> str | None:
        prefix = "*** "
        suffix = f" {phrase} ***"
        if message.startswith(prefix) and message.endswith(suffix):
            return message[len(prefix) : -len(suffix)].strip()
        return None

    def _append_message(self, message: str) -> None:
        if self.chat_display is None:
            return

        self.chat_display.configure(state="normal")
        self.chat_display.insert(tk.END, message + "\n")
        self.chat_display.see(tk.END)
        self.chat_display.configure(state="disabled")

    # ------------------------- SENDING -------------------------

    def send_message(self) -> None:
        if not self.connected or self.client_socket is None:
            messagebox.showwarning("Not Connected", "Please connect to the server first.")
            return

        message = self.message_var.get().strip()
        recipient = self.private_to_var.get().strip()

        if not message:
            return

        if recipient and recipient != "Broadcast":
            payload = f"/msg {recipient} {message}"
        else:
            payload = message

        try:
            self.client_socket.send(payload.encode())
            self.message_var.set("")
            self.message_entry.focus_set()
        except Exception as exc:
            messagebox.showerror("Send Failed", f"Could not send message:\n{exc}")
            self.disconnect()

    def request_user_list(self) -> None:
        if not self.connected or self.client_socket is None:
            return
        try:
            self.client_socket.send("/list".encode())
        except Exception:
            pass

    # ------------------------- USER LIST / RECIPIENT -------------------------

    def _refresh_user_widgets(self) -> None:
        if self.users_listbox is not None:
            self.users_listbox.delete(0, tk.END)
            for user in sorted(self.online_users):
                self.users_listbox.insert(tk.END, user)

        if self.private_combo is not None:
            values = ["Broadcast"] + sorted(self.online_users)
            self.private_combo["values"] = values

            current = self.private_to_var.get().strip()
            if current != "Broadcast" and current not in self.online_users:
                self.private_to_var.set("Broadcast")

    def _on_user_select(self, _event=None) -> None:
        if self.users_listbox is None:
            return
        selection = self.users_listbox.curselection()
        if not selection:
            return
        username = self.users_listbox.get(selection[0])
        self.private_to_var.set(username)

    def _recipient_selected(self, _event=None) -> None:
        # Keep selection in sync. No extra logic needed.
        pass

    # ------------------------- DISCONNECT / CLOSE -------------------------

    def disconnect(self) -> None:
        if not self.connected:
            self.on_close()
            return

        self.running = False
        self.connected = False
        self.status_var.set("Disconnecting...")

        self._safe_close_socket()

        self.connection_var.set("Disconnected")
        self.status_var.set("Disconnected")

        if self.chat_frame is not None:
            self.chat_frame.destroy()
            self.chat_frame = None

        self.online_users.clear()

        # Return to login screen for reconnection.
        self._build_login_ui()
        messagebox.showinfo("Disconnected", "You have been disconnected.")

    def _handle_remote_disconnect(self) -> None:
        self.running = False
        self.connected = False
        self._safe_close_socket()
        self.connection_var.set("Disconnected")
        self.status_var.set("Server disconnected")

        if self.chat_frame is not None:
            self.chat_frame.destroy()
            self.chat_frame = None

        self.online_users.clear()
        self._build_login_ui()
        messagebox.showwarning("Disconnected", "Connection closed by server.")

    def _safe_close_socket(self) -> None:
        sock = self.client_socket
        self.client_socket = None
        if sock is None:
            return
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except Exception:
            pass
        try:
            sock.close()
        except Exception:
            pass

    def on_close(self) -> None:
        self.running = False
        self.connected = False
        self._safe_close_socket()
        self.root.destroy()

    # ------------------------- RUN -------------------------

    def run(self) -> None:
        self.root.mainloop()


if __name__ == "__main__":
    ChatClientGUI().run()
