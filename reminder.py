import requests # type: ignore
import base64
import time
from datetime import datetime, timedelta
import json

# YoAI API Key
YOAI_API_KEY = "019460fa-68fa-7efb-b4cf-bc838f2ed6a7:81009105a93be4bbc8e740745b78b1a429513da24115f0fc3669489548f4458c"

# YoAI API Endpoints
GET_UPDATES_URL = "https://yoai.yophone.com/api/pub/getUpdates"
SEND_MESSAGE_URL = "https://yoai.yophone.com/api/pub/sendMessage"
SET_WEBHOOK_URL = "https://yoai.yophone.com/api/pub/setWebhook"

# Headers for API requests
HEADERS = {
    "Content-Type": "application/json",
    "X-YoAI-API-Key": YOAI_API_KEY,
}

# ----- Data structures -----
# Store user states to manage conversation flow
# Possible states:
#   0 - Just started; waiting for /start
#   1 - Time zone not set (awaiting user to provide time zone)
#   2 - Time zone set; ready to receive messages to remind about
#   3 - Received a message to remind about, waiting for date/time
#   4 - Received date/time, waiting for reminder option
# (After scheduling, user returns to state 2)
user_states = {}

# Store user time zones: chat_id -> (offset_hours, "Name or region")
#   Example: +4 Armenia -> (4, "Armenia")
user_timezones = {}

# Temporary storage while we await user responses:
#   reminder_text: text of the forwarded message the user wants to be reminded about
#   reminder_datetime: the datetime the user wants to be reminded
#   warning_issued: whether we have already issued a 1-minute warning
#   time_prompt_timestamp: when we asked for date/time, to check the 1-minute timeout
#   option_prompt_timestamp: when we asked for the reminder option
user_temp_data = {}

# Reminders structure:
#  We'll store each reminder as a dictionary:
#  {
#    "chat_id": ...,
#    "reminder_text": ...,
#    "reminder_time": ... (the exact time at which the final reminder should go off, in UTC or local),
#    "option": ... (which option 1-4, or default)
#  }
# We'll poll these and send messages at the appropriate times.
reminders = []


# ----- Helper Functions -----
def decode_base64(text):
    """Decode Base64-encoded string."""
    try:
        return base64.b64decode(text).decode("utf-8")
    except Exception as e:
        # print(f"Error decoding Base64 text: {e}")
        return text


def send_message(chat_id, text):
    """Send a text message to the specified chat_id."""
    payload = {"to": chat_id, "text": text}
    try:
        response = requests.post(SEND_MESSAGE_URL, json=payload, headers=HEADERS)
        # if response.status_code == 200 and response.json().get("success"):
        #     # print(f"Message sent to {chat_id}: {text}")
        # else:
        #     # print(f"Failed to send message to {chat_id}: {response.json()}")
    except Exception as e:
        print(f"Error sending message: {e}")


def get_updates():
    """Fetch new updates from YoAI."""
    try:
        response = requests.post(GET_UPDATES_URL, json={}, headers=HEADERS)
        if response.status_code == 200:
            updates = response.json()
            if updates.get("success") and updates.get("data"):
                return updates["data"]
            else:
                # No new data in the response
                return []
        elif response.status_code == 204:
            # No content
            return []
        else:
            # print(f"Failed to fetch updates. HTTP Status: {response.status_code}, Response: {response.text}")
            return []
    except Exception as e:
        # print(f"Error while fetching updates: {e}")
        return []


def parse_timezone(text):
    """
    Attempt to parse a time zone in the format '+4', '-3', etc.
    Possibly with a region or name after it (e.g., '+4 Armenia').
    Returns (offset_int, region_string) or None if invalid.
    """
    parts = text.split(maxsplit=1)
    tz_part = parts[0].strip()  # e.g. "+4" or "-3"
    region = parts[1].strip() if len(parts) > 1 else ""  # e.g. "Armenia"

    # Validate that tz_part starts with '+' or '-' followed by digits
    if (tz_part.startswith('+') or tz_part.startswith('-')) and tz_part[1:].isdigit():
        try:
            offset = int(tz_part)
            return offset, region
        except ValueError:
            return None
    else:
        return None


