import requests
import base64
import time
from datetime import datetime, timedelta
import json
import zeep

# YoAI API Key
YOAI_API_KEY = "01945bfb-0e2d-7a10-89ec-aed5b067359d:07e058c3375879e783f9b8aa3bc849af8de22267bceee7056c9795f98109fe8e"

# YoAI API Endpoints
GET_UPDATES_URL = "https://yoai.yophone.com/api/pub/getUpdates"
SEND_MESSAGE_URL = "https://yoai.yophone.com/api/pub/sendMessage"

# Headers for API requests
HEADERS = {
    "Content-Type": "application/json",
    "X-YoAI-API-Key": YOAI_API_KEY,
}

# In-memory storage for birthdays (could be replaced with a database in production)
birthdays = {}


def decode_base64(text):
    """
    Decodes a Base64-encoded string into plain text.
    """
    try:
        return base64.b64decode(text).decode("utf-8")
    except Exception as e:
        #print(f"Error decoding Base64 text: {e}")
        return text


def get_updates():
    """
    Fetches updates from YoAI.
    """
    try:
        response = requests.post(GET_UPDATES_URL, json={}, headers=HEADERS)
        if response.status_code == 200:
            updates = response.json()
            if updates.get("success") and updates.get("data"):
                return updates["data"]
            else:
                #print("No updates available.")
                return []
        elif response.status_code == 204:
            #print("No new updates (HTTP 204). Waiting for new messages...")
            return []
        else:
            #print(f"Failed to fetch updates. HTTP Status: {response.status_code}, Response: {response.text}")
            return []
    except Exception as e:
        #print(f"Error while fetching updates: {e}")
        return []


def send_message(chat_id, text):
    """
    Sends a message to a specific chat ID via YoAI.
    """
    payload = {"to": chat_id, "text": text}
    try:
        response = requests.post(SEND_MESSAGE_URL, json=payload, headers=HEADERS)
        if response.status_code == 200 and response.json().get("success"):
            #print(f"Message sent to {chat_id}: {text}")
        else:
            #print(f"Failed to send message to {chat_id}: {response.json()}")
    except Exception as e:
        #print(f"Error sending message: {e}")


def process_updates():
    """
    Processes updates by decoding messages and sending appropriate responses.
    """
    updates = get_updates()
    if not updates:
        #print("No updates to process.")
    for message in updates:
        chat_id = message.get("chatId")
        encoded_text = message.get("text", "")
        sender = message.get("sender", {})
        sender_name = f"{sender.get('firstName', '')} {sender.get('lastName', '')}".strip()

        # Decode the Base64 message text
        text = decode_base64(encoded_text)

        #print(f"Processing message: {text} from {sender_name} (Chat ID: {chat_id})")

        # Respond based on the message content
        if text.lower() == "/start":
            response_text = (
                f"Welcome, {sender_name}! 👋\n"
                "I am your Birthday Bot. Type 'help' for commands or send me a date for a special event."
            )
        elif text.lower() == "help":
            response_text = (
                "Available commands:\n"
                "- /start: Start the bot\n"
                "- add: Add a new birthday or special event\n"
                "- show: Show all upcoming birthdays and events\n"
                "- help: Show this help message"
            )
        elif text.lower() == "show":
            if birthdays:
                response_text = "Here are your upcoming events:\n"
                for name, date in birthdays.items():
                    response_text += f"{name}: {date}\n"
            else:
                response_text = "You haven't added any birthdays or events yet."
        elif text.lower().startswith("add "):
            # Extract name and date from the message
            try:
                parts = text[4:].split(" on ")
                name = parts[0].strip()
                date_str = parts[1].strip()
                date_obj = datetime.strptime(date_str, "%Y-%m-%d")
                birthdays[name] = date_obj.strftime("%Y-%m-%d")
                response_text = f"Added {name}'s birthday on {date_obj.strftime('%Y-%m-%d')}!"
            except Exception as e:
                response_text = "Failed to add the event. Please use the format: 'add <Name> on <YYYY-MM-DD>'"
        else:
            response_text = f"Sorry, I didn't understand that. You said: {text}"

        # Send the response back to the user
        send_message(chat_id, response_text)


def check_upcoming_birthdays():
    """
    Checks for upcoming birthdays or events and sends reminders.
    """
    today = datetime.now()
    for name, date_str in birthdays.items():
        birthday_date = datetime.strptime(date_str, "%Y-%m-%d")
        # Send reminder a week before the event
        if birthday_date - timedelta(days=7) <= today <= birthday_date:
            reminder_text = f"Reminder: {name}'s special day is coming up on {birthday_date.strftime('%Y-%m-%d')}!"
            send_message(chat_id, reminder_text)


if __name__ == "__main__":
    #print("BirthdayBot is running...")

    # Use polling to fetch updates
    while True:
        process_updates()
        check_upcoming_birthdays()
        time.sleep(5)