def parse_datetime(text):
    """
    Parse a date/time in the format 'YYYY-MM-DD HH:MM'.
    Returns a datetime object or None if invalid.
    """
    try:
        dt = datetime.strptime(text.strip(), "%Y-%m-%d %H:%M")
        return dt
    except ValueError:
        return None


def process_updates():
    """Main update processor—handles the conversation logic and state transitions."""
    global user_states, user_timezones, user_temp_data, reminders

    updates = get_updates()
    if not updates:
        return

    for message in updates:
        chat_id = message.get("chatId")
        encoded_text = message.get("text", "")
        text = decode_base64(encoded_text).strip()
        sender = message.get("sender", {})
        sender_name = (f"{sender.get('firstName', '')} {sender.get('lastName', '')}").strip()

        # Make sure we have a default state for this user
        if chat_id not in user_states:
            user_states[chat_id] = 0

        current_state = user_states[chat_id]

        # print(f"Received from {sender_name} (chat {chat_id}), state={current_state}: {text}")

        # -------------------- STATE MACHINE --------------------
        if text.lower() == "/start":
            # Greet the user, explain how the bot works, ask for time zone
            user_states[chat_id] = 1  # Next: ask for time zone
            send_message(
                chat_id,
                (
                    f"Hello, {sender_name}! I'm your Reminder Bot.\n"
                    "Here's how I work:\n"
                    "1. First, please provide your time zone in the format '+4 Armenia' (for example).\n"
                    "2. Once the time zone is set, just forward me any message you want to be reminded of.\n"
                    "3. I'll ask you when you want to be reminded (in the format YYYY-MM-DD HH:MM).\n"
                    "4. You'll then select one of these reminder options:\n"
                    "   1) 9:00 AM on the same day\n"
                    "   2) 3 hours before\n"
                    "   3) 1 hour before\n"
                    "   4) Exactly at the specified time\n"
                    "   (Default is 15 minutes before if you don't choose anything.)\n"
                    "Let's get started—please send me your time zone!"
                )
            )
            continue

        # If we haven't set time zone yet, or are waiting to set it
        if current_state == 1:
            # User is supposed to send time zone info
            tz_parsed = parse_timezone(text)
            if tz_parsed is None:
                send_message(chat_id, "Invalid time zone format. Please try again (e.g. '+4 Armenia').")
            else:
                offset, region = tz_parsed
                user_timezones[chat_id] = (offset, region)
                user_states[chat_id] = 2
                send_message(
                    chat_id,
                    f"Time zone successfully set to {offset} {region}.\n"
                    "Everything is ready! Now, just forward a message you want to be reminded about."
                )
            continue

        # State 2: Time zone set, user can forward a message to remind about
        if current_state == 2:
            # The user can forward any text (the message they'd like a reminder for)
            # We'll store it, then ask for the date/time
            user_temp_data[chat_id] = {
                "reminder_text": text,
                "reminder_datetime": None,
                "warning_issued": False,
                "time_prompt_timestamp": datetime.now(),
                "option_prompt_timestamp": None,
            }
            user_states[chat_id] = 3

            send_message(
                chat_id,
                "When should I remind you? Please specify in YYYY-MM-DD HH:MM format."
            )
            continue

        # State 3: We have the reminder text, waiting for user to provide date/time
        if current_state == 3:
            dt = parse_datetime(text)
            if dt is None:
                # Could be an invalid format or user might be ignoring the request
                # Check if they typed something else. We'll just ask them again:
                send_message(chat_id, "I couldn't understand the date/time. Please use 'YYYY-MM-DD HH:MM'.")
            else:
                # We have a valid datetime. Store it and move on to reminder option.
                user_temp_data[chat_id]["reminder_datetime"] = dt
                user_temp_data[chat_id]["option_prompt_timestamp"] = datetime.now()
                user_states[chat_id] = 4
                send_message(
                    chat_id,
                    (
                        "Great! Now, choose a reminder option:\n"
                        "1) Remind at 9:00 AM on the same day\n"
                        "2) 3 hours before\n"
                        "3) 1 hour before\n"
                        "4) Exactly at the specified time\n"
                        "(If you do not select any option, I'll remind you 15 minutes before by default.)"
                    )
                )
            continue

        # State 4: We have the text and date/time, waiting for user to choose reminder option
        if current_state == 4:
            # Strip out spaces from the beginning/end of the number
            chosen_option = text.strip()
            # If user typed nothing or typed something that isn't 1-4, handle
            if chosen_option in ["1", "2", "3", "4"]:
                # Valid option
                chosen_option = int(chosen_option)
            else:
                # Maybe there's extra spaces or something else (like " 4")
                # Let's filter out non-digit characters or handle partial
                numeric_part = "".join([ch for ch in chosen_option if ch.isdigit()])
                if numeric_part in ["1", "2", "3", "4"]:
                    chosen_option = int(numeric_part)
                elif chosen_option == "":
                    # If truly empty, treat it as no selection => default
                    chosen_option = 0  # We'll treat 0 as "no selection"
                else:
                    # Check if user typed something that can't parse
                    if numeric_part == "":
                        # If there's no digit at all, treat as invalid
                        send_message(chat_id, "That option doesn't exist. Please choose 1, 2, 3, or 4.")
                        continue
                    else:
                        # If numeric_part is something else, also invalid
                        if numeric_part not in ["1", "2", "3", "4"]:
                            send_message(chat_id, "That option doesn't exist. Please choose 1, 2, 3, or 4.")
                            continue
                        else:
                            chosen_option = int(numeric_part)

            # Now we have a valid chosen_option (possibly 0 for default)
            # Schedule the reminder
            reminder_text = user_temp_data[chat_id]["reminder_text"]
            reminder_datetime = user_temp_data[chat_id]["reminder_datetime"]
            (offset, region) = user_timezones[chat_id]

            # Convert user local time to a "server reference" time if needed
            # For simplicity, assume server's local time is UTC or a known reference.
            # We'll treat the user's specified time as local and convert it to UTC by subtracting the offset:
            # UTC = user_local_time - offset (in hours)
            # e.g. if offset=+4 and user says 2025-01-01 10:00 local, that's 2025-01-01 06:00 UTC
            user_local = reminder_datetime
            # Convert to UTC:
            reminder_utc = user_local - timedelta(hours=offset)

            # Next, figure out final "send" time based on the option.
            # We'll store *all* relevant times (like "9:00 same day", etc.) in a schedule.
            # But the user specifically wants one single time for the final reminder. We'll handle each option:
            if chosen_option == 1:
                # Remind at 9:00 AM on the same day (local time).
                # We'll create a new datetime with the same date, but hour=9, minute=0 (user local).
                remind_local = user_local.replace(hour=9, minute=0, second=0)
                # Convert that to UTC
                final_utc = remind_local - timedelta(hours=offset)
                option_msg = "I will remind you at 9:00 AM on the same day."
            elif chosen_option == 2:
                # 3 hours before
                final_utc = reminder_utc - timedelta(hours=3)
                option_msg = "I will remind you 3 hours before the specified time."
            elif chosen_option == 3:
                # 1 hour before
                final_utc = reminder_utc - timedelta(hours=1)
                option_msg = "I will remind you 1 hour before the specified time."
            elif chosen_option == 4:
                # Exactly at the specified time
                final_utc = reminder_utc
                option_msg = "I will remind you exactly at the specified time."
            else:
                # Default: 15 minutes before
                final_utc = reminder_utc - timedelta(minutes=15)
                option_msg = "I will remind you 15 minutes before the specified time (default)."

            # Store the reminder
            reminders.append({
                "chat_id": chat_id,
                "reminder_text": reminder_text,
                "final_utc": final_utc,  # when we actually send the reminder
                "original_local": user_local,  # just for reference if needed
                "option_chosen": chosen_option
            })

            # Notify the user
            send_message(
                chat_id,
                f"Your reminder is set! {option_msg}\n\n"
                f"You want to be reminded about:\n\"{reminder_text}\"\n"
                f"at local time: {user_local.strftime('%Y-%m-%d %H:%M')} (UTC offset {offset})."
            )

            # Reset user state to time zone set / ready to accept new messages
            user_states[chat_id] = 2
            continue

        # If user is in any other state, or message is not recognized, do nothing special
        else:
            # Possibly check timeouts or warnings here
            pass


def check_timeouts():
    """
    Check if user has not provided the required input (date/time or option) within 1 minute.
    If so, send a warning or reset the conversation if they've already been warned.
    """
    for chat_id, state in user_states.items():
        if state == 3:
            # waiting for date/time
            data = user_temp_data.get(chat_id)
            if data:
                prompt_time = data.get("time_prompt_timestamp")
                if prompt_time:
                    elapsed = (datetime.now() - prompt_time).total_seconds()
                    if elapsed > 60:
                        # Over a minute has passed
                        if not data["warning_issued"]:
                            # Issue warning
                            send_message(
                                chat_id,
                                "You haven't provided a date/time within 1 minute. Please respond soon, or send a new message."
                            )
                            data["warning_issued"] = True
                        else:
                            # They have already been warned; reset conversation
                            send_message(chat_id, "No date/time received. I'll wait for a new message.")
                            user_states[chat_id] = 2
                            # Clear temp data for this chat
                            user_temp_data.pop(chat_id, None)

        elif state == 4:
            # waiting for reminder option
            data = user_temp_data.get(chat_id)
            if data:
                prompt_time = data.get("option_prompt_timestamp")
                if prompt_time:
                    elapsed = (datetime.now() - prompt_time).total_seconds()
                    if elapsed > 60:
                        # Over a minute has passed, no option chosen => default
                        reminder_text = data["reminder_text"]
                        reminder_datetime = data["reminder_datetime"]
                        (offset, region) = user_timezones[chat_id]

                        # Convert user local time to UTC
                        user_local = reminder_datetime
                        reminder_utc = user_local - timedelta(hours=offset)
                        # Default = 15 min before
                        final_utc = reminder_utc - timedelta(minutes=15)

                        reminders.append({
                            "chat_id": chat_id,
                            "reminder_text": reminder_text,
                            "final_utc": final_utc,
                            "original_local": user_local,
                            "option_chosen": 0  # indicates default
                        })

                        send_message(
                            chat_id,
                            f"You did not choose a reminder option. Defaulting to 15 minutes before.\n"
                            f"Your reminder has been set for \"{reminder_text}\" at local time: "
                            f"{user_local.strftime('%Y-%m-%d %H:%M')} (offset {offset})."
                        )

                        # Reset user state
                        user_states[chat_id] = 2
                        user_temp_data.pop(chat_id, None)


def send_reminders():
    """
    Periodically check if it's time to send any reminders.
    We'll compare the current UTC time to each reminder's final_utc.
    If it's time, we send the reminder and remove it.
    """
    global reminders
    now_utc = datetime.utcnow()
    if not reminders:
        return

    # We'll work on a copy to safely remove from the original
    for r in reminders[:]:
        final_utc = r["final_utc"]
        if now_utc >= final_utc:
            # Time to remind
            chat_id = r["chat_id"]
            reminder_text = r["reminder_text"]
            send_message(chat_id, f"⏰ Reminder! Don't forget:\n\n{reminder_text}")
            reminders.remove(r)


def set_webhook(webhook_url):
    """Set a webhook for the bot (optional if you're using polling)."""
    try:
        payload = {"webhookURL": webhook_url}
        response = requests.post(SET_WEBHOOK_URL, json=payload, headers=HEADERS)

        if response.status_code == 200:
            response_data = response.json()
            if response_data.get("success"):
                # print("Webhook set successfully.")
                return True
            else:
                # print(f"Failed to set webhook. Response: {response_data}")
                return False
        else:
            # print(f"HTTP Error: {response.status_code}, Response: {response.text}")
            return False
    except Exception as e:
        # print(f"Error while setting webhook: {e}")
        return False


if __name__ == "__main__":
    # print("Reminder Bot is running...")

    # Use a simple polling mechanism
    while True:
        process_updates()   # Process incoming messages and update states
        check_timeouts()    # Check if we should warn the user or reset
        send_reminders()    # Send any reminders that are due
        time.sleep(5)       # Poll interval (adjust as needed)
